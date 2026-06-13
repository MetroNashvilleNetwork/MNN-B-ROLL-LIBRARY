# Cinematic Rebuild — File-by-File Implementation Spec

**Date:** 2026-06-13
**Goal:** Rebuild `broll_search/editor/` to the user's confirmed cinematic direction:
(1) cinematic + SMOOTH — fast cuts allowed, **no shot may look shaky** (stabilize aggressively, every handheld shot);
(2) **one motion per clip** — use the clip's real single camera move when present (select that exact segment), add a gentle synthetic push-in when static;
(3) **mostly slow-mo** (~2.5× for 60fps on a 23.976 timeline) but NOT all — leave some shots normal for contrast;
(4) per-clip **exposure correction** (fix over/under, even out shot-to-shot);
(5) premium, well-produced, not generic (low-strength house look ~0.4).

Grounded in three new research docs (`2026-06-13-one-motion-detection.md`, `-exposure-correction.md`, `-clean-compositing-order.md`) and the prior docs (`-pacing-and-cutting.md`, `-slowmo-speed-ramps.md`, `-reframe-and-motion.md`, `-reference-and-footage-dna.md`).

**The canonical per-clip filter order (everything must conform to this):**
```
[1] vidstabdetect (pass 1, -f null, on trimmed SOURCE)
[2] vidstabtransform / deshake          (stabilize)
[3] lut3d sony_slog3.cube               (LOG→709 convert)
[4] eq                                   (exposure correction — NEW)
[5] look_walkman.cube blended @ ~0.4    (house look)
[6] scale(prescale) → zoompan           (reframe + push-in, FUSED — NEW)
[7] setpts=2.5*PTS                       (slow-mo, selective)
[8] fps=24000/1001                       (conform)
[9] format=yuv420p                       (last)
```

---

## IMPLEMENTATION ORDER (build bottom-up; each layer is independently testable)

1. `analysis.py` — exposure measurement (pure numpy, no video).
2. `motion.py` — NEW module, one-motion detection (pure-ish, OpenCV on a file).
3. `scout.py` — wire exposure + motion fields into `ClipScout` + cache.
4. `edl.py` — add the carried `Clip` fields (the contract everything else fills).
5. `filters.py` — `exposure_filter()`, fused `reframe_pushin_filter()`, rewire `clip_video_chain` tail order + new params.
6. `render.py` — upgrade stabilization strings, pass new args, proxy-vs-final prescale gate.
7. `director.py` — schema/prompt rewrite (cinematic, fast-but-smooth, mostly-slowmo, one-motion selection, push-when-static, aggressive-stabilize) + deterministic exposure/motion post-pass in `parse_director_edl`.
8. `pipeline.py` + `__main__.py` — cinematic defaults (stabilize ON, slowmo mostly-on, exposure ON, look 0.4) + thread new fields candidate→EDL.

Do TDD per layer: `analysis`/`motion`/`filters` are pure and unit-testable; `director` parsing is testable with the existing fake client.

---

## FILE 1 — `analysis.py`  (build first)

Add the S-Log3→709 prediction LUT + exposure measurement. Pure functions on numpy arrays.

**New module-level constants/functions (verbatim from exposure doc §a):**
```python
def _build_slog3_to_709_lut() -> np.ndarray:
    cv = np.arange(256, dtype=np.float64) / 255.0
    lin = np.where(
        cv >= 171.2102946929 / 1023.0,
        (10.0 ** ((cv * 1023.0 - 420.0) / 261.5)) * 0.19 - 0.01,
        (cv * 1023.0 - 95.0) * 0.01125000 / (171.2102946929 - 95.0),
    )
    lin = np.clip(lin, 0.0, None)
    v = np.where(lin < 0.018, lin * 4.5, 1.099 * np.power(lin, 0.45) - 0.099)
    return np.clip(v, 0.0, 1.0)

_SLOG3_709 = (_build_slog3_to_709_lut() * 255.0).astype(np.uint8)

def exposure_stats(frame, profile: str = "sony_slog3") -> dict:
    g = to_gray(frame)
    if profile in ("sony_slog3", "dji_dlogm"):
        g = np.take(_SLOG3_709, g)            # predict post-LUT 709 luma
    hist = cv2.calcHist([g], [0], None, [256], [0, 256]).ravel()
    total = float(g.size) or 1.0
    mean = float((np.arange(256) * hist).sum() / total)
    shadow_clip = float(hist[:6].sum()) / total
    highlight_clip = float(hist[250:].sum()) / total
    cdf = np.cumsum(hist) / total
    median = float(np.searchsorted(cdf, 0.5))
    return {"mean": round(mean, 2), "shadow_clip": round(shadow_clip, 4),
            "highlight_clip": round(highlight_clip, 4), "midtone": round(median, 2)}
```
- Add `TARGET_MID = 112` as a module constant (44% mid; matches the graded reference).
- Tests: feed synthetic arrays (all-50, all-200, ramp) and assert mean/clip fractions; assert the LUT is monotonic and maps the S-Log3 grey range into a plausible 709 spread.

