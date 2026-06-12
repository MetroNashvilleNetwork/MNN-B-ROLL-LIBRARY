"""Branded title/outro cards for the MNN Auto-Editor (navy + cream + logo).

Card layout (9:16 vertical, navy bg):
  ┌──────────────────────────────┐
  │                              │
  │      [MNN logo, ~20%w]       │  centred at H*0.30
  │                              │
  │  Title text (cream, 6.2%h)   │  centred at H*0.52
  │  Subtitle  (bronze, 3.0%h)   │  below title
  │                              │
  └──────────────────────────────┘

Text is composited via OpenCV onto a PNG frame (which avoids any dependency on
ffmpeg's optional libfreetype/drawtext filter). The composited PNG is then
looped into an MP4 via ffmpeg.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import cv2
import numpy as np

from . import brand


# ---------------------------------------------------------------------------
# Hex colour string  →  BGR tuple for OpenCV
# ---------------------------------------------------------------------------

def _hex_to_bgr(hex_color: str) -> tuple[int, int, int]:
    """Convert '0xRRGGBB' or '#RRGGBB' to an OpenCV BGR tuple."""
    h = hex_color.lstrip("0x").lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b, g, r)  # OpenCV is BGR


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
# Internal compositing helpers (OpenCV)
# ---------------------------------------------------------------------------

def _paste_rgba(canvas: np.ndarray, overlay: np.ndarray, cx: int, cy: int) -> None:
    """Alpha-composite *overlay* (BGRA) onto *canvas* (BGR) centred at (cx, cy).

    Clips to canvas bounds so nothing explodes if the overlay is larger.
    """
    oh, ow = overlay.shape[:2]
    ch, cw = canvas.shape[:2]

    x0 = cx - ow // 2
    y0 = cy - oh // 2

    # Compute the intersection in canvas coordinates
    x1c = max(x0, 0)
    y1c = max(y0, 0)
    x2c = min(x0 + ow, cw)
    y2c = min(y0 + oh, ch)
    if x2c <= x1c or y2c <= y1c:
        return

    # Corresponding slice in the overlay
    x1o = x1c - x0
    y1o = y1c - y0
    x2o = x1o + (x2c - x1c)
    y2o = y1o + (y2c - y1c)

    roi = canvas[y1c:y2c, x1c:x2c]
    ov_crop = overlay[y1o:y2o, x1o:x2o]

    alpha = ov_crop[:, :, 3:4].astype(np.float32) / 255.0
    bgr = ov_crop[:, :, :3].astype(np.float32)
    roi_f = roi.astype(np.float32)
    blended = (bgr * alpha + roi_f * (1.0 - alpha)).clip(0, 255).astype(np.uint8)
    canvas[y1c:y2c, x1c:x2c] = blended


def _put_text_centred(
    canvas: np.ndarray,
    text: str,
    y_px: int,
    font_scale: float,
    color_bgr: tuple,
    thickness: int = 2,
) -> None:
    """Draw *text* horizontally centred on *canvas* at vertical position *y_px*."""
    font = cv2.FONT_HERSHEY_DUPLEX
    (tw, th), _ = cv2.getTextSize(text, font, font_scale, thickness)
    x = (canvas.shape[1] - tw) // 2
    # y in OpenCV is the *baseline*, so shift down by one text-height
    cv2.putText(canvas, text, (x, y_px + th), font, font_scale, color_bgr, thickness,
                cv2.LINE_AA)


def _composite_card(
    width: int,
    height: int,
    logo_path: str,
    title: str,
    subtitle: str,
) -> np.ndarray:
    """Return a (height, width, 3) BGR numpy array — the card frame."""
    # Navy background
    bg_bgr = _hex_to_bgr(brand.NAVY)
    canvas = np.full((height, width, 3), bg_bgr, dtype=np.uint8)

    base = min(width, height)
    logo_w = int(base * 0.20)
    title_fs_px = int(base * 0.062)   # font-size in pixels
    sub_fs_px = int(base * 0.030)

    # --- Logo (BGRA, alpha-composited) ---
    logo_bgra = cv2.imread(str(logo_path), cv2.IMREAD_UNCHANGED)
    if logo_bgra is not None:
        # Ensure 4-channel BGRA
        if logo_bgra.ndim == 2:
            logo_bgra = cv2.cvtColor(logo_bgra, cv2.COLOR_GRAY2BGRA)
        elif logo_bgra.shape[2] == 3:
            logo_bgra = cv2.cvtColor(logo_bgra, cv2.COLOR_BGR2BGRA)
        # Scale to logo_w, preserve aspect ratio
        lh_orig, lw_orig = logo_bgra.shape[:2]
        lh_new = int(logo_w * lh_orig / lw_orig)
        logo_bgra = cv2.resize(logo_bgra, (logo_w, lh_new), interpolation=cv2.INTER_LANCZOS4)
        # Centre horizontally; vertical centre at H*0.30
        cx = width // 2
        cy = int(height * 0.30)
        _paste_rgba(canvas, logo_bgra, cx, cy)

    # --- Title text (cream) ---
    # Scale from pixel font-size to OpenCV font_scale: approximate mapping
    # OpenCV FONT_HERSHEY_DUPLEX at scale=1.0 produces ~18px tall glyphs.
    title_scale = title_fs_px / 26.0
    sub_scale = sub_fs_px / 26.0

    title_y = int(height * 0.52)
    if title:
        ink_bgr = _hex_to_bgr(brand.INK)
        _put_text_centred(canvas, title, title_y, title_scale, ink_bgr, thickness=2)

    # --- Subtitle text (bronze) ---
    sub_y = title_y + title_fs_px + 24
    if subtitle:
        bronze_bgr = _hex_to_bgr(brand.BRONZE)
        _put_text_centred(canvas, subtitle, sub_y, sub_scale, bronze_bgr, thickness=1)

    return canvas


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
    """Render a branded card MP4: navy background, centred logo, cream title,
    bronze subtitle.

    Used for both the opening title card and the closing outro.

    Parameters
    ----------
    out_path:   Destination MP4 path.
    width/height: Frame size in pixels.
    fps:        ffmpeg rate string, e.g. "24000/1001" or "30".
    title:      Main headline (cream).
    subtitle:   Secondary line (bronze), shown below the title.
    logo_path:  Absolute path to the MNN logo PNG.
    font_path:  Absolute path to a font file (used when drawtext is available;
                here, text is composited via OpenCV so this parameter is
                accepted but not required at runtime).
    ffmpeg_path: Path to the ffmpeg binary.
    cwd:        Working directory for the ffmpeg subprocess.
    tmpdir:     Directory for temporary files (PNG frame).
    duration:   Card duration in seconds (default 1.6).
    """
    out_path = Path(out_path)
    tmpdir = Path(tmpdir)
    tmpdir.mkdir(parents=True, exist_ok=True)

    # --- 1. Composite the card frame with OpenCV ----------------------------
    frame = _composite_card(width, height, logo_path, title, subtitle)

    png_path = tmpdir / "card_frame.png"
    ok = cv2.imwrite(str(png_path), frame)
    if not ok:
        raise RuntimeError(f"cv2.imwrite failed: {png_path}")

    # --- 2. Encode the PNG into an MP4 via ffmpeg ---------------------------
    # filter_complex:
    #   [0:v] format=yuv420p [out]
    # Input 0: the composited PNG, looped for the full duration.
    filter_complex = "[0:v]format=yuv420p[out]"

    cmd = [
        ffmpeg_path, "-y",
        "-loop", "1",
        "-i", str(png_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-r", fps,
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-pix_fmt", "yuv420p",
        "-t", str(duration),
        str(out_path),
    ]

    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        timeout=120,
        **_run_kwargs(),
    )
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "ignore")[-1500:]
        raise RuntimeError(f"card render failed ({proc.returncode}):\n{err}")

    return out_path
