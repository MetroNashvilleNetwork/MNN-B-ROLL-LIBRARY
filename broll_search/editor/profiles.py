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