---

## FILE 2 — `motion.py`  (NEW module)

One-motion detection. Returns the 4 fields the EDL/renderer key off. Implements one-motion doc §3 exactly. Validated prototype: `/tmp/motionfinal.py`.

**Public function:**
```python
def motion_features(path: str) -> dict:
    # -> {"motion_type": "pan"|"tilt"|"push_in"|"pull_back"|"static"|"complex",
    #     "motion_in": float, "motion_out": float, "motion_strength": float}
```

**Sampling (sequential, NOT seek — ~10× faster):**
- `target_hz = 8.0`, `proc_w = 480`, `max_steps = 400`.
- `step = round(fps / target_hz)`. Read with `cap.grab()` every frame, `cap.retrieve()` only every `step`-th. Downscale each retrieved frame to 480px wide, grayscale.

**Per consecutive retrieved pair:**
- `cv2.goodFeaturesToTrack(maxCorners=200, qualityLevel=0.01, minDistance=8, blockSize=7)` on prev.
- `cv2.calcOpticalFlowPyrLK(winSize=(21,21), maxLevel=3)`.
- `cv2.estimateAffinePartial2D(method=cv2.RANSAC, ransacReprojThreshold=3)` on survivors.
- Require `inliers >= 8` else emit identity (cut/failed = "no motion this step", not a spike).
- Extract `vx = M[0,2]/W`, `vy = M[1,2]/H`, `scale = sqrt(M00² + M01²)`.

**Smoothing & robust stats:**
- 5-tap rolling **median** on `vx, vy, zr(scale)` (kills single-frame spikes).
- Physical units: `vx_s = median_vx * hz * 100` (%width/sec), `vy_s` likewise, `zrate = (zr-1)*hz*100`.
- Per-axis **speed** = robust median of `|·_s|`.
- Per-axis **consistency** = `|sum(v)| / sum(|v|)` ∈ [0,1] — the key discriminator (clean pan→1.0, jitter→0.2).

**Classification thresholds (verbatim):**
```
PAN_MIN_SPEED  = 2.5    # %/s translation for a real pan/tilt
ZOOM_MIN_SPEED = 1.2    # %/s zoom for a real push/pull
CONS_MIN       = 0.60   # directional purity for a "clean" move
COMPLEX_SPEED  = 6.0    # %/s median speed w/ low consistency => shaky/complex
MIN_SPAN_S     = 0.8    # a clean move must persist at least this long
```
- Candidate axis qualifies iff `speed >= its_min AND consistency >= CONS_MIN`. x→`pan`, y→`tilt`, zoom→`push_in`(mean scale>1)/`pull_back`.
- ≥1 candidate → pick **max(speed × consistency)** (this enforces ONE motion; competing axes lose).
- No candidate → median combined speed ≥ `COMPLEX_SPEED` ⇒ `complex`, else `static`.

**Span (`motion_in`/`motion_out`):**
- pan/tilt → longest consecutive same-sign run on the dominant axis (`_longest_run`); `motion_in=t[i]`, `motion_out=t[j]+1/hz`. Run shorter than `MIN_SPAN_S` → fall back to whole clip.
- push_in/pull_back → whole clip `(0, duration)`.
- static/complex → `(0, duration)` (renderer owns window + synthetic push).

