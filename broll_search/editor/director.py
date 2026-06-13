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
    return f"""You are a senior video editor cutting a {target_total:.0f}-second vertical social montage on the theme "{theme}".

You are shown {len(candidates)} b-roll proxy clips (low-res previews of the real footage), in the same order as this manifest:
{_candidate_manifest(candidates)}

The music track is {music.duration:.0f}s at ~{music.tempo:.0f} BPM with {len(music.beats)} beats.

WATCH the clips and compose the edit. Output a `timeline`: an ordered list of cuts. For each cut choose:
- clip_index: which clip (0-based, from the manifest)
- in / out: the exact best in- and out-point IN SECONDS within that clip (pick the strongest moment you SEE)
- role: "hook" for the very first (most arresting) shot, "closer" for the last, "body" otherwise
- subject_x: 0.0=left .. 1.0=right, where the main subject sits, so vertical cropping keeps them framed
- stabilize: true for ANY shot with visible handheld movement, bounce, or shake (most non-tripod / gimbal-less footage benefits) — be generous; smoothing a slightly shaky shot looks far more professional than leaving it shaky. Use false only for clearly locked-off / tripod shots.
- retime: "slowmo" to play the shot as smooth slow motion (great for high-fps clips with flowing motion — water, crowds, movement); else "normal". NOTE: slowmo plays the clip roughly (its fps / 24) times slower, so a 1s in/out span becomes ~2.5s on screen for 60fps footage — pick a SHORTER in/out span for slowmo shots.
- reason: one short phrase on why you chose this shot/moment

Craft rules (make it look human-made, NOT auto-generated):
- Open on the single strongest, most arresting shot (the hook) in the first ~1.5s.
- VARY shot lengths; never metronomic.
- Sequence with variety: establishing -> medium -> detail; never two near-identical shots back to back.
- Use only the best clips; skip soft or poorly-exposed ones.
- Keep it tight to about {target_total:.0f} seconds total.

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
