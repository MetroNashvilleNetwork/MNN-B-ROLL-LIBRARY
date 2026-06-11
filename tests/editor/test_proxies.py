import shutil
import subprocess
import pytest
from broll_search.editor.proxies import make_proxy, proxy_for

ffmpeg = shutil.which("ffmpeg")
ffprobe = shutil.which("ffprobe")
needs = pytest.mark.skipif(not (ffmpeg and ffprobe), reason="ffmpeg/ffprobe not available")


@needs
def test_make_proxy_downscales(tmp_path):
    src = tmp_path / "s.mp4"
    subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30",
                    "-t", "2", "-pix_fmt", "yuv420p", str(src)], check=True, capture_output=True)
    out = make_proxy(src, tmp_path / "p.mp4", ffmpeg_path=ffmpeg, height=240)
    assert out.exists() and out.stat().st_size > 0
    assert out.stat().st_size < src.stat().st_size           # proxy is smaller
    h = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=height", "-of", "csv=p=0", str(out)],
                       capture_output=True, text=True).stdout.strip()
    assert int(h) == 240


@needs
def test_proxy_for_caches(tmp_path):
    src = tmp_path / "s.mp4"
    subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
                    "-t", "1", "-pix_fmt", "yuv420p", str(src)], check=True, capture_output=True)
    cache = tmp_path / "cache"
    p1 = proxy_for(src, cache, ffmpeg_path=ffmpeg, height=180)
    mtime1 = p1.stat().st_mtime_ns
    p2 = proxy_for(src, cache, ffmpeg_path=ffmpeg, height=180)
    assert p1 == p2 and p2.stat().st_mtime_ns == mtime1       # reused, not regenerated
