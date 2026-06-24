"""AI curation: infer theme + pacing and pick music from scout summaries (Phases B/C)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Sequence

from .music import MusicInfo, analyze_music
from .scout import ClipScout

PACING_STYLES = ("cinematic_slow", "social_punchy", "documentary", "municipal_neutral")

CURATE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "theme": {"type": "string"},
        "theme_sentence": {"type": "string"},
        "pacing_style": {
            "type": "string",
            "enum": list(PACING_STYLES),
        },
        "music_index": {"type": "integer"},
        "music_rationale": {"type": "string"},
    },
    "required": ["theme", "pacing_style", "music_index"],
}


@dataclass
class MusicOption:
    path: str
    duration: float
    tempo: float


@dataclass
class EditCuration:
    theme: str
    theme_sentence: str
    pacing_style: str
    music_path: str
    music_rationale: str = ""


class CuratorClient:
    """Text-only JSON generation (no proxy uploads)."""

    def generate_json(self, prompt: str, schema: dict) -> dict:
        raise NotImplementedError


def probe_music_options(paths: Sequence[str]) -> List[MusicOption]:
    """Lightweight tempo/duration for each track (full analyze runs on the pick)."""
    out: List[MusicOption] = []
    for p in paths:
        info: MusicInfo = analyze_music(p)
        out.append(MusicOption(path=p, duration=info.duration, tempo=info.tempo))
    return out


def _scout_summary_lines(scouts: Sequence[ClipScout], limit: int = 48) -> str:
    ranked = sorted(
        (s for s in scouts if s.duration > 0),
        key=lambda s: s.score,
        reverse=True,
    )[:limit]
    ranked.sort(key=lambda s: s.path)
    lines = []
    for sc in ranked:
        lines.append(
            f"- {os.path.basename(sc.path)}: {sc.duration:.1f}s quality={sc.score:.0f} "
            f"motion={sc.motion_type} move={sc.motion_strength:.0f} "
            f"best=[{sc.best_in:.1f}-{sc.best_out:.1f}]"
        )
    return "\n".join(lines) if lines else "(no usable clips)"


def build_curator_prompt(
    scouts: Sequence[ClipScout],
    music_options: Sequence[MusicOption],
    target_total: float,
    theme_hint: str = "",
) -> str:
    tracks = []
    for i, m in enumerate(music_options):
        tracks.append(
            f"  [{i}] {os.path.basename(m.path)} — {m.duration:.0f}s, ~{m.tempo:.0f} BPM"
        )
    track_block = "\n".join(tracks)
    hint = (
        f'The editor already has a working title: "{theme_hint}". '
        "Refine it only if the footage clearly suggests something more specific."
        if theme_hint and theme_hint.strip()
        else "Infer a short, specific theme title from the footage (not generic)."
    )
    return f"""You are the creative producer for Metro Nashville Network social recaps.

Target edit length: ~{target_total:.0f} seconds. Landscape-first, premium municipal B-roll.

Footage scout summary (chronological by filename within the list):
{_scout_summary_lines(scouts)}

Available music tracks (pick ONE by music_index):
{track_block}

{hint}

Choose pacing_style:
- cinematic_slow: moody, mostly slow-motion, breathing room
- social_punchy: quicker hooks, still smooth (not chaotic)
- documentary: observational, steadier cuts
- municipal_neutral: balanced MNN house style

Match music tempo/energy to the footage mood and your pacing_style.
Output ONLY JSON matching the schema."""


def parse_curation(data: dict, music_options: Sequence[MusicOption]) -> EditCuration:
    theme = str((data or {}).get("theme", "")).strip() or "MNN B-Roll"
    sentence = str((data or {}).get("theme_sentence", "")).strip()
    pacing = str((data or {}).get("pacing_style", "municipal_neutral")).strip()
    if pacing not in PACING_STYLES:
        pacing = "municipal_neutral"
    try:
        idx = int((data or {}).get("music_index", 0))
    except (TypeError, ValueError):
        idx = 0
    if not music_options:
        raise RuntimeError("No music tracks to curate")
    idx = max(0, min(idx, len(music_options) - 1))
    rationale = str((data or {}).get("music_rationale", "")).strip()
    return EditCuration(
        theme=theme,
        theme_sentence=sentence,
        pacing_style=pacing,
        music_path=music_options[idx].path,
        music_rationale=rationale,
    )


def curate_edit(
    client: CuratorClient,
    scouts: Sequence[ClipScout],
    music_paths: Sequence[str],
    target_total: float = 35.0,
    theme_hint: str = "",
) -> EditCuration:
    music_options = probe_music_options(music_paths)
    prompt = build_curator_prompt(scouts, music_options, target_total, theme_hint=theme_hint)
    data = client.generate_json(prompt, CURATE_RESPONSE_SCHEMA)
    return parse_curation(data, music_options)
