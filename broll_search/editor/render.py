"""Render an EDL to a single MP4 with ffmpeg.

Strategy (simple and robust for Phase 1): render each clip to a normalized
intermediate (trim + color + reframe + conform), concat the intermediates with
the concat demuxer, then mux in loudness-normalized music. Follows the
subprocess/Windows-console conventions from broll_search/web/media.py."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from ..config import PROJECT_ROOT
from .branding import escape_filter_path
from .edl import EDL
from .filters import clip_video_chain


_STAB_MODE_CACHE: dict = {}


def stabilization_mode(ffmpeg_path: str = "ffmpeg") -> str:
    """Return the best stabilizer this ffmpeg build supports: 'vidstab', 'deshake', or ''."""
    if ffmpeg_path in _STAB_MODE_CACHE:
        return _STAB_MODE_CACHE[ffmpeg_path]
    mode = ""
    try:
        proc = subprocess.run([ffmpeg_path, "-hide_banner", "-filters"],
                              capture_output=True, text=True, timeout=30)
        out = proc.stdout or ""
        if "vidstabtransform" in out and "vidstabdetect" in out:
            mode = "vidstab"
        elif "deshake" in out:
            mode = "deshake"
    except (OSError, subprocess.SubprocessError):
        mode = ""
    _STAB_MODE_CACHE[ffmpeg_path] = mode
    return mode


def _run(cmd: list[str], cwd=None, timeout=None) -> None:
    kwargs: dict = {"capture_output": True}
    if cwd is not None:
        kwargs["cwd"] = str(cwd)
    if timeout is not None:
        kwargs["timeout"] = timeout
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = si
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        proc = subprocess.run(cmd, **kwargs)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffmpeg timed out after {timeout}s")
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "ignore")[-1500:]
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}):\n{err}")


def render_format(
    edl: EDL,
    out_path: Path,
    width: int,
    height: int,
    lut_dir: str = "luts",
    ffmpeg_path: str = "ffmpeg",
    look_strength: float = 1.0,
    tmpdir: Optional[Path] = None,
    cwd: Optional[Path] = None,
    brand_enabled: bool = False,
    font_path: str = "",
    final_quality: bool = True,
    outro: str = "card",
    slowmo_factor: float = 0.0,
) -> Path:
    if not edl.clips:
        raise ValueError("render_format: EDL has no clips")

    out_path = Path(out_path)
    run_cwd = Path(cwd) if cwd else PROJECT_ROOT

    base = Path(tmpdir or out_path.parent)
    base.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f"render_{width}x{height}_", dir=str(base)))

    stab_mode = stabilization_mode(ffmpeg_path)

    try:
        # 1) per-clip normalized intermediates
        seg_files = []
        card_font = ""
        if brand_enabled and edl.clips:
            from . import brand as _brand
            from .branding import make_card
            card_font = _brand.brand_font(font_path)
            if card_font:
                title = make_card(tmp / "card_00_title.mp4", width, height, edl.fps,
                                  title=edl.theme, subtitle="", logo_path=str(_brand.LOGO_PATH),
                                  font_path=card_font, ffmpeg_path=ffmpeg_path, cwd=run_cwd,
                                  tmpdir=tmp, duration=1.8)
                seg_files.append(title)
        for clip in edl.clips:
            seg = tmp / f"seg_{clip.id:03d}.mp4"
            stab = ""
            if getattr(clip, "stabilize", False) and stab_mode:
                if stab_mode == "vidstab":
                    trf = tmp / f"stab_{clip.id:03d}.trf"
                    _run([ffmpeg_path, "-y", "-ss", str(clip.in_point), "-t", str(clip.duration),
                          "-i", clip.source, "-vf",
                          f"vidstabdetect=shakiness=10:accuracy=15:stepsize=6:mincontrast=0.3:result={escape_filter_path(str(trf))}",
                          "-f", "null", "-"], cwd=run_cwd, timeout=600)
                    # Bump smoothing to 50 for complex clips with high motion_strength (>=15 %/s)
                    motion_type = getattr(clip, "motion_type", "static")
                    motion_strength = getattr(clip, "motion_strength", 0.0)
                    smoothing = 65 if (motion_type == "complex" and motion_strength >= 15.0) else 55
                    stab = (f"vidstabtransform=input={escape_filter_path(str(trf))}:smoothing={smoothing}:"
                            f"optzoom=1:zoom=0:interpol=bicubic:crop=black,"
                            f"unsharp=5:5:0.8:3:3:0.4,")
                elif stab_mode == "deshake":
                    stab = "deshake=rx=64:ry=64:edge=clamp:blocksize=8:contrast=125:search=1,"
            # Compute zoompan frame count (pre-slowmo, in source-fps units)
            src_fps = clip.source_fps or (60000 / 1001)
            n_frames = max(1, int(round(clip.duration * src_fps)))
            prescale_h = 4320 if final_quality else 2160
            vf = stab + clip_video_chain(clip.color_profile, lut_dir, width, height,
                                         edl.fps, look_strength, subject_x=clip.subject_x,
                                         retime=clip.retime, source_fps=clip.source_fps,
                                         exposure_adjust=clip.exposure_adjust,
                                         highlight_clip=clip.highlight_clip,
                                         push=clip.push_in, n_frames=n_frames,
                                         prescale_h=prescale_h, slowmo_factor=slowmo_factor)
            _run([ffmpeg_path, "-y", "-ss", str(clip.in_point), "-t", str(clip.duration),
                  "-i", clip.source, "-an", "-vf", vf, "-r", edl.fps,
                  "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                  "-pix_fmt", "yuv420p", str(seg)],
                 cwd=run_cwd, timeout=600)
            seg_files.append(seg)

        if outro == "card" and brand_enabled and card_font and edl.clips:
            outro_seg = make_card(tmp / "card_zz_outro.mp4", width, height, edl.fps,
                                  title=_brand.WORDMARK, subtitle="", logo_path=str(_brand.LOGO_PATH),
                                  font_path=card_font, ffmpeg_path=ffmpeg_path, cwd=run_cwd,
                                  tmpdir=tmp, duration=1.6)
            seg_files.append(outro_seg)

        # 2) concat intermediates (identical params -> stream copy)
        listfile = tmp / "concat.txt"
        listfile.write_text(
            "".join(
                "file '" + str(s.resolve()).replace("'", "'\\''") + "'\n"
                for s in seg_files
            ),
            encoding="utf-8",
        )
        silent = tmp / "silent.mp4"
        _run([ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
              "-c", "copy", str(silent)],
             cwd=run_cwd, timeout=120)

        # 3) mux loudness-normalized music; end at the shorter of video/music
        if outro == "fade":
            # Fade picture to black + fade music out over the final ~0.8s.
            # Video length = sum of on-screen clip durations (+ opening title card).
            vdur = sum(c.duration * (2.5 if c.retime == "slowmo" else 1.0)
                       for c in edl.clips)
            if brand_enabled and card_font:
                vdur += 1.8   # opening title card
            fade_d = 0.8
            fade_st = max(0.0, vdur - fade_d)
            _run([ffmpeg_path, "-y", "-i", str(silent), "-i", edl.music,
                  "-map", "0:v:0", "-map", "1:a:0",
                  "-vf", f"fade=t=out:st={fade_st:.3f}:d={fade_d}",
                  "-af", ("loudnorm=I=-14:TP=-1.5:LRA=11,"
                          f"afade=t=out:st={fade_st:.3f}:d={fade_d}"),
                  "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
                  "-c:a", "aac", "-b:a", "192k",
                  "-shortest", "-movflags", "+faststart", str(out_path)],
                 cwd=run_cwd, timeout=600)
        else:
            _run([ffmpeg_path, "-y", "-i", str(silent), "-i", edl.music,
                  "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                  "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k",
                  "-shortest", "-movflags", "+faststart", str(out_path)],
                 cwd=run_cwd, timeout=600)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return out_path
