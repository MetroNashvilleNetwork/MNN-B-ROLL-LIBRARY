# One-Motion-Per-Shot Detection (OpenCV)

**Date:** 2026-06-13
**Scope:** Detect, within each source clip, the segment containing ONE clean continuous camera move (pan / tilt / push-in / pull-back), select it as the clip in/out point, or classify the clip STATIC/COMPLEX so the renderer can add a gentle synthetic push-in instead. Designed to fit the existing `broll_search/editor/scout.py` frame-sampling style. Validated on real FX6 clips in `dev_media/clips/`.

---

## 1. Editorial Rationale — Why One Motion Per Shot

The target look is "cinematic + SMOOTH, one motion per clip." The reasons this rule matters:

- **A single, legible camera move reads as intentional; two moves read as accident.** When a shot pans AND tilts AND drifts (handheld), the eye cannot lock onto a direction and the cut feels nervous. Isolating one clean move (a pan, a tilt, a push, a reveal) gives every shot a clear vector of attention. This is the single biggest difference between "premium" and "generic."
- **Direction is a cutting tool.** A montage cut on matched or deliberately contrasted motion direction (pan-left into pan-left, or push-in into static) feels musical. You can only do this if each clip has ONE known direction.
- **Slow-mo amplifies whatever motion is present** (slowmo research §1.2: "slowing down shake amplifies it"). A clip with one smooth move slows beautifully; a clip with chaotic handheld jitter becomes a seasick mess at 2.5×. So motion classification must happen *before* the slow-mo and stabilize decisions and should feed them.
- **Static shots feel dead on mobile** (reframe research §3.1). The fix is a synthetic push-in so subtle "you wouldn't even realize it's there." But you must only add it to shots that have NO real move — adding a push on top of an existing pan creates two motions and breaks the rule. Hence we must reliably separate "has a real move" from "static."

**Conclusion:** every clip resolves to exactly one motion. Either (a) it already contains a clean real move and we trim to that move's span, or (b) it is static/too-shaky and the renderer manufactures one gentle push-in over the chosen window. The user's #1 complaint (shaky footage) is handled because the `complex` class — handheld shots with no clean direction — is routed to aggressive stabilization + synthetic push, never used at its raw shaky motion.

---

## 2. How It Fits scout.py

`scout.py` samples frames by seeking (`cap.set(CAP_PROP_POS_FRAMES, idx)`) to ~12 evenly-spaced frames and scores each independently. **Motion is different: it needs *consecutive* frame pairs**, so per-clip seeking to 12 sparse frames is the wrong sampling. Instead we read frames **sequentially** with `cap.grab()` / `cap.retrieve()` at a fixed decimation (every Nth frame for ~8 Hz). Sequential grab is ~10× faster than per-frame seek (measured: 6 s vs 56 s for an 11.5 s clip).

Integration plan: add a sibling module `motion.py` and a function `motion_features(path)` returning `{motion_type, motion_in, motion_out, motion_strength}`. Call it inside `scout_clip` (or a parallel `scout_clip_motion`) and add the four fields to the `ClipScout` dataclass. Reuse the existing disk cache exactly as-is (size+mtime key) — motion analysis is the expensive part and benefits most from caching.

---

## 3. The Algorithm

### 3.1 Motion-track estimation (per clip)

```
target_hz   = 8.0      # sample ~8 motion samples / sec of footage
proc_w      = 480      # downscale width before tracking (speed + robustness)
max_steps   = 400      # safety cap (~50s of footage at 8Hz)
```

Pipeline per consecutive sampled pair:
1. Sequential decode with `cap.grab()`; `retrieve()` only every `step = round(fps/target_hz)` frames.
2. Downscale to 480 px wide, convert to grayscale.
3. `cv2.goodFeaturesToTrack(maxCorners=200, qualityLevel=0.01, minDistance=8, blockSize=7)` on the previous frame.
4. `cv2.calcOpticalFlowPyrLK(winSize=(21,21), maxLevel=3)` to track them into the current frame.
5. `cv2.estimateAffinePartial2D(method=RANSAC, ransacReprojThreshold=3)` on the surviving matches → a similarity transform. Extract:
   - `vx = M[0,2] / W`, `vy = M[1,2] / H` — translation as a fraction of frame width/height **per step**.
   - `scale = sqrt(M[0,0]^2 + M[0,1]^2)` — per-step zoom multiplier.
   - require `inliers >= 8`, else emit a zero/identity sample (treats a cut or failed estimate as "no motion this step" rather than a spike).

