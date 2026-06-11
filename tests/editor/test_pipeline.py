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
