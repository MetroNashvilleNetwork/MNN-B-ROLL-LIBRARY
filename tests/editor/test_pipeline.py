from broll_search.editor.probe import ClipInfo
from broll_search.editor.music import MusicInfo
from broll_search.editor.scout import ClipScout
from broll_search.editor import pipeline


def test_build_edl_from_inputs(monkeypatch):
    # Stub probing + music so this stays a fast unit test (no ffmpeg/librosa).
    infos = {
        "FX6_a.mov": ClipInfo("FX6_a.mov", 10, 3840, 2160, 23.976),
        "DJI_b.mp4": ClipInfo("DJI_b.mp4", 10, 3840, 2160, 59.94),
    }
    monkeypatch.setattr(pipeline, "probe_clip", lambda p, ffprobe_path="ffprobe": infos[p])
    beats = [i * 0.5 for i in range(33)]
    monkeypatch.setattr(pipeline, "analyze_music",
                        lambda p: MusicInfo(p, 16.0, 120.0, beats))

    edl = pipeline.build_edl(
        clip_paths=["FX6_a.mov", "DJI_b.mp4"], music_path="m.wav",
        theme="parks", target_total=4.0, default_profile="rec709",
        ffprobe_path="ffprobe")
    assert edl.theme == "parks"
    assert [c.color_profile for c in edl.clips][:2] == ["sony_slog3", "dji_dlogm"]


def test_find_media_lists_supported_files(tmp_path):
    (tmp_path / "a.MOV").write_bytes(b"x")
    (tmp_path / "b.mp4").write_bytes(b"x")
    (tmp_path / "notes.txt").write_bytes(b"x")
    found = pipeline.find_media(tmp_path, pipeline.VIDEO_EXTS)
    names = sorted(p.name for p in found)
    assert names == ["a.MOV", "b.mp4"]


def test_find_media_missing_dir_raises(tmp_path):
    import pytest
    with pytest.raises(RuntimeError):
        pipeline.find_media(tmp_path / "does_not_exist", pipeline.VIDEO_EXTS)


def test_build_edl_scored_ranks_by_quality(monkeypatch):
    scouts = {
        "a.mov": ClipScout("a.mov", score=2.0, best_in=0.0, best_out=2.0, duration=10, fps=24),
        "FX6_b.mov": ClipScout("FX6_b.mov", score=9.0, best_in=1.0, best_out=3.0, duration=10, fps=24),
    }
    monkeypatch.setattr(pipeline, "scout_clip_cached",
                        lambda p, cache, window=1.5: scouts[p])
    beats = [i * 0.5 for i in range(33)]
    monkeypatch.setattr(pipeline, "analyze_music",
                        lambda p: MusicInfo(p, 16.0, 120.0, beats))
    edl = pipeline.build_edl_scored(
        clip_paths=["a.mov", "FX6_b.mov"], music_path="m.wav", theme="parks",
        target_total=4.0, default_profile="rec709", cache={}, window=1.5)
    assert edl.clips[0].source == "FX6_b.mov"   # higher score becomes the hook
    assert edl.clips[0].role == "hook"


def test_build_edl_director_caps_and_uses_model(monkeypatch, tmp_path):
    from broll_search.editor.scout import ClipScout
    from broll_search.editor.director import DirectorClient
    scouts = {
        "FX6_a.mov": ClipScout("FX6_a.mov", 20, 0, 2, 10, 60, 0.4),
        "DJI_b.mp4": ClipScout("DJI_b.mp4", 15, 0, 2, 8, 30, 0.6),
        "FX6_c.mov": ClipScout("FX6_c.mov", 5, 0, 2, 9, 60, 0.5),
    }
    monkeypatch.setattr(pipeline, "scout_clip_cached", lambda p, cache, window=1.5: scouts[p])
    monkeypatch.setattr(pipeline, "proxy_for",
                        lambda p, d, ffmpeg_path="ffmpeg": tmp_path / (p + ".proxy"))
    monkeypatch.setattr(pipeline, "analyze_music",
                        lambda p: MusicInfo(p, 30.0, 120.0, [i * 0.5 for i in range(61)]))

    class Fake(DirectorClient):
        def __init__(self):
            self.seen = None
        def generate_edl(self, prompt, proxy_paths):
            self.seen = proxy_paths
            return {"timeline": [{"clip_index": 0, "in": 0, "out": 2, "role": "hook"}]}

    fake = Fake()
    edl = pipeline.build_edl_director(
        ["FX6_a.mov", "DJI_b.mp4", "FX6_c.mov"], "m.wav", "Parks",
        target_total=24, default_profile="rec709", cache={}, proxy_dir=tmp_path,
        ffmpeg_path="ffmpeg", client=fake, max_candidates=2)
    assert len(fake.seen) == 2                       # cost cap: only top-2 scored clips sent
    assert edl.clips[0].source == "FX6_a.mov"        # model picked candidate 0 (highest-scored)