**`motion_strength`** = robust median speed of the dominant axis (%/sec). Used to scale stabilization aggressiveness and to gate slow-mo.

**Robustness:** guard everything with try/except returning `{"motion_type":"static","motion_in":0.0,"motion_out":duration,"motion_strength":0.0}` so a bad clip never crashes the scout. Cost ~0.5s per second of footage; relies on scout cache.

---

## FILE 3 — `scout.py`

Add exposure + motion fields to `ClipScout`, populate them, keep the disk cache backward-compatible.

**New `ClipScout` fields (all defaulted so old JSON cache still loads via `ClipScout(**fields)`):**
```python
# exposure (709-predicted)
exp_mean: float = 112.0
exp_midtone: float = 112.0
exp_shadow_clip: float = 0.0
exp_highlight_clip: float = 0.0
# motion
motion_type: str = "static"
motion_in: float = 0.0
motion_out: float = 0.0
motion_strength: float = 0.0
```

**In `scout_clip`:**
1. Pass the clip's `profile` in (new param `profile: str = "sony_slog3"`) so `exposure_stats` predicts 709 correctly. (Pipeline already knows the per-clip profile via `profile_for`; thread it through, default `sony_slog3` since the library is FX6 S-Log3.)
2. For each sampled frame call `exposure_stats(f, profile)`. Aggregate: `exp_mean`/`exp_midtone = median` of per-frame means/midtones; `exp_shadow_clip`/`exp_highlight_clip = max` of per-frame fractions (worst case drives the rescue).
3. Call `motion_features(path)` once and copy its 4 fields onto the `ClipScout`. (If `motion_out == 0`, set it to `duration`.)

**`scout_clip_cached` / `_cache_key`:** unchanged — `asdict` already serializes the new fields; `_key` (size:mtime) already invalidates on change. Motion is the expensive part and benefits most from the existing cache. Pass `profile` through `scout_clip_cached` too.

**Test:** old cache JSON (without new keys) must still load (defaults fill in); a re-scout writes all 12 fields.

---

## FILE 4 — `edl.py`

Add the carried fields to `Clip` (the contract the director fills and the renderer reads). All defaulted to identity/no-op so existing tests and old `edl.json` round-trip.

**New `Clip` fields:**
```python
# exposure (deterministic, computed from measurement — NOT model-chosen)
exposure_adjust: float = 0.0    # signed; renderer maps to eq/curves. abs<0.04 => no filter
highlight_clip: float = 0.0     # >0.02 => prepend colorlevels ceiling pull
# motion / one-motion-per-clip
motion_type: str = "static"     # pan|tilt|push_in|pull_back|static|complex
push_in: float = 0.0            # synthetic push amount (0 = none; 0.05/0.07/0.08 by duration)
```
Notes:
- Keep existing `stabilize: bool` — it stays the aggressive-stabilize flag; for `complex` clips the director sets it True.
- `motion_strength` does not need to live on `Clip` (only used during selection); keep it on `ClipScout`/`DirectorCandidate`.
- `validate_edl` unchanged (new fields are no-ops at identity). Optionally clamp in the parser (below) rather than validating here.

---

## FILE 5 — `filters.py`

Add exposure, fuse reframe+push, and re-order the `clip_video_chain` tail to the canonical order. This is where the compositing-order doc lands.

### 5a. NEW `exposure_filter(adjust, highlight_clip=0.0) -> str` (verbatim from exposure doc §b)
```python
def exposure_filter(adjust: float, highlight_clip: float = 0.0) -> str:
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
```
- `gamma_weight` is the cinematic key: limits gamma's lift on highlights so shadows/mids rise without blowing whites.

