# Slow Motion & Speed Ramps: Research for Automated Cinematic Editing

**Date:** 2026-06-13  
**Context:** Sony FX6 footage (primarily 60fps 4K, up to 120fps FHD), timeline at 23.976fps  
**Purpose:** Rules and decision logic for an automated editor applying slow-mo and speed ramps to b-roll montages

---

## Executive Summary

Slow motion and speed ramps are among the most powerful — and most abused — tools in cinematic editing. Used correctly, they signal *importance*, extend emotional moments, and create a muscular rhythmic feel when locked to music. The core principle that recurs across every professional source: **special effects must remain special**. In a 20–30 second social montage, 30–40% of screen time in genuine slow-mo is the approximate ceiling; beyond that, the effect loses meaning. The FX6 at 60fps gives exactly one clean slowdown ratio against a 23.976 timeline: **40% speed (2.5× slowdown)**. That is the only ratio to use for real-frame slow-mo with 60fps source. Frame-blending and optical flow are fallbacks when source fps is insufficient, but both produce visible artifacts versus true overcranked footage.

---

## 1. WHEN to Use Slow Motion

### 1.1 Subject Types That Earn It

**HIGH-VALUE — use slow motion:**

| Subject / Moment | Why It Works | Notes |
|---|---|---|
| **Water** (pour, splash, droplet, wave) | Motion detail invisible at 24p; slow-mo reveals shape and texture | Even 2.5× transforms a mundane pour into a visual event |
| **Fabric / hair / material in motion** | Captures micro-movement that reads as luxury / production value | Dress hems, flags, curtains, food garnish |
| **Crowd / people in motion** | Creates an impressionistic, cinematic environment shot | Works for stadium, market, street bustle |
| **Gesture / hands / face reaction** | Isolates emotional specificity: a raised eyebrow, a handshake grip | The "emotional close-up" rule — if the gesture tells the story, slow it |
| **Reveals** | Pull-back, product reveal, talent emerge from light | The slow-mo *extends* the reveal beat, preventing it from feeling rushed |
| **Impact moments** | Ball contact, door slam, tool hitting surface | The slowing down telegraphs *weight* |
| **Hero shot** (the anchor clip of a sequence) | The primary payoff image that every other clip builds toward | See Section 5 for hold duration |
| **Motion with strong directionality** | Subject moving purposefully across frame — walking, running, driving | Clean directional motion benefits most from slow-mo |

**Sources:** StudioBinder [1], Pixflow [2], FilmPAC [3], Finchley Learning [4]

### 1.2 When NOT to Use Slow Motion

The following scenarios actively hurt when slowed down:

- **Static subjects with no motion** — slowing a shot of a person standing still, a building, or a product sitting on a shelf adds nothing; it just makes a boring shot last longer. [2]
- **Talking-head / interview b-roll used as illustration** — slow-mo adds an "unreal" gloss that fights the authenticity of documentary-style content. [5]
- **Low-light footage shot at high-fps** — the FX6 at 60fps requires 1/120s shutter minimum (180° shutter rule). In dim environments this forces underexposure or excessive ISO, ruining the clip before it's even slowed. [4]
- **Handheld shots with unintentional camera shake** — slowing down shake *amplifies* it. Save slow-mo for stabilized shots (gimbal, slider, tripod). [4][6]
- **Already-slow narrative pacing** — if the preceding 3 clips are already deliberate, another slow-mo clip creates lethargy, not drama. Slow-mo needs contrast against normal-speed or fast-cut material to register.
- **Clips where the interesting action has already ended** — the shot needs *live motion* during the window being slowed. A reveal that already happened before you hit record has nothing to stretch.
- **Over 40% of total montage runtime** — see Section 6.

**Source:** Videomaker [7], Rocket Productions [5], StudioBinder [1]

---

## 2. HOW MUCH to Slow Down — Frame Math for FX6 + 23.976 Timeline

### 2.1 The Master Formula

