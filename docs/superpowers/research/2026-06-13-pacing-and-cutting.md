# Pacing & Cutting for Automated Social/Music-Video Editors
## Research Findings — 2026-06-13

**Purpose:** Encode professional pacing and cutting techniques into automatable rules for an AI director that picks clips, in/out points, and assembly order from a b-roll pool, synchronized to a known music beat grid.

---

## Sources

1. VashiVisuals — Vashi Nedomansky ACE, music video ASL analysis: https://vashivisuals.com/music-video-editing-stats/
2. PremiumBeat — Timing Music to Video Edits (Brent Pierce tutorial): https://www.premiumbeat.com/blog/timing-music-for-video-editing/
3. PremiumBeat — Interview with Ernie Gilbert (editor, "This Is America"): https://www.premiumbeat.com/blog/interview-editor-this-is-america/
4. Film Editing Pro — Fast vs. Slow Pacing Tips: https://www.filmeditingpro.com/fast-vs-slow-video-editing-pacing-tips/
5. Film Editing Pro — Music Editing Timing Tips: https://www.filmeditingpro.com/music-editing-timing-tips-to-control-pacing-intensity/
6. Inside The Edit — Biggest Mistake Editors Make When Cutting Music (Paddy): https://www.insidetheedit.com/blog/mistake-editors-make-cutting-music
7. SteedFilms — Stop Cutting to the Beat: https://www.steedfilms.com/learn/stop-cutting-to-the-beat-thats-lazy-editing
8. Beat2Cut — Beat-Sync Video Editing Complete Guide: https://beat2cut.com/blog/beat-sync-video-editing-complete-guide/
9. LBBOnline — More Than Just Cutting to the Beat (professional music video editor interviews): https://lbbonline.com/news/more-than-just-cutting-to-the-beat-the-nuance-of-editing-music-videos
10. Silverman Sound — BPM to FPS Calculator: https://www.silvermansound.com/bpm-to-fps-calculator
11. VidPros — Video Clip Length Ultimate Guide: https://vidpros.com/video-clip-length/
12. MotionEdits — Art of Pacing: https://motionedits.com/the-art-of-pacing-how-we-edit-for-maximum-engagement/
13. NoFilmSchool — Larry Jordan Montage Techniques: https://nofilmschool.com/2014/09/larry-jordan-teaches-us-how-create-video-montage-set-music
14. ProEditors.Club — Pacing guide: https://proeditors.club/resources/pacing
15. FilmDaft — Cutting to the Beat: https://filmdaft.com/how-to-edit-video-clips-to-the-beat-of-music-the-easy-way/
16. Studiobinder — Walter Murch Rule of Six: https://www.studiobinder.com/blog/walter-murch-rule-of-six/
17. Studiobinder — Soviet Montage Theory: https://www.studiobinder.com/blog/soviet-montage-theory/
18. PremiumBeat — Three-Second Rule in Cinematography: https://www.premiumbeat.com/blog/cinematography-following-three-second-rule/
19. Viewinder — Hiro Murai Film School: https://viewinder.com/hiro-murai/
20. GoTranscript — Mastering Pacing & Rhythm: https://gotranscript.com/public/mastering-pacing-and-rhythm-essential-editing-techniques-for-engaging-videos
21. Brandefy — Optimize First 3 Seconds: https://brandefy.com/optimize-first-3-seconds-video/
22. Beat2Cut — Final Cut Pro Beat Sync: https://beat2cut.com/blog/how-to-sync-video-to-music-beats/
23. Cornell University study (via FilmEditingPro) on ASL reduction: 12 seconds (1930) → 2.5 seconds (current)
24. EditorsKeys — How to Edit Music Videos Like a Pro: https://www.editorskeys.com/blogs/news/how-to-edit-music-videos-like-a-pro-sync-techniques-creative-effects-transitions
25. Mubert — How to Match Music with Video Pacing: https://mubert.com/blog/how-to-match-music-with-video-pacing

