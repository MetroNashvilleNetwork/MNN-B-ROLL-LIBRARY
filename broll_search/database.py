"""Phase 2 — SQLite index: schema, upserts, search, and stats.

One row per b-roll file. Full-text search is provided by an FTS5 virtual table
kept in sync with the ``files`` table via triggers, so searches over filename /
keywords / folder / shooter are fast even on large libraries.

Searchable/derived columns explained:
* ``shooter``      — top-level folder under the footage root (Aaron, Gil, …).
* ``month_name``   — the month subfolder name (e.g. "July"), if present.
* ``shoot_year`` / ``shoot_month`` — derived shoot date (year from the footage
  root folder name, month from the month subfolder). ``shoot_date`` is the
  ISO ``YYYY-MM-01`` form for easy month-level range filtering.
* ``shot_type``    — detected from the filename (Closeup, Wide, Medium, …).
* ``keywords``     — filename split into individual words for keyword search.
* ``size_bytes`` + ``mtime_ns`` — used for incremental indexing (skip unchanged).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Optional

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id            INTEGER PRIMARY KEY,
    path          TEXT UNIQUE NOT NULL,
    root          TEXT NOT NULL,
    relative_path TEXT,
    filename      TEXT NOT NULL,
    extension     TEXT,
    shooter       TEXT,
    month_name    TEXT,
    shoot_year    INTEGER,
    shoot_month   INTEGER,
    shoot_date    TEXT,
    shot_type     TEXT,
    parent_folder TEXT,
    folder_path   TEXT,
    keywords      TEXT,
    size_bytes    INTEGER,
    mtime_ns      INTEGER,
    date_created  TEXT,
    date_modified TEXT,
    duration_sec  REAL,
    width         INTEGER,
    height        INTEGER,
    codec         TEXT,
    indexed_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_files_root        ON files(root);
CREATE INDEX IF NOT EXISTS idx_files_extension   ON files(extension);
CREATE INDEX IF NOT EXISTS idx_files_shot_type   ON files(shot_type);
CREATE INDEX IF NOT EXISTS idx_files_shooter     ON files(shooter);
CREATE INDEX IF NOT EXISTS idx_files_shoot_date  ON files(shoot_date);
CREATE INDEX IF NOT EXISTS idx_files_modified    ON files(date_modified);

-- Full-text search mirror (external-content FTS5 over the files table).
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    filename, keywords, folder_path, shooter, shot_type,
    content='files', content_rowid='id'
);

-- Keep the FTS index in sync with the files table automatically.
CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, filename, keywords, folder_path, shooter, shot_type)
    VALUES (new.id, new.filename, new.keywords, new.folder_path, new.shooter, new.shot_type);
END;
CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, filename, keywords, folder_path, shooter, shot_type)
    VALUES ('delete', old.id, old.filename, old.keywords, old.folder_path, old.shooter, old.shot_type);
END;
CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, filename, keywords, folder_path, shooter, shot_type)
    VALUES ('delete', old.id, old.filename, old.keywords, old.folder_path, old.shooter, old.shot_type);
    INSERT INTO files_fts(rowid, filename, keywords, folder_path, shooter, shot_type)
    VALUES (new.id, new.filename, new.keywords, new.folder_path, new.shooter, new.shot_type);
END;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# Columns accepted by upsert_file (everything except the autoincrement id).
_FILE_COLUMNS = [
    "path", "root", "relative_path", "filename", "extension", "shooter",
    "month_name", "shoot_year", "shoot_month", "shoot_date", "shot_type",
    "parent_folder", "folder_path", "keywords", "size_bytes", "mtime_ns",
    "date_created", "date_modified", "duration_sec", "width", "height",
    "codec", "indexed_at",
]


def connect(db_path: Path | str, *, ensure: bool = True) -> sqlite3.Connection:
    """Open the index database.

    ``ensure=True`` creates the schema if needed (use at startup / for writers).
    ``ensure=False`` skips all schema work and performs **no writes** — use for
    per-request read connections in the web server, so that read traffic never
    contends for the write lock while an indexing pass is running (WAL lets
    readers proceed concurrently with a writer, but only if they don't write).
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path), timeout=10)
    con.row_factory = sqlite3.Row
    # Wait (up to 10s) for a lock instead of erroring immediately.
    con.execute("PRAGMA busy_timeout=10000;")
    con.execute("PRAGMA foreign_keys=ON;")
    if ensure:
        init_db(con)
    return con