```
Playback Speed % = Timeline FPS ÷ Source FPS × 100
```

For a 23.976fps timeline (treated as 24fps for practical math):

| Source FPS | Playback % | Slowdown Factor | Real Frames? |
|---|---|---|---|
| 30fps | 80% | 1.25× | Yes — slight slow |
| 60fps | **40%** | **2.5×** | **Yes — primary FX6 ratio** |
| 120fps | **20%** | **5×** | **Yes — FX6 FHD mode** |
| 240fps | 10% | 10× | Yes (FX6 FHD only) |

**Source:** PremiumBeat [6], Creative COW [8], Adobe Community [9]

### 2.2 The Clean Multiple Rule

Only these percentages give you real, non-duplicated frames. Any other speed (e.g., 35%, 50%, 60%) forces the NLE to either drop or duplicate frames, which creates micro-stutter. **Always conform to one of the values above** when using FX6 source material.

- **FX6 at 60fps → use 40% speed** in a 23.976 timeline. This is your primary workaround. A 5-second real-time clip becomes 12.5 seconds of slow-mo. [8]
- **FX6 at 120fps (FHD) → use 20% speed**. A 2-second event becomes 10 seconds. Reserve this for ultra-dramatic hero moments or impact freezes.
- **S&Q mode on FX6**: When shooting in S&Q, the camera bakes the slow-motion into the clip metadata and the file already reads at 23.976fps in the NLE. No post-processing required — just drop it in. Confirm whether the clip was recorded in S&Q (already conformed) or as a native 60fps file before applying timeline speed changes. [10][11]

### 2.3 The 180° Shutter Rule at High FPS

Always maintain 180° (shutter speed = 2× frame rate) when shooting overcranked:

- 60fps → 1/120s shutter
- 120fps → 1/240s shutter

Violating this creates footage that looks unnaturally sharp (no motion blur), which appears jarring and "video" when slowed down. This is the number one field error with FX6 slow-mo. [4][6]

---

## 3. SPEED RAMPS — Accelerate, Decelerate, and Easing

### 3.1 What a Speed Ramp Is

A speed ramp is a *transition within a single clip* between two different playback speeds. The transition itself (the "ramp") has a duration measured in frames, with Bezier easing curves controlling whether the transition feels gradual or punchy. Unlike a cut between clips, a ramp lets the viewer feel the world change speed — which, done right, is invisible; done wrong, feels mechanical.

**Core editorial principle:** "If I can feel the ramp while watching it, the ramp is wrong." [12]

### 3.2 Ramp Presets and Frame Timing

These are industry-standard timing blueprints sourced from DJordanMedia [12]:

| Preset Name | Ramp-In Duration | Hold Speed | Hold Duration | Ramp-Out | Use Case |
|---|---|---|---|---|---|
| **Cinematic Drift** | 12–15 frames | 30–35% | 10–20 frames | 12–15 frames | Elegance, fashion, emotion |
| **Impact Freeze** | 6–8 frames | 10–15% | 3–5 frames | Fast | Hit, collision, weight moment |
| **Transition Pull** | Full clip | 40–50% | Across cut | — | Cross-clip flow, no hard hold |
| **Reverse Ramp** | — | 20–30% | Starts slow | 20–25 frames out | Building tension toward cut |

At 23.976fps, "12–15 frames" ≈ 0.5–0.625 seconds of transition time. This is long enough to feel smooth but short enough not to distract.

### 3.3 Easing Curves

Never use linear speed interpolation. Always apply Bezier or ease-in/ease-out curves:

- **Ease-out** (decelerate): footage starts at normal speed and *glides* into slow-mo. Feels luxurious, contemplative.
- **Ease-in** (accelerate): footage *launches* out of slow-mo into normal or fast speed. Feels energetic, propulsive — the classic "slingshot" feel coming out of a beat drop.
- **Ease-in + ease-out** (both): smooth S-curve transition. Most natural for seamless invisible ramps.

