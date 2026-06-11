# MNN Auto-Editor — Design Spec

**Date:** 2026-06-11
**Status:** Draft for review
**Project:** MNN B-Roll Library (`MetroNashvilleNetwork/MNN-B-ROLL-LIBRARY`)
**Companion research:** [`docs/superpowers/research/2026-06-11-editing-craft-and-automation.md`](../research/2026-06-11-editing-craft-and-automation.md)

---

## 1. Goal

Add an **automatic video editor** to the existing B-Roll Library that turns the indexed footage into **finished, social-ready videos** on a recurring (~twice-weekly) schedule — with **no human editing in the loop**. The output must look **well-produced and human-made, not auto-generated/templated.** A human reviews and posts the finished files; the system never publishes on its own.

The existing app indexes b-roll from a SharePoint drive (mapped on Windows) into SQLite and serves a searchable gallery. This feature is a new module *inside* that app, reusing its config, database, scheduler, ffmpeg, and web UI.

---

## 2. Product summary

Each run produces **one themed video** built **only from b-roll** — a music-driven, branded montage with tasteful on-screen text (no voiceover).

- **Story carrier:** music + on-screen text. No spoken narration.
- **Formats produced each run:** vertical **9:16** *and* landscape **16:9**.
- **Subject of each video:** a **theme** drawn from the whole library (e.g. `water`, `courts`, `kitchen`, `nature`, `city`), using the AI tags/descriptions/categories already in the index.
- **Cadence:** twice weekly, scheduled.
- **Master timeline:** **23.98 fps** (24000/1001), cinematic.
- **Delivery:** finished MP4s + preview surfaced in a new **"Productions" tab** for a human to review and post.

---

## 3. Key decisions (locked)

| # | Decision | Choice | Notes |
|---|---|---|---|
| 1 | Edit style | Fully automatic, finished product | No timeline editing by the user |
| 2 | Narration | Music + on-screen text only | No voiceover/TTS |
| 3 | Formats | 9:16 **and** 16:9 each run | Two renders per video |
| 4 | Video subject | Themed, from whole library | Theme auto-selected, overridable |
| 5 | Cadence | Twice weekly (scheduled) | Extends existing scheduler |
| 6 | Master fps | 23.98 (24000/1001) | All clips conform to it |
| 7 | Editor brain | **LLM creative director** | Gemini |
| 8 | Model vision | **Full vision** — model watches footage | Drives clip choice, timing, framing, text |
| 9 | Data handling | Footage **proxies** sent to Gemini/Vertex cloud | See §11 — deliberate trade-off |
| 10 | Run environment | **Windows server** (prod, installed by a non-technical manager) + Mac (dev/build only) | Footage on mapped drive; turnkey install required (§10.1) |
| 11 | Color | Color-managed: convert → match → house look | Uses the user's LUTs |
| 12 | Retime | Director decides per clip; high-fps → smooth slow-mo | True-frame slow-mo |
| 13 | Publishing | Human reviews & posts | No auto-publish |

**Cameras / color profiles in use:** Sony FX6 (**S-Log3**), DJI Osmo Pocket 3 (**D-Log M**).

---

## 4. Architecture & pipeline

Core principle (from the research): **"decisions in the model, pixels in ffmpeg."** The creative director makes *content-aware decisions*; deterministic code executes *frame-exact craft*. We never ask the model for per-frame coordinates or exact timings — that is exactly where auto-editors become jittery and generic.

| Stage | What happens | Tech |
|---|---|---|
| **0 · Scout & prep** *(cached, incremental)* | For new/changed clips: shot detection → usable segments; per-frame **subject positions** + quality numbers (sharpness/exposure/shake) for the renderer; read **source fps + camera/profile**; generate a small low-res **proxy** for the model to watch. | PySceneDetect, OpenCV, mediapipe/YOLO, ffmpeg/ffprobe |
| **1 · Music** | Select a track matching the theme's mood; compute **beat grid + energy curve**. | librosa |
| **2 · Creative Director (Gemini, vision)** | Gemini **watches the proxies** of the theme's candidate clips and composes the edit → emits a structured **EDL** (clip choice, exact in/out, order, roles, retime, reframe intent, text). Per-clip **scouting notes cached** so only new clips are watched next run. | Gemini (Vertex AI) |
| **3 · Refine** *(deterministic)* | Validate EDL; **snap cuts to beats**; compute **smoothed reframe trajectories**; plan color conversion + match + look; gate Ken Burns / stabilization; lay out text in safe zones. | NumPy, OpenCV |
| **4 · Render** | Execute the EDL **twice** (9:16 + 16:9) from **original high-res files**: conform/retime → color chain → reframe → cuts/transitions → text → music (loudness-normalized). | ffmpeg |
| **5 · Deliver** | Write finished MP4s + preview to an output folder and surface in the **Productions tab** for review/posting. | Flask |

