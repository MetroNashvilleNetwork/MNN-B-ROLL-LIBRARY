import numpy as np
from broll_search.editor.music import analyze_signal


def _click_track(bpm=120, sr=22050, seconds=8):
    """Synthesize clicks at a fixed BPM so beat tracking has a known answer."""
    y = np.zeros(int(sr * seconds), dtype=np.float32)
    interval = int(sr * 60.0 / bpm)
    for i in range(0, len(y), interval):
        y[i:i + 200] = 1.0  # short impulse
    return y, sr


def test_analyze_signal_detects_tempo_and_beats():
    y, sr = _click_track(bpm=120)
    tempo, beats = analyze_signal(y, sr)
    assert 110 <= tempo <= 130          # near 120 BPM
    assert len(beats) >= 8              # ~ one per beat over 8s
    assert all(b2 > b1 for b1, b2 in zip(beats, beats[1:]))  # increasing
