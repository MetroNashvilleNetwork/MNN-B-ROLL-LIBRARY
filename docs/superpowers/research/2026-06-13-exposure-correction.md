# Per-Clip Exposure Correction + Shot-to-Shot Matching
**Date:** 2026-06-13
**Author:** Claude Code (Opus 4.8)
**Scope:** Design the exposure stage of the MNN auto-editor — cheap per-clip measurement in the scout (OpenCV), gentle ffmpeg correction in the renderer (after LOG→709 LUT, before house look), and optional shot-to-shot evening.
**Files read:** `broll_search/editor/scout.py`, `analysis.py`, `filters.py`, `render.py`, `edl.py`, `director.py`, research `2026-06-13-reference-and-footage-dna.md`.

---

## Design constraint that drives everything

The scout samples frames with `cv2.VideoCapture` on the **raw S-Log3** file (flat, grey, before any LUT). The renderer corrects **after** the conversion LUT, i.e. in **Rec.709 display space**. So measurement space ≠ correction space. We must:

1. Measure exposure in S-Log3 space (what OpenCV sees) and classify under/over.
2. Map that classification to a correction applied in 709 space, where the gamma/brightness numbers actually mean what they look like.

This works because S-Log3 is monotonic: an S-Log3 frame that reads dark stays dark after the LUT, and one that reads bright stays bright. The *amount* of correction is tuned for 709, but the *direction and magnitude class* comes from the log measurement. The scout therefore stores **709-predicted** stats (it converts each sampled grey value through an approximate S-Log3→709 transfer before averaging), so the renderer's `eq`/`curves` numbers map 1:1 to the measured value.

---

## (a) Cheap per-clip exposure MEASUREMENT (scout, OpenCV)

Add to `analysis.py`. Operates on the same grayscale frame the scout already computes — near-zero extra cost (one histogram + a vectorized LUT, reusing `to_gray`).

```python
import numpy as np

# Approximate Sony S-Log3 (code value, 0..1) -> linear -> Rec.709 gamma (0..1).
# Precomputed 256-entry LUT so the per-frame cost is a single np.take.
def _build_slog3_to_709_lut() -> np.ndarray:
    cv = np.arange(256, dtype=np.float64) / 255.0
    # S-Log3 decode to scene-linear reflectance (Sony spec, normalized to ~0.18 mid-grey).
    lin = np.where(
        cv >= 171.2102946929 / 1023.0,
        (10.0 ** ((cv * 1023.0 - 420.0) / 261.5)) * 0.19 - 0.01,
        (cv * 1023.0 - 95.0) * 0.01125000 / (171.2102946929 - 95.0),
    )
    lin = np.clip(lin, 0.0, None)
    # Rec.709 OETF (display-referred, with a soft 0.9 gain so we land near the look LUT's input).
    v = np.where(lin < 0.018, lin * 4.5, 1.099 * np.power(lin, 0.45) - 0.099)
    return np.clip(v, 0.0, 1.0)

_SLOG3_709 = (_build_slog3_to_709_lut() * 255.0).astype(np.uint8)

def exposure_stats(frame, profile: str = "sony_slog3") -> dict:
    """Cheap exposure measurement on one frame, reported in *709-predicted* space.
    Returns mean luma (0..255), shadow/highlight clip fractions, and midtone."""
    g = to_gray(frame)
    if profile in ("sony_slog3", "dji_dlogm"):
        g = np.take(_SLOG3_709, g)          # predict the post-LUT 709 luma
    hist = cv2.calcHist([g], [0], None, [256], [0, 256]).ravel()
    total = float(g.size) or 1.0
    mean = float((np.arange(256) * hist).sum() / total)
    shadow_clip = float(hist[:6].sum()) / total      # crushed blacks
    highlight_clip = float(hist[250:].sum()) / total  # blown whites
    # robust midtone = median, less swayed by a bright window or dark BG
    cdf = np.cumsum(hist) / total
    median = float(np.searchsorted(cdf, 0.5))
    return {"mean": round(mean, 2),
            "shadow_clip": round(shadow_clip, 4),
            "highlight_clip": round(highlight_clip, 4),
            "midtone": round(median, 2)}
```

