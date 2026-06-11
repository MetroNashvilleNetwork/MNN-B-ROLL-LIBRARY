# MNN Auto-Editor — Phase 1 (Offline Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From a folder of clips + a music track, automatically produce a beat-cut, color-graded, 23.98 fps montage exported in **vertical 9:16 and landscape 16:9** — fully offline, no Gemini yet.

**Architecture:** A thin vertical slice of the pipeline from the spec (`docs/superpowers/specs/2026-06-11-mnn-auto-editor-design.md`): `probe → music analysis → heuristic planner → EDL → ffmpeg render`. "Decisions" live in pure-Python functions (testable anywhere by asserting the constructed ffmpeg commands); "pixels" are produced by ffmpeg. Each clip is rendered to a normalized intermediate, intermediates are concatenated, then music is mixed in with loudness normalization.

**Tech Stack:** Python 3.9 (cross-platform, Windows-targeted), `librosa` (beat detection), `numpy`, `ffmpeg`/`ffprobe` (render), `pytest`. New package `broll_search/editor/`. The three user LUTs are bundled into `luts/`.

**Scope (Phase 1):** beat-synced **varied** cutting · per-camera color chain (S-Log3 / D-Log M conversion → house look) · conform to 23.98 · center-crop reframe · dual export · CLI. **Deferred to later phases:** quality scoring & best-moment selection, slow-mo retime, smart subject-aware reframe, on-screen text/branding, the Gemini director, web "Productions" tab, scheduling, Windows installer.

**Conventions:** follow existing patterns in `broll_search/web/media.py` (subprocess + `os.name == "nt"` console hiding + bundled-tool resolution) and `broll_search/config.py` (dataclasses). LUTs are referenced by **relative, space-free, forward-slash paths** to dodge ffmpeg filtergraph escaping on Windows.

---

## File structure

| File | Responsibility |
|---|---|
| `broll_search/editor/__init__.py` | Package marker |
| `broll_search/editor/edl.py` | `Clip`/`EDL` dataclasses + `validate_edl` |
| `broll_search/editor/probe.py` | `probe_clip` (fps/duration/dims) + `_parse_fps` |
| `broll_search/editor/music.py` | `analyze_signal`/`analyze_music` (beats, tempo, duration) |
| `broll_search/editor/timing.py` | `beat_segment_endpoints` (varied, beat-snapped cut points) |
| `broll_search/editor/profiles.py` | `profile_for` (path → color profile) |
| `broll_search/editor/filters.py` | ffmpeg filtergraph builders (color, reframe, conform, full chain) |
| `broll_search/editor/planner.py` | `plan` (clips + music → EDL) |
| `broll_search/editor/render.py` | `render_format` (EDL → one MP4 via ffmpeg) |
| `broll_search/editor/pipeline.py` | `run_pipeline` (orchestration) |
| `broll_search/editor/__main__.py` | CLI: `python -m broll_search.editor` |
| `tests/editor/test_*.py` | one test module per source module |
| `luts/` | bundled LUTs (safe ASCII names) |
| `requirements-editor.txt` | Phase 1 deps |

---

### Task 0: Dev environment & package skeleton

**Files:**
- Create: `requirements-editor.txt`
- Create: `broll_search/editor/__init__.py`
- Create: `tests/editor/__init__.py`
- Create: `pytest.ini`
- Create: `luts/sony_slog3.cube`, `luts/dji_dlogm.cube`, `luts/look_walkman.cube` (copied)
- Modify: `.gitignore`

- [ ] **Step 1: Create the editor dependency file**

`requirements-editor.txt`:
```
# MNN Auto-Editor — Phase 1 dependencies (in addition to the app's requirements.txt)
numpy>=1.21,<2
librosa>=0.10,<1
soundfile>=0.12        # write synthetic test audio
pytest>=7
```

- [ ] **Step 2: Create the package + test package markers**

`broll_search/editor/__init__.py`:
```python
"""MNN Auto-Editor — automatic b-roll → social video generation.

Phase 1 (offline foundation): probe → music analysis → heuristic planner → EDL
→ ffmpeg render (vertical 9:16 + landscape 16:9). No cloud/LLM yet.
"""
```

`tests/editor/__init__.py`:
```python
```

- [ ] **Step 3: Add pytest config**

`pytest.ini`:
```ini
[pytest]
testpaths = tests
python_files = test_*.py
addopts = -ra
```

- [ ] **Step 4: Bundle the LUTs under safe names**

Copy the user's three validated LUTs into `luts/` with space-free names (filtergraph-safe):
```bash
cd ~/MNN-B-ROLL-LIBRARY && mkdir -p luts
cp "/Users/gilbranlaureano/Library/Application Support/ProApps/Custom LUTs/Fx6 Phntm ARRI LUTs-G6/65x/Neutral Fx6_65x_Legacy.cube" luts/sony_slog3.cube
cp "/Users/gilbranlaureano/Library/Application Support/ProApps/Custom LUTs/DJI OSMO Pocket 3 D-Log M to Rec.709 V1.cube" luts/dji_dlogm.cube
cp "/Users/gilbranlaureano/Library/Application Support/ProApps/Custom LUTs/Vintage lut/NEW WALKMAN.cube" luts/look_walkman.cube
ls -la luts/
```
Expected: three `.cube` files listed.

- [ ] **Step 5: Update .gitignore**

Append to `.gitignore`:
```
# Auto-Editor
dev_media/
output/
.venv-editor/
```

- [ ] **Step 6: Create a virtualenv and install deps**

