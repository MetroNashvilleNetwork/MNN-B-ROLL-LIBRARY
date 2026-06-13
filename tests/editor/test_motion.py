"""Unit tests for broll_search.editor.motion.

Synthetic video clips are generated via ffmpeg (must be on PATH).
The pan clip uses testsrc2 + crop with a time-varying x offset to produce
a clean horizontal camera-pan signal.  The static clip uses a solid grey
color source — no feature motion at all.
"""

from __future__ import annotations

import os
import subprocess
import tempfile

import numpy as np
import pytest

from broll_search.editor.motion import (
    PAN_MIN_SPEED,
    ZOOM_MIN_SPEED,
    CONS_MIN,
    COMPLEX_SPEED,
    MIN_SPAN_S,
    _med,
    _consistency,
    _longest_run,
    _classify,
    motion_features,
)


# ---------------------------------------------------------------------------
# Helper: synthetic clip factory
# ---------------------------------------------------------------------------

def _make_clip(vf_filter: str, duration: float = 3.0, fps: int = 30) -> str:
    """Return a temp path to an H.264 clip built from the given lavfi filtergraph."""
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"testsrc2=size=640x360:rate={fps}:duration={duration}",
        "-vf", vf_filter,
        "-an",
        path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


def _make_static_clip(duration: float = 3.0, fps: int = 30) -> str:
    """Solid grey colour source — no motion whatsoever."""
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=gray:size=640x360:rate={fps}:duration={duration}",
        "-an",
        path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


# ---------------------------------------------------------------------------
# Unit tests — pure helper functions (no video I/O)
# ---------------------------------------------------------------------------

class TestMed:
    def test_passthrough_short_array(self):
        a = np.array([1.0])
        np.testing.assert_array_equal(_med(a), a)

    def test_kills_spike(self):
        """A single large spike in the middle should be suppressed."""
        a = np.array([1.0, 1.0, 100.0, 1.0, 1.0])
        out = _med(a, k=5)
        assert out[2] < 10.0, f"Spike not suppressed: {out[2]}"

    def test_preserves_trend(self):
        """A monotonically increasing array should remain monotonically non-decreasing."""
        a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        out = _med(a)
        assert np.all(np.diff(out) >= 0)

    def test_length_preserved(self):
        a = np.arange(20, dtype=float)
        assert len(_med(a)) == len(a)


class TestConsistency:
    def test_monotone_is_one(self):
        """A perfectly monotone array has consistency ~1.0."""
        v = np.array([1.0, 1.0, 1.0, 1.0, 1.0])
        assert _consistency(v) == pytest.approx(1.0)

    def test_alternating_is_low(self):
        """An alternating-sign array cancels itself → near 0."""
        v = np.array([1.0, -1.0, 1.0, -1.0, 1.0, -1.0])
        assert _consistency(v) < 0.3

    def test_zero_array_returns_zero(self):
        v = np.zeros(5)
        assert _consistency(v) == 0.0

    def test_range(self):
        """Consistency is always in [0, 1]."""
        rng = np.random.default_rng(42)
        v = rng.standard_normal(50)
        c = _consistency(v)
        assert 0.0 <= c <= 1.0


class TestLongestRun:
    def test_all_positive(self):
        v = np.array([1.0, 2.0, 3.0])
        i, j, net = _longest_run(v)
        assert i == 0 and j == 2
        assert net == pytest.approx(6.0)

    def test_single_element(self):
        v = np.array([5.0])
        i, j, net = _longest_run(v)
        assert i == 0 and j == 0

    def test_split_picks_larger(self):
        """[ +, +, -, - ] — positive run sums 3, negative run sums 10."""
        v = np.array([1.0, 2.0, -4.0, -6.0])
        i, j, net = _longest_run(v)
        assert net == pytest.approx(10.0)
        assert i == 2 and j == 3

    def test_sign_boundary(self):
        """Zero-values should be treated as continuing the current run."""
        v = np.array([1.0, 0.0, 1.0, -1.0])
        i, j, _ = _longest_run(v)
        # First three elements form a same-sign run (0 extends +1)
        assert i == 0 and j == 2


# ---------------------------------------------------------------------------
# Unit tests — _classify with synthetic track dictionaries (no video I/O)
# ---------------------------------------------------------------------------

def _make_track(
    vx=None, vy=None, zr=None,
    n=40, fps=30.0, hz=8.0, duration=5.0,
):
    """Build a minimal track dict for _classify."""
    t = np.linspace(0, duration * (n - 1) / n, n)
    vx = np.asarray(vx if vx is not None else np.zeros(n))
    vy = np.asarray(vy if vy is not None else np.zeros(n))
    zr = np.asarray(zr if zr is not None else np.ones(n))
    return dict(fps=fps, duration=duration, hz=hz,
                t=t, vx=vx, vy=vy, zr=zr, inliers=np.full(n, 20))


