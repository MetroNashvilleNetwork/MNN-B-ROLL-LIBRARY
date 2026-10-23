"""Flask app powering the local footage gallery.

All routes are served on localhost. The browser UI calls the JSON API under
``/api`` and pulls thumbnails/previews from ``/thumb`` and ``/preview``. Opening
a file's location uses ``/api/reveal`` which runs Explorer on this same machine.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib import error as urllib_error, request as urllib_request

from flask import Flask, Response, jsonify, request, send_file, send_from_directory

from .. import __app_name__, database as db
from ..config import Config
from .. import indexer, scheduler
from .media import MediaEngine
from . import categories as cats
from . import doctor as doctor_mod
from . import git_sync_status

STATIC_DIR = Path(__file__).resolve().parent / "static"
SERVER_FOOTAGE_ROOT = r"C:\Users\SRV-ITS-MNN\OneDrive - Metro Nashville Gov\MNNPublic - 2026 Metro Nashville Archive B-Roll Footage"
NETWORK_FOOTAGE_ROOT = r"\\smb.data.nashville.org\MNNArchive\2026 Metro Nashville Archive B-Roll Footage"
MNN_CONTROL_URL = os.environ.get("MNN_CONTROL_URL", "http://127.0.0.1:4001").rstrip("/")


def _mnn_control_user():
    """Who is viewing, per MNN Control. The gallery has no sign-in of its own,
    but MNN Control's session cookie reaches every port on this host."""
    cookie = request.headers.get("Cookie")
    if not cookie:
        return None
    check = urllib_request.Request(
        MNN_CONTROL_URL + "/api/check-session",
        headers={"Cookie": cookie, "Accept": "application/json"},
    )
    try:
        with urllib_request.urlopen(check, timeout=4) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib_error.URLError, OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("authenticated"):
        return None
    return data.get("user")


def _network_path(path: str) -> str:
    norm_path = os.path.normcase(os.path.normpath(path))
    norm_root = os.path.normcase(os.path.normpath(SERVER_FOOTAGE_ROOT))
    if norm_path == norm_root:
        return NETWORK_FOOTAGE_ROOT
    if norm_path.startswith(norm_root + os.sep):
        rel = os.path.relpath(os.path.normpath(path), os.path.normpath(SERVER_FOOTAGE_ROOT))
        return os.path.normpath(os.path.join(NETWORK_FOOTAGE_ROOT, rel))
    return path


def _row_to_dict(r) -> dict:
    network_path = _network_path(r["path"])
    keys = r.keys()
    ai_desc = r["ai_description"] if "ai_description" in keys else None
    ai_tags = r["ai_tags"] if "ai_tags" in keys else None
    return {
        "id": r["id"],
        "filename": r["filename"],
        "shooter": r["shooter"],
        "month": r["month_name"],
        "shoot_date": r["shoot_date"],
        "shot_type": r["shot_type"],
        "ext": (r["extension"] or "").lstrip("."),
        "duration": r["duration_sec"],
        "width": r["width"],
        "height": r["height"],
        "size": r["size_bytes"],
        "modified": r["date_modified"],
        "folder": r["folder_path"],
        "path": r["path"],
        "network_path": network_path,
        "network_folder": os.path.dirname(network_path),
        "description": ai_desc or "",
        "tags": [t.strip() for t in (ai_tags or "").split(",") if t.strip()],
    }


class _IndexState:
    """Tracks a background re-index so the UI can show progress."""

    def __init__(self) -> None:
        self.running = False
        self.message = ""
        self.lock = threading.Lock()


def _categorized_ids(con) -> set:
    """Set of file ids that match at least one subject category.

    Reads only the full-text index. The old version pulled every matching
    file row and then stat'd each path on the footage drive.
    """
    expr = cats.all_categories_fts()
    if not expr:
        return set()
    return {r[0] for r in con.execute(
        "SELECT rowid FROM files_fts WHERE files_fts MATCH ?", (expr,))}


