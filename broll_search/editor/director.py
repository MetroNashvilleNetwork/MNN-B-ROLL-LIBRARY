"""AI creative director: compose an edit by having a model watch clip proxies.

The model-specific call lives behind the DirectorClient interface; everything in
this module (prompt, schema, parsing) is pure and unit-tested with a fake client."""

from __future__ import annotations

import math
import os
import statistics
from dataclasses import dataclass
from typing import List, Sequence

from . import analysis
from .edl import Clip, EDL
from .music import MusicInfo
from .profiles import profile_for


@dataclass
class DirectorCandidate:
    index: int
    path: str
    proxy_path: str
    duration: float
    fps: float
    score: float
    subject_x: float = 0.5
    # 7a — measured exposure fields (pipeline copies from ClipScout)
    exp_mean: float = 112.0
    exp_highlight_clip: float = 0.0
    # 7a — measured motion fields (pipeline copies from ClipScout)
    motion_type: str = "static"
    motion_in: float = 0.0
    motion_out: float = 0.0
    motion_strength: float = 0.0


# JSON schema the model fills via structured output.
# 7c — shape is unchanged (clip_index,in,out,role,subject_x,stabilize,retime,reason).
# Exposure/push fields are NOT in the schema — they are deterministic post-pass only.
EDL_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "timeline": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clip_index": {"type": "integer"},
                    "in": {"type": "number"},
                    "out": {"type": "number"},
                    "role": {"type": "string", "enum": ["hook", "body", "closer"]},
                    "subject_x": {"type": "number"},
                    "stabilize": {"type": "boolean"},
                    "retime": {"type": "string", "enum": ["normal", "slowmo"]},
                    "reason": {"type": "string"},
                },
                "required": ["clip_index", "in", "out", "role"],
            },
        },
    },
    "required": ["timeline"],
}


def _candidate_manifest(candidates: Sequence[DirectorCandidate]) -> str:
    """7b — surface motion info so the model anchors in/out inside real-move spans."""
    lines = []
    for c in candidates:
        lines.append(
            f"Clip {c.index}: file={os.path.basename(c.path)} duration={c.duration:.1f}s "
            f"fps={c.fps:.0f} quality={c.score:.0f} subject_x={c.subject_x:.2f} "
            f"motion={c.motion_type}[{c.motion_in:.1f}-{c.motion_out:.1f}] "
            f"move={c.motion_strength:.0f}")
    return "\n".join(lines)


