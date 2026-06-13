from broll_search.editor.filters import (
    color_filter, reframe_filter, conform_filter, clip_video_chain,
    LUT_FILES, LOOK_LUT, reframe_filter_anchored,
    exposure_filter, reframe_pushin_filter,
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
    # Without push, the chain uses scale+crop (no zoompan), then fps, then format.
    chain = clip_video_chain("dji_dlogm", "luts", 1080, 1920, "24000/1001", 1.0)
    assert "dji_dlogm.cube" in chain
    # convert cube precedes the reframe
    assert chain.index("dji_dlogm.cube") < chain.index("fps=24000/1001")
    # fps precedes format
    assert chain.index("fps=24000/1001") < chain.index("format=yuv420p")
    # format=yuv420p is last
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


def test_retime_optical_factor_has_no_interpolation():
    """Default (factor=0) uses the frame-exact 2.5x ratio, no interpolation."""
    f = retime_filter("slowmo", 60.0, "24000/1001")
    assert "2.5" in f and "minterpolate" not in f


def test_retime_higher_factor_adds_motion_interpolation():
    """A factor past the optical ratio adds minterpolate for smooth slower slow-mo."""
    f = retime_filter("slowmo", 60.0, "24000/1001", slowmo_factor=3.0)
    assert "setpts=3.0" in f and "minterpolate" in f and "mci" in f


def test_clip_video_chain_inserts_setpts_before_fps_when_slowmo():
    chain = clip_video_chain("rec709", "luts", 1080, 1920, "24000/1001",
                             retime="slowmo", source_fps=60.0)
    assert "setpts=" in chain
    assert chain.index("setpts=") < chain.index("fps=24000/1001")


def test_clip_chain_full_strength_is_linear():
    chain = clip_video_chain("sony_slog3", "luts", 1080, 1920, "24000/1001", look_strength=1.0)
    assert "split" not in chain and "blend" not in chain
    assert "sony_slog3.cube" in chain and "look_walkman.cube" in chain


def test_clip_chain_partial_strength_blends_look():
    chain = clip_video_chain("sony_slog3", "luts", 1080, 1920, "24000/1001", look_strength=0.4)
    assert "split" in chain and "blend=all_expr=" in chain
    assert "A*(1-0.4)+B*0.4" in chain
    assert "sony_slog3.cube" in chain and "look_walkman.cube" in chain
    assert chain.rstrip().endswith("format=yuv420p")


def test_clip_chain_zero_strength_drops_look():
    chain = clip_video_chain("sony_slog3", "luts", 1080, 1920, "24000/1001", look_strength=0.0)
    assert "look_walkman.cube" not in chain        # no look at all
    assert "sony_slog3.cube" in chain              # conversion still applied


# ---------------------------------------------------------------------------
# spec 5a — exposure_filter
# ---------------------------------------------------------------------------

def test_exposure_filter_none_when_small():
    """abs(adjust) < 0.04 returns empty string."""
    assert exposure_filter(0.0) == ""
    assert exposure_filter(0.03) == ""
    assert exposure_filter(-0.03) == ""


def test_exposure_filter_underexposed_lift():
    """Positive adjust (too dark) → eq with gamma>1 and gamma_weight<1."""
    f = exposure_filter(0.20)
    assert f.startswith("eq=gamma=")
    assert "gamma_weight=" in f
    assert "brightness=" in f
    # gamma > 1.0 for positive adjust
    gamma_val = float(f.split("eq=gamma=")[1].split(":")[0])
    assert gamma_val > 1.0


def test_exposure_filter_overexposed_tame():
    """Negative adjust (too bright) → eq with gamma<1 and gamma_weight=1.0."""
    f = exposure_filter(-0.20)
    assert "eq=gamma=" in f
    assert "gamma_weight=1.0" in f
    gamma_val = float(f.split("eq=gamma=")[1].split(":")[0])
    assert gamma_val < 1.0


def test_exposure_filter_highlight_clip_prefix():
    """highlight_clip > 0.02 prepends colorlevels ceiling."""
    f = exposure_filter(0.15, highlight_clip=0.05)
    assert f.startswith("colorlevels=rimax=0.94")
    assert "eq=gamma=" in f


def test_exposure_filter_highlight_clip_skipped_when_low():
    """highlight_clip <= 0.02 does NOT add colorlevels prefix."""
    f = exposure_filter(0.15, highlight_clip=0.01)
    assert not f.startswith("colorlevels")
    assert f.startswith("eq=gamma=")


def test_exposure_filter_clamps_adjust():
    """adjust is clamped to [-0.45, 0.45]; extreme values still produce output."""
    f_high = exposure_filter(2.0)
    f_low = exposure_filter(-2.0)
    assert f_high != ""
    assert f_low != ""
    # gamma_weight for strong positive adjust (>0.20) uses 0.55 gw
    gw_high = float(f_high.split("gamma_weight=")[1].split(":")[0])
    assert abs(gw_high - 0.55) < 0.001


# ---------------------------------------------------------------------------
# spec 5b — reframe_pushin_filter
# ---------------------------------------------------------------------------

def test_reframe_pushin_no_push_fixed_z():
    """push==0 => z='1.0' (no animation)."""
    f = reframe_pushin_filter(1080, 1920, push=0.0, n_frames=100)
    assert "zoompan=" in f
    assert "z='1.0'" in f


def test_reframe_pushin_push_gt0_cosine_z():
    """push>0 => z expression contains cosine ease-in-out."""
    f = reframe_pushin_filter(1080, 1920, push=0.07, n_frames=150)
    assert "zoompan=" in f
    assert "cos(" in f
    assert "1.0+" in f or "1.0 +" in f.replace("1.0+", "1.0 +")


def test_reframe_pushin_contains_escaped_clip():
    """x expression uses escaped commas for the filtergraph parser."""
    f = reframe_pushin_filter(1080, 1920)
    assert "\\," in f


def test_reframe_pushin_prescale_prefix():
    """prescale_h > 0 prepends a scale filter before zoompan."""
    f = reframe_pushin_filter(1080, 1920, prescale_h=2160)
    assert f.startswith("scale=-2:2160:flags=lanczos,")
    assert "zoompan=" in f


def test_reframe_pushin_no_prescale():
    """prescale_h == 0 means no leading scale filter."""
    f = reframe_pushin_filter(1080, 1920, prescale_h=0)
    assert f.startswith("zoompan=")


def test_reframe_pushin_fps_is_source_rate():
    """zoompan fps= matches the source rate (not the timeline rate)."""
    f = reframe_pushin_filter(1080, 1920, src_fps=60000/1001)
    # 60000/1001 * 1000 rounded = 59940
    assert "fps=59940/1000" in f


# ---------------------------------------------------------------------------
# spec 5c — clip_video_chain canonical order
# ---------------------------------------------------------------------------

def test_chain_exposure_between_convert_and_look():
    """eq filter lands after convert LUT but before look LUT."""
    chain = clip_video_chain("sony_slog3", "luts", 1080, 1920, "24000/1001",
                             look_strength=1.0, exposure_adjust=0.20)
    assert "eq=gamma=" in chain
    assert chain.index("sony_slog3.cube") < chain.index("eq=gamma=")
    assert chain.index("eq=gamma=") < chain.index("look_walkman.cube")


def test_chain_zoompan_before_setpts_before_fps():
    """zoompan precedes setpts which precedes format (push>0 activates zoompan).
    When push>0, zoompan's internal fps handles conform so no external fps= follows.
    The canonical order is: zoompan -> setpts -> format=yuv420p."""
    chain = clip_video_chain("sony_slog3", "luts", 1080, 1920, "24000/1001",
                             look_strength=1.0, retime="slowmo", source_fps=60.0,
                             push=0.07, n_frames=60)
    assert "zoompan=" in chain
    assert "setpts=" in chain
    assert chain.index("zoompan=") < chain.index("setpts=")
    assert chain.index("setpts=") < chain.index("format=yuv420p")


def test_chain_push_zero_gives_no_zoompan():
    """push==0 => reframe_filter_anchored (scale+crop) is used, no zoompan."""
    chain = clip_video_chain("rec709", "luts", 1080, 1920, "24000/1001",
                             push=0.0, n_frames=100)
    assert "zoompan=" not in chain
    assert "crop=w=1080:h=1920" in chain


def test_chain_push_gt0_gives_z_1_when_no_animation():
    """push>0 activates zoompan; push==0 but prescale also activates it."""
    chain = clip_video_chain("rec709", "luts", 1080, 1920, "24000/1001",
                             push=0.0, n_frames=0, prescale_h=2160)
    assert "zoompan=" in chain
    assert "z='1.0'" in chain


def test_chain_blend_path_exposure_shared():
    """Blend path: exposure eq appears before split so BOTH branches see it."""
    chain = clip_video_chain("sony_slog3", "luts", 1080, 1920, "24000/1001",
                             look_strength=0.4, exposure_adjust=0.25)
    # chain should have eq before split
    assert "eq=gamma=" in chain
    assert "split" in chain
    assert chain.index("eq=gamma=") < chain.index("split")


def test_chain_format_yuv420p_is_last():
    """format=yuv420p is always the final element."""
    for strength in (0.0, 0.4, 1.0):
        chain = clip_video_chain("sony_slog3", "luts", 1080, 1920, "24000/1001",
                                 look_strength=strength)
        assert chain.endswith("format=yuv420p"), f"Failed for strength={strength}"


def test_chain_no_exposure_when_adjust_tiny():
    """No exposure eq in chain when exposure_adjust is below threshold."""
    chain = clip_video_chain("sony_slog3", "luts", 1080, 1920, "24000/1001",
                             look_strength=1.0, exposure_adjust=0.02, saturation=1.0)
    assert "eq=" not in chain


def test_chain_includes_saturation_by_default():
    """The grade adds a saturation boost by default (Gibby: 'add some saturation')."""
    chain = clip_video_chain("sony_slog3", "luts", 1080, 1920, "24000/1001", look_strength=0.4)
    assert "eq=saturation=1.2" in chain


def test_chain_saturation_disabled_at_unity():
    chain = clip_video_chain("sony_slog3", "luts", 1080, 1920, "24000/1001",
                             look_strength=0.4, saturation=1.0)
    assert "saturation" not in chain
