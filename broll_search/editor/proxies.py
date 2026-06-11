"""Low-res proxy generation for the AI director.

The director watches tiny proxies (not the originals), keeping upload size and
cost down. Proxies are cached by source size + mtime so each clip is encoded
once. Subprocess/Windows-console handling mirrors broll_search/render.py."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path


def _run_kwargs() -> dict:
    kwargs: dict = {"capture_output": True}
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = si
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return kwargs


def make_proxy(src, out_path, ffmpeg_path: str = "ffmpeg", height: int = 480,
               crf: int = 32, fps: int = 15, timeout: float = 300) -> Path:
    """Render a small, low-bitrate, reduced-fps proxy of `src` for the model to watch."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg_path, "-y", "-i", str(src),
           "-vf", f"scale=-2:{height},fps={fps}",
           "-c:v", "libx264", "-crf", str(crf), "-preset", "veryfast",
           "-an", "-movflags", "+faststart", str(out_path)]
    try:
        proc = subprocess.run(cmd, timeout=timeout, **_run_kwargs())
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"proxy generation timed out after {timeout}s for {src}")
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "ignore")[-1000:]
        raise RuntimeError(f"proxy ffmpeg failed ({proc.returncode}):\n{err}")
    return out_path


def proxy_for(src, cache_dir, ffmpeg_path: str = "ffmpeg", height: int = 480,
              crf: int = 32, fps: int = 15) -> Path:
    """Return a cached proxy for `src`, generating it if missing. Cache key is the
    source path + size + mtime, so a changed source is re-proxied automatically."""
    src = Path(src)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    st = src.stat()
    key = hashlib.sha1(f"{src}:{st.st_size}:{st.st_mtime_ns}".encode("utf-8")).hexdigest()[:16]
    out = cache_dir / f"{key}.mp4"
    if out.exists() and out.stat().st_size > 0:
        return out
    return make_proxy(src, out, ffmpeg_path=ffmpeg_path, height=height, crf=crf, fps=fps)
