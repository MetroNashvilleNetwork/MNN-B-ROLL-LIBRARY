from broll_search.editor.probe import ClipInfo
from broll_search.editor.music import MusicInfo
from broll_search.editor.planner import plan
from broll_search.editor.edl import validate_edl


def _info(path, dur, fps=23.976):
    return ClipInfo(path=path, duration=dur, width=3840, height=2160, fps=fps)


def _music():
    beats = [i * 0.5 for i in range(33)]  # 16s @ 120 BPM
    return MusicInfo(path="m.wav", duration=16.0, tempo=120.0, beats=beats)


def test_plan_builds_valid_beat_aligned_edl():
    clips = [_info("FX6_a.mov", 10), _info("DJI_b.mp4", 10), _info("FX6_c.mov", 10)]
    edl = plan(clips, _music(), theme="parks", target_total=6.0,
               default_profile="rec709", pattern=(4, 2, 3))
    assert validate_edl(edl) == []
    assert edl.theme == "parks" and edl.music == "m.wav"
    assert len(edl.clips) >= 1
    # first clip is the hook; profiles inferred from filenames
    assert edl.clips[0].role == "hook"
    assert edl.clips[0].color_profile == "sony_slog3"   # "FX6_a"
    assert edl.clips[1].color_profile == "dji_dlogm"    # "DJI_b"
    # durations are varied (not all equal)
    durs = [c.duration for c in edl.clips]
    assert len(set(durs)) > 1


def test_plan_clamps_segment_to_short_clip():
    short = [_info("FX6_short.mov", 0.4)]   # shorter than a 2.0s segment
    edl = plan(short, _music(), theme="t", target_total=6.0,
               default_profile="rec709", pattern=(4,))
    assert validate_edl(edl) == []
    assert edl.clips[0].duration <= 0.4


def test_plan_skips_zero_duration_clip_without_wasting_segment():
    clips = [_info("FX6_a.mov", 10), _info("DJI_bad.mp4", 0), _info("FX6_c.mov", 10)]
    edl = plan(clips, _music(), theme="t", target_total=6.0,
               default_profile="rec709", pattern=(4, 2, 3))
    # the zero-duration clip is skipped; the two good clips are used
    assert [c.source for c in edl.clips] == ["FX6_a.mov", "FX6_c.mov"]
    assert [c.role for c in edl.clips] == ["hook", "closer"]


def test_plan_more_segments_than_clips_keeps_closer_last():
    clips = [_info("FX6_a.mov", 10), _info("DJI_b.mp4", 10)]
    edl = plan(clips, _music(), theme="t", target_total=30.0,
               default_profile="rec709", pattern=(2,))
    assert len(edl.clips) == 2
    assert edl.clips[0].role == "hook" and edl.clips[-1].role == "closer"
