"""Turn a beat grid into a sequence of varied, beat-aligned (start, end) cut points.

Varying the number of beats per segment is the single biggest defense against the
'metronome cut' that makes auto-edits look generic (see the research doc)."""

from __future__ import annotations

from typing import List, Sequence, Tuple


def beat_segment_endpoints(
    beats: Sequence[float],
    target_total: float,
    pattern: Sequence[int] = (4, 2, 3, 2, 4, 3),
) -> List[Tuple[float, float]]:
    """Walk the beat grid, consuming `pattern[i]` beats per segment, until the
    summed segment length reaches `target_total` or the beats run out.

    Returns a list of (start_time, end_time), both exact beat timestamps.
    """
    if len(beats) < 2:
        return []
    segments: List[Tuple[float, float]] = []
    idx = 0
    pat_i = 0
    total = 0.0
    last = len(beats) - 1
    while idx < last and total < target_total:
        n = max(1, pattern[pat_i % len(pattern)])
        end_idx = min(idx + n, last)
        start, end = float(beats[idx]), float(beats[end_idx])
        if end <= start:
            break
        segments.append((start, end))
        total += end - start
        idx = end_idx
        pat_i += 1
    return segments