Output arrays: `t[]`, `vx[]`, `vy[]`, `zr[]` (scale), plus `fps`, `duration`, `hz`.

**Why estimateAffinePartial2D over Farneback:** feature+RANSAC gives a robust *global* motion (rejecting moving subjects as outliers) and directly yields separable pan / tilt / zoom components. Dense Farneback would need a separate aggregation step and is slower. RANSAC outlier rejection is essential because the subject often moves independently of the camera.

### 3.2 Smoothing & robust statistics

- Apply a **5-tap rolling median** to `vx, vy, zr` to kill single-frame RANSAC spikes (motion blur, a passing object). Median, not mean — one bad frame must not move the estimate.
- Convert to physical units: `vx_s = median_vx * hz * 100` → **percent of frame width per second**. Same for `vy_s` (tilt) and `zrate = (zr-1)*hz*100` (zoom %/s).
- **Speed** per axis = robust median of `|vx_s|`, `|vy_s|`, `|zrate|`.
- **Consistency** per axis = `|sum(v)| / sum(|v|)` ∈ [0,1] — net displacement divided by total path length. **This is the core discriminator.** A clean pan moves monotonically (consistency → 1.0); handheld jitter cancels itself out (consistency → 0.2). Validated: a clean tilt scored 0.62 while two shaky clips scored 0.23 and 0.04.

### 3.3 Classification (thresholds)

```
PAN_MIN_SPEED  = 2.5    # %/s median translation to be a real pan/tilt
ZOOM_MIN_SPEED = 1.2    # %/s median zoom to be a real push/pull
CONS_MIN       = 0.60   # directional purity required for a "clean" move
COMPLEX_SPEED  = 6.0    # %/s median speed with low consistency => shaky/complex
MIN_SPAN_S     = 0.8    # a clean move must persist at least this long
```

Logic:
1. Build candidate clean moves — an axis qualifies only if **BOTH** speed ≥ its min AND consistency ≥ `CONS_MIN`:
   - x-axis qualifies → `pan`; y-axis → `tilt`; zoom → `push_in` (mean scale>1) or `pull_back`.
2. If ≥1 candidate: pick the one with the highest `speed × consistency` score (the most pronounced *and* cleanest move). This is what enforces ONE motion — competing axes lose.
3. If NO candidate clears the bar:
   - median combined speed ≥ `COMPLEX_SPEED` → `complex` (shaky / multi-directional handheld).
   - else → `static`.

### 3.4 Span selection (motion_in / motion_out)

- For **pan / tilt**: find the **longest consecutive same-sign run** on the dominant axis (`_longest_run`) — that contiguous span is the single clean move. `motion_in = t[i]`, `motion_out = t[j] + 1/hz`. If the run is shorter than `MIN_SPAN_S`, fall back to the whole clip. (Validated: an 11.5 s clip with a tilt yielded the segment [0.12 s, 3.97 s].)
- For **push_in / pull_back**: zoom is gradual and global, so use the whole clip (`0 .. duration`).
- For **static / complex**: `motion_in = 0, motion_out = duration` — the renderer owns the window and applies a synthetic push-in (and, for `complex`, aggressive stabilization first).

### 3.5 Returned record (per clip)

```python
{
  "motion_type": "pan" | "tilt" | "push_in" | "pull_back" | "static" | "complex",
  "motion_in":   float,   # seconds — start of the single clean move
  "motion_out":  float,   # seconds — end of the single clean move
  "motion_strength": float # robust median speed in %/sec of the dominant axis
}
```

---

## 4. Validated Results (real dev_media/clips)

