# Reframe & Motion: Converting 16:9 to 9:16 for Social Media
**Research date:** 2026-06-13  
**Scope:** Subject-aware cropping, push-in motion, smoothing, blur-vs-crop, shot-type rules — with concrete numbers for an ffmpeg-based automated renderer that knows each clip's subject x-position (0..1).

---

## Executive Summary

Converting landscape footage to vertical for Reels/TikTok/Shorts is not a flat center-crop problem. The four principles that separate professional work from amateur are: (1) crop to the subject, not the center; (2) add slow motion to static shots so they feel alive; (3) smooth all position changes so the crop never jerks; (4) choose blur-fill over crop when aggressive scale would destroy context or quality. This document gives concrete numbers for each principle and shows how an ffmpeg renderer can implement them.

---

## 1. Geometry of the Conversion

### 1.1 What you lose
A 1920×1080 frame cropped to 9:16 at the same height produces a 608×1080 native window — only **32% of the horizontal width**. Upscaled to 1080×1920 that is a **1.78× (178%) digital zoom**.  
From 4K (3840×2160): the native 9:16 window is 1215×2160, already above 1080p — safe to crop without upscaling quality loss.  
**Rule: always start from 4K if possible; treating 1080p as the source caps your effective zoom to ~130–150% before softness is visible.** [1][2]

### 1.2 Target output
| Property | Value |
|---|---|
| Resolution | 1080 × 1920 px |
| Aspect ratio | 9:16 |
| Safe content zone | Top 10% and bottom 20% excluded by platform UI overlays |
| Vertical safe zone | Rows 192–1536 (80% of height), i.e. top 10% and bottom 20% blocked |
| Subject eye line | 15–25% from top = rows ~288–480 |

Sources: [3][4]

---

## 2. Subject-Aware Cropping — The Core Rule

### 2.1 Never use a flat center-crop
A center-crop assumes the subject is at x=0.5. Professional tools (Premiere Auto Reframe, DaVinci Smart Reframe, CapCut Auto Reframe, Google AutoFlip) all perform subject detection and track a dynamic crop window. [5][6][7]

### 2.2 Crop x-offset formula
Given subject x-position **sx** (0 = left edge, 1 = right edge) in the original 16:9 frame:

```
# Source: 1920×1080
# Target crop width at 1:1 pixel scale: 608 px (= 1080 × 9/16)
# After upscale to 1080 wide: scale factor = 1080 / 608 = 1.776×

crop_w = round(source_h * 9 / 16)          # = 608 for 1080p source
x_center = round(sx * source_w)            # subject center pixel
x_offset = clamp(x_center - crop_w/2, 0, source_w - crop_w)
```

This keeps the subject centered in the crop window. Clamp prevents the window from going out of frame.

**ffmpeg crop (1080p source, center on subject):**
```
ffmpeg -i input.mp4 \
  -vf "crop=608:1080:X_OFFSET:0, scale=1080:1920" \
  output.mp4
```
Where `X_OFFSET` = computed offset above.

**Dynamic x-offset over time** (subject moves): generate ffmpeg expressions or write keyframes with one crop filter per segment.

### 2.3 Headroom rules
Eyes should land in the upper third: **15–25% from the top of the 1920px output** = rows 288–480.  
- Too much headroom (eyes below 35%) = subject looks tiny, feels amateur.  
- Too little (eyes above 10%) = hair cropped, uncomfortable.  
- For interviews/talking heads: crop so chin is no lower than 60% of frame height, keeping torso visible. [3]

### 2.4 Nose room / lead room
If subject is facing or moving left or right, shift the crop window slightly in the direction they face: add 5–10% of `crop_w` as a lead-room offset. Formula:

```
lead_offset = round(facing_direction * 0.07 * crop_w)
# facing_direction: +1 = right, -1 = left, 0 = frontal
x_offset += lead_offset
x_offset = clamp(x_offset, 0, source_w - crop_w)
```

### 2.5 Rule of thirds in vertical
Horizontal rule-of-thirds applies **differently** in 9:16. The dominant principle is **centered horizontally** (the phone is narrow). Vertical thirds still apply: subject eyes at the upper third intersection (25% from top) is the professional default. [3][4]

---

## 3. When to Push-In vs. Stay Full-Frame

### 3.1 The principle
Static shots feel flat on mobile. A slow push-in (digital zoom creep over the clip duration) adds "aliveness" without drawing attention to itself. The LinkedIn Learning editorial guideline states: "it's so subtle you wouldn't even realize it's there, but it is there." [8]

### 3.2 Decision matrix

