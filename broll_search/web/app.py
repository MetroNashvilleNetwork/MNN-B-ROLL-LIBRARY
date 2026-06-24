"""Flask app powering the local footage gallery.

All routes are served on localhost. The browser UI calls the JSON API under
``/api`` and pulls thumbnails/previews from ``/thumb`` and ``/preview``. Opening
a file's location uses ``/api/reveal`` which runs Explorer on this same machine.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import Flask, Response, g, jsonify, request, send_file, send_from_directory

from .. import __app_name__, database as db
from ..config import Config
from .. import indexer, scheduler
from .media import MediaEngine
from . import categories as cats
from . import doctor as doctor_mod

STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_SERVER_FOOTAGE_ROOT = (
    r"C:\Users\SRV-ITS-MNN\OneDrive - Metro Nashville Gov"
    r"\MNNPublic - 2026 Metro Nashville Archive B-Roll Footage"
)
DEFAULT_NETWORK_FOOTAGE_ROOT = (
    r"\\smb.data.nashville.org\MNNArchive\2026 Metro Nashville Archive B-Roll Footage"
)


def _network_path(path: str, config: Config) -> str:
    server_root = (getattr(config, "server_footage_root", None)
                   or DEFAULT_SERVER_FOOTAGE_ROOT)
    network_root = (getattr(config, "network_footage_root", None)
                    or DEFAULT_NETWORK_FOOTAGE_ROOT)
    if server_root:
        server_root = str(server_root)
    if network_root:
        network_root = str(network_root)
    norm_path = os.path.normcase(os.path.normpath(path))
    norm_root = os.path.normcase(os.path.normpath(server_root))
    if norm_path == norm_root:
        return network_root
    if norm_path.startswith(norm_root + os.sep):
        rel = os.path.relpath(os.path.normpath(path), os.path.normpath(server_root))
        return os.path.normpath(os.path.join(network_root, rel))
    return path


def _row_to_dict(r, config: Config) -> dict:
    network_path = _network_path(r["path"], config)
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


def _set_index_state(index_state: _IndexState, *, running: bool | None = None,
                     message: str | None = None) -> None:
    with index_state.lock:
        if running is not None:
            index_state.running = running
        if message is not None:
            index_state.message = message


def _categorized_ids(con) -> set:
    """Set of file ids that match at least one subject category."""
    expr = cats.all_categories_fts()
    if not expr:
        return set()
    return {r["id"] for r in db.search(con, fts_expr=expr, limit=100000)}


def _footage_path_ok(config: Config, path: str) -> bool:
    """Only serve files that live under configured footage roots."""
    return config.is_path_under_footage_roots(path)


def create_app(config: Config) -> Flask:
    app = Flask(__name__, static_folder=None)
    media = MediaEngine(
        ffmpeg_path=config.ffmpeg_path,
        ffprobe_path=config.ffprobe_path,
        cache_dir=config.cache_dir,
        preview_max_width=config.preview_max_width,
        preview_max_seconds=config.preview_max_seconds,
    )
    index_state = _IndexState()

    @app.before_request
    def _lan_share_guard():
        if not app.config.get("LAN_SHARE"):
            return None
        token = (app.config.get("SHARE_TOKEN") or "").strip()
        if not token:
            return None
        remote = request.remote_addr or ""
        if remote in ("127.0.0.1", "::1"):
            return None
        if request.cookies.get("broll_share") == token:
            return None
        if request.args.get("token") == token:
            g.share_set_cookie = True
            return None
        return Response(
            "Unauthorized. Open the gallery using the shared link that includes ?token=…",
            status=401,
            mimetype="text/plain",
        )

    @app.after_request
    def _share_set_cookie(resp):
        if getattr(g, "share_set_cookie", False):
            token = (app.config.get("SHARE_TOKEN") or "").strip()
            if token:
                resp.set_cookie(
                    "broll_share", token, httponly=True, samesite="Lax", max_age=86400 * 30)
        return resp

    # Create the schema once at startup (the only place that may write).
    db.connect(config.database_abspath, ensure=True).close()

    def get_db():
        # One *read-only* connection per request thread: ensure=False means no
        # writes, so requests never block on the indexer's write lock (WAL lets
        # readers run concurrently with a writer).
        return db.connect(config.database_abspath, ensure=False)

    # -- pages ------------------------------------------------------------

    @app.route("/")
    def home():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.route("/static/<path:name>")
    def static_files(name):
        return send_from_directory(STATIC_DIR, name)

    # -- API --------------------------------------------------------------

    @app.route("/api/filters")
    def api_filters():
        con = get_db()
        try:
            data = {
                "shooters": db.distinct_values(con, "shooter"),
                "shot_types": db.distinct_values(con, "shot_type"),
                "extensions": [e.lstrip(".") for e in db.distinct_values(con, "extension")],
                "months": db.available_months(con),
                "total": db.file_count(con),
                "last_index": db.get_meta(con, "last_index_completed_at"),
                "has_ffmpeg": media.has_ffmpeg,
                "app_name": __app_name__,
            }
        finally:
            con.close()
        return jsonify(data)

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
                sample = db.search(con, fts_expr=expr, sort="modified", limit=1)
                out.append({
                    "key": c["key"], "label": c["label"], "count": count,
                    "sample_id": sample[0]["id"] if sample else None,
                })
            # Catch-all: clips that match no category at all ("More B-Roll").
            categorized = _categorized_ids(con)
            if categorized:
                exclude = sorted(categorized)
                uncat_count = db.search_count(con, exclude_ids=exclude)
                if uncat_count:
                    sample = db.search(con, exclude_ids=exclude, sort="modified", limit=1)
                    out.append({
                        "key": cats.UNCATEGORIZED_KEY,
                        "label": cats.UNCATEGORIZED_LABEL,
                        "count": uncat_count,
                        "sample_id": sample[0]["id"] if sample else None,
                    })
            else:
                total = db.file_count(con)
                if total:
                    sample = db.search(con, sort="modified", limit=1)
                    out.append({
                        "key": cats.UNCATEGORIZED_KEY,
                        "label": cats.UNCATEGORIZED_LABEL,
                        "count": total,
                        "sample_id": sample[0]["id"] if sample else None,
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

            rows = db.search(con, q, extensions=extensions, shot_type=shot,
                             shooter=shooter, date_from=date_from, date_to=date_to,
                             sort=sort, limit=limit, offset=offset,
                             fts_expr=fts_expr, exclude_ids=exclude_ids)
            total = db.search_count(con, q, extensions=extensions, shot_type=shot,
                                    shooter=shooter, date_from=date_from, date_to=date_to,
                                    fts_expr=fts_expr, exclude_ids=exclude_ids)
        finally:
            con.close()
        return jsonify({
            "total": total, "offset": offset, "limit": limit,
            "items": [_row_to_dict(r, config) for r in rows],
        })

    @app.route("/api/clip/<int:file_id>")
    def api_clip(file_id):
        con = get_db()
        try:
            row = db.get_by_id(con, file_id)
        finally:
            con.close()
        if not row:
            return jsonify({"error": "not found"}), 404
        d = _row_to_dict(row, config)
        d["has_preview"] = media.has_ffmpeg
        return jsonify(d)

    @app.route("/thumb/<int:file_id>")
    def thumb(file_id):
        con = get_db()
        try:
            row = db.get_by_id(con, file_id)
        finally:
            con.close()
        if not row:
            return Response(status=404)
        if not _footage_path_ok(config, row["path"]):
            return Response(status=403)
        p = media.thumbnail_path(row["path"], row["mtime_ns"])
        if p and p.exists():
            return send_file(str(p), mimetype="image/jpeg", conditional=True)
        # Fallback placeholder card.
        sub = " · ".join(x for x in [row["shooter"], row["month_name"],
                                     row["shot_type"]] if x)
        svg = media.placeholder_svg(row["filename"], sub)
        return Response(svg, mimetype="image/svg+xml")

    @app.route("/preview/<int:file_id>")
    def preview(file_id):
        con = get_db()
        try:
            row = db.get_by_id(con, file_id)
        finally:
            con.close()
        if not row:
            return Response(status=404)
        if not _footage_path_ok(config, row["path"]):
            return Response(status=403)
        p = media.preview_path(row["path"], row["mtime_ns"])
        if p and p.exists():
            return send_file(str(p), mimetype="video/mp4", conditional=True)
        return Response(status=404)

    @app.route("/download/<int:file_id>")
    def download(file_id):
        con = get_db()
        try:
            row = db.get_by_id(con, file_id)
        finally:
            con.close()
        if not row:
            return Response(status=404)
        path = row["path"]
        if not path or not os.path.exists(path):
            return Response(status=404)
        if not _footage_path_ok(config, path):
            return Response(status=403)
        return send_file(
            path,
            as_attachment=True,
            download_name=row["filename"] or os.path.basename(path),
            conditional=True,
        )

    @app.route("/api/reveal", methods=["POST"])
    def api_reveal():
        data = request.get_json(silent=True) or {}
        con = get_db()
        try:
            row = db.get_by_id(con, int(data.get("id", -1)))
        finally:
            con.close()
        if not row:
            return jsonify({"ok": False, "error": "not found"}), 404
        network_path = _network_path(row["path"], config)
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
        with index_state.lock:
            indexing = index_state.running
            message = index_state.message
        return jsonify({
            "indexing": indexing,
            "message": message,
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
                result = indexer.run_index(
                    config,
                    log=lambda m: _set_index_state(index_state, message=m),
                    full_rescan=full,
                )
                if result.skipped_duplicate:
                    _set_index_state(index_state, message="Skipped (index already running)")
                else:
                    _set_index_state(index_state, message="Done")
            finally:
                _set_index_state(index_state, running=False)

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
    app.config["LAN_SHARE"] = share
    app.config["SHARE_TOKEN"] = (config.share_token or "").strip()

    if scheduler.is_index_due(config):
        threading.Thread(
            target=lambda: indexer.run_index(
                config, log=lambda m: print(f"  [index] {m}")),
            daemon=True,
        ).start()

    local_url = f"http://127.0.0.1:{port}/"
    print(f"\n{__app_name__}")
    print(f"  On this computer:        {local_url}")
    if share:
        ip = _lan_ip()
        if ip:
            lan_url = f"http://{ip}:{port}/"
            if app.config["SHARE_TOKEN"]:
                lan_url += f"?token={app.config['SHARE_TOKEN']}"
            print(f"  Share with your manager: {lan_url}")
            print("  (They must be on the same MNN network. Send them that link.)")
        else:
            print("  (Could not determine this computer's network address.)")
        if not app.config["SHARE_TOKEN"]:
            print("  Security note: anyone on the LAN can browse while this is running.")
            print("  Set \"share_token\" in config.json to require ?token= for remote viewers.")
        print("  Close this window to stop sharing.")
    print("  Press Ctrl+C in this window to stop.\n")

    if open_browser:
        import webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(local_url)).start()

    app.run(host=host, port=port, threaded=True, debug=False)
    return 0