---

## Key Named Editors Referenced

- **Vashi Nedomansky, ACE** — American Cinema Editors member; published the first quantitative ASL analysis of modern music videos; found one video with ASL of 0.3s (strobing dissolve-accumulation style). [1]
- **Ernie Gilbert** — Editor of Childish Gambino "This Is America" (dir. Hiro Murai); also cut "Somebody I Used to Know"; uses Adobe Premiere Pro; describes his instinct as "less cutty, more lingering." [3]
- **Hiro Murai** — Director (not editor) whose style favors repetitive rhythmic cut patterns on Childish Gambino/Earl Sweatshirt videos. [19]
- **Walter Murch, ACE** — Creator of the Rule of Six; coined "Emotion first, rhythm third" hierarchy. [16]
- **Larry Jordan** — Editor/educator; taught that cutting to secondary beats (not primary downbeats) avoids robotic feel. [13]
- **Paddy (Inside The Edit)** — Teaches the "Duet Theory" — music and dialogue/action alternate rather than overlap, and cut to individual instrument layers. [6]
- **Sergei Eisenstein** — Theorized Metric, Rhythmic, Tonal, Overtonal, and Intellectual montage; metric montage is the foundational rule-set for beat-locked cutting. [17]

---

## TECHNIQUE 1 — Beat-Grid Foundation: BPM → Shot-Length Formula

### What It Is
Every musical beat is a candidate cut point. The duration of one beat is determined by BPM. At common social/music-video tempos, beats fall every 0.375–0.6 seconds.

### The Math [Source 10]
```
seconds_per_beat = 60 / BPM

Common values:
  100 BPM → 0.600 s/beat
  120 BPM → 0.500 s/beat
  128 BPM → 0.469 s/beat
  140 BPM → 0.429 s/beat

seconds_per_bar (4/4 time) = seconds_per_beat × 4
  100 BPM → 2.40 s/bar
  120 BPM → 2.00 s/bar
  128 BPM → 1.875 s/bar
  140 BPM → 1.714 s/bar

Common cut-duration multiples (in beats):
  1 beat  = 0.43–0.60 s  (ultra-fast; drop sections)
  2 beats = 0.86–1.20 s  (fast; chorus/drop)
  4 beats = 1.71–2.40 s  (standard; chorus)
  8 beats = 3.43–4.80 s  (relaxed; verse)
  16 beats = 6.86–9.60 s (slow; intro/outro/bridge hold)
```

### Anticipation Offset Rule [Source 8]
Cut 1–2 frames BEFORE the beat, not on it. Due to visual processing lag, an early cut feels perfectly synchronized. At 24 fps, 1 frame = 41.7ms; 2 frames = 83ms.

### Automatable AI Rule
```
shot_duration_beats = choose_from(allowed_beat_multiples_for_section)
cut_point_frames = beat_frame_index - 1   // 1-frame anticipation offset
shot_duration_seconds = shot_duration_beats × (60 / BPM)
```

---

## TECHNIQUE 2 — Cutting on the Beat vs. the Downbeat

### What It Is
In 4/4 time there are four beats per bar. Beat 1 (the downbeat) is the strongest. Beats 2 and 4 carry the snare (backbeat). Beats 3 is a secondary downbeat. Off-beats (the "and" of each beat, 8th-note positions) add syncopation.

### The Rules [Sources 2, 8, 15]

| Cut type | When to use | Effect |
|---|---|---|
| Downbeat (beat 1 of bar) | Major scene/section changes | Authoritative, clear |
| Snare hit (beats 2 & 4) | Action, emphasis cuts | Punchy, energetic |
| Kick drum hit | Any strong transient | Hard, physical |
| 16th-note lift (1/16 before beat 1) | Adding interest to section boundaries | Creates forward pull |
| Off-beat ("and" of 2 or 4) | Syncopated feel | Exciting, unexpected |
| Skip a downbeat (cut on beat 2 of bar) | Breaking predictability | Surprising, modern |

