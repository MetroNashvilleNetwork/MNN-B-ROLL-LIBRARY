"""Turn a beat grid into a sequence of varied, beat-aligned (start, end) cut points.

Varying the number of beats per segment is the single biggest defense against the
'metronome cut' that makes auto-edits look generic (see the research doc)."""

from __future__ import annotations

import bisect
from typing import List, Optional, Sequence, Tuple

from .edl import clamp_clip_to_source
from .filters import slowmo_playback_factor


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


def snap_clips_to_beats(clips, beats, slowmo_factor: float = 0.0,
                        start_offset: float = 0.0, target_hold: float = 1.2,
                        target_total: float = 0.0,
                        pattern: Sequence[int] = (),
                        source_durations: Optional[Sequence[float]] = None,
                        off_beat_fraction: float = 0.15) -> None:
    """Resize each clip so its cut boundary lands on a music beat.

    On-screen hold is a (varied) whole number of beats near ``target_hold``; the
    source span is ``hold / factor`` (so a slow-mo clip at 4x with a 1.8s on-screen
    hold uses a 0.45s span). The span is re-centered on the clip's existing
    best-moment midpoint, so the moment is preserved while the cut snaps to the beat.

    ``start_offset`` is the video time the first footage clip begins at (e.g. a title
    ``off_beat_fraction`` — fraction of cuts that intentionally land between beats
    (human feel; 0 disables). Mutates ``clips``.
    """
    beats = [float(b) for b in beats]
    if len(beats) < 4 or not clips:
        return
    interval = (beats[-1] - beats[0]) / (len(beats) - 1)
    if interval <= 0:
        return
    if not pattern:
        base = max(2, round(target_hold / interval))        # beats/shot for ~target_hold
        pattern = (base, base, base + 1, base)               # punchier: mostly the shorter hold
    off_every = max(0, round(1.0 / off_beat_fraction)) if off_beat_fraction > 0 else 0
    cut_t = float(start_offset)
    idx = bisect.bisect_right(beats, cut_t)                  # first beat after the start
    kept = len(clips)
    for k, clip in enumerate(clips):
        if idx >= len(beats):
            kept = k
            break
        if clip.retime == "slowmo":
            f = slowmo_playback_factor(clip.source_fps or 0.0, slowmo_factor=slowmo_factor)
        else:
            f = 1.0
        want = pattern[k % len(pattern)] * interval          # desired on-screen seconds
        j = idx
        while j < len(beats) - 1 and (beats[j] - cut_t) < want:
            j += 1
        onscreen = beats[j] - cut_t
        if onscreen <= 0:
            kept = k
            break
        span = round(onscreen / f, 3)
        mid = (clip.in_point + clip.out_point) / 2.0
        new_in = max(0.0, round(mid - span / 2.0, 3))
        clip.in_point = new_in
        clip.out_point = round(new_in + span, 3)
        if source_durations is not None and k < len(source_durations):
            clamp_clip_to_source(clip, float(source_durations[k] or 0))
        if off_every and (k + 1) % off_every == 0 and j > 0:
            cut_t = round((beats[j - 1] + beats[j]) / 2.0, 3)
        else:
            cut_t = beats[j]
        idx = bisect.bisect_right(beats, cut_t)
        if target_total and (cut_t - start_offset) >= target_total:  # length ceiling
            kept = k + 1
            break
    if 0 < kept < len(clips):                                # drop clips past the ceiling
        del clips[kept:]