def create_app(config: Config, media: Optional[MediaEngine] = None, *,
               warm_thumbs: bool = True) -> Flask:
    app = Flask(__name__, static_folder=None)
    if media is None:
        media = MediaEngine(
            ffmpeg_path=config.ffmpeg_path,
            ffprobe_path=config.ffprobe_path,
            cache_dir=config.cache_dir,
            preview_max_width=config.preview_max_width,
            preview_max_seconds=config.preview_max_seconds,
        )
    index_state = _IndexState()

    # Create the schema once at startup (the only place that may write).
    db.connect(config.database_abspath, ensure=True).close()

    def get_db():
        # One *read-only* connection per request thread: ensure=False means no
        # writes, so requests never block on the indexer's write lock (WAL lets
        # readers run concurrently with a writer).
        return db.connect(config.database_abspath, ensure=False)

    def prune_missing_paths(paths) -> None:
        """Remove stale rows when the web app discovers deleted footage.

        The scheduled/full indexer is still the main source of truth, but this
        keeps the UI from showing dead cards between indexing passes.
        """
        paths = sorted({p for p in paths if p})
        if not paths:
            return
        con = db.connect(config.database_abspath, ensure=False)
        try:
            db.delete_paths(con, paths)
            con.commit()
        finally:
            con.close()

    def row_exists(row) -> bool:
        if not row:
            return False
        path = row["path"]
        return bool(path and os.path.exists(path))

    def get_existing_by_id(file_id: int):
        con = get_db()
        try:
            row = db.get_by_id(con, file_id)
        finally:
            con.close()
        if row and not row_exists(row):
            prune_missing_paths([row["path"]])
            return None
        return row

    def schedule_thumb_scan() -> None:
        """Queue posters for every indexed clip, newest first.

        This only looks at the local thumbnail cache and the SQLite index.
        It does not stat the footage drive — that walk is what made the
        gallery feel stuck, and the indexer already owns it.
        """
        def _run() -> None:
            try:
                con = db.connect(config.database_abspath, ensure=False)
                try:
                    rows = con.execute(
                        "SELECT path, mtime_ns FROM files ORDER BY date_modified DESC"
                    ).fetchall()
                finally:
                    con.close()
                media.enqueue_many((r["path"], r["mtime_ns"]) for r in rows)
            except Exception:
                return

        threading.Thread(target=_run, name="broll-thumb-scan", daemon=True).start()

    media.set_rescan(schedule_thumb_scan)
    media.start_workers()
    if warm_thumbs:
        schedule_thumb_scan()
    app.extensions["schedule_thumb_scan"] = schedule_thumb_scan

    def filters_payload(con) -> dict:
        return {
            "shooters": db.distinct_values(con, "shooter"),
            "shot_types": db.distinct_values(con, "shot_type"),
            "extensions": [e.lstrip(".") for e in db.distinct_values(con, "extension")],
            "months": db.available_months(con),
            "total": db.file_count(con),
            "last_index": db.get_meta(con, "last_index_completed_at"),
            "has_ffmpeg": media.has_ffmpeg,
            "app_name": __app_name__,
        }

    def uncategorized(con, limit: int):
        """Clips that match no subject category.

        One full-text query collects the categorized ids, then the newest
        leftovers are paged out of SQLite. Nothing here touches the footage
        drive. (MATCH inside a JOIN/NOT EXISTS is unreliable across SQLite
        builds, so the id set stays in Python — a thousand integers, not a
        thousand network stats.)
        """
        matched = _categorized_ids(con)
        total = db.file_count(con)
        count = max(0, total - len(matched))
        if count <= 0 or limit <= 0:
            return 0, []
        rows = []
        offset = 0
        while len(rows) < limit:
            chunk = db.search(con, sort="modified", limit=200, offset=offset)
            if not chunk:
                break
            for r in chunk:
                if r["id"] not in matched:
                    rows.append(r)
                    if len(rows) >= limit:
                        break
            offset += len(chunk)
        return count, rows

    def home_sections(con, limit: int = 14) -> list:
        sections = [{
            "key": "",
            "label": "Recently added",
            "count": db.file_count(con),
            "items": [_row_to_dict(r) for r in
                      db.search(con, sort="modified", limit=limit, offset=0)],
        }]
        for c in cats.CATEGORIES:
            expr = cats.category_fts(c["key"])
            if not expr:
                continue
            count = db.search_count(con, fts_expr=expr)
            if count <= 0:
                continue
            rows = db.search(con, fts_expr=expr, sort="modified", limit=limit, offset=0)
            if not rows:
                continue
            sections.append({
                "key": c["key"],
                "label": c["label"],
                "count": count,
                "items": [_row_to_dict(r) for r in rows],
            })
        ucount, urows = uncategorized(con, limit)
        if urows:
            sections.append({
                "key": cats.UNCATEGORIZED_KEY,
                "label": cats.UNCATEGORIZED_LABEL,
                "count": ucount,
                "items": [_row_to_dict(r) for r in urows],
            })
        return sections

    # -- pages ------------------------------------------------------------

    @app.route("/")
    def home():
        # The portal in front of this app caches aggressively. The HTML must
        # revalidate so a new app.js?v= query string actually reaches browsers.
        resp = send_from_directory(STATIC_DIR, "index.html", max_age=0)
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.route("/static/<path:name>")
    def static_files(name):
        return send_from_directory(STATIC_DIR, name)

    @app.route("/api/git-sync-status")
    def api_git_sync_status():
        # Feeds the admin-only "Git sync conflict" alert (static/git-sync-alert.js).
        if not git_sync_status.is_admin(_mnn_control_user()):
            return jsonify({"visible": False}), 403
        repo = os.environ.get("GIT_SYNC_REPO", "autobroll")
        return jsonify({"visible": True, **git_sync_status.load(repo)})

    # -- API --------------------------------------------------------------

    @app.route("/api/filters")
    def api_filters():
        con = get_db()
        try:
            data = filters_payload(con)
        finally:
            con.close()
        return jsonify(data)

    @app.route("/api/home")
    def api_home():
        """Front page in one response: filters plus every category row.

        The browser used to ask for categories, then for each row, and every
        one of those calls stat'd the footage files. On the OneDrive archive
        that is the multi-second (often multi-minute) pause before anything
        appears. The index is the source of truth here.
        """
        try:
            limit = max(1, min(40, int(request.args.get("limit", 14))))
        except ValueError:
            limit = 14
        con = get_db()
        try:
            payload = {
                "filters": filters_payload(con),
                "sections": home_sections(con, limit),
            }
        finally:
            con.close()
        resp = jsonify(payload)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/api/categories")
    def api_categories():
        """Subject categories that actually have footage, with a sample clip."""
        con = get_db()
        out = []
        try:
            for c in cats.CATEGORIES:
                expr = cats.category_fts(c["key"])
                if not expr:
                    continue
                count = db.search_count(con, fts_expr=expr)
                if count <= 0:
                    continue
                sample = db.search(con, fts_expr=expr, sort="modified", limit=1, offset=0)
                if not sample:
                    continue
                out.append({
                    "key": c["key"], "label": c["label"], "count": count,
                    "sample_id": sample[0]["id"],
                })
            ucount, urows = uncategorized(con, 1)
            if urows:
                out.append({
                    "key": cats.UNCATEGORIZED_KEY, "label": cats.UNCATEGORIZED_LABEL,
                    "count": ucount, "sample_id": urows[0]["id"],
                })
        finally:
            con.close()
        return jsonify({"categories": out})

    @app.route("/api/search")
    def api_search():
        q = request.args.get("q", "")
        # Filters may be comma-separated for multi-select (e.g. shooter=Gil,Tim).
        def _multi(name):
            raw = request.args.get(name) or ""
            vals = [v.strip() for v in raw.split(",") if v.strip()]
            return vals or None
        shooter = _multi("shooter")
        shot = _multi("shot")
        extensions = _multi("ext")
        category = request.args.get("category") or None
        date_from = request.args.get("from") or None
        date_to = request.args.get("to") or None
        sort = request.args.get("sort", "relevance")
        try:
            limit = max(1, min(200, int(request.args.get("limit", 60))))
            offset = max(0, int(request.args.get("offset", 0)))
        except ValueError:
            limit, offset = 60, 0

        con = get_db()
        try:
            exclude_ids = None
            if category == cats.UNCATEGORIZED_KEY:
                # 'More B-Roll' = matches no category; keep free-text + filters.
                exclude_ids = sorted(_categorized_ids(con))
                fts_expr = cats.combine_fts(q, "") if q else None
            else:
                fts_expr = cats.combine_fts(q, category or "") if (q or category) else None
            if fts_expr == "":
                fts_expr = None

            search_kwargs = {
                "query": q,
                "extensions": extensions,
                "shot_type": shot,
                "shooter": shooter,
                "date_from": date_from,
                "date_to": date_to,
                "sort": sort,
                "fts_expr": fts_expr,
                "exclude_ids": exclude_ids,
            }
            rows = db.search(con, limit=limit, offset=offset, **search_kwargs)
            total = db.search_count(con, q, extensions=extensions, shot_type=shot,
                                    shooter=shooter, date_from=date_from, date_to=date_to,
                                    fts_expr=fts_expr, exclude_ids=exclude_ids)
        finally:
            con.close()
        return jsonify({
            "total": total, "offset": offset, "limit": limit,
            "items": [_row_to_dict(r) for r in rows],
        })

    @app.route("/api/clip/<int:file_id>")
    def api_clip(file_id):
        row = get_existing_by_id(file_id)
        if not row:
            return jsonify({"error": "not found"}), 404
        d = _row_to_dict(row)
        d["has_preview"] = media.has_ffmpeg
        return jsonify(d)

    @app.route("/thumb/<int:file_id>")
    def thumb(file_id):
        # Never stat the footage file and never run ffmpeg on this request.
        # A cache hit is a local JPEG. A miss is queued (visible clips go to
        # the front) and the browser retries. A remembered failure returns the
        # placeholder immediately instead of encoding the same clip again.
        con = get_db()
        try:
            row = db.get_by_id(con, file_id)
        finally:
            con.close()
        if not row:
            return Response(status=404)
        src, mtime = row["path"], row["mtime_ns"]
        cached = media.cached_thumbnail(src, mtime)
        if cached:
            resp = send_file(
                str(cached), mimetype="image/jpeg", conditional=True,
                max_age=7 * 24 * 3600,
            )
            resp.headers["X-Thumb-State"] = "ready"
            return resp
        # Pending and failed are both empty 404s. A 200 image is only ever a
        # real JPEG, so a browser or the portal in front of this app cannot
        # cache the "Preview unavailable" card in place of the poster.
        state = "failed" if media.thumb_state(src, mtime) == "failed" else "pending"
        if state == "pending":
            media.enqueue_thumbnail(src, mtime, front=True)
        resp = Response(status=404)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Thumb-State"] = state
        return resp

    @app.route("/preview/<int:file_id>")
    def preview(file_id):
        con = get_db()
        try:
            row = db.get_by_id(con, file_id)
        finally:
            con.close()
        if not row:
            return Response(status=404)
        src, mtime = row["path"], row["mtime_ns"]
        cached = media.cached_preview(src, mtime)
        if cached:
            resp = send_file(
                str(cached), mimetype="video/mp4", conditional=True,
                max_age=7 * 24 * 3600,
            )
            resp.headers["X-Thumb-State"] = "ready"
            return resp
        # Encode in the background. The hover handler retries until the MP4
        # exists, so this request cannot sit on ffmpeg for minutes.
        media.enqueue_preview(src, mtime)
        resp = Response(status=404)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Thumb-State"] = "pending"
        return resp

    @app.route("/download/<int:file_id>")
    def download(file_id):
        row = get_existing_by_id(file_id)
        if not row:
            return Response(status=404)
        path = row["path"]
        if not path or not os.path.exists(path):
            return Response(status=404)
        return send_file(
            path,
            as_attachment=True,
            download_name=row["filename"] or os.path.basename(path),
            conditional=True,
        )

    @app.route("/api/reveal", methods=["POST"])
    def api_reveal():
        data = request.get_json(silent=True) or {}
        try:
            file_id = int(data.get("id", -1))
        except (TypeError, ValueError):
            file_id = -1
        row = get_existing_by_id(file_id)
        if not row:
            return jsonify({"ok": False, "error": "not found"}), 404
        network_path = _network_path(row["path"])
        return jsonify({
            "ok": True,
            "path": network_path,
            "folder": os.path.dirname(network_path),
        })

    @app.route("/api/status")
    def api_status():
        con = get_db()
        try:
            count = db.file_count(con)
            last = db.get_meta(con, "last_index_completed_at")
        finally:
            con.close()
        return jsonify({
            "indexing": index_state.running,
            "message": index_state.message,
            "count": count,
            "last_index": last,
        })

    @app.route("/api/doctor")
    def api_doctor():
        con = get_db()
        try:
            report = doctor_mod.build_report(config, media, con)
        finally:
            con.close()
        return jsonify(report)

    @app.route("/doctor")
    def doctor_page():
        con = get_db()
        try:
            report = doctor_mod.build_report(config, media, con)
        finally:
            con.close()
        return Response(doctor_mod.render_html(report), mimetype="text/html")

    @app.route("/api/reindex", methods=["POST"])
    def api_reindex():
        full = bool((request.get_json(silent=True) or {}).get("full"))
        with index_state.lock:
            if index_state.running:
                return jsonify({"ok": False, "error": "already running"}), 409
            index_state.running = True
            index_state.message = "Starting…"

        def worker():
            try:
                indexer.run_index(
                    config,
                    log=lambda m: setattr(index_state, "message", m),
                    full_rescan=full,
                )
            finally:
                index_state.running = False
                index_state.message = "Done"
                schedule_thumb_scan()

        threading.Thread(target=worker, daemon=True).start()
        return jsonify({"ok": True})

    return app


