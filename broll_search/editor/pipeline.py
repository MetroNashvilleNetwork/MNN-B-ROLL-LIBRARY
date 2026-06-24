"""Phase 1 orchestration: a folder of clips + a music track -> two MP4s."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

from ..config import PROJECT_ROOT
from ..web.media import _resolve_tool
from .director import DirectorCandidate, apply_cinematic_defaults, compose_edit
from .edl import EDL, clamp_clip_to_source, dedupe_edl_sources, validate_edl
from .music import MusicInfo, analyze_music
from .planner import plan, plan_scored
from .probe import ClipInfo, probe_clip
from .profiles import profile_for
from .proxies import proxy_for
from .render import render_format
from .scout import scout_clip_cached, load_cache, save_cache

VIDEO_EXTS = {".mp4", ".mov", ".mxf", ".m4v", ".mkv", ".avi"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac"}
AUTO_THEME_VALUES = {"", "auto"}


@dataclass
class RenderResult:
    edl: EDL
    vertical: Path | None
    landscape: Path | None
    out_dir: Path


def find_media(folder: Path, exts, *, recursive: bool = True) -> List[Path]:
    folder = Path(folder)
    if not folder.is_dir():
        raise RuntimeError(f"Folder not found: {folder}")
    exts = {e.lower() for e in exts}
    if recursive:
        return sorted(
            p for p in folder.rglob("*")
            if p.is_file() and p.suffix.lower() in exts
        )
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in exts
    )


def _source_durations_from_cache(cache: dict, clip_paths: Sequence[str]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for path in clip_paths:
        entry = cache.get(str(path)) or {}
        dur = entry.get("duration")
        if dur:
            out[str(path)] = float(dur)
    return out


def _clamp_edl_to_sources(edl: EDL, durations: Dict[str, float]) -> None:
    for clip in edl.clips:
        clamp_clip_to_source(clip, durations.get(clip.source, 0.0))


def _is_auto_theme(theme: str) -> bool:
    return (theme or "").strip().lower() in AUTO_THEME_VALUES


def _scout_all(clip_paths: Sequence[str], cache: dict, default_profile: str):
    scouts = []
    for p in clip_paths:
        scouts.append(
            scout_clip_cached(
                p, cache, profile=profile_for(p, default_profile),
            )
        )
    return scouts


def _apply_beat_sync(
    edl: EDL,
    music: MusicInfo,
    source_durations: Dict[str, float],
    *,
    slowmo_factor: float,
    intro_offset: float,
    target_total: float,
    off_beat_fraction: float,
) -> None:
    from .timing import snap_clips_to_beats

    snap_clips_to_beats(
        edl.clips,
        music.beats,
        slowmo_factor=slowmo_factor,
        start_offset=intro_offset,
        target_total=target_total,
        source_durations=[source_durations.get(c.source, 0.0) for c in edl.clips],
        off_beat_fraction=off_beat_fraction,
    )


def build_edl_scored(clip_paths: Sequence[str], music_path: str, theme: str,
                     target_total: float, default_profile: str,
                     cache: dict, window: float = 1.5,
                     slowmo_ceiling: float = 0.70, slowmo_all: bool = False,
                     slowmo_factor: float = 0.0) -> EDL:
    """Quality-ranked EDL + apply the same cinematic post-pass as the director path."""
    scouts = [scout_clip_cached(p, cache, window=window,
                                profile=profile_for(p, default_profile))
              for p in clip_paths]
    music = analyze_music(music_path)
    edl = plan_scored(scouts, music, theme=theme, target_total=target_total,
                      default_profile=default_profile)
    scouts_by_path = {sc.path: sc for sc in scouts}
    apply_cinematic_defaults(edl, scouts_by_path,
                             target_total=target_total, slowmo_ceiling=slowmo_ceiling,
                             slowmo_all=slowmo_all, slowmo_factor=slowmo_factor)
    dedupe_edl_sources(edl)
    return edl


def build_edl_director(clip_paths: Sequence[str], music_path: str, theme: str,
                       target_total: float, default_profile: str,
                       cache: dict, proxy_dir, ffmpeg_path: str, client,
                       max_candidates: int = 40,
                       slowmo_ceiling: float = 0.70, slowmo_all: bool = False,
                       slowmo_factor: float = 0.0,
                       beat_sync: bool = True, intro_offset: float = 0.0,
                       pacing_style: str = "municipal_neutral",
                       off_beat_fraction: float = 0.15) -> EDL:
    """Director-driven EDL: rank clips, scout them (with correct profile), pass to Gemini."""
    music = analyze_music(music_path)
    ranked = []
    for p in clip_paths:
        clip_profile = profile_for(p, default_profile)
        sc = scout_clip_cached(p, cache, profile=clip_profile)
        if sc.score > 0 and sc.duration > 0:
            ranked.append((p, sc))
    ranked.sort(key=lambda ps: ps[1].score, reverse=True)
    ranked = ranked[:max_candidates]
    ranked.sort(key=lambda ps: ps[0])
    candidates = []
    for i, (p, sc) in enumerate(ranked):
        proxy = proxy_for(p, proxy_dir, ffmpeg_path=ffmpeg_path)
        candidates.append(DirectorCandidate(
            index=i, path=p, proxy_path=str(proxy), duration=sc.duration,
            fps=sc.fps, score=sc.score, subject_x=sc.subject_x,
            best_in=sc.best_in, best_out=sc.best_out,
            exp_mean=sc.exp_mean,
            exp_midtone=sc.exp_midtone,
            exp_highlight_clip=sc.exp_highlight_clip,
            motion_type=sc.motion_type,
            motion_in=sc.motion_in,
            motion_out=sc.motion_out,
            motion_strength=sc.motion_strength,
        ))
    edl = compose_edit(theme, candidates, music, client,
                       default_profile=default_profile, target_total=target_total,
                       slowmo_ceiling=slowmo_ceiling, slowmo_all=slowmo_all,
                       slowmo_factor=slowmo_factor, pacing_style=pacing_style)
    source_durs = {p: sc.duration for p, sc in ranked}
    if beat_sync:
        _apply_beat_sync(
            edl, music, source_durs,
            slowmo_factor=slowmo_factor,
            intro_offset=intro_offset,
            target_total=target_total,
            off_beat_fraction=off_beat_fraction,
        )
    _clamp_edl_to_sources(edl, source_durs)
    dedupe_edl_sources(edl)
    return edl


def build_edl(clip_paths: Sequence[str], music_path: str, theme: str,
              target_total: float, default_profile: str,
              ffprobe_path: str = "ffprobe") -> EDL:
    infos: List[ClipInfo] = [probe_clip(p, ffprobe_path=ffprobe_path) for p in clip_paths]
    music: MusicInfo = analyze_music(music_path)
    return plan(infos, music, theme=theme, target_total=target_total,
                default_profile=default_profile)


def run_pipeline(clips_dir, music_dir, out_dir, theme,
                 target_total=35.0, default_profile="sony_slog3",
                 lut_dir="luts", ffmpeg_path="ffmpeg", ffprobe_path="ffprobe",
                 scored=True, scout_cache=None, director_client=None,
                 curator_client=None, auto_curate=True,
                 max_candidates=40, proxy_dir=None,
                 brand: bool = True, font_path: str = "",
                 look_strength: float = 0.3,
                 stabilize: bool = True,
                 exposure: bool = True,
                 slowmo_ceiling: float = 0.70,
                 final_quality: bool = True,
                 outro: str = "fade",
                 slowmo_all: bool = False,
                 slowmo_factor: float = 0.0,
                 beat_sync: bool = True,
                 off_beat_fraction: float = 0.15,
                 formats: str = "landscape",
                 pacing_style: str = "municipal_neutral"):
    """Run the full pipeline: scout → EDL → render."""
    ffmpeg = _resolve_tool(ffmpeg_path, "ffmpeg")
    ffprobe = _resolve_tool(ffprobe_path, "ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError(
            "ffmpeg/ffprobe not found. Install them, put them on PATH, or drop "
            "ffmpeg(.exe)/ffprobe(.exe) into the project's tools/ folder.")

    clip_paths = [str(p) for p in find_media(Path(clips_dir), VIDEO_EXTS)]
    if not clip_paths:
        raise RuntimeError(f"No video clips found in {clips_dir}")
    music_files = find_media(Path(music_dir), AUDIO_EXTS)
    if not music_files:
        raise RuntimeError(f"No music track found in {music_dir}")

    cache_path = Path(scout_cache) if scout_cache else PROJECT_ROOT / "cache" / "editor_scout.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = load_cache(cache_path)
    source_durations = _source_durations_from_cache(cache, clip_paths)

    curator = curator_client or director_client
    music_path = str(music_files[0])
    if auto_curate and curator is not None:
        from .autonomy import curate_edit

        scouts = _scout_all(clip_paths, cache, default_profile)
        theme_hint = "" if _is_auto_theme(theme) else theme.strip()
        try:
            curation = curate_edit(
                curator,
                scouts,
                [str(p) for p in music_files],
                target_total,
                theme_hint=theme_hint,
            )
            if _is_auto_theme(theme):
                theme = curation.theme
            music_path = curation.music_path
            pacing_style = curation.pacing_style
            print(
                f"Curator: theme={theme!r} music={Path(music_path).name} "
                f"pacing={pacing_style}",
                file=sys.stderr,
            )
        except Exception as exc:
            print(f"Warning: AI curation failed ({exc}); using folder defaults.",
                  file=sys.stderr)
    elif _is_auto_theme(theme):
        theme = "MNN B-Roll"

    intro_offset = 1.8 if brand else 0.0
    director_failed = False
    if director_client is not None:
        pdir = Path(proxy_dir) if proxy_dir else PROJECT_ROOT / "cache" / "proxies"
        try:
            edl = build_edl_director(
                clip_paths, music_path, theme, target_total,
                default_profile, cache, pdir, ffmpeg,
                director_client, max_candidates,
                slowmo_ceiling=slowmo_ceiling, slowmo_all=slowmo_all,
                slowmo_factor=slowmo_factor,
                beat_sync=beat_sync, intro_offset=intro_offset,
                pacing_style=pacing_style,
                off_beat_fraction=off_beat_fraction,
            )
            errs = validate_edl(edl, source_durations)
        except Exception as exc:
            director_failed = True
            print(f"Warning: AI director failed ({exc}); using quality scoring.",
                  file=sys.stderr)
            edl, errs = None, [f"director failed: {exc}"]
        if edl is None or errs:
            if errs and not director_failed:
                print("Warning: director EDL invalid; using quality scoring.\n  - "
                      + "\n  - ".join(errs), file=sys.stderr)
            edl = build_edl_scored(clip_paths, music_path, theme, target_total,
                                   default_profile, cache,
                                   slowmo_ceiling=slowmo_ceiling, slowmo_all=slowmo_all,
                                   slowmo_factor=slowmo_factor)
    elif scored:
        edl = build_edl_scored(clip_paths, music_path, theme, target_total,
                               default_profile, cache,
                               slowmo_ceiling=slowmo_ceiling, slowmo_all=slowmo_all,
                               slowmo_factor=slowmo_factor)
    else:
        edl = build_edl(clip_paths, music_path, theme, target_total,
                        default_profile, ffprobe_path=ffprobe)

    music_info = analyze_music(music_path)
    if beat_sync and director_client is None:
        _apply_beat_sync(
            edl, music_info, source_durations,
            slowmo_factor=slowmo_factor,
            intro_offset=intro_offset,
            target_total=target_total,
            off_beat_fraction=off_beat_fraction,
        )

    _clamp_edl_to_sources(edl, source_durations)
    dedupe_edl_sources(edl)
    save_cache(cache_path, cache)

    if not stabilize:
        for clip in edl.clips:
            clip.stabilize = False
    if not exposure:
        for clip in edl.clips:
            clip.exposure_adjust = 0.0
            clip.highlight_clip = 0.0

    errors = validate_edl(edl, source_durations)
    if errors:
        raise RuntimeError("Invalid EDL:\n  - " + "\n  - ".join(errors))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    vertical = landscape = None
    if formats in ("both", "vertical"):
        vertical = render_format(edl, out / "vertical.mp4", 1080, 1920,
                                 lut_dir=lut_dir, ffmpeg_path=ffmpeg, tmpdir=out,
                                 brand_enabled=brand, font_path=font_path,
                                 look_strength=look_strength, final_quality=final_quality,
                                 outro=outro, slowmo_factor=slowmo_factor)
    if formats in ("both", "landscape"):
        landscape = render_format(edl, out / "landscape.mp4", 1920, 1080,
                                  lut_dir=lut_dir, ffmpeg_path=ffmpeg, tmpdir=out,
                                  brand_enabled=brand, font_path=font_path,
                                  look_strength=look_strength, final_quality=final_quality,
                                  outro=outro, slowmo_factor=slowmo_factor)
    (out / "edl.json").write_text(_edl_to_json(edl), encoding="utf-8")
    return RenderResult(edl=edl, vertical=vertical, landscape=landscape, out_dir=out)


def _edl_to_json(edl: EDL) -> str:
    import json
    from dataclasses import asdict
    return json.dumps(asdict(edl), indent=2)
