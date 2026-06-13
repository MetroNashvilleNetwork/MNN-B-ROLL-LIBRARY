# Clean Per-Clip Compositing Order: Stabilize → Color → Reframe → Motion → Slow-Mo → Conform

**Date:** 2026-06-13
**Scope:** The exact, artifact-free per-clip ffmpeg pipeline that fuses all the editorial intents the user confirmed — aggressive stabilization, S-Log3→709 conversion, exposure correction, low-strength house look, subject-aware vertical reframe, gentle push-in on static shots, mostly-on 2.5× slow-mo, and 23.976fps conform.
**Source files read:** `broll_search/editor/render.py`, `broll_search/editor/filters.py`, `broll_search/editor/edl.py`. Prior research: slowmo-speed-ramps, reframe-and-motion, reference-and-footage-dna.
**Environment confirmed:** dev Mac ffmpeg 8.1.1 has **deshake only** (no vidstab); has `zoompan`, `setpts`, `unsharp`, `eq`. LUTs `sony_slog3.cube`, `look_walkman.cube` present in `luts/`. Source: Sony FX6 4K 3840×2160, 59.94fps, S-Log3, no color tags in container.

---

## 0. The One Rule That Governs Everything: Order

There is exactly one correct macro-order. Each stage either depends on a coordinate space (pixels) or a time space (PTS), and mixing them up creates the specific artifacts the user complains about. The order:

```
[1] vidstabdetect (pass 1, analysis only, on SOURCE frames at SOURCE fps)
        │  (writes transforms .trf — no video output)
        ▼
[2] vidstabtransform / deshake   ← STABILIZE on real source frames
        ▼
[3] lut3d  sony_slog3.cube       ← LOG→709 CONVERSION
        ▼
[4] eq (gamma/brightness/contrast/saturation)  ← EXPOSURE CORRECTION per clip
        ▼
[5] house LOOK (look_walkman.cube, blended at low strength via split+blend)
        ▼
[6] scale(prescale) → zoompan    ← REFRAME (subject crop) + gentle PUSH-IN, fused
        ▼
[7] setpts=FACTOR*PTS            ← SLOW-MO (time domain) — mostly on
        ▼
[8] fps=24000/1001               ← CONFORM to timeline
        ▼
[9] format=yuv420p               ← 8-bit 4:2:0 for libx264
```

The non-negotiable invariants behind this order:

1. **Stabilize FIRST, on the original frames, before any geometry change.** vidstab/deshake estimate inter-frame camera motion. They must see the native, full-resolution, full-FOV frames at their native frame cadence. If you crop/scale/reframe first, you throw away the border pixels the stabilizer needs to fill the warped edges, and the motion model fits a smaller, already-distorted image → worse smoothing and visible edge wobble. If you slow-mo first (setpts), the PTS no longer matches the frame cadence vidstab assumes and the per-frame transforms drift.
2. **Color BEFORE look BEFORE exposure-vs-look ordering matters:** conversion LUT first (it expects log-encoded input), then exposure correction in the now-linearized 709 domain (eq behaves predictably on 709, not on the log curve), then the stylistic look on top. Doing exposure on the raw S-Log3 curve produces muddy, unpredictable shifts because the log gamma compresses highlights.
3. **Geometry (reframe + push-in) is ONE fused zoompan, not two filters.** A separate crop then a separate zoompan re-samples twice and softens. Fuse them.
4. **setpts (slow-mo) must come AFTER all spatial filters and BEFORE fps.** setpts only rewrites timestamps; it changes no pixels. Put it late so spatial filters still operate at native temporal density (better stabilization, better zoompan stepping). Then `fps` resamples the stretched timeline to 23.976.
5. **format=yuv420p dead last**, right before the encoder, so every prior stage runs in the highest bit depth ffmpeg keeps internally.

---

## 1. Stage-by-Stage Detail

### [1]+[2] Stabilization — AGGRESSIVE, smooth-not-shaky

