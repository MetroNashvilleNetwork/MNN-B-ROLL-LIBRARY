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
from .scout import ClipScout
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
    clip_idx = 0
    cid = 1
    for seg_start, seg_end in segments:
        # advance past unusable (zero/negative-duration) clips without wasting the segment
        while clip_idx < len(clips) and clips[clip_idx].duration <= 0:
            clip_idx += 1
        if clip_idx >= len(clips):
            break  # no more usable clips
        info = clips[clip_idx]
        seg_dur = seg_end - seg_start
        if info.duration >= seg_dur:
            in_point = round(max(0.0, (info.duration - seg_dur) / 2.0), 3)
            out_point = round(in_point + seg_dur, 3)
        else:
            in_point, out_point = 0.0, round(info.duration, 3)
        edl_clips.append(Clip(
            id=cid, source=info.path, in_point=in_point, out_point=out_point,
            color_profile=profile_for(info.path, default_profile), role="body",
        ))
        clip_idx += 1
        cid += 1
    # roles in a post-pass so hook/closer always land on real, surviving clips
    if edl_clips:
        edl_clips[0].role = "hook"
        if len(edl_clips) > 1:
            edl_clips[-1].role = "closer"
    return EDL(theme=theme, music=music.path, clips=edl_clips,
               duration_target_s=target_total)


def plan_scored(
    scouts: "Sequence[ClipScout]",
    music: MusicInfo,
    theme: str,
    target_total: float = 28.0,
    default_profile: str = "rec709",
    pattern: Sequence[int] = (4, 2, 3, 2, 4, 3),
) -> EDL:
    """Quality-ranked planner: pick the best-scoring clips, in score order, using
    each clip's best moment trimmed to the beat segment. Highest score = hook."""
    ranked = sorted((s for s in scouts if s.score > 0 and s.duration > 0),
                    key=lambda s: s.score, reverse=True)
    segments = beat_segment_endpoints(music.beats, target_total, pattern)
    edl_clips: List[Clip] = []
    cid = 1
    for seg_start, seg_end in segments:
        if cid - 1 >= len(ranked):
            break
        sc = ranked[cid - 1]
        seg_dur = seg_end - seg_start
        window = sc.best_out - sc.best_in
        in_point = round(sc.best_in, 3)
        if window >= seg_dur:
            out_point = round(sc.best_in + seg_dur, 3)
        else:
            out_point = round(sc.best_out, 3)
        edl_clips.append(Clip(
            id=cid, source=sc.path, in_point=in_point, out_point=out_point,
            color_profile=profile_for(sc.path, default_profile), role="body",
            subject_x=sc.subject_x,
        ))
        cid += 1
    if edl_clips:
        edl_clips[0].role = "hook"
        if len(edl_clips) > 1:
            edl_clips[-1].role = "closer"
    return EDL(theme=theme, music=music.path, clips=edl_clips,
               duration_target_s=target_total)
