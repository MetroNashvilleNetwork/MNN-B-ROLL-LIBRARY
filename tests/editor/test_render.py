import shutil
import subprocess
import json
from pathlib import Path

import pytest

from broll_search.editor.edl import Clip, EDL
from broll_search.editor.render import render_format

ffmpeg = shutil.which("ffmpeg")
ffprobe = shutil.which("ffprobe")
pytestmark = pytest.mark.skipif(not (ffmpeg and ffprobe),
                                reason="ffmpeg/ffprobe not available")


def _make_clip(path, seconds, fps, name="FX6_x"):
    subprocess.run([ffmpeg, "-y", "-f", "lavfi",
                    "-i", f"testsrc2=size=1280x720:rate={fps}",
                    "-t", str(seconds), "-pix_fmt", "yuv420p", str(path)], check=True)


def _make_tone(path, seconds):
    subprocess.run([ffmpeg, "-y", "-f", "lavfi",
                    "-i", "sine=frequency=440:sample_rate=44100",
                    "-t", str(seconds), str(path)], check=True)


def _ffprobe_json(path):
    result = subprocess.run(
        [ffprobe, "-v", "quiet", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def test_render_vertical_produces_playable_mp4(tmp_path):
    a, b = tmp_path / "FX6_a.mp4", tmp_path / "DJI_b.mp4"
    _make_clip(a, 3, 60)
    _make_clip(b, 3, 30)
    music = tmp_path / "m.wav"
    _make_tone(music, 10)

    edl = EDL(theme="t", music=str(music), clips=[
        Clip(1, str(a), 0.0, 1.5, "rec709", "hook"),
        Clip(2, str(b), 0.0, 1.0, "rec709", "closer"),
    ])
    out = tmp_path / "vertical.mp4"
    render_format(edl, out, width=1080, height=1920, lut_dir="luts",
                  ffmpeg_path=ffmpeg, tmpdir=tmp_path)

    assert out.exists() and out.stat().st_size > 0
    meta = _ffprobe_json(out)
    vid = next(s for s in meta["streams"] if s["codec_type"] == "video")
    assert vid["width"] == 1080 and vid["height"] == 1920
    assert any(s["codec_type"] == "audio" for s in meta["streams"])


def test_render_is_cwd_independent(tmp_path, monkeypatch):
    """LUTs must resolve via PROJECT_ROOT, not the process cwd."""
    # Change to a directory that has no luts/ subdir
    monkeypatch.chdir(tmp_path)

    clip_path = tmp_path / "FX6_x.mp4"
    _make_clip(clip_path, 2, 30)
    music = tmp_path / "m.wav"
    _make_tone(music, 10)

    edl = EDL(theme="t", music=str(music), clips=[
        Clip(1, str(clip_path), 0.0, 1.5, "sony_slog3", "hook"),
    ])
    out = tmp_path / "out_cwd_test.mp4"
    # Do NOT pass cwd — must default to PROJECT_ROOT so luts/ resolves
    render_format(edl, out, width=1080, height=1920, lut_dir="luts",
                  ffmpeg_path=ffmpeg, tmpdir=tmp_path)

    assert out.exists() and out.stat().st_size > 0
    meta = _ffprobe_json(out)
    vid = next(s for s in meta["streams"] if s["codec_type"] == "video")
    assert vid["width"] == 1080 and vid["height"] == 1920


def test_render_duration_uses_shortest(tmp_path):
    """Output duration should be clipped to video length, not the 10 s tone."""
    a = tmp_path / "FX6_a.mp4"
    b = tmp_path / "FX6_b.mp4"
    _make_clip(a, 2, 30)
    _make_clip(b, 1, 30)
    music = tmp_path / "long.wav"
    _make_tone(music, 10)

    edl = EDL(theme="t", music=str(music), clips=[
        Clip(1, str(a), 0.0, 1.5, "rec709", "hook"),
        Clip(2, str(b), 0.0, 1.0, "rec709", "closer"),
    ])
    out = tmp_path / "shortest.mp4"
    render_format(edl, out, width=1080, height=1920, lut_dir="luts",
                  ffmpeg_path=ffmpeg, tmpdir=tmp_path)

    meta = _ffprobe_json(out)
    duration = float(meta["format"]["duration"])
    assert duration < 4.0, f"Expected duration < 4 s, got {duration:.2f} s"


def test_empty_edl_raises():
    """render_format must raise ValueError immediately when EDL has no clips."""
    edl = EDL(theme="t", music="m.wav", clips=[])
    with pytest.raises(ValueError, match="no clips"):
        render_format(edl, Path("/tmp/never.mp4"), width=1080, height=1920)


def _ffprobe_duration(path):
    out = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip()
    return float(out)


def test_render_slowmo_stretches_duration(tmp_path):
    src = tmp_path / "FX6_60.mp4"
    subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=60",
                    "-t", "3", "-pix_fmt", "yuv420p", str(src)], check=True, capture_output=True)
    music = tmp_path / "m.wav"
    _make_tone(music, 20)
    edl = EDL(theme="t", music=str(music), clips=[
        Clip(1, str(src), 0.0, 1.0, "rec709", "hook", retime="slowmo", source_fps=60.0)])
    out = tmp_path / "v.mp4"
    render_format(edl, out, 1080, 1920, lut_dir="luts", ffmpeg_path=ffmpeg, tmpdir=tmp_path)
    # 1.0s of 60fps source, slowed by ~2.5x -> ~2.5s on screen
    assert 2.2 < _ffprobe_duration(out) < 2.8