Rule for Bezier handle positioning: pull handles approximately **30–40% of the distance between keyframes** for standard easing. Shorter = snappier; longer = more cinematic drift. [12]

### 3.4 Emotional Feel by Ramp Type

| Ramp Direction | Emotional Effect | When to Use |
|---|---|---|
| Fast → Slow (decelerate) | Gravity, weight, significance, luxury | Entering a hero moment, emotional reveal, water detail |
| Slow → Fast (accelerate) | Energy, propulsion, time-passing, urgency | Exiting a moment, transitioning into action, beat drop punch |
| Slow → Full Stop (freeze) | Maximum dramatic emphasis | Peak of motion: jump apex, splash crown, collision impact |
| Fast → Slow → Fast | Wave-like rhythm | Music-synced montage with even beats |

**Sources:** Stephen Frowe [13], Kapwing [14], Filmora [15]

---

## 4. SYNCING SLOW-MO / RAMPS TO MUSIC

### 4.1 The Beat Drop Rule

The most effective placement for a speed ramp's *bottom* (the slowest point) is **on or 2–4 frames before the musical beat or drop**. Because the ramp into slow-mo takes 6–15 frames, you begin the deceleration before the beat so that the *held slow point* lands exactly on the downbeat. This creates the feeling that the music caused the world to slow down.

```
Timeline position:
  ... [normal speed] ... [ramp begins @ frame N-12] ... [held slo-mo @ frame N] [BEAT] ...
```

For accelerating out of a drop, place the ramp-out to begin on the beat or 2–4 frames after, accelerating *into* the next phrase. [15][12]

### 4.2 Identifying Sync Points

Types of musical moments that earn a ramp:
- **Downbeat / kick drum** — the hardest, most reliable hit
- **Snare backbeat** — works for impact ramps on strong 2 and 4
- **Melodic resolve** — a chord arriving home; use a gentle drift ramp, not an impact freeze
- **Drop / build release** — the biggest moment in electronic/trailer music; earns the full Impact Freeze preset
- **Silence before a hit** — ramp into the slow-mo during the silence; the beat "releases" the hold

Rule: **One major speed event per musical bar** at most. Two ramps in 4 beats feels spastic unless you are making a dance-edit where the rhythm is the point.

### 4.3 Sync Workflow

1. Place audio on timeline first.
2. Mark beat positions with markers (M key in Premiere/Resolve).
3. Place clips so the *intended slow-mo window* falls over the marker.
4. Apply ramp, set hold to land on marker.
5. Use the graph editor to verify the speed curve crosses the target speed at exactly the marker frame.

**Sources:** Filmora [15], ReelMind [16], DJordanMedia [12]

---

## 5. THE HERO SHOT HOLD

The "hero shot" is the single most important clip in a montage — the payoff image that every preceding clip has been building toward. Treatment:

- **Duration in the edit:** 2–4 seconds of held slow-mo (at 40% playback, this requires 5–10 seconds of source footage to fill).
- **Speed:** typically 30–40% (Cinematic Drift range) rather than an extreme 10–15% freeze. Extreme freezes are for impact hits; hero moments want *movement* — just slow, deliberate movement. Water, fabric, a face turning toward camera. [1][2]
- **Entry:** always ramp in (decelerate). Never cut directly to a held slow-mo — it reads as a mistake unless stylistically intentional.
- **Exit:** typically ramp out (accelerate) or hard cut on a musical hit. A gentle ramp out feels softer; a hard cut out is more aggressive/editorial.
- **Position in montage:** the hero shot belongs in the final third. In a 20–30 second montage, this means seconds 15–25. It is the emotional peak the edit has earned.

Viewer absorption research: "most viewers need roughly 3 seconds to absorb a shot fully; beyond 5 seconds, attention begins to fade." [17] At 40% playback, a 3-second screen hold requires just 1.2 seconds of real-time source footage — keep source clips longer than you think you need.

---

## 6. HOW MUCH SLOW-MO IS TOO MUCH

### 6.1 The 30–40% Rule

