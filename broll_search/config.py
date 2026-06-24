"""Phase 1 — Configuration loading and validation.

Loads ``config.json`` (settings such as the mapped SharePoint drive paths),
fills in defaults for any missing fields, and exposes a typed :class:`Config`
object to the rest of the app. Designed so non-technical staff only ever have
to edit a small, well-commented JSON file.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Project root = the folder that contains this package (one level up).
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent

CONFIG_FILENAME = "config.json"
EXAMPLE_FILENAME = "config.example.json"

CONFIG_PATH = PROJECT_ROOT / CONFIG_FILENAME
EXAMPLE_PATH = PROJECT_ROOT / EXAMPLE_FILENAME


class ConfigError(Exception):
    """Raised when the configuration file is missing or malformed."""


# --- Default values -------------------------------------------------------
# Anything the user omits from config.json falls back to these.

DEFAULT_VIDEO_EXTENSIONS = [
    ".mp4", ".mxf", ".mov", ".avi", ".mkv", ".m4v", ".wmv",
]

DEFAULT_AUTO_INDEX = {
    "enabled": True,
    "run_on_launch": True,
    "interval_hours": 24,
}

DEFAULT_VALIDATION = {
    "listing_timeout_seconds": 10,
    "warn_if_empty": True,
}


@dataclass
class AutoIndexConfig:
    enabled: bool = True
    run_on_launch: bool = True
    interval_hours: int = 24


@dataclass
class ValidationConfig:
    listing_timeout_seconds: float = 10.0
    warn_if_empty: bool = True


@dataclass
class Config:
    """Typed view of config.json with defaults already applied."""

    footage_paths: list[str] = field(default_factory=list)
    database_path: str = "broll_index.db"
    video_extensions: list[str] = field(default_factory=lambda: list(DEFAULT_VIDEO_EXTENSIONS))
    auto_index: AutoIndexConfig = field(default_factory=AutoIndexConfig)
    extract_video_metadata: bool = True
    ffprobe_path: str = "ffprobe"
    ffmpeg_path: str = "ffmpeg"
    metadata_manifest: str = ""   # optional explicit path to the Clipper's AI manifest
    web_port: int = 8765
    preview_max_width: int = 640
    preview_max_seconds: int = 60
    server_footage_root: str = ""
    network_footage_root: str = ""
    share_token: str = ""   # optional; when set, LAN share mode requires ?token= on first visit
    validation: ValidationConfig = field(default_factory=ValidationConfig)

    # Absolute path the config was loaded from (for messages / saving).
    source_path: Path = field(default=CONFIG_PATH)

    # -- Derived helpers ---------------------------------------------------

    @property
    def database_abspath(self) -> Path:
        """Resolve database_path relative to the project root if not absolute."""
        p = Path(self.database_path)
        return p if p.is_absolute() else (PROJECT_ROOT / p)

    @property
    def cache_dir(self) -> Path:
        """Local folder for generated thumbnails and preview clips."""
        return PROJECT_ROOT / "cache"

    @property
    def normalized_extensions(self) -> set[str]:
        """Lower-cased extensions with a guaranteed leading dot."""
        out: set[str] = set()
        for ext in self.video_extensions:
            ext = ext.strip().lower()
            if not ext:
                continue
            if not ext.startswith("."):
                ext = "." + ext
            out.add(ext)
        return out

    def configured_footage_paths(self) -> list[Path]:
        """footage_paths as Path objects, with placeholders filtered out."""
        paths: list[Path] = []
        for raw in self.footage_paths:
            if not raw or not str(raw).strip():
                continue
            if _looks_like_placeholder(str(raw)):
                continue
            paths.append(Path(str(raw).strip()))
        return paths

    def is_path_under_footage_roots(self, path: str) -> bool:
        """True when ``path`` resolves under a configured footage root."""
        if not path or not str(path).strip():
            return False
        try:
            resolved = Path(path).resolve()
        except OSError:
            return False
        roots = self.configured_footage_paths()
        if not roots:
            return True
        for root in roots:
            try:
                root_res = root.resolve()
            except OSError:
                root_res = root
            try:
                resolved.relative_to(root_res)
                return True
            except ValueError:
                continue
        return False


# Common example/placeholder values we should not treat as real drives.
# Compared after normalizing: lower-cased, backslashes -> forward slashes,
# trailing separators stripped.
_PLACEHOLDER_PATHS = {
    "z:/b-roll footage",
    "x:/path/to/footage",
    "path/to/footage",
    "",
}


def _normalize_path_key(raw: str) -> str:
    return raw.strip().lower().replace("\\", "/").rstrip("/")


def _looks_like_placeholder(raw: str) -> bool:
    key = _normalize_path_key(raw)
    return key in {_normalize_path_key(p) for p in _PLACEHOLDER_PATHS}


def config_exists() -> bool:
    return CONFIG_PATH.exists()


def init_config(overwrite: bool = False) -> Path:
    """Create config.json from config.example.json.

    Returns the path written. Raises ConfigError if the example is missing,
    or if config.json already exists and ``overwrite`` is False.
    """
    if CONFIG_PATH.exists() and not overwrite:
        raise ConfigError(
            f"{CONFIG_FILENAME} already exists at {CONFIG_PATH}. "
            f"Edit it directly, or pass overwrite=True to replace it."
        )
    if not EXAMPLE_PATH.exists():
        raise ConfigError(
            f"Cannot create {CONFIG_FILENAME}: template {EXAMPLE_FILENAME} "
            f"is missing from {PROJECT_ROOT}."
        )
    shutil.copyfile(EXAMPLE_PATH, CONFIG_PATH)
    return CONFIG_PATH


def load_config(path: Path | str | None = None, *, create_if_missing: bool = False) -> Config:
    """Load and validate configuration.

    Parameters
    ----------
    path:
        Optional explicit path to a config JSON file. Defaults to config.json
        in the project root.
    create_if_missing:
        If True and the config file does not exist, copy the example template
        first instead of raising.
    """
    cfg_path = Path(path) if path else CONFIG_PATH

    if not cfg_path.exists():
        if create_if_missing and cfg_path == CONFIG_PATH:
            init_config()
        else:
            raise ConfigError(
                f"Configuration file not found: {cfg_path}\n"
                f"Run 'python main.py --init-config' to create one from the template."
            )

    try:
        with open(cfg_path, "r", encoding="utf-8") as fh:
            raw: dict[str, Any] = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"{cfg_path.name} is not valid JSON (line {exc.lineno}, column "
            f"{exc.colno}): {exc.msg}. Check for missing commas or unescaped "
            f"backslashes in Windows paths (use '/' or '\\\\')."
        ) from exc
    except OSError as exc:
        raise ConfigError(f"Could not read {cfg_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{cfg_path.name} must contain a JSON object at the top level.")

    return _build_config(raw, cfg_path)


def _build_config(raw: dict[str, Any], source: Path) -> Config:
    footage_paths = raw.get("footage_paths", [])
    if isinstance(footage_paths, str):  # tolerate a single string
        footage_paths = [footage_paths]
    if not isinstance(footage_paths, list):
        raise ConfigError("'footage_paths' must be a list of folder paths.")

    extensions = raw.get("video_extensions", DEFAULT_VIDEO_EXTENSIONS)
    if not isinstance(extensions, list):
        raise ConfigError("'video_extensions' must be a list, e.g. [\".mp4\", \".mov\"].")

    auto_raw = raw.get("auto_index", {}) or {}
    auto = AutoIndexConfig(
        enabled=bool(auto_raw.get("enabled", DEFAULT_AUTO_INDEX["enabled"])),
        run_on_launch=bool(auto_raw.get("run_on_launch", DEFAULT_AUTO_INDEX["run_on_launch"])),
        interval_hours=int(auto_raw.get("interval_hours", DEFAULT_AUTO_INDEX["interval_hours"])),
    )

    val_raw = raw.get("validation", {}) or {}
    validation = ValidationConfig(
        listing_timeout_seconds=float(
            val_raw.get("listing_timeout_seconds", DEFAULT_VALIDATION["listing_timeout_seconds"])
        ),
        warn_if_empty=bool(val_raw.get("warn_if_empty", DEFAULT_VALIDATION["warn_if_empty"])),
    )

    return Config(
        footage_paths=[str(p) for p in footage_paths],
        database_path=str(raw.get("database_path", "broll_index.db")),
        video_extensions=[str(e) for e in extensions],
        auto_index=auto,
        extract_video_metadata=bool(raw.get("extract_video_metadata", True)),
        ffprobe_path=str(raw.get("ffprobe_path", "ffprobe")),
        ffmpeg_path=str(raw.get("ffmpeg_path", "ffmpeg")),
        metadata_manifest=str(raw.get("metadata_manifest", "")),
        web_port=int(raw.get("web_port", 8765)),
        preview_max_width=int(raw.get("preview_max_width", 640)),
        preview_max_seconds=int(raw.get("preview_max_seconds", 60)),
        server_footage_root=str(raw.get("server_footage_root", "")),
        network_footage_root=str(raw.get("network_footage_root", "")),
        share_token=str(raw.get("share_token", "")),
        validation=validation,
        source_path=source,
    )