**Critical rule:** Never cut ONLY on beat 1 of every bar. That is the most common beginner mistake. [Sources 2, 9, 13]

### Automatable AI Rule
```
candidate_cut_points = [beat_1, beat_2, beat_3, beat_4, 
                        16th_note_before_bar_start]
primary_cuts = downbeats (beat_1)     // use for section-change cuts
secondary_cuts = snare + kick hits    // use for within-section cuts
syncopation_cuts = off_beat_8th_notes // inject ~15–25% of cuts here
avoid = cutting on every consecutive beat_1 without variation
```

---

## TECHNIQUE 3 — Mapping Cut Density to Musical Energy Sections

### What It Is
Shot duration (and therefore cut density) should mirror the musical energy curve: slow/spacious in intros and verses, building toward drops/choruses, maximum density at the peak, then relaxing in bridges and outros.

### Shot Duration by Section [Sources 1, 4, 7, 11, 12, 20]

| Song section | Energy level | Target shot duration | Cut density |
|---|---|---|---|
| Intro | Low → building | 6–16 beats (3–10 s at 120 BPM) | 1 cut per bar or less |
| Verse | Low–medium | 4–8 beats (2–4.8 s) | 1 cut per 2 bars |
| Pre-chorus / build | Medium → high | 2–4 beats (1–2.4 s) | 1 cut per bar |
| Chorus | High | 2–4 beats (1–2.4 s) | 1–2 cuts per bar |
| Drop (EDM) | Peak | 1–2 beats (0.43–1.2 s) | 2–4 cuts per bar |
| Post-drop decay | High → medium | 4 beats (2 s) | 1 cut per bar |
| Bridge / breakdown | Low | 8–16 beats (4–10 s) | 1 cut per 2–4 bars |
| Outro | Low → end | 8–16+ beats (4–10+ s) | Slow out; hold last shot |

**From VashiVisuals data [1]:** Top-charting music videos average 3.5 s/clip during choruses, 5–6 s during verses. The extreme outlier was 0.3 s/clip (strobe-style dissolve). General current music video ASL is ~2 s.

**Social/short-form specifics [11]:**
- TikTok / Reels: 1–2 s clips for peak sections
- YouTube Shorts: 2–3 s clips
- Music video (beat-synced): 2–6 s overall range

### Energy-Level Shot Duration Thresholds

```
energy_level → target_shot_duration_beats:
  0.0–0.2  (ambient/silent) → 16 beats
  0.2–0.4  (intro/verse)   → 8 beats
  0.4–0.6  (pre-chorus)    → 4 beats
  0.6–0.8  (chorus)        → 2 beats
  0.8–1.0  (drop/peak)     → 1 beat
  
energy_level can be derived from:
  - RMS loudness of audio at that time position
  - Beat density (number of transients per second)
  - Section label from song structure analysis (verse/chorus/drop)
```

### Automatable AI Rule
```
for each_clip:
  section = get_section(clip.beat_position)  // intro/verse/chorus/drop/etc
  energy = get_energy(clip.beat_position)    // 0.0–1.0
  target_beats = map_energy_to_beats(energy) // see table above
  duration_seconds = target_beats × (60 / BPM)
  clip.out_point = clip.in_point + duration_seconds
```

---

## TECHNIQUE 4 — Cutting on Action / Motion

### What It Is
Cut mid-motion: when a subject is physically in motion (pan, turn, reach, throw, step), cut to the next shot at the beginning of that motion — not before it starts and not after it ends. The viewer's eye follows the trajectory and the cut becomes invisible.

### The Rule [Sources from Wikipedia Cutting on Action, VideoMaker, FilmSupply]
- Cut at approximately the **first third** of the action (1/3 through the motion arc)
- Never cut at the beginning (static) or end (static) of a motion — the viewer's eye is not engaged
- The incoming shot should show the same or continuing motion from a different angle