No formal percentage is universally codified, but the consistent editorial consensus synthesized across sources:

> **In a 20–30 second montage, no more than 30–40% of total runtime should be in slow-motion.**

- 20-second montage → max 6–8 seconds of screen time in slow-mo
- 30-second montage → max 9–12 seconds of screen time in slow-mo

This leaves the remainder in normal speed (or faster-than-normal). The normal-speed clips are what give slow-mo its *contrast* and therefore its power.

### 6.2 Structural Distribution

Avoid clustering all slow-mo at the same point. Recommended distribution for a 6-clip 25-second montage:

| Clip | Speed | Purpose |
|---|---|---|
| 1 | 100% (normal) | Establishes world/context quickly |
| 2 | 40% (2.5×) | First slow-mo surprise, 2 sec hold |
| 3 | 100% | Palette cleanser, energy refresh |
| 4 | 100% → ramp to 40% | Speed ramp into hero approach |
| 5 | 40% (hero shot, 3–4 sec) | The emotional peak |
| 6 | 100% or speed ramp to fast | Exit energy |

This gives ~6–7 seconds of slow-mo in a 25-second video — roughly 25–28% — within the healthy range.

### 6.3 Warning Signs of Over-Use

- Every clip is slowed to 40%: viewer becomes anesthetized; effect disappears.
- Slow-mo on the opening clip: wastes the contrast effect at the beginning; viewers have no normal-speed baseline to compare against.
- Slow-mo on clips with no interesting motion: compounds the "boring" quality instead of masking it.

**Sources:** Pixflow [2], Videomaker [7], Rocket Productions [5], StudioBinder [1]

---

## 7. REAL FRAMES vs FRAME-BLENDING vs OPTICAL FLOW

### 7.1 The Hierarchy

```
REAL FRAMES (overcranked source) > Optical Flow > Frame Blending
```

**Real frames** (shooting 60fps or 120fps) are always the best option. The camera captured actual photons at every intermediate moment. There is no interpolation, no artifact, no softening. The motion blur in each frame is physically correct (follows the 180° shutter rule). This is always what to prefer when possible. [6][18]

**Optical Flow** analyzes pixel motion vectors and *synthesizes* new intermediate frames. When it works (clean, high-contrast footage with simple motion), it is nearly indistinguishable from real frames. When it fails, it warps and ghosts — most commonly on:
- Water/liquid (complex non-rigid motion)
- Foliage (millions of independent motion vectors)
- Fast camera movement
- Low-quality/noisy source footage

**Frame Blending** simply cross-dissolves between existing frames. It is faster to compute (real-time playback in NLE) but inherently blurrier. It is the last resort for "this is all we have." [18]

### 7.2 When to Use Each

| Slowdown Factor | Source FPS | Recommendation |
|---|---|---|
| 2.5× | 60fps | Real frames at 40%. No interpolation needed. |
| 5× | 120fps | Real frames at 20%. |
| Any | 24fps native | Optical Flow only if footage is clean/simple. Avoid on water/foliage. Never frame-blend below 50% of a 24p original. |
| 3–4× | 60fps (partial) | Optical Flow acceptable if footage is stable and high-contrast |

### 7.3 Artifacts and Failure Modes

- **Frame blending** on complex motion (crowd, water): smeared, painterly ghost images.
- **Optical flow** on fast camera moves: the background warps and "swims."
- **Both** on low-quality source: amplify noise and compression artifacts.

The automated editor's decision logic: **if source_fps ÷ timeline_fps ≤ a clean integer (e.g., 2.5× from 60fps), use real frames with no interpolation. If the requested slow factor exceeds what real frames provide, use optical flow only for simple/clean subjects; flag water, foliage, and crowd shots for manual review.**

**Sources:** Boris FX [18], Adobe Community [19]

---

## 8. AUTOMATED EDITOR DECISION LOGIC

### 8.1 Clip Classification Inputs

