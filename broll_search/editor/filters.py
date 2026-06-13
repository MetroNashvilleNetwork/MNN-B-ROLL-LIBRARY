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


def _fps_to_float(fps) -> float:
    s = str(fps)
    if "/" in s:
        n, d = s.split("/", 1)
        try:
            return float(n) / float(d) if float(d) else 0.0
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def retime_filter(retime: str, source_fps: float, target_fps: str = "24000/1001") -> str:
    """Return a setpts slow-motion filter, or '' if no slowdown applies.
    Slowmo plays every source frame at the target rate -> factor = source/target."""
    if retime != "slowmo":
        return ""
    tgt = _fps_to_float(target_fps)
    if not source_fps or not tgt or source_fps <= tgt * 1.1:
        return ""
    factor = round(source_fps / tgt, 4)
    return f"setpts={factor}*PTS"


def exposure_filter(adjust: float, highlight_clip: float = 0.0) -> str:
    """Build an ffmpeg eq (exposure correction) filter string.

    Returns '' when the adjustment is below the perceptible threshold (abs<0.04).
    Optionally prepends a colorlevels ceiling pull when highlight_clip>0.02."""
    a = max(-0.45, min(0.45, float(adjust)))
    if abs(a) < 0.04:
        return ""
    if a > 0:                                  # UNDEREXPOSED -> lift
        gamma  = round(1.0 + a * 0.85, 3)
        gw     = round(0.55 if a > 0.20 else 0.7, 3)
        bright = round(a * 0.06, 3)
        eq = f"eq=gamma={gamma}:gamma_weight={gw}:brightness={bright}"
    else:                                      # OVEREXPOSED -> tame
        gamma  = round(1.0 + a * 0.55, 3)
        bright = round(a * 0.05, 3)
        eq = f"eq=gamma={gamma}:gamma_weight=1.0:brightness={bright}"
    if highlight_clip > 0.02:                  # blown whites -> ceiling pull first
        eq = "colorlevels=rimax=0.94:gimax=0.94:bimax=0.94," + eq
    return eq


def reframe_pushin_filter(width, height, subject_x=0.5, push=0.0,
                          n_frames=0, src_fps=60000/1001, prescale_h=0):
    """Fused scale(prescale)+zoompan reframe with optional cosine push-in.

    Replaces the separate reframe_filter_anchored in the chain tail — one
    resample, no double-soften.  push==0 => z fixed at 1.0 (real-motion clips).
    zoompan fps matches source rate (pre-slowmo) so frame-index animation is
    correct before setpts stretches the timeline."""
    sx = max(0.0, min(1.0, float(subject_x)))
    N = max(1, int(n_frames))
    # ease-in-out cosine push; push==0 => z fixed at 1.0 (real-motion clips)
    if push and push > 0.0:
        z = f"1.0+{round(push,4)}*(1-cos(3.14159265*on/{N}))/2"
    else:
        z = "1.0"
    pre = f"scale=-2:{prescale_h}:flags=lanczos," if prescale_h else ""
    # Use min(max(...)) instead of clip() — clip() with escaped commas inside
    # the zoompan x expression causes ffmpeg 8.x to ignore input EOF and loop
    # indefinitely, ballooning the output to ~960 s regardless of source length.
    x = f"min(max({sx}*iw-(iw/zoom)/2\\,0)\\,iw-iw/zoom)"
    y = "ih/2-(ih/zoom)/2"
    fps_in = f"{int(round(src_fps*1000))}/1000" if isinstance(src_fps, float) else str(src_fps)
    return (f"{pre}zoompan=z='{z}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps_in}")


def clip_video_chain(profile: str, lut_dir: str, width: int, height: int,
                     fps: str, look_strength: float = 1.0, subject_x: float = 0.5,
                     retime: str = "normal", source_fps: float = 0.0,
                     exposure_adjust: float = 0.0, highlight_clip: float = 0.0,
                     push: float = 0.0, n_frames: int = 0,
                     prescale_h: int = 0, saturation: float = 1.2) -> str:
    """Per-clip video chain: color (with dial-able look strength) -> reframe ->
    retime -> conform -> 8-bit 4:2:0.

    Canonical order:
      convert_lut -> exposure(eq) -> look(blend @ strength) ->
      reframe+pushin(zoompan) -> setpts(retime) -> fps -> format=yuv420p

    When 0 < look_strength < 1 the house look is blended over the converted
    image via split+blend.  Exposure correction lands between convert and look
    (and is shared on both blend branches so both paths see corrected luma)."""
    # --- build component strings ---
    s = max(0.0, min(1.0, float(look_strength)))
    convert = ""
    cube = LUT_FILES.get(profile)
    if cube:
        convert = _lut3d(f"{lut_dir}/{cube}")
    look = _lut3d(f"{lut_dir}/{LOOK_LUT}")

    exp = exposure_filter(exposure_adjust, highlight_clip)

    # --- canonical tail (after colour): reframe -> retime -> conform -> format ---
    # zoompan fps must match source rate so `on` frame-index animation is correct.
    # When source_fps is unknown (0), fall back to the timeline fps.
    # IMPORTANT: ffmpeg 8.x has a bug where ANY fps= filter applied AFTER zoompan
    # causes zoompan to ignore input EOF and loop to ~960s.  The workaround is:
    #   - when push>0 (real zoompan animation), embed fps inside zoompan and skip
    #     the external conform_filter (zoompan's fps= param is enough); setpts
    #     (retime) must still come AFTER zoompan but BEFORE the format filter.
    #   - when push==0, use reframe_filter_anchored (scale+crop, no zoompan) so
    #     the external conform_filter works normally.
    src_fps_val = source_fps if source_fps else _fps_to_float(fps)
    zoompan_needed = push > 0 or prescale_h > 0
    rt = retime_filter(retime, source_fps, fps)
    if zoompan_needed:
        # zoompan path: embed fps inside zoompan (workaround for ffmpeg 8.x bug
        # where any external fps= filter after zoompan causes infinite looping).
        # The conform_filter is NOT added separately — zoompan's fps= handles it.
        reframe = reframe_pushin_filter(width, height, subject_x, push, n_frames,
                                        src_fps_val, prescale_h)
        tail_parts = [reframe]
        if rt:
            tail_parts.append(rt)
        tail_parts.append("format=yuv420p")
    else:
        # no-push path: scale+crop, no zoompan; external fps= filter is safe here.
        reframe = reframe_filter_anchored(width, height, subject_x)
        tail_parts = [reframe]
        if rt:
            tail_parts.append(rt)
        tail_parts += [conform_filter(fps), "format=yuv420p"]
    tail = ",".join(tail_parts)
    # saturation boost on the graded image (before reframe; shared by all paths)
    if abs(saturation - 1.0) > 0.01:
        tail = f"eq=saturation={round(saturation, 3)}," + tail

    # --- colour path ---
    if s >= 0.999:
        # full-strength: convert -> exp -> look -> tail (all linear)
        color = ",".join(p for p in [convert, exp, look] if p)
        return ",".join(p for p in [color, tail] if p)

    if s <= 0.001:
        # look-off: convert -> exp -> tail
        color = ",".join(p for p in [convert, exp] if p)
        return ",".join(p for p in [color, tail] if p)

    # blend path: exp is applied BEFORE the split so both branches see it
    pre = ",".join(p for p in [convert, exp] if p)
    pre_str = (pre + ",") if pre else ""
    return (f"{pre_str}split[b][k];[k]{look}[kk];"
            f"[b][kk]blend=all_expr='A*(1-{s})+B*{s}'[g];[g]{tail}")