### For b-roll / montage (non-narrative) version:
- Prefer clips that **begin with motion in frame** — this creates immediate visual engagement
- Prioritize clips where camera or subject starts moving within the first 12 frames (0.5 s)
- A clip that "arrives" into motion reads as more energetic than one that "settles" out of it

### Automatable AI Rule
```
score_clip_for_motion_entry(clip):
  motion_in_first_0.5s = detect_optical_flow(clip, 0, 0.5s) > threshold
  if motion_in_first_0.5s:
    clip.motion_entry_score = HIGH     // prefer as cut target
  else:
    clip.motion_entry_score = LOW

sort_clips_by(motion_entry_score) for high-energy sections
cut_point_within_clip = frame where optical_flow velocity peaks
// i.e., cut IN at the moment of peak motion, not at rest
```

---

## TECHNIQUE 5 — J-Cuts and L-Cuts (Split Edits)

### What They Are [Sources 4, 6, Adobe docs, EpidemicSound]
- **J-Cut:** Audio from the NEXT clip starts before the video cuts. Viewer hears the incoming scene before seeing it. Creates anticipation/forward pull.
- **L-Cut:** Audio from the PREVIOUS clip continues after the video has already cut to the next scene. Viewer sees new content while still hearing the old. Creates continuity/lingering resonance.

### Rules for Music Videos / Social Content
- J-cuts work best as **section transitions**: the audio of the chorus hits while the video is still on the last verse shot (0.5–2 beats of audio lead)
- L-cuts work well after an **emotional peak**: hold the audio of the impact moment while the video moves to a reaction or wide shot
- In purely music-synced b-roll edits, J/L cuts are most useful for **ambient/natural sound layered under music**: outdoor sound starts 1–2 seconds before the outdoor clip appears (J-cut feel)
- Walter Murch noted that "we cut when a thought is complete" — J/L cuts allow thought to bleed across the picture edit, creating more fluid cognition [16]

### Automatable AI Rule
```
j_cut(clip_A, clip_B):
  // Blend or crossfade natural audio from clip_B starting 0.5–2.0 s
  // before clip_B's video in-point
  audio_lead_seconds = random_uniform(0.5, 2.0)
  clip_B.audio_in = clip_B.video_in - audio_lead_seconds

l_cut(clip_A, clip_B):
  // Extend clip_A's audio past its video out-point by 0.5–1.5 s
  audio_tail_seconds = random_uniform(0.5, 1.5)
  clip_A.audio_out = clip_A.video_out + audio_tail_seconds

apply_j_cuts: preferentially on section-change cuts (verse→chorus, drop entry)
apply_l_cuts: preferentially after high-impact moments (drop landing, emotional beat)
```

---

## TECHNIQUE 6 — Match Cuts

### What They Are [Sources from Studiobinder, MotionEdits, Wikipedia]
A match cut transitions between two shots that share a visual property: shape, color, motion direction, action, or composition. Creates a "visual rhyme" — the juxtaposition produces a third meaning neither shot carries alone.

### Types
1. **Action match cut**: Same physical action continued across two different shots/locations
2. **Graphic match cut**: Two shots with matching shapes, colors, or composition (e.g., circle sun → round logo)
3. **Match-on-motion**: A camera movement (pan left) in shot A is continued by same-direction motion in shot B
4. **Eyeline match**: Character looks off-screen; cut to what they see

### For B-Roll Montage / Automation
- Match cuts raise perceived production value without additional footage
- Most valuable match cut for automated editing: **match-on-motion** — pair clips where optical flow vectors are aligned at the cut point
- Second most valuable: **graphic match** — pair clips where dominant hue, composition zone, or silhouette shape is similar