The automated director should tag each clip with:
- `source_fps`: read from file metadata
- `motion_type`: detected or tagged (water, crowd, gesture, reveal, static, action, hero)
- `has_gimbal_stabilization`: boolean
- `timeline_fps`: project constant = 23.976

### 8.2 Decision Tree

```
IF source_fps == 60:
    base_slowmo_speed = 40%  (2.5× — clean real frames)
    base_slowmo_factor = 2.5

IF source_fps == 120:
    base_slowmo_speed = 20%  (5× — clean real frames)
    base_slowmo_factor = 5.0

IF source_fps == 24 AND slow_desired:
    FLAG: no real frames available
    → use optical flow ONLY if motion_type is NOT in [water, foliage, crowd]
    → else skip slow-mo for this clip

APPLY slow motion IF:
    motion_type IN [water, fabric, gesture, reveal, hero, impact, crowd]
    AND has_gimbal_stabilization == true
    AND clip_duration_real_seconds >= 1.5   (need content to stretch)

DO NOT slow IF:
    motion_type IN [static, talking_head, low_light]
    OR clip is first clip of montage  (preserve contrast baseline)
    OR montage_slowmo_runtime / montage_total_runtime > 0.40

HERO SHOT:
    → position in final third of montage (after 60% mark)
    → apply Cinematic Drift ramp-in (12 frames @ 23.976 = 0.5s)
    → hold at 40% for 3–4 seconds screen time
    → ramp-out on next beat marker or hard cut
```

### 8.3 Speed Ramp Insertion Rules

```
FOR each musical beat marker B:
    IF preceding clip ends within 0.5s of B AND next clip is hero/impact:
        → insert Cinematic Drift ramp beginning 12 frames before B
        → hold slow point AT B

    IF beat is a DROP (detected by amplitude spike):
        → insert Impact Freeze ramp beginning 6–8 frames before B
        → hold at 10–15% for 3–5 frames
        → ramp out fast (6 frames)

    EASING: always Bezier (ease-in/ease-out), handles at 30–40% of keyframe distance
    INTERPOLATION: set NLE to "Optical Flow" ONLY if motion_type is clean; else "None" (real frames)
```

---

## 9. SUMMARY TABLE — Quick Reference

| Parameter | FX6 60fps | FX6 120fps (FHD) | 24fps Source |
|---|---|---|---|
| **Playback speed** | 40% | 20% | Avoid; OF only |
| **Slowdown** | 2.5× | 5× | Varies |
| **Screen time from 1s source** | 2.5s | 5s | — |
| **Interpolation needed** | No | No | Yes (OF) |
| **Best for** | Cinematic drift, hero | Ultra-dramatic, impact | Last resort |

| Ramp Preset | Ramp Duration | Hold Speed | Hold Duration | Use Case |
|---|---|---|---|---|
| Cinematic Drift | 12–15 frames | 30–35% | 10–20 frames | Emotion, reveal |
| Impact Freeze | 6–8 frames | 10–15% | 3–5 frames | Hit, collision |
| Transition Pull | Full clip | 40–50% | Cross-clip | Flow |
| Reverse Ramp | 20–25 frames out | 20–30% | Starts slow | Tension build |

---

## 10. LIMITATIONS AND CAVEATS

1. No single authoritative published rule exists for the "30–40% montage slow-mo ceiling" — this figure is synthesized from multiple professional editorial voices and practical convention, not a formalized standard.
2. Frame-count timing presets (12–15 frames, 6–8 frames) come from practitioner sources [12], not academic or broadcast standards bodies.
3. S&Q behavior on FX6 varies by firmware version. Always confirm in post whether the clip arrives pre-conformed or as native high-fps.
4. Optical flow quality varies dramatically by NLE version and GPU. DaVinci Resolve's OF is generally superior to Premiere Pro's for complex motion; test on each project.
5. Music sync beat placement advice assumes BPM-driven editing. For non-rhythmic audio (ambient, dialogue-led), ramp timing follows emotional arc, not beats.

---

## Bibliography

