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
from .edl import EDL
from .filters import clip_video_chain


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
) -> Path:
    if not edl.clips:
        raise ValueError("render_format: EDL has no clips")

    out_path = Path(out_path)
    run_cwd = Path(cwd) if cwd else PROJECT_ROOT

    base = Path(tmpdir or out_path.parent)
    base.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f"render_{width}x{height}_", dir=str(base)))

    try:
        # 1) per-clip normalized intermediates
        seg_files = []
        for clip in edl.clips:
            seg = tmp / f"seg_{clip.id:03d}.mp4"
            vf = clip_video_chain(clip.color_profile, lut_dir, width, height,
                                  edl.fps, look_strength)
            _run([ffmpeg_path, "-y", "-ss", str(clip.in_point), "-i", clip.source,
                  "-t", str(clip.duration), "-an", "-vf", vf, "-r", edl.fps,
                  "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                  "-pix_fmt", "yuv420p", str(seg)],
                 cwd=run_cwd, timeout=600)
            seg_files.append(seg)

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
        _run([ffmpeg_path, "-y", "-i", str(silent), "-i", edl.music,
              "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
              "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k",
              "-shortest", "-movflags", "+faststart", str(out_path)],
             cwd=run_cwd, timeout=600)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return out_path