### 5b. NEW fused `reframe_pushin_filter(width, height, subject_x, push, n_frames, src_fps, prescale_h=0) -> str`
Replaces the separate `reframe_filter_anchored` in the chain tail with ONE `scale(prescale)+zoompan` (resample once, no double-soften). From compositing doc §6 + reframe doc §3.2/§4.
```python
def reframe_pushin_filter(width, height, subject_x=0.5, push=0.0,
                          n_frames=0, src_fps=60000/1001, prescale_h=0):
    sx = max(0.0, min(1.0, float(subject_x)))
    N = max(1, int(n_frames))
    # ease-in-out cosine push; push==0 => z fixed at 1.0 (real-motion clips)
    if push and push > 0.0:
        z = f"1.0+{round(push,4)}*(1-cos(3.14159265*on/{N}))/2"
    else:
        z = "1.0"
    pre = f"scale=-2:{prescale_h}:flags=lanczos," if prescale_h else ""
    x = f"clip({sx}*iw-(iw/zoom)/2\\,0\\,iw-iw/zoom)"
    y = "ih/2-(ih/zoom)/2"
    fps_in = f"{int(round(src_fps*1000))}/1000" if isinstance(src_fps, float) else str(src_fps)
    return (f"{pre}zoompan=z='{z}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps_in}")
```
- **Prescale trick:** zoompan crops a sub-rect and upscales to `s`; feeding native 4K softens at push. Pass `prescale_h=4320` on finals, `2160` on proxies. `prescale_h=0` (no prescale) only if push==0 AND you accept the plain center-crop. Keep `reframe_filter_anchored` available for a no-prescale path / tests.
- **zoompan internal `fps` = source rate** (pre-slowmo), because zoompan animates by frame index `on` and must run BEFORE setpts. `N` = output frames of zoompan = `round(trim_duration * source_fps)` (the un-slowed frame count). Caller computes `N` and passes it in.
- Push defaults by duration (set in the director/parser, see §7): `<4s → 0.05`, `4–10s → 0.07`, `>10s → 0.08`. (Reframe doc: 1.05/1.08/1.10; we cap a touch lower because the vidstab optzoom already adds a little zoom — total stays ≤ ~1.10.)

### 5c. REWIRE `clip_video_chain` — new signature + canonical tail order
New params: `exposure_adjust: float = 0.0, highlight_clip: float = 0.0, push: float = 0.0, n_frames: int = 0, prescale_h: int = 0`.

New body order (replaces current `reframe → retime → conform → format` tail):
```
convert_lut  ->  EXPOSURE(eq)  ->  LOOK(blend @ strength)  ->  reframe+pushin(zoompan)  ->  setpts  ->  fps  ->  format=yuv420p
```
- Build `exp = exposure_filter(exposure_adjust, highlight_clip)`.
- **Full-strength path (s≥0.999):** `color = ",".join(p for p in [convert, exp, look] if p)`.
- **Look-off path (s≤0.001):** `",".join(p for p in [convert, exp] if p)` then tail.
- **Blend path:** apply `exp` to the converted image BEFORE the split so base AND look branch share corrected exposure:
  `{convert,}{exp,}split[b][k];[k]{look}[kk];[b][kk]blend=all_expr='A*(1-{s})+B*{s}'[g];[g]{tail}`