Run:
```bash
cd ~/MNN-B-ROLL-LIBRARY
python3 -m venv .venv-editor
.venv-editor/bin/python -m pip install --upgrade pip
.venv-editor/bin/python -m pip install -r requirements-editor.txt
```
Expected: installs succeed (librosa pulls numpy/scipy/numba/soundfile). All subsequent `python`/`pytest` commands use `.venv-editor/bin/python -m ...`.

- [ ] **Step 7: Fix local ffmpeg (dev render tests only)**

The Homebrew ffmpeg is currently broken (missing `libx265.215.dylib`). Repair it so local render/integration tests can run (irrelevant to the Windows server):
```bash
brew reinstall ffmpeg
ffmpeg -hide_banner -filters | grep -wE 'lut3d|crop|scale|fps|loudnorm' | awk '{print $2}'
```
Expected: `crop fps loudnorm lut3d scale` all present.

- [ ] **Step 8: Commit**

```bash
git add requirements-editor.txt broll_search/editor/__init__.py tests/editor/__init__.py pytest.ini luts/ .gitignore
git commit -m "chore(editor): scaffold Phase 1 package, deps, bundled LUTs"
```

---

### Task 1: EDL data model + validation

**Files:**
- Create: `broll_search/editor/edl.py`
- Test: `tests/editor/test_edl.py`

- [ ] **Step 1: Write the failing test**

`tests/editor/test_edl.py`:
```python
from broll_search.editor.edl import Clip, EDL, validate_edl


def _clip(**kw):
    base = dict(id=1, source="a.mov", in_point=0.0, out_point=2.0,
                color_profile="rec709", role="hook")
    base.update(kw)
    return Clip(**base)


def test_clip_duration():
    assert _clip(in_point=1.0, out_point=3.5).duration == 2.5


def test_valid_edl_has_no_errors():
    edl = EDL(theme="parks", music="m.wav", clips=[_clip()])
    assert validate_edl(edl) == []


def test_empty_edl_is_invalid():
    edl = EDL(theme="parks", music="m.wav", clips=[])
    assert any("no clips" in e for e in validate_edl(edl))


def test_bad_inout_is_invalid():
    edl = EDL(theme="parks", music="m.wav", clips=[_clip(in_point=2.0, out_point=1.0)])
    assert any("out_point" in e for e in validate_edl(edl))


def test_unknown_profile_is_invalid():
    edl = EDL(theme="parks", music="m.wav", clips=[_clip(color_profile="bogus")])
    assert any("color_profile" in e for e in validate_edl(edl))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-editor/bin/python -m pytest tests/editor/test_edl.py -v`
Expected: FAIL (`ModuleNotFoundError: broll_search.editor.edl`).

- [ ] **Step 3: Write minimal implementation**

`broll_search/editor/edl.py`:
```python
"""Edit Decision List — the contract between the planner/director and renderer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

KNOWN_PROFILES = {"sony_slog3", "dji_dlogm", "rec709"}


@dataclass
class Clip:
    id: int
    source: str          # path to the source video file
    in_point: float      # seconds from clip start
    out_point: float     # seconds from clip start (> in_point)
    color_profile: str   # one of KNOWN_PROFILES
    role: str = "body"   # hook | body | closer (informational in Phase 1)

    @property
    def duration(self) -> float:
        return round(self.out_point - self.in_point, 3)


@dataclass
class EDL:
    theme: str
    music: str           # path to the chosen music track
    clips: List[Clip] = field(default_factory=list)
    fps: str = "24000/1001"
    duration_target_s: float = 28.0


def validate_edl(edl: EDL) -> List[str]:
    """Return a list of human-readable problems; empty means valid."""
    errors: List[str] = []
    if not edl.clips:
        errors.append("EDL has no clips")
    for c in edl.clips:
        if c.in_point < 0:
            errors.append(f"clip {c.id}: in_point must be >= 0")
        if c.out_point <= c.in_point:
            errors.append(
                f"clip {c.id}: out_point ({c.out_point}) must be > in_point ({c.in_point})")
        if c.color_profile not in KNOWN_PROFILES:
            errors.append(f"clip {c.id}: unknown color_profile '{c.color_profile}'")
    return errors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv-editor/bin/python -m pytest tests/editor/test_edl.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add broll_search/editor/edl.py tests/editor/test_edl.py
git commit -m "feat(editor): EDL data model and validation"
```

---

### Task 2: Clip probing (fps/duration/dimensions)

**Files:**
- Create: `broll_search/editor/probe.py`
- Test: `tests/editor/test_probe.py`

- [ ] **Step 1: Write the failing test**

