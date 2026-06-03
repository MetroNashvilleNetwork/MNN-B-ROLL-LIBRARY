"""Phase 2 — daily auto-index trigger.

Lightweight, dependency-free scheduling: the index records when it last
completed, and these helpers decide whether enough time has passed to re-index.
The UI calls :func:`maybe_index_on_launch` at startup and also backs the manual
"Re-index Now" button via :func:`indexer.run_index`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Optional

from . import database as db
from . import indexer
from .config import Config


def last_index_time(config: Config) -> Optional[datetime]:
    """When indexing last completed, or None if it never has."""
    try:
        con = db.connect(config.database_abspath)
    except Exception:
        return None
    try:
        raw = db.get_meta(con, "last_index_completed_at")
    finally:
        con.close()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def indexed_file_count(config: Config) -> int:
    try:
        con = db.connect(config.database_abspath)
    except Exception:
        return 0
    try:
        return db.file_count(con)
    finally:
        con.close()


def is_index_due(config: Config, now: Optional[datetime] = None) -> bool:
    """True if no index exists yet, or the configured interval has elapsed."""
    if not config.auto_index.enabled:
        return False
    last = last_index_time(config)
    if last is None:
        return True
    now = now or datetime.now()
    interval = timedelta(hours=max(1, config.auto_index.interval_hours))
    return (now - last) >= interval


def maybe_index_on_launch(
    config: Config,
    *,
    progress: Optional[Callable[[int, Optional[int], str], None]] = None,
    log: Optional[Callable[[str], None]] = None,
    force: bool = False,
) -> Optional[indexer.IndexResult]:
    """Run a re-index at startup if one is due (or forced). Returns the result,
    or None if nothing ran."""
    if not force:
        if not config.auto_index.enabled or not config.auto_index.run_on_launch:
            return None
        if not is_index_due(config):
            return None
    return indexer.run_index(config, progress=progress, log=log)