**Orchestration:** a twice-weekly scheduled job selects the theme, runs Stages 0–5, and posts the result. The job is idempotent and resumable (cached scouting + analysis mean reruns are cheap).

---

## 5. The EDL — contract between model and renderer

The EDL is the single interface between the creative director and the render engine. It is **validated against a strict JSON schema** before rendering.

### 5.1 Shape (annotated)

```jsonc
{
  "project": {
    "theme": "Nashville Parks & Green Space",
    "fps": "24000/1001",
    "duration_target_s": 28,
    "music": { "track": "uplifting-build-02.wav",
               "why": "warm, builds at 0:12 — matches outdoor optimism" }
  },
  "timeline": [
    {
      "id": 1,
      "role": "hook",                         // hook | establish | detail | closer
      "source": "Gil/July/park-aerial-sunrise.mov",
      "in": 4.20, "out": 6.60,                // best moment the model found
      "retime": { "source_fps": 60, "mode": "slowmo" },     // slowmo | normal
      "reframe": { "intent": "follow jogger entering from right",
                   "subject": "person", "anchor": "thirds_right" },  // INTENT only
      "color": { "profile": "DJI_DLogM" },    // → code applies correct conversion + look
      "text": { "content": "Green space, everywhere you look",
                "style": "title", "in": 0.2, "out": 2.4 },
      "cut_on_beat": true
    }
    // … more clips, varied roles & durations …
  ]
}
```

### 5.2 What the director decides
Clip selection · the **exact best in/out moment** in each clip · order and each clip's **role** · whether to **slow-mo** · **reframe intent** (subject + where to anchor) · which **text** appears and where · which **music** track fits.

### 5.3 What the director does NOT do
Per-frame crop coordinates · exact frame timing · color math. It supplies *intent*; deterministic code does the frame-exact work.

### 5.4 Anti-generic guardrails (encoded in the director's instructions)
Derived from the research's "14 tells → defeats" table:

- **Vary shot lengths** — never metronomic; code beat-snaps each clip to *different* beat multiples.
- **Hook in the first ~1.5 s** — strongest, most arresting shot first; designed for silent autoplay.
- **Shot grammar** — establish → medium → detail; penalize repetition and similar-looking back-to-back shots.
- **Restraint** — hard cuts by default; dissolves only at section seams; slow-mo only when it earns it.
- **Minimal, branded text** — a title, an occasional context line, an outro; never clutter; inside safe zones.

### 5.5 Validation & repair
The EDL is checked against a schema (types, ranges, source files exist, in<out, durations sane, total length near target). A malformed/out-of-bounds EDL is **auto-repaired** where safe (clamp ranges, drop invalid clips) or the director is **re-prompted**; persistent failure falls back to the heuristic planner (§12).

---

## 6. Creative Director (Gemini, full vision)

- **Provider-agnostic seam.** A single `compose_edit(theme, candidates, music) → EDL` call behind an interface, with a **Gemini (Vertex AI)** adapter as the primary. Swappable (Claude, local model, or the heuristic fallback) by config without touching the rest of the pipeline.
- **Inputs:** theme; the candidate clip **proxies** (video the model watches); per-clip metadata (tags, description, shooter, date, duration, source fps, quality scores); the chosen track's structure (length, energy curve, beat timestamps); and brand/text constraints.
- **Output:** the EDL (§5), via the provider's **structured-output / JSON-schema mode**.
- **Scope per run:** only the **theme's candidate pool** is sent (not the whole library), as **proxies** (not originals). Only **new/changed** clips are watched; prior **scouting notes** are cached in SQLite and reused.
- **Cost guardrail:** a per-run cap on number of clips / total proxy minutes sent. Configurable.

> **Verify at build time** (against current Google docs): exact Gemini model ID, video-input limits (max length/size per request, File API vs inline), structured-output mechanics, and pricing. Choose proxy resolution/fps to fit limits and control cost. See §17.

---

## 7. Render & craft engine

### 7.1 Color management (color-managed, per camera)
Project master is **Rec.709 @ 23.98**. Per clip:

