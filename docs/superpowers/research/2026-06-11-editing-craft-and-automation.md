# Editing Craft & Automation: Turning a B-Roll Library into Pro-Looking Vertical Social Video

**Date:** 2026-06-11
**Audience:** Lead architect, MNN B-Roll Library
**Goal:** Inform the design of a fully **offline, Windows, Python + ffmpeg** system that automatically assembles raw b-roll into **non-generic, well-produced** 9:16 social videos (Instagram Reels / TikTok / YouTube Shorts) with **no human editor in the loop**, batch-processed on a twice-weekly schedule.
**Brand context:** City-government media network. Tasteful, credible, not gimmicky.

---

## 0. How to read this document

The client's one-line spec is the north star: *"I don't want the editing looking generic; it needs to look well produced and high quality."* Generic-looking output is not one flaw — it is the sum of ~12 specific, individually-fixable "tells." This document treats each craft principle as **(a)** what pros do, **(b)** why auto-editors fail / the visible tell, **(c)** the offline-automatable technique with named library + ffmpeg filter, plus rough **reliability** and **effort** notes.

A note on architecture that recurs throughout: the right design is a **two-stage pipeline** — an **analysis pass** (Python: PySceneDetect, librosa, OpenCV, mediapipe/YOLO, faster-whisper write a JSON "edit decision list"/EDL) and a **render pass** (ffmpeg executes the EDL: `crop`, `scale`, `zoompan`, `xfade`, `minterpolate`, `vidstab`, `lut3d`/`curves`, `drawtext`/`subtitles`, `amix`, `loudnorm`). Keep the *decisions* in Python and the *pixels* in ffmpeg. This mirrors how a human edits (watch/select, then assemble) and is the key to not looking templated: the decisions become content-aware instead of fixed.

The existing app already has the foundation: a SQLite index of clips, ffprobe metadata, a clipper-produced AI metadata sidecar (`_mnn_broll_metadata.json` with tags/description/category). The auto-editor should **read that index** to choose clips by topic, then run the per-clip analysis below.

---

## 1. Edit Rhythm & Pacing

