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


def _make_clip(path, seconds, fps):
    subprocess.run([ffmpeg, "-y", "-f", "lavfi",
                    "-i", f"testsrc2=size=1280x720:rate={fps}",
                    "-t", str(seconds), "-pix_fmt", "yuv420p", str(path)], check=True)


def _make_tone(path, seconds):
    subprocess.run([ffmpeg, "-y", "-f", "lavfi",
                    "-i", "sine=frequency=440:sample_rate=44100",
                    "-t", str(seconds), str(path)], check=True)


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
    meta = json.loads(subprocess.run(
        [ffprobe, "-v", "quiet", "-print_format", "json", "-show_streams", str(out)],
        capture_output=True, text=True).stdout)
    vid = next(s for s in meta["streams"] if s["codec_type"] == "video")
    assert vid["width"] == 1080 and vid["height"] == 1920
    assert any(s["codec_type"] == "audio" for s in meta["streams"])
