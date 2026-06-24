from broll_search.editor.autonomy import (
    EditCuration,
    build_curator_prompt,
    curate_edit,
    parse_curation,
    probe_music_options,
)
from broll_search.editor.autonomy import MusicOption
from broll_search.editor.scout import ClipScout


class FakeCurator:
    def generate_json(self, prompt, schema):
        assert "Footage scout summary" in prompt
        return {
            "theme": "Nashville Nights",
            "theme_sentence": "City lights and live music downtown.",
            "pacing_style": "cinematic_slow",
            "music_index": 1,
            "music_rationale": "Slower tempo matches moody footage.",
        }


def test_parse_curation_picks_track():
    opts = [
        MusicOption("a.wav", 120.0, 128.0),
        MusicOption("b.wav", 90.0, 82.0),
    ]
    c = parse_curation({"theme": "T", "pacing_style": "social_punchy", "music_index": 1}, opts)
    assert c.music_path == "b.wav"
    assert c.pacing_style == "social_punchy"


def test_curate_edit_with_fake_client(monkeypatch):
    scouts = [
        ClipScout("c1.mov", 8.0, 0.0, 2.0, 10.0, 60.0, motion_type="pan", motion_strength=4.0),
        ClipScout("c2.mov", 6.0, 0.0, 2.0, 8.0, 60.0, motion_type="static"),
    ]
    monkeypatch.setattr(
        "broll_search.editor.autonomy.probe_music_options",
        lambda paths: [MusicOption(p, 60.0, 100.0) for p in paths],
    )
    result = curate_edit(FakeCurator(), scouts, ["a.wav", "b.wav"], 35.0)
    assert isinstance(result, EditCuration)
    assert result.theme == "Nashville Nights"
    assert result.music_path == "b.wav"
    assert result.pacing_style == "cinematic_slow"


def test_build_curator_prompt_includes_scouts():
    scouts = [ClipScout("FX6_a.mov", 9.0, 0.0, 2.0, 12.0, 60.0)]
    prompt = build_curator_prompt(scouts, [MusicOption("m.wav", 30.0, 120.0)], 35.0)
    assert "FX6_a.mov" in prompt and "[0]" in prompt
