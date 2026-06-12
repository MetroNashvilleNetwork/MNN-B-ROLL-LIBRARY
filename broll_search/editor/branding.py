"""Branded title/outro cards for the MNN Auto-Editor (navy + cream + logo).

Card layout (9:16 vertical, navy bg):
  ┌──────────────────────────────┐
  │                              │
  │      [MNN logo, ~22%w]       │  centred at H*0.30
  │                              │
  │  Title text (cream, 6.4%h)   │  centred at H*0.52
  │  Subtitle  (bronze, 3.0%h)   │  below title
  │                              │
  └──────────────────────────────┘

Text is composited via Pillow (real brand font) onto a PNG frame, which avoids
any dependency on ffmpeg's optional libfreetype/drawtext filter. The composited
PNG is then looped into an MP4 via ffmpeg.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import brand


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def escape_filter_path(p: str) -> str:
    """Make a filesystem path safe inside an ffmpeg filtergraph.

    ffmpeg filtergraph parsing splits on ':' (option separator) and '\\'.
    Normalise to forward slashes, then escape any remaining colon (Windows
    drive letter) as '\\:'.
    """
    # 1. Replace all backslashes with forward slashes.
    safe = str(p).replace("\\", "/")
    # 2. Escape colons (drive letter on Windows: C:/ -> C\\:/).
    safe = safe.replace(":", "\\:")
    return safe


def _run_kwargs() -> dict:
    """Subprocess kwargs that suppress the console window on Windows."""
    kwargs: dict = {"capture_output": True}
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = si
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return kwargs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def make_card(
    out_path,
    width: int,
    height: int,
    fps: str,
    title: str,
    subtitle: str,
    logo_path: str,
    font_path: str,
    ffmpeg_path: str,
    cwd,
    tmpdir,
    duration: float = 1.6,
) -> Path:
    """Render a branded card (navy bg, centered logo, cream title, bronze subtitle)
    with Pillow, then loop it into a short video clip. Used for title + outro."""
    from PIL import Image, ImageDraw, ImageFont

    out_path = Path(out_path)
    tmpdir = Path(tmpdir)
    tmpdir.mkdir(parents=True, exist_ok=True)
    base = min(width, height)

    img = Image.new("RGB", (width, height), (8, 21, 43))   # MNN navy #08152b
    draw = ImageDraw.Draw(img)

    if logo_path and Path(logo_path).exists():
        logo = Image.open(logo_path).convert("RGBA")
        lw = int(base * 0.22)
        lh = max(1, int(lw * logo.height / logo.width))
        logo = logo.resize((lw, lh))
        img.paste(logo, ((width - lw) // 2, int(height * 0.30 - lh / 2)), logo)

    def _centered(text, size, fill, y):
        if not text:
            return
        font = ImageFont.truetype(font_path, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((width - tw) // 2, y), text, font=font, fill=fill)

    title_size = int(base * 0.064)
    sub_size = int(base * 0.030)
    _centered(title, title_size, (244, 241, 232), int(height * 0.52))           # cream
    _centered(subtitle, sub_size, (200, 154, 92), int(height * 0.52) + title_size + 24)  # bronze

    png = tmpdir / "card.png"
    img.save(str(png))

    cmd = [ffmpeg_path, "-y", "-loop", "1", "-i", str(png), "-t", str(duration),
           "-r", fps, "-c:v", "libx264", "-crf", "18", "-preset", "medium",
           "-pix_fmt", "yuv420p", str(out_path)]
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, timeout=120, **_run_kwargs())
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "ignore")[-1500:]
        raise RuntimeError(f"card render failed ({proc.returncode}):\n{err}")
    return out_path
