"""One-motion-per-clip camera-move detection (OpenCV).

Public API
----------
motion_features(path) -> dict
    Returns {"motion_type", "motion_in", "motion_out", "motion_strength"}.
    motion_type: "pan" | "tilt" | "push_in" | "pull_back" | "static" | "complex"

Algorithm:
  Sequential grab/retrieve sampling at ~8 Hz → goodFeaturesToTrack →
  calcOpticalFlowPyrLK → estimateAffinePartial2D → 5-tap median smoothing →
  longest-same-sign-run span.

See docs/superpowers/research/2026-06-13-one-motion-detection.md §3 for full rationale.
"""

from __future__ import annotations

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Classification thresholds (verbatim from spec §FILE 2)
# ---------------------------------------------------------------------------

PAN_MIN_SPEED  = 2.5   # %/s median translation for a real pan/tilt
ZOOM_MIN_SPEED = 1.2   # %/s median zoom for a real push/pull
CONS_MIN       = 0.60  # directional purity for a "clean" move
COMPLEX_SPEED  = 6.0   # %/s median speed w/ low consistency => shaky/complex
MIN_SPAN_S     = 0.8   # a clean move must persist at least this long

# Sampling constants
_TARGET_HZ  = 8.0
_PROC_W     = 480
_MAX_STEPS  = 400


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _med(a: np.ndarray, k: int = 5) -> np.ndarray:
    """5-tap rolling median filter (edges use partial window)."""
    if len(a) < 2:
        return a.copy()
    out = a.copy()
    for i in range(len(a)):
        lo = max(0, i - k // 2)
        hi = min(len(a), i + k // 2 + 1)
        out[i] = np.median(a[lo:hi])
    return out


def _consistency(v: np.ndarray) -> float:
    """Directional purity: |net displacement| / total path length.

    = 1.0 for a perfectly monotone move; ~0 for zero-mean jitter.
    """
    tot = float(np.abs(v).sum())
    if tot < 1e-9:
        return 0.0
    return abs(float(v.sum())) / tot


def _longest_run(v: np.ndarray) -> tuple[int, int, float]:
    """Longest consecutive same-sign run in *v*.

    Returns ``(i, j, net_displacement)`` — inclusive index range of the run
    with the largest absolute net displacement.
    """
    if len(v) < 2:
        return 0, len(v) - 1, 0.0
    sgn = np.sign(v)
    best = (0, 0, 0.0)
    i = 0
    n = len(v)
    while i < n:
        j = i
        while j + 1 < n and (sgn[j + 1] == sgn[i] or sgn[j + 1] == 0):
            j += 1
        net = abs(float(v[i:j + 1].sum()))
        if net > best[2]:
            best = (i, j, net)
        i = j + 1
    return best


def _estimate_motion_track(path: str) -> dict | None:
    """Decode *path* sequentially and return per-step motion arrays.

    Uses cap.grab() / cap.retrieve() for ~10× faster sequential access vs
    per-frame seek.  Downscales to ``_PROC_W`` px wide and converts to
    grayscale before optical-flow tracking.

    Returns None if the clip cannot be opened or is too short.
    """
    cap = cv2.VideoCapture(path)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = count / fps if fps else 0.0
    if not count or not fps:
        cap.release()
        return None

    step = max(1, int(round(fps / _TARGET_HZ)))
    hz = fps / step

    prev = None
    W = H = None
    t: list[float] = []
    vx: list[float] = []
    vy: list[float] = []
    zr: list[float] = []
    ninl: list[int] = []
    fidx = 0
    nstep = 0

    while nstep < _MAX_STEPS:
        if not cap.grab():
            break
        if fidx % step == 0:
            ok, frame = cap.retrieve()
            if ok and frame is not None:
                h, w = frame.shape[:2]
                sc = _PROC_W / w
                gray = cv2.cvtColor(
                    cv2.resize(frame, (_PROC_W, int(h * sc))),
                    cv2.COLOR_BGR2GRAY,
                )
                if W is None:
                    W = _PROC_W
                    H = int(h * sc)

                if prev is not None:
                    vxx = vyy = 0.0
                    ss = 1.0
                    inl_n = 0
                    p0 = cv2.goodFeaturesToTrack(
                        prev,
                        maxCorners=200,
                        qualityLevel=0.01,
                        minDistance=8,
                        blockSize=7,
                    )
                    if p0 is not None and len(p0) >= 8:
                        p1, stt, _ = cv2.calcOpticalFlowPyrLK(
                            prev, gray, p0, None,
                            winSize=(21, 21),
                            maxLevel=3,
                        )
                        mask = stt.ravel() == 1
                        g0 = p0[mask]
                        g1 = p1[mask]
                        if len(g0) >= 8:
                            M, inl = cv2.estimateAffinePartial2D(
                                g0, g1,
                                method=cv2.RANSAC,
                                ransacReprojThreshold=3,
                            )
                            if (
                                M is not None
                                and inl is not None
                                and int(inl.sum()) >= 8
                            ):
                                a, b = M[0, 0], M[0, 1]
                                ss = float(np.sqrt(a * a + b * b))
                                vxx = float(M[0, 2]) / W
                                vyy = float(M[1, 2]) / H
                                inl_n = int(inl.sum())

                    t.append(fidx / fps)
                    vx.append(vxx)
                    vy.append(vyy)
                    zr.append(ss)
                    ninl.append(inl_n)
                    nstep += 1
                prev = gray
        fidx += 1

    cap.release()
    return dict(
        fps=fps,
        duration=duration,
        hz=hz,
        t=np.array(t),
        vx=np.array(vx),
        vy=np.array(vy),
        zr=np.array(zr),
        inliers=np.array(ninl),
    )


def _classify(r: dict | None) -> dict:
    """Classify motion from the track arrays returned by ``_estimate_motion_track``.

    Returns the 4-field dict suitable for ``motion_features``.
    """
    if r is None or len(r["vx"]) < 4:
        dur = r["duration"] if r else 0.0
        return dict(
            motion_type="static",
            motion_in=0.0,
            motion_out=dur,
            motion_strength=0.0,
        )

    hz = r["hz"]
    dur = r["duration"]
    t = r["t"]

    # 5-tap median smoothing kills single-frame RANSAC / motion-blur spikes
    vx_sm = _med(r["vx"])
    vy_sm = _med(r["vy"])
    zr_sm = _med(r["zr"])

    # Convert to physical units (%width/sec or %height/sec)
    vx_s = vx_sm * hz * 100.0
    vy_s = vy_sm * hz * 100.0
    zrate = (zr_sm - 1.0) * hz * 100.0

    # Combined speed magnitude for fallback complex/static decision
    speed = np.sqrt(vx_s ** 2 + vy_s ** 2)

    # Per-axis robust speed (median of absolute values)
    spd_x = float(np.median(np.abs(vx_s)))
    spd_y = float(np.median(np.abs(vy_s)))
    spd_z = float(np.median(np.abs(zrate)))

    # Per-axis directional consistency
    cons_x = _consistency(vx_sm)
    cons_y = _consistency(vy_sm)
    cons_z = _consistency(zr_sm - 1.0)

    # Build candidate clean moves (axis qualifies iff speed AND consistency both clear)
    cands: list[tuple[str, float, float, np.ndarray]] = []
    if spd_x >= PAN_MIN_SPEED and cons_x >= CONS_MIN:
        cands.append(("pan", spd_x, cons_x, vx_s))
    if spd_y >= PAN_MIN_SPEED and cons_y >= CONS_MIN:
        cands.append(("tilt", spd_y, cons_y, vy_s))
    if spd_z >= ZOOM_MIN_SPEED and cons_z >= CONS_MIN:
        ztype = "push_in" if float(zr_sm.mean()) > 1.0 else "pull_back"
        cands.append((ztype, spd_z, cons_z, zrate))

    if cands:
        # Enforce ONE motion: pick the highest (speed × consistency) candidate
        cands.sort(key=lambda c: c[1] * c[2], reverse=True)
        mtype, spd, _cons, arr = cands[0]

        if mtype in ("push_in", "pull_back"):
            # Zoom is global / gradual → use whole clip
            mi, mo = 0.0, dur
        else:
            # pan / tilt → longest consecutive same-sign run
            i, j, _ = _longest_run(arr)
            mi = float(t[i])
            mo = float(min(dur, t[j] + 1.0 / hz))
            if (mo - mi) < MIN_SPAN_S:
                mi, mo = 0.0, dur

        return dict(
            motion_type=mtype,
            motion_in=round(mi, 2),
            motion_out=round(mo, 2),
            motion_strength=round(spd, 2),
        )

    # No clean move: shaky/complex vs static
    if float(np.median(speed)) >= COMPLEX_SPEED:
        return dict(
            motion_type="complex",
            motion_in=0.0,
            motion_out=round(dur, 2),
            motion_strength=round(float(np.median(speed)), 2),
        )
    return dict(
        motion_type="static",
        motion_in=0.0,
        motion_out=round(dur, 2),
        motion_strength=round(float(np.median(speed)), 2),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def motion_features(path: str) -> dict:
    """Detect the dominant camera move in a video file.

    Parameters
    ----------
    path:
        Absolute path to a video file (any format OpenCV can decode).

    Returns
    -------
    dict with keys:
        motion_type   : "pan" | "tilt" | "push_in" | "pull_back" | "static" | "complex"
        motion_in     : float — start of the clean-move segment (seconds)
        motion_out    : float — end of the clean-move segment (seconds)
        motion_strength : float — robust median speed of the dominant axis (%/sec)

    Never raises — a bad clip returns the static fallback with ``motion_out``
    set to the clip duration (or 0 if duration cannot be read).
    """
    try:
        r = _estimate_motion_track(path)
        return _classify(r)
    except Exception:
        # Static fallback: determine duration best-effort
        duration = 0.0
        try:
            cap = cv2.VideoCapture(path)
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            cnt = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            cap.release()
            if fps > 0 and cnt > 0:
                duration = cnt / fps
        except Exception:
            pass
        return {
            "motion_type": "static",
            "motion_in": 0.0,
            "motion_out": duration,
            "motion_strength": 0.0,
        }
