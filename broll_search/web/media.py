"""Thumbnail and preview generation for the footage gallery.

For each clip we lazily produce, and cache locally:

* a **poster thumbnail** (JPG) shown in the grid, and
* a short **web-friendly preview** (H.264 MP4) that plays on hover and in the
  detail view — because .mov/.mxf often won't play directly in a browser.

Everything is cached under ``<project>/cache`` keyed by the file path + its
modified time, so a clip is only ever processed once. If ffmpeg isn't installed,
the gallery still works: thumbnails fall back to a labelled placeholder and
previews are simply unavailable.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..config import PROJECT_ROOT


def _resolve_tool(configured: str, base_name: str) -> Optional[str]:
    """Find ffmpeg/ffprobe, preferring a copy bundled in tools/ (no PATH edits)."""
    if configured and configured not in (base_name, base_name + ".exe"):
        p = Path(configured)
        if p.exists():
            return str(p)
    found = shutil.which(configured) or shutil.which(base_name)
    if found:
        return found
    names = [base_name + ".exe", base_name]
    for folder in (PROJECT_ROOT / "tools", PROJECT_ROOT / "bin", PROJECT_ROOT):
        for name in names:
            cand = folder / name
            if cand.exists():
                return str(cand)
    return None


def _hidden_kwargs() -> dict:
    kwargs: dict = {"capture_output": True}
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = si
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return kwargs


@dataclass
class MediaEngine:
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    cache_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "cache")
    preview_max_width: int = 640
    preview_max_seconds: int = 60
    max_concurrent: int = 3   # cap simultaneous ffmpeg jobs (avoid CPU storms)

    ffmpeg: Optional[str] = field(init=False, default=None)
    ffprobe: Optional[str] = field(init=False, default=None)
    _locks: dict = field(init=False, default_factory=dict)
    _locks_guard: threading.Lock = field(init=False, default_factory=threading.Lock)
    _gen_sem: threading.Semaphore = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.ffmpeg = _resolve_tool(self.ffmpeg_path, "ffmpeg")
        self.ffprobe = _resolve_tool(self.ffprobe_path, "ffprobe")
        # Limit how many ffmpeg processes run at once so a burst of thumbnail
        # requests (e.g. the first page load) can't saturate the CPU and starve
        # the web server's own request handling.
        self._gen_sem = threading.Semaphore(max(1, self.max_concurrent))
        self.thumbs_dir = self.cache_dir / "thumbs"
        self.previews_dir = self.cache_dir / "previews"
        self.thumbs_dir.mkdir(parents=True, exist_ok=True)
        self.previews_dir.mkdir(parents=True, exist_ok=True)

    @property
    def has_ffmpeg(self) -> bool:
        return bool(self.ffmpeg)

    # -- cache keys -------------------------------------------------------

    def _key(self, path: str, mtime_ns: Optional[int]) -> str:
        raw = f"{path}:{mtime_ns or 0}".encode("utf-8", "ignore")
        return hashlib.sha1(raw).hexdigest()

    def _lock_for(self, key: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    # -- ffmpeg runner ----------------------------------------------------

    def _run(self, cmd: list[str], timeout: float) -> bool:
        try:
            proc = subprocess.run(cmd, timeout=timeout, **_hidden_kwargs())
            return proc.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    # -- thumbnails -------------------------------------------------------

    def thumbnail_path(self, src: str, mtime_ns: Optional[int]) -> Optional[Path]:
        """Return a cached JPG thumbnail, generating it if needed.

        Returns None if ffmpeg is unavailable or generation fails (caller should
        fall back to a placeholder)."""
        if not self.has_ffmpeg:
            return None
        key = self._key(src, mtime_ns)
        out = self.thumbs_dir / f"{key}.jpg"
        if out.exists() and out.stat().st_size > 0:
            return out
        if not os.path.exists(src):
            return None
        with self._lock_for(key):
            if out.exists() and out.stat().st_size > 0:
                return out
            scale = f"scale='min({self.preview_max_width},iw)':-2"
            with self._gen_sem:  # cap concurrent ffmpeg jobs
                for ss in ("1", "0"):  # try 1s in; fall back to first frame
                    ok = self._run(
                        [self.ffmpeg, "-y", "-ss", ss, "-i", src,
                         "-frames:v", "1", "-vf", scale, "-q:v", "3", str(out)],
                        timeout=60,
                    )
                    if ok and out.exists() and out.stat().st_size > 0:
                        return out
        return None

    # -- previews ---------------------------------------------------------

    def preview_path(self, src: str, mtime_ns: Optional[int]) -> Optional[Path]:
        """Return a cached web-friendly MP4 preview, generating it if needed."""
        if not self.has_ffmpeg:
            return None
        key = self._key(src, mtime_ns)
        out = self.previews_dir / f"{key}.mp4"
        if out.exists() and out.stat().st_size > 0:
            return out
        if not os.path.exists(src):
            return None
        with self._lock_for(key):
            if out.exists() and out.stat().st_size > 0:
                return out
            tmp = out.with_suffix(".partial.mp4")
            scale = f"scale='min({self.preview_max_width},iw)':-2"
            with self._gen_sem:  # cap concurrent ffmpeg jobs
                ok = self._run(
                    [self.ffmpeg, "-y", "-i", src,
                     "-t", str(self.preview_max_seconds),
                     "-vf", scale,
                     "-c:v", "libx264", "-crf", "28", "-preset", "veryfast",
                     "-c:a", "aac", "-b:a", "96k",
                     "-movflags", "+faststart", str(tmp)],
                    timeout=600,
                )
            if ok and tmp.exists() and tmp.stat().st_size > 0:
                tmp.replace(out)
                return out
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        return None

    # -- placeholder ------------------------------------------------------

    @staticmethod
    def placeholder_svg(label: str, sub: str = "") -> bytes:
        """A simple labelled card used when no real thumbnail exists."""
        def esc(s: str) -> str:
            return (s.replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;").replace('"', "&quot;"))
        label = esc(label[:60])
        sub = esc(sub[:40])
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#2b3245"/><stop offset="1" stop-color="#1b2030"/>
  </linearGradient></defs>
  <rect width="640" height="360" fill="url(#g)"/>
  <g opacity="0.18">
    <circle cx="320" cy="150" r="46" fill="#8b93a7"/>
    <polygon points="305,128 305,172 345,150" fill="#1b2030"/>
  </g>
  <text x="320" y="250" font-family="Segoe UI, Arial" font-size="22"
        fill="#e7eaf2" text-anchor="middle">{label}</text>
  <text x="320" y="284" font-family="Segoe UI, Arial" font-size="16"
        fill="#9aa3b8" text-anchor="middle">{sub}</text>
</svg>""".encode("utf-8")

    def warm_cache(self, rows, log=None) -> dict:
        """Pre-generate thumbnails (and previews) for many rows up front.

        Optional — the gallery generates lazily on demand — but handy for a
        'build previews now' batch. Returns simple counts."""
        counts = {"thumbs": 0, "previews": 0, "skipped": 0}
        for r in rows:
            src = r["path"]
            mt = r["mtime_ns"]
            if self.thumbnail_path(src, mt):
                counts["thumbs"] += 1
            if self.preview_path(src, mt):
                counts["previews"] += 1
            if log:
                log(f"cached {src}")
        return counts