| Shot type | Subject movement | Recommended motion |
|---|---|---|
| Talking head / interview | None or minimal | **Slow push-in**: 1.00→1.08, full clip duration |
| Medium shot, subject stationary | None | **Slow push-in**: 1.00→1.10, full clip duration |
| Wide / establishing | None | **Slow push-in** OR stay full if context is critical; 1.00→1.05 over full clip |
| B-roll with movement in-frame | Subject moves | **Tracking crop** follows subject; no additional zoom |
| Action / fast sports | Fast movement | Tracking only; zoom increases jitter risk |
| Close-up (face filling frame) | None/minimal | Stay full or very subtle push 1.00→1.05 |

### 3.3 Punch-in for subject that is already framed tight
When the source is already a close-up and the subject is well-centered in the 9:16 crop, the **crop IS the punch-in** (the 1.78× upscale from 1080p is the punch). No additional zoom needed — adding zoom on top risks visible softness.

### 3.4 Scale / zoom limits by source resolution
| Source | Max safe digital zoom | Notes |
|---|---|---|
| 1080p (1920×1080) | ~130% (1.30×) | Above 150% visible softness [2] |
| 4K (3840×2160) | ~200% (2.00×) | Above 200% softness risk [2] |
| 6K / 8K | ~300% | Ample headroom |

The 9:16 crop itself at 1080p source IS already a ~178% zoom when upscaled. Therefore: **do not add additional zoompan zoom on top of a 1080p center-crop** unless you first scale to a larger intermediate. For 4K sources, adding a 1.0→1.1 zoompan on top of the 9:16 crop is safe.

---

## 4. Slow Push-In Parameters (Ken Burns on Video)

### 4.1 Scale range
Professional practice and multiple editor guides converge on:
- **Subtle (invisible):** 1.00→1.05 (5% zoom growth) over clip duration
- **Noticeable but professional:** 1.00→1.10 (10%) over clip duration  
- **Dramatic / intentional:** 1.00→1.20 (20%) over clip duration — draws attention
- Documentary/Ken Burns standard: typically 2–5 seconds per 10–20% zoom on stills [9]

For a 5-second b-roll clip at 25fps (125 frames):  
- 5% zoom: zoom step per frame = `0.05 / 125 = 0.0004`  
- 10% zoom: step = `0.10 / 125 = 0.0008`

### 4.2 ffmpeg zoompan for slow push-in on video
The key pattern: use `d=1` (duration=1 frame, so the expression re-evaluates every frame) with `pzoom` (previous zoom value):

```bash
# 5% push-in over entire clip, centered, for a 1080x1920 vertical output
ffmpeg -i input.mp4 \
  -vf "scale=8640:-1, \
       zoompan=z='min(pzoom+0.0004,1.05)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=25" \
  -c:v libx264 -crf 18 -pix_fmt yuv420p output.mp4
```

**Why `scale=8640:-1` first?** The zoompan filter works by selecting a sub-region of the input and upscaling it to output size. Pre-scaling to a large intermediate (8× width) dramatically reduces pixelation. For 1080p input, 8× = 8640px wide. For 4K, even smaller prescale is needed. [10]

**Centered on subject at horizontal position sx:**
```
x='(iw*SX)-(iw/zoom/2)'
```
Replace `SX` with the decimal subject x-position (e.g., 0.42). Clamp to `max(0, min(iw-iw/zoom, expr))`.

### 4.3 Zoom-out (pull-back) for reveal effect
```
z='if(eq(on,1), 1.10, max(1.00, pzoom-0.0008))'
```
Starts at 1.10, decreases 0.0008/frame back to 1.00 (revealing more context).

### 4.4 Easing
ffmpeg's `zoompan` uses linear interpolation by default. For a gentle ease-in-out, use a sinusoidal expression:
```
z='1.0 + 0.10 * (1 - cos(PI * on / N)) / 2'
```
Where `N` = total frames. This eases in from 1.0 at frame 0 and arrives at 1.10 at frame N. Replace `PI` with `3.14159265`.

Full ease-in-out push-in command (replace N with actual frame count):
```bash
ffmpeg -i input.mp4 \
  -vf "scale=8640:-1, \
       zoompan=z='1.0+0.10*(1-cos(3.14159265*on/N))/2': \
              x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=25" \
  -c:v libx264 -crf 18 output.mp4
```

---

## 5. Smoothing Reframe Motion (Anti-Jitter)

### 5.1 The problem
AI bounding boxes jitter frame-to-frame. If the crop x-offset is computed directly from per-frame subject detections, the result shakes visibly. Google AutoFlip solves this with **Euclidean-norm optimization: minimize residuals between a smooth low-degree polynomial and the raw bounding box path.** [7]