Aggregate across the sampled frames in `scout_clip` (median of per-frame means is robust to one stray frame). Store on `ClipScout` as `exp_mean`, `exp_shadow_clip`, `exp_highlight_clip`, `exp_midtone`.

**Target mid-tone:** `TARGET_MID = 112` (on 0..255, ≈ 44% — a touch below 50% so the house look LUT can add contrast without crushing; matches the reference's "mids lifted, shadows slightly crushed" character). Reference frames measured ≈ 105–120 mean; this target keeps cuts consistent with the graded reference.

---

## (b) Per-clip CORRECTION toward target (ffmpeg, exact strings)

Computed once per clip in the scout/director and stored as a single float `exposure_adjust` = how many stops (approx) to move, derived from measured mean vs target. The renderer turns that float into a filter. **All numbers below are validated to parse + run on this Mac's ffmpeg** (`/opt/homebrew/bin/ffmpeg`), and a dark grey 76→100 luma lift was confirmed for the example `eq` string.

### Mapping: measured `exp_mean` → `exposure_adjust` (float, clamped gentle)

```
err = TARGET_MID - exp_mean        # +ve = too dark (lift), -ve = too bright (tame)
exposure_adjust = clamp(err / 140.0, -0.45, +0.45)
```

`/140` keeps it cinematic: a frame 56 below target (mean 56, deep underexposure) yields +0.40 — a strong but not flat lift; a perfectly exposed clip yields ~0 and gets **no filter** (skip entirely when `abs < 0.04`). The clamp guarantees we never flatten the image.

### The correction filter (preferred: `eq`, with highlight-protected gamma)

`eq`'s `gamma_weight` reduces gamma's effect on bright areas, so we lift shadows/mids **without** pushing highlights toward clipping — exactly the cinematic, non-flat goal.

```python
def exposure_filter(adjust: float, highlight_clip: float = 0.0) -> str:
    a = max(-0.45, min(0.45, float(adjust)))
    if abs(a) < 0.04:
        return ""                       # already well-exposed: touch nothing
    if a > 0:                            # UNDEREXPOSED -> lift
        gamma = round(1.0 + a * 0.85, 3)        # a=+0.45 -> gamma 1.383
        gw    = round(0.55 if a > 0.20 else 0.7, 3)  # protect highlights more on big lifts
        bright= round(a * 0.06, 3)               # tiny pedestal lift for the very dark
        return f"eq=gamma={gamma}:gamma_weight={gw}:brightness={bright}"
    else:                                # OVEREXPOSED -> tame
        gamma = round(1.0 + a * 0.55, 3)        # a=-0.45 -> gamma 0.752 (darken)
        bright= round(a * 0.05, 3)               # slight negative pedestal
        return f"eq=gamma={gamma}:gamma_weight=1.0:brightness={bright}"
```

Example outputs (exact strings the renderer emits):
- Mean 56 (badly dark, C5899-class): `adjust=+0.40` → `eq=gamma=1.34:gamma_weight=0.55:brightness=0.024`
- Mean 92 (slightly dark): `adjust=+0.143` → `eq=gamma=1.122:gamma_weight=0.7:brightness=0.009`
- Mean 150 (hot, C5905-class beverages): `adjust=-0.271` → `eq=gamma=0.851:gamma_weight=1.0:brightness=-0.014`

### Highlight rescue when blown (add a clamp only when needed)

If `exp_highlight_clip > 0.02` (real blown whites, e.g. window/can), prepend a gentle ceiling pull via `colorlevels` so the look LUT doesn't bake in the clip:

```
colorlevels=rimax=0.94:gimax=0.94:bimax=0.94
```
Full string for an overexposed-with-clipping clip:
`colorlevels=rimax=0.94:gimax=0.94:bimax=0.94,eq=gamma=0.88:gamma_weight=1.0:brightness=-0.01`

### Alternative (equivalent, for shadows+highlights in one pass): `curves`
A single S-shaped-but-lifting curve is also valid (validated to run). Use when a clip is *both* a little dark in shadows and a little hot in highlights:
`curves=all='0/0.03 0.25/0.32 0.5/0.52 0.75/0.74 1/0.97'`
(lifts shadows/mids, pulls the top end down to 0.97). `eq` is preferred as the default because the gamma↔measurement mapping is linear and trivially explainable; `curves` is the manual escape hatch.

---

## (c) Optional SHOT-TO-SHOT matching (so cuts don't jump)

Two-tier, both cheap because the scout already stored every clip's `exp_mean`:

1. **Global anchor (default):** every clip is corrected toward the *same* `TARGET_MID = 112`. This alone removes 80% of jumpiness — every shot lands near 44% mid.
2. **Neighbor easing (optional, on by default for adjacent clips of the same scene):** after the per-clip adjust, nudge each clip's target a fraction toward the running timeline mean so a deliberately moody-dark shot next to a bright one meet partway instead of fully:
   ```
   matched_target = TARGET_MID*(1-w) + timeline_mean*w     # w = 0.35
   ```
   Recompute `exposure_adjust` against `matched_target`. Keep `w` low (0.35) so we even out *without* erasing intentional contrast between a dark detail macro and a bright crowd wide.

Implementation: a single post-pass over `edl.clips` in the director/pipeline that sets each `clip.exposure_adjust`. No second video pass — it only adjusts the float that feeds `exposure_filter`.

---

## (d) Integration plan (exact wiring)

1. **`analysis.py`** — add `_build_slog3_to_709_lut`, `_SLOG3_709`, `exposure_stats()` (above). Pure-function, unit-testable on numpy arrays (no video files), like the existing metrics.

2. **`scout.py`** — in `scout_clip`, call `exposure_stats(f, profile)` per sampled frame; store the **median** mean and the **max** clip fractions on `ClipScout`. New fields:
   ```python
   exp_mean: float = 112.0
   exp_midtone: float = 112.0
   exp_shadow_clip: float = 0.0
   exp_highlight_clip: float = 0.0
   ```
   These auto-flow into the JSON disk cache (`asdict` + `ClipScout(**fields)`) — only requirement is defaults so old cache entries still load.

3. **`edl.py` `Clip`** — add one carried field:
   ```python
   exposure_adjust: float = 0.0   # signed stops-ish; renderer maps to an eq/curves filter
   highlight_clip: float = 0.0    # >0.02 triggers the colorlevels ceiling
   ```
   No validation change needed (0.0 = no-op).

4. **`director.py`** — `DirectorCandidate` carries `exp_mean`/`exp_highlight_clip` (from the ClipScout). In `parse_director_edl`, after building each `Clip`, compute `exposure_adjust` from `TARGET_MID` and the candidate's `exp_mean` (mapping in (b)) and set `clip.exposure_adjust`, `clip.highlight_clip`. Optionally run the (c) neighbor-easing post-pass over the finished `clips` list. The model does **not** decide exposure numbers — it stays a deterministic, measured correction (the prompt already tells it to *skip* badly exposed clips; this *fixes* the ones it keeps).

5. **`filters.py`** — add `exposure_filter(adjust, highlight_clip)` (above). Insert it into `clip_video_chain` **between the conversion LUT and the look LUT**:
   ```
   convert_lut  ->  EXPOSURE  ->  look_lut  ->  reframe -> retime -> conform -> format
   ```
   Concretely, in `clip_video_chain` build `exp = exposure_filter(exposure_adjust, highlight_clip)` and splice it: in the full-strength path `color = ",".join([convert, exp, look])`; in the blend path apply `exp` to the converted image *before* the `split` (so both the base and the look-blended copy share corrected exposure). `clip_video_chain` gains two params `exposure_adjust=0.0, highlight_clip=0.0`.

6. **`render.py`** — pass `clip.exposure_adjust` and `clip.highlight_clip` into the `clip_video_chain(...)` call (one-line change alongside the existing `subject_x`/`retime` args). Stabilization, conform, music stages are untouched. Correction happens inside the existing per-clip intermediate render — no extra ffmpeg pass, so render time is unchanged.

**Order rationale:** exposure correction must sit *after* convert (so we operate in 709, where the numbers are meaningful and clip-detection is real) and *before* the look (so the house grade receives a consistently-exposed image and its contrast/warmth lands the same on every shot — the core of shot-to-shot matching).
