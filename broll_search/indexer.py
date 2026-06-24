"""Phase 2 — folder scanner and incremental indexer.

Walks each footage root, filters to configured video extensions, derives
metadata from your ``<root-year>/<shooter>/<month>/<filename>`` convention,
optionally reads duration/resolution/codec via ffprobe, and upserts rows into
the SQLite index. Incremental: a file whose size and modified-time already match
the index is skipped; files that have vanished from a root are removed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import database as db
from . import metadata
from .config import Config, PROJECT_ROOT

ProgressFn = Callable[[int, Optional[int], str], None]
LogFn = Callable[[str], None]

# Only one index run at a time (web auto-index + manual re-index + desktop).
_INDEX_LOCK = threading.Lock()


# --- Filename / path parsing ---------------------------------------------

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}

_YEAR_RE = re.compile(r"(?:19|20)\d{2}")

# Ordered shot-type detection. First match wins, so more specific/!common
# phrases come first. Multi-word entries are matched against the hyphenated
# filename; single words are matched as whole tokens.
_SHOT_TYPES: list[tuple[str, list[str]]] = [
    ("Closeup", ["closeup", "close-up"]),
    ("Wide", ["wide-shot", "wideshot", "wide"]),
    ("Medium", ["medium-shot", "medium", "mid-shot"]),
    ("Static", ["static", "locked-off"]),
    ("Aerial", ["aerial", "drone"]),
    ("Tracking", ["tracking", "dolly", "gimbal"]),
    ("Handheld", ["handheld", "hand-held"]),
    ("Pan", ["pan", "panning"]),
    ("Tilt", ["tilt"]),
    ("Zoom", ["zoom"]),
    ("Establishing", ["establishing"]),
    ("POV", ["pov"]),
]


def parse_year_from_root(root: Path) -> Optional[int]:
    """Pull a 4-digit year from the footage root folder name (e.g. '2026 …')."""
    m = _YEAR_RE.search(root.name)
    return int(m.group(0)) if m else None


def detect_shot_type(stem: str) -> Optional[str]:
    s = stem.lower()
    tokens = set(re.split(r"[^a-z0-9]+", s))
    for canonical, needles in _SHOT_TYPES:
        for needle in needles:
            if "-" in needle:
                if needle in s:
                    return canonical
            elif needle in tokens:
                return canonical
    return None


def extract_keywords(stem: str) -> str:
    """Filename stem -> space-separated lowercase words for keyword search."""
    words = [w for w in re.split(r"[^a-z0-9]+", stem.lower()) if w]
    # De-duplicate while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return " ".join(out)


def derive_path_fields(root: Path, file_path: Path, root_year: Optional[int]) -> dict:
    """Derive shooter, month, shoot date, etc. from the file's location."""
    try:
        rel = file_path.relative_to(root)
    except ValueError:
        rel = Path(file_path.name)
    parts = rel.parts  # e.g. ('Gil', 'July', 'clip.mov')

    shooter = parts[0] if len(parts) >= 2 else None

    month_name = None
    shoot_month = None
    for part in parts[:-1]:  # any folder above the file
        key = part.strip().lower()
        if key in _MONTHS:
            month_name = part
            shoot_month = _MONTHS[key]
            break

    shoot_year = root_year
    shoot_date = None
    if shoot_year and shoot_month:
        shoot_date = f"{shoot_year:04d}-{shoot_month:02d}-01"

    return {
        "relative_path": str(rel),
        "shooter": shooter,
        "month_name": month_name,
        "shoot_year": shoot_year,
        "shoot_month": shoot_month,
        "shoot_date": shoot_date,
    }


# --- ffprobe --------------------------------------------------------------