This is the user's #1 priority. The current code's vidstab call is too timid (`smoothing=30` but `crop=black:zoom=0` leaves visible black wobble at edges, and shakiness/accuracy are not tuned for "smooth everything"). Replace with the settings below.

**Two-pass vidstab (production Windows ffmpeg — PREFERRED):**

Pass 1 — detect (runs on the trimmed source, `-f null`, no spatial filters before it):
```
vidstabdetect=shakiness=10:accuracy=15:stepsize=6:mincontrast=0.3:result=stab_NNN.trf
```
- `shakiness=10` (max): tell the detector to assume heavy handheld shake so it finds and tracks aggressively. Safe even on mild shots.
- `accuracy=15` (max): most measurement fields per frame → most accurate motion model. Slower but we want quality.
- `stepsize=6`: search step in pixels; default is fine, 6 gives a good speed/accuracy trade at 4K.
- `mincontrast=0.3`: ignore low-contrast regions that produce noisy vectors.

Pass 2 — transform (this is the head of the per-clip `-vf` chain):
```
vidstabtransform=input=stab_NNN.trf:smoothing=40:optzoom=1:zoom=0:maxshift=-1:maxangle=-1:crop=black:interpol=bicubic,unsharp=5:5:0.8:3:3:0.4
```
- `smoothing=40` ≈ **40 frames of look-ahead/behind** at 59.94fps ≈ 0.67s window. This is the aggressiveness dial. 40 is "very smooth" — it lets the virtual camera glide and absorbs almost all handheld jitter without freezing intentional moves. (Default is 10 = barely smoothed. 30 = current code = moderate. 40–50 = "nothing looks shaky," our target. Go 50 for the shakiest clips.) Higher than ~60 starts to feel like a floaty gimbal and can clip out genuine motion.
- **`optzoom=1` + `zoom=0`** — the border-hiding trick. `optzoom=1` makes vidstab compute the *minimum* dynamic zoom each frame so the warped/rotated frame never shows black edges. This is how we get "no black wobble at the edges" automatically. The current code's `crop=black:zoom=0` is wrong for our goal — it relies on the later reframe crop to hide borders and can still flash black; `optzoom=1` is the correct aggressive-stabilize choice. (`optzoom=2` allows even more adaptive zoom but can pulse; `optzoom=1` is the safe aggressive setting.)
- `crop=black` is harmless once optzoom hides borders, but you can also use `crop=keepborder`; with optzoom=1 the borders are gone either way.
- `interpol=bicubic`: smoother warp interpolation than the default bilinear.
- `unsharp=5:5:0.8...` immediately after recovers the slight softening the warp+zoom introduces. Keep luma amount modest (0.8) so it doesn't crunch S-Log noise.

Because we already crop hard later for the 9:16 reframe (32–56% of the width is discarded), there is plenty of margin to absorb vidstab's stabilization zoom — the two are complementary, not competing. **Stabilization zoom is "free" here.**

**deshake fallback (this Mac):**
deshake has no two-pass and no smoothing-window parameter, so it cannot match vidstab. Best aggressive single-pass config:
```
deshake=rx=64:ry=64:edge=clamp:blocksize=8:contrast=125:search=1
```
- `rx=64:ry=64` (max search range, default 16): allow large per-frame correction so big shakes get caught.
- `edge=clamp`: replicate edge pixels instead of showing black borders — equivalent intent to vidstab's optzoom for hiding edges (deshake cannot dynamically zoom, so clamp + the later reframe crop together hide the borders).
- `blocksize=8`, `contrast=125`, `search=1` (exhaustive): more thorough block matching.
deshake is per-frame reactive (no look-ahead) so it will never be as glassy as vidstab smoothing=40; treat it as preview-only and re-render finals on the Windows box. Note: deshake's edges are best masked by doing the reframe crop afterward (which we do) plus `edge=clamp`.