### 5.2 Practical smoothing for an automated renderer

**Option A: Low-pass filter on x-offset series**  
Apply a 1D Gaussian or moving-average smoothing over the x-offset time series before generating crop commands:
```python
import numpy as np
from scipy.ndimage import gaussian_filter1d

x_offsets_raw = [...]  # per-frame crop x values
x_offsets_smooth = gaussian_filter1d(x_offsets_raw, sigma=15)
# sigma=15 at 25fps ≈ 0.6s smoothing window — good starting point
# sigma=25 ≈ 1s — for slow-moving subjects
```

**Option B: Camera mode selection (AutoFlip strategy)**  
Classify each clip before rendering:
- **Stationary**: Subject barely moves (std-dev of x < 5% of frame width). Use a single static crop. No animation.
- **Panning**: Subject moves monotonically across frame. Use linear interpolation of crop x from start to end position.
- **Tracking**: Subject moves non-linearly. Use smoothed position series.

**Option C: Velocity-limited interpolation**  
Limit the maximum crop-x change per frame:
```python
MAX_PX_PER_FRAME = 4  # at 25fps = 100px/sec max drift
for i in range(1, len(x_offsets)):
    delta = x_offsets[i] - x_offsets[i-1]
    x_offsets[i] = x_offsets[i-1] + clamp(delta, -MAX_PX_PER_FRAME, MAX_PX_PER_FRAME)
```

### 5.3 Premiere Pro's approach by motion preset
| Setting | Use case | Keyframe density | Behavior |
|---|---|---|---|
| Slower motion | Interviews, talking heads | Very few keyframes | Near-static, smooth |
| Default | Most content | Moderate | Follows action |
| Faster motion | Sports, action | Many keyframes | Aggressive tracking |

DaVinci Resolve's Smart Reframe was found to add **80 keyframes vs Premiere's 67** for a 27-second clip, and sometimes adds motion to shots that should be static — requiring manual cleanup. [11]

---

## 6. Blurred Pillarbox vs. Crop: Decision Rules

### 6.1 When crop wins
- Subject stays in a predictable zone of the 16:9 frame  
- 4K or higher source (crop quality loss is minimal)  
- Content is social-native / fast-paced (full-screen fill converts better)
- Single subject, close to center

### 6.2 When blurred pillarbox wins
- Wide / establishing shot where crop removes critical context (e.g., showing a location, crowd, or action across the whole frame)
- 1080p source where cropping to 9:16 + upscale would be visibly soft
- Subject moves across the full width of the 16:9 frame too fast to track cleanly
- Two or more subjects at opposite sides of the frame
- Preserving environmental context is editorially important (event footage, panorama)

Professional guidance: "Use background blur for event footage where you captured the entire stage or venue." [12] However, pure pillarbox (black bars) performs poorly — it "looks lazy" and audiences swipe past in under a second. The **blurred-fill** version retains full-bleed feel. [13]

### 6.3 Pillarbox quality tip
The blurred layer should be: original video scaled to fill 1080×1920, then blurred (sigma 20–40). The sharp layer is the original video scaled proportionally to fit within the frame. The result fills the screen while keeping the original aspect ratio legible.

### 6.4 ffmpeg blurred pillarbox (landscape 16:9 → vertical 9:16)
Adapted from community-verified recipes [14]:

```bash
# Landscape 1920×1080 → 1080×1920 with blurred background
ffmpeg -i input.mp4 -filter_complex \
  "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=30[bg]; \
   [0:v]scale=1080:1920:force_original_aspect_ratio=decrease[fg]; \
   [bg][fg]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2" \
  -c:v libx264 -crf 18 -c:a copy output.mp4
```

**Breakdown:**
1. `[bg]`: scale input to fill 1080×1920 (overflow), crop to exact 1080×1920, blur sigma=30
2. `[fg]`: scale input to fit inside 1080×1920 (letterbox), preserving AR
3. `overlay`: center the sharp layer over the blurred background

---

## 7. Shot-Type-Specific Reframing Rules

### 7.1 Talking head / interview
- Crop tight: eyes at ~20% from top, torso visible to ~60% frame height
- Scale: 1.0–1.1× on top of 9:16 crop (if 4K source)
- Motion: slow push-in 1.00→1.05 over clip duration, or static if already tight
- Premiere motion preset: **Slower motion**
- x-offset: face center ± headroom-aware shift (0.5 unless face is off-center)

