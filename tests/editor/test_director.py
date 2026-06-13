from broll_search.editor.director import (
    DirectorCandidate, build_director_prompt, parse_director_edl, compose_edit,
    DirectorClient, EDL_RESPONSE_SCHEMA,
)
from broll_search.editor.music import MusicInfo
from broll_search.editor.edl import validate_edl


def _cands():
    return [
        DirectorCandidate(0, "FX6_a.mov", "p0.mp4", duration=10, fps=60, score=20, subject_x=0.4),
        DirectorCandidate(1, "DJI_b.mp4", "p1.mp4", duration=8, fps=30, score=15, subject_x=0.6),
    ]


def _music():
    return MusicInfo("m.wav", 30.0, 120.0, [i * 0.5 for i in range(61)])


def test_prompt_mentions_theme_and_clips():
    p = build_director_prompt("Parks", _cands(), _music(), 24)
    assert "Parks" in p and "Clip 0" in p and "Clip 1" in p and "JSON" in p


def test_parse_builds_edl_in_timeline_order():
    data = {"timeline": [
        {"clip_index": 1, "in": 1.0, "out": 3.0, "role": "hook", "subject_x": 0.7, "stabilize": True},
        {"clip_index": 0, "in": 2.0, "out": 3.5, "role": "closer"},
    ]}
    edl = parse_director_edl(data, _cands(), "t", _music(), default_profile="rec709")
    assert validate_edl(edl) == []
    assert [c.source for c in edl.clips] == ["DJI_b.mp4", "FX6_a.mov"]
    assert edl.clips[0].role == "hook" and edl.clips[0].subject_x == 0.7
    assert edl.clips[0].stabilize is True
    assert edl.clips[0].color_profile == "dji_dlogm"
    assert edl.clips[1].color_profile == "sony_slog3"


def test_parse_skips_invalid_entries():
    data = {"timeline": [
        {"clip_index": 9, "in": 0, "out": 1, "role": "hook"},   # index out of range
        {"clip_index": 0, "in": 3, "out": 2, "role": "body"},   # out <= in
        {"clip_index": 1, "in": 0, "out": 2, "role": "body"},   # valid
    ]}
    edl = parse_director_edl(data, _cands(), "t", _music())
    assert [c.source for c in edl.clips] == ["DJI_b.mp4"]


def test_parse_clamps_in_out_and_subject():
    data = {"timeline": [{"clip_index": 1, "in": -1, "out": 999, "role": "body", "subject_x": 5}]}
    edl = parse_director_edl(data, _cands(), "t", _music())
    c = edl.clips[0]
    assert c.in_point == 0.0 and c.out_point == 8.0 and c.subject_x == 1.0   # clamped to dur=8, sx<=1


def test_compose_edit_with_fake_client():
    class Fake(DirectorClient):
        def generate_edl(self, prompt, proxy_paths):
            assert "Parks" in prompt and len(proxy_paths) == 2
            return {"timeline": [{"clip_index": 0, "in": 0, "out": 2, "role": "hook"}]}

    edl = compose_edit("Parks", _cands(), _music(), Fake(), target_total=10)
    assert len(edl.clips) == 1 and edl.clips[0].source == "FX6_a.mov"


def test_schema_shape():
    assert EDL_RESPONSE_SCHEMA["type"] == "object"
    assert "timeline" in EDL_RESPONSE_SCHEMA["properties"]


def test_parse_sets_retime_and_source_fps():
    data = {"timeline": [
        {"clip_index": 0, "in": 0, "out": 1, "role": "hook", "retime": "slowmo"},
        {"clip_index": 1, "in": 0, "out": 2, "role": "body"},
    ]}
    edl = parse_director_edl(data, _cands(), "t", _music())
    assert edl.clips[0].retime == "slowmo" and edl.clips[0].source_fps == 60   # cand 0 fps=60
    assert edl.clips[1].retime == "normal"                                     # default


def test_parse_rejects_bad_retime():
    data = {"timeline": [{"clip_index": 0, "in": 0, "out": 1, "role": "hook", "retime": "weird"}]}
    edl = parse_director_edl(data, _cands(), "t", _music())
    assert edl.clips[0].retime == "normal"


def test_prompt_mentions_slowmo():
    assert "slow" in build_director_prompt("Parks", _cands(), _music(), 24).lower()


def test_schema_has_retime():
    props = EDL_RESPONSE_SCHEMA["properties"]["timeline"]["items"]["properties"]
    assert "retime" in props


def test_prompt_encodes_house_style():
    p = build_director_prompt("Parks", _cands(), _music(), 24).lower()
    assert "detail" in p or "macro" in p          # open on detail/prop
    assert "accelerat" in p                        # accelerating pace
    assert "hard cut" in p                         # hard cuts
    assert "sparing" in p or "rare" in p or "at most one" in p   # slow-mo restraint
    assert "shots" in p                            # shot-count guidance