def init_db(con: sqlite3.Connection) -> None:
    """Create tables/indexes/triggers if they do not exist (idempotent).

    Only writes when something is actually missing, so calling it repeatedly is
    cheap and doesn't needlessly grab the write lock."""
    con.executescript(_SCHEMA)  # every statement is CREATE ... IF NOT EXISTS
    con.execute("PRAGMA journal_mode=WAL;")
    if con.execute("SELECT 1 FROM meta WHERE key='schema_version'").fetchone() is None:
        set_meta(con, "schema_version", str(SCHEMA_VERSION))
    con.commit()


@contextmanager
def transaction(con: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise


# --- Meta key/value -------------------------------------------------------


def set_meta(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_meta(con: sqlite3.Connection, key: str, default: Optional[str] = None) -> Optional[str]:
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


# --- File rows ------------------------------------------------------------


def get_existing_fingerprint(con: sqlite3.Connection, path: str) -> Optional[tuple[int, int]]:
    """Return (size_bytes, mtime_ns) for an indexed file, or None if new.

    Used for incremental indexing: if these match the file on disk, the row is
    up to date and can be skipped without re-reading metadata.
    """
    row = con.execute(
        "SELECT size_bytes, mtime_ns FROM files WHERE path=?", (path,)
    ).fetchone()
    if row is None:
        return None
    return (row["size_bytes"], row["mtime_ns"])


def upsert_file(con: sqlite3.Connection, record: dict) -> None:
    """Insert or update a file row keyed on its path."""
    cols = ", ".join(_FILE_COLUMNS)
    placeholders = ", ".join(f":{c}" for c in _FILE_COLUMNS)
    updates = ", ".join(f"{c}=excluded.{c}" for c in _FILE_COLUMNS if c != "path")
    values = {c: record.get(c) for c in _FILE_COLUMNS}
    con.execute(
        f"INSERT INTO files ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT(path) DO UPDATE SET {updates}",
        values,
    )


def all_paths_for_root(con: sqlite3.Connection, root: str) -> set[str]:
    rows = con.execute("SELECT path FROM files WHERE root=?", (root,)).fetchall()
    return {r["path"] for r in rows}


def delete_paths(con: sqlite3.Connection, paths: Iterable[str]) -> int:
    paths = list(paths)
    if not paths:
        return 0
    con.executemany("DELETE FROM files WHERE path=?", [(p,) for p in paths])
    return len(paths)


# --- Stats ----------------------------------------------------------------


def file_count(con: sqlite3.Connection) -> int:
    return con.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"]


def distinct_values(con: sqlite3.Connection, column: str) -> list[str]:
    """Distinct non-null values for a column (for populating UI filters)."""
    if column not in {"extension", "shot_type", "shooter", "month_name"}:
        raise ValueError(f"Refusing to query unknown column: {column}")
    rows = con.execute(
        f"SELECT DISTINCT {column} AS v FROM files "
        f"WHERE {column} IS NOT NULL AND {column} != '' ORDER BY {column}"
    ).fetchall()
    return [r["v"] for r in rows]


# --- Search ---------------------------------------------------------------

_SORT_COLUMNS = {
    "filename": "f.filename",
    "modified": "f.date_modified",
    "created": "f.date_created",
    "shoot_date": "f.shoot_date",
    "size": "f.size_bytes",
    "shooter": "f.shooter",
    "relevance": "rank",  # only meaningful when a text query is present
}


def _build_fts_query(text: str) -> str:
    """Turn a plain user query into a safe FTS5 MATCH expression.

    Each whitespace-separated word becomes a prefix term (``word*``) and all
    terms are AND-ed, so "blodgett oven" matches files containing both. Quotes
    and other FTS operators in user input are stripped to avoid syntax errors.
    """
    cleaned = []
    for tok in text.replace('"', " ").replace("-", " ").split():
        # Keep alphanumerics; drop characters FTS would treat as operators.
        safe = "".join(ch for ch in tok if ch.isalnum())
        if safe:
            cleaned.append(f"{safe}*")
    return " AND ".join(cleaned)


def _build_where(
    query: str,
    extensions: Optional[list[str]],
    shot_type: Optional[str],
    shooter: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    fts_expr: Optional[str] = None,
) -> tuple[str, str, list]:
    """Return (joins, where_sql, params) shared by search() and search_count().

    ``fts_expr``: a ready-made FTS5 MATCH expression (used for category OR
    queries). When given it overrides the plain-text ``query`` building."""
    params: list = []
    where: list[str] = []
    joins = ""

    if fts_expr is not None:
        fts_query = fts_expr.strip()
    else:
        fts_query = _build_fts_query(query) if query and query.strip() else ""
    if fts_query:
        joins = "JOIN files_fts ON files_fts.rowid = f.id"
        where.append("files_fts MATCH ?")
        params.append(fts_query)

    if extensions:
        norm = []
        for e in extensions:
            e = e.strip().lower()
            if e and not e.startswith("."):
                e = "." + e
            if e:
                norm.append(e)
        if norm:
            where.append(f"f.extension IN ({', '.join('?' for _ in norm)})")
            params.extend(norm)

    if shot_type:
        where.append("f.shot_type = ?")
        params.append(shot_type)
    if shooter:
        where.append("f.shooter = ?")
        params.append(shooter)
    if date_from:
        where.append("f.shoot_date >= ?")
        params.append(date_from)
    if date_to:
        where.append("f.shoot_date <= ?")
        params.append(date_to)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    return joins, where_sql, params


def search(
    con: sqlite3.Connection,
    query: str = "",
    *,
    extensions: Optional[list[str]] = None,
    shot_type: Optional[str] = None,
    shooter: Optional[str] = None,
    date_from: Optional[str] = None,   # ISO 'YYYY-MM-DD' against shoot_date
    date_to: Optional[str] = None,
    sort: str = "relevance",
    descending: bool = True,
    limit: int = 1000,
    offset: int = 0,
    fts_expr: Optional[str] = None,
) -> list[sqlite3.Row]:
    """Search the index. All arguments are optional; with no query and no
    filters it returns the most recent files."""
    joins, where_sql, params = _build_where(
        query, extensions, shot_type, shooter, date_from, date_to, fts_expr)
    has_fts = "files_fts" in joins

    # Pick sort. Relevance only works with an FTS query; otherwise fall back.
    sort_key = sort if sort in _SORT_COLUMNS else "relevance"
    if sort_key == "relevance" and not has_fts:
        sort_key = "modified"
    order_col = _SORT_COLUMNS[sort_key]
    order_dir = "ASC" if sort_key == "relevance" else ("DESC" if descending else "ASC")

    sql = (
        f"SELECT f.* FROM files f {joins} {where_sql} "
        f"ORDER BY {order_col} {order_dir} LIMIT ? OFFSET ?"
    )
    params.extend([int(limit), int(offset)])
    return con.execute(sql, params).fetchall()


def search_count(
    con: sqlite3.Connection,
    query: str = "",
    *,
    extensions: Optional[list[str]] = None,
    shot_type: Optional[str] = None,
    shooter: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    fts_expr: Optional[str] = None,
) -> int:
    """Total number of files matching a search (ignoring limit/offset)."""
    joins, where_sql, params = _build_where(
        query, extensions, shot_type, shooter, date_from, date_to, fts_expr)
    sql = f"SELECT COUNT(*) AS n FROM files f {joins} {where_sql}"
    return con.execute(sql, params).fetchone()["n"]


def get_by_id(con: sqlite3.Connection, file_id: int) -> Optional[sqlite3.Row]:
    return con.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()


def available_months(con: sqlite3.Connection) -> list[dict]:
    """Distinct shoot months for filter UI: [{label:'2026-07', date:'2026-07-01'}]."""
    rows = con.execute(
        "SELECT DISTINCT shoot_year, shoot_month, shoot_date FROM files "
        "WHERE shoot_date IS NOT NULL ORDER BY shoot_date"
    ).fetchall()
    return [
        {"label": f"{r['shoot_year']:04d}-{r['shoot_month']:02d}",
         "date": r["shoot_date"]}
        for r in rows
    ]
