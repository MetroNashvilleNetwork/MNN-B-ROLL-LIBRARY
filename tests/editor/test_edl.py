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
