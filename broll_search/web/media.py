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
    max_concurrent: int = 1   # cap simultaneous ffmpeg jobs (avoid CPU storms)

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
            w = self.preview_max_width
            # Normal scaler is fast for 8-bit; zscale is the fallback for 10-bit /
            # 4:2:2 footage (yuv422p10le) that the swscale build can't convert.
            filters = [
                f"scale='min({w},iw)':-2,format=yuvj420p",
                f"zscale={w}:-2,format=yuvj420p",
            ]
            with self._gen_sem:  # cap concurrent ffmpeg jobs
                for ss in ("1", "0"):       # try 1s in; fall back to first frame
                    for vf in filters:
                        ok = self._run(
                            [self.ffmpeg, "-y", "-ss", ss, "-i", src,
                             "-frames:v", "1", "-vf", vf, "-q:v", "3", str(out)],
                            timeout=90,
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
            w = self.preview_max_width
            # Force 8-bit 4:2:0 *inside* the filter chain (not just via -pix_fmt):
            # browsers can only decode yuv420p H.264, and a lot of the source
            # footage is 10-bit / 4:2:2 (ProRes yuv422p10le, HEVC yuv420p10le,
            # MJPEG yuvj422p). Without this an encoded preview can keep the
            # source's 10-bit/4:2:2 layout and play ~1s then freeze in the
            # browser. zscale is the fallback scaler for 10-bit sources swscale
            # can't convert. (Thumbnails already bake format= in the same way.)
            filters = [f"scale='min({w},iw)':-2,format=yuv420p",
                       f"zscale={w}:-2,format=yuv420p"]
            ok = False
            with self._gen_sem:  # cap concurrent ffmpeg jobs
                for vf in filters:
                    ok = self._run(
                        [self.ffmpeg, "-y", "-i", src,
                         "-t", str(self.preview_max_seconds),
                         "-vf", vf,
                         "-c:v", "libx264", "-crf", "28", "-preset", "veryfast",
                         # 8-bit 4:2:0 so 10-bit/422 sources still encode AND play in browsers
                         "-pix_fmt", "yuv420p",
                         "-c:a", "aac", "-b:a", "96k",
                         "-movflags", "+faststart", str(tmp)],
                        timeout=600,
                    )
                    if ok and tmp.exists() and tmp.stat().st_size > 0:
                        break
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
        """A clean dark 'preview unavailable' card shown when a thumbnail can't
        be generated (usually because the source file is online-only/not synced
        from SharePoint, so ffmpeg can't read it)."""
        def esc(s: str) -> str:
            return (s.replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;").replace('"', "&quot;"))
        sub = esc(sub[:48])
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#0e1c30"/><stop offset="1" stop-color="#070f1d"/>
  </linearGradient></defs>
  <rect width="640" height="360" fill="url(#g)"/>
  <g transform="translate(320 150)" fill="none" stroke="#3f5d7d" stroke-width="3"
     stroke-linejoin="round" opacity="0.7">
    <rect x="-46" y="-32" width="92" height="64" rx="8"/>
    <path d="M-46 -14 L46 -14"/>
    <path d="M-30 -32 L-22 -14 M-10 -32 L-2 -14 M10 -32 L18 -14 M30 -32 L38 -14"/>
    <circle cx="0" cy="9" r="11"/>
  </g>
  <text x="320" y="232" font-family="Segoe UI, Arial" font-size="17"
        fill="#9fb0c6" text-anchor="middle" letter-spacing="0.5">Preview unavailable</text>
  <text x="320" y="258" font-family="Segoe UI, Arial" font-size="13"
        fill="#5f7186" text-anchor="middle">{sub}</text>
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
