"""Self-diagnostics for the footage gallery.

The app often runs on a server we can't open a terminal on (it auto-syncs code
from GitHub and we only reach it through the browser). When thumbnails or
previews won't generate for some footage, we need to see *why* from the server's
own point of view: is ffmpeg present and HEVC-capable? Can the server actually
read the (possibly OneDrive online-only / network) source file, and how fast?
Does a real thumbnail attempt succeed, and if not, what does ffmpeg say?

``/doctor`` renders this as a readable page; ``/api/doctor`` returns the raw
JSON. Nothing here writes to the index; the only side effect is that a couple of
sample thumbnails may get generated (which is harmless — it just warms the
cache).
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from .. import database as db
from .media import MediaEngine, _hidden_kwargs

# Bump this string on every push that touches the server so we can confirm, from
# the browser, that the server actually pulled the latest code. If /doctor shows
# an old marker, the GitHub sync is behind and no code fix will take effect.
BUILD_MARKER = "2026-06-08 doctor-v1 + 10-bit-preview-fix"


def _run_capture(cmd: list, timeout: float) -> dict:
    """Run a command, capturing rc / stdout / stderr / elapsed seconds."""
    t0 = time.monotonic()
    try:
        proc = subprocess.run(cmd, timeout=timeout, **_hidden_kwargs())
        return {
            "rc": proc.returncode,
            "stdout": (proc.stdout or b"").decode("utf-8", "replace"),
            "stderr": (proc.stderr or b"").decode("utf-8", "replace"),
            "elapsed": round(time.monotonic() - t0, 2),
            "error": None,
        }
    except subprocess.TimeoutExpired:
        return {"rc": None, "stdout": "", "stderr": "", "elapsed": round(time.monotonic() - t0, 2),
                "error": f"TIMEOUT after {timeout}s"}
    except OSError as exc:
        return {"rc": None, "stdout": "", "stderr": "", "elapsed": round(time.monotonic() - t0, 2),
                "error": f"{type(exc).__name__}: {exc}"}


def _tool_report(label: str, resolved: Optional[str]) -> dict:
    info: dict = {"name": label, "resolved_path": resolved, "found": bool(resolved)}
    if not resolved:
        return info
    ver = _run_capture([resolved, "-hide_banner", "-version"], timeout=15)
    info["version"] = (ver["stdout"] or ver["stderr"]).splitlines()[:1]
    if label == "ffmpeg":
        dec = _run_capture([resolved, "-hide_banner", "-decoders"], timeout=15)
        blob = dec["stdout"] + dec["stderr"]
        info["can_decode_hevc"] = (" hevc" in blob) or ("HEVC" in blob)
        info["can_decode_h264"] = (" h264" in blob)
        enc = _run_capture([resolved, "-hide_banner", "-encoders"], timeout=15)
        info["has_libx264"] = "libx264" in (enc["stdout"] + enc["stderr"])
    return info


def _git_head(repo_dir: Path) -> dict:
    """Best-effort: which commit is actually checked out on this server."""
    out = _run_capture(["git", "-C", str(repo_dir), "rev-parse", "--short", "HEAD"], timeout=10)
    head = (out["stdout"] or "").strip() or None
    sub = _run_capture(["git", "-C", str(repo_dir), "log", "-1", "--format=%s",
                        "--no-color"], timeout=10)
    return {"commit": head, "subject": (sub["stdout"] or "").strip() or None,
            "error": out["error"]}


def _read_test(path: str, nbytes: int = 1_000_000) -> dict:
    """Time reading the first chunk — slow/failed reads flag OneDrive online-only
    or a flaky network share."""
    t0 = time.monotonic()
    try:
        with open(path, "rb") as fh:
            data = fh.read(nbytes)
        return {"ok": True, "bytes_read": len(data),
                "elapsed": round(time.monotonic() - t0, 3), "error": None}
    except OSError as exc:
        return {"ok": False, "bytes_read": 0,
                "elapsed": round(time.monotonic() - t0, 3),
                "error": f"{type(exc).__name__}: {exc}"}


def _probe_clip(media: MediaEngine, row, *, attempt_thumb: bool) -> dict:
    path = row["path"]
    rep: dict = {"id": row["id"], "filename": row["filename"], "path": path}

    try:
        rep["exists"] = os.path.exists(path)
    except OSError as exc:
        rep["exists"] = False
        rep["exists_error"] = str(exc)
    try:
        rep["size_bytes"] = os.path.getsize(path) if rep.get("exists") else None
    except OSError as exc:
        rep["size_bytes"] = None
        rep["size_error"] = str(exc)

    rep["read_first_1mb"] = _read_test(path) if rep.get("exists") else None

    # ffprobe the streams (codec/pix_fmt/dims) — shows HEVC/10-bit/multi-stream.
    if media.ffprobe and rep.get("exists"):
        pr = _run_capture(
            [media.ffprobe, "-v", "error", "-show_entries",
             "stream=index,codec_type,codec_name,profile,pix_fmt,width,height",
             "-of", "default=noprint_wrappers=1", path],
            timeout=30,
        )
        rep["ffprobe"] = {"elapsed": pr["elapsed"], "error": pr["error"],
                          "output": (pr["stdout"] or pr["stderr"]).strip()[:1200]}

    # Live thumbnail attempt with captured ffmpeg stderr — the smoking gun.
    if attempt_thumb and media.ffmpeg and rep.get("exists"):
        w = media.preview_max_width
        out = media.cache_dir / "doctor_probe.jpg"
        cmd = [media.ffmpeg, "-y", "-ss", "1", "-i", path, "-frames:v", "1",
               "-map", "0:v:0", "-vf", f"scale='min({w},iw)':-2,format=yuvj420p",
               "-q:v", "3", str(out)]
        res = _run_capture(cmd, timeout=60)
        ok = res["rc"] == 0 and out.exists() and out.stat().st_size > 0
        rep["thumbnail_attempt"] = {
            "ok": ok,
            "rc": res["rc"],
            "elapsed": res["elapsed"],
            "error": res["error"],
            "stderr_tail": "\n".join(res["stderr"].splitlines()[-6:]),
        }
        try:
            if out.exists():
                out.unlink()
        except OSError:
            pass
    return rep


def build_report(config, media: MediaEngine, con) -> dict:
    repo_dir = Path(__file__).resolve().parents[2]

    # cache writability
    cache_writable = None
    cache_error = None
    try:
        media.cache_dir.mkdir(parents=True, exist_ok=True)
        probe = media.cache_dir / ".doctor_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        cache_writable = True
    except OSError as exc:
        cache_writable = False
        cache_error = str(exc)

    # sample clips: prefer a couple of DJI / drone files (the reported problem)
    # plus a couple of others that usually work, for contrast.
    def _rows(where, n):
        try:
            return list(con.execute(
                f"select id, filename, path from files where {where} limit ?", (n,)))
        except Exception:
            return []

    dji = _rows("filename like 'DJI%' or lower(path) like '%drone%'", 2)
    others = _rows("filename not like 'DJI%' and lower(path) not like '%drone%'", 2)

    samples = []
    for r in dji:
        samples.append(_probe_clip(media, r, attempt_thumb=True))
    for r in others:
        samples.append(_probe_clip(media, r, attempt_thumb=True))

    # cache contents
    def _count(p):
        try:
            return len(list(p.glob("*.*")))
        except OSError:
            return None

    return {
        "build_marker": BUILD_MARKER,
        "git": _git_head(repo_dir),
        "ffmpeg": _tool_report("ffmpeg", media.ffmpeg),
        "ffprobe": _tool_report("ffprobe", media.ffprobe),
        "config": {
            "footage_paths": [str(p) for p in config.footage_paths],
            "ffmpeg_path": config.ffmpeg_path,
            "ffprobe_path": config.ffprobe_path,
            "database": str(config.database_abspath),
            "cache_dir": str(media.cache_dir),
            "cache_writable": cache_writable,
            "cache_error": cache_error,
            "preview_max_width": media.preview_max_width,
            "preview_max_seconds": media.preview_max_seconds,
        },
        "index": {
            "total_files": db.file_count(con),
            "dji_or_drone": len(_rows("filename like 'DJI%' or lower(path) like '%drone%'", 100000)),
            "thumbs_cached": _count(media.cache_dir / "thumbs"),
            "previews_cached": _count(media.cache_dir / "previews"),
        },
        "samples": samples,
    }


def render_html(report: dict) -> str:
    import json as _json

    def esc(s) -> str:
        return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    ff = report["ffmpeg"]
    verdicts = []

    if not ff.get("found"):
        verdicts.append(("bad", "ffmpeg NOT found on the server — no thumbnails or "
                                "previews can be generated at all. Provide ffmpeg.exe "
                                "(PATH or tools\\) on the server."))
    else:
        if ff.get("can_decode_hevc") is False:
            verdicts.append(("bad", "This ffmpeg build CANNOT decode HEVC (H.265). The "
                                    "DJI drone clips are HEVC, so they fail while H.264 "
                                    "clips work. Replace with a full ffmpeg build."))
        if ff.get("has_libx264") is False:
            verdicts.append(("bad", "This ffmpeg has no libx264 encoder — previews can't "
                                    "be made. Replace with a full ffmpeg build."))

    for s in report.get("samples", []):
        tag = "DJI/drone" if (s["filename"].upper().startswith("DJI") or "drone" in s["path"].lower()) else "other"
        if not s.get("exists"):
            verdicts.append(("bad", f"[{tag}] {esc(s['filename'])}: the server cannot see "
                                    f"this file at all ({esc(s.get('exists_error',''))})."))
            continue
        rt = s.get("read_first_1mb") or {}
        if rt and not rt.get("ok"):
            verdicts.append(("bad", f"[{tag}] {esc(s['filename'])}: file exists but reading "
                                    f"it FAILED ({esc(rt.get('error'))}) — likely OneDrive "
                                    f"online-only / not hydrated."))
        elif rt and rt.get("elapsed", 0) > 10:
            verdicts.append(("warn", f"[{tag}] {esc(s['filename'])}: reading the first 1 MB "
                                     f"took {rt['elapsed']}s — the file is very slow to read "
                                     f"(OneDrive hydration / network). Thumbnail/preview "
                                     f"generation will time out."))
        ta = s.get("thumbnail_attempt")
        if ta and not ta.get("ok"):
            verdicts.append(("bad", f"[{tag}] {esc(s['filename'])}: live thumbnail attempt "
                                    f"FAILED (rc={ta.get('rc')}, {esc(ta.get('error') or '')}, "
                                    f"{ta.get('elapsed')}s). ffmpeg said: "
                                    f"{esc(ta.get('stderr_tail') or '')}"))
        elif ta and ta.get("ok") and ta.get("elapsed", 0) > 20:
            verdicts.append(("warn", f"[{tag}] {esc(s['filename'])}: thumbnail worked but took "
                                     f"{ta['elapsed']}s — too slow for a smooth gallery."))

    if not verdicts:
        verdicts.append(("ok", "No problems detected in the sampled clips — ffmpeg is "
                               "present and the sampled files generate thumbnails."))

    rows = "".join(
        f'<div class="v {cls}"><b>{cls.upper()}</b> {msg}</div>' for cls, msg in verdicts
    )
    pretty = esc(_json.dumps(report, indent=2, default=str))
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>B-Roll Library — Diagnostics</title>
<style>
 body{{font:14px/1.5 Segoe UI,Arial,sans-serif;background:#0a1320;color:#dce6f2;margin:0;padding:28px;}}
 h1{{font-size:20px;margin:0 0 4px;}} .marker{{color:#8fa6c0;margin-bottom:18px;}}
 .v{{padding:10px 14px;border-radius:8px;margin:8px 0;}}
 .v.bad{{background:#3a1620;border:1px solid #7d2740;}}
 .v.warn{{background:#3a2f16;border:1px solid #7d6427;}}
 .v.ok{{background:#163a27;border:1px solid #277d4f;}}
 .v b{{margin-right:8px;letter-spacing:.5px;}}
 pre{{background:#06101e;border:1px solid #1d2c40;border-radius:8px;padding:16px;
      overflow:auto;font:12px/1.45 Consolas,monospace;color:#bcd;}}
 a{{color:#2ba8e8;}}
</style></head><body>
<h1>B-Roll Library — Diagnostics</h1>
<div class="marker">Server build: <b>{esc(report.get('build_marker'))}</b>
 &nbsp;·&nbsp; git: {esc((report.get('git') or {}).get('commit'))}
 &nbsp;·&nbsp; ffmpeg: {esc(ff.get('resolved_path'))}</div>
{rows}
<h3>Full report</h3>
<pre>{pretty}</pre>
</body></html>"""