### 7.2 Medium shot (waist up, some background)
- Crop to subject, include some background context
- Scale: 1.1–1.3× (bring subject up from small in wide medium shot)
- Motion: slow push-in 1.00→1.08 adds professionalism
- Premiere motion preset: **Default**

### 7.3 Wide / establishing shot
- Decision point: use blur-fill if subject is < 40% of frame height; crop if subject is larger
- If cropping: scale 1.3–1.6× to make subject fill ~50% of vertical frame
- Motion: very subtle push-in 1.00→1.05 or static
- Context note: wide shots often lose their meaning when cropped aggressively; prefer blur-fill + animated subtle zoom toward the key element

### 7.4 Close-up (face fills most of frame)
- The 9:16 crop IS the punch-in. No additional zoom.
- Headroom: ensure top of head clears safe zone (10% from top)
- Motion: static or 1.00→1.03 micro-push only
- Risk: over-zooming a close-up causes uncanny "face squish" effect

### 7.5 Action / B-roll with subject movement
- Tracking mode (dynamic x-offset follows smoothed subject position)
- No push-in — tracking is the motion
- Premiere motion preset: **Faster motion**
- Smooth position changes with sigma-15 Gaussian filter on x-offset series

### 7.6 Two-shot or group shot
- Center crop between subjects (average of x-positions)
- Scale: zoom out enough to keep both in frame; may require 1.5–1.7× for very wide two-shot
- Alternative: use blur-fill to keep both subjects visible, especially if they are at opposite ends of the frame

---

## 8. Platform Safe Zones (Avoid With Subject + Text)

| Platform | Top exclusion | Bottom exclusion | Right exclusion |
|---|---|---|---|
| TikTok | 10% (192px) | 20% (384px) | 10% (108px) |
| Instagram Reels | 8% (154px) | 25% (480px) | 12% (130px) |
| YouTube Shorts | 12% (230px) | 18% (346px) | 8% (86px) |

Keep subject's eyes and key action in **rows 288–1536** (15%–80% of 1920px height). [4]

---

## 9. Summary Decision Tree for the Automated Renderer

```
Input: clip, subject_x (0..1), source_resolution, clip_duration_s, shot_type

IF source_resolution == 1080p AND shot_type == wide:
    → USE blur-fill (crop quality loss too high)
    → ADD subtle push-in 1.00→1.05 on blur layer toward subject

IF source_resolution >= 4K OR shot_type in [talking_head, medium, close_up]:
    → USE subject-aware crop
    → x_offset = clamp(subject_x * source_w - crop_w/2, 0, source_w - crop_w)
    → SMOOTH x_offset series with gaussian_filter1d(sigma=15)
    
    IF shot is stationary (subject_x std_dev < 0.03):
        → USE single fixed crop + slow push-in 1.00→1.08 (ease-in-out)
    ELIF shot has slow drift:
        → USE smoothed tracking + push-in 1.00→1.05
    ELIF shot has fast action:
        → USE fast tracking (sigma=8) + no push-in

Push-in zoom step:
    subtle (< 4s clip):  z_max = 1.05, step = 0.05 / total_frames
    normal (4–10s clip): z_max = 1.08, step = 0.08 / total_frames  
    long (> 10s clip):   z_max = 1.10, step = 0.10 / total_frames

ffmpeg zoompan expression (ease-in-out):
    z='1.0 + Z_RANGE*(1-cos(3.14159265*on/N))/2'
    x='X_SUBJ_CENTER - (iw/zoom/2)'   # pre-scale to 8640px wide first
```

---

## 10. Complete ffmpeg Recipes Reference

### 10.1 Subject-aware crop, static position, 1080p source
```bash
# sx = subject x as decimal, e.g. 0.42
CROP_W=608
X_OFFSET=$(python3 -c "import sys; sx=float(sys.argv[1]); print(max(0, min(1312, round(sx*1920 - 304))))" 0.42)

ffmpeg -i input.mp4 \
  -vf "crop=${CROP_W}:1080:${X_OFFSET}:0, scale=1080:1920" \
  -c:v libx264 -crf 18 -c:a copy output.mp4
```

### 10.2 Slow push-in on 4K source, centered on subject
```bash
# Pre-scale to 8640 wide to reduce zoompan softness
# N = total frames (compute with ffprobe first)
# SX = subject x decimal
ffmpeg -i input_4k.mp4 \
  -vf "scale=8640:-1, \
       zoompan=z='1.0+0.08*(1-cos(3.14159265*on/N))/2': \
              x='iw*SX-(iw/zoom/2)':y='ih/2-(ih/zoom/2)': \
              d=1:s=1080x1920:fps=25" \
  -c:v libx264 -crf 18 -pix_fmt yuv420p output.mp4
```