> Code note: in `render.py` the `.trf` analysis run already correctly precedes the transform and runs on the trimmed source with no other filters — keep that structure, just upgrade the parameter strings. The transform string is prepended (with a trailing comma) to `clip_video_chain(...)`, so vidstab/deshake naturally land at the head of the chain — order [1]/[2] is already structurally right.

### [3] LOG→709 conversion
`lut3d=interp=tetrahedral:file=luts/sony_slog3.cube`. Already in `clip_video_chain` via `color_filter`. Tetrahedral interpolation is the correct choice (avoids the banding trilinear can introduce on log→709). This must be the first pixel-color operation after stabilization and before exposure.

### [4] EXPOSURE correction (NEW — per clip)
Add an `eq` stage **after** the conversion LUT, **before** the look. Drive it from a per-clip correction the director/scout computes (the scout already measures quality/exposure). Recommended form:
```
eq=gamma=G:brightness=B:contrast=C:saturation=S
```
- For an **underexposed** clip (e.g. C5899 award pins): `gamma≈1.15–1.30`, `brightness≈0.02–0.05`. Gamma lifts mids/shadows without clipping highlights — preferred over raw brightness.
- For an **overexposed** clip (e.g. C5905 beverages): `gamma≈0.80–0.90`, `brightness≈-0.03`, and lean on `contrast≈1.03` to re-seat the blacks.
- Shot-to-shot evening: normalize toward a target average luma; keep `saturation` near 1.0 (the look LUT carries the saturation character).
Keep corrections gentle (gamma within 0.8–1.3). eq on the 709-converted image is predictable; eq on raw S-Log3 is not (do not move it before the conversion LUT). If a future build has it, `curves`/`zscale` give finer control, but `eq` is universally present and sufficient.

### [5] House LOOK at LOW strength
Keep the existing `split[b][k];[k]lut3d(look)[kk];[b][kk]blend=all_expr='A*(1-s)+B*s'` blend. For "premium, not generic," run **low strength s ≈ 0.35–0.5** so the look tints rather than dominates. This already exists in `clip_video_chain`; the only change is to insert exposure (eq) *before* the split so both the base and the looked branch share the corrected exposure.

### [6] REFRAME + PUSH-IN — fused single zoompan
Replace the separate `reframe_filter_anchored` (scale+crop) and any later zoom with **one** prescale→zoompan, so we resample once:

```
scale=-2:4320:flags=lanczos,                      # prescale (see trick below)
zoompan=
   z='if(static, 1.0+PUSH*(1-cos(PI*on/N))/2, 1.0)':   # gentle ease-in-out push-in on static shots only
   x='clip(SX*iw - (iw/zoom)/2, 0, iw - iw/zoom)':       # subject-anchored horizontal center
   y='ih/2 - (ih/zoom)/2':
   d=1:s=1080x1920:fps=SLOWMO_TIMELINE_FPS
```

**The prescale trick (avoids soft pixels):** zoompan internally crops a sub-rectangle and upscales it to the output `s`. If you feed it the native 3840×2160, any push-in zoom magnifies already-limited pixels → softness. Pre-upscale the source to a tall intermediate first (the reframe-and-motion doc uses 8× width for 1080p; for our 4K source, prescale to ~2× height, e.g. `scale=-2:4320` → 7680×4320 equivalent box) so zoompan crops from an oversampled image and the output 1080×1920 stays crisp even at 1.10× push. Use `flags=lanczos` for the cleanest upscale. (Memory/time cost is real at 4320p; for proxies use `scale=-2:2160` and only go full on finals.)

**Push-in only on static shots (ONE MOTION PER CLIP):** the EDL/director decides `static` per clip. If the clip already has a real camera move (we selected that exact in/out segment), set push to 0 — the real move *is* the one motion. If static, apply the gentle synthetic push: `PUSH = 0.06–0.08` (6–8%) with the **cosine ease-in-out** `1.0+PUSH*(1-cos(PI*on/N))/2` from the reframe doc, never linear. `N` = total frames of the (already slowed) clip. Anchor `x` on `subject_x` (the `Clip.subject_x` field), clamped in-frame; vertically centered.