class TestClassify:
    def test_none_returns_static(self):
        result = _classify(None)
        assert result["motion_type"] == "static"
        assert result["motion_in"] == 0.0
        assert result["motion_strength"] == 0.0

    def test_too_few_samples_static(self):
        """< 4 samples → static fallback."""
        r = _make_track(n=3)
        result = _classify(r)
        assert result["motion_type"] == "static"

    def test_clean_pan_synthetic(self):
        """Constant vx above threshold + high consistency → pan."""
        n = 40
        # vx = 0.03 per-step → vx_s = 0.03 * 8 * 100 = 24 %/s → above PAN_MIN_SPEED
        vx = np.full(n, 0.03)
        r = _make_track(vx=vx, n=n)
        result = _classify(r)
        assert result["motion_type"] == "pan"
        assert result["motion_strength"] > PAN_MIN_SPEED
        # Span should be set
        assert result["motion_out"] > result["motion_in"]

    def test_clean_tilt_synthetic(self):
        """Constant vy above threshold → tilt."""
        n = 40
        vy = np.full(n, -0.04)  # downward tilt; sign doesn't matter for type
        r = _make_track(vy=vy, n=n)
        result = _classify(r)
        assert result["motion_type"] == "tilt"

    def test_push_in_synthetic(self):
        """scale > 1 + high consistency → push_in."""
        n = 40
        # scale per-step = 1.003 → zrate = (1.003-1)*8*100 = 2.4 %/s > ZOOM_MIN_SPEED
        zr = np.full(n, 1.003)
        r = _make_track(zr=zr, n=n)
        result = _classify(r)
        assert result["motion_type"] == "push_in"
        # push_in uses whole clip
        assert result["motion_in"] == pytest.approx(0.0)
        assert result["motion_out"] == pytest.approx(5.0)

    def test_pull_back_synthetic(self):
        """scale < 1 consistently → pull_back."""
        n = 40
        zr = np.full(n, 0.997)  # shrinking
        r = _make_track(zr=zr, n=n)
        result = _classify(r)
        assert result["motion_type"] == "pull_back"

    def test_complex_high_speed_low_consistency(self):
        """High speed but random directions → complex."""
        rng = np.random.default_rng(0)
        n = 60
        # vx alternates sign at high amplitude: speed high, consistency ~0
        vx = rng.choice([-0.08, 0.08], size=n)
        r = _make_track(vx=vx, n=n)
        result = _classify(r)
        assert result["motion_type"] == "complex"

    def test_static_low_speed(self):
        """Very small random motion below thresholds → static."""
        rng = np.random.default_rng(1)
        n = 40
        vx = rng.uniform(-0.0001, 0.0001, n)
        vy = rng.uniform(-0.0001, 0.0001, n)
        r = _make_track(vx=vx, vy=vy, n=n)
        result = _classify(r)
        assert result["motion_type"] == "static"

    def test_pan_wins_over_weaker_tilt(self):
        """When both pan and tilt qualify, the stronger one wins."""
        n = 40
        vx = np.full(n, 0.05)   # strong pan
        vy = np.full(n, 0.02)   # weaker but still maybe qualifying tilt
        r = _make_track(vx=vx, vy=vy, n=n)
        result = _classify(r)
        # Pan is stronger; the one motion rule must pick pan
        assert result["motion_type"] == "pan"

    def test_result_keys(self):
        r = _make_track(n=40)
        result = _classify(r)
        assert set(result.keys()) == {
            "motion_type", "motion_in", "motion_out", "motion_strength"
        }

    def test_motion_out_ge_motion_in(self):
        """motion_out must always be >= motion_in."""
        for seed in range(5):
            rng = np.random.default_rng(seed)
            n = 40
            vx = rng.standard_normal(n) * 0.02
            vy = rng.standard_normal(n) * 0.02
            r = _make_track(vx=vx, vy=vy, n=n)
            res = _classify(r)
            assert res["motion_out"] >= res["motion_in"], \
                f"out < in for seed={seed}: {res}"

    def test_push_in_whole_clip_span(self):
        """push_in / pull_back always span the whole clip."""
        n = 40
        zr = np.full(n, 1.002)
        r = _make_track(zr=zr, n=n, duration=4.0)
        result = _classify(r)
        assert result["motion_type"] == "push_in"
        assert result["motion_in"] == pytest.approx(0.0)
        assert result["motion_out"] == pytest.approx(4.0)

    def test_short_run_falls_back_to_whole_clip(self):
        """If the longest same-sign run is shorter than MIN_SPAN_S, use whole clip."""
        n = 40
        # Two equal-length alternating sections: neither run is long enough
        # (each ~0.625 s at 8 Hz, n=5 per half — but let's make them clearly short)
        vx = np.concatenate([np.full(3, 0.04), np.full(3, -0.04), np.full(34, 0.04)])
        r = _make_track(vx=vx, n=40, duration=5.0)
        result = _classify(r)
        if result["motion_type"] == "pan":
            # The long run (34 steps) is >>MIN_SPAN_S; span should cover it
            assert (result["motion_out"] - result["motion_in"]) >= MIN_SPAN_S

    def test_static_complex_span_is_whole_clip(self):
        """static and complex always set motion_in=0 and motion_out=duration."""
        n = 40
        r = _make_track(n=n, duration=6.0)  # zero motion → static
        res = _classify(r)
        assert res["motion_in"] == pytest.approx(0.0)
        assert res["motion_out"] == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# Integration tests — synthetic video files (require ffmpeg)
