from broll_search.editor.profiles import profile_for


def test_sony_filename_maps_to_slog3():
    assert profile_for("/x/FX6_Aaron_clip01.mov", default="rec709") == "sony_slog3"


def test_dji_filename_maps_to_dlogm():
    assert profile_for("/x/DJI_Osmo_Pocket3_walk.mp4", default="rec709") == "dji_dlogm"


def test_unknown_uses_default():
    assert profile_for("/x/random_clip.mov", default="sony_slog3") == "sony_slog3"
