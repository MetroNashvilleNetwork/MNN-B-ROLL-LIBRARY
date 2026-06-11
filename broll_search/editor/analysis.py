"""Frame-level quality metrics for clip scouting (OpenCV).

Pure functions on image arrays so they unit-test without video files.
Higher = better (sharper, better-exposed)."""

from __future__ import annotations

import cv2
import numpy as np


def to_gray(frame: np.ndarray) -> np.ndarray:
    """BGR uint8 frame -> single-channel grayscale (2-D input passes through)."""
    if frame.ndim == 2:
        return frame
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def sharpness(gray: np.ndarray) -> float:
    """Focus measure = variance of the Laplacian. Higher = sharper / more in focus."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def exposure_score(gray: np.ndarray) -> float:
    """Fraction of pixels NOT clipped to near-black or near-white.
    1.0 = nothing crushed or blown out; lower = more clipping."""
    total = gray.size
    if total == 0:
        return 0.0
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).ravel()
    clipped = float(hist[:6].sum() + hist[250:].sum())
    return 1.0 - clipped / total


def frame_quality(frame: np.ndarray) -> float:
    """Combined relative quality of a single frame (higher = better):
    sharpness scaled by how well-exposed the frame is."""
    g = to_gray(frame)
    return sharpness(g) * exposure_score(g)