### 10.3 Blurred pillarbox (1080p wide shot)
```bash
ffmpeg -i input.mp4 -filter_complex \
  "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=30[bg]; \
   [0:v]scale=1080:1920:force_original_aspect_ratio=decrease[fg]; \
   [bg][fg]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2" \
  -c:v libx264 -crf 18 -c:a copy output.mp4
```

### 10.4 Tracking crop with smoothing (dynamic x-offset, Python-generated)
```python
# Pseudocode — generate per-second crop segments
import numpy as np
from scipy.ndimage import gaussian_filter1d

# subject_x_per_frame: array of floats [0..1], one per frame at 25fps
subject_x = np.array([...])
x_offsets = np.round(subject_x * 1920 - 304).astype(int)
x_offsets = np.clip(x_offsets, 0, 1312)
x_offsets = gaussian_filter1d(x_offsets.astype(float), sigma=15).astype(int)

# Build ffmpeg filter with crop=608:1080:X:0 changing each second
# Use sendcmd filter or trim+concat approach
```

---

## Bibliography

1. Klap — "How to Zoom Video for Social Media Without Losing Quality": https://klap.app/blog/how-to-zoom-video  
2. EdicionVideoPro — "9:16 Aspect Ratio Guide" (2026): https://edicionvideopro.com/en/editing-techniques/916-aspect-ratio-guide-vertical-video-for-tiktok-reels/  
3. InfluencersTime — "Vertical Video Framing Tips for Mobile Engagement" (2025): https://www.influencers-time.com/master-vertical-video-framing-for-engaging-mobile-content/  
4. EdicionVideoPro — safe zone breakdown: https://edicionvideopro.com/en/editing-techniques/916-aspect-ratio-guide-vertical-video-for-tiktok-reels/  
5. Adobe Help — "Add Auto Reframe Effect": https://helpx.adobe.com/premiere-pro/using/auto-reframe.html  
6. CapCut — "Auto Reframe" tool: https://www.capcut.com/tools/auto-reframe  
7. Google Research — "AutoFlip: An Open Source Framework for Intelligent Video Reframing" (2020): https://research.google/blog/autoflip-an-open-source-framework-for-intelligent-video-reframing/  
8. LinkedIn Learning — "Slow Zoom-In to Draw Attention": https://www.linkedin.com/learning/video-editing-techniques-for-impactful-content/slow-zoom-in-to-draw-attention  
9. MasterClass — "How to Use the Ken Burns Effect in a Documentary": https://www.masterclass.com/articles/how-to-use-the-ken-burns-effect-in-a-documentary  
10. Bannerbear — "How to Create Videos with a Ken Burns Effect using FFmpeg": https://www.bannerbear.com/blog/how-to-do-a-ken-burns-style-effect-with-ffmpeg/  
11. ELEMENTS Media Storage — "Comparing the Auto Reframe Functions in DaVinci Resolve and Premiere Pro": https://elements.tv/blog/comparing-the-auto-reframe-in-davinci-resolve-and-premiere-pro/  
12. Sureshot Video — "Convert Horizontal Video to Vertical": https://sureshot.video/blog/convert-horizontal-video-to-vertical  
13. Async — "AI Reframe: Horizontal to Vertical Video Converting": https://async.com/blog/horizontal-to-vertical-video-converting/  
14. Community FFmpeg recipe (gblur vertical blur): https://www.junian.dev/tech/ffmpeg-vertical-video-blur/  
15. FFmpeg zoompan mko.re guide: https://mko.re/blog/ken-burns-ffmpeg/  
16. Creatomate — "How to Zoom Images and Videos using FFmpeg": https://creatomate.com/blog/how-to-zoom-images-and-videos-using-ffmpeg  
17. Larry Jordan — "Smart Reframe in DaVinci Resolve 19": https://larryjordan.com/articles/convert-horizontal-video-to-vertical-video-in-davinci-resolve-19/  
18. No Film School — "The Hidden Language of Movies: How the Slow Zoom Builds Intimacy": https://nofilmschool.com/zoom-shots-mean-intimacy  
19. Chier Hu / Medium — "Adapting Videos for Horizontal, Vertical, and Other Aspect Ratios": https://chierhu.medium.com/adapting-videos-for-horizontal-vertical-and-other-aspect-ratios-563837a47fd0  
20. ArneAnka GitHub Gist — FFmpeg blurred background command: https://gist.github.com/ArneAnka/a1348b13fc291f72f862d92f35380428  