1. **Convert** log → Rec.709 with the camera's conversion LUT (`lut3d`, **tetrahedral** interpolation):
   - Sony **S-Log3** → `luts/Neutral Fx6_65x_Legacy.cube` (65³)
   - DJI **D-Log M** → `luts/DJI OSMO Pocket 3 D-Log M to Rec.709 V1.cube` (33³)
   - Already-Rec.709 footage → skip conversion.
2. **Normalize & match** — per-clip auto white-balance (gray-world) + percentile exposure, then histogram-match toward a hero shot so cuts don't jump (`curves`/`colorbalance`).
3. **House look** — apply `luts/NEW WALKMAN.cube` (17³, vintage) to every clip for one cohesive on-brand aesthetic. **Look strength is tunable** (blend with pre-look) and tuned on real footage.

**Profile detection:** a config **per-shooter → camera/profile map** (the archive is organized by shooter) routes each clip to the right conversion; the vision director flags clips that look mis-tagged (flat/log) as a backstop. All three LUTs are bundled into the project `luts/` folder.

### 7.2 Conform & retime → 23.98
- **23.98 / 24** — pass through.
- **60 / 120** — conform to **smooth real slow-mo** using the source's actual frames (`setpts`, no frame-invention); the director chooses *when* slow-mo is used per clip.
- **29.97 / 30** — conform to 23.98 by a **slight slow-conform** (all frames preserved → no judder) by default; motion-compensated rate conversion (`minterpolate`) reserved as a flagged fallback, used sparingly because it can warp.
- All clips are placed on the 23.98 timebase before cutting.

### 7.3 Reframe (9:16)
Per-frame subject detection (mediapipe / YOLO; OpenCV saliency fallback) → centroid → **heavily smoothed trajectory** (Savitzky-Golay / Kalman) → place subject on a thirds line with correct headroom → `crop` + `scale`. Static-vs-tracking decided from motion. Blurred-pillarbox composite used **only** for genuine wide vistas, never as the universal fallback. The 16:9 render keeps native framing. *(Smoothing is the single biggest separator of pro vs. amateur reframing.)*

### 7.4 Beat-sync
`librosa` beat grid + energy curve. The director's per-clip durations snap to **varied** beat multiples; cut density rises and falls with the music's energy (build/breathe). Optional downbeat refinement (madmom) is an upgrade, not a requirement (it is the one fragile Windows dependency).

### 7.5 Motion & polish (restraint by default)
Hard cuts default; `xfade` dissolves only at section seams. **Ken Burns** (`zoompan`, upscale-first) gated onto **low-motion** clips only. **Stabilization** (`vidstab`) gated onto **shaky** clips only. No gratuitous transitions.

### 7.6 Text & branding
Title card + sparse context lines + branded outro, rendered with the brand font/colors in **social safe zones** (avoid top ~14% / bottom ~20%; keep the right action-rail clear). Logo bug optional. *(Requires the brand kit — §14.)*

### 7.7 Render outputs (×2)
9:16 and 16:9, 23.98 fps, MP4 (H.264 baseline; H.265 optional), music **loudness-normalized to ≈ −14 LUFS** (`loudnorm`), burned-in text, plus a thumbnail/preview for the gallery. Clip audio is muted (music-only montage).

---

## 8. Scouting, proxies & caching
- **Proxies:** small, low-bitrate copies of candidate clips, generated once and cached, for the model to watch. Final renders use the originals.
- **Analysis cache:** shot boundaries, quality scores, subject tracks, source fps/profile, and the director's per-clip **scouting notes** are stored in the existing SQLite DB, keyed by file path + mtime/size. Reruns process **only new/changed clips**, so cost scales with new footage, not library size.

---

## 9. Theme selection & scheduling
- **Auto-selection:** pick the category with the most **fresh, high-scoring, not-recently-used** footage; **rotate** so themes don't repeat back-to-back. Uses the existing index categories/tags.
- **Override:** a run can be given an explicit theme.
- **Schedule:** twice-weekly job extending `broll_search/scheduler.py`. Runs unattended; posts results to the Productions tab; logs cost and a per-run report.

---

## 10. Integration & repo layout
New package `broll_search/editor/` (mirrors existing package conventions), reusing `config.py`, `database.py`, `scheduler.py`, and the Flask `web/` app.

