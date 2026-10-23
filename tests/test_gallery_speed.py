"""The gallery must answer from the index, and posters must not block requests."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from broll_search import database as db
from broll_search.config import Config
from broll_search.web.app import create_app
from broll_search.web.media import MediaEngine


def _clip(path: str, filename: str, keywords: str, modified: str, mtime_ns: int = 100) -> dict:
    return {
        "path": path,
        "root": r"C:\footage",
        "relative_path": filename,
        "filename": filename,
        "extension": ".mp4",
        "shooter": "Aaron",
        "month_name": "October",
        "shoot_year": 2026,
        "shoot_month": 10,
        "shoot_date": "2026-10-01",
        "shot_type": "Wide",
        "parent_folder": "October",
        "folder_path": r"C:\footage\Aaron\October",
        "keywords": keywords,
        "size_bytes": 2048,
        "mtime_ns": mtime_ns,
        "date_created": modified,
        "date_modified": modified,
        "duration_sec": 12,
        "width": 1920,
        "height": 1080,
        "codec": "h264",
        "ai_description": None,
        "ai_tags": None,
        "ai_category": None,
        "indexed_at": modified,
    }


class _TimeoutEngine(MediaEngine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.runs = 0

    def _run(self, cmd, timeout):
        self.runs += 1
        return "timeout"


class _OkEngine(MediaEngine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.runs = 0

    def _run(self, cmd, timeout):
        self.runs += 1
        Path(cmd[-1]).write_bytes(b"\xff\xd8\xff\xd9")
        return "ok"


class GallerySpeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "index.db"
        self.cache = self.root / "cache"
        self.ffmpeg = self.root / "ffmpeg"
        self.ffmpeg.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.ffmpeg.chmod(0o755)
        con = db.connect(self.db_path, ensure=True)
        try:
            db.upsert_file(con, _clip(
                r"C:\footage\meeting.mp4", "council-meeting.mp4",
                "corporate meeting office", "2026-10-20T12:00:00", 1,
            ))
            db.upsert_file(con, _clip(
                r"C:\footage\odd.mp4", "zzzzunique-clip.mp4",
                "zzzzunique", "2026-10-21T12:00:00", 2,
            ))
            for i in range(80):
                db.upsert_file(con, _clip(
                    rf"C:\footage\extra-{i}.mp4", f"extra-{i}.mp4",
                    "water treatment plant", f"2026-09-{(i % 28) + 1:02d}T00:00:00", 1000 + i,
                ))
            con.commit()
        finally:
            con.close()
        self.media = MediaEngine(ffmpeg_path=str(self.ffmpeg), cache_dir=self.cache)
        # Page-load tests must not start ffmpeg workers or walk the archive.
        self.media.start_workers = lambda: None
        self.config = Config(database_path=str(self.db_path), footage_paths=[])
        self.app = create_app(self.config, media=self.media, warm_thumbs=False)
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_home_does_not_stat_footage_and_is_one_payload(self):
        import broll_search.web.app as appmod
        calls = []
        original = appmod.os.path.exists

        def guard(path):
            if str(path).lower().endswith(".mp4"):
                calls.append(str(path))
            return original(path)

        appmod.os.path.exists = guard
        try:
            started = time.perf_counter()
            rv = self.client.get("/api/home")
            elapsed = time.perf_counter() - started
        finally:
            appmod.os.path.exists = original

        self.assertEqual(rv.status_code, 200, rv.data)
        self.assertEqual(calls, [])
        self.assertLess(elapsed, 1.5, f"/api/home took {elapsed:.2f}s")
        body = rv.get_json()
        labels = [s["label"] for s in body["sections"]]
        self.assertEqual(labels[0], "Recently added")
        self.assertIn("Corporate & Meetings", labels)
        self.assertIn("Water & Utilities", labels)
        self.assertIn("More B-Roll", labels)
        recent_names = [i["filename"] for i in body["sections"][0]["items"]]
        self.assertIn("zzzzunique-clip.mp4", recent_names)
        self.assertEqual(body["filters"]["total"], 82)
        more = next(s for s in body["sections"] if s["key"] == "_more")
        self.assertEqual(more["items"][0]["filename"], "zzzzunique-clip.mp4")

    def test_search_keeps_rows_when_the_file_is_not_on_disk(self):
        rv = self.client.get("/api/search?q=zzzzunique")
        self.assertEqual(rv.status_code, 200)
        names = [i["filename"] for i in rv.get_json()["items"]]
        self.assertEqual(names, ["zzzzunique-clip.mp4"])

    def test_preview_miss_returns_immediately(self):
        row = self.client.get("/api/search?q=zzzzunique").get_json()["items"][0]
        started = time.perf_counter()
        rv = self.client.get(f"/preview/{row['id']}")
        elapsed = time.perf_counter() - started
        self.assertEqual(rv.status_code, 404)
        self.assertEqual(rv.headers["X-Thumb-State"], "pending")
        self.assertIn("no-store", rv.headers["Cache-Control"])
        self.assertLess(elapsed, 0.5)

    def test_missing_poster_is_queued_not_encoded_inline(self):
        queued = []

        def enqueue(src, mtime, front=False):
            queued.append((src, front))

        self.media.enqueue_thumbnail = enqueue
        row = self.client.get("/api/search?q=zzzzunique").get_json()["items"][0]
        started = time.perf_counter()
        rv = self.client.get(f"/thumb/{row['id']}")
        elapsed = time.perf_counter() - started
        self.assertEqual(rv.status_code, 404)
        self.assertEqual(rv.headers["X-Thumb-State"], "pending")
        self.assertIn("no-store", rv.headers["Cache-Control"])
        self.assertEqual(queued, [(r"C:\footage\odd.mp4", True)])
        self.assertLess(elapsed, 0.5)

    def test_cached_poster_is_a_jpeg(self):
        src = r"C:\footage\odd.mp4"
        key = self.media._key(src, 2)
        jpg = self.media.thumbs_dir / f"{key}.jpg"
        jpg.write_bytes(b"\xff\xd8\xff\xd9")
        row = self.client.get("/api/search?q=zzzzunique").get_json()["items"][0]
        rv = self.client.get(f"/thumb/{row['id']}")
        self.assertEqual(rv.status_code, 200)
        self.assertIn("jpeg", rv.content_type)
        self.assertEqual(rv.headers["X-Thumb-State"], "ready")
        self.assertTrue(rv.data.startswith(b"\xff\xd8"))

    def test_timeout_is_remembered_and_not_retried(self):
        eng = _TimeoutEngine(ffmpeg_path=str(self.ffmpeg), cache_dir=self.root / "cache2")
        src = self.root / "slow.mp4"
        src.write_bytes(b"video")
        self.assertFalse(eng._generate_thumbnail(str(src), eng._key(str(src), 7)))
        self.assertEqual(eng.runs, 1)
        self.assertEqual(eng.thumb_state(str(src), 7), "failed")
        eng.enqueue_thumbnail(str(src), 7, front=True)
        self.assertEqual(eng.thumb_queue_depth(), 0)

    def test_poster_is_generated_once(self):
        eng = _OkEngine(ffmpeg_path=str(self.ffmpeg), cache_dir=self.root / "cache3")
        src = self.root / "ok.mp4"
        src.write_bytes(b"video")
        first = eng.thumbnail_path(str(src), 5)
        second = eng.thumbnail_path(str(src), 5)
        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        self.assertEqual(eng.runs, 1)
        self.assertGreater(first.stat().st_size, 0)

    def test_visible_poster_jumps_the_queue(self):
        eng = MediaEngine(ffmpeg_path=str(self.ffmpeg), cache_dir=self.root / "cache4")
        eng.enqueue_thumbnail("older.mp4", 1)
        eng.enqueue_thumbnail("newer.mp4", 1)
        eng.enqueue_thumbnail("older.mp4", 1, front=True)
        self.assertEqual([item[0] for item in eng._thumb_q], ["older.mp4", "newer.mp4"])
        key = eng._key("newer.mp4", 1)
        eng._thumb_q.clear()
        eng._thumb_queued.clear()
        eng._thumb_inflight_keys.add(key)
        eng.enqueue_thumbnail("newer.mp4", 1, front=True)
        self.assertEqual(eng.thumb_queue_depth(), 0)

    def test_real_ffmpeg_writes_a_jpeg_poster(self):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("ffmpeg is not installed")
        src = self.root / "color.mp4"
        subprocess.check_call(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "color=c=red:s=320x180:d=1",
             "-pix_fmt", "yuv420p", str(src)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        eng = MediaEngine(ffmpeg_path=ffmpeg, cache_dir=self.root / "cache5")
        poster = eng.thumbnail_path(str(src), src.stat().st_mtime_ns)
        self.assertIsNotNone(poster)
        self.assertTrue(poster.read_bytes().startswith(b"\xff\xd8"))
        self.assertGreater(poster.stat().st_size, 100)


if __name__ == "__main__":
    unittest.main()
