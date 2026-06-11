import numpy as np
from broll_search.editor.analysis import sharpness, exposure_score, frame_quality, to_gray


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
