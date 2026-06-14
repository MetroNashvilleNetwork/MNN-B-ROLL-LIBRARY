from broll_search.editor.timing import beat_segment_endpoints, snap_clips_to_beats
from broll_search.editor.edl import Clip


def _slowmo_clip(i, in_p=2.0, out_p=2.5):
    return Clip(id=i, source=f"{i}.mov", in_point=in_p, out_point=out_p,
                color_profile="rec709", retime="slowmo", source_fps=60.0)


def test_snap_lands_every_cut_on_a_beat():
    beats = [round(0.5 * i, 3) for i in range(40)]   # 120 BPM grid
    clips = [_slowmo_clip(i) for i in range(1, 6)]
    snap_clips_to_beats(clips, beats, slowmo_factor=4.0, start_offset=0.0)
    beatset = set(round(b, 3) for b in beats)
    t = 0.0
    for c in clips:
        onscreen = (c.out_point - c.in_point) * 4.0   # 4x slow-mo
        t = round(t + onscreen, 3)
        assert t in beatset, f"cut at {t}s is not on a beat"


def test_snap_preserves_best_moment_center():
    beats = [round(0.5 * i, 3) for i in range(40)]
    c = _slowmo_clip(1, in_p=3.0, out_p=3.4)          # best-moment midpoint = 3.2
    snap_clips_to_beats([c], beats, slowmo_factor=4.0)
    assert abs((c.in_point + c.out_point) / 2.0 - 3.2) < 0.05


def test_snap_truncates_to_target_total():
    beats = [round(0.5 * i, 3) for i in range(80)]   # 0..39.5s of beats
    clips = [_slowmo_clip(i) for i in range(1, 30)]  # 29 clips — uncapped would run ~50s+
    snap_clips_to_beats(clips, beats, slowmo_factor=4.0, target_total=12.0)
    runtime = sum((c.out_point - c.in_point) * 4.0 for c in clips)
    assert len(clips) < 29 and runtime <= 14.0    # capped near the 12s ceiling


def test_snap_respects_start_offset():
    beats = [round(0.5 * i, 3) for i in range(40)]
    clips = [_slowmo_clip(i) for i in range(1, 4)]
    snap_clips_to_beats(clips, beats, slowmo_factor=4.0, start_offset=1.8)
    beatset = set(round(b, 3) for b in beats)
    t = 1.8   # footage begins after a 1.8s title card
    for c in clips:
        t = round(t + (c.out_point - c.in_point) * 4.0, 3)
        assert t in beatset


def test_segments_land_on_beats_with_varied_lengths():
    beats = [i * 0.5 for i in range(33)]  # 0.0 .. 16.0, every 0.5s (120 BPM)
    segs = beat_segment_endpoints(beats, target_total=8.0, pattern=(4, 2, 3))
    # each (start, end) must be exact beat times
    beatset = set(round(b, 6) for b in beats)
    for start, end in segs:
        assert round(start, 6) in beatset
        assert round(end, 6) in beatset
        assert end > start
    # lengths follow the varied pattern (4,2,3 beats * 0.5s = 2.0,1.0,1.5 ...)
    lengths = [round(end - start, 3) for start, end in segs]
    assert lengths[:3] == [2.0, 1.0, 1.5]
    # total is close to the target (within one pattern step)
    assert abs(sum(lengths) - 8.0) <= 2.0


def test_handles_too_few_beats():
    assert beat_segment_endpoints([0.0], target_total=8.0, pattern=(4,)) == []