[1] StudioBinder — "How to Use Slow Motion to Create Iconic Moments"  
https://www.studiobinder.com/blog/how-to-use-slow-motion-in-film-to-create-iconic-moments/

[2] Pixflow — "Professional Use of Slow-Motion & Fast-Forward in Filmmaking"  
https://pixflow.net/blog/professional-use-of-slow-motion-fast-forward-in-filmmaking/

[3] FILMPAC — "What You Need To Know To Shoot Cinematic Slow Motion"  
https://filmpac.com/what-you-need-to-know-to-shoot-cinematic-slow-motion/

[4] Finchley Learning — "Mastering Slow Motion Video Editing: Cinematic Tips"  
https://www.finchley.co.uk/finchley-learning/mastering-slow-motion-video-editing-cinematic-tips-for-your-next-shoot

[5] Rocket Productions — "Should I Always Film Office B-Roll Shots in Slow Motion?"  
https://rocketproductions.com.au/blog/should-i-always-film-office-b-roll-shots-in-slow-motion/

[6] PremiumBeat — "How to Achieve Perfect Slow-Motion Results in Post"  
https://www.premiumbeat.com/blog/how-to-achieve-perfect-slow-motion-results-in-post/

[7] Videomaker — "Here's a Few Ways to Make Your B-Roll Look Awesome Without Using Slow-Motion"  
https://www.videomaker.com/heres-a-few-ways-to-make-your-b-roll-look-awesome-without-using-slow-motion/

[8] Creative COW — "Any TIPS for Slow-Motion @ 60fps?"  
https://creativecow.net/forums/thread/any-tips-for-slow-motion-60fpsaeae/

[9] Adobe Community — "Slowing 60fps footage for a 24fps timeline"  
https://community.adobe.com/questions-529/slowing-60fps-footage-for-a-24fps-timeline-47544

[10] Sony Cinematography — "Know Your FX6: S&Q Mode"  
https://sony-cinematography.com/articles/know-your-fx6-sandq-mode-sony-cine/

[11] Film Plus Gear — "Slow and Quick Motion with the Sony FX6"  
https://filmplusgear.com/slow-and-quick-motion-with-the-sony-fx6/

[12] DJordanMedia — "After Effects Speed Ramp Tutorial (The Right Way)"  
https://djordanmedia.com/blogs/news/after-effects-speed-ramp-tutorial

[13] Stephen Frowe — "Understanding Speed Ramping in Modern Filmmaking"  
https://stephenfrowe.com/archives/143

[14] Kapwing — "How to Use the Speed Ramp Effect (with Examples)"  
https://www.kapwing.com/resources/how-to-use-the-speed-ramp-effect/

[15] Filmora / Wondershare — "Speed Ramping Tutorial: Speed Up and Slow Down a Video"  
https://filmora.wondershare.com/video-editing-tips/speed-ramping.html

[16] ReelMind — "Automated Video Time Warp: Smooth Speed Ramps with Audio Sync"  
https://reelmind.ai/blog/automated-video-time-warp-smooth-speed-ramps-with-audio-sync

[17] Motion Edits — "The Art of Pacing: How We Edit for Maximum Engagement"  
https://motionedits.com/the-art-of-pacing-how-we-edit-for-maximum-engagement/

[18] Boris FX — "Optical Flow vs Frame Blending: What is the Main Difference"  
https://borisfx.com/blog/optical-flow-vs-frame-blending-main-difference/

[19] Adobe Community — "Frame-Blending vs Optical Flow"  
https://community.adobe.com/t5/premiere-pro/frame-blending-vs-optical-flow/td-p/10608955

[20] MixMoov — "Using Slow Motion and Speed Ramping"  
https://www.mixmoov.com/using-slow-motion-speed-ramping/

[21] IndieFilming — "Tutorial: Sony S&Q Mode"  
https://indiefilming.com/tutorials/sony-sq-mode

---

*Researched 2026-06-13. Part of MNN Auto-Editor superpowers documentation.*