def build_director_prompt(theme: str, candidates: Sequence[DirectorCandidate],
                          music: MusicInfo, target_total: float = 28.0) -> str:
    """7d — cinematic direction: premium + SMOOTH, one-motion, mostly-slowmo."""
    n_shots = max(6, round(target_total / 1.2))
    slowmo_cap = math.ceil(n_shots * 0.4)
    bpm = round(music.tempo)
    beat = round(60.0 / bpm, 2) if bpm else 0
    return f"""You are a senior video editor cutting a {target_total:.0f}-second vertical (9:16) social recap on the theme "{theme}" in the house style of Metro Nashville Network. Cut a premium, cinematic, SMOOTH edit. Cuts may be fast but NOTHING may look shaky or chaotic — every shot must read as one clean, intentional camera move.

You are shown {len(candidates)} b-roll proxy clips (low-res previews), in this manifest order:
{_candidate_manifest(candidates)}

Music: ~{bpm} BPM (one beat ~= {beat}s), {music.duration:.0f}s long.

STRUCTURE / ARC — follow this exactly:
1. OPEN on 1-2 CLOSE DETAIL or PROP macro shots (a branded object, award, sign, hands) held longer (~3s, then ~2.5s). Do NOT open on a person or a wide.
2. First HUMAN moment — a candid reaction (~1.3s).
3. ESTABLISHING WIDE (~0.9s) to set the scene.
4. BUILD and ACCELERATE — alternate people, reactions, details, action; shots get progressively SHORTER toward the end (start ~2s, finish ~0.4–0.6s rapid-fire). Anticipate each beat: land the cut 1–2 frames BEFORE it.
5. CLOSE on a longer WIDE group/hero hold (~2.5–3s) that breathes.

ONE MOTION PER CLIP (selection rule):
Each clip is tagged with a detected `motion`. When a clip has a real move (pan/tilt/push_in/pull_back), set your `in`/`out` INSIDE its [motion_in–motion_out] span so the cut contains that single clean move. For `static` clips pick the sharpest moment; a gentle push-in is added automatically. NEVER select a span that contains two different moves. NEVER pick a `complex` clip for slow-mo unless you also set stabilize=true.

AGGRESSIVE STABILIZE:
Set stabilize=true for ANY handheld or `complex` clip — err strongly toward stabilizing. The viewer's #1 complaint is shaky footage; smoothness beats everything.

MOSTLY SLOW-MO:
Default retime=slowmo on clips with a clean directional move (pan/tilt/push_in/pull_back) and on emotional/water/fabric/reveal/reaction beats. Slow-mo plays ~2.5× slower, so give those a SHORT (~1.0–1.6s) source span. Keep roughly 30–40% of total runtime at slow-mo — slow-mo must stay special; leave the rest `normal` for contrast. At most about {slowmo_cap} slow-mo shots. Keep most `static` shots at normal speed.

EXPOSURE:
Prefer well-exposed clips. You may keep a slightly over/under shot — exposure is corrected automatically. Just avoid badly clipped footage.

PACING:
- Shot durations should land on the beat; cut 1–2 frames EARLY for drive.
- VARY shot lengths; never more than 3 same-length shots in a row.
- Aim for about {n_shots} shots total, following the slow→fast acceleration arc above.

RULES: ALL HARD CUTS (no dissolves). Prioritize emotional + story moments. Use only strong clips — skip soft, over/under-exposed, or repetitive ones.

Output ONLY JSON matching the schema."""


def _push_in_for_duration(dur: float) -> float:
    """Push amount by on-screen duration (spec §7e step 3)."""
    if dur < 4.0:
        return 0.05
    elif dur <= 10.0:
        return 0.07
    else:
        return 0.08


