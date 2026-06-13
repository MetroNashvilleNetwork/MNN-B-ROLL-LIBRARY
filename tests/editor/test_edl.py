from broll_search.editor.edl import Clip, EDL, validate_edl


def _clip(**kw):
    base = dict(id=1, source="a.mov", in_point=0.0, out_point=2.0,
                color_profile="rec709", role="hook")
    base.update(kw)
    return Clip(**base)


def test_clip_duration():
    assert _clip(in_point=1.0, out_point=3.5).duration == 2.5


def test_valid_edl_has_no_errors():
    edl = EDL(theme="parks", music="m.wav", clips=[_clip()])
    assert validate_edl(edl) == []


def test_empty_edl_is_invalid():
    edl = EDL(theme="parks", music="m.wav", clips=[])
    assert any("no clips" in e for e in validate_edl(edl))


def test_bad_inout_is_invalid():
    edl = EDL(theme="parks", music="m.wav", clips=[_clip(in_point=2.0, out_point=1.0)])
    assert any("out_point" in e for e in validate_edl(edl))


def test_unknown_profile_is_invalid():
    edl = EDL(theme="parks", music="m.wav", clips=[_clip(color_profile="bogus")])
    assert any("color_profile" in e for e in validate_edl(edl))


def test_clip_stabilize_defaults_false_and_is_settable():
    assert _clip().stabilize is False
    assert _clip(stabilize=True).stabilize is True


def test_clip_retime_defaults():
    c = _clip()
    assert c.retime == "normal" and c.source_fps == 0.0
    assert _clip(retime="slowmo", source_fps=60.0).retime == "slowmo"


def test_clip_new_fields_default_correctly():
    c = _clip()
    assert c.exposure_adjust == 0.0
    assert c.highlight_clip == 0.0
    assert c.motion_type == "static"
    assert c.push_in == 0.0


def test_clip_new_fields_are_settable():
    c = _clip(exposure_adjust=0.25, highlight_clip=0.05,
              motion_type="pan", push_in=0.07)
    assert c.exposure_adjust == 0.25
    assert c.highlight_clip == 0.05
    assert c.motion_type == "pan"
    assert c.push_in == 0.07


def test_clip_new_fields_negative_exposure():
    c = _clip(exposure_adjust=-0.30)
    assert c.exposure_adjust == -0.30


def test_clip_new_fields_all_motion_types():
    for mt in ("pan", "tilt", "push_in", "pull_back", "static", "complex"):
        c = _clip(motion_type=mt)
        assert c.motion_type == mt
