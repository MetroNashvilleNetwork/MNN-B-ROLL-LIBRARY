# MNN Auto-Editor — Session Handoff (2026-06-15)

A complete continuation doc for the automatic social-video editor built on this repo.
Branch: **`auto-editor-phase1`** (NOT pushed/merged). 215 tests green.

---

## What it is
An automatic editor that turns indexed b-roll into finished social recap videos.
A **Gemini director** watches low-res proxies, chooses clips/moments/order; a deterministic
post-pass + ffmpeg pipeline handle color, slow-mo, stabilization, beat-sync, and render.
Runs ~2×/week. Production target: a **Windows server** (non-technical manager installs it);
dev is on Gibby's Mac.

## CURRENT STATE — what's working (and approved by Gibby)
The landscape cut is essentially the finished product. Gibby has approved, in order, each of:
- **Quarter-speed slow-mo** (4× / 25%), motion-interpolated past the 2.5× optical limit — "i love it"
- **Smooth** via real **vidstab** stabilization (not the weak Mac `deshake`)
- **Best moment per clip** (tight selections on each clip's peak)
- **Brighter** (exposure target midtone 125) + **+20% saturation**
- **Cold open** (no title card) → **clean fade-out** (no app-icon, no black tail)
- **Cut to the beat** — every cut lands within ~10ms (¼ frame) of a song beat
- **Chronological story-arc sequencing**, **balanced mix** (people/scale/detail), **punchier** holds
- **Landscape (16:9) only** for now — vertical deferred

### THE COMMAND (reproduces the current best landscape cut)
```bash
cd ~/MNN-B-ROLL-LIBRARY
GEMINI_API_KEY=$(cat .gemini_key) .venv-editor/bin/python -m broll_search.editor \
  --director --preview --slowmo-all --slowmo-factor 4.0 --no-brand --format landscape \
  --clips dev_media/batch24 --music dev_media/music --profile sony_slog3 \
  --out output/mnn_seq --theme "Nashville City Life" --duration 24 --outro fade \
  --ffmpeg "$(pwd)/tools/ffmpeg" --ffprobe "$(pwd)/tools/ffprobe"
```
- Latest output: **`output/mnn_seq/landscape.mp4`** (24.0s, 13 shots, beat-synced) — **Gibby has NOT watched this one yet** (it has the new chronological order + punchier holds).
- Render time: ~12-15 min landscape-only (4× motion-interpolation + 2-pass vidstab are the cost). Both formats ≈ 25-30 min.

## CRITICAL environment facts
- **vidstab ffmpeg lives in `tools/ffmpeg` + `tools/ffprobe`** (static evermeet.cx build, gitignored). The Mac's brew ffmpeg has NO vidstab (only `deshake`) — ALWAYS pass `--ffmpeg ./tools/ffmpeg --ffprobe ./tools/ffprobe` for Mac previews so they match the Windows finals. The Windows server needs a vidstab+minterpolate ffmpeg too.
- **Gemini**: model `gemini-flash-latest` (`gemini-2.0-flash-001` is retired/404). Key in gitignored `.gemini_key` — **Gibby pasted it in chat once; it SHOULD be rotated**; use Vertex AI for prod.
- **Clip library**: `dev_media/clips` = **128 clips**. `build_edl_director` scouts ALL passed paths then keeps top `max_candidates=40`, so point `--clips` at a SUBSET dir. Test batches are symlinks in `dev_media/batchN` (currently using `dev_media/batch24`).
- **Scout cache** (`cache/editor_scout.json`) keys by PATH → a different dir = full re-scout (slow: optical-flow motion analysis). Any ClipScout schema change requires clearing it.
- Dev venv: `.venv-editor`. Tests: `.venv-editor/bin/python -m pytest tests/editor -q`.

## The dials (all CLI flags on `python -m broll_search.editor`)
- `--slowmo-factor` 0=optical 2.5× (frame-exact); **4.0** = quarter-speed (approved), interpolated past 2.5×. (40% speed = 2.5×; 33% = 3×; 25% = 4×.)
- `--slowmo-all` — every clip slow-mo (the approved mode).
- `--outro {card,fade,none}` — **fade** (approved); `--no-brand` drops the opening title card (cold open, approved).
- `--format {both,landscape,vertical}` — **landscape** for now.
- `--no-beat-sync` to disable beat snapping; `--slowmo-ceiling` (0.85), `--look-strength` (0.4), `--preview` (2160 prescale dev / omit → 4320 final), `--no-stabilize`, `--no-exposure`.

## How the key pieces work (where to edit)
- `broll_search/editor/director.py` — `build_director_prompt` (creative brief: sequencing/best-moment/slow-mo/balanced), `parse_director_edl` + `apply_cinematic_defaults` (deterministic post-pass: motion windowing, push-ins, exposure via **midtone** not mean, slow-mo forcing). Candidates are sorted **chronologically** (by C#### filename) before the director sees them.
- `broll_search/editor/timing.py` — `snap_clips_to_beats` (resizes each clip so cuts land on real librosa beats; on-screen hold = beats×interval, source span = hold/factor; `target_total` length ceiling; pattern `(base,base,base+1,base)` = punchier).
- `broll_search/editor/filters.py` — `retime_filter` (setpts + minterpolate when factor>optical), `clip_video_chain` (LUT→exposure→look→saturation→reframe/push→retime→format), `exposure_filter`.
- `broll_search/editor/render.py` — per-clip render (vidstab 2-pass: `vidstabdetect` + `vidstabtransform` smoothing 55/65), concat, music loudnorm + **fade-out probes true video length** (`_probe_duration`).
- `broll_search/editor/pipeline.py` — `build_edl_director` / `run_pipeline` (threads all params; renders per `--format`).

## OPEN ITEMS / NEXT STEPS
1. **Gibby to review `output/mnn_seq/landscape.mp4`** — verify the new chronological placement "makes sense" and whether 13 shots is punchy enough (can push to ~2-beat holds / ~15-16 shots → "more punch").
2. **"New guides" Gibby mentioned (2026-06-15):** he said he added guides for me to check; I could NOT find them (searched repo, Desktop/Downloads/Documents/dev_media/Movies, and Google Drive recent + by-name). **Need the path / Drive link / pasted content.** Likely the next creative input — get these first.
3. **Vertical (9:16):** deferred. Re-enable with `--format both` once landscape is locked.
4. **Title/branding:** currently dropped (cold open). Option to add a beat-aligned text title later (Gibby said "no text" for now). The `brand/mnn-logo.png` is the blue Clip-Namer app icon — off-palette for broadcast; don't reuse it as-is.
5. **Operational:** run on the full library (curate subset dirs), and the Windows-server install (re-render finals at 4320 prescale + vidstab; needs a vidstab ffmpeg on the box).
6. Possible polish: per-clip white-balance match; the `--slowmo-all` STRUCTURE arc still has some legacy second-counts (harmless — beat-snap overrides timing).

## Known-good verification commands
- Beat alignment (from saved EDL): cumulative `(out-in)*factor` vs `analyze_music(...).beats` — current cut is 13/13 within 10ms.
- Black-tail check: sample frame luma at 16/19/22s — should be bright (footage runs to ~target-0.8s, then 0.8s fade).

See also memory: `~/.claude/projects/-Users-gilbranlaureano/memory/project-mnn-auto-editor.md`.
