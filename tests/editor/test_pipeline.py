import pytest

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
                        lambda p, cache, window=1.5, **kw: scouts[p])
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
    monkeypatch.setattr(pipeline, "scout_clip_cached",
                        lambda p, cache, window=1.5, **kw: scouts[p])
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
    assert len(fake.seen) == 2                       # cost cap: only top-2 SCORED clips sent
    # top-2 by score are FX6_a + DJI_b; candidates are then ordered CHRONOLOGICALLY
    # (by filename), so index 0 = "DJI_b.mp4" (D < F). Model picked candidate 0.
    assert edl.clips[0].source == "DJI_b.mp4"


# ---------------------------------------------------------------------------
# 8a — build_edl_director copies measured motion/exposure onto candidates
# ---------------------------------------------------------------------------

def test_director_copies_motion_and_exposure_from_scout(monkeypatch, tmp_path):
    """build_edl_director must copy motion_type, exp_mean (and friends) from
    ClipScout onto DirectorCandidate so the director post-pass has real data.
    A pan scout with exp_mean=60 should produce a clip with motion_type='pan'
    and a positive exposure_adjust (underexposed → lift)."""
    from broll_search.editor.director import DirectorClient

    # Scout with real-move + dark exposure
    sc = ClipScout(
        "FX6_a.mov", score=20, best_in=1.0, best_out=3.0, duration=8.0, fps=60.0,
        subject_x=0.5,
        exp_mean=60.0, exp_midtone=60.0, exp_highlight_clip=0.0,
        motion_type="pan", motion_in=1.0, motion_out=5.0, motion_strength=7.0,
    )
    scouts = {"FX6_a.mov": sc}
    monkeypatch.setattr(pipeline, "scout_clip_cached",
                        lambda p, cache, window=1.5, **kw: scouts[p])
    monkeypatch.setattr(pipeline, "proxy_for",
                        lambda p, d, ffmpeg_path="ffmpeg": tmp_path / (p + ".proxy"))
    monkeypatch.setattr(pipeline, "analyze_music",
                        lambda p: MusicInfo(p, 30.0, 120.0, [i * 0.5 for i in range(61)]))

    class FakeClient(DirectorClient):
        def generate_edl(self, prompt, proxy_paths):
            # model picks the full pan span
            return {"timeline": [{"clip_index": 0, "in": 1.0, "out": 4.0,
                                  "role": "hook", "retime": "normal"}]}

    edl = pipeline.build_edl_director(
        ["FX6_a.mov"], "m.wav", "Parks",
        target_total=24, default_profile="rec709", cache={},
        proxy_dir=tmp_path, ffmpeg_path="ffmpeg", client=FakeClient())

    assert len(edl.clips) == 1
    clip = edl.clips[0]
    # motion_type must be copied from scout through candidate to clip
    assert clip.motion_type == "pan", f"Expected 'pan', got {clip.motion_type!r}"
    # dark clip (exp_mean=60) => positive exposure_adjust
    assert clip.exposure_adjust > 0, (
        f"Expected positive exposure_adjust for dark clip, got {clip.exposure_adjust}")
    # real move => no synthetic push
    assert clip.push_in == pytest.approx(0.0), (
        f"Expected push_in=0 for real-move clip, got {clip.push_in}")


# ---------------------------------------------------------------------------
# 8c — run_pipeline escape-hatch flags zero the fields
# ---------------------------------------------------------------------------

def _make_edl_with_fields():
    """Build a tiny EDL with stabilize=True, exposure_adjust, highlight_clip set."""
    from broll_search.editor.edl import EDL, Clip
    clip = Clip(
        id=1, source="a.mp4", in_point=0.0, out_point=2.0,
        color_profile="rec709", stabilize=True,
        exposure_adjust=0.35, highlight_clip=0.05,
    )
    return EDL(theme="t", music="m.wav", clips=[clip])


def _patch_run_pipeline_env(monkeypatch, tmp_path, edl):
    """Common monkeypatches to make run_pipeline fast/headless (no ffmpeg)."""
    monkeypatch.setattr(pipeline, "build_edl_scored", lambda *a, **kw: edl)
    monkeypatch.setattr(pipeline, "find_media",
                        lambda folder, exts: (
                            [tmp_path / "a.mp4"]
                            if any(e in exts for e in (".mp4", ".mov"))
                            else [tmp_path / "m.wav"]
                        ))
    monkeypatch.setattr(pipeline, "_resolve_tool", lambda t, name: t)
    monkeypatch.setattr(pipeline, "load_cache", lambda p: {})
    monkeypatch.setattr(pipeline, "save_cache", lambda p, c: None)
    monkeypatch.setattr(pipeline, "validate_edl", lambda e: [])
    monkeypatch.setattr(pipeline, "render_format",
                        lambda *a, **kw: tmp_path / "out.mp4")


def test_run_pipeline_no_stabilize_zeros_field(monkeypatch, tmp_path):
    """stabilize=False must zero clip.stabilize after EDL build."""
    edl = _make_edl_with_fields()
    _patch_run_pipeline_env(monkeypatch, tmp_path, edl)

    pipeline.run_pipeline(
        str(tmp_path), str(tmp_path), str(tmp_path / "out"), "t",
        scout_cache=str(tmp_path / "cache.json"),
        stabilize=False, exposure=True)

    assert edl.clips[0].stabilize is False
    # exposure fields must still be set (we did not zero them)
    assert edl.clips[0].exposure_adjust != 0.0


def test_run_pipeline_no_exposure_zeros_fields(monkeypatch, tmp_path):
    """exposure=False must zero exposure_adjust and highlight_clip after EDL build."""
    edl = _make_edl_with_fields()
    _patch_run_pipeline_env(monkeypatch, tmp_path, edl)

    pipeline.run_pipeline(
        str(tmp_path), str(tmp_path), str(tmp_path / "out"), "t",
        scout_cache=str(tmp_path / "cache.json"),
        stabilize=True, exposure=False)

    assert edl.clips[0].exposure_adjust == pytest.approx(0.0)
    assert edl.clips[0].highlight_clip == pytest.approx(0.0)
    # stabilize was not zeroed
    assert edl.clips[0].stabilize is True


# ---------------------------------------------------------------------------
# 8d — __main__.py flag plumbing
# ---------------------------------------------------------------------------

def test_main_escape_hatch_flags_thread_to_run_pipeline(monkeypatch):
    """--no-stabilize / --no-exposure / --slowmo-ceiling must thread to run_pipeline."""
    from broll_search.editor import __main__ as main_mod
    from broll_search.editor.__main__ import main

    captured = {}

    def capturing_run_pipeline(*args, **kwargs):
        captured.update(kwargs)
        raise SystemExit(0)   # short-circuit after capturing kwargs

    monkeypatch.setattr(main_mod, "run_pipeline", capturing_run_pipeline)

    try:
        main(["--clips", ".", "--music", ".", "--out", ".",
              "--no-stabilize", "--no-exposure", "--slowmo-ceiling", "0.25"])
    except SystemExit:
        pass

    assert captured.get("stabilize") is False
    assert captured.get("exposure") is False
    assert captured.get("slowmo_ceiling") == pytest.approx(0.25)