**Critical zoompan + setpts interaction:** zoompan animates by **frame index `on`**, not by PTS. So zoompan and setpts are orthogonal and both can be present — but **zoompan must run before setpts**. If setpts (slow-mo) ran first, zoompan's `fps=` resample and its `N` frame-count math would operate on the stretched timeline and the push would either complete too early or stutter. Put zoompan in pixel space (early), then setpts retimes the already-pushed frames. Compute `N` from the *output* frame count of zoompan (= source frames in the trim, since fps inside zoompan should match the pre-slowmo cadence). Practically: drive zoompan's internal `fps` at the source rate and let stage [8] `fps=` do the final conform after setpts.

### [7] SLOW-MO — mostly on, 2.5×
`setpts=2.5*PTS` for 59.94fps source on a 23.976 timeline (factor = source_fps/target_fps = 59.94/23.976 = 2.5 — clean real frames, no interpolation, the only clean ratio for 60fps). This is exactly what `retime_filter` computes today (`factor = round(source_fps/tgt, 4)`). Keep it. Per the slowmo research, **do not slow every clip** — leave ~60% at normal speed for contrast; the director sets `retime="slowmo"` selectively (emotional/water/fabric/reaction/hero), `"normal"` otherwise. setpts changes only timestamps, so it is pixel-free and safe to sit between zoompan and fps.

### [8] CONFORM
`fps=24000/1001`. After setpts stretches the timeline, `fps` resamples to exactly 23.976. For slowmo clips the stretched 59.94→23.976 mapping yields real, non-duplicated frames (2.5× = clean). For normal clips, 59.94→23.976 drops frames cleanly. Already present via `conform_filter`.

### [9] PIXEL FORMAT
`format=yuv420p` last, for libx264 / `-pix_fmt yuv420p`. Already present.

---

## 2. The Full Per-Clip `-vf` String (vidstab build)

vidstabdetect runs as a separate `-f null` pre-pass writing `stab_NNN.trf` (no spatial filters). Then the per-clip transform/render `-vf`:

```
vidstabtransform=input=stab_NNN.trf:smoothing=40:optzoom=1:zoom=0:interpol=bicubic:crop=black,
unsharp=5:5:0.8:3:3:0.4,
lut3d=interp=tetrahedral:file=luts/sony_slog3.cube,
eq=gamma=G:brightness=B:contrast=C:saturation=S,
split[b][k];[k]lut3d=interp=tetrahedral:file=luts/look_walkman.cube[kk];
[b][kk]blend=all_expr='A*(1-0.4)+B*0.4'[g];
[g]scale=-2:4320:flags=lanczos,
zoompan=z='1.0+0.07*(1-cos(3.14159265*on/N))/2':x='clip(SX*iw-(iw/zoom)/2,0,iw-iw/zoom)':y='ih/2-(ih/zoom)/2':d=1:s=1080x1920:fps=60000/1001[z];
[z]setpts=2.5*PTS,
fps=24000/1001,
format=yuv420p
```
(For a static-with-push clip. For a real-motion clip drop the push: `z='1.0'`. For a normal-speed clip drop `setpts`.)

**deshake (Mac) variant** — swap the first two lines for:
```
deshake=rx=64:ry=64:edge=clamp:blocksize=8:contrast=125:search=1,
```
(no detect pass, no `.trf`).

---

## 3. Integration Notes for `render.py` / `filters.py`

1. **`render.py` stabilization block:** upgrade the two parameter strings only — structure (detect pass → transform prefix) is already correct.
   - detect: `shakiness=10:accuracy=15:stepsize=6:mincontrast=0.3`
   - transform: `smoothing=40:optzoom=1:zoom=0:interpol=bicubic:crop=black` then `,unsharp=5:5:0.8:3:3:0.4,`
   - deshake fallback: `deshake=rx=64:ry=64:edge=clamp:blocksize=8:contrast=125:search=1,`
