"""Phase 1 orchestration: a folder of clips + a music track -> two MP4s."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

from ..config import PROJECT_ROOT
from ..web.media import _resolve_tool
from .director import DirectorCandidate, apply_cinematic_defaults, compose_edit
from .edl import EDL, validate_edl
from .music import MusicInfo, analyze_music
from .planner import plan, plan_scored
from .probe import ClipInfo, probe_clip
from .profiles import profile_for
from .proxies import proxy_for
from .render import render_format
from .scout import scout_clip_cached, load_cache, save_cache

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


def build_edl_scored(clip_paths: Sequence[str], music_path: str, theme: str,
                     target_total: float, default_profile: str,
                     cache: dict, window: float = 1.5,
                     slowmo_ceiling: float = 0.85, slowmo_all: bool = False) -> EDL:
    """Quality-ranked EDL + apply the same cinematic post-pass as the director path."""
    scouts = [scout_clip_cached(p, cache, window=window,
                                profile=profile_for(p, default_profile))
              for p in clip_paths]
    music = analyze_music(music_path)
    edl = plan_scored(scouts, music, theme=theme, target_total=target_total,
                      default_profile=default_profile)
    # 8b — build a scouts_by_path dict so apply_cinematic_defaults can look up measurements
    scouts_by_path = {sc.path: sc for sc in scouts}
    apply_cinematic_defaults(edl, scouts_by_path,
                             target_total=target_total, slowmo_ceiling=slowmo_ceiling, slowmo_all=slowmo_all)
    return edl


def build_edl_director(clip_paths: Sequence[str], music_path: str, theme: str,
                       target_total: float, default_profile: str,
                       cache: dict, proxy_dir, ffmpeg_path: str, client,
                       max_candidates: int = 40,
                       slowmo_ceiling: float = 0.85, slowmo_all: bool = False,
                       slowmo_factor: float = 0.0,
                       beat_sync: bool = True, intro_offset: float = 0.0) -> EDL:
    """Director-driven EDL: rank clips, scout them (with correct profile), pass to Gemini."""
    music = analyze_music(music_path)
    ranked = []
    for p in clip_paths:
        # 8a — pass per-clip profile so exposure is measured in the right colour space
        clip_profile = profile_for(p, default_profile)
        sc = scout_clip_cached(p, cache, profile=clip_profile)
        if sc.score > 0 and sc.duration > 0:
            ranked.append((p, sc))
    ranked.sort(key=lambda ps: ps[1].score, reverse=True)
    ranked = ranked[:max_candidates]
    candidates = []
    for i, (p, sc) in enumerate(ranked):
        proxy = proxy_for(p, proxy_dir, ffmpeg_path=ffmpeg_path)
        # 8a — copy ALL measured fields from ClipScout onto DirectorCandidate
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
                       slowmo_factor=slowmo_factor)
    if beat_sync:
        from .timing import snap_clips_to_beats
        snap_clips_to_beats(edl.clips, music.beats, slowmo_factor=slowmo_factor,
                            start_offset=intro_offset)
    return edl


def build_edl(clip_paths: Sequence[str], music_path: str, theme: str,
              target_total: float, default_profile: str,
              ffprobe_path: str = "ffprobe") -> EDL:
    infos: List[ClipInfo] = [probe_clip(p, ffprobe_path=ffprobe_path) for p in clip_paths]
    music: MusicInfo = analyze_music(music_path)
    return plan(infos, music, theme=theme, target_total=target_total,
                default_profile=default_profile)


def run_pipeline(clips_dir, music_dir, out_dir, theme,
                 target_total=28.0, default_profile="rec709",
                 lut_dir="luts", ffmpeg_path="ffmpeg", ffprobe_path="ffprobe",
                 scored=True, scout_cache=None, director_client=None,
                 max_candidates=40, proxy_dir=None,
                 brand: bool = True, font_path: str = "",
                 look_strength: float = 0.4,
                 stabilize: bool = True,
                 exposure: bool = True,
                 slowmo_ceiling: float = 0.85,
                 final_quality: bool = True,
                 outro: str = "fade",
                 slowmo_all: bool = False,
                 slowmo_factor: float = 0.0,
                 beat_sync: bool = True):
    """Run the full pipeline: scout → EDL → render two formats.

    Parameters
    ----------
    stabilize:
        When False, zero ``clip.stabilize`` on every EDL clip after build
        (escape hatch; normally you want stabilisation ON).
    exposure:
        When False, zero ``clip.exposure_adjust`` and ``clip.highlight_clip``
        on every clip (escape hatch; normally ON).
    slowmo_ceiling:
        Fraction of ``target_total`` that may be slow-mo on-screen (default 0.85).
        Threaded into the EDL builders so the post-pass cap is consistent.
    """
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
    music_path = str(music_files[0])

    cache_path = Path(scout_cache) if scout_cache else PROJECT_ROOT / "cache" / "editor_scout.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = load_cache(cache_path)

    if director_client is not None:
        pdir = Path(proxy_dir) if proxy_dir else PROJECT_ROOT / "cache" / "proxies"
        try:
            edl = build_edl_director(clip_paths, music_path, theme, target_total,
                                     default_profile, cache, pdir, ffmpeg,
                                     director_client, max_candidates,
                                     slowmo_ceiling=slowmo_ceiling, slowmo_all=slowmo_all,
                                     slowmo_factor=slowmo_factor,
                                     beat_sync=beat_sync, intro_offset=(1.8 if brand else 0.0))
            errs = validate_edl(edl)
        except Exception:
            edl, errs = None, ["director failed"]
        if edl is None or errs:
            edl = build_edl_scored(clip_paths, music_path, theme, target_total,
                                   default_profile, cache,
                                   slowmo_ceiling=slowmo_ceiling, slowmo_all=slowmo_all)
    elif scored:
        edl = build_edl_scored(clip_paths, music_path, theme, target_total,
                               default_profile, cache,
                               slowmo_ceiling=slowmo_ceiling, slowmo_all=slowmo_all)
    else:
        edl = build_edl(clip_paths, music_path, theme, target_total,
                        default_profile, ffprobe_path=ffprobe)
    save_cache(cache_path, cache)

    # 8c — escape-hatch overrides: zero fields AFTER EDL is built
    if not stabilize:
        for clip in edl.clips:
            clip.stabilize = False
    if not exposure:
        for clip in edl.clips:
            clip.exposure_adjust = 0.0
            clip.highlight_clip = 0.0

    errors = validate_edl(edl)
    if errors:
        raise RuntimeError("Invalid EDL:\n  - " + "\n  - ".join(errors))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # 8c — final_quality=True for both deliverable renders
    vertical = render_format(edl, out / "vertical.mp4", 1080, 1920,
                             lut_dir=lut_dir, ffmpeg_path=ffmpeg, tmpdir=out,
                             brand_enabled=brand, font_path=font_path,
                             look_strength=look_strength, final_quality=final_quality, outro=outro, slowmo_factor=slowmo_factor)
    landscape = render_format(edl, out / "landscape.mp4", 1920, 1080,
                              lut_dir=lut_dir, ffmpeg_path=ffmpeg, tmpdir=out,
                              brand_enabled=brand, font_path=font_path,
                              look_strength=look_strength, final_quality=final_quality, outro=outro, slowmo_factor=slowmo_factor)
    (out / "edl.json").write_text(_edl_to_json(edl), encoding="utf-8")
    return RenderResult(edl=edl, vertical=vertical, landscape=landscape, out_dir=out)


def _edl_to_json(edl: EDL) -> str:
    import json
    from dataclasses import asdict
    return json.dumps(asdict(edl), indent=2)