@dataclass
class FFProbe:
    """Resolves and runs ffprobe, degrading gracefully if it isn't installed."""

    ffprobe_path: str = "ffprobe"
    enabled: bool = True
    timeout: float = 30.0
    resolved: Optional[str] = field(init=False, default=None)
    available: bool = field(init=False, default=False)
    _warned: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        if not self.enabled:
            return
        self.resolved = self._resolve(self.ffprobe_path)
        self.available = bool(self.resolved)

    @staticmethod
    def _resolve(configured: str) -> Optional[str]:
        """Find ffprobe, preferring a copy bundled with the app so staff never
        have to edit PATH. Search order:

        1. the exact 'ffprobe_path' from config (if it's a real file),
        2. ffprobe on the system PATH,
        3. a bundled binary at tools/ffprobe.exe, ffprobe.exe, or bin/ffprobe.exe
           next to the project.
        """
        # 1) Explicit path to a real file.
        if configured and configured not in ("ffprobe", "ffprobe.exe"):
            p = Path(configured)
            if p.exists():
                return str(p)

        # 2) On PATH.
        found = shutil.which(configured) or shutil.which("ffprobe")
        if found:
            return found

        # 3) Bundled alongside the app.
        names = ["ffprobe.exe", "ffprobe"]
        folders = [PROJECT_ROOT / "tools", PROJECT_ROOT / "bin", PROJECT_ROOT]
        for folder in folders:
            for name in names:
                cand = folder / name
                if cand.exists():
                    return str(cand)
        return None

    def probe(self, path: str) -> dict:
        """Return {duration_sec, width, height, codec} or {} on any failure."""
        if not (self.enabled and self.available and self.resolved):
            return {}
        cmd = [
            self.resolved, "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", path,
        ]
        kwargs: dict = {"capture_output": True, "text": True, "timeout": self.timeout}
        if os.name == "nt":  # don't flash a console window on Windows
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs["startupinfo"] = si
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        try:
            proc = subprocess.run(cmd, **kwargs)
            if proc.returncode != 0 or not proc.stdout:
                return {}
            data = json.loads(proc.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            return {}

        out: dict = {}
        fmt = data.get("format", {})
        if fmt.get("duration"):
            try:
                out["duration_sec"] = float(fmt["duration"])
            except (TypeError, ValueError):
                pass
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                out["width"] = stream.get("width")
                out["height"] = stream.get("height")
                out["codec"] = stream.get("codec_name")
                break
        return out


# --- Indexing -------------------------------------------------------------


@dataclass
class IndexResult:
    scanned: int = 0
    added: int = 0
    updated: int = 0
    skipped: int = 0
    removed: int = 0
    errors: int = 0
    skipped_duplicate: bool = False
    roots_indexed: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    ffprobe_used: bool = False

    def summary(self) -> str:
        return (
            f"Indexed {self.scanned} file(s): {self.added} added, "
            f"{self.updated} updated, {self.skipped} unchanged, "
            f"{self.removed} removed, {self.errors} error(s)."
        )


def _is_hidden_or_system(name: str, entry_path: str) -> bool:
    if name.startswith(".") or name.lower() == "desktop.ini":
        return True
    if os.name == "nt":
        try:
            attrs = os.stat(entry_path).st_file_attributes  # type: ignore[attr-defined]
            hidden = 0x2
            system = 0x4
            if attrs & (hidden | system):
                return True
        except (OSError, AttributeError):
            pass
    return False


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def run_index(
    config: Config,
    *,
    progress: Optional[ProgressFn] = None,
    log: Optional[LogFn] = None,
    full_rescan: bool = False,
) -> IndexResult:
    """Scan all configured footage roots and update the SQLite index."""
    def _log(msg: str) -> None:
        if log:
            log(msg)

    if not _INDEX_LOCK.acquire(blocking=False):
        _log("Index already in progress — skipped.")
        return IndexResult(
            started_at=datetime.now().isoformat(timespec="seconds"),
            finished_at=datetime.now().isoformat(timespec="seconds"),
            skipped_duplicate=True,
        )

    try:
        return _run_index_locked(config, progress=progress, log=log, full_rescan=full_rescan)
    finally:
        _INDEX_LOCK.release()


def _run_index_locked(
    config: Config,
    *,
    progress: Optional[ProgressFn] = None,
    log: Optional[LogFn] = None,
    full_rescan: bool = False,
) -> IndexResult:
    def _log(msg: str) -> None:
        if log:
            log(msg)

    result = IndexResult(started_at=datetime.now().isoformat(timespec="seconds"))
    extensions = config.normalized_extensions
    ff = FFProbe(
        ffprobe_path=config.ffprobe_path,
        enabled=config.extract_video_metadata,
    )
    result.ffprobe_used = ff.available
    if config.extract_video_metadata and not ff.available:
        _log("ffprobe not found — indexing without video metadata "
             "(duration/resolution). Set 'ffprobe_path' in config.json to enable.")

    con = db.connect(config.database_abspath)
    try:
        roots = config.configured_footage_paths()
        if not roots:
            _log("No footage paths configured; nothing to index.")
            return result

        processed = 0
        for root in roots:
            if not root.is_dir():
                _log(f"Skipping '{root}' — not an accessible folder.")
                continue
            root_str = str(root)
            root_year = parse_year_from_root(root)
            result.roots_indexed.append(root_str)
            # AI metadata from the MNN Clipper (manifest at root + per-file sidecars).
            meta_idx = metadata.load_for_root(root, getattr(config, "metadata_manifest", None) or None)
            if meta_idx.count:
                _log(f"  Loaded AI metadata for {meta_idx.count} clip(s) from {meta_idx.loaded_from}")
            _log(f"Scanning {root} (year={root_year or 'unknown'}) …")

            seen: set[str] = set()
            pending = 0
            for dirpath, dirnames, filenames in os.walk(root_str):
                # Prune hidden/system directories in place.
                dirnames[:] = [
                    d for d in dirnames
                    if not _is_hidden_or_system(d, os.path.join(dirpath, d))
                ]
                for fname in filenames:
                    full = os.path.join(dirpath, fname)
                    ext = os.path.splitext(fname)[1].lower()
                    if ext not in extensions:
                        continue
                    if _is_hidden_or_system(fname, full):
                        continue

                    result.scanned += 1
                    seen.add(full)
                    if progress:
                        progress(processed, None, full)
                    processed += 1

                    try:
                        st = os.stat(full)
                    except OSError as exc:
                        result.errors += 1
                        _log(f"  ! could not stat {full}: {exc}")
                        continue

                    fp = db.get_existing_fingerprint(con, full)
                    if fp is not None and not full_rescan and fp == (st.st_size, st.st_mtime_ns):
                        # File unchanged — but the Clipper's AI metadata may have been
                        # added/updated since last index. Apply it cheaply (no ffprobe).
                        ai = meta_idx.lookup(full, root_str)
                        if ai and (ai["tags"] or ai["description"] or ai["category"]):
                            base_kw = extract_keywords(Path(full).stem)
                            extra_kw = extract_keywords(
                                " ".join(ai["tags"]) + " " + ai["description"] + " " + ai["location"])
                            new_kw = (base_kw + " " + extra_kw).strip()
                            try:
                                db.update_ai_metadata(
                                    con, full, ai["description"] or None,
                                    ", ".join(ai["tags"]) or None, ai["category"] or None, new_kw)
                                pending += 1
                            except Exception:  # noqa: BLE001
                                pass
                        result.skipped += 1
                        continue

                    path_obj = Path(full)
                    stem = path_obj.stem
                    record = {
                        "path": full,
                        "root": root_str,
                        "filename": fname,
                        "extension": ext,
                        "parent_folder": os.path.basename(dirpath),
                        "folder_path": dirpath,
                        "shot_type": detect_shot_type(stem),
                        "keywords": extract_keywords(stem),
                        "size_bytes": st.st_size,
                        "mtime_ns": st.st_mtime_ns,
                        "date_created": _iso(st.st_ctime),
                        "date_modified": _iso(st.st_mtime),
                        "indexed_at": datetime.now().isoformat(timespec="seconds"),
                        "duration_sec": None, "width": None,
                        "height": None, "codec": None,
                    }
                    record.update(derive_path_fields(root, path_obj, root_year))
                    record.update(ff.probe(full))

                    # Fold in the Clipper's AI metadata (tags + description) so it
                    # is searchable and improves auto-categorization.
                    ai = meta_idx.lookup(full, root_str)
                    if ai:
                        record["ai_description"] = ai["description"] or None
                        record["ai_tags"] = ", ".join(ai["tags"]) or None
                        record["ai_category"] = ai["category"] or None
                        extra = " ".join(ai["tags"]) + " " + ai["description"] + " " + ai["location"]
                        extra_kw = extract_keywords(extra)
                        if extra_kw:
                            record["keywords"] = (record["keywords"] + " " + extra_kw).strip()

                    try:
                        db.upsert_file(con, record)
                    except Exception as exc:  # noqa: BLE001
                        result.errors += 1
                        _log(f"  ! could not index {full}: {exc}")
                        continue

                    if fp is None:
                        result.added += 1
                    else:
                        result.updated += 1

                    pending += 1
                    if pending >= 200:  # commit periodically on large libraries
                        con.commit()
                        pending = 0

            con.commit()

            # Remove rows for files that no longer exist under this root.
            stale = db.all_paths_for_root(con, root_str) - seen
            if stale:
                db.delete_paths(con, stale)
                result.removed += len(stale)
                con.commit()

        result.finished_at = datetime.now().isoformat(timespec="seconds")
        db.set_meta(con, "last_index_completed_at", result.finished_at)
        db.set_meta(con, "last_index_summary", result.summary())
        db.set_meta(con, "last_index_file_count", str(db.file_count(con)))
        con.commit()
        _log(result.summary())
        return result
    finally:
        con.close()
