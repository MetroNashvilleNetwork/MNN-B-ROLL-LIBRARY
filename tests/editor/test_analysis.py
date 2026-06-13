import numpy as np
from broll_search.editor.analysis import (
    sharpness, exposure_score, frame_quality, to_gray, subject_x,
    _build_slog3_to_709_lut, _SLOG3_709, exposure_stats, TARGET_MID,
)


def _checkerboard(size=128, cell=8, lo=100, hi=160):
    """A sharp but well-exposed (mid-tone) checkerboard."""
    img = np.full((size, size), lo, dtype=np.uint8)
    for y in range(0, size, cell):
        for x in range(0, size, cell):
            if ((x // cell) + (y // cell)) % 2 == 0:
                img[y:y + cell, x:x + cell] = hi
    return img


def test_sharpness_higher_for_detailed_image():
    assert sharpness(_checkerboard()) > sharpness(np.full((128, 128), 128, dtype=np.uint8))


def test_exposure_score_penalizes_clipping():
    mid = np.full((64, 64), 128, dtype=np.uint8)
    black = np.zeros((64, 64), dtype=np.uint8)
    white = np.full((64, 64), 255, dtype=np.uint8)
    assert exposure_score(mid) > 0.9
    assert exposure_score(black) < 0.1
    assert exposure_score(white) < 0.1


def test_frame_quality_prefers_sharp_well_exposed_bgr():
    cb = _checkerboard()
    sharp_bgr = np.stack([cb, cb, cb], axis=-1)          # gray -> BGR
    dark_bgr = np.zeros((128, 128, 3), dtype=np.uint8)
    assert frame_quality(sharp_bgr) > frame_quality(dark_bgr)


def test_to_gray_passthrough_for_2d():
    g = np.zeros((10, 10), dtype=np.uint8)
    assert to_gray(g).shape == (10, 10)


def _detail_patch(size=200, side="left"):
    """A flat mid-gray frame with a high-detail checkerboard patch on one side."""
    img = np.full((size, size), 128, dtype=np.uint8)
    patch = _checkerboard(size=60, cell=6)
    if side == "left":
        img[70:130, 10:70] = patch
    else:
        img[70:130, size - 70:size - 10] = patch
    return img


def test_subject_x_leans_to_detail_side():
    assert subject_x(_detail_patch(side="left")) < 0.4
    assert subject_x(_detail_patch(side="right")) > 0.6


def test_subject_x_uniform_frame_is_centered():
    assert subject_x(np.full((100, 100), 128, dtype=np.uint8)) == 0.5


def test_subject_x_accepts_bgr():
    cb = _checkerboard()
    bgr = np.stack([cb, cb, cb], axis=-1)
    val = subject_x(bgr)
    assert 0.0 <= val <= 1.0


# ---------------------------------------------------------------------------
# S-Log3 -> 709 LUT tests
# ---------------------------------------------------------------------------

def test_slog3_lut_length():
    lut = _build_slog3_to_709_lut()
    assert lut.shape == (256,)


def test_slog3_lut_range():
    """All output values must be in [0, 1]."""
    lut = _build_slog3_to_709_lut()
    assert float(lut.min()) >= 0.0
    assert float(lut.max()) <= 1.0


def test_slog3_lut_monotonic():
    """LUT must be non-decreasing — higher S-Log3 code -> higher 709 value."""
    lut = _build_slog3_to_709_lut()
    assert np.all(np.diff(lut) >= -1e-12), "LUT is not monotonically non-decreasing"


def test_slog3_lut_grey_range():
    """S-Log3 middle grey (~95 code ≈ 37%) should map to a plausible 709 value
    (roughly 0.18 linear ≈ 0.46 709-gamma), well above 0 and below 1."""
    lut = _build_slog3_to_709_lut()
    # S-Log3 90% reflectance grey is code ~420/1023 ≈ index 105 (8-bit)
    midgrey_709 = lut[105]
    assert 0.35 < midgrey_709 < 0.75, f"Mid-grey 709 value {midgrey_709:.3f} out of plausible range"


def test_slog3_uint8_lut_dtype():
    assert _SLOG3_709.dtype == np.uint8
    assert _SLOG3_709.shape == (256,)


# ---------------------------------------------------------------------------
# TARGET_MID constant
# ---------------------------------------------------------------------------

def test_target_mid_value():
    assert TARGET_MID == 112


# ---------------------------------------------------------------------------
# exposure_stats synthetic-array tests
# ---------------------------------------------------------------------------

def _gray2d(value, size=64):
    """Return a flat 2-D grayscale array filled with *value*."""
    return np.full((size, size), value, dtype=np.uint8)


def _ramp_gray(size=256):
    """1-D ramp 0..255 tiled into a (256, 256) grayscale image."""
    row = np.arange(256, dtype=np.uint8)
    return np.tile(row, (size, 1))


def test_exposure_stats_all50_raw():
    """All-50 frame (no profile conversion): mean ~50, no highlight clip."""
    frame = _gray2d(50)
    stats = exposure_stats(frame, profile="raw")
    assert abs(stats["mean"] - 50.0) < 1.0
    assert stats["highlight_clip"] == 0.0
    assert stats["shadow_clip"] == 0.0


def test_exposure_stats_all200_raw():
    """All-200 frame: mean ~200, some highlight clip (200 < 250 so no clip)."""
    frame = _gray2d(200)
    stats = exposure_stats(frame, profile="raw")
    assert abs(stats["mean"] - 200.0) < 1.0
    assert stats["shadow_clip"] == 0.0
    assert stats["highlight_clip"] == 0.0  # 200 < 250, not clipped


def test_exposure_stats_all255_raw_has_highlight_clip():
    """All-255 frame: all pixels in the highlight clip bin."""
    frame = _gray2d(255)
    stats = exposure_stats(frame, profile="raw")
    assert stats["highlight_clip"] > 0.99


def test_exposure_stats_all0_raw_has_shadow_clip():
    """All-0 frame: all pixels in the shadow clip bin."""
    frame = _gray2d(0)
    stats = exposure_stats(frame, profile="raw")
    assert stats["shadow_clip"] > 0.99


def test_exposure_stats_ramp_raw():
    """Ramp 0..255: mean ~127, shadow and highlight clips both present."""
    frame = _ramp_gray()
    stats = exposure_stats(frame, profile="raw")
    assert 120.0 < stats["mean"] < 135.0
    assert stats["shadow_clip"] > 0.0
    assert stats["highlight_clip"] > 0.0


def test_exposure_stats_keys():
    """Must return exactly the four expected keys."""
    stats = exposure_stats(_gray2d(128), profile="raw")
    assert set(stats.keys()) == {"mean", "shadow_clip", "highlight_clip", "midtone"}


def test_exposure_stats_slog3_profile_applies_lut():
    """S-Log3 profile must produce a different (higher) mean than raw for a
    mid-code S-Log3 frame (e.g. code 100 in log space is dark in 709)."""
    # Code 100 is below the S-Log3 knee so it maps to a low 709 value;
    # code 160 is above the knee and maps to a mid-range 709 value.
    frame_lo = _gray2d(100)
    frame_hi = _gray2d(160)
    stats_lo_slog = exposure_stats(frame_lo, profile="sony_slog3")
    stats_hi_slog = exposure_stats(frame_hi, profile="sony_slog3")
    stats_lo_raw = exposure_stats(frame_lo, profile="raw")
    # LUT mapped value at code 160 must differ from the raw value (160)
    assert stats_hi_slog["mean"] != 160.0
    # Higher S-Log3 code -> higher 709 mean
    assert stats_hi_slog["mean"] > stats_lo_slog["mean"]
    # LUT pass changes the result vs raw for the same pixel value
    assert stats_lo_slog["mean"] != stats_lo_raw["mean"]


def test_exposure_stats_dji_dlogm_uses_slog3_lut():
    """dji_dlogm profile must apply the same LUT as sony_slog3."""
    frame = _gray2d(140)
    assert exposure_stats(frame, profile="dji_dlogm") == exposure_stats(frame, profile="sony_slog3")


def test_exposure_stats_unknown_profile_is_raw():
    """An unknown profile must NOT apply the LUT (treated as raw)."""
    frame = _gray2d(140)
    assert exposure_stats(frame, profile="unknown") == exposure_stats(frame, profile="raw")


def test_exposure_stats_bgr_input():
    """exposure_stats must accept a 3-channel BGR frame."""
    frame_gray = _gray2d(128)
    frame_bgr = np.stack([frame_gray, frame_gray, frame_gray], axis=-1)
    stats = exposure_stats(frame_bgr, profile="raw")
    assert abs(stats["mean"] - 128.0) < 1.0
