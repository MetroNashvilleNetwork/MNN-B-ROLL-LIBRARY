from broll_search.editor.timing import beat_segment_endpoints


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
