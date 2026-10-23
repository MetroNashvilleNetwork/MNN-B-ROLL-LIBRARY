"""Thumbnail and preview generation for the footage gallery.

For each clip we lazily produce, and cache locally:

* a **poster thumbnail** (JPG) shown in the grid, and
* a short **web-friendly preview** (H.264 MP4) that plays on hover and in the
  detail view — because .mov/.mxf often won't play directly in a browser.

Everything is cached under ``<project>/cache`` keyed by the file path + its
modified time, so a clip is only ever processed once. If ffmpeg isn't installed,
the gallery still works: thumbnails fall back to a labelled placeholder and
previews are simply unavailable.

Page requests never run ffmpeg themselves. A cached JPEG is returned
immediately; a missing one is queued for a small background pool, with the
clips the browser is actually showing jumped to the front of the line.
Failures (missing file, online-only OneDrive placeholder, timeout) are
remembered for a few minutes so a reload does not start the work over.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ..config import PROJECT_ROOT

# How long a failed poster stays failed before the background pool tries again.
# Short enough that a file hydrated by OneDrive shows up on a later visit,
# long enough that a bad clip cannot pin the CPU on every page load.
THUMB_FAIL_TTL_SEC = 10 * 60
# Grid tiles are ~256px wide. 480 covers a retina screen without decoding a
# 4K frame into a giant JPEG.
DEFAULT_THUMB_WIDTH = 480


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


def _is_cloud_placeholder(path: str) -> bool:
    """True when Windows says the file is an online-only placeholder.

    Opening those paths makes OneDrive download the whole clip before ffmpeg
    can read a single frame. That stalls the gallery, so posters skip them
    and try again after the failure TTL, once the file may be hydrated.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    except (AttributeError, OSError):
        return False
    if attrs is None or attrs == 0xFFFFFFFF or attrs < 0:
        return False
    offline = 0x1000
    recall_on_open = 0x40000
    recall_on_data_access = 0x400000
    pinned = 0x80000
    if attrs & pinned:
        return False
    return bool(attrs & (offline | recall_on_open | recall_on_data_access))


