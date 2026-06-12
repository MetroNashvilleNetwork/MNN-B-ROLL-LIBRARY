import os
import shutil
import subprocess
from pathlib import Path

import pytest

from broll_search.editor import brand
from broll_search.editor.branding import escape_filter_path, make_card

ffmpeg = shutil.which("ffmpeg")
ffprobe = shutil.which("ffprobe")
needs = pytest.mark.skipif(not (ffmpeg and ffprobe), reason="ffmpeg/ffprobe not available")


def test_escape_filter_path_handles_windows_colon():
    assert escape_filter_path(r"C:\Windows\Fonts\segoeui.ttf") == "C\\:/Windows/Fonts/segoeui.ttf"
    assert escape_filter_path("/System/Library/Fonts/SFNS.ttf") == "/System/Library/Fonts/SFNS.ttf"


def test_brand_palette_and_logo_present():
    assert brand.NAVY.startswith("0x") and brand.INK.startswith("0x")
    assert Path(brand.LOGO_PATH).exists()              # logo bundled at brand/mnn-logo.png


def test_brand_font_resolves_to_existing_file():
    f = brand.brand_font()
    assert f and Path(f).exists()                      # a real font file on this OS


@needs
def test_make_card_renders_branded_vertical(tmp_path):
    out = tmp_path / "title.mp4"
    make_card(out, width=1080, height=1920, fps="24000/1001",
              title="Nashville Parks", subtitle="Metro Nashville Network",
              logo_path=str(brand.LOGO_PATH), font_path=brand.brand_font(),
              ffmpeg_path=ffmpeg, cwd=os.getcwd(), tmpdir=tmp_path, duration=1.5)
    assert out.exists() and out.stat().st_size > 0
    meta = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
                           "-show_entries", "stream=width,height", "-show_entries",
                           "format=duration", "-of", "default=noprint_wrappers=1", str(out)],
                          capture_output=True, text=True).stdout
    assert "width=1080" in meta and "height=1920" in meta
