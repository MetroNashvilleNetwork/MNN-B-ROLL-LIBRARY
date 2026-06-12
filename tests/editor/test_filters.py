from broll_search.editor.filters import (
    color_filter, reframe_filter, conform_filter, clip_video_chain,
    LUT_FILES, LOOK_LUT, reframe_filter_anchored,
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
    assert chain.index("dji_dlogm.cube") < chain.index("crop=w=1080:h=1920")
    assert chain.index("crop=w=1080:h=1920") < chain.index("fps=24000/1001")
    assert chain.endswith("format=yuv420p")


def test_reframe_anchored_uses_subject_and_escapes_commas():
    f = reframe_filter_anchored(1080, 1920, 0.75)
    assert f.startswith("scale=1080:1920:force_original_aspect_ratio=increase,crop=w=1080:h=1920:")
    assert "0.75*iw-1080/2" in f
    assert "\\," in f                       # commas inside clip() are escaped
    assert "y=(ih-1920)/2" in f


def test_reframe_anchored_clamps_subject():
    assert "1.0*iw" in reframe_filter_anchored(1080, 1920, 5.0)    # clamped high -> 1.0
    assert "0.0*iw" in reframe_filter_anchored(1080, 1920, -3.0)   # clamped low -> 0.0


from broll_search.editor.filters import retime_filter, _fps_to_float


def test_fps_to_float():
    assert round(_fps_to_float("24000/1001"), 3) == 23.976
    assert _fps_to_float("30") == 30.0


def test_retime_filter_slowmo_60fps():
    f = retime_filter("slowmo", 60.0, "24000/1001")
    assert f.startswith("setpts=") and "PTS" in f
    # factor ~ 60/23.976 = 2.5
    assert "2.5" in f


def test_retime_filter_normal_or_lowfps_is_empty():
    assert retime_filter("normal", 60.0, "24000/1001") == ""
    assert retime_filter("slowmo", 24.0, "24000/1001") == ""   # not high-fps -> no slow


def test_clip_video_chain_inserts_setpts_before_fps_when_slowmo():
    chain = clip_video_chain("rec709", "luts", 1080, 1920, "24000/1001",
                             retime="slowmo", source_fps=60.0)
    assert "setpts=" in chain
    assert chain.index("setpts=") < chain.index("fps=24000/1001")
