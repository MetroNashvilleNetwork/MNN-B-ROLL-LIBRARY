import shutil
import subprocess
import pytest
from broll_search.editor import scout as scout_mod
from broll_search.editor.scout import (
    scout_clip, scout_clip_cached, ClipScout, load_cache, save_cache,
)

ffmpeg = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(not ffmpeg, reason="ffmpeg not available")


@needs_ffmpeg
def test_scout_finds_sharp_window(tmp_path):
    sharp, blur, clip = tmp_path / "sharp.mp4", tmp_path / "blur.mp4", tmp_path / "clip.mp4"
    subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
                    "-t", "2", "-pix_fmt", "yuv420p", str(sharp)], check=True, capture_output=True)
    subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
                    "-t", "2", "-vf", "boxblur=12", "-pix_fmt", "yuv420p", str(blur)],
                   check=True, capture_output=True)
    lst = tmp_path / "l.txt"
    lst.write_text(f"file '{sharp}'\nfile '{blur}'\n")
    subprocess.run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(clip)], check=True, capture_output=True)

    sc = scout_clip(str(clip), window=1.0, n=16)
    assert sc.duration > 3.0
    assert sc.best_in < 2.0          # best moment is in the sharp first half
    assert sc.best_out > sc.best_in
    assert sc.score > 0


def test_scout_cache_reuses_result(tmp_path, monkeypatch):
    f = tmp_path / "x.mp4"
    f.write_bytes(b"stand-in bytes")
    cache = {}
    sentinel = ClipScout(path=str(f), score=1.23, best_in=0.0, best_out=1.5,
                         duration=4.0, fps=30.0)
    calls = {"n": 0}

    def fake_scout(path, window=1.5, n=12, profile="sony_slog3"):
        calls["n"] += 1
        return sentinel

    monkeypatch.setattr(scout_mod, "scout_clip", fake_scout)
    a = scout_clip_cached(str(f), cache)
    b = scout_clip_cached(str(f), cache)
    assert calls["n"] == 1           # second call served from cache, not re-scouted
    assert a == b == sentinel
    assert str(f) in cache


def test_cache_roundtrip(tmp_path):
    p = tmp_path / "c.json"
    save_cache(p, {"a": {"_key": "1", "path": "a", "score": 1.0, "best_in": 0.0,
                         "best_out": 1.0, "duration": 2.0, "fps": 30.0}})
    assert load_cache(p)["a"]["score"] == 1.0
    assert load_cache(tmp_path / "missing.json") == {}


def _fake_motion(path):
    return {"motion_type": "static", "motion_in": 0.0, "motion_out": 3.0,
            "motion_strength": 0.0}


def _fake_exposure_stats(frame, profile="sony_slog3"):
    return {"mean": 112.0, "midtone": 112.0, "shadow_clip": 0.0, "highlight_clip": 0.0}


def test_scout_records_median_subject_x(monkeypatch):
    import numpy as np
    frames = [(0.0, np.zeros((4, 4, 3), np.uint8)),
              (1.0, np.zeros((4, 4, 3), np.uint8)),
              (2.0, np.zeros((4, 4, 3), np.uint8))]
    monkeypatch.setattr(scout_mod, "sample_frames", lambda path, n=12: (24.0, 3.0, frames))
    xs = iter([0.2, 0.8, 0.5])
    monkeypatch.setattr(scout_mod, "frame_subject_x", lambda f: next(xs))
    monkeypatch.setattr(scout_mod, "exposure_stats", _fake_exposure_stats)
    monkeypatch.setattr(scout_mod, "motion_features", _fake_motion)
    sc = scout_mod.scout_clip("x.mp4", window=1.0)
    assert sc.subject_x == 0.5   # median of [0.2, 0.8, 0.5]


@needs_ffmpeg
def test_scout_subject_x_in_range(tmp_path):
    import subprocess
    clip = tmp_path / "c.mp4"
    subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
                    "-t", "2", "-pix_fmt", "yuv420p", str(clip)], check=True, capture_output=True)
    sc = scout_clip(str(clip), window=1.0, n=8)
    assert 0.0 <= sc.subject_x <= 1.0


# ---------------------------------------------------------------------------
# FILE 3 — new exposure + motion fields
# ---------------------------------------------------------------------------

def test_old_cache_json_loads_without_new_keys(tmp_path):
    """Old cache JSON (without the 8 new fields) must still load via defaults."""
    p = tmp_path / "cache.json"
    # Minimal record as written by the pre-rebuild scout (no exp_* / motion_* keys)
    old_record = {
        "_key": "999:12345",
        "path": "/some/old/clip.mp4",
        "score": 0.85,
        "best_in": 0.0,
        "best_out": 1.5,
        "duration": 5.0,
        "fps": 59.94,
    }
    save_cache(p, {"/some/old/clip.mp4": old_record})
    loaded = load_cache(p)
    fields = {k: v for k, v in loaded["/some/old/clip.mp4"].items() if k != "_key"}
    # Must construct without raising — defaults fill missing keys
    sc = ClipScout(**fields)
    assert sc.exp_mean == 112.0
    assert sc.exp_midtone == 112.0
    assert sc.exp_shadow_clip == 0.0
    assert sc.exp_highlight_clip == 0.0
    assert sc.motion_type == "static"
    assert sc.motion_in == 0.0
    assert sc.motion_out == 0.0
    assert sc.motion_strength == 0.0