# ---------------------------------------------------------------------------

class TestMotionFeaturesSyntheticVideo:
    """Create synthetic clips via ffmpeg and verify end-to-end classification."""

    @pytest.fixture(scope="class")
    def pan_clip(self):
        """testsrc2 with a linearly translating crop → clean horizontal pan."""
        # x offset moves at 50 px/frame on a 640-wide source → obvious pan
        path = _make_clip("crop=480:360:t*50:0", duration=3.0, fps=30)
        yield path
        os.unlink(path)

    @pytest.fixture(scope="class")
    def static_clip(self):
        """Solid grey colour — zero optical flow → static."""
        path = _make_static_clip(duration=3.0, fps=30)
        yield path
        os.unlink(path)

    def test_pan_clip_classifies_as_pan(self, pan_clip):
        result = motion_features(pan_clip)
        assert result["motion_type"] == "pan", \
            f"Expected 'pan', got {result['motion_type']!r}. Full: {result}"

    def test_pan_clip_strength_above_threshold(self, pan_clip):
        result = motion_features(pan_clip)
        assert result["motion_strength"] >= PAN_MIN_SPEED, \
            f"motion_strength {result['motion_strength']} below PAN_MIN_SPEED"

    def test_pan_clip_span_covers_most_of_clip(self, pan_clip):
        result = motion_features(pan_clip)
        span = result["motion_out"] - result["motion_in"]
        assert span >= MIN_SPAN_S

    def test_static_clip_classifies_as_static(self, static_clip):
        result = motion_features(static_clip)
        assert result["motion_type"] == "static", \
            f"Expected 'static', got {result['motion_type']!r}. Full: {result}"

    def test_static_clip_motion_in_is_zero(self, static_clip):
        result = motion_features(static_clip)
        assert result["motion_in"] == pytest.approx(0.0)

    def test_static_clip_motion_out_equals_duration(self, static_clip):
        result = motion_features(static_clip)
        assert result["motion_out"] == pytest.approx(3.0, abs=0.2)

    def test_result_has_all_keys(self, pan_clip):
        result = motion_features(pan_clip)
        assert set(result.keys()) == {
            "motion_type", "motion_in", "motion_out", "motion_strength"
        }

    def test_motion_out_ge_motion_in(self, pan_clip):
        result = motion_features(pan_clip)
        assert result["motion_out"] >= result["motion_in"]

    def test_motion_type_is_valid_string(self, static_clip):
        valid = {"pan", "tilt", "push_in", "pull_back", "static", "complex"}
        result = motion_features(static_clip)
        assert result["motion_type"] in valid

    def test_motion_strength_is_non_negative(self, static_clip):
        result = motion_features(static_clip)
        assert result["motion_strength"] >= 0.0


# ---------------------------------------------------------------------------
# Robustness / error handling
# ---------------------------------------------------------------------------

class TestMotionFeaturesRobustness:
    def test_nonexistent_file_returns_static(self):
        """A missing file must return the static fallback without raising."""
        result = motion_features("/nonexistent/path/clip.mp4")
        assert result["motion_type"] == "static"
        assert result["motion_in"] == 0.0
        assert result["motion_strength"] == 0.0

    def test_empty_string_path_returns_static(self):
        result = motion_features("")
        assert result["motion_type"] == "static"

    def test_return_type_is_dict(self):
        result = motion_features("/nonexistent.mp4")
        assert isinstance(result, dict)

    def test_all_keys_present_on_fallback(self):
        result = motion_features("/nonexistent.mp4")
        assert set(result.keys()) == {
            "motion_type", "motion_in", "motion_out", "motion_strength"
        }