def _lan_ip() -> Optional[str]:
    """Best-effort local network IP of this machine (for sharing on the LAN)."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))  # no packets sent; just picks the iface
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return None


def run_web(config: Config, *, share: bool = False, port: Optional[int] = None,
            open_browser: bool = True) -> int:
    """Start the local gallery server (and open a browser tab).

    share=False  -> bind localhost only (just this computer).
    share=True   -> bind all interfaces so others on the same network (e.g. your
                    manager) can open it from their own computer.
    """
    port = port or config.web_port
    host = "0.0.0.0" if share else "127.0.0.1"
    app = create_app(config)

    if scheduler.is_index_due(config):
        def _index_then_warm() -> None:
            try:
                indexer.run_index(config)
            finally:
                scan = app.extensions.get("schedule_thumb_scan")
                if scan:
                    scan()

        threading.Thread(target=_index_then_warm, daemon=True).start()

    local_url = f"http://127.0.0.1:{port}/"
    print(f"\n{__app_name__}")
    print(f"  On this computer:        {local_url}")
    if share:
        ip = _lan_ip()
        if ip:
            print(f"  Share with your manager: http://{ip}:{port}/")
            print("  (They must be on the same MNN network. Send them that link.)")
        else:
            print("  (Could not determine this computer's network address.)")
        print("  Note: sharing exposes the gallery to your local network while this")
        print("  window stays open. Close this window to stop sharing.")
    print("  Press Ctrl+C in this window to stop.\n")

    if open_browser:
        import webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(local_url)).start()

    app.run(host=host, port=port, threaded=True, debug=False)
    return 0