def test_scout_clip_writes_all_new_fields(monkeypatch):
    """A fresh scout call populates all 8 new exposure + motion fields."""
    import numpy as np
    frames = [
        (0.0, np.full((4, 4, 3), 80, dtype=np.uint8)),
        (1.0, np.full((4, 4, 3), 90, dtype=np.uint8)),
    ]
    monkeypatch.setattr(scout_mod, "sample_frames", lambda path, n=12: (30.0, 2.0, frames))
    monkeypatch.setattr(scout_mod, "frame_subject_x", lambda f: 0.5)

    def fake_exp(frame, profile="sony_slog3"):
        return {"mean": 85.0, "midtone": 80.0, "shadow_clip": 0.01, "highlight_clip": 0.02}

    def fake_mot(path):
        return {"motion_type": "pan", "motion_in": 0.5, "motion_out": 1.8,
                "motion_strength": 5.3}

    monkeypatch.setattr(scout_mod, "exposure_stats", fake_exp)
    monkeypatch.setattr(scout_mod, "motion_features", fake_mot)

    sc = scout_mod.scout_clip("fake.mp4", window=1.0)
    assert sc.exp_mean == 85.0
    assert sc.exp_midtone == 80.0
    assert sc.exp_shadow_clip == 0.01
    assert sc.exp_highlight_clip == 0.02
    assert sc.motion_type == "pan"
    assert sc.motion_in == 0.5
    assert sc.motion_out == 1.8
    assert sc.motion_strength == 5.3


def test_scout_exposure_aggregation(monkeypatch):
    """exp_mean/midtone = median of per-frame values; clip fracs = max (worst case)."""
    import numpy as np
    frames = [
        (0.0, np.zeros((4, 4, 3), dtype=np.uint8)),
        (1.0, np.zeros((4, 4, 3), dtype=np.uint8)),
        (2.0, np.zeros((4, 4, 3), dtype=np.uint8)),
    ]
    monkeypatch.setattr(scout_mod, "sample_frames", lambda path, n=12: (30.0, 3.0, frames))
    monkeypatch.setattr(scout_mod, "frame_subject_x", lambda f: 0.5)

    per_frame = [
        {"mean": 100.0, "midtone": 95.0, "shadow_clip": 0.02, "highlight_clip": 0.01},
        {"mean": 120.0, "midtone": 115.0, "shadow_clip": 0.05, "highlight_clip": 0.00},
        {"mean": 110.0, "midtone": 105.0, "shadow_clip": 0.01, "highlight_clip": 0.03},
    ]
    it = iter(per_frame)
    monkeypatch.setattr(scout_mod, "exposure_stats", lambda f, profile="sony_slog3": next(it))
    monkeypatch.setattr(scout_mod, "motion_features", _fake_motion)

    sc = scout_mod.scout_clip("fake.mp4", window=1.0)
    # median of [100, 120, 110] = 110
    assert sc.exp_mean == 110.0
    # median of [95, 115, 105] = 105
    assert sc.exp_midtone == 105.0
    # max shadow_clip
    assert sc.exp_shadow_clip == 0.05
    # max highlight_clip
    assert sc.exp_highlight_clip == 0.03


def test_scout_profile_threaded_to_exposure_stats(monkeypatch):
    """The profile param is forwarded to exposure_stats for each frame."""
    import numpy as np
    frames = [(0.0, np.zeros((4, 4, 3), dtype=np.uint8))]
    monkeypatch.setattr(scout_mod, "sample_frames", lambda path, n=12: (30.0, 1.0, frames))
    monkeypatch.setattr(scout_mod, "frame_subject_x", lambda f: 0.5)
    monkeypatch.setattr(scout_mod, "motion_features", _fake_motion)

    seen_profiles = []

    def capturing_exp(frame, profile="sony_slog3"):
        seen_profiles.append(profile)
        return {"mean": 112.0, "midtone": 112.0, "shadow_clip": 0.0, "highlight_clip": 0.0}

    monkeypatch.setattr(scout_mod, "exposure_stats", capturing_exp)
    scout_mod.scout_clip("fake.mp4", window=1.0, profile="dji_dlogm")
    assert seen_profiles == ["dji_dlogm"]


def test_scout_clip_cached_threads_profile(tmp_path, monkeypatch):
    """scout_clip_cached forwards the profile param to scout_clip."""
    f = tmp_path / "v.mp4"
    f.write_bytes(b"bytes")
    cache = {}
    seen = []

    def fake_scout(path, window=1.5, n=12, profile="sony_slog3"):
        seen.append(profile)
        return ClipScout(path=path, score=0.0, best_in=0.0, best_out=1.0,
                         duration=2.0, fps=30.0)

    monkeypatch.setattr(scout_mod, "scout_clip", fake_scout)
    scout_clip_cached(str(f), cache, profile="dji_dlogm")
    assert seen == ["dji_dlogm"]


def test_scout_motion_out_defaults_to_duration_when_zero(monkeypatch):
    """If motion_features returns motion_out==0, scout uses duration instead."""
    import numpy as np
    frames = [(0.0, np.zeros((4, 4, 3), dtype=np.uint8))]
    monkeypatch.setattr(scout_mod, "sample_frames", lambda path, n=12: (30.0, 5.0, frames))
    monkeypatch.setattr(scout_mod, "frame_subject_x", lambda f: 0.5)
    monkeypatch.setattr(scout_mod, "exposure_stats", _fake_exposure_stats)

    def mot_zero_out(path):
        return {"motion_type": "static", "motion_in": 0.0, "motion_out": 0.0,
                "motion_strength": 0.0}

    monkeypatch.setattr(scout_mod, "motion_features", mot_zero_out)
    sc = scout_mod.scout_clip("fake.mp4", window=1.0)
    assert sc.motion_out == 5.0   # fell back to duration