`tests/editor/test_probe.py`:
```python
import json
from broll_search.editor import probe
from broll_search.editor.probe import _parse_fps, ClipInfo


def test_parse_fps_fraction():
    assert round(_parse_fps("60000/1001"), 2) == 59.94


def test_parse_fps_integer():
    assert _parse_fps("30") == 30.0


def test_parse_fps_zero_denominator_is_zero():
    assert _parse_fps("30/0") == 0.0


def test_probe_clip_parses_ffprobe_json(monkeypatch):
    fake = json.dumps({
        "format": {"duration": "12.5"},
        "streams": [{"codec_type": "video", "width": 3840, "height": 2160,
                     "r_frame_rate": "60000/1001"}],
    })

    class _Proc:
        returncode = 0
        stdout = fake

    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **k: _Proc())
    info = probe.probe_clip("anything.mov", ffprobe_path="ffprobe")
    assert info == ClipInfo(path="anything.mov", duration=12.5,
                            width=3840, height=2160, fps=round(60000 / 1001, 6))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-editor/bin/python -m pytest tests/editor/test_probe.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write minimal implementation**

`broll_search/editor/probe.py`:
```python
"""Probe a clip's fps, duration, and dimensions via ffprobe.

Mirrors the subprocess/Windows-console handling used in broll_search/indexer.py.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class ClipInfo:
    path: str
    duration: float
    width: int
    height: int
    fps: float


def _parse_fps(rate: Optional[str]) -> float:
    """'60000/1001' -> 59.94 ; '30' -> 30.0 ; bad/zero -> 0.0"""
    if not rate:
        return 0.0
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            den_f = float(den)
            return round(float(num) / den_f, 6) if den_f else 0.0
        except ValueError:
            return 0.0
    try:
        return float(rate)
    except ValueError:
        return 0.0


def _run_kwargs() -> dict:
    kwargs: dict = {"capture_output": True, "text": True, "timeout": 30}
    if os.name == "nt":  # don't flash a console window on Windows
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = si
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return kwargs


def probe_clip(path: str, ffprobe_path: str = "ffprobe") -> ClipInfo:
    """Return a ClipInfo. Missing fields default to 0; never raises on probe failure."""
    cmd = [ffprobe_path, "-v", "quiet", "-print_format", "json",
           "-show_format", "-show_streams", path]
    try:
        proc = subprocess.run(cmd, **_run_kwargs())
        data = json.loads(proc.stdout) if proc.returncode == 0 and proc.stdout else {}
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        data = {}

    duration = 0.0
    try:
        duration = float(data.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        pass

    width = height = 0
    fps = 0.0
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
            fps = _parse_fps(stream.get("r_frame_rate"))
            break

    return ClipInfo(path=path, duration=duration, width=width, height=height, fps=fps)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv-editor/bin/python -m pytest tests/editor/test_probe.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add broll_search/editor/probe.py tests/editor/test_probe.py
git commit -m "feat(editor): ffprobe-based clip probing"
```

---

### Task 3: Music analysis (beats, tempo, duration)

**Files:**
- Create: `broll_search/editor/music.py`
- Test: `tests/editor/test_music.py`

- [ ] **Step 1: Write the failing test**

`tests/editor/test_music.py`:
```python
import numpy as np
from broll_search.editor.music import analyze_signal


def _click_track(bpm=120, sr=22050, seconds=8):
    """Synthesize clicks at a fixed BPM so beat tracking has a known answer."""
    y = np.zeros(int(sr * seconds), dtype=np.float32)
    interval = int(sr * 60.0 / bpm)
    for i in range(0, len(y), interval):
        y[i:i + 200] = 1.0  # short impulse
    return y, sr


def test_analyze_signal_detects_tempo_and_beats():
    y, sr = _click_track(bpm=120)
    tempo, beats = analyze_signal(y, sr)
    assert 110 <= tempo <= 130          # near 120 BPM
    assert len(beats) >= 8              # ~ one per beat over 8s
    assert all(b2 > b1 for b1, b2 in zip(beats, beats[1:]))  # increasing
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-editor/bin/python -m pytest tests/editor/test_music.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write minimal implementation**

`broll_search/editor/music.py`:
```python
"""Music analysis: beat grid, tempo, and duration via librosa."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

import librosa


@dataclass
class MusicInfo:
    path: str
    duration: float
    tempo: float
    beats: List[float] = field(default_factory=list)  # beat times in seconds


def analyze_signal(y, sr) -> Tuple[float, List[float]]:
    """Return (tempo_bpm, beat_times_seconds) for an audio signal array."""
    tempo, beat_times = librosa.beat.beat_track(y=y, sr=sr, units="time")
    return float(tempo), [float(b) for b in beat_times]


def analyze_music(path: str) -> MusicInfo:
    """Load an audio file and return its tempo, beat grid, and duration."""
    y, sr = librosa.load(path, sr=None, mono=True)
    duration = float(librosa.get_duration(y=y, sr=sr))
    tempo, beats = analyze_signal(y, sr)
    return MusicInfo(path=path, duration=duration, tempo=tempo, beats=beats)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv-editor/bin/python -m pytest tests/editor/test_music.py -v`
Expected: PASS (1 passed). (First run is slow — librosa/numba JIT warm-up.)

- [ ] **Step 5: Commit**

```bash
git add broll_search/editor/music.py tests/editor/test_music.py
git commit -m "feat(editor): librosa music/beat analysis"
```

---

### Task 4: Beat-snapped, varied cut points

**Files:**
- Create: `broll_search/editor/timing.py`
- Test: `tests/editor/test_timing.py`

- [ ] **Step 1: Write the failing test**

`tests/editor/test_timing.py`:
```python
from broll_search.editor.timing import beat_segment_endpoints


def test_segments_land_on_beats_with_varied_lengths():
    beats = [i * 0.5 for i in range(33)]  # 0.0 .. 16.0, every 0.5s (120 BPM)
    segs = beat_segment_endpoints(beats, target_total=8.0, pattern=(4, 2, 3))
    # each (start, end) must be exact beat times
    beatset = set(round(b, 6) for b in beats)
    for start, end in segs:
        assert round(start, 6) in beatset
        assert round(end, 6) in beatset
        assert end > start
    # lengths follow the varied pattern (4,2,3 beats * 0.5s = 2.0,1.0,1.5 ...)
    lengths = [round(end - start, 3) for start, end in segs]
    assert lengths[:3] == [2.0, 1.0, 1.5]
    # total is close to the target (within one pattern step)
    assert abs(sum(lengths) - 8.0) <= 2.0


