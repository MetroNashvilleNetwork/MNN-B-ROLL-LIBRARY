"""Phase 1 — SharePoint mapped-drive connection validator.

The SharePoint b-roll library is mapped into Windows as an ordinary drive
letter or UNC path (e.g. ``Z:\\B-Roll Footage`` or ``\\\\server\\share``). This
module checks, at launch, that each configured footage path is actually
reachable and warns clearly when it is not — distinguishing between:

* the drive letter not being mapped at all (SharePoint offline / not signed in),
* the specific folder being missing or renamed,
* the folder being reachable but empty (often a sign sync is still catching up),
* permission problems, and
* a hung/slow network drive that never responds.

It deliberately does **not** touch the SharePoint API — everything here is plain
filesystem access against the mapped path, with a timeout so a dead network
mount can't freeze the app.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .config import Config


class DriveStatus(Enum):
    """Outcome of validating a single footage path. ``ok`` is the only state
    that needs no user attention; ``empty`` is a soft warning; the rest are
    hard errors that block indexing for that path."""

    OK = "ok"
    NOT_CONFIGURED = "not_configured"
    DRIVE_OFFLINE = "drive_offline"
    PATH_MISSING = "path_missing"
    NOT_A_DIRECTORY = "not_a_directory"
    PERMISSION_DENIED = "permission_denied"
    EMPTY = "empty"
    TIMEOUT = "timeout"
    ERROR = "error"

    @property
    def is_ok(self) -> bool:
        return self is DriveStatus.OK

    @property
    def is_warning(self) -> bool:
        return self is DriveStatus.EMPTY

    @property
    def is_error(self) -> bool:
        return not self.is_ok and not self.is_warning


@dataclass
class PathResult:
    """Result of validating one configured footage path."""

    path: str
    status: DriveStatus
    message: str
    drive_root: str | None = None
    entry_count: int | None = None

    @property
    def ok(self) -> bool:
        return self.status.is_ok

    def label(self) -> str:
        if self.status.is_ok:
            return "OK"
        if self.status.is_warning:
            return "WARNING"
        return "ERROR"


@dataclass
class ValidationReport:
    """Aggregate result across all configured footage paths."""

    results: list[PathResult] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return bool(self.results) and all(r.status.is_ok for r in self.results)

    @property
    def any_usable(self) -> bool:
        """True if at least one path can actually be indexed (OK or just empty)."""
        return any(r.status.is_ok or r.status.is_warning for r in self.results)

    @property
    def errors(self) -> list[PathResult]:
        return [r for r in self.results if r.status.is_error]

    @property
    def warnings(self) -> list[PathResult]:
        return [r for r in self.results if r.status.is_warning]

    def usable_paths(self) -> list[str]:
        return [r.path for r in self.results if r.status.is_ok or r.status.is_warning]

    def summary_line(self) -> str:
        if not self.results:
            return "No footage paths configured."
        ok = sum(1 for r in self.results if r.status.is_ok)
        warn = len(self.warnings)
        err = len(self.errors)
        parts = [f"{ok} OK"]
        if warn:
            parts.append(f"{warn} warning(s)")
        if err:
            parts.append(f"{err} error(s)")
        return f"{len(self.results)} path(s): " + ", ".join(parts)


# --- Low-level checks -----------------------------------------------------


def _drive_root(path: Path) -> str | None:
    """Return the drive/anchor that must be mounted for ``path`` to resolve.

    For ``Z:\\B-Roll`` -> ``Z:\\``; for a UNC ``\\\\server\\share\\x`` -> the
    ``\\\\server\\share`` anchor. Returns None if it can't be determined.
    """
    anchor = path.anchor
    return anchor or None


def _drive_is_mounted(path: Path) -> bool:
    """Is the underlying drive letter / UNC share present at all?"""
    root = _drive_root(path)
    if not root:
        # Relative path — treat the current working directory as 'mounted'.
        return True
    try:
        return os.path.exists(root)
    except OSError:
        return False


def _list_with_timeout(path: Path, timeout: float) -> tuple[int | None, BaseException | None]:
    """Count entries in ``path``, aborting if it takes longer than ``timeout``.

    A dead or very slow network mount can make ``os.scandir`` hang; running it
    on a worker thread lets us give up instead of freezing the whole app.
    Returns ``(entry_count, exception)`` — exactly one of the two is set.
    """

    def _count() -> int:
        count = 0
        with os.scandir(path) as it:
            for _ in it:
                count += 1
                # We only need to know "is there anything here"; stop early so a
                # huge library doesn't make the launch check slow.
                if count >= 1:
                    break
        return count

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_count)
        try:
            return future.result(timeout=timeout), None
        except FuturesTimeout:
            return None, FuturesTimeout()
        except BaseException as exc:  # noqa: BLE001 - report any access error
            return None, exc


# --- Public API -----------------------------------------------------------


def validate_path(raw_path: str, timeout: float = 10.0, warn_if_empty: bool = True) -> PathResult:
    """Validate a single configured footage path against the mapped drive."""
    if not raw_path or not raw_path.strip():
        return PathResult(raw_path, DriveStatus.NOT_CONFIGURED,
                          "No path provided.")

    path = Path(raw_path.strip())
    root = _drive_root(path)

    # 1) Is the drive letter / UNC share mounted at all?
    if not _drive_is_mounted(path):
        return PathResult(
            raw_path, DriveStatus.DRIVE_OFFLINE,
            f"Drive '{root or path}' is not available. The SharePoint mapping "
            f"may be offline, disconnected, or you may not be signed in. Open "
            f"File Explorer and confirm the drive is connected.",
            drive_root=root,
        )

    # 2) Does the specific folder exist?
    try:
        exists = path.exists()
    except OSError as exc:
        return PathResult(
            raw_path, DriveStatus.ERROR,
            f"Could not access '{path}': {exc}", drive_root=root,
        )
    if not exists:
        return PathResult(
            raw_path, DriveStatus.PATH_MISSING,
            f"The folder '{path}' was not found, even though drive '{root}' is "
            f"connected. It may have been moved or renamed, or SharePoint sync "
            f"has not created it locally yet.",
            drive_root=root,
        )

    # 3) Is it actually a directory?
    if not path.is_dir():
        return PathResult(
            raw_path, DriveStatus.NOT_A_DIRECTORY,
            f"'{path}' exists but is not a folder. footage_paths must point to "
            f"folders, not individual files.",
            drive_root=root,
        )

    # 4) Can we list it (within the timeout)?
    count, error = _list_with_timeout(path, timeout)
    if error is not None:
        if isinstance(error, FuturesTimeout):
            return PathResult(
                raw_path, DriveStatus.TIMEOUT,
                f"'{path}' did not respond within {timeout:g}s. The network "
                f"drive may be slow, reconnecting, or SharePoint may be busy "
                f"syncing. Try again in a moment.",
                drive_root=root,
            )
        if isinstance(error, PermissionError):
            return PathResult(
                raw_path, DriveStatus.PERMISSION_DENIED,
                f"Access to '{path}' was denied. Check that your Windows "
                f"account has permission to this SharePoint library.",
                drive_root=root,
            )
        return PathResult(
            raw_path, DriveStatus.ERROR,
            f"Could not read '{path}': {error}", drive_root=root,
        )

    # 5) Reachable. Empty is a soft warning (often sync still catching up).
    if warn_if_empty and count == 0:
        return PathResult(
            raw_path, DriveStatus.EMPTY,
            f"'{path}' is reachable but appears to be empty. If you expect "
            f"footage here, SharePoint sync may still be downloading files.",
            drive_root=root, entry_count=0,
        )

    return PathResult(
        raw_path, DriveStatus.OK,
        f"Connected: '{path}' is reachable.",
        drive_root=root, entry_count=count,
    )


def validate_config(config: Config) -> ValidationReport:
    """Validate every footage path in the configuration.

    Placeholder/example paths left in the config are surfaced as
    NOT_CONFIGURED so first-time users get an actionable message instead of a
    confusing 'drive offline'.
    """
    report = ValidationReport()
    timeout = config.validation.listing_timeout_seconds
    warn_if_empty = config.validation.warn_if_empty

    raw_paths = [p for p in config.footage_paths if p and p.strip()]

    if not raw_paths:
        report.results.append(PathResult(
            "", DriveStatus.NOT_CONFIGURED,
            "No footage paths configured. Edit config.json and set "
            "'footage_paths' to your mapped SharePoint folder, e.g. "
            "\"Z:/B-Roll Footage\".",
        ))
        return report

    from .config import _looks_like_placeholder  # local import to avoid cycle

    for raw in raw_paths:
        if _looks_like_placeholder(raw):
            report.results.append(PathResult(
                raw, DriveStatus.NOT_CONFIGURED,
                f"'{raw}' looks like the example placeholder. Edit config.json "
                f"and set 'footage_paths' to your real mapped SharePoint folder.",
            ))
            continue
        report.results.append(validate_path(raw, timeout=timeout, warn_if_empty=warn_if_empty))

    return report


def format_report(report: ValidationReport) -> str:
    """Render a human-readable multi-line report for console / status display."""
    lines = ["B-Roll drive connection check", "=" * 32]
    if not report.results:
        lines.append("No footage paths configured.")
        return "\n".join(lines)
    for r in report.results:
        lines.append(f"[{r.label():^7}] {r.path or '(empty)'}")
        lines.append(f"          {r.message}")
    lines.append("-" * 32)
    lines.append(report.summary_line())
    return "\n".join(lines)