def parse_director_edl(data: dict, candidates: Sequence[DirectorCandidate],
                       theme: str, music: MusicInfo, default_profile: str = "rec709",
                       target_total: float = 28.0,
                       slowmo_ceiling: float = 0.40,
                       shot_to_shot_easing: bool = True) -> EDL:
    """Build an EDL and apply the deterministic post-pass (§7e)."""
    by_index = {c.index: c for c in candidates}
    clips: List[Clip] = []
    clip_cands: List[DirectorCandidate] = []   # parallel list for §7e easing pass
    cid = 1

    # ---- Build clips (model choices) -----------------------------------------
    for item in (data or {}).get("timeline", []):
        try:
            cand = by_index.get(int(item["clip_index"]))
            in_p = float(item["in"])
            out_p = float(item["out"])
        except (KeyError, TypeError, ValueError):
            continue
        if cand is None:
            continue
        in_p = max(0.0, min(in_p, cand.duration))
        out_p = max(0.0, min(out_p, cand.duration))
        if out_p <= in_p:
            continue
        role = item.get("role", "body")
        if role not in ("hook", "body", "closer"):
            role = "body"
        try:
            sx = max(0.0, min(1.0, float(item.get("subject_x", cand.subject_x))))
        except (TypeError, ValueError):
            sx = cand.subject_x
        retime = item.get("retime", "normal")
        if retime not in ("normal", "slowmo"):
            retime = "normal"
        stabilize = bool(item.get("stabilize", False))

        clip = Clip(
            id=cid,
            source=cand.path,
            in_point=round(in_p, 3),
            out_point=round(out_p, 3),
            color_profile=profile_for(cand.path, default_profile),
            role=role,
            stabilize=stabilize,
            subject_x=round(sx, 3),
            retime=retime,
            source_fps=cand.fps,
        )
        clips.append(clip)
        clip_cands.append(cand)
        cid += 1

    # ---- Deterministic post-pass §7e ----------------------------------------

    REAL_MOVES = {"pan", "tilt", "push_in", "pull_back"}

    for clip, cand in zip(clips, clip_cands):

        # Step 1 — copy motion type
        clip.motion_type = cand.motion_type

        # Step 2 — one-motion windowing (pan/tilt/push_in/pull_back)
        if cand.motion_type in REAL_MOVES:
            m_in = cand.motion_in
            m_out = cand.motion_out if cand.motion_out > cand.motion_in else cand.duration
            # Intersect model window with motion span
            win_in = max(clip.in_point, m_in)
            win_out = min(clip.out_point, m_out)
            if win_in >= win_out:
                # No overlap — snap the model window inside the motion span
                desired_dur = clip.out_point - clip.in_point
                win_in = m_in
                win_out = min(m_in + desired_dur, m_out)
                if win_out <= win_in:
                    win_out = m_out
            # If intersection is shorter than needed, pad symmetrically inside motion span
            desired_dur = clip.out_point - clip.in_point
            if (win_out - win_in) < desired_dur:
                extra = desired_dur - (win_out - win_in)
                pad_left = min(extra / 2.0, win_in - m_in)
                pad_right = min(extra - pad_left, m_out - win_out)
                win_in = max(m_in, win_in - pad_left)
                win_out = min(m_out, win_out + pad_right)
            clip.in_point = round(win_in, 3)
            clip.out_point = round(win_out, 3)

        # Step 3 — push-in (one synthetic motion for static/complex)
        if cand.motion_type in REAL_MOVES:
            clip.push_in = 0.0   # real move IS the one motion
        elif cand.motion_type == "complex":
            clip.stabilize = True   # force stabilize on complex
            clip.push_in = _push_in_for_duration(clip.duration)
        else:  # static
            clip.push_in = _push_in_for_duration(clip.duration)

        # Step 4a — slow-mo safety: never slow complex+unstabilized
        if clip.retime == "slowmo" and cand.motion_type == "complex" and not clip.stabilize:
            clip.retime = "normal"

        # Step 5 — exposure (deterministic from measurement)
        err = analysis.TARGET_MID - cand.exp_mean
        adjust = max(-0.45, min(0.45, err / 140.0))
        clip.exposure_adjust = round(adjust, 3)
        clip.highlight_clip = cand.exp_highlight_clip

    # Step 4b — slow-mo cap: downgrade excess slowmo past ~40% of target_total
    total_slowmo_s = 0.0
    cap_s = target_total * slowmo_ceiling
    for clip in clips:
        if clip.retime == "slowmo":
            on_screen = clip.duration * 2.5   # setpts=2.5*PTS
            if total_slowmo_s + on_screen > cap_s:
                clip.retime = "normal"
            else:
                total_slowmo_s += on_screen

    # Step 6 — shot-to-shot easing (exposure doc §c)
    if shot_to_shot_easing and clip_cands:
        exp_means = [c.exp_mean for c in clip_cands]
        timeline_mean = statistics.median(exp_means)
        for clip, cand in zip(clips, clip_cands):
            matched_target = analysis.TARGET_MID * 0.65 + timeline_mean * 0.35
            err2 = matched_target - cand.exp_mean
            adjust2 = max(-0.45, min(0.45, err2 / 140.0))
            clip.exposure_adjust = round(adjust2, 3)

    return EDL(theme=theme, music=music.path, clips=clips, duration_target_s=target_total)


