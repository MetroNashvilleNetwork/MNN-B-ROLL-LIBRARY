"""Phase 1 heuristic planner: clips + music beat grid -> EDL.

Deliberately simple — it cuts clips (in source order) to varied, beat-aligned
durations. Later phases replace/augment this with quality scoring, variety
de-dup, and the Gemini director (the EDL contract stays the same)."""

from __future__ import annotations

from typing import List, Sequence

from .edl import Clip, EDL
from .music import MusicInfo
from .probe import ClipInfo
from .profiles import profile_for
from .timing import beat_segment_endpoints


def plan(
    clips: Sequence[ClipInfo],
    music: MusicInfo,
    theme: str,
    target_total: float = 28.0,
    default_profile: str = "rec709",
    pattern: Sequence[int] = (4, 2, 3, 2, 4, 3),
) -> EDL:
    segments = beat_segment_endpoints(music.beats, target_total, pattern)
    edl_clips: List[Clip] = []
    cid = 1
    for i, (seg_start, seg_end) in enumerate(segments):
        if i >= len(clips):
            break  # ran out of distinct clips
        info = clips[i]
        seg_dur = seg_end - seg_start
        if info.duration <= 0:
            continue
        if info.duration >= seg_dur:
            # center the segment within the available footage
            in_point = round(max(0.0, (info.duration - seg_dur) / 2.0), 3)
            out_point = round(in_point + seg_dur, 3)
        else:
            # clip shorter than the beat segment — use the whole clip
            in_point, out_point = 0.0, round(info.duration, 3)
        is_last = (i == len(segments) - 1) or (i == len(clips) - 1)
        role = "hook" if cid == 1 else ("closer" if is_last else "body")
        edl_clips.append(Clip(
            id=cid, source=info.path, in_point=in_point, out_point=out_point,
            color_profile=profile_for(info.path, default_profile), role=role,
        ))
        cid += 1
    return EDL(theme=theme, music=music.path, clips=edl_clips,
               duration_target_s=target_total)