def test_handles_too_few_beats():
    assert beat_segment_endpoints([0.0], target_total=8.0, pattern=(4,)) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-editor/bin/python -m pytest tests/editor/test_timing.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write minimal implementation**

`broll_search/editor/timing.py`:
```python
"""Turn a beat grid into a sequence of varied, beat-aligned (start, end) cut points.

Varying the number of beats per segment is the single biggest defense against the
'metronome cut' that makes auto-edits look generic (see the research doc)."""

from __future__ import annotations

from typing import List, Sequence, Tuple


def beat_segment_endpoints(
    beats: Sequence[float],
    target_total: float,
    pattern: Sequence[int] = (4, 2, 3, 2, 4, 3),
) -> List[Tuple[float, float]]:
    """Walk the beat grid, consuming `pattern[i]` beats per segment, until the
    summed segment length reaches `target_total` or the beats run out.

    Returns a list of (start_time, end_time), both exact beat timestamps.
    """
    if len(beats) < 2:
        return []
    segments: List[Tuple[float, float]] = []
    idx = 0
    pat_i = 0
    total = 0.0
    last = len(beats) - 1
    while idx < last and total < target_total:
        n = max(1, pattern[pat_i % len(pattern)])
        end_idx = min(idx + n, last)
        start, end = float(beats[idx]), float(beats[end_idx])
        if end <= start:
            break
        segments.append((start, end))
        total += end - start
        idx = end_idx
        pat_i += 1
    return segments
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv-editor/bin/python -m pytest tests/editor/test_timing.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add broll_search/editor/timing.py tests/editor/test_timing.py
git commit -m "feat(editor): varied beat-aligned cut points"
```

---

### Task 5: Color-profile detection

**Files:**
- Create: `broll_search/editor/profiles.py`
- Test: `tests/editor/test_profiles.py`

- [ ] **Step 1: Write the failing test**

`tests/editor/test_profiles.py`:
```python
from broll_search.editor.profiles import profile_for


def test_sony_filename_maps_to_slog3():
    assert profile_for("/x/FX6_Aaron_clip01.mov", default="rec709") == "sony_slog3"


def test_dji_filename_maps_to_dlogm():
    assert profile_for("/x/DJI_Osmo_Pocket3_walk.mp4", default="rec709") == "dji_dlogm"


def test_unknown_uses_default():
    assert profile_for("/x/random_clip.mov", default="sony_slog3") == "sony_slog3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-editor/bin/python -m pytest tests/editor/test_profiles.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write minimal implementation**

`broll_search/editor/profiles.py`:
```python
"""Guess a clip's camera color profile from its path/filename.

Phase 1 heuristic only; later phases add a config per-shooter map and a
vision backstop (see spec §7.1)."""

from __future__ import annotations

import os

_SONY_HINTS = ("fx6", "fx3", "fx9", "sony", "slog", "s-log")
_DJI_HINTS = ("dji", "osmo", "pocket", "dlog", "d-log", "mavic", "mini")


def profile_for(path: str, default: str = "rec709") -> str:
    name = os.path.basename(path).lower()
    if any(h in name for h in _SONY_HINTS):
        return "sony_slog3"
    if any(h in name for h in _DJI_HINTS):
        return "dji_dlogm"
    return default
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv-editor/bin/python -m pytest tests/editor/test_profiles.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add broll_search/editor/profiles.py tests/editor/test_profiles.py
git commit -m "feat(editor): filename-based color profile detection"
```

---

### Task 6: ffmpeg filtergraph builders (color, reframe, conform)

**Files:**
- Create: `broll_search/editor/filters.py`
- Test: `tests/editor/test_filters.py`

- [ ] **Step 1: Write the failing test**

`tests/editor/test_filters.py`:
```python
from broll_search.editor.filters import (
    color_filter, reframe_filter, conform_filter, clip_video_chain,
    LUT_FILES, LOOK_LUT,
)


def test_color_filter_sony_converts_then_looks():
    f = color_filter("sony_slog3", lut_dir="luts", look_strength=1.0)
    # conversion LUT first, then the look LUT, both tetrahedral
    assert f.index("luts/sony_slog3.cube") < f.index("luts/look_walkman.cube")
    assert "interp=tetrahedral" in f


def test_color_filter_rec709_skips_conversion():
    f = color_filter("rec709", lut_dir="luts", look_strength=1.0)
    assert "sony_slog3.cube" not in f and "dji_dlogm.cube" not in f
    assert "look_walkman.cube" in f  # look still applied