### (a) What pros do
- **Every cut is motivated.** A cut answers a question the viewer is starting to ask ("what's he looking at?", "what does the whole room look like?"). Cuts are not on a metronome.
- **Cut on motion / on action.** Transition *during* a movement (a head turn, a door opening, a hand reaching). The eye is tracking the motion and is "blind" to the cut, so it reads as invisible and natural. ([LucidLink](https://www.lucidlink.com/blog/editing-techniques), [Adobe](https://www.adobe.com/creativecloud/video/post-production/cuts-in-film.html))
- **Varied shot duration.** Durations follow the emotional content, not a fixed value. Reflective wide shots breathe (4–6s); action/detail beats are quick (0.5–1.5s).
- **Pacing curve (build / breathe).** Energy rises and falls. A piece opens with a hook, breathes, builds, peaks, and resolves. Pacing is *emotion control* — viewers subconsciously sync to the cut rhythm; fast cuts feel like a gasp, slow pans feel like an exhale. ([oboe.com](https://oboe.com/learn/professional-video-editing-workflow-and-storytelling-7otf6t/pacing-and-rhythm-professional-video-editing-workflow-and-storytelling-2))
- **J-cuts and L-cuts.** Audio leads or lags the picture. A **J-cut** (next scene's audio starts *before* its picture) pulls the viewer forward; an **L-cut** (this scene's audio continues *over* the next picture) softens the transition. These are the single biggest "this was edited by a human" signal in dialogue/voiceover work. ([SpotlightFX](https://spotlightfx.com/blog/what-are-j-cuts-and-l-cuts-professional-dialogue-editing-explained), [MotionEdits](https://motionedits.com/j-cut-and-l-cut-the-key-elements-of-an-immersive-video/))
- **Match cuts.** Cut between two shots that share a shape, motion, or composition (a spinning wheel → a spinning fan) for a satisfying, intentional feel.
- **Continuity.** Respect screen direction, the 180° line, and eyeline so space stays coherent.

### (b) Why auto-editors fail — the tells
- **Robotic equal-length cuts.** The #1 giveaway. Clip after clip at exactly 2.0s reads as a slideshow, not an edit. Standardized clip lengths create a "uniform feel" that screams template. ([Digen](https://resource.digen.ai/how-to-customize-ai-video-templates-2026/))
- **Cuts land mid-motion-arc or at dead moments**, not at the natural action beat — so cuts feel arbitrary.
- **No audio leading/lagging** — every cut is a hard A/V sync point, which feels mechanical.
- **Flat energy** — no build or release; the whole piece is one density.

### (c) Offline-automatable techniques
- **Vary duration deterministically but non-uniformly.** Drive shot length from (i) the music structure (Section 2) and (ii) a *pacing curve* you define per template — e.g. a numpy array of target durations that starts short (hook), lengthens (breathe), shortens toward a musical peak. Add a small bounded jitter (±10–15%) so no two adjacent clips are identical length. **Reliability: high. Effort: low.** This single change defeats the biggest tell.
- **Cut on motion (approximate).** Use OpenCV dense optical flow (`cv2.calcOpticalFlowFarneback`) to compute a per-frame **motion-energy curve** for a clip; place the out-point at a *local motion peak* or just after it, and the in-point of the next clip at *its* motion onset. This mimics "cut on action" without true semantic understanding. ([OpenCV optical flow](https://docs.opencv.org/4.x/d4/dee/tutorial_optical_flow.html)) **Reliability: medium (it's a heuristic). Effort: medium.**
- **J/L-cuts (audio offset).** Trivial to automate when a music/voiceover bed exists: in the render graph, start the *next* clip's audio N frames before its video (J) or hold the *previous* clip's audio over the cut (L). With b-roll the ambient audio is usually replaced by a music track, so the highest-value version is **letting the music carry across cuts** (already the default if you lay one continuous music bed under hard picture cuts) and, where voiceover/interview audio exists, offsetting it. ffmpeg: handle audio on a separate timeline and `amix`/`adelay`. **Reliability: high. Effort: low–medium.**
- **Match cuts (opportunistic).** Hard to do reliably without semantic matching, but you can cheaply find *compositional* matches: compare the dominant motion vector direction (from optical flow) or the saliency-centroid position of the last frame of clip A vs the first frame of candidate clip B, and prefer pairings that continue the motion/position. **Reliability: low–medium. Effort: medium–high. (Nice-to-have, not v1.)**
- **Continuity:** mostly unsolvable automatically for arbitrary b-roll; mitigate by avoiding back-to-back near-identical shots (see Section 3 jump-cut avoidance) rather than trying to enforce the 180° rule.

---

## 2. Music-Driven Editing

This is the **highest impact-to-effort lever** for making auto-cut b-roll feel produced. Cutting picture to a music track's beats and structure is exactly what a human editor does first, and it is very automatable offline.

### (a) What pros do
- **Cut on the beat / downbeat.** Picture changes land on musical beats — most often the **downbeat** (beat 1 of the bar) for "hard" cuts and on-beats or half-beats for faster sequences.
- **Map cut density and clip energy to song structure.** Sparse, long shots in the intro; cut density rises through the build; rapid cuts and the biggest visual payoff on the **drop/chorus**; settle in the outro. The edit's pacing curve *is* the song's energy curve.
- **Choose and segment the track** so the video's length matches a musical phrase (cut on a phrase boundary, not mid-bar), and start the piece at a strong musical entry.

### (b) Why auto-editors fail — the tells
- Cuts ignore the music entirely (cut every N seconds while the music does its own thing) — the disconnect is palpable even to non-musicians.
- Cuts land *near* but not *on* the beat (off by 80–150ms) — feels "loose" and amateur.
- Constant cut density regardless of whether the track is in a quiet intro or a peak — no build, so the drop has no impact.
- Track ends abruptly or is hard-faded mid-phrase.

### (c) Offline-automatable techniques — the toolbox
**Beat & tempo (baseline):** `librosa.beat.beat_track(y, sr)` returns `(tempo_bpm, beats)`; with `units='time'` (or `librosa.frames_to_time(beats, sr=sr)`) you get **beat timestamps in seconds** directly. Default `hop_length=512`. This is pure-Python, fast, fully offline, and the obvious default. **Caveat: librosa returns beats, not downbeats.** ([librosa docs](https://librosa.org/doc/main/generated/librosa.beat.beat_track.html))

**Downbeats & meter (better cuts):** for true downbeat (bar-start) detection, use **madmom** (`DBNDownBeatTrackingProcessor` + `RNNDownBeatProcessor`) — it is explicitly designed for **offline** batch use and shines for rhythm-based video editing; or **BeatNet** (CRNN + particle filtering, joint beat/downbeat/tempo/meter, has an offline mode). madmom is the pragmatic pick for an offline batch pipeline. ([BIFF.ai rundown](https://biff.ai/a-rundown-of-open-source-beat-detection-models/), [madmom paper](https://dl.acm.org/doi/10.1145/2964284.2973795), [BeatNet](https://github.com/mjhydri/BeatNet)) **Windows note:** madmom has historically needed a C build toolchain and can be finicky to `pip install` on Windows/newer Python; budget setup time or pin a known-good wheel. librosa is the safer Windows default; madmom is the upgrade.

**Snapping cuts to beats — the actual technique:**
1. Detect beat (and ideally downbeat) times → array `beats[]` in seconds.
2. Build the pacing/energy curve. Cheap structure proxy without a full segmenter: compute `librosa.feature.rms` (loudness) and/or `librosa.onset.onset_strength` over the track; smooth it; high-energy regions → higher cut density (cut every beat or half-beat), low-energy → cut every 2–4 bars. For real section boundaries (intro/verse/chorus) use `librosa.segment` (e.g. `librosa.segment.agglomerative` on chroma/MFCC, or the recurrence-matrix approach) to find structural change points.
3. Choose cut points = a *subset* of `beats[]` whose spacing follows the curve (prefer downbeats for the sparse sections). **This is what creates a build instead of a metronome.**
4. For each interval between chosen cuts, pull a clip segment of that exact length (Section 3 picks *which* clip and *which* segment).
5. Render so each clip's in-point aligns to its beat timestamp. Because clips are pre-trimmed to beat-spaced lengths and concatenated, alignment is exact.

**Track ending:** trim/loop the music to end on a phrase boundary (a downbeat that is a power-of-two bars from the start) and apply a short `afade=out`.

**Reliability:** beat-snapping with librosa = **high**; downbeat/section mapping with madmom = **medium-high** (genre dependent — steady-tempo music with a clear beat is near-perfect; rubato/orchestral is harder). **Effort:** librosa beat-snap = **low**; full structure-aware density mapping = **medium**.

---

## 3. Shot Selection & Sequencing

### (a) What pros do
- **Establishing → medium → detail** narrative grammar: orient the viewer (wide), develop (medium), reward with texture (close/detail). Repeat in waves.
- **The 5-shot method** (classic doc/ENG coverage of an action): (1) close-up on the hands/action, (2) close-up on the face, (3) wide of the whole scene, (4) over-the-shoulder, (5) an unusual/creative angle. Sequencing across these gives variety and coverage from limited footage.
- **Shot-type variety.** Never two of the same framing back-to-back. Alternate wide/medium/tight and vary angle and subject.
- **Avoid jump cuts** (two near-identical shots of the same subject with a tiny change → a visible "jump") and **avoid repetition** of the same clip or look.
- **Order for narrative flow** — a beginning/middle/end, even in a 20-second montage.

### (b) Why auto-editors fail — the tells
- Clips chosen by filename/recency, ignoring framing → three wides in a row, or the same shot type throughout (monotone).
- **Using a whole long clip, or a fixed first-N-seconds**, instead of the *best* sub-segment — so you keep the shaky lead-in, the rack-focus, the moment the operator bumps the tripod.
- Repeating a striking clip because it scored well on a tag match → viewer notices the loop.
- Visible **jump cuts** from putting two similar shots adjacent.

### (c) Offline-automatable techniques
**Auto-score clip "usability" (per candidate segment) — all OpenCV/numpy, fully offline:**
- **Sharpness / focus:** variance of the Laplacian — `cv2.Laplacian(gray, cv2.CV_64F).var()`. Low variance = blurry/out-of-focus; high = sharp. Sample several frames per second and take a robust statistic (median). This is the standard, fast, well-documented blur metric. ([PyImageSearch](https://pyimagesearch.com/2015/09/07/blur-detection-with-opencv/), [TheAILearner](https://theailearner.com/2021/10/30/blur-detection-using-the-variance-of-the-laplacian-method/)) **Reliability: high (relative ranking within a shoot). Effort: low.** Threshold is content-dependent — rank segments rather than using an absolute cutoff.
- **Exposure / clipping:** grayscale (or per-channel) **histogram** — fraction of pixels in the bottom (crushed blacks) and top (blown highlights) bins, plus mean luma for under/over-exposure. Penalize segments with heavy clipping. **Reliability: high. Effort: low.**
- **Stability / shake:** dense optical flow (`calcOpticalFlowFarneback`) → look at the *global/low-frequency* motion (intended camera move, OK) vs *high-frequency jitter* (shake, bad). A high RMS of frame-to-frame residual flow ⇒ shaky; rank it down (or flag for stabilization, Section 7). ([academic use of Farneback for stabilization quality](https://docs.opencv.org/4.x/d4/dee/tutorial_optical_flow.html)) **Reliability: medium-high. Effort: medium.**
- **Motion content:** mean optical-flow magnitude tells you static vs dynamic. Use it both to *pick energetic clips for energetic music sections* and to decide *which clips get a Ken Burns push-in* (static ones — Section 7).
- **(Optional) "interestingness"/saliency spread** to avoid empty frames; OpenCV `saliency` module (`StaticSaliencySpectralResidual`) gives a cheap saliency map whose energy/spread is a usable proxy.

**Pick the best segment within a long clip:** slide a window of the *target duration* (from Section 2) across the clip, score each window by a weighted blend of the above (sharpness↑, exposure↑, stability↑, motion-appropriateness↑), and take the top-scoring window. Combine with **PySceneDetect** (`detect(path, AdaptiveDetector())`) so windows never straddle an internal hard cut and so you can treat each detected shot as an independent candidate. `AdaptiveDetector` is the recommended detector for content with camera motion (rolling-average threshold avoids false cuts on pans). ([PySceneDetect detectors](https://www.scenedetect.com/docs/latest/api/detectors.html), [GitHub](https://github.com/Breakthrough/PySceneDetect)) **Reliability: high for segmentation, medium-high for "best" selection. Effort: medium.**

**Enforce shot-type variety & no repeats (sequencing):**
- Use the existing index's `shot type` (already auto-detected from filename: Closeup/Wide/Medium/Static/Aerial/Tracking/etc.) plus the clipper's `tags`/`category` as the variety key. Greedy-select with a constraint: **never place the same shot-type or the same source clip twice in a row**, and bias toward a wide→medium→tight rotation.
- **Jump-cut avoidance:** compute a cheap visual fingerprint per chosen frame (color histogram or perceptual hash — PySceneDetect ships a `HashDetector`/perceptual hash) and forbid adjacent clips whose fingerprints are too similar.
- **Narrative ordering:** open on a strong **establishing** shot (widest, highest usability), end on a clean resolving shot; in between, follow the music's energy. **Reliability: high. Effort: medium.**

---

## 4. Reframing Landscape → Vertical 9:16 (the PRO way)

This is where most auto-tools look the cheapest, so it is a priority. Source b-roll is overwhelmingly 16:9; the target is 1080×1920.

### (a) What pros do
- **Subject-aware reframe**, not a center crop. They keep the *subject* in frame, respect **headroom** (a little space above the head, not too much, not cut off) and the **rule of thirds** (subject/eyes on a third line, not dead-center).
- **Motion-track the subject** across the shot so the crop window follows them; the move is *smoothed/eased*, not jittery, and often held still when the subject barely moves ("locked" vs "tracking" camera).
- **A true reframe usually beats a blurred-pillarbox** when there is a clear subject. The blurred-background-with-letterboxed-16:9-strip look is a *fallback*, acceptable for very wide establishing shots or graphics where any crop would destroy the composition, but it reads as "I didn't bother" if overused.

### (b) Why auto-editors fail — the tells
- **Dumb center crop** lops off the subject (a person standing off-center disappears).
- **Crop jitters** because per-frame detection is noisy and unsmoothed — the frame "vibrates."
- **Blurred pillarbox on everything** — the laziest, most recognizable auto-vertical look.
- Headroom wrong (subject's head jammed at the top or floating in the lower third).

### (c) Offline-automatable pipeline (concrete)
**Detection (per frame, on a downscaled copy for speed):**
- **People/faces:** **mediapipe** Face Detector / Pose, or a person-class detector. mediapipe is fast, CPU-friendly, offline, pip-installable on Windows. ([mediapipe Face Detector](https://ai.google.dev/edge/mediapipe/solutions/vision/face_detector/python))
- **General objects (for non-people b-roll — buildings, vehicles, machinery):** **YOLO** (Ultralytics YOLOv8/v11) running locally on CPU, or OpenCV DNN with a bundled ONNX model. Fully offline once weights are downloaded.
- **Fallback when nothing is detected:** **saliency** — OpenCV `StaticSaliencySpectralResidual`/`StaticSaliencyFineGrained` gives a "where would a human look" heatmap; crop around its centroid.

**This is exactly how Google's AutoFlip worked** — it fused face detection + object detection (people/pets/cars) + shot boundaries + border detection, chose between a **stable** camera (hold still if the subject stays within ~50% of frame) and a **tracking** camera (follow if it moves more), and supported marking features as "required." **AutoFlip itself is deprecated (support ended March 1, 2023)** so don't depend on the package, but **replicate its design**: detect → score saliency/subject → decide stable vs tracking → smooth. ([mediapipe AutoFlip](https://mediapipe.readthedocs.io/en/latest/solutions/autoflip.html)) Adobe Premiere's **Auto Reframe** is the commercial equivalent: AI subject tracking builds per-frame position keyframes and offers Slower/Default/Faster motion presets — i.e., a tunable smoothing factor. We can mirror that with a smoothing parameter. ([Miracamp](https://www.miracamp.com/learn/premiere-pro/auto-reframe), [Adobe Help](https://helpx.adobe.com/premiere/desktop/add-video-effects/commonly-used-effects/add-auto-reframe-effect-to-a-sequence.html))

**Compute the crop window (per shot, not per frame):**
1. Detect the subject box/centroid per sampled frame across the shot.
2. **Smooth the centroid trajectory** heavily (moving average / Savitzky-Golay / a 1-D Kalman filter) — this kills jitter. Decide **stable vs tracking**: if the subject's smoothed X stays within a small band, lock the crop to a single X (no movement); else pan it along the smoothed path. Easing/clamp max pan speed (Premiere's "motion preset").
3. Place the 9:16 window so the subject sits on a **thirds line** vertically and with correct **headroom** (e.g. keep the face in the upper third; leave ~5–10% above the head). For people, derive headroom from the face/eye-line position.
4. Clamp the window to the frame bounds.

**Render (ffmpeg):** a per-frame or per-segment `crop` + `scale`:
`-vf "crop=ih*9/16:ih:x='<smoothed expr>':y=0,scale=1080:1920"`. For a static reframe, x is a constant; for a tracked reframe, supply the smoothed x as a time expression or pre-bake keyframes via the `sendcmd`/`zoompan` mechanism or segment-wise crops concatenated. **When detection confidence is low / scene is a pure landscape vista,** fall back to the **blurred pillarbox**: `scale` the full frame to fit width on a `boxblur`'d, `scale`-to-fill background (`split`→blur bg→overlay fg) — but use it sparingly and intentionally.

**Reliability:** people-centric reframe = **high**; general-object = **medium-high**; smoothing is what separates pro from amateur and is **fully deterministic once you have the trajectory**. **Effort:** **high** (this is the most code-heavy module) but the payoff is enormous.

---

## 5. Retiming (Speed Ramps & Slow-Mo)

### (a) What pros do
- **Slow-mo for emphasis** (a flag unfurling, water, a reveal) — held a beat longer to feel weighty.
- **Speed up** to compress dead time or for energy.
- **Speed ramps** (smooth acceleration/deceleration into and out of slow-mo), often timed so the *snap* lands on a beat.
- Do it **smoothly** —真 slow-mo from high-frame-rate source (e.g. 60/120fps shot played at 24/30) is clean; slowing 24fps footage requires **frame interpolation** or it judders.

### (b) Why auto-editors fail — the tells
- Slowing normal-fps footage with naive frame duplication → visible **stutter/judder**.
- Speed changes that ignore the music (the "snap" lands off-beat).
- Over-using slow-mo so nothing feels special.

### (c) Offline-automatable techniques (ffmpeg)
- **Change speed:** `setpts` for video (`setpts=2.0*PTS` = half speed) and `atempo` for audio. Simple, reliable. **Reliability: high. Effort: low.**
- **Smooth slow-mo via motion interpolation:** `minterpolate` (`-vf "minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc:vsbmc=1"`) synthesizes in-between frames with motion compensation, giving smooth slow-mo from lower-fps source. **It is CPU-heavy and can introduce warping artifacts** on complex motion/occlusion — use selectively on short emphasis beats, not whole clips. ([ffmpeg minterpolate; general guidance from the Ken Burns/interpolation searches]) **Reliability: medium (artifact risk). Effort: medium.** (Higher-quality ML interpolation like RIFE exists and runs offline, but adds heavy deps/possibly GPU — out of scope for a CPU batch box unless justified.)
- **Best practice for this project:** *prefer real slow-mo* — if the clipper/ffprobe metadata shows a clip was shot at 50/60fps, you can slow it to 24/30 with zero interpolation and perfect smoothness. Reserve `minterpolate` for the occasional 24/30fps clip that must be slowed for a beat-synced emphasis. Time the ramp's end to a downbeat (Section 2). **Reliability: high (for real slow-mo). Effort: low.**

---

## 6. Color & Look (Cohesion + "Cinematic")

### (a) What pros do
- **Grade for cohesion** so clips from different cameras/days/lighting feel like one piece: match exposure, white balance, and contrast first (technical "shot matching"), then apply a unifying **creative grade/LUT** on top.
- **Match to a reference** — pick a hero shot and pull the others toward it.
- Achieve a consistent **"look"** (gentle contrast curve, controlled saturation, a subtle color cast) that is tasteful, not Instagram-filter heavy — important for a **government/credible** brand.

### (b) Why auto-editors fail — the tells
- **No matching** — clips visibly jump in brightness/white balance from cut to cut (one warm, one cold, one dark). This is a glaring amateur tell in a montage.
- **Heavy, gaudy filters** applied uniformly (over-saturated teal-and-orange) — reads as a cheap preset and is *off-brand* for a city government.
- Crushed/blown footage left uncorrected.

### (c) Offline-automatable techniques
**Per-clip auto-correct (normalize toward neutral):**
- **Auto white balance:** **Gray-World** assumption (scale R,G,B so their means are equal) — trivial in OpenCV/numpy. Caveat: gray-world fails on shots dominated by one color (big blue sky, large skin close-ups go gray); guard with a confidence check or use a more robust variant (gray-edge, or weighted gray-patch). ([PyImageSearch auto color correction](https://pyimagesearch.com/2021/02/15/automatic-color-correction-with-opencv-and-python/), [white-balancing methods](https://jmanansala.medium.com/image-processing-with-python-color-correction-using-white-balancing-6c6c749886de)) **Reliability: medium. Effort: low-medium.**
- **Auto exposure/contrast:** stretch/normalize luma using histogram percentiles (clip the top/bottom 0.5%); apply with ffmpeg `eq` (brightness/contrast/gamma/saturation) or `curves`. **Reliability: medium-high. Effort: low.**

**Shot-to-shot matching (cohesion — the high-value part):**
- **Histogram matching** to a reference shot: `skimage.exposure.match_histograms(src, ref, channel_axis=-1)` (or per-channel) makes every clip share the hero clip's tonal/color distribution. This is *the* film-industry technique for cross-shot consistency. ([PyImageSearch histogram matching](https://pyimagesearch.com/2021/02/08/histogram-matching-with-opencv-scikit-image-and-python/)) Pick the reference as the highest-usability, well-exposed clip in the set. Apply the *measured per-channel adjustment* as ffmpeg `curves`/`colorbalance`/`eq` so the render stays in ffmpeg. **Reliability: medium-high. Effort: medium.** (Match exposure/WB *before* histogram matching for best results.)

**Unifying creative look (cohesion + brand):**
- Apply **one tasteful LUT** across the whole video via ffmpeg `lut3d=file=brand.cube`. Keep it subtle (gentle filmic contrast, mild desaturation) for the government brand. A single shared LUT is the cheapest way to make mismatched clips feel intentional. ([Gabor Heja LUT guide](https://gabor.heja.hu/blog/2024/12/10/using-ffmpeg-to-color-correct-color-grade-a-video-lut-hald-clut/), [BinaryTides LUT](https://www.binarytides.com/color-grading-hlg-videos-with-ffmpeg/)) **Reliability: high. Effort: low** (once a LUT is chosen — a one-time human/brand decision).

**Recommended order in the render graph:** per-clip exposure/WB normalize → histogram-match to reference → shared brand LUT. `eq`/`curves`/`colorbalance` → `lut3d`.

---

## 7. Motion & Polish

### (a) What pros do
- **Subtle push-ins / Ken Burns on static shots.** A slow ~3–6% zoom or drift gives a still or locked-off shot life. Very subtle — the viewer shouldn't consciously notice.
- **Stabilize** shaky handheld so it's watchable but not "video-game smooth."
- **Hard cuts dominate.** ~90%+ of cuts in good short-form are straight cuts. Transitions are used sparingly and with intent.
- Which transitions read **pro**: straight cut; **J/L audio cuts**; a clean **cross-dissolve** for a time/place change or a reflective mood; a **dip-to-black** as a chapter break; a **match cut**; a fast **whip-pan/blur** *only* when motivated and matched to motion. Which read **amateur**: star wipes, page curls, cube spins, random "cool" transitions, gratuitous glitch/zoom-pulse on every cut, default slideshow crossfades on everything.

### (b) Why auto-editors fail — the tells
- **Transition on every cut** (the canonical template look): a crossfade or zoom-punch between every clip instead of clean cuts.
- **Cheesy transition library** (wipes/spins) that no working editor uses.
- Ken Burns that is too fast/too obvious, or applied to *every* shot (including already-moving ones) so the whole video drifts queasily.
- Over-stabilized footage with warping/"jello" edges, or unstabilized shake left in.

### (c) Offline-automatable techniques (ffmpeg)
- **Ken Burns / push-in:** `zoompan` (e.g. `zoompan=z='min(zoom+0.0005,1.06)':d=<frames>:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920`). **Pro tips that defeat the tells:** (1) **upscale first** (`scale` the source up ~2× before `zoompan`) to avoid the well-known zoompan *jitter*; (2) keep the zoom **tiny and slow**; (3) **only apply to low-motion clips** (use the optical-flow motion score from Section 3 to gate it — never Ken-Burns a shot that already moves). ([Bannerbear Ken Burns](https://www.bannerbear.com/blog/how-to-do-a-ken-burns-style-effect-with-ffmpeg/), [mko.re](https://mko.re/blog/ken-burns-ffmpeg/), [hadna.space](https://hadna.space/en/notes/11-ffmpeg-ken-burns-effect-zoom-pan)) **Reliability: high. Effort: low-medium.**
- **Stabilization:** ffmpeg **vidstab**, two-pass — `vidstabdetect` (writes a transforms file) then `vidstabtransform` (`smoothing=` controls how many frames are averaged: larger = smoother but limits real camera moves). Gate it on the shake score so you only stabilize clips that need it, and keep `smoothing` moderate to avoid the warping/over-smooth look. ([VidStab + ffmpeg gist](https://gist.github.com/hlorand/e5012fa315dcfe358008cf1b4611c7e0)) **Reliability: high. Effort: medium (two-pass per clip adds render time).**
- **Transitions:** **default to hard cuts.** ffmpeg's `xfade` offers ~44 transitions (fade, dissolve, wipes, slides, smooth*, etc.) — **use only `fade`/`dissolve`/`fadeblack`, and only at deliberate section boundaries**, never on every cut. The `xfade-easing` project adds eased timing if you want a slightly more refined dissolve. ([OTTVerse xfade](https://ottverse.com/crossfade-between-videos-ffmpeg-xfade-filter/), [xfade-easing](https://github.com/scriptituk/xfade-easing)) **Reliability: high. Effort: low.** *The discipline (restraint) is the feature, not the transition variety.*

---

## 8. Social-Specific Craft

### (a) What pros do
- **Hook in the first 1–3 seconds.** ~87% of viewers decide to keep watching within 3 seconds; strong 3-second hold rates correlate with 5–10× more reach. Open on the most arresting shot/moment, not a slow logo fade. Use a **pattern interrupt** (unexpected motion, bold visual, motion toward camera) in the first ~1.5s. ([OpusClip hooks](https://www.opus.pro/blog/instagram-reels-hook-formulas), [Scenith 3-second rule](https://scenith.in/blogs/three-second-rule))
- **Retention pacing:** in the first 0–3 seconds keep energy high; sustain a **visual change every ~1.5–3 seconds** to prevent fatigue. ([AIR Media-Tech retention editing](https://air.io/en/youtube-hacks/advanced-retention-editing-cutting-patterns-that-keep-viewers-past-minute-8))
- **Designed for silent autoplay:** most viewers start muted, so the story must read **visually** and via **burned-in captions**.
- **Captions/typography:** clean sans-serif, large, high-contrast with a stroke/box/shadow for legibility over any footage; **karaoke-style word highlighting** for energy; phrases short (a few words per card).
- **Safe zones:** keep text and key subjects out of the platform UI overlay regions (top and bottom; right-side action rail).
- **Loops:** design the last frame to flow into the first so the autoplay loop is seamless.

### (b) Why auto-editors fail — the tells
- Slow/branded cold open → instant scroll-away.
- **Generic auto-captions in the default tool font** (the CapCut/template caption look) → screams "auto-edited." ([Digen on cookie-cutter look](https://resource.digen.ai/how-to-customize-ai-video-templates-2026/))
- Text placed in the UI-overlay zone → gets covered by the platform's buttons/username.
- No hook structure (treats second 1 like second 15).
- Hard stop at the end (no loop consideration).

### (c) Offline-automatable techniques
- **Platform specs (target these):** **9:16, 1080×1920, H.264 MP4, 30fps** as the safe universal master. Length: keep MNN pieces short (~15–45s typical); the platforms allow far more (TikTok upload up to 60 min; **IG Reels up to 20 min**; **YouTube Shorts up to 3 min/180s** since Oct 2024) but short performs. ([Sprout Social specs](https://sproutsocial.com/insights/social-media-video-specs-guide/), [Shorts Ninja](https://shortsninja.com/blog/best-aspect-ratios-for-tiktok-youtube-instagram-2025/)) **Reliability: high. Effort: low.**
- **Safe zones:** keep captions and critical subject framing within the central band — **avoid the top ~14% and bottom ~20%**, and keep key visuals in the **middle ~60%**; leave the right edge clear of the action rail. Bake these as fixed margins for `drawtext`/`subtitles` positioning and as a constraint in the reframe (Section 4). ([Sprout Social](https://sproutsocial.com/insights/social-media-video-specs-guide/), [Shorts Ninja](https://shortsninja.com/blog/best-aspect-ratios-for-tiktok-youtube-instagram-2025/)) **Reliability: high. Effort: low.**
- **Captions/subtitles (offline):** **faster-whisper** (CTranslate2 reimplementation of Whisper, up to ~4× faster, CPU-capable, fully offline) → word-level timestamps → render. faster-whisper is the clear offline default. ([RunPod faster-whisper](https://www.runpod.io/blog/transcribe-and-translate-audio-files-with-faster-whisper), [Buzz offline transcription](https://buzzcaptions.com/)) Render either via ffmpeg `subtitles=captions.ass` (ASS lets you set a branded font, outline, and **karaoke `\k` word timing**) or `drawtext`. **For a government brand, use a clean custom font + subtle box/outline, never the stock template style.** Note Whisper struggles with music/lyrics, so captions are for **voiceover/interview** audio, not the music bed. ([William Huster Whisper+ffmpeg](https://williamhuster.com/automatically-subtitle-videos/)) **Reliability: high for clear speech. Effort: medium.**
- **Hook:** make clip selection *hook-aware* — force slot 1 to be the highest-scoring, highest-motion, sharpest clip (a pattern-interrupt frame), and start the music near an onset. **Reliability: high. Effort: low.**
- **Loop:** optionally `xfade`/match the final 0.3–0.5s back toward the opening shot, or simply choose a last clip whose end composition resembles the first (reuse the Section 3 fingerprint). **Reliability: medium. Effort: low-medium.**
- **Silent-autoplay:** ensure the story reads with sound off — this is a *design constraint on selection/captions*, not a render step.

---

## 9. What Makes Auto-Edited Content Look Generic — and the Defeat for Each

| # | The giveaway (tell) | Why it happens | The specific defeat |
|---|---------------------|----------------|---------------------|
| 1 | **Equal-length cuts** (metronome) | Fixed `clip_len` constant | Music/beat-driven variable durations + pacing curve + bounded jitter (Sec 1–2) |
| 2 | **Cuts ignore the music** | No audio analysis | Snap cuts to `librosa`/`madmom` beats & downbeats; density follows energy (Sec 2) |
| 3 | **Dumb center crop / jittery reframe** | Per-frame center or unsmoothed detection | Subject-aware crop (mediapipe/YOLO/saliency) + heavily smoothed trajectory + thirds/headroom (Sec 4) |
| 4 | **Blurred pillarbox on everything** | Lazy universal fallback | Use true reframe by default; pillarbox only for genuine wide vistas (Sec 4) |
| 5 | **Color jumps cut-to-cut** | No shot matching | Auto WB/exposure normalize → histogram-match to reference → shared LUT (Sec 6) |
| 6 | **Gaudy uniform filter** | One heavy preset | Subtle, on-brand LUT; restraint (Sec 6) |
| 7 | **Transition on every cut / cheesy wipes** | Template default | Hard cuts by default; dissolve/fade only at section breaks (Sec 7) |
| 8 | **Queasy Ken Burns on every shot** | Blanket zoompan | Gate Ken Burns on low-motion clips only; tiny/slow; upscale first (Sec 7) |
| 9 | **Stock template captions/font** | Tool's default caption style | Custom branded ASS font + outline; karaoke word timing (Sec 8) |
| 10 | **Text/subject in UI-overlay zone** | No safe-zone awareness | Fixed safe-zone margins on text + reframe (Sec 8) |
| 11 | **Weak/slow cold open** | No hook logic | Hook-aware slot-1 selection (sharpest/highest-motion) + pattern interrupt (Sec 8) |
| 12 | **Repeated clips / jump cuts / monotone shot types** | Selection ignores variety | Variety constraints + perceptual-hash de-dup + establishing→medium→detail ordering (Sec 3) |
| 13 | **Judder in slow-mo** | Naive frame duplication | Real slow-mo from high-fps source; `minterpolate` only when needed (Sec 5) |
| 14 | **Stutter/shake left in, or over-stabilized warble** | No stability handling | vidstab gated on shake score, moderate smoothing (Sec 7) |

---

## 10. Automatability Map (offline / Windows / Python + ffmpeg)

Legend — **Reliability**: how trustworthy unattended; **Effort**: build cost; **Stack**: ML model vs pure ffmpeg/CV.

| Capability | Tool / function | Technique | ML? | Reliability | Effort | Windows/offline |
|---|---|---|---|---|---|---|
| **Scene/shot detection** | **PySceneDetect** `detect(path, AdaptiveDetector())` | rolling-avg HSV content diff; `split_video_ffmpeg` | No | High | Low | Easy (pip) |
| **Beat detection** | **librosa** `beat.beat_track(units='time')` | onset envelope + DP tempo; `frames_to_time` | No | High | Low | Easy (pip) |
| **Downbeat/meter** | **madmom** `DBNDownBeatTrackingProcessor`; or **BeatNet** | RNN + DBN/particle filter | Yes | Med-High | Med | madmom = trickier Windows build; pin a wheel |
| **Music structure/energy** | **librosa** `feature.rms`, `onset.onset_strength`, `segment.*` | energy curve → cut density; segmentation | No | Med-High | Med | Easy |
| **Sharpness/focus score** | **OpenCV** `Laplacian(...).var()` | variance of Laplacian | No | High | Low | Easy |
| **Exposure score** | **OpenCV/numpy** histogram | clipped-pixel %, mean luma | No | High | Low | Easy |
| **Shake / motion score** | **OpenCV** `calcOpticalFlowFarneback` | RMS of residual flow (shake) / mean magnitude (motion) | No | Med-High | Med | Easy (CPU-heavy) |
| **Saliency (reframe fallback)** | **OpenCV** `saliency.StaticSaliencySpectralResidual` | spectral-residual heatmap centroid | No | Med | Low | Easy |
| **Face/person for reframe** | **mediapipe** Face Detector / Pose | bbox/landmarks per frame | Yes | High (people) | Med | Easy (pip, CPU) |
| **General object for reframe** | **YOLO** (Ultralytics) / OpenCV-DNN ONNX | bbox of buildings/vehicles/etc. | Yes | Med-High | Med-High | Offline after weights cached; CPU OK |
| **Reframe smoothing** | numpy / scipy (Savitzky-Golay / Kalman) | smooth centroid; stable-vs-track decision | No | High | Med | Easy |
| **Captions (ASR)** | **faster-whisper** (CTranslate2) | word-level timestamps offline | Yes | High (clear speech) | Med | Easy; CPU works, GPU faster |
| **Color: WB/exposure** | **OpenCV/numpy** gray-world + histogram | auto WB + percentile stretch | No | Med | Low-Med | Easy |
| **Color: shot matching** | **scikit-image** `exposure.match_histograms` | match to reference shot | No | Med-High | Med | Easy |
| **Reframe / scale render** | **ffmpeg** `crop`, `scale` | per-shot crop window → 1080×1920 | — | High | (in Sec 4) | Core workhorse |
| **Push-in / Ken Burns** | **ffmpeg** `zoompan` | subtle gated zoom (upscale first) | — | High | Low-Med | Core |
| **Stabilization** | **ffmpeg** `vidstabdetect`+`vidstabtransform` | two-pass, gated, moderate smoothing | — | High | Med | Core (needs vidstab-enabled build) |
| **Retiming** | **ffmpeg** `setpts`/`atempo`; `minterpolate` | speed change; motion interp for slow-mo | — | High / Med | Low / Med | Core |
| **Transitions** | **ffmpeg** `xfade` (fade/dissolve only) | section breaks only | — | High | Low | Core |
| **Color grade (look)** | **ffmpeg** `lut3d`, `curves`, `eq`, `colorbalance` | apply normalize + brand LUT | — | High | Low | Core |
| **Caption render** | **ffmpeg** `subtitles=*.ass` / `drawtext` | branded font, karaoke `\k`, safe zones | — | High | Med | Core |
| **Audio mix/master** | **ffmpeg** `amix`, `adelay` (J/L), `afade`, `loudnorm` | duck/mix, normalize to broadcast loudness | — | High | Low | Core |
| **Orchestration** | Python (subprocess) ± **MoviePy** | build EDL → drive ffmpeg | No | High | Med | Easy |

**Genuinely needs an ML model:** subject detection for reframe (mediapipe/YOLO), speech-to-text captions (faster-whisper), and (optionally) downbeat detection (madmom/BeatNet) and ML frame interpolation (RIFE — likely out of scope). **Everything else is pure ffmpeg + classical OpenCV/numpy**, which is the bulk of the system and the cheapest to make robust on a Windows batch box.

**Orchestration note:** prefer **driving ffmpeg via `subprocess` from Python** for the heavy lifting (full control of complex `filter_complex` graphs, deterministic, fast). MoviePy is convenient for sketching/compositing but is slower and less precise for frame-exact beat alignment; if used, use it for layout and let ffmpeg do the final encode. Cache per-clip analysis (sharpness/beat/detections) in the **existing SQLite index** so re-runs and the twice-weekly batch don't re-analyze unchanged clips — exactly mirroring how the app already caches ffmpeg thumbnails.

**Windows/offline feasibility summary:** all core ffmpeg filters require an ffmpeg build compiled with `--enable-libvidstab` (vidstab) — verify the bundled `ffmpeg.exe` includes it (e.g. a full gyan.dev build). PySceneDetect, librosa, OpenCV (incl. `opencv-contrib` for `saliency`), scikit-image, mediapipe, ultralytics, and faster-whisper all pip-install and run offline on Windows; **madmom is the one fragile dependency** (C build / older-Python expectations) — treat it as an optional upgrade over librosa, not a hard requirement.

---

## Top 10 Techniques, Ranked by Impact-to-Effort (Build Order)

Ranked to most separate **generic** from **pro** output for the lowest build cost. This is the recommended implementation order.

1. **Beat-synced variable-length cutting** (librosa `beat_track` → cut on beats; pacing curve from `rms`/`onset_strength`; bounded jitter). *Kills the #1 tell (metronome cuts) AND ties picture to music in one move.* **Impact: very high. Effort: low.**
2. **Subject-aware vertical reframe with smoothing** (mediapipe/YOLO/OpenCV-saliency → smoothed crop trajectory → ffmpeg `crop`+`scale`; thirds + headroom; pillarbox only as fallback). *The single biggest "looks cheap" fix for 16:9→9:16.* **Impact: very high. Effort: high.**
3. **Best-segment selection via quality scoring** (OpenCV Laplacian-variance sharpness + histogram exposure + Farneback shake, sliding-window over each PySceneDetect shot). *Stops the system from using blurry/shaky/dead footage — the difference between "raw" and "edited."* **Impact: high. Effort: medium.**
4. **Shot-type variety + de-dup + establishing→medium→detail ordering** (use existing index shot-type/tags; perceptual-hash to block jump cuts/repeats). *Defeats monotony and jump cuts; reuses data you already have.* **Impact: high. Effort: medium (low if leveraging the index).**
5. **Cross-shot color matching + subtle brand LUT** (gray-world WB + percentile exposure → `skimage.match_histograms` to a hero shot → ffmpeg `lut3d`). *Makes mismatched clips feel like one cohesive, credible piece.* **Impact: high. Effort: medium.**
6. **Burned-in branded captions** (faster-whisper word timestamps → ffmpeg `subtitles=*.ass` with a custom font + outline + karaoke timing, inside safe zones). *Designed-for-silent-autoplay; a custom caption style is a strong anti-template signal.* **Impact: high (for any narrated content). Effort: medium.**
7. **Hook-first selection + correct platform master + safe zones** (force slot-1 to highest-motion/sharpest clip; export 1080×1920 H.264 30fps; fixed top-14%/bottom-20% margins). *Directly drives retention/reach; nearly free.* **Impact: high. Effort: low.**
8. **Restrained transitions = hard cuts** (default straight cuts; `xfade=fade/dissolve` only at section boundaries; let the music bed/L-cuts carry across). *Removing template transitions is itself a pro signal.* **Impact: medium-high. Effort: low.**
9. **Gated subtle Ken Burns on static clips** (`zoompan`, upscale-first, tiny/slow, only when optical-flow motion score is low). *Adds life to locked-off shots without the queasy "everything drifts" tell.* **Impact: medium. Effort: low-medium.**
10. **Targeted stabilization + real slow-mo for emphasis** (vidstab two-pass gated on shake score, moderate `smoothing`; prefer high-fps source for slow-mo, `minterpolate` only when forced, ramp end on a downbeat). *Polish that reads as "shot well," used sparingly.* **Impact: medium. Effort: medium.**

> **One-line build strategy:** Ship #1, #7, #8 first (a few days of work) for an immediate, obvious jump above template tools; then #3–#5 for cohesion; then invest in #2 (reframe) as the flagship; layer #6, #9, #10 as polish. Keep all *decisions* in a JSON EDL produced by the Python analysis pass, and let **ffmpeg** execute every pixel operation. Cache analysis in the existing SQLite index for the twice-weekly batch.

---

## Sources

- Adobe — Cuts in film: https://www.adobe.com/creativecloud/video/post-production/cuts-in-film.html
- LucidLink — 17 foundational editing techniques: https://www.lucidlink.com/blog/editing-techniques
- SpotlightFX — J-cuts & L-cuts: https://spotlightfx.com/blog/what-are-j-cuts-and-l-cuts-professional-dialogue-editing-explained
- MotionEdits — J-cut and L-cut: https://motionedits.com/j-cut-and-l-cut-the-key-elements-of-an-immersive-video/
- oboe.com — Pacing and Rhythm: https://oboe.com/learn/professional-video-editing-workflow-and-storytelling-7otf6t/pacing-and-rhythm-professional-video-editing-workflow-and-storytelling-2
- librosa — beat_track: https://librosa.org/doc/main/generated/librosa.beat.beat_track.html
- BIFF.ai — Rundown of open-source beat detection models: https://biff.ai/a-rundown-of-open-source-beat-detection-models/
- madmom (ACM MM 2016): https://dl.acm.org/doi/10.1145/2964284.2973795
- BeatNet: https://github.com/mjhydri/BeatNet
- PySceneDetect — Detectors: https://www.scenedetect.com/docs/latest/api/detectors.html
- PySceneDetect — GitHub: https://github.com/Breakthrough/PySceneDetect
- PyImageSearch — Blur detection with OpenCV: https://pyimagesearch.com/2015/09/07/blur-detection-with-opencv/
- TheAILearner — Variance of Laplacian: https://theailearner.com/2021/10/30/blur-detection-using-the-variance-of-the-laplacian-method/
- OpenCV — Optical Flow: https://docs.opencv.org/4.x/d4/dee/tutorial_optical_flow.html
- MediaPipe — AutoFlip (saliency-aware cropping, legacy): https://mediapipe.readthedocs.io/en/latest/solutions/autoflip.html
- MediaPipe — Face Detector (Python): https://ai.google.dev/edge/mediapipe/solutions/vision/face_detector/python
- Miracamp — Auto Reframe in Premiere Pro: https://www.miracamp.com/learn/premiere-pro/auto-reframe
- Adobe Help — Auto Reframe effect: https://helpx.adobe.com/premiere/desktop/add-video-effects/commonly-used-effects/add-auto-reframe-effect-to-a-sequence.html
- PyImageSearch — Automatic color correction: https://pyimagesearch.com/2021/02/15/automatic-color-correction-with-opencv-and-python/
- PyImageSearch — Histogram matching: https://pyimagesearch.com/2021/02/08/histogram-matching-with-opencv-scikit-image-and-python/
- Medium (Manansala) — White balancing methods: https://jmanansala.medium.com/image-processing-with-python-color-correction-using-white-balancing-6c6c749886de
- Gabor Heja — ffmpeg color grade with LUT/HALD CLUT: https://gabor.heja.hu/blog/2024/12/10/using-ffmpeg-to-color-correct-color-grade-a-video-lut-hald-clut/
- BinaryTides — Color grading with LUTs in ffmpeg: https://www.binarytides.com/color-grading-hlg-videos-with-ffmpeg/
- Bannerbear — Ken Burns with ffmpeg: https://www.bannerbear.com/blog/how-to-do-a-ken-burns-style-effect-with-ffmpeg/
- mko.re — Ken Burns slideshows with ffmpeg: https://mko.re/blog/ken-burns-ffmpeg/
- hadna.space — ffmpeg Ken Burns zoom/pan: https://hadna.space/en/notes/11-ffmpeg-ken-burns-effect-zoom-pan
- VidStab + ffmpeg (gist): https://gist.github.com/hlorand/e5012fa315dcfe358008cf1b4611c7e0
- OTTVerse — xfade filter: https://ottverse.com/crossfade-between-videos-ffmpeg-xfade-filter/
- xfade-easing: https://github.com/scriptituk/xfade-easing
- OpusClip — Instagram Reels hook formulas: https://www.opus.pro/blog/instagram-reels-hook-formulas
- Scenith — The 3-second rule: https://scenith.in/blogs/three-second-rule
- AIR Media-Tech — Advanced retention editing: https://air.io/en/youtube-hacks/advanced-retention-editing-cutting-patterns-that-keep-viewers-past-minute-8
- Sprout Social — Social media video specs guide: https://sproutsocial.com/insights/social-media-video-specs-guide/
- Shorts Ninja — Best aspect ratios 2025: https://shortsninja.com/blog/best-aspect-ratios-for-tiktok-youtube-instagram-2025/
- RunPod — Transcribe with faster-whisper: https://www.runpod.io/blog/transcribe-and-translate-audio-files-with-faster-whisper
- Buzz — Offline audio transcription: https://buzzcaptions.com/
- William Huster — Auto-caption with Whisper + ffmpeg: https://williamhuster.com/automatically-subtitle-videos/
- Digen — Customizing AI video templates (2026): https://resource.digen.ai/how-to-customize-ai-video-templates-2026/
