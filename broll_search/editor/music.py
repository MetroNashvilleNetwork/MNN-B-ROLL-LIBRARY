"""Music analysis: beat grid, tempo, and duration via librosa."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np
import librosa


@dataclass
class MusicInfo:
    path: str
    duration: float
    tempo: float
    beats: List[float] = field(default_factory=list)  # beat times in seconds


def analyze_signal(y, sr) -> Tuple[float, List[float]]:
    """Return (tempo_bpm, beat_times_seconds) for an audio signal array."""
    tempo, beat_times = librosa.beat.beat_track(y=y, sr=sr, units="time")
    return float(np.atleast_1d(tempo)[0]), [float(b) for b in beat_times]


def analyze_music(path: str) -> MusicInfo:
    """Load an audio file and return its tempo, beat grid, and duration."""
    y, sr = librosa.load(path, sr=None, mono=True)
    duration = float(librosa.get_duration(y=y, sr=sr))
    tempo, beats = analyze_signal(y, sr)
    return MusicInfo(path=path, duration=duration, tempo=tempo, beats=beats)