def test_reframe_vertical_dims():
    assert reframe_filter(1080, 1920) == (
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920")


def test_conform_filter_uses_fps():
    assert conform_filter("24000/1001") == "fps=24000/1001"


def test_clip_video_chain_order_and_format():
    chain = clip_video_chain("dji_dlogm", "luts", 1080, 1920, "24000/1001", 1.0)
    # color -> reframe -> conform -> 8-bit 4:2:0 at the end
    assert chain.index("dji_dlogm.cube") < chain.index("crop=1080:1920")
    assert chain.index("crop=1080:1920") < chain.index("fps=24000/1001")
    assert chain.endswith("format=yuv420p")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-editor/bin/python -m pytest tests/editor/test_filters.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write minimal implementation**

`broll_search/editor/filters.py`:
```python
"""Pure builders for ffmpeg filtergraph strings (no ffmpeg execution here).

LUTs are referenced by relative, space-free, forward-slash paths so the same
filtergraph string works on Windows without colon/space escaping headaches."""

from __future__ import annotations

LUT_FILES = {
    "sony_slog3": "sony_slog3.cube",
    "dji_dlogm": "dji_dlogm.cube",
}
LOOK_LUT = "look_walkman.cube"


def _lut3d(rel_path: str) -> str:
    return f"lut3d=interp=tetrahedral:file={rel_path}"


def color_filter(profile: str, lut_dir: str = "luts", look_strength: float = 1.0) -> str:
    """Conversion LUT (if the profile is log) -> house look LUT.

    look_strength is accepted for forward-compat; Phase 1 applies the look at
    full strength (blending is a later-phase refinement)."""
    parts = []
    conv = LUT_FILES.get(profile)
    if conv:
        parts.append(_lut3d(f"{lut_dir}/{conv}"))
    parts.append(_lut3d(f"{lut_dir}/{LOOK_LUT}"))
    return ",".join(parts)


def reframe_filter(width: int, height: int) -> str:
    """Center-crop reframe: scale to cover the target box, then crop to it."""
    return (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}")


def conform_filter(fps: str = "24000/1001") -> str:
    return f"fps={fps}"


def clip_video_chain(profile: str, lut_dir: str, width: int, height: int,
                     fps: str, look_strength: float = 1.0) -> str:
    """Full per-clip video filter chain: color -> reframe -> conform -> 8-bit 420."""
    return ",".join([
        color_filter(profile, lut_dir, look_strength),
        reframe_filter(width, height),
        conform_filter(fps),
        "format=yuv420p",
    ])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv-editor/bin/python -m pytest tests/editor/test_filters.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add broll_search/editor/filters.py tests/editor/test_filters.py
git commit -m "feat(editor): ffmpeg filtergraph builders (color/reframe/conform)"
```

---

### Task 7: Heuristic planner (clips + music → EDL)

**Files:**
- Create: `broll_search/editor/planner.py`
- Test: `tests/editor/test_planner.py`

- [ ] **Step 1: Write the failing test**

`tests/editor/test_planner.py`:
```python
from broll_search.editor.probe import ClipInfo
from broll_search.editor.music import MusicInfo
from broll_search.editor.planner import plan
from broll_search.editor.edl import validate_edl


def _info(path, dur, fps=23.976):
    return ClipInfo(path=path, duration=dur, width=3840, height=2160, fps=fps)


def _music():
    beats = [i * 0.5 for i in range(33)]  # 16s @ 120 BPM
    return MusicInfo(path="m.wav", duration=16.0, tempo=120.0, beats=beats)


def test_plan_builds_valid_beat_aligned_edl():
    clips = [_info("FX6_a.mov", 10), _info("DJI_b.mp4", 10), _info("FX6_c.mov", 10)]
    edl = plan(clips, _music(), theme="parks", target_total=6.0,
               default_profile="rec709", pattern=(4, 2, 3))
    assert validate_edl(edl) == []
    assert edl.theme == "parks" and edl.music == "m.wav"
    assert len(edl.clips) >= 1
    # first clip is the hook; profiles inferred from filenames
    assert edl.clips[0].role == "hook"
    assert edl.clips[0].color_profile == "sony_slog3"   # "FX6_a"
    assert edl.clips[1].color_profile == "dji_dlogm"    # "DJI_b"
    # durations are varied (not all equal)
    durs = [c.duration for c in edl.clips]
    assert len(set(durs)) > 1


def test_plan_clamps_segment_to_short_clip():
    short = [_info("FX6_short.mov", 0.4)]   # shorter than a 2.0s segment
    edl = plan(short, _music(), theme="t", target_total=6.0,
               default_profile="rec709", pattern=(4,))
    assert validate_edl(edl) == []
    assert edl.clips[0].duration <= 0.4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-editor/bin/python -m pytest tests/editor/test_planner.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write minimal implementation**

`broll_search/editor/planner.py`:
```python
"""Phase 1 heuristic planner: clips + music beat grid -> EDL.

Deliberately simple — it cuts clips (in source order) to varied, beat-aligned
durations. Later phases replace/augment this with quality scoring, variety
de-dup, and the Gemini director (the EDL contract stays the same)."""

from __future__ import annotations

from typing import List, Sequence

from .edl import Clip, EDL
from .music import MusicInfo
from .probe import ClipInfo
from .profiles import profile_for
from .timing import beat_segment_endpoints


def plan(
    clips: Sequence[ClipInfo],
    music: MusicInfo,
    theme: str,
    target_total: float = 28.0,
    default_profile: str = "rec709",
    pattern: Sequence[int] = (4, 2, 3, 2, 4, 3),
) -> EDL:
    segments = beat_segment_endpoints(music.beats, target_total, pattern)
    edl_clips: List[Clip] = []
    cid = 1
    for i, (seg_start, seg_end) in enumerate(segments):
        if i >= len(clips):
            break  # ran out of distinct clips
        info = clips[i]
        seg_dur = seg_end - seg_start
        if info.duration <= 0:
            continue
        if info.duration >= seg_dur:
            # center the segment within the available footage
            in_point = round(max(0.0, (info.duration - seg_dur) / 2.0), 3)
            out_point = round(in_point + seg_dur, 3)
        else:
            # clip shorter than the beat segment — use the whole clip
            in_point, out_point = 0.0, round(info.duration, 3)
        is_last = (i == len(segments) - 1) or (i == len(clips) - 1)
        role = "hook" if cid == 1 else ("closer" if is_last else "body")
        edl_clips.append(Clip(
            id=cid, source=info.path, in_point=in_point, out_point=out_point,
            color_profile=profile_for(info.path, default_profile), role=role,
        ))
        cid += 1
    return EDL(theme=theme, music=music.path, clips=edl_clips,
               duration_target_s=target_total)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv-editor/bin/python -m pytest tests/editor/test_planner.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add broll_search/editor/planner.py tests/editor/test_planner.py
git commit -m "feat(editor): Phase 1 heuristic planner"
```

---

### Task 8: Render engine (EDL → MP4 via ffmpeg)

**Files:**
- Create: `broll_search/editor/render.py`
- Test: `tests/editor/test_render.py`

- [ ] **Step 1: Write the failing test** (integration; skips without ffmpeg)

`tests/editor/test_render.py`:
```python
import shutil
import subprocess
import json
from pathlib import Path

import pytest

from broll_search.editor.edl import Clip, EDL
from broll_search.editor.render import render_format

ffmpeg = shutil.which("ffmpeg")
ffprobe = shutil.which("ffprobe")
pytestmark = pytest.mark.skipif(not (ffmpeg and ffprobe),
                                reason="ffmpeg/ffprobe not available")


def _make_clip(path, seconds, fps):
    subprocess.run([ffmpeg, "-y", "-f", "lavfi",
                    "-i", f"testsrc2=size=1280x720:rate={fps}",
                    "-t", str(seconds), "-pix_fmt", "yuv420p", str(path)], check=True)


def _make_tone(path, seconds):
    subprocess.run([ffmpeg, "-y", "-f", "lavfi",
                    "-i", "sine=frequency=440:sample_rate=44100",
                    "-t", str(seconds), str(path)], check=True)


def test_render_vertical_produces_playable_mp4(tmp_path):
    a, b = tmp_path / "FX6_a.mp4", tmp_path / "DJI_b.mp4"
    _make_clip(a, 3, 60)
    _make_clip(b, 3, 30)
    music = tmp_path / "m.wav"
    _make_tone(music, 10)

    edl = EDL(theme="t", music=str(music), clips=[
        Clip(1, str(a), 0.0, 1.5, "rec709", "hook"),
        Clip(2, str(b), 0.0, 1.0, "rec709", "closer"),
    ])
    out = tmp_path / "vertical.mp4"
    render_format(edl, out, width=1080, height=1920, lut_dir="luts",
                  ffmpeg_path=ffmpeg, tmpdir=tmp_path)

    assert out.exists() and out.stat().st_size > 0
    meta = json.loads(subprocess.run(
        [ffprobe, "-v", "quiet", "-print_format", "json", "-show_streams", str(out)],
        capture_output=True, text=True).stdout)
    vid = next(s for s in meta["streams"] if s["codec_type"] == "video")
    assert vid["width"] == 1080 and vid["height"] == 1920
    assert any(s["codec_type"] == "audio" for s in meta["streams"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-editor/bin/python -m pytest tests/editor/test_render.py -v`
Expected: FAIL (`ModuleNotFoundError: broll_search.editor.render`). (Or SKIP if ffmpeg was not repaired in Task 0 — repair it so this runs.)

- [ ] **Step 3: Write minimal implementation**

`broll_search/editor/render.py`:
```python
"""Render an EDL to a single MP4 with ffmpeg.

Strategy (simple and robust for Phase 1): render each clip to a normalized
intermediate (trim + color + reframe + conform), concat the intermediates with
the concat demuxer, then mux in loudness-normalized music. Follows the
subprocess/Windows-console conventions from broll_search/web/media.py."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from .edl import EDL
from .filters import clip_video_chain


def _run(cmd: list) -> None:
    kwargs: dict = {"capture_output": True}
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = si
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(cmd, **kwargs)
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "ignore")[-1500:]
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}):\n{err}")


def render_format(
    edl: EDL,
    out_path: Path,
    width: int,
    height: int,
    lut_dir: str = "luts",
    ffmpeg_path: str = "ffmpeg",
    look_strength: float = 1.0,
    tmpdir: Optional[Path] = None,
) -> Path:
    out_path = Path(out_path)
    tmp = Path(tmpdir or out_path.parent) / f".render_{width}x{height}"
    tmp.mkdir(parents=True, exist_ok=True)

    # 1) per-clip normalized intermediates
    seg_files = []
    for clip in edl.clips:
        seg = tmp / f"seg_{clip.id:03d}.mp4"
        vf = clip_video_chain(clip.color_profile, lut_dir, width, height,
                              edl.fps, look_strength)
        _run([ffmpeg_path, "-y", "-ss", str(clip.in_point), "-i", clip.source,
              "-t", str(clip.duration), "-an", "-vf", vf, "-r", edl.fps,
              "-c:v", "libx264", "-crf", "18", "-preset", "medium",
              "-pix_fmt", "yuv420p", str(seg)])
        seg_files.append(seg)

    # 2) concat intermediates (identical params -> stream copy)
    listfile = tmp / "concat.txt"
    listfile.write_text("".join(f"file '{s.resolve()}'\n" for s in seg_files),
                        encoding="utf-8")
    silent = tmp / "silent.mp4"
    _run([ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
          "-c", "copy", str(silent)])

    # 3) mux loudness-normalized music; end at the shorter of video/music
    _run([ffmpeg_path, "-y", "-i", str(silent), "-i", edl.music,
          "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
          "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k",
          "-shortest", "-movflags", "+faststart", str(out_path)])
    return out_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv-editor/bin/python -m pytest tests/editor/test_render.py -v`
Expected: PASS (1 passed). If it SKIPs, repair ffmpeg (Task 0, Step 7) and re-run.

> **Note on 10-bit log footage:** real S-Log3/D-Log files are often 10-bit 4:2:2. If a real clip errors in `lut3d`/`scale`, prepend `zscale` (as `web/media.py` does for 10-bit) — add that handling when validating against the user's sample clips.

- [ ] **Step 5: Commit**

```bash
git add broll_search/editor/render.py tests/editor/test_render.py
git commit -m "feat(editor): ffmpeg render engine (trim+color+reframe+concat+music)"
```

---

### Task 9: Pipeline orchestration + CLI

**Files:**
- Create: `broll_search/editor/pipeline.py`
- Create: `broll_search/editor/__main__.py`
- Test: `tests/editor/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

`tests/editor/test_pipeline.py`:
```python
from broll_search.editor.probe import ClipInfo
from broll_search.editor.music import MusicInfo
from broll_search.editor import pipeline


def test_build_edl_from_inputs(monkeypatch):
    # Stub probing + music so this stays a fast unit test (no ffmpeg/librosa).
    infos = {
        "FX6_a.mov": ClipInfo("FX6_a.mov", 10, 3840, 2160, 23.976),
        "DJI_b.mp4": ClipInfo("DJI_b.mp4", 10, 3840, 2160, 59.94),
    }
    monkeypatch.setattr(pipeline, "probe_clip", lambda p, ffprobe_path="ffprobe": infos[p])
    beats = [i * 0.5 for i in range(33)]
    monkeypatch.setattr(pipeline, "analyze_music",
                        lambda p: MusicInfo(p, 16.0, 120.0, beats))

    edl = pipeline.build_edl(
        clip_paths=["FX6_a.mov", "DJI_b.mp4"], music_path="m.wav",
        theme="parks", target_total=4.0, default_profile="rec709",
        ffprobe_path="ffprobe")
    assert edl.theme == "parks"
    assert [c.color_profile for c in edl.clips][:2] == ["sony_slog3", "dji_dlogm"]


def test_find_media_lists_supported_files(tmp_path):
    (tmp_path / "a.MOV").write_bytes(b"x")
    (tmp_path / "b.mp4").write_bytes(b"x")
    (tmp_path / "notes.txt").write_bytes(b"x")
    found = pipeline.find_media(tmp_path, pipeline.VIDEO_EXTS)
    names = sorted(p.name for p in found)
    assert names == ["a.MOV", "b.mp4"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-editor/bin/python -m pytest tests/editor/test_pipeline.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write minimal implementation**

`broll_search/editor/pipeline.py`:
```python
"""Phase 1 orchestration: a folder of clips + a music track -> two MP4s."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from .edl import EDL, validate_edl
from .music import MusicInfo, analyze_music
from .planner import plan
from .probe import ClipInfo, probe_clip
from .render import render_format

VIDEO_EXTS = {".mp4", ".mov", ".mxf", ".m4v", ".mkv", ".avi"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac"}


@dataclass
class RenderResult:
    edl: EDL
    vertical: Path
    landscape: Path
    out_dir: Path


def find_media(folder: Path, exts) -> List[Path]:
    exts = {e.lower() for e in exts}
    return sorted(p for p in Path(folder).iterdir()
                  if p.is_file() and p.suffix.lower() in exts)


def build_edl(clip_paths: Sequence[str], music_path: str, theme: str,
              target_total: float, default_profile: str,
              ffprobe_path: str = "ffprobe") -> EDL:
    infos: List[ClipInfo] = [probe_clip(p, ffprobe_path=ffprobe_path) for p in clip_paths]
    music: MusicInfo = analyze_music(music_path)
    return plan(infos, music, theme=theme, target_total=target_total,
                default_profile=default_profile)


def run_pipeline(clips_dir: str, music_dir: str, out_dir: str, theme: str,
                 target_total: float = 28.0, default_profile: str = "rec709",
                 lut_dir: str = "luts", ffmpeg_path: str = "ffmpeg",
                 ffprobe_path: str = "ffprobe") -> RenderResult:
    clip_paths = [str(p) for p in find_media(Path(clips_dir), VIDEO_EXTS)]
    if not clip_paths:
        raise RuntimeError(f"No video clips found in {clips_dir}")
    music = find_media(Path(music_dir), AUDIO_EXTS)
    if not music:
        raise RuntimeError(f"No music track found in {music_dir}")

    edl = build_edl(clip_paths, str(music[0]), theme, target_total,
                    default_profile, ffprobe_path=ffprobe_path)
    errors = validate_edl(edl)
    if errors:
        raise RuntimeError("Invalid EDL:\n  - " + "\n  - ".join(errors))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    vertical = render_format(edl, out / "vertical.mp4", 1080, 1920,
                             lut_dir=lut_dir, ffmpeg_path=ffmpeg_path, tmpdir=out)
    landscape = render_format(edl, out / "landscape.mp4", 1920, 1080,
                              lut_dir=lut_dir, ffmpeg_path=ffmpeg_path, tmpdir=out)
    (out / "edl.json").write_text(_edl_to_json(edl), encoding="utf-8")
    return RenderResult(edl=edl, vertical=vertical, landscape=landscape, out_dir=out)


def _edl_to_json(edl: EDL) -> str:
    import json
    from dataclasses import asdict
    return json.dumps(asdict(edl), indent=2)
```

`broll_search/editor/__main__.py`:
```python
"""CLI: python -m broll_search.editor --clips dev_media/clips --music dev_media/music"""

from __future__ import annotations

import argparse
import sys

from .pipeline import run_pipeline


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="broll_search.editor",
                                description="MNN Auto-Editor (Phase 1, offline)")
    p.add_argument("--clips", default="dev_media/clips", help="Folder of source clips")
    p.add_argument("--music", default="dev_media/music", help="Folder with a music track")
    p.add_argument("--out", default="output/latest", help="Output folder")
    p.add_argument("--theme", default="MNN B-Roll", help="Theme label for the video")
    p.add_argument("--duration", type=float, default=28.0, help="Target length (s)")
    p.add_argument("--profile", default="rec709",
                   choices=["rec709", "sony_slog3", "dji_dlogm"],
                   help="Default color profile when not inferable from filename")
    p.add_argument("--lut-dir", default="luts")
    p.add_argument("--ffmpeg", default="ffmpeg")
    p.add_argument("--ffprobe", default="ffprobe")
    args = p.parse_args(argv)

    try:
        res = run_pipeline(args.clips, args.music, args.out, args.theme,
                           target_total=args.duration, default_profile=args.profile,
                           lut_dir=args.lut_dir, ffmpeg_path=args.ffmpeg,
                           ffprobe_path=args.ffprobe)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Done. {len(res.edl.clips)} clips -> {res.vertical} and {res.landscape}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv-editor/bin/python -m pytest tests/editor/test_pipeline.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full suite**

Run: `.venv-editor/bin/python -m pytest tests/editor -v`
Expected: all pass (render test passes if ffmpeg present, else skips).

- [ ] **Step 6: Commit**

```bash
git add broll_search/editor/pipeline.py broll_search/editor/__main__.py tests/editor/test_pipeline.py
git commit -m "feat(editor): Phase 1 pipeline orchestration + CLI"
```

---

### Task 10: End-to-end smoke run on real sample clips

**Files:** none (manual verification once the user drops clips into `dev_media/`)

- [ ] **Step 1: Confirm sample media is present**

Run: `ls dev_media/clips dev_media/music`
Expected: at least one video in `clips/` and one track in `music/`. If empty, stop and ask the user to drop samples in.

- [ ] **Step 2: Run the editor end-to-end**

Run:
```bash
.venv-editor/bin/python -m broll_search.editor \
  --clips dev_media/clips --music dev_media/music \
  --out output/smoke --theme "Nashville" --duration 20
```
Expected: prints `Done. N clips -> output/smoke/vertical.mp4 and output/smoke/landscape.mp4`.

- [ ] **Step 3: Inspect the outputs**

Run:
```bash
ffprobe -v quiet -print_format json -show_streams output/smoke/vertical.mp4 \
  | python3 -c "import sys,json; s=json.load(sys.stdin)['streams']; v=[x for x in s if x['codec_type']=='video'][0]; print('video', v['width'], v['height'], v['avg_frame_rate']); print('audio', any(x['codec_type']=='audio' for x in s))"
open output/smoke/vertical.mp4 output/smoke/landscape.mp4
```
Expected: vertical reports `1080 1920`, landscape `1920 1080`, both `24000/1001`, audio `True`. Both play; cuts land on the beat; color looks graded (not flat log) on Sony/DJI clips.

- [ ] **Step 4: Record findings**

Note any issues (10-bit `lut3d` errors → add `zscale`; off-beat cuts; bad crops) as the punch-list for Phase 2 / fixes. No commit (outputs are git-ignored).

---

## Self-review

**Spec coverage (Phase 1 scope):** beat-synced varied cutting (Tasks 4,7) ✓ · per-camera color chain with the user's LUTs (Tasks 0,5,6) ✓ · conform to 23.98 (Task 6) ✓ · reframe to 9:16 + native 16:9 (Tasks 6,8) ✓ · dual export with loudness-normalized music (Task 8) ✓ · CLI (Task 9) ✓ · cross-platform/Windows-safe subprocess + relative LUT paths (Tasks 2,6,8) ✓. Deferred items are listed in **Scope** and remain in the spec for later plans.

**Placeholder scan:** every code step contains complete, runnable code; no TBD/TODO. `look_strength` is a real parameter (passed through, full-strength in Phase 1) — documented, not a placeholder.

**Type consistency:** `ClipInfo(path,duration,width,height,fps)`, `MusicInfo(path,duration,tempo,beats)`, `Clip(id,source,in_point,out_point,color_profile,role)`, `EDL(theme,music,clips,fps,duration_target_s)` are used identically across `probe`, `music`, `planner`, `render`, `pipeline`. Function names (`probe_clip`, `analyze_music`, `plan`, `clip_video_chain`, `render_format`, `run_pipeline`, `build_edl`, `find_media`) match between definitions and call sites/tests.

---

## Next phases (separate plans)
- **Phase 2:** quality scoring + best-moment windowing, variety/de-dup, slow-mo retime (high-fps → smooth), 29.97/30 conform, color normalize/match.
- **Phase 3:** subject-aware reframe (mediapipe/YOLO + smoothed trajectory).
- **Phase 4:** Gemini full-vision creative director + scouting cache + cost caps (heuristic planner stays as fallback).
- **Phase 5:** on-screen text/branding, web "Productions" tab, scheduling.
- **Phase 6:** Windows server installer + manager hand-off doc.
