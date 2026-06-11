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


_FACE_CASCADE = None


def _face_cascade():
    """Lazily load the bundled frontal-face Haar cascade (empty if unavailable)."""
    global _FACE_CASCADE
    if _FACE_CASCADE is None:
        try:
            _FACE_CASCADE = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        except Exception:
            _FACE_CASCADE = cv2.CascadeClassifier()
    return _FACE_CASCADE


def subject_x(frame: np.ndarray) -> float:
    """Normalized horizontal center (0..1) of the main subject:
    largest frontal face if found, else the gradient-energy centroid
    (cheap saliency proxy), else 0.5 (frame center)."""
    g = to_gray(frame)
    h, w = g.shape[:2]
    if w == 0:
        return 0.5
    cascade = _face_cascade()
    if cascade is not None and not cascade.empty():
        faces = cascade.detectMultiScale(g, scaleFactor=1.2, minNeighbors=5)
        if len(faces):
            fx, _, fw, _ = max(faces, key=lambda f: int(f[2]) * int(f[3]))
            return float((fx + fw / 2.0) / w)
    lap = np.abs(cv2.Laplacian(g, cv2.CV_64F))
    M = cv2.moments(lap)
    if M["m00"] > 0:
        return float((M["m10"] / M["m00"]) / w)
    return 0.5
