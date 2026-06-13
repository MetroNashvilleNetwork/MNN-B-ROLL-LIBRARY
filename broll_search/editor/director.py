"""AI creative director: compose an edit by having a model watch clip proxies.

The model-specific call lives behind the DirectorClient interface; everything in
this module (prompt, schema, parsing) is pure and unit-tested with a fake client."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Sequence

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


# JSON schema the model fills via structured output.
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
    lines = []
    for c in candidates:
        lines.append(
            f"Clip {c.index}: file={os.path.basename(c.path)} duration={c.duration:.1f}s "
            f"fps={c.fps:.0f} quality={c.score:.0f} subject_x={c.subject_x:.2f}")
    return "\n".join(lines)


def build_director_prompt(theme: str, candidates: Sequence[DirectorCandidate],
                          music: MusicInfo, target_total: float = 28.0) -> str:
    n_shots = max(6, round(target_total / 1.2))
    bpm = round(music.tempo)
    beat = round(60.0 / bpm, 2) if bpm else 0
    return f"""You are a senior video editor cutting a {target_total:.0f}-second vertical (9:16) social recap on the theme "{theme}" in the house style of Metro Nashville Network. Emulate this proven style exactly.

You are shown {len(candidates)} b-roll proxy clips (low-res previews), in this manifest order:
{_candidate_manifest(candidates)}

Music: ~{bpm} BPM (one beat ~= {beat}s), {music.duration:.0f}s long.

WATCH the clips and compose the edit as a `timeline` of cuts. Follow this STRUCTURE/ARC:
1. OPEN on 1-2 CLOSE DETAIL or PROP macro shots (a branded object, award, sign, hands) held longer (~3s, then ~2.5s). Do NOT open on a person or a wide.
2. Then the FIRST HUMAN moment - a candid (~1.3s).
3. Then an ESTABLISHING WIDE (~0.9s) to set the scene.
4. BUILD and ACCELERATE - alternate people, reactions, details, action, with shots getting progressively SHORTER toward the end (start ~2s, finish ~0.4-0.6s rapid-fire).
5. CLOSE on a longer WIDE group/hero hold (~2.5-3s) that breathes.

For each cut choose:
- clip_index (from the manifest)
- in / out: the single BEST moment in that clip, in seconds (strongest expression/action - NOT the first frames)
- role: "hook" for shot 1, "closer" for the final hold, "body" otherwise
- subject_x: 0.0=left .. 1.0=right, where the subject sits (for the vertical crop)
- stabilize: true for any handheld/shaky shot
- retime: "slowmo" ONLY for the single hero moment (see below); "normal" for everything else

PACING:
- Make shot durations land on the beat; a cut feels tightest landing 1-2 frames BEFORE the beat.
- VARY shot lengths; never more than 3 same-length shots in a row.
- Aim for about {n_shots} shots, following the slow->fast acceleration arc above.

SLOW-MO - use SPARINGLY (the reference used almost none):
- At most ONE hero slow-mo, in the final third, ONLY on a shot that earns it (applause, water, a gesture, a reveal). It plays ~2.5x slower, so give it a SHORT (~1.2-1.5s) in/out span. Do NOT slow other clips.

RULES: ALL HARD CUTS (no dissolves). Prioritize emotional + story moments. Use only strong clips - skip soft, over/under-exposed, or repetitive ones.

Output ONLY JSON matching the schema."""


def parse_director_edl(data: dict, candidates: Sequence[DirectorCandidate],
                       theme: str, music: MusicInfo, default_profile: str = "rec709",
                       target_total: float = 28.0) -> EDL:
    by_index = {c.index: c for c in candidates}
    clips: List[Clip] = []
    cid = 1
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
        clips.append(Clip(
            id=cid, source=cand.path, in_point=round(in_p, 3), out_point=round(out_p, 3),
            color_profile=profile_for(cand.path, default_profile), role=role,
            stabilize=bool(item.get("stabilize", False)), subject_x=round(sx, 3),
            retime=retime, source_fps=cand.fps))
        cid += 1
    return EDL(theme=theme, music=music.path, clips=clips, duration_target_s=target_total)


class DirectorClient:
    """Interface: turn a prompt + proxy video paths into the model's raw JSON dict."""

    def generate_edl(self, prompt: str, proxy_paths: Sequence[str]) -> dict:
        raise NotImplementedError


def compose_edit(theme: str, candidates: Sequence[DirectorCandidate], music: MusicInfo,
                 client: DirectorClient, default_profile: str = "rec709",
                 target_total: float = 28.0) -> EDL:
    prompt = build_director_prompt(theme, candidates, music, target_total)
    proxy_paths = [c.proxy_path for c in candidates]
    data = client.generate_edl(prompt, proxy_paths)
    return parse_director_edl(data, candidates, theme, music, default_profile, target_total)