- **Tail** = `reframe_pushin_filter(width,height,subject_x,push,n_frames,source_fps,prescale_h)` + (retime setpts if slowmo) + `conform_filter(fps)` + `format=yuv420p`, in that order.
- `retime_filter` stays exactly as-is (`setpts=2.5*PTS` when slowmo, else `""`). It MUST sit AFTER zoompan and BEFORE fps (compositing doc invariant #4 — else the push stutters/finishes early on the stretched timeline).

**Tests (pure-string):** assert exposure eq lands between convert and look; assert zoompan precedes setpts which precedes fps; assert `push==0 → z='1.0'`; assert blend path shares exposure on both branches; assert `format=yuv420p` is last.

---

## FILE 6 — `render.py`

Upgrade the stabilization parameter strings (structure is already correct), pass the new chain args, gate the prescale.

### 6a. Aggressive stabilization (compositing doc §1, §5) — replace the timid strings
The `.trf` detect pass already precedes the transform prefix on the trimmed source — keep that structure, swap parameters only.

- **vidstab detect (pass 1, `-f null`):**
  `vidstabdetect=shakiness=10:accuracy=15:stepsize=6:mincontrast=0.3:result=<trf>`
- **vidstab transform (head of `-vf`):**
  `vidstabtransform=input=<trf>:smoothing=40:optzoom=1:zoom=0:interpol=bicubic:crop=black,unsharp=5:5:0.8:3:3:0.4,`
  - `smoothing=40` is the "nothing looks shaky" dial. **Scale by motion_strength:** if `clip.motion_type=="complex"` and `motion_strength` high (e.g. ≥15 %/s), bump to `smoothing=50`.
  - **`optzoom=1`** replaces the current weak `crop=black:zoom=0` — auto-zooms to hide warped borders (no black-edge flash). The 9:16 reframe discards 32–56% width, so this zoom is "free."
- **deshake fallback (this Mac, preview only):**
  `deshake=rx=64:ry=64:edge=clamp:blocksize=8:contrast=125:search=1,`
  (single-pass, no `.trf`; re-render finals on the Windows vidstab box).

### 6b. Pass new args into `clip_video_chain`
Extend the call (alongside existing `subject_x`/`retime`/`source_fps`):
```python
n_frames = max(1, int(round(clip.duration * (clip.source_fps or 60000/1001))))
prescale_h = 4320 if final_quality else 2160     # final vs proxy/preview
vf = stab + clip_video_chain(
    clip.color_profile, lut_dir, width, height, edl.fps, look_strength,
    subject_x=clip.subject_x, retime=clip.retime, source_fps=clip.source_fps,
    exposure_adjust=clip.exposure_adjust, highlight_clip=clip.highlight_clip,
    push=clip.push_in, n_frames=n_frames, prescale_h=prescale_h)
```
- `n_frames` is the PRE-slowmo zoompan frame count (trim_dur × source_fps), per compositing doc §6.
- Add a `final_quality: bool = True` param to `render_format` (pipeline passes True for the two deliverables; a future fast preview passes False → `prescale_h=2160`).
- Stabilization timeout already 600s — fine; the 4320p prescale is heavy, so keep `-preset medium` and the per-clip 600s timeout.

### 6c. Everything else unchanged
Concat demuxer, music `loudnorm=I=-14:TP=-1.5:LRA=11`, branded title/outro cards, `-shortest`, `+faststart`. No extra ffmpeg pass — exposure + push live inside the existing per-clip intermediate, so render time is essentially unchanged (only the prescale adds cost).

---

## FILE 7 — `director.py`

Rewrite the schema + prompt for the confirmed style, and add the deterministic exposure/motion/push post-pass in `parse_director_edl`. **The model picks clips, in/out, role, subject_x, and the slow-mo/stabilize *intent*; it NEVER chooses exposure numbers, push amounts, or motion classification — those are measured/deterministic.**

### 7a. `DirectorCandidate` — carry the measured fields
Add: `exp_mean: float = 112.0`, `exp_highlight_clip: float = 0.0`, `motion_type: str = "static"`, `motion_in: float = 0.0`, `motion_out: float = 0.0`, `motion_strength: float = 0.0`. (Pipeline copies these from the `ClipScout`.)

### 7b. `_candidate_manifest` — surface motion so the model selects within real moves
Append to each line: `motion={motion_type}[{motion_in:.1f}-{motion_out:.1f}] move={motion_strength:.0f}`. This lets the model anchor its in/out inside the detected clean-move span and avoid raw `complex` shots for slow-mo.

### 7c. `EDL_RESPONSE_SCHEMA` — keep `stabilize`/`retime`; clarify enums
Unchanged shape (`clip_index,in,out,role,subject_x,stabilize,retime,reason`). `retime ∈ {normal,slowmo}`, `role ∈ {hook,body,closer}`. No exposure/push fields in the schema — those are deterministic.

### 7d. `build_director_prompt` — the cinematic direction (rewrite)
Direction the prompt must encode (keep the existing OPEN→build→CLOSE arc and beat-anticipation pacing from the pacing doc; layer the new style on top):

- **Tone:** "Cut a premium, cinematic, SMOOTH 9:16 recap. Cuts may be fast but **nothing may look shaky or chaotic**. Every shot should read as one clean, intentional camera move."
- **ONE MOTION PER CLIP (selection rule):** "Each clip is tagged with a detected `motion`. When a clip has a real move (`pan/tilt/push_in/pull_back`), set your `in`/`out` **inside its `[motion_in–motion_out]` span** so the cut contains that single clean move. For `static` clips pick the sharpest moment; a gentle push-in is added automatically. Never select a span that contains two different moves."
- **AGGRESSIVE STABILIZE:** "Set `stabilize=true` for ANY handheld/`complex` clip — err toward stabilizing. The viewer's #1 complaint is shaky footage; smoothness beats everything."
- **MOSTLY SLOW-MO (changed from the old 'almost none'):** "Default `retime=slowmo` on clips with a clean directional move (`pan/tilt/push_in/pull_back`) and on emotional/water/fabric/reveal/reaction beats — it plays ~2.5× slower so give those a SHORT (~1.0–1.6s) source span. Keep roughly **30–40% of total runtime, not more**, at slow-mo (slow-mo must stay special); leave the rest `normal` for contrast. **Never** slow-mo a `complex`/shaky clip unless it is also `stabilize=true`. Keep most `static` shots at normal speed."
- **EXPOSURE:** "Prefer well-exposed clips, but you may keep a slightly over/under shot — exposure is corrected automatically; just don't pick badly clipped ones."
- **PACING (unchanged intent):** land durations on the beat, cut 1–2 frames early, vary shot lengths (never >3 same-length in a row), slow→fast acceleration arc, ~`n_shots` cuts, ALL HARD CUTS.

Add a one-line counter so the model self-limits slow-mo: "At most about `ceil(n_shots*0.4)` slow-mo shots."

### 7e. `parse_director_edl` — deterministic post-pass (the heart of the rebuild)
After building each `Clip` (current logic stays for clip_index/in/out/role/subject_x/stabilize/retime), set the measured/derived fields:

1. **Copy motion:** `clip.motion_type = cand.motion_type`.
2. **One-motion windowing:** if `motion_type ∈ {pan,tilt,push_in,pull_back}`, **intersect** the model's `[in,out]` with `[motion_in, motion_out]`; if they don't overlap, snap the window inside the motion span (motion span wins — a clean move is the editorial asset). Keep `out>in`; if the intersection is too short for the on-screen duration, pad symmetrically within `[motion_in,motion_out]`.
3. **Push-in (one motion for static):**
   - `pan/tilt/push_in/pull_back` → `clip.push_in = 0.0` (the real move IS the one motion; no synthetic push).
   - `static` → `clip.push_in =` 0.05 (`dur<4`), 0.07 (`4≤dur≤10`), 0.08 (`dur>10`).
   - `complex` → force `clip.stabilize = True`, then treat as static for push: same duration-based `push_in`. (Aggressive stabilize + gentle push = the shaky-footage fix.)
4. **Slow-mo safety gate (enforce the style server-side, don't trust the model blindly):**
   - If `retime=="slowmo"` AND `motion_type=="complex"` AND not `stabilize` → downgrade to `normal` (never slow raw shake).
   - Optionally cap total slow-mo: walk clips in order, sum slowmo on-screen seconds; once past ~40% of `target_total`, downgrade further `slowmo`→`normal` (keeps the effect special even if the model over-uses it).
5. **Exposure (deterministic, from measurement):**
   ```python
   err = analysis.TARGET_MID - cand.exp_mean      # +ve = too dark
   adjust = max(-0.45, min(0.45, err / 140.0))
   clip.exposure_adjust = round(adjust, 3)
   clip.highlight_clip = cand.exp_highlight_clip
   ```
6. **Optional shot-to-shot easing (exposure doc §c, on by default):** second pass over `edl.clips`: `timeline_mean = median(cand.exp_mean)`; per clip recompute against `matched_target = TARGET_MID*0.65 + timeline_mean*0.35` (w=0.35) → re-derive `exposure_adjust`. Evens cuts without erasing intentional dark-vs-bright contrast. Float-only, no extra video pass.

**Tests (fake client, no ffmpeg):** static clip → `push_in>0`, real-move clip → `push_in==0` and window ⊆ motion span, complex clip → `stabilize=True`, dark candidate (`exp_mean=56`) → `exposure_adjust≈+0.40`, hot candidate (`exp_mean=150`) → `≈-0.27`, slow-mo cap downgrades excess slowmo, complex+slowmo+unstabilized → normal.

---

## FILE 8 — `pipeline.py`  (+ `__main__.py`)

Thread the new measured fields candidate→EDL, and set the cinematic DEFAULTS.

### 8a. `build_edl_director` — copy measured fields onto candidates
When building `DirectorCandidate`s, also pass `exp_mean=sc.exp_mean, exp_highlight_clip=sc.exp_highlight_clip, motion_type=sc.motion_type, motion_in=sc.motion_in, motion_out=sc.motion_out, motion_strength=sc.motion_strength`. Pass each clip's `profile` (via `profile_for`) into `scout_clip_cached` so exposure is measured in the right space.

### 8b. `build_edl_scored` — make the scored fallback honor the style too
The scored planner (`planner.plan_scored`) produces `Clip`s without the director. Add a shared helper `apply_cinematic_defaults(edl, scouts_by_path)` (live in `director.py` or a small `style.py`) that runs the SAME deterministic post-pass as §7e (motion windowing, push-in, stabilize for complex, exposure adjust, slow-mo gate) so BOTH paths (director and scored) hit the confirmed look. Default slow-mo selection in the scored path: slowmo on clean-move clips up to the 40% cap, normal otherwise.

### 8c. Cinematic DEFAULTS (the knobs)
- `look_strength=0.4` — already the default in `run_pipeline` and `__main__`; KEEP (premium, not generic).
- **Stabilize aggressive ON by default:** stabilization is per-clip via `clip.stabilize`; the post-pass forces it True for all `complex` clips and the prompt pushes the model to set it on any handheld. No global flag needed, but add `--no-stabilize` escape hatch that zeroes `clip.stabilize` if the user ever wants it off. The aggressive vidstab params (smoothing=40/optzoom=1) are the new defaults in `render.py`.
- **Slow-mo mostly-on** is enforced in the post-pass (clean-move + emotional → slowmo, capped at ~40% runtime). Add `--slowmo-ceiling` (default `0.40`) and pass it to the gate.
- **Exposure-correct ON** by default (deterministic in the post-pass). Add `--no-exposure` escape hatch that zeroes `exposure_adjust`/`highlight_clip`.
- `final_quality=True` for the two render_format calls (4320p prescale on finals).
- Keep `target_total=28.0`, `fps=24000/1001`, music `loudnorm`, branding ON.

### 8d. `__main__.py` — add the escape-hatch flags
`--no-stabilize`, `--no-exposure`, `--slowmo-ceiling` (default 0.40). All default to the cinematic behavior; flags only turn things DOWN. Thread into `run_pipeline`.

---

## CROSS-CUTTING INVARIANTS (must hold after the rebuild)

- **Filter order is law:** stabilize → convert LUT → eq exposure → look blend → zoompan(reframe+push) → setpts → fps → format. Any reorder reintroduces a named artifact (black-edge wobble, push stutter, muddy tone). See compositing doc §4 pitfalls table.
- **One motion per clip:** exactly one of {real-move-window, synthetic-push} per clip; never both. `push_in>0` ⟺ `motion_type∈{static,complex}`.
- **Slow-mo only the clean ratio:** `setpts=2.5*PTS` (59.94/23.976). `retime_filter` already enforces; never interpolate.
- **Never slow raw shake:** `complex` clip may only be `slowmo` if `stabilize=True`.
- **Model picks, math decides:** the Gemini director never emits exposure_adjust, push_in, or motion_type — all deterministic from measurement. The model only selects clips/spans/role/subject_x and the slowmo/stabilize intent (which the post-pass can still override for safety).
- **Backward-compatible caches/EDL:** every new `ClipScout`/`Clip` field is defaulted so old `editor_scout.json` and `edl.json` still load.
- **Mac vs Windows:** deshake is preview-only on this Mac; finals must be re-rendered on the Windows vidstab box (`smoothing=40 optzoom=1`). `stabilization_mode()` already picks correctly.
