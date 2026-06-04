"""Read AI metadata produced by the MNN Clipper and attach it to footage.

The Clipper already generates an AI breakdown per clip (tags + a description).
Rather than re-analyzing video (which would break the offline rule and send
sensitive footage to a cloud service), the B-Roll indexer simply reads that
metadata and folds it into the search index.

Two sources are supported (a clip may use either):

1. A **manifest** JSON file at the footage root, named ``_mnn_broll_metadata.json``
   (or set ``metadata_manifest`` in config.json). Shape::

       {
         "version": 1,
         "clips": [
           {
             "filename": "blodgett-oven-closeup-commercial-kitchen.mov",
             "description": "Close-up of a Blodgett commercial oven.",
             "tags": ["oven", "stainless steel", "commercial kitchen"],
             "category": "kitchen",          // optional B-Roll category key
             "location": "The Commissary"     // optional, any extra fields ok
           }
         ]
       }

   ``clips`` may also be an object keyed by filename. Matching is by file name
   (case-insensitive); an optional ``"path"`` (relative to the root) wins if set.

2. A per-file **sidecar** named ``<videofilename>.mnn.json`` next to the clip,
   containing a single clip object (same fields, ``filename`` optional).

All fields are optional. ``tags`` accepts a list or a comma/semicolon string.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

MANIFEST_NAME = "_mnn_broll_metadata.json"
SIDECAR_SUFFIX = ".mnn.json"


def _norm_tags(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.replace(";", ",").split(",")]
        return [p for p in parts if p]
    if isinstance(raw, (list, tuple)):
        return [str(t).strip() for t in raw if str(t).strip()]
    return []


def _norm_entry(entry: dict) -> dict:
    return {
        "description": str(entry.get("description") or entry.get("caption") or "").strip(),
        "tags": _norm_tags(entry.get("tags") or entry.get("keywords") or entry.get("labels")),
        "category": str(entry.get("category") or "").strip(),
        "location": str(entry.get("location") or "").strip(),
        "path": str(entry.get("path") or "").strip(),
    }


class MetadataIndex:
    """Loaded AI metadata for one footage root, looked up by file."""

    def __init__(self) -> None:
        self.by_name: dict[str, dict] = {}   # lower basename -> entry
        self.by_relpath: dict[str, dict] = {}  # normalized relpath -> entry
        self.loaded_from: Optional[str] = None
        self.count = 0

    def load_manifest(self, manifest_path: Path) -> None:
        try:
            with open(manifest_path, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return
        clips = data.get("clips", data) if isinstance(data, dict) else data
        items = []
        if isinstance(clips, dict):
            for name, entry in clips.items():
                if isinstance(entry, dict):
                    entry = {**entry, "filename": entry.get("filename", name)}
                    items.append((name, entry))
        elif isinstance(clips, list):
            for entry in clips:
                if isinstance(entry, dict):
                    items.append((entry.get("filename", ""), entry))
        for name, entry in items:
            norm = _norm_entry(entry)
            fname = (entry.get("filename") or name or "").strip()
            if fname:
                self.by_name[os.path.basename(fname).lower()] = norm
            if norm["path"]:
                self.by_relpath[norm["path"].replace("\\", "/").lower()] = norm
            self.count += 1
        self.loaded_from = str(manifest_path)

    def lookup(self, full_path: str, root: str) -> Optional[dict]:
        # 1) per-file sidecar next to the clip
        sidecar = Path(full_path + SIDECAR_SUFFIX)
        if sidecar.exists():
            try:
                with open(sidecar, "r", encoding="utf-8-sig") as fh:
                    return _norm_entry(json.load(fh))
            except (OSError, json.JSONDecodeError):
                pass
        # 2) manifest by relative path, then by basename
        try:
            rel = os.path.relpath(full_path, root).replace("\\", "/").lower()
        except ValueError:
            rel = ""
        if rel and rel in self.by_relpath:
            return self.by_relpath[rel]
        return self.by_name.get(os.path.basename(full_path).lower())


def load_for_root(root: Path, manifest_override: Optional[str] = None) -> MetadataIndex:
    """Load the manifest for a footage root (if present)."""
    idx = MetadataIndex()
    candidates = []
    if manifest_override:
        candidates.append(Path(manifest_override))
    candidates.append(Path(root) / MANIFEST_NAME)
    for c in candidates:
        if c.exists():
            idx.load_manifest(c)
            break
    return idx
