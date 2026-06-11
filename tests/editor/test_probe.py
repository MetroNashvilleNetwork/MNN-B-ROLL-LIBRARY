import json
from broll_search.editor import probe
from broll_search.editor.probe import _parse_fps, ClipInfo


def test_parse_fps_fraction():
    assert round(_parse_fps("60000/1001"), 2) == 59.94


def test_parse_fps_integer():
    assert _parse_fps("30") == 30.0


def test_parse_fps_zero_denominator_is_zero():
    assert _parse_fps("30/0") == 0.0


def test_probe_clip_parses_ffprobe_json(monkeypatch):
    fake = json.dumps({
        "format": {"duration": "12.5"},
        "streams": [{"codec_type": "video", "width": 3840, "height": 2160,
                     "r_frame_rate": "60000/1001"}],
    })

    class _Proc:
        returncode = 0
        stdout = fake

    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **k: _Proc())
    info = probe.probe_clip("anything.mov", ffprobe_path="ffprobe")
    assert info == ClipInfo(path="anything.mov", duration=12.5,
                            width=3840, height=2160, fps=round(60000 / 1001, 6))