| Clip | dur | type | in | out | strength | note |
|---|---|---|---|---|---|---|
| C5883 | 2.5 | push_in | 0.00 | 2.50 | 4.38 | gentle real push |
| C5886 | 3.0 | complex | 0.00 | 3.00 | 24.9 | shaky — cons 0.23, NOT a pull |
| C5887 | 13.0 | complex | 0.00 | 13.0 | 21.6 | shaky — cons 0.04 |
| C5888 | 3.0 | pan | 0.12 | 3.00 | 4.54 | clean pan |
| C5889 | 1.0 | tilt | 0.12 | 1.00 | 5.62 | |
| C5895 | 11.5 | tilt | 0.12 | 3.97 | 12.5 | **segment selected from 11.5s clip** |
| C5900 | 5.5 | pull_back | 0.00 | 5.51 | 2.57 | gentle real pull |
| C5907 | 3.5 | static | 0.00 | 3.50 | 5.17 | → synthetic push |
| C5978 | 10.5 | pan | 0.12 | 6.77 | 9.41 | 6.7s pan span chosen |

Distribution over 20 sequential clips: complex 7, tilt 5, push_in 4, pan 2, pull_back 1, static 1 — a realistic spread for handheld FX6 footage where many shots are too shaky for a raw move and get routed to stabilize + synthetic push.

**Performance:** ~0.5 s of analysis per second of footage at 8 Hz / 480 px. Full 128-clip library ≈ 6–7 min cold, then cached.

---

## 5. How Clip Selection Uses motion_in / motion_out

This feeds the EDL `Clip.in_point` / `out_point` and the renderer's reframe/retime decisions.

1. **Real-move clips (`pan/tilt/push_in/pull_back`)** — the director should anchor the clip's chosen window **inside `[motion_in, motion_out]`**. The scout's quality-based `best_in/best_out` is intersected with the motion span; the motion span wins when they conflict (a sharp frame in the middle of chaos is useless; a clean move is the editorial asset). The renderer does **NOT** add a synthetic push-in — the real move IS the one motion. Subject-aware reframe still applies, smoothed (reframe research §5.2 sigma-15) so the crop doesn't fight the pan.

2. **`static`** — pick the window by scout quality (`best_in/best_out`) anywhere in the clip; the renderer adds the gentle synthetic push-in (reframe research §4: ease-in-out `1.00→1.05` for <4 s, `→1.08` for 4–10 s, `→1.10` for longer). This is the "one motion" for an otherwise dead shot.

3. **`complex`** — treat as static for windowing (use scout quality) BUT set `Clip.stabilize = True` so the renderer runs vidstab (Windows) / deshake (this Mac) aggressively, then adds the synthetic push-in on the stabilized result. This is the direct fix for the user's #1 complaint. `motion_strength` can scale stabilization aggressiveness (higher → stronger smoothing / more crop).

4. **Slow-mo interaction:** prefer real-frame slow-mo (2.5× at 40%) on clean-move clips with strong directional motion (slowmo research §1.1) — a clean pan/tilt/push slows gorgeously. AVOID slow-mo on `complex` clips unless stabilized first, and keep `static` synthetic-push clips mostly at normal speed for contrast. `motion_type` + `motion_strength` are the inputs to that slow-mo gate.

5. **Minimum usable span:** if `motion_out - motion_in` is below the needed on-screen duration (after slow-mo math), pad symmetrically within the clip bounds, or downgrade to `static` handling if padding would re-introduce a second move.

---

## 6. Limitations & Caveats

- Per-step `scale` from `estimateAffinePartial2D` couples weakly with translation; a fast tilt can read a spurious zoom. The consistency gate plus picking the single highest-scoring axis suppresses this (validated on C5895: tilt won over a phantom −56% zoom).
- A hard cut inside a source clip produces one outlier step; the inlier≥8 guard + median smoothing neutralize it, but the library is single-take b-roll so cuts are rare.
- 8 Hz is tuned for the slow, deliberate moves in this footage. Fast whip-pans would need higher `target_hz`; they are out of scope (a whip is rarely a usable "one clean move" for this premium-smooth brief and would classify `complex`).
- Thresholds are calibrated to 480 px / 8 Hz on FX6 4K. Changing either requires re-tuning `PAN_MIN_SPEED` / `COMPLEX_SPEED`.
- deshake (Mac) is far weaker than vidstab (Windows); `complex` clips will look meaningfully smoother on the production Windows render.