```
broll_search/editor/
  __init__.py
  scout.py          # Stage 0: shot detection, quality scoring, subject tracks, proxies
  music.py          # Stage 1: track selection + beat/energy analysis
  director.py       # Stage 2: provider interface + Gemini adapter + EDL schema/validation
  refine.py         # Stage 3: beat-snap, reframe trajectories, color/retime planning
  render.py         # Stage 4: ffmpeg graph builder + dual export
  pipeline.py       # orchestration (Stages 0–5), theme selection, run reports
  heuristic.py      # fallback planner (no-LLM EDL) for resilience
  schema.py         # EDL JSON schema
luts/               # bundled: Sony conv, DJI conv, NEW WALKMAN look
```

**Config additions** (`config.json`): `editor.enabled`, `editor.schedule`, `editor.formats`, `editor.duration_target_s`, `editor.music_dir`, `editor.luts` (paths), `editor.look_strength`, `editor.shooter_camera_map`, `editor.provider` (+ Vertex project/creds), `editor.cost_cap`, `editor.output_dir`, `editor.brand` (logo/font/colors).

**Productions tab** (new view in `web/`): lists finished productions; play 9:16 & 16:9; show theme, clips used, music, run report; **Open file location**, **Copy path**, **Mark as posted**, and **Re-run** (regenerate). No publishing integration.

**Output structure:** `output/<date>-<theme>/{vertical.mp4, landscape.mp4, preview.jpg, edl.json, report.md}`.

### 10.1 Deployment & install (Windows server)
Production runs on a **Windows server installed by a non-technical manager**, so install must be turnkey — mirroring the existing `Setup (first time).bat` pattern:

- **One-step setup script** (`.bat`/PowerShell): creates/uses a Python environment and `pip install -r requirements-editor.txt`; verifies a **full `ffmpeg.exe` build** (with `lut3d`, `zoompan`, `xfade`, `minterpolate`, `vidstab*`, `loudnorm`, `drawtext`) in `tools/` or on PATH; copies the three LUTs into `luts/`; writes an editor config from a template with a clearly-marked **Gemini/Vertex key** slot.
- **Scheduling:** register the twice-weekly run via the app's scheduler and/or a **Windows Scheduled Task** the setup script creates.
- **Heavy deps on Windows:** `librosa`, `opencv-python`, `PySceneDetect` install cleanly; `mediapipe` (reframe phase) is the one to verify on the target Windows/Python version — pin known-good versions with an OpenCV-saliency fallback.
- **Hand-off doc:** a short, non-technical install/run/troubleshoot guide for the manager.
- **Cross-platform code:** all modules are OS-agnostic Python, following the existing `os.name == "nt"` console-hiding and bundled-tool-resolution patterns in `web/media.py` and `indexer.py`.

---

## 11. Data handling, privacy & offline messaging
This feature **intentionally relaxes** the app's "100% offline / nothing leaves MNN" guarantee: **proxy footage and clip metadata are sent to Gemini/Vertex (Google cloud)** to drive the edit. Originals never leave (renders are local), but proxies are recognizable footage.

- **Recommendation:** run via **Vertex AI enterprise** (no training on customer data; region/data-residency controls) and obtain the appropriate internal data-policy sign-off before production use.
- **Scoping:** only the theme's candidate proxies are sent; nothing is sent for clips already scouted.
- **Docs update required:** README and UI copy must clearly state that **library *search* remains fully offline**, while the **Auto-Editor is an online feature**. This must not be misleading to staff or stakeholders.
- **Kill switch:** `editor.provider: "heuristic"` runs the whole pipeline fully offline (lower creative ceiling) with zero external calls.

---

## 12. Error handling & failure modes
- **Bad/malformed EDL** → schema validation → auto-repair where safe → re-prompt → **heuristic fallback**. A run never silently produces garbage.
- **Gemini failure / timeout / quota** → retry with backoff → heuristic fallback; surfaced in the run report.
- **Cost cap exceeded** → stop sending to the model, finish with what's scouted or fall back; report it (never silently truncate).
- **Missing asset** (LUT, music, brand kit) → clear, actionable error; degrade where sensible (e.g., skip look if look-LUT missing).
- **ffmpeg error on a clip** → drop the clip, log it, continue; fail the run only if too few clips remain.
- **Footage drive unreachable** → abort early with notification (reuses existing drive validator).
- **No ffmpeg / no libvidstab** → degrade gracefully (skip stabilization; warn).

---

