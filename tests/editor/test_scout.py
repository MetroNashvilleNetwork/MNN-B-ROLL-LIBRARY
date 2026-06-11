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

    def fake_scout(path, window=1.5, n=12):
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


def test_scout_records_median_subject_x(monkeypatch):
    import numpy as np
    frames = [(0.0, np.zeros((4, 4, 3), np.uint8)),
              (1.0, np.zeros((4, 4, 3), np.uint8)),
              (2.0, np.zeros((4, 4, 3), np.uint8))]
    monkeypatch.setattr(scout_mod, "sample_frames", lambda path, n=12: (24.0, 3.0, frames))
    xs = iter([0.2, 0.8, 0.5])
    monkeypatch.setattr(scout_mod, "frame_subject_x", lambda f: next(xs))
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