@dataclass
class MediaEngine:
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    cache_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "cache")
    preview_max_width: int = 640
    preview_max_seconds: int = 60
    max_concurrent: int = 2   # simultaneous thumbnail ffmpeg jobs
    thumb_max_width: int = DEFAULT_THUMB_WIDTH

    ffmpeg: Optional[str] = field(init=False, default=None)
    ffprobe: Optional[str] = field(init=False, default=None)
    _locks: dict = field(init=False, default_factory=dict)
    _locks_guard: threading.Lock = field(init=False, default_factory=threading.Lock)
    _gen_sem: threading.Semaphore = field(init=False, default=None)
    _q_lock: threading.Lock = field(init=False, default_factory=threading.Lock)
    _cv: threading.Condition = field(init=False, default=None)
    _thumb_q: deque = field(init=False, default_factory=deque)
    _preview_q: deque = field(init=False, default_factory=deque)
    _thumb_queued: set = field(init=False, default_factory=set)
    _preview_queued: set = field(init=False, default_factory=set)
    _thumb_inflight_keys: set = field(init=False, default_factory=set)
    _thumb_inflight: int = field(init=False, default=0)
    _workers_started: bool = field(init=False, default=False)
    _rescan_cb: Optional[Callable[[], None]] = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.ffmpeg = _resolve_tool(self.ffmpeg_path, "ffmpeg")
        self.ffprobe = _resolve_tool(self.ffprobe_path, "ffprobe")
        # One preview encode at a time. It has its own worker, so a hover
        # cannot sit in front of poster generation.
        self._gen_sem = threading.Semaphore(1)
        self._cv = threading.Condition(self._q_lock)
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

    def _thumb_file(self, key: str) -> Path:
        return self.thumbs_dir / f"{key}.jpg"

    def _fail_file(self, folder: Path, key: str) -> Path:
        return folder / f"{key}.fail"

    def _failure_fresh(self, folder: Path, key: str) -> bool:
        path = self._fail_file(folder, key)
        try:
            first = path.read_text(encoding="utf-8").splitlines()[0]
            stamp = float(first)
        except (OSError, ValueError, IndexError):
            return False
        return (time.time() - stamp) < THUMB_FAIL_TTL_SEC

    def _mark_failure(self, folder: Path, key: str, reason: str) -> None:
        try:
            self._fail_file(folder, key).write_text(
                f"{time.time():.0f}\n{reason[:400]}", encoding="utf-8")
        except OSError:
            pass

    def _clear_failure(self, folder: Path, key: str) -> None:
        try:
            self._fail_file(folder, key).unlink()
        except OSError:
            pass

    @staticmethod
    def _cleanup(path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    # -- ffmpeg runner ----------------------------------------------------

    def _run(self, cmd: list[str], timeout: float) -> str:
        """Return ``ok``, ``error``, or ``timeout``."""
        try:
            proc = subprocess.run(cmd, timeout=timeout, **_hidden_kwargs())
            return "ok" if proc.returncode == 0 else "error"
        except subprocess.TimeoutExpired:
            return "timeout"
        except OSError:
            return "error"

    # -- worker pool ------------------------------------------------------

    def set_rescan(self, callback: Callable[[], None]) -> None:
        """Register a callback that re-queues posters missing from the cache.

        The web app passes a function that reads the index. It is called once
        a few minutes after startup, and again on that interval, so a clip
        that failed because it was online-only can succeed after OneDrive
        hydrates it — without anyone clicking Re-index.
        """
        self._rescan_cb = callback

    def start_workers(self) -> None:
        """Start the background ffmpeg pools. Safe to call more than once."""
        if self._workers_started or not self.has_ffmpeg:
            self._workers_started = True
            return
        self._workers_started = True
        workers = max(1, int(self.max_concurrent))
        for i in range(workers):
            threading.Thread(
                target=self._thumb_worker, name=f"broll-thumb-{i}", daemon=True,
            ).start()
        threading.Thread(
            target=self._preview_worker, name="broll-preview", daemon=True,
        ).start()
        threading.Thread(
            target=self._rescan_loop, name="broll-thumb-rescan", daemon=True,
        ).start()

    def _rescan_loop(self) -> None:
        # Wait out the failure TTL before the first automatic retry so a
        # just-failed clip is not encoded twice at startup.
        while True:
            time.sleep(THUMB_FAIL_TTL_SEC)
            cb = self._rescan_cb
            if cb is None:
                continue
            try:
                cb()
            except Exception:
                continue

    def thumb_queue_depth(self) -> int:
        with self._q_lock:
            return len(self._thumb_q)

    def _offer_thumb(self, src: str, mtime_ns: Optional[int], *, front: bool) -> bool:
        """Queue one poster. Caller holds ``_q_lock``. Returns True if newly queued."""
        if not src or not self.has_ffmpeg:
            return False
        key = self._key(src, mtime_ns)
        if self._thumb_file(key).exists() or self._failure_fresh(self.thumbs_dir, key):
            return False
        if key in self._thumb_queued or key in self._thumb_inflight_keys:
            if front and key in self._thumb_queued:
                self._promote(key)
            return False
        self._thumb_queued.add(key)
        item = (src, mtime_ns, key)
        if front:
            self._thumb_q.appendleft(item)
        else:
            self._thumb_q.append(item)
        return True

    def _promote(self, key: str) -> None:
        """Move a queued poster to the front. Caller holds ``_q_lock``."""
        if not self._thumb_q:
            return
        kept = deque()
        moved = None
        for item in self._thumb_q:
            if moved is None and item[2] == key:
                moved = item
            else:
                kept.append(item)
        if moved is not None:
            kept.appendleft(moved)
            self._thumb_q = kept

    def enqueue_thumbnail(self, src: str, mtime_ns: Optional[int], *, front: bool = False) -> None:
        """Queue a poster. ``front=True`` is for a clip the browser is showing."""
        with self._q_lock:
            if self._offer_thumb(src, mtime_ns, front=front):
                self._cv.notify()

    def enqueue_many(self, pairs) -> int:
        """Queue many posters at the back, skipping ones already cached or known-bad.

        ``pairs`` is an iterable of ``(path, mtime_ns)`` in the order they
        should be generated (newest first is what the home page shows).
        """
        added = 0
        with self._q_lock:
            for src, mtime_ns in pairs:
                if self._offer_thumb(src, mtime_ns, front=False):
                    added += 1
            if added:
                self._cv.notify_all()
        return added

    def _thumb_worker(self) -> None:
        while True:
            with self._cv:
                while not self._thumb_q:
                    self._cv.wait(timeout=2.0)
                if not self._thumb_q:
                    continue
                src, mtime_ns, key = self._thumb_q.popleft()
                self._thumb_queued.discard(key)
                self._thumb_inflight_keys.add(key)
                self._thumb_inflight += 1
            try:
                if not (self._thumb_file(key).exists() or self._failure_fresh(self.thumbs_dir, key)):
                    self._generate_thumbnail(src, key)
            finally:
                with self._cv:
                    self._thumb_inflight_keys.discard(key)
                    self._thumb_inflight -= 1
                    self._cv.notify_all()

    def enqueue_preview(self, src: str, mtime_ns: Optional[int]) -> None:
        """Queue a hover preview on its own worker, separate from posters."""
        if not src or not self.has_ffmpeg:
            return
        key = self._key(src, mtime_ns)
        if self._preview_file(key).exists() or self._failure_fresh(self.previews_dir, key):
            return
        with self._cv:
            if key in self._preview_queued:
                return
            self._preview_queued.add(key)
            self._preview_q.append((src, mtime_ns, key))
            self._cv.notify()

    def _preview_worker(self) -> None:
        while True:
            with self._cv:
                while not self._preview_q:
                    self._cv.wait(timeout=1.5)
                if not self._preview_q:
                    continue
                src, mtime_ns, key = self._preview_q.popleft()
                self._preview_queued.discard(key)
            try:
                if self.cached_preview(src, mtime_ns) or self._failure_fresh(self.previews_dir, key):
                    continue
                if not self.preview_path(src, mtime_ns):
                    self._mark_failure(self.previews_dir, key, "preview-failed")
            except Exception:
                self._mark_failure(self.previews_dir, key, "preview-error")

    # -- thumbnails -------------------------------------------------------

    def cached_thumbnail(self, src: str, mtime_ns: Optional[int]) -> Optional[Path]:
        """Return the cached JPEG if it is already on disk. Never generates one."""
        path = self._thumb_file(self._key(src, mtime_ns))
        try:
            if path.exists() and path.stat().st_size > 0:
                return path
        except OSError:
            return None
        return None

    def thumb_state(self, src: str, mtime_ns: Optional[int]) -> str:
        """``ready``, ``pending`` (queued or not yet tried), or ``failed``."""
        if self.cached_thumbnail(src, mtime_ns):
            return "ready"
        if not self.has_ffmpeg:
            return "failed"
        if self._failure_fresh(self.thumbs_dir, self._key(src, mtime_ns)):
            return "failed"
        return "pending"

    def _generate_thumbnail(self, src: str, key: str) -> bool:
        """Create ``thumbs/<key>.jpg``. Remembers a failure instead of retrying forever."""
        out = self._thumb_file(key)
        if out.exists() and out.stat().st_size > 0:
            return True
        if not self.has_ffmpeg:
            return False
        if not os.path.exists(src) or _is_cloud_placeholder(src):
            self._mark_failure(self.thumbs_dir, key, "unreadable")
            return False
        tmp = self.thumbs_dir / f"{key}.partial.jpg"
        w = self.thumb_max_width
        # yuv420p first: current ffmpeg accepts it for JPEG and it converts a
        # lot of 8-bit footage. yuvj420p is the older full-range fallback.
        # zscale covers 10-bit / 4:2:2 (ProRes, HEVC) that swscale cannot.
        filters = [
            f"scale='min({w},iw)':-2,format=yuv420p",
            f"scale='min({w},iw)':-2,format=yuvj420p",
            f"zscale={w}:-2,format=yuv420p",
        ]
        with self._lock_for(key):
            if out.exists() and out.stat().st_size > 0:
                return True
            # One timeout means the file is too slow to read (usually a
            # network or OneDrive hydrate). Further filter attempts would
            # only multiply that wait, so stop at the first timeout.
            for ss in ("1", "0"):
                for vf in filters:
                    self._cleanup(tmp)
                    status = self._run(
                        [self.ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
                         "-ss", ss, "-i", src, "-map", "0:v:0", "-an", "-sn", "-dn",
                         "-frames:v", "1", "-vf", vf, "-q:v", "5", str(tmp)],
                        timeout=20,
                    )
                    if status == "ok" and tmp.exists() and tmp.stat().st_size > 0:
                        tmp.replace(out)
                        self._clear_failure(self.thumbs_dir, key)
                        return True
                    if status == "timeout":
                        self._cleanup(tmp)
                        self._mark_failure(self.thumbs_dir, key, "timeout")
                        return False
            # Some clips reject ``-map 0:v:0`` (no video stream index yet).
            # One last try without it, from the first frame.
            self._cleanup(tmp)
            status = self._run(
                [self.ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
                 "-ss", "0", "-i", src, "-an", "-frames:v", "1",
                 "-vf", filters[0], "-q:v", "5", str(tmp)],
                timeout=20,
            )
            if status == "ok" and tmp.exists() and tmp.stat().st_size > 0:
                tmp.replace(out)
                self._clear_failure(self.thumbs_dir, key)
                return True
            self._cleanup(tmp)
            self._mark_failure(self.thumbs_dir, key, "ffmpeg-failed" if status != "timeout" else "timeout")
            return False

    def thumbnail_path(self, src: str, mtime_ns: Optional[int]) -> Optional[Path]:
        """Return a cached JPG thumbnail, generating it on this thread if needed.

        The web gallery does not call this on the request path — it queues
        :meth:`enqueue_thumbnail` instead. Batch tools (``warm_cache``) still
        use the blocking form.
        """
        cached = self.cached_thumbnail(src, mtime_ns)
        if cached:
            return cached
        if not self.has_ffmpeg:
            return None
        key = self._key(src, mtime_ns)
        if self._generate_thumbnail(src, key):
            return self.cached_thumbnail(src, mtime_ns)
        return None

    # -- previews ---------------------------------------------------------

    def _preview_file(self, key: str) -> Path:
        return self.previews_dir / f"{key}.mp4"

    def cached_preview(self, src: str, mtime_ns: Optional[int]) -> Optional[Path]:
        path = self._preview_file(self._key(src, mtime_ns))
        try:
            if path.exists() and path.stat().st_size > 0:
                return path
        except OSError:
            return None
        return None

    def preview_path(self, src: str, mtime_ns: Optional[int]) -> Optional[Path]:
        """Return a cached web-friendly MP4 preview, generating it if needed."""
        if not self.has_ffmpeg:
            return None
        key = self._key(src, mtime_ns)
        out = self._preview_file(key)
        if out.exists() and out.stat().st_size > 0:
            return out
        if not os.path.exists(src) or _is_cloud_placeholder(src):
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
            with self._gen_sem:
                for vf in filters:
                    status = self._run(
                        [self.ffmpeg, "-y", "-nostdin", "-i", src,
                         "-t", str(self.preview_max_seconds),
                         "-vf", vf,
                         "-c:v", "libx264", "-crf", "28", "-preset", "veryfast",
                         # 8-bit 4:2:0 so 10-bit/422 sources still encode AND play in browsers
                         "-pix_fmt", "yuv420p",
                         "-c:a", "aac", "-b:a", "96k",
                         "-movflags", "+faststart", str(tmp)],
                        timeout=600,
                    )
                    if status == "ok" and tmp.exists() and tmp.stat().st_size > 0:
                        ok = True
                        break
                    if status == "timeout":
                        break
            if ok and tmp.exists() and tmp.stat().st_size > 0:
                tmp.replace(out)
                self._clear_failure(self.previews_dir, key)
                return out
            self._cleanup(tmp)
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
