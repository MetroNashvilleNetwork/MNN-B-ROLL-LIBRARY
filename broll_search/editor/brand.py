"""MNN brand assets (palette, logo, font) — matched to the MNN Clip Namer."""

from __future__ import annotations

from pathlib import Path

from ..config import PROJECT_ROOT

# ffmpeg hex colors (0xRRGGBB) — from the Clip Namer's CSS custom properties.
NAVY = "0x08152b"       # --bg
INK = "0xf4f1e8"        # --ink (cream text)
BRONZE = "0xc89a5c"     # --bronze (accent)
SKY = "0x5bb1ff"        # --sky

LOGO_PATH = PROJECT_ROOT / "brand" / "mnn-logo.png"
WORDMARK = "Metro Nashville Network"

# Candidate clean-sans font files per OS (the brand uses Segoe UI / SF / Inter).
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/System/Library/Fonts/SFNS.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def brand_font(override: str = "") -> str:
    """Path to a clean sans matching the MNN brand.

    Resolution order:
    1. Explicit *override* path (if it exists).
    2. A bundled font at brand/fonts/brand.ttf (drop one in to lock the face).
    3. The OS's native clean sans from the candidate list above.
    """
    if override and Path(override).exists():
        return override
    bundled = PROJECT_ROOT / "brand" / "fonts" / "brand.ttf"
    if bundled.exists():
        return str(bundled)
    for cand in _FONT_CANDIDATES:
        if Path(cand).exists():
            return cand
    return ""