def test_render_with_branding_adds_cards(tmp_path):
    a = tmp_path / "FX6_a.mp4"
    _make_clip(a, 3, 60)
    music = tmp_path / "m.wav"
    _make_tone(music, 30)
    edl = EDL(theme="Nashville Parks", music=str(music), clips=[
        Clip(1, str(a), 0.0, 1.5, "rec709", "hook"),
        Clip(2, str(a), 0.0, 1.0, "rec709", "closer")])
    out = tmp_path / "branded.mp4"
    render_format(edl, out, 1080, 1920, lut_dir="luts", ffmpeg_path=ffmpeg,
                  tmpdir=tmp_path, brand_enabled=True)
    assert out.exists()
    # clips total ~2.5s; title+outro cards add ~3s -> well over 4s
    assert _ffprobe_duration(out) > 4.0


from broll_search.editor.render import stabilization_mode


def test_stabilization_mode_detects_a_filter():
    mode = stabilization_mode(ffmpeg)          # this build has at least deshake
    assert mode in ("vidstab", "deshake")


def test_render_stabilized_clip_succeeds(tmp_path):
    src = tmp_path / "shaky.mp4"
    # a moving test source so a stabilizer has something to do
    subprocess.run([ffmpeg, "-y", "-f", "lavfi",
                    "-i", "testsrc2=size=1280x720:rate=30", "-t", "2",
                    "-vf", "crop=in_w/1.2:in_h/1.2:x=10*sin(n/3):y=10*cos(n/3)",
                    "-pix_fmt", "yuv420p", str(src)], check=True, capture_output=True)
    music = tmp_path / "m.wav"
    _make_tone(music, 10)
    edl = EDL(theme="t", music=str(music), clips=[
        Clip(1, str(src), 0.0, 1.5, "rec709", "hook", stabilize=True)])
    out = tmp_path / "v.mp4"
    render_format(edl, out, 1080, 1920, lut_dir="luts", ffmpeg_path=ffmpeg, tmpdir=tmp_path)
    assert out.exists() and out.stat().st_size > 0       # stabilized clip rendered cleanly


def test_render_partial_look_strength_runs(tmp_path):
    src = tmp_path / "FX6.mp4"
    _make_clip(src, 2, 30)
    music = tmp_path / "m.wav"
    _make_tone(music, 10)
    edl = EDL(theme="t", music=str(music), clips=[Clip(1, str(src), 0.0, 1.5, "sony_slog3", "hook")])
    out = tmp_path / "v.mp4"
    render_format(edl, out, 1080, 1920, lut_dir="luts", ffmpeg_path=ffmpeg,
                  tmpdir=tmp_path, look_strength=0.4)
    assert out.exists() and out.stat().st_size > 0