### Automatable AI Rule
```
find_match_cut_pairs(pool):
  for each clip_A ending_in_motion:
    find clip_B where:
      optical_flow_direction(clip_B.first_frames) 
        ≈ optical_flow_direction(clip_A.last_frames)  // ±30 degrees
      OR dominant_color(clip_B.first_frame) 
        ≈ dominant_color(clip_A.last_frame)           // ΔE < 15
      OR composition_weight_zone(clip_B.first_frame) 
        ≈ composition_weight_zone(clip_A.last_frame)  // same third
  
  match_cut_pairs = ranked list
  insert match cuts at ~20–30% of total cuts for visual variety
```

---

## TECHNIQUE 7 — Variable Shot-Length Patterns (Anti-Monotony)

### The Core Problem [Sources 7, 8, 9, 13]
When every shot is the same duration (e.g., exactly 2 beats per clip throughout), the viewer subconsciously detects the pattern and mentally "exits" — attention drifts to the rhythm itself rather than the content. This is called "robotic rhythm."

Named editor Larry Jordan: "You'll create a predictable rhythm that will cause the viewer to anticipate the cuts, distracting them from the actual content." [13]

### The Solution: Intentional Variation Patterns

**Four pacing patterns identified [Source 14]:**

1. **Linear Rise**: Shots start long and progressively shorten as energy builds
   - e.g., 8-beat → 4-beat → 2-beat → 1-beat over the course of a build section

2. **The Wave**: Alternating long and short shots (tension/release cycles)
   - e.g., 4-beat → 1-beat → 4-beat → 1-beat within a chorus

3. **Spike/Punchy**: Mostly consistent medium shots with sudden bursts of ultra-fast cuts
   - e.g., 4-beat × 3 shots → 1-beat × 4 shots → back to 4-beat

4. **Consistent Pace with Secondary Beat Variation**: Holds to a base duration but varies which beat the cut falls on
   - e.g., always 4-beat shots, but cuts alternating between beat-1 and beat-3, or occasionally the "and" of beat-2

### Specific Anti-Monotony Rules
- **Never repeat the same shot duration more than 3–4 consecutive times** [Sources 7, 13]
- **Vary cut points** within a bar: use beat-1 for ~50% of cuts, snare (beat-2 or 4) for ~30%, off-beat for ~20% [Source 8]
- **Occasionally skip a beat**: hold a clip for 3 beats when the pattern established 2-beat cuts — the viewer feels surprise and re-engages [Source 2]
- **Larry Jordan's "secondary beat" rule**: At least 20–30% of cuts should fall on secondary beats (beats 2, 3, 4 or subdivisions), never exclusively on beat-1 [13]

### Automatable AI Rule
```
anti_monotony_rules:
  max_consecutive_same_duration = 3
  min_duration_variation_ratio = 0.3   // ≥30% of shots differ from modal duration
  
  beat_offset_distribution:
    beat_1   = 50%
    beat_2/4 = 30%
    off-beat = 20%
  
  inject_hold_shot(probability=0.1):
    // 10% chance of a 2× longer shot to break pattern
    shot_duration = normal_duration × 2
```

---

## TECHNIQUE 8 — Building and Releasing Energy (Tension-Release Architecture)

### What It Is
Energy in a music video edit operates in cycles: build, peak, decay. Tension is created by increasing cut density and motion; release happens when pacing suddenly slows or a single long shot holds. Without release, sustained tension becomes fatigue.

### Specific Rules [Sources 7, 12, 14]

**Building energy:**
- Progressively shorten shot durations from section start to drop/chorus peak
- Linear build: at 120 BPM, a 16-bar pre-chorus could go 8-beat → 4-beat → 2-beat → 1-beat over its four 4-bar phrases
- Add motion: prefer clips with camera movement (pan, tilt, zoom) over static shots as energy rises
- Insert speed ramp: slow the footage to 50–70% speed 1–2 bars before the drop to create anticipation, then snap to 100% or 120% on the downbeat [speed ramp sources]

