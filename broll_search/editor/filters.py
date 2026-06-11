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


def conform_filter(fps: str = "24000/1001") -> str:
    return f"fps={fps}"


def clip_video_chain(profile: str, lut_dir: str, width: int, height: int,
                     fps: str, look_strength: float = 1.0) -> str:
    """Full per-clip video filter chain: color -> reframe -> conform -> 8-bit 420."""
    return ",".join([
        color_filter(profile, lut_dir, look_strength),
        reframe_filter(width, height),
        conform_filter(fps),
        "format=yuv420p",
    ])
