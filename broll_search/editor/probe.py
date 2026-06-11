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
