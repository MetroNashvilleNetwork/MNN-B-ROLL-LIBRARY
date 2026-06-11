from broll_search.editor.filters import (
    color_filter, reframe_filter, conform_filter, clip_video_chain,
    LUT_FILES, LOOK_LUT,
)


def test_color_filter_sony_converts_then_looks():
    f = color_filter("sony_slog3", lut_dir="luts", look_strength=1.0)
    # conversion LUT first, then the look LUT, both tetrahedral
    assert f.index("luts/sony_slog3.cube") < f.index("luts/look_walkman.cube")
    assert "interp=tetrahedral" in f


def test_color_filter_rec709_skips_conversion():
    f = color_filter("rec709", lut_dir="luts", look_strength=1.0)
    assert "sony_slog3.cube" not in f and "dji_dlogm.cube" not in f
    assert "look_walkman.cube" in f  # look still applied


def test_reframe_vertical_dims():
    assert reframe_filter(1080, 1920) == (
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920")


def test_conform_filter_uses_fps():
    assert conform_filter("24000/1001") == "fps=24000/1001"


def test_clip_video_chain_order_and_format():
    chain = clip_video_chain("dji_dlogm", "luts", 1080, 1920, "24000/1001", 1.0)
    # color -> reframe -> conform -> 8-bit 4:2:0 at the end
    assert chain.index("dji_dlogm.cube") < chain.index("crop=1080:1920")
    assert chain.index("crop=1080:1920") < chain.index("fps=24000/1001")
    assert chain.endswith("format=yuv420p")