**Releasing / resolving energy:**
- On the bar immediately AFTER the drop's first phrase (typically bar 2 or 3), insert one 4–8-beat static or slow shot
- The Wave pattern (see Technique 7) creates mini tension-release cycles within a single chorus
- Bridges / breakdowns: drop to 8–16-beat shots; prefer static/wide shots; allow ambient sound or reverb tail to breathe

**Post-drop rule:**
The drop's first 4 bars should be maximum cut density (1-beat shots); bars 5–8 can relax to 2-beat shots as the loop settles. This mirrors how electronic music producers construct drops with an initial explosive phrase followed by a repeated groove.

### Automatable AI Rule
```
energy_curve = analyze_audio_loudness_and_transient_density(track)
  // Returns energy 0.0–1.0 at each beat position

for each_beat:
  if energy_rising:
    target_shot_duration = max(1_beat, current_duration - 1_beat_per_phrase)
  if energy_at_peak:
    target_shot_duration = 1_beat
  if energy_falling (post-drop):
    insert_hold_shot = True if beat_position == drop_beat + 8
    target_shot_duration = 4_beats
  if energy_low (bridge):
    target_shot_duration = 8_beats
    prefer_static_clips = True
```

---

## TECHNIQUE 9 — The Opening Hook (First 3 Seconds)

### Why It Matters [Sources, various]
- 65% of viewers who watch the first 3 seconds will watch 10+ more seconds (Meta internal data)
- Reels with strong 3-second hooks maintain 23% higher retention throughout the entire video
- Platforms weight the first 15% of a video's retention heavily in algorithmic distribution
- Retention decisions happen in the **first 12 frames** (0.5 seconds at 24fps)
- 3-second hold rate above 70% = strong hook; below 50% = rewrite it

### The Rules for Hook Construction [Sources from topteny.com, brandefy.com, opus.pro]
1. **Motion in the very first frame**: The opening frame must contain movement — camera movement, subject movement, or a hard cut from a previous frame (whip pan, snap zoom). Autoplay-silent scrollers respond to motion before audio.
2. **Never start on a static title card, logo, or black frame**
3. **The first cut comes within 1–2 seconds**: An edit in the first 1–2 seconds signals to the viewer that the video is actively going somewhere
4. **Pattern interrupt**: Open with something visually unexpected — unusual angle, extreme close-up, whip pan, visual mismatch, or a moment mid-action rather than the beginning of an action
5. **Start mid-action, not at the start**: Begin clip selection at the peak of an action (clip.in_point = peak_motion_frame) rather than the wind-up

### For Music-Video/B-Roll Automated Editing
- Hook shot: **select the clip with highest motion_score AND highest visual_interest_score from the pool**
- In-point: set at peak optical flow moment in that clip, not at clip start
- Duration: 1–2 beats (short — create curiosity, do not satisfy it)
- Apply a J-cut if possible: if the music has a strong downbeat within the first bar, let the first clip land ON that downbeat even if it means starting audio slightly before video

### Automatable AI Rule
```
hook_selection:
  candidate = max(pool, key=lambda c: c.motion_score + c.visual_interest_score)
  hook_in_point = argmax(optical_flow_magnitude, candidate.frames[0:90])  // first 3s
  hook_duration = 1_beat or 2_beats
  hook_cut_to_beat_1_bar_1 = True  // first cut lands on beat 1 of bar 1

hook_constraints:
  REJECT: clips with zero motion in first 24 frames
  REJECT: clips showing text, logos, or black leader
  PREFER: clips containing face, fast motion, or unexpected visual
```

---

## TECHNIQUE 10 — When to Hold a Shot Long

### The Principle
Not every shot should be short. Long holds serve specific functions: emotional resonance, landscape revelation, surprise through contrast with surrounding fast edits. A long hold after many short cuts creates maximum impact because contrast defines perception.

