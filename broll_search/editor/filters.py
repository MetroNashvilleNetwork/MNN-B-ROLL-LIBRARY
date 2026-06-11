"""Pure builders for ffmpeg filtergraph strings (no ffmpeg execution here).

LUTs are referenced by relative, space-free, forward-slash paths so the same
filtergraph string works on Windows without colon/space escaping headaches."""

from __future__ import annotations

LUT_FILES = {
    "sony_slog3": "sony_slog3.cube",
    "dji_dlogm": "dji_dlogm.cube",
}
LOOK_LUT = "look_walkman.cube"


def _lut3d(rel_path: str) -> str:
    return f"lut3d=interp=tetrahedral:file={rel_path}"


def color_filter(profile: str, lut_dir: str = "luts", look_strength: float = 1.0) -> str:
    """Conversion LUT (if the profile is log) -> house look LUT.

    look_strength is accepted for forward-compat; Phase 1 applies the look at
    full strength (blending is a later-phase refinement)."""
    parts = []
    conv = LUT_FILES.get(profile)
    if conv:
        parts.append(_lut3d(f"{lut_dir}/{conv}"))
    parts.append(_lut3d(f"{lut_dir}/{LOOK_LUT}"))
    return ",".join(parts)


def reframe_filter(width: int, height: int) -> str:
    """Center-crop reframe: scale to cover the target box, then crop to it."""
    return (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}")


def reframe_filter_anchored(width: int, height: int, subject_x: float = 0.5) -> str:
    """Subject-anchored crop: scale to cover the WxH box, then crop a window whose
    horizontal centre follows subject_x (0=left..1=right), clamped to stay in frame;
    vertically centred. Commas inside clip() are backslash-escaped for the
    filtergraph parser."""
    sx = max(0.0, min(1.0, float(subject_x)))
    x_expr = f"clip({sx}*iw-{width}/2\\,0\\,iw-{width})"
    return (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop=w={width}:h={height}:x={x_expr}:y=(ih-{height})/2")


def conform_filter(fps: str = "24000/1001") -> str:
    return f"fps={fps}"


def clip_video_chain(profile: str, lut_dir: str, width: int, height: int,
                     fps: str, look_strength: float = 1.0, subject_x: float = 0.5) -> str:
    """Full per-clip video filter chain: color -> reframe -> conform -> 8-bit 420."""
    return ",".join([
        color_filter(profile, lut_dir, look_strength),
        reframe_filter_anchored(width, height, subject_x),
        conform_filter(fps),
        "format=yuv420p",
    ])