2. **`filters.py` — add exposure:** new `exposure_filter(gamma, brightness, contrast, saturation)` → `eq=...`, inserted in `clip_video_chain` **after** the conversion LUT and **before** the look split. Add `exposure` fields (or an `eq` dict) to the `Clip` dataclass; default to identity (`gamma=1,brightness=0,contrast=1,saturation=1`) so untouched clips are unchanged.
3. **`filters.py` — fuse reframe+push:** replace `reframe_filter_anchored` usage in the tail with a `reframe_pushin_filter(width,height,subject_x,push,N,static,prescale_h)` that emits the `scale(prescale)+zoompan` block. Keep `reframe_filter_anchored` for the no-push path or implement push=0 → `z='1.0'`. Add `push` and `static` (or a `motion` enum) to `Clip`.
4. **Ordering inside `clip_video_chain`:** today the tail is `reframe → retime → conform → format`. New tail must be `look → reframe+pushin (zoompan) → retime(setpts) → conform(fps) → format`. setpts MUST stay after zoompan and before fps. The blend look already precedes the tail — keep that, just route its `[g]` output into the zoompan.
5. **`N` for zoompan:** compute from the trim duration × source_fps (output frames of zoompan, pre-slowmo). Pass it in from the director/EDL (it knows in/out and source_fps).
6. **`look_strength`:** set the default low (0.4) for the premium-not-generic goal; it already flows through `clip_video_chain`.
7. **Performance:** the 4320p prescale is heavy. Gate it: full prescale on finals, `scale=-2:2160` on proxy/preview renders.

---

## 4. Pitfalls Catalog (what breaks if you reorder)

| Reordering mistake | Resulting artifact |
|---|---|
| Reframe/crop before stabilize | Stabilizer loses border pixels → black edge wobble, worse motion model |
| setpts (slow-mo) before stabilize | PTS desync → vidstab transforms drift, jitter returns |
| zoompan after setpts | Push-in stutters / finishes early (N math on stretched timeline) |
| Exposure (eq) before conversion LUT | Muddy, unpredictable tone (eq on log gamma) |
| Look LUT before conversion LUT | Look applied to log data → wrong colors entirely |
| Separate crop + separate zoompan | Double resample → soft pixels |
| No prescale before zoompan push | Magnified native pixels → visible softness |
| vidstab `crop=black:zoom=0` (no optzoom) | Black border flashes at frame edges |
| format=yuv420p early | All later filters run at 8-bit → banding |
| fps before setpts | Conform happens on un-stretched footage → slow-mo wrong/duplicated frames |

---

## 5. Aggressive-Stabilization Settings — Quick Reference

| | vidstab (preferred) | deshake (Mac fallback) |
|---|---|---|
| Analysis | `vidstabdetect=shakiness=10:accuracy=15:stepsize=6:mincontrast=0.3` (separate `-f null` pass) | n/a (single pass) |
| Transform | `vidstabtransform=input=…trf:smoothing=40:optzoom=1:zoom=0:interpol=bicubic:crop=black` | `deshake=rx=64:ry=64:edge=clamp:blocksize=8:contrast=125:search=1` |
| Smoothness dial | `smoothing` 40 default; 50 for shakiest; 30 only if motion looks frozen | fixed (no look-ahead) — preview only |
| Border hiding | `optzoom=1` (auto dynamic zoom) | `edge=clamp` + later reframe crop |
| Sharpen recover | `unsharp=5:5:0.8:3:3:0.4` | same |

**Bottom line:** stabilize on source frames (vidstab two-pass, `smoothing=40 optzoom=1`; deshake `rx=ry=64 edge=clamp` fallback) → convert LUT → eq exposure → low-strength look blend → fused prescale+zoompan (subject crop + cosine push-in only when static) → `setpts=2.5*PTS` (selective) → `fps=24000/1001` → `format=yuv420p`. The fused zoompan and the stabilization crop margin do all the heavy lifting for "smooth, premium, one-motion-per-clip" without re-sampling twice or flashing black edges.