### Specific Durations [Sources 11, 12, 14]
- **Emotional beat / candid moment**: 5–8 seconds (emotional processing takes 3–5 s to complete)
- **Landscape / establishing wide shot**: 4–8 seconds
- **Action shot that needs to "land"**: 2–4 beats post-impact
- **Dramatic pause before a drop**: 1–2 bars of near-silence with a slow/static shot
- **Post-drop resolution**: one 4–6 second shot in the second phrase of a drop to release tension

**The 3-second attention rule [Sources 12, 18]:** Most viewers need ~3 seconds to fully absorb a shot. Shots shorter than 1 second are perceived but not processed; shots extending past 5–7 seconds (in an otherwise fast-cut piece) require active engagement or the viewer drifts.

**The pro editors' "8-second rule"** (flocksy.com): In slower drama, 8 seconds is a sweet spot — long enough for resonance, not so long the viewer gets bored.

**Ernie Gilbert's approach [3]:** He describes his natural instinct as "less cutty and more lingering" — meaning even within high-energy music video work, he prefers to hold the shots that carry emotional weight rather than cutting for the sake of the beat.

### When to Hold [Rule Table]

| Situation | Hold duration | Why |
|---|---|---|
| Emotional face / candid | 4–8 s | Viewer needs time to read the emotion |
| Landscape / wide establishing | 4–8 s | Visual information is spatial, not temporal |
| Immediately before a big drop | 2–4 bars (hold the tension) | Contrast maximizes impact of the incoming cut |
| After a burst of 1-beat cuts | 1× 4-beat hold | Tension release; rest for viewer cognition |
| Song outro / wind-down | 8–16+ s | Mirror the musical deceleration |
| Symbolic or graphic match shot | 2–4 s | Viewer needs time to make the conceptual connection |

### Automatable AI Rule
```
long_hold_triggers:
  if section == 'bridge' or section == 'outro':
    force_long_shot = True
    min_duration = 8_beats

  if consecutive_1beat_cuts >= 4:
    insert_long_shot(duration=4_beats)     // mandatory tension release

  if clip.emotional_score > 0.7:           // face detection + candid classifier
    min_duration = max(clip.min_duration, 3.0)  // ensure 3s floor

  if beat_position == drop_start - 8_beats:
    insert_static_buildup_shot(duration=4_to_8_beats)  // pre-drop tension hold
```

---

## TECHNIQUE 11 — Walter Murch's Rule of Six (Priority Hierarchy)

### What It Is [Source 16]
The fundamental theory that determines which principle governs any individual cut decision. Priorities in descending order:

1. **Emotion (51%)** — Does this cut make the viewer feel the right thing?
2. **Story (23%)** — Does this cut advance the narrative/idea?
3. **Rhythm (10%)** — Does this cut feel rhythmically right?
4. **Eye trace (7%)** — Where is the viewer's attention on screen?
5. **2D screen space (5%)** — Does this cut maintain visual coherence?
6. **3D spatial continuity (4%)** — Does this cut respect physical space?

**Implication:** Rhythm (beat-sync) is only the 3rd priority. If a clip that is emotionally perfect lands 2 frames off the beat, use it anyway and trim the adjacent clip to make the math work.

### Automatable AI Rule
```
cut_selection_score(clip, position):
  emotional_score  × 0.51
  + story_score    × 0.23
  + rhythm_score   × 0.10   // how closely does cut align to nearest beat?
  + eye_trace      × 0.07
  + visual_match   × 0.09   // combined 2D/3D

// rhythm_score = 1.0 if cut within 2 frames of beat; 0.5 if within 1 beat; 0.0 otherwise
// emotional_score: from clip metadata (human-labeled) or visual/audio ML classifier
```

---

## TECHNIQUE 12 — Eisenstein's Metric Montage (Algorithmic Beat Cutting)