## 13. Testing & QC
- **Dev environment & acceptance:** built and tested on Mac with **stand-in media** (synthetic ffmpeg test clips + the user's sample clips). The production **Windows server is set up later by the manager**, so the design targets a **clean hand-off**: most logic is tested by asserting the *constructed ffmpeg commands/filtergraphs* (no execution needed, fully cross-platform); a few integration tests actually run ffmpeg on synthetic media and **skip gracefully if ffmpeg is absent**. **Real footage and final-look acceptance happen on the server** after install.
- **Unit:** EDL schema (golden valid/invalid cases); color-chain (LUT applies, S-Log3/D-Log M sample → expected 709 range); conform/retime math (60→23.98 = expected slow factor; 30→23.98 no dropped frames); reframe-trajectory smoothness (jitter below threshold); beat-snap correctness.
- **Integration / smoke:** a 3–5 clip edit produces valid **9:16 + 16:9 @ 23.98** MP4s that play, with audio at target loudness and text in safe zones.
- **QC gate:** an automated/semi-automated checklist built from the research's **"14 generic tells"** (metronome cuts, center-crop, color jumps, cheesy transitions, etc.) — a production must pass before it lands in the Productions tab as "ready."
- **Director eval:** a small set of fixed (theme, clips, music) inputs with sanity assertions on the EDL (varied durations, hook present, no immediate repeats) to catch regressions in prompt/model behavior.

---

## 14. Assets & prerequisites
- ✅ Sony S-Log3 conversion LUT — `Neutral Fx6_65x_Legacy.cube` (received)
- ✅ House look LUT — `NEW WALKMAN.cube` (received)
- ✅ DJI D-Log M conversion LUT — `DJI OSMO Pocket 3 D-Log M to Rec.709 V1.cube` (received)
- ⏳ **Sample clips** (5–15 real, mix of cameras/fps/log) for Mac dev
- ⏳ **Music library** the user has rights to (folder of tracks)
- ⏳ **Brand kit** — logo (PNG/SVG), brand font(s), color(s), any intro/outro
- ⏳ **Gemini / Vertex AI** access — project + credentials, and data-policy sign-off
- ⏳ **Shooter → camera/profile map** (e.g. which shooters use FX6 vs Osmo Pocket 3)

---

## 15. Build order (impact-first, from research)
1. **Foundation:** scout/proxy + EDL schema + render skeleton; **beat-synced varied cutting** + correct **dual export (9:16 + 16:9 @ 23.98)** + hard-cut discipline. *(Immediately beats template tools.)*
2. **Selection quality:** quality scoring (sharpness/exposure/shake), best-moment windowing, variety/de-dup.
3. **Color chain:** per-camera conversion + match + house look (the user's LUTs).
4. **Conform/retime:** slow-mo + 30→23.98 handling.
5. **Flagship reframe:** subject-aware 9:16 with smoothed trajectories.
6. **Creative director:** Gemini full-vision integration + scouting cache + cost caps (heuristic planner built first as both fallback and scaffold).
7. **Polish:** text/branding, Ken Burns, stabilization, Productions tab + scheduling.

*(Each phase ships something runnable; the director can sit on top of the heuristic planner once the render engine is solid.)*

---

## 16. Out of scope (v1) / future seams
- **Spoken-word captions / subtitles** (faster-whisper) — not needed for a music montage; seam left if a future format wants transcribed speech.
- **Auto-publishing** to social accounts — explicitly excluded; humans post.
- **Interactive timeline editing** — this is a finished-product generator, not an NLE.
- **Alternate model providers** — interface exists; only Gemini built in v1.

---

## 17. Open items to verify at build time
- Gemini: exact model ID, video-input limits, File API mechanics, structured-output mode, pricing → choose proxy spec + cost cap accordingly.
- Confirm the bundled/Windows `ffmpeg.exe` is compiled with `--enable-libvidstab` (and `lut3d`, `zoompan`, `xfade`, `minterpolate`, `loudnorm`, `drawtext`/`subtitles`).
- Confirm mediapipe / chosen detector installs and runs acceptably on the Windows production machine (CPU vs GPU).
- Validate `NEW WALKMAN` look strength on real graded footage (it may need dialing back).
- Decide H.264 vs H.265 and target bitrates per platform.
- Windows server specifics (at packaging time): Windows Server version; whether the manager can install Python or we ship a bundled/portable runtime; admin rights for Scheduled Tasks; and **GPU availability** (affects reframe/CV speed — CPU is fine for a twice-weekly batch, just slower).

---

## 18. References
- Editing-craft & automation research: [`docs/superpowers/research/2026-06-11-editing-craft-and-automation.md`](../research/2026-06-11-editing-craft-and-automation.md)
- Existing app: `README.md`, `CLIPPER_AI_METADATA.md`, `broll_search/`
