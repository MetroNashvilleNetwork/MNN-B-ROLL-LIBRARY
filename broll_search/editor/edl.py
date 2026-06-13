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
    stabilize: bool = False  # director sets True for shaky shots → renderer applies vidstab (later phase)
    subject_x: float = 0.5   # 0=left..1=right; where to anchor the vertical reframe
    retime: str = "normal"      # "normal" | "slowmo"
    source_fps: float = 0.0     # used to compute the slow-mo factor when retime == "slowmo"
    # exposure (deterministic, computed from measurement — NOT model-chosen)
    exposure_adjust: float = 0.0    # signed; renderer maps to eq/curves. abs<0.04 => no filter
    highlight_clip: float = 0.0     # >0.02 => prepend colorlevels ceiling pull
    # motion / one-motion-per-clip
    motion_type: str = "static"     # pan|tilt|push_in|pull_back|static|complex
    push_in: float = 0.0            # synthetic push amount (0 = none; 0.05/0.07/0.08 by duration)

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