### What It Is [Source 17]
Metric montage is the most directly automatable of Eisenstein's five montage types. Clips are joined according to their frame-length in a formula corresponding to a musical measure. Tension increases by shortening clips while preserving the formula proportions.

### The Rule
- Establish a base-unit shot length (e.g., 4 beats = 1 bar)
- Repeat that unit-length as a "measure"
- Increase tension by halving the unit: 4-beat → 2-beat → 1-beat
- This is exactly the Linear Rise pattern in Technique 7, given theoretical grounding

**For automated editing:** Metric montage is the default cut-scheduling algorithm for beat-synced content. All other techniques (J/L cuts, holds, anticipation offsets) are modifiers applied on top of this base grid.

---

## TECHNIQUE 13 — Duet Theory (Audio-Visual Alternation)

### What It Is [Source 6 — Paddy, Inside The Edit]
Music and action/dialogue should NOT overlap; they should alternate in a "duet." The strongest musical moments (chorus hits, drops, swells) should land during visual pauses or moments of visual stillness — not beneath fast-cut confusion.

For b-roll montage: assign **specific instrument layers to specific visual elements**:
- Kick drum hit → physical impact / fast motion clip
- Snare → color change, whip-pan, or graphic cut
- Hi-hat pattern → consistent repeating motion
- Synth swell → wide shot, emotional face, or landscape
- Bass drop → maximum cut density / strobe sequence

### Automatable AI Rule
```
for each transient in audio_analysis:
  if transient.type == 'kick':
    schedule_clip_with(motion_type='impact', at=transient.beat_position)
  if transient.type == 'snare':
    schedule_clip_with(motion_type='whip_pan_or_graphic_match', at=transient.beat_position)
  if transient.type == 'synth_swell':
    schedule_clip_with(motion_type='slow_wide_or_face', at=transient.beat_position)
  if transient.type == 'drop':
    schedule_burst(clips=4, each_duration=1_beat, starting_at=transient.beat_position)
```

---

## Summary: Shot Duration Reference Table

| Context | Min duration | Target | Max |
|---|---|---|---|
| TikTok/Reels peak energy | 0.5 s (1 beat @ 120) | 1–2 s | 3 s |
| Music video chorus (120 BPM) | 1 s | 2–3.5 s | 4 s |
| Music video verse | 2 s | 4–5 s | 6 s |
| Music video drop (EDM, 128 BPM) | 0.43 s (1 beat) | 0.87 s (2 beats) | 1.75 s |
| Pre-drop buildup hold | 2 s | 4–6 s | 8 s |
| Bridge / breakdown | 4 s | 6–8 s | 12 s |
| Emotional hold shot | 3 s | 5–7 s | 10 s |
| Opening hook shot | 0.5 s | 1–1.5 s | 2 s |
| Outro / final hold | 4 s | 8–12 s | 20 s |

---

## Implementation Priority for AI Director

**Must-have rules (encode first):**

1. BPM → beat_duration_seconds formula (Technique 1)
2. Energy section → target shot duration mapping (Technique 3)
3. 1-frame anticipation offset (Technique 1)
4. Max 3 consecutive same-duration shots (Technique 7)
5. Opening hook = highest motion-score clip, starts on beat 1 (Technique 9)
6. Pre-drop hold (4–8 beats static) before peak sections (Technique 8)
7. Post-burst long-hold insertion after 4+ consecutive 1-beat cuts (Technique 10)

**Secondary rules (add for quality):**

8. Beat-offset distribution (50% beat-1 / 30% snare / 20% off-beat) (Technique 2)
9. Motion-in-first-frame preference for clip selection (Technique 4)
10. J-cut at section boundaries (Technique 5)
11. Match-cut pairs from optical-flow similarity (Technique 6)
12. Duet theory: map transient types to clip motion types (Technique 13)
13. Murch scoring for final cut selection (Technique 11)

---

*Research conducted 2026-06-13. All source URLs listed in Sources section above.*
