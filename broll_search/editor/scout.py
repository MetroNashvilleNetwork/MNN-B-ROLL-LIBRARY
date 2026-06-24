"""Scout a clip: sample frames, score quality, find the best moment.

Results cache to disk (keyed by file size + mtime) so the recurring job only
re-analyzes new or changed clips."""

from __future__ import annotations

import json
import os
import statistics
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Tuple

import cv2

from .analysis import frame_quality, subject_x as frame_subject_x, exposure_stats
from .motion import motion_features


@dataclass
class ClipScout:
    path: str
    score: float        # overall quality = mean of sampled frame qualities
    best_in: float      # seconds — start of the best window
    best_out: float     # seconds — end of the best window
    duration: float     # seconds
    fps: float
    subject_x: float = 0.5   # 0=left .. 1=right; median across sampled frames
    # exposure (709-predicted) — all defaulted for cache back-compat
    exp_mean: float = 112.0
    exp_midtone: float = 112.0
    exp_shadow_clip: float = 0.0
    exp_highlight_clip: float = 0.0
    # motion — all defaulted for cache back-compat
    motion_type: str = "static"
    motion_in: float = 0.0
    motion_out: float = 0.0
    motion_strength: float = 0.0


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


def scout_clip(path: str, window: float = 1.5, n: int = 12,
               profile: str = "sony_slog3") -> ClipScout:
    """Sample, score, and locate the best `window`-second moment in a clip.

    Parameters
    ----------
    profile:
        Colour-space profile for exposure measurement (``"sony_slog3"`` or
        ``"dji_dlogm"`` apply the S-Log3→709 prediction LUT before measuring;
        anything else measures the raw 8-bit luma).  Defaults to
        ``"sony_slog3"`` because the MNN library is FX6 S-Log3.
    """
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
    sxs = [frame_subject_x(f) for _, f in frames]
    sx = round(float(statistics.median(sxs)), 3) if sxs else 0.5

    # --- exposure aggregation across sampled frames -------------------------
    per_frame_stats = [exposure_stats(f, profile) for _, f in frames]
    exp_mean = round(float(statistics.median([s["mean"] for s in per_frame_stats])), 2)
    exp_midtone = round(float(statistics.median([s["midtone"] for s in per_frame_stats])), 2)
    exp_shadow_clip = round(max(s["shadow_clip"] for s in per_frame_stats), 4)
    exp_highlight_clip = round(max(s["highlight_clip"] for s in per_frame_stats), 4)

    # --- motion detection (one call per clip) --------------------------------
    mf = motion_features(str(path))
    motion_out_val = mf["motion_out"]
    if motion_out_val == 0:
        motion_out_val = duration

    return ClipScout(
        path=str(path),
        score=score,
        best_in=round(best_in, 3),
        best_out=round(best_out, 3),
        duration=round(duration, 3),
        fps=fps,
        subject_x=sx,
        exp_mean=exp_mean,
        exp_midtone=exp_midtone,
        exp_shadow_clip=exp_shadow_clip,
        exp_highlight_clip=exp_highlight_clip,
        motion_type=mf["motion_type"],
        motion_in=mf["motion_in"],
        motion_out=motion_out_val,
        motion_strength=mf["motion_strength"],
    )


# --- caching -------------------------------------------------------------

def _cache_key(path: str) -> str:
    try:
        st = os.stat(path)
    except OSError:
        return "missing"
    return f"{st.st_size}:{st.st_mtime_ns}"


def scout_clip_cached(path: str, cache: dict, window: float = 1.5, n: int = 12,
                      profile: str = "sony_slog3") -> ClipScout:
    """Return a ClipScout, reusing the cached one if the file is unchanged."""
    path = str(path)
    key = _cache_key(path)
    entry = cache.get(path)
    if entry and entry.get("_key") == key:
        fields = {k: v for k, v in entry.items() if k != "_key"}
        return ClipScout(**fields)
    sc = scout_clip(path, window=window, n=n, profile=profile)
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
    p = Path(cache_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    tmp.replace(p)