def apply_cinematic_defaults(edl: EDL, scouts_by_path: dict,
                              target_total: float = 28.0,
                              slowmo_ceiling: float = 0.40,
                              shot_to_shot_easing: bool = True) -> None:
    """Apply the same deterministic post-pass as parse_director_edl (§7e / §8b).

    Mutates ``edl.clips`` in-place.  ``scouts_by_path`` maps source path →
    ClipScout (provides the measured exp/motion fields).

    Called by pipeline.build_edl_scored so the scored fallback path gets the
    same cinematic look as the director path.
    """
    REAL_MOVES = {"pan", "tilt", "push_in", "pull_back"}

    # --- pair each clip with its scout (or a synthetic stand-in with defaults) ---
    from .scout import ClipScout as _ClipScout

    def _default_scout(path: str, duration: float) -> "_ClipScout":
        return _ClipScout(path=path, score=0.0, best_in=0.0,
                          best_out=duration, duration=duration, fps=0.0)

    paired: List[tuple] = []
    for clip in edl.clips:
        sc = scouts_by_path.get(clip.source)
        if sc is None:
            sc = _default_scout(clip.source, clip.duration)
        paired.append((clip, sc))

    for clip, sc in paired:

        # Step 1 — copy motion type
        clip.motion_type = sc.motion_type

        # Step 2 — one-motion windowing
        if sc.motion_type in REAL_MOVES:
            m_in = sc.motion_in
            m_out = sc.motion_out if sc.motion_out > sc.motion_in else sc.duration
            win_in = max(clip.in_point, m_in)
            win_out = min(clip.out_point, m_out)
            if win_in >= win_out:
                desired_dur = clip.out_point - clip.in_point
                win_in = m_in
                win_out = min(m_in + desired_dur, m_out)
                if win_out <= win_in:
                    win_out = m_out
            desired_dur = clip.out_point - clip.in_point
            if (win_out - win_in) < desired_dur:
                extra = desired_dur - (win_out - win_in)
                pad_left = min(extra / 2.0, win_in - m_in)
                pad_right = min(extra - pad_left, m_out - win_out)
                win_in = max(m_in, win_in - pad_left)
                win_out = min(m_out, win_out + pad_right)
            clip.in_point = round(win_in, 3)
            clip.out_point = round(win_out, 3)

        # Step 3 — push-in / stabilize
        if sc.motion_type in REAL_MOVES:
            clip.push_in = 0.0
        elif sc.motion_type == "complex":
            clip.stabilize = True
            clip.push_in = _push_in_for_duration(clip.duration)
        else:  # static
            clip.push_in = _push_in_for_duration(clip.duration)

        # Step 4a — slow-mo safety (scored path: default static clips to normal)
        if clip.retime == "slowmo" and sc.motion_type == "complex" and not clip.stabilize:
            clip.retime = "normal"

        # In the scored path clips start as normal; assign slowmo for clean moves
        if clip.retime == "normal" and sc.motion_type in REAL_MOVES:
            clip.retime = "slowmo"

        # Step 5 — exposure
        err = analysis.TARGET_MID - sc.exp_mean
        adjust = max(-0.45, min(0.45, err / 140.0))
        clip.exposure_adjust = round(adjust, 3)
        clip.highlight_clip = sc.exp_highlight_clip

    # Step 4b — slow-mo cap
    total_slowmo_s = 0.0
    cap_s = target_total * slowmo_ceiling
    for clip in edl.clips:
        if clip.retime == "slowmo":
            on_screen = clip.duration * 2.5
            if total_slowmo_s + on_screen > cap_s:
                clip.retime = "normal"
            else:
                total_slowmo_s += on_screen

    # Step 6 — shot-to-shot easing
    if shot_to_shot_easing and paired:
        exp_means = [sc.exp_mean for _, sc in paired]
        timeline_mean = statistics.median(exp_means)
        for clip, sc in paired:
            matched_target = analysis.TARGET_MID * 0.65 + timeline_mean * 0.35
            err2 = matched_target - sc.exp_mean
            adjust2 = max(-0.45, min(0.45, err2 / 140.0))
            clip.exposure_adjust = round(adjust2, 3)


class DirectorClient:
    """Interface: turn a prompt + proxy video paths into the model's raw JSON dict."""

    def generate_edl(self, prompt: str, proxy_paths: Sequence[str]) -> dict:
        raise NotImplementedError


def compose_edit(theme: str, candidates: Sequence[DirectorCandidate], music: MusicInfo,
                 client: DirectorClient, default_profile: str = "rec709",
                 target_total: float = 28.0,
                 slowmo_ceiling: float = 0.40) -> EDL:
    prompt = build_director_prompt(theme, candidates, music, target_total)
    proxy_paths = [c.proxy_path for c in candidates]
    data = client.generate_edl(prompt, proxy_paths)
    return parse_director_edl(data, candidates, theme, music, default_profile, target_total,
                              slowmo_ceiling=slowmo_ceiling)
