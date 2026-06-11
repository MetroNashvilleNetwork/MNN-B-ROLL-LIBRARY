"""Scout a clip: sample frames, score quality, find the best moment.

Results cache to disk (keyed by file size + mtime) so the recurring job only
re-analyzes new or changed clips."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Tuple

import cv2

from .analysis import frame_quality


@dataclass
class ClipScout:
    path: str
    score: float        # overall quality = mean of sampled frame qualities
    best_in: float      # seconds — start of the best window
    best_out: float     # seconds — end of the best window
    duration: float     # seconds
    fps: float


def sample_frames(path: str, n: int = 12) -> Tuple[float, float, List[Tuple[float, "any"]]]:
    """Return (fps, duration_seconds, [(t_seconds, frame_bgr), ...]) for n
    roughly evenly-spaced frames. Empty frame list if the clip can't be read."""
    cap = cv2.VideoCapture(str(path))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = (count / fps) if fps else 0.0
    out: List[Tuple[float, "any"]] = []
    if count > 0 and n > 0:
        idxs = sorted(set(int(count * (i + 0.5) / n) for i in range(n)))
        for idx in idxs:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if ok and frame is not None:
                t = idx / fps if fps else 0.0
                out.append((t, frame))
    cap.release()
    return fps, duration, out


def scout_clip(path: str, window: float = 1.5, n: int = 12) -> ClipScout:
    """Sample, score, and locate the best `window`-second moment in a clip."""
    fps, duration, frames = sample_frames(path, n)
    if not frames:
        best_out = min(window, duration) if duration else window
        return ClipScout(path=str(path), score=0.0, best_in=0.0,
                         best_out=round(best_out, 3), duration=round(duration, 3), fps=fps)
    scored = [(t, frame_quality(f)) for t, f in frames]
    score = float(sum(q for _, q in scored) / len(scored))
    best_t = max(scored, key=lambda tq: tq[1])[0]
    best_in = max(0.0, best_t - window / 2.0)
    if duration:
        best_in = min(best_in, max(0.0, duration - window))
    best_out = best_in + window
    if duration:
        best_out = min(best_out, duration)
    return ClipScout(path=str(path), score=score, best_in=round(best_in, 3),
                     best_out=round(best_out, 3), duration=round(duration, 3), fps=fps)


# --- caching -------------------------------------------------------------

def _cache_key(path: str) -> str:
    st = os.stat(path)
    return f"{st.st_size}:{st.st_mtime_ns}"


def scout_clip_cached(path: str, cache: dict, window: float = 1.5, n: int = 12) -> ClipScout:
    """Return a ClipScout, reusing the cached one if the file is unchanged."""
    path = str(path)
    key = _cache_key(path)
    entry = cache.get(path)
    if entry and entry.get("_key") == key:
        fields = {k: v for k, v in entry.items() if k != "_key"}
        return ClipScout(**fields)
    sc = scout_clip(path, window=window, n=n)
    rec = asdict(sc)
    rec["_key"] = key
    cache[path] = rec
    return sc


def load_cache(cache_path) -> dict:
    p = Path(cache_path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_cache(cache_path, cache: dict) -> None:
    Path(cache_path).write_text(json.dumps(cache, indent=2), encoding="utf-8")
