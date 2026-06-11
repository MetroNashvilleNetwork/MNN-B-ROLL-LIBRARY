"""Phase 1 orchestration: a folder of clips + a music track -> two MP4s."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

from ..web.media import _resolve_tool
from .edl import EDL, validate_edl
from .music import MusicInfo, analyze_music
from .planner import plan
from .probe import ClipInfo, probe_clip
from .render import render_format

VIDEO_EXTS = {".mp4", ".mov", ".mxf", ".m4v", ".mkv", ".avi"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac"}


@dataclass
class RenderResult:
    edl: EDL
    vertical: Path
    landscape: Path
    out_dir: Path


def find_media(folder: Path, exts) -> List[Path]:
    folder = Path(folder)
    if not folder.is_dir():
        raise RuntimeError(f"Folder not found: {folder}")
    exts = {e.lower() for e in exts}
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() in exts)


def build_edl(clip_paths: Sequence[str], music_path: str, theme: str,
              target_total: float, default_profile: str,
              ffprobe_path: str = "ffprobe") -> EDL:
    infos: List[ClipInfo] = [probe_clip(p, ffprobe_path=ffprobe_path) for p in clip_paths]
    music: MusicInfo = analyze_music(music_path)
    return plan(infos, music, theme=theme, target_total=target_total,
                default_profile=default_profile)


def run_pipeline(clips_dir: str, music_dir: str, out_dir: str, theme: str,
                 target_total: float = 28.0, default_profile: str = "rec709",
                 lut_dir: str = "luts", ffmpeg_path: str = "ffmpeg",
                 ffprobe_path: str = "ffprobe") -> RenderResult:
    ffmpeg = _resolve_tool(ffmpeg_path, "ffmpeg")
    ffprobe = _resolve_tool(ffprobe_path, "ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError(
            "ffmpeg/ffprobe not found. Install them, put them on PATH, or drop "
            "ffmpeg(.exe)/ffprobe(.exe) into the project's tools/ folder.")

    clip_paths = [str(p) for p in find_media(Path(clips_dir), VIDEO_EXTS)]
    if not clip_paths:
        raise RuntimeError(f"No video clips found in {clips_dir}")
    music = find_media(Path(music_dir), AUDIO_EXTS)
    if not music:
        raise RuntimeError(f"No music track found in {music_dir}")

    edl = build_edl(clip_paths, str(music[0]), theme, target_total,
                    default_profile, ffprobe_path=ffprobe)
    errors = validate_edl(edl)
    if errors:
        raise RuntimeError("Invalid EDL:\n  - " + "\n  - ".join(errors))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    vertical = render_format(edl, out / "vertical.mp4", 1080, 1920,
                             lut_dir=lut_dir, ffmpeg_path=ffmpeg, tmpdir=out)
    landscape = render_format(edl, out / "landscape.mp4", 1920, 1080,
                              lut_dir=lut_dir, ffmpeg_path=ffmpeg, tmpdir=out)
    (out / "edl.json").write_text(_edl_to_json(edl), encoding="utf-8")
    return RenderResult(edl=edl, vertical=vertical, landscape=landscape, out_dir=out)


def _edl_to_json(edl: EDL) -> str:
    import json
    from dataclasses import asdict
    return json.dumps(asdict(edl), indent=2)
