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
from broll_search.web.app import (
    NETWORK_FOOTAGE_ROOT, create_app, poster_sources, _file_is_local, _network_path,
)
from broll_search.web.doctor import BUILD_MARKER
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
        self.assertEqual(body["build"], BUILD_MARKER)
        self.assertIn("cached", body["posters"])
        posters = self.client.get("/api/posters")
        self.assertEqual(posters.status_code, 200)
        self.assertIn("no-store", posters.headers["Cache-Control"])
        self.assertEqual(posters.get_json()["build"], BUILD_MARKER)
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

    def test_old_unreadable_marker_is_retried(self):
        """Failure notes from the build that skipped OneDrive files are stale."""
        eng = MediaEngine(ffmpeg_path=str(self.ffmpeg), cache_dir=self.root / "cache-old")
        src = self.root / "cloud.mp4"
        src.write_bytes(b"video")
        key = eng._key(str(src), 9)
        (eng.thumbs_dir / f"{key}.fail").write_text("100\nunreadable\n", encoding="utf-8")
        self.assertEqual(eng.thumb_state(str(src), 9), "pending")
        eng.enqueue_thumbnail(str(src), 9, front=True)
        self.assertEqual(eng.thumb_queue_depth(), 1)

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
        data = poster.read_bytes()
        self.assertTrue(data.startswith(b"\xff\xd8"))
        self.assertGreater(poster.stat().st_size, 100)
        self.assertGreater(_jpeg_width(data), 0)
        self.assertLessEqual(_jpeg_width(data), 480)

    def test_archive_paths_map_onto_the_share(self):
        tail = r"\Aaron\July\clip.mp4"
        expected = NETWORK_FOOTAGE_ROOT + tail
        onedrive = (
            r"C:\Users\SRV-ITS-MNN\OneDrive - Metro Nashville Gov"
            r"\MNNPublic - 2026 Metro Nashville Archive B-Roll Footage"
            + tail
        )
        mapped = r"X:\2026 Metro Nashville Archive B-Roll Footage" + tail
        forwarded = onedrive.replace("\\", "/")
        self.assertEqual(_network_path(onedrive), expected)
        self.assertEqual(_network_path(mapped), expected)
        self.assertEqual(_network_path(forwarded), expected)
        self.assertEqual(_network_path(expected), expected)
        alt = (
            r"\\smb.data.nashville.org\MNNArchive"
            r"\MNNPublic - 2026 Metro Nashville Archive B-Roll Footage"
            + tail
        )
        self.assertEqual(poster_sources(onedrive), [expected, alt, onedrive])
        self.assertEqual(poster_sources(""), [])

    def test_unc_share_is_not_statd(self):
        import os
        share = NETWORK_FOOTAGE_ROOT + r"\Aaron\July\clip.mp4"

        def boom(path):
            raise AssertionError(f"stat'd {path}")

        orig = os.path.isfile
        os.path.isfile = boom
        try:
            self.assertFalse(_file_is_local(share))
            self.assertEqual(poster_sources(share), [share])
        finally:
            os.path.isfile = orig

    def test_hydrated_archive_file_stays_local(self):
        folder = self.root / "2026 Metro Nashville Archive B-Roll Footage" / "Aaron"
        folder.mkdir(parents=True)
        clip = folder / "clip.mp4"
        clip.write_bytes(b"video")
        sources = poster_sources(str(clip))
        self.assertEqual(sources[-1], str(clip))
        self.assertTrue(sources[0].startswith("\\\\smb.data.nashville.org\\"))

    def test_v2_timeout_marker_is_retried_from_the_share(self):
        eng = MediaEngine(ffmpeg_path=str(self.ffmpeg), cache_dir=self.root / "cache-v2")
        src = self.root / "cloud.mp4"
        src.write_bytes(b"video")
        key = eng._key(str(src), 9)
        (eng.thumbs_dir / f"{key}.fail").write_text(
            f"v6\n{time.time():.0f}\nunreadable share slash: invalid argument\n", encoding="utf-8")
        self.assertEqual(eng.thumb_state(str(src), 9), "pending")
        eng.enqueue_thumbnail(str(src), 9, front=True)
        self.assertEqual(eng.thumb_queue_depth(), 1)

    def test_slow_share_falls_through_to_the_local_file(self):
        eng = _TimeoutThenOk(ffmpeg_path=str(self.ffmpeg), cache_dir=self.root / "cache-share")
        local = self.root / "clip.mp4"
        local.write_bytes(b"video")
        share = r"\\smb.data.nashville.org\MNNArchive\clip.mp4"
        eng.source_resolver = lambda src: [share, str(local)]
        import os
        orig = os.path.exists

        def guard(path):
            if str(path).startswith("\\\\"):
                raise AssertionError(f"stat'd {path}")
            return orig(path)

        os.path.exists = guard
        try:
            made = eng._generate_thumbnail(str(local), eng._key(str(local), 3))
        finally:
            os.path.exists = orig
        self.assertTrue(made)
        self.assertEqual(eng.runs, 2)
        self.assertEqual(eng.tried, [
            r"\\?\UNC\smb.data.nashville.org\MNNArchive\clip.mp4",
            str(local),
        ])

    def test_unreadable_share_does_not_retry_filters(self):
        eng = _UnreadableThenOk(ffmpeg_path=str(self.ffmpeg), cache_dir=self.root / "cache-unreadable")
        local = self.root / "clip.mp4"
        local.write_bytes(b"video")
        share = r"\\server\share\clip.mp4"
        eng.source_resolver = lambda src: [share, str(local)]
        self.assertTrue(eng._generate_thumbnail(str(local), eng._key(str(local), 4)))
        self.assertEqual(eng.runs, 2)
        self.assertEqual(eng.tried, [r"\\?\UNC\server\share\clip.mp4", str(local)])

    def test_codec_error_tries_zscale_before_another_copy(self):
        eng = _ZscaleEngine(ffmpeg_path=str(self.ffmpeg), cache_dir=self.root / "cache-zscale")
        local = self.root / "tenbit.mp4"
        local.write_bytes(b"video")
        self.assertTrue(eng._generate_thumbnail(str(local), eng._key(str(local), 8)))
        self.assertEqual(eng.runs, 2)
        self.assertIn("zscale", eng.filters[1])
        self.assertNotIn("zscale", eng.filters[0])

    def test_preview_reads_the_share_when_onedrive_is_missing(self):
        eng = _OkEngine(ffmpeg_path=str(self.ffmpeg), cache_dir=self.root / "cache-preview")
        eng.tried = []
        real_run = eng._run

        def _run(cmd, timeout):
            eng.tried.append(cmd[cmd.index("-i") + 1])
            return real_run(cmd, timeout)

        eng._run = _run
        indexed = (
            r"C:\Users\SRV-ITS-MNN\OneDrive - Metro Nashville Gov"
            r"\MNNPublic - 2026 Metro Nashville Archive B-Roll Footage"
            r"\Aaron\July\clip.mp4"
        )
        eng.source_resolver = poster_sources
        out = eng.preview_path(indexed, 1)
        self.assertIsNotNone(out)
        self.assertEqual(
            eng.tried,
            [r"\\?\UNC\smb.data.nashville.org\MNNArchive\2026 Metro Nashville Archive B-Roll Footage\Aaron\July\clip.mp4"],
        )

    def test_pinned_placeholder_is_still_cloud_and_share_uses_forward_slashes(self):
        from broll_search.web.media import _attrs_are_cloud, _ffmpeg_input_names
        self.assertTrue(_attrs_are_cloud(0x80000 | 0x400000))
        self.assertTrue(_attrs_are_cloud(0x400, 0x9000101A))
        self.assertFalse(_attrs_are_cloud(0x20))
        share = r"\\smb.data.nashville.org\MNNArchive\clip.mp4"
        self.assertEqual(_ffmpeg_input_names(share), [
            r"\\?\UNC\smb.data.nashville.org\MNNArchive\clip.mp4",
            share,
        ])
        self.assertEqual(_ffmpeg_input_names(r"C:\footage\clip.mp4"), [
            "file:C:/footage/clip.mp4",
            r"C:\footage\clip.mp4",
        ])

    def test_invalid_share_spelling_tries_the_extended_path(self):
        eng = _InvalidThenExtended(ffmpeg_path=str(self.ffmpeg), cache_dir=self.root / "cache-ext")
        share = r"\\smb.data.nashville.org\MNNArchive\clip.mp4"
        eng.source_resolver = lambda src: [share]
        self.assertTrue(eng._generate_thumbnail(share, eng._key(share, 1)))
        self.assertEqual(eng.tried, [
            r"\\?\UNC\smb.data.nashville.org\MNNArchive\clip.mp4",
            r"\\?\UNC\smb.data.nashville.org\MNNArchive\clip.mp4",
            share,
        ])

    def test_unreadable_share_does_not_map_a_drive(self):
        eng = _UnreadableThenOk(ffmpeg_path=str(self.ffmpeg), cache_dir=self.root / "cache-nolink")
        local = self.root / "clip.mp4"
        local.write_bytes(b"video")
        share = r"\\server\share\clip.mp4"
        eng.source_resolver = lambda src: [share, str(local)]

        def boom(root):
            raise AssertionError(f"mapped {root}")

        eng._net_use_map = boom
        self.assertTrue(eng._generate_thumbnail(str(local), eng._key(str(local), 4)))

    def test_rejected_share_opens_through_a_drive_letter(self):
        eng = _OnlyShareDrive(ffmpeg_path=str(self.ffmpeg), cache_dir=self.root / "cache-drive")
        share = (
            r"\\smb.data.nashville.org\MNNArchive"
            r"\2026 Metro Nashville Archive B-Roll Footage\Aaron\clip.mp4"
        )
        eng.source_resolver = lambda src: [src]
        import os
        orig = os.path.exists

        def guard(path):
            text = str(path)
            if text.startswith("\\\\") or text.startswith("//"):
                raise AssertionError(f"stat'd {path}")
            return orig(path)

        os.path.exists = guard
        try:
            made = eng._generate_thumbnail(share, eng._key(share, 2))
        finally:
            os.path.exists = orig
        self.assertTrue(made)
        self.assertEqual(eng.mapped, r"\\smb.data.nashville.org\MNNArchive")
        self.assertTrue(eng.tried[-1].startswith("Y:"))
        self.assertIn("Aaron", eng.tried[-1])
        self.assertNotIn("2026", eng.tried[-1])
        eng.tried.clear()
        other = (
            r"\\smb.data.nashville.org\MNNArchive"
            r"\2026 Metro Nashville Archive B-Roll Footage\Aaron\other.mp4"
        )
        self.assertTrue(eng._generate_thumbnail(other, eng._key(other, 2)))
        self.assertEqual(eng.tried, [r"Y:\Aaron\other.mp4"])
        self.assertEqual(eng.max_concurrent, 4)

    def test_drive_map_failure_names_the_reason(self):
        eng = _AlwaysRejected(ffmpeg_path=str(self.ffmpeg), cache_dir=self.root / "cache-drive-fail")
        share = r"\\smb.data.nashville.org\MNNArchive\clip.mp4"
        eng.source_resolver = lambda src: [share]

        def deny(root):
            raise OSError("System error 53 has occurred.")

        eng._net_use_map = deny
        self.assertFalse(eng._generate_thumbnail(share, eng._key(share, 3)))
        err = eng.poster_status()["last_error"]
        self.assertIn("share long-path: invalid argument", err)
        self.assertIn("Error opening input: Invalid argument", err)
        self.assertIn("share drive: System error 53 has occurred.", err)

    def test_drive_paths_try_the_share_root_before_the_archive_folder(self):
        from broll_search.web.media import _drive_suffixes
        parts = [
            "2026 Metro Nashville Archive B-Roll Footage",
            "Aaron", "July", "clip.mp4",
        ]
        suffixes = _drive_suffixes(parts, ["Council", "MNNPublic - 2026 Metro Nashville Archive B-Roll Footage"])
        self.assertEqual(suffixes[0], ["Aaron", "July", "clip.mp4"])
        self.assertEqual(suffixes[1], parts)
        self.assertEqual(
            suffixes[2],
            ["MNNPublic - 2026 Metro Nashville Archive B-Roll Footage", "Aaron", "July", "clip.mp4"],
        )

    def test_missing_drive_file_names_the_folders(self):
        eng = _FoldersThenMissing(ffmpeg_path=str(self.ffmpeg), cache_dir=self.root / "cache-folders")
        share = (
            r"\\smb.data.nashville.org\MNNArchive"
            r"\2026 Metro Nashville Archive B-Roll Footage\Aaron\July\clip.mp4"
        )
        eng.source_resolver = lambda src: [share]
        self.assertFalse(eng._generate_thumbnail(share, eng._key(share, 5)))
        err = eng.poster_status()["last_error"]
        self.assertIn("share folders: 2024 Reels, Council Meetings", err)
        drive_paths = [name for name in eng.tried if name.startswith("Y:")]
        self.assertTrue(drive_paths)
        self.assertTrue(drive_paths[0].endswith("Aaron\\July\\clip.mp4"))

    def test_existing_net_use_letter_is_reused(self):
        eng = MediaEngine(ffmpeg_path=str(self.ffmpeg), cache_dir=self.root / "cache-net")
        text = (
            "Status       Local     Remote\n"
            "OK           Z:        \\\\other\\share\n"
            "OK           Y:        \\\\smb.data.nashville.org\\MNNArchive\n"
        )
        self.assertEqual(
            eng._drive_from_net_use(text, r"\\smb.data.nashville.org\MNNArchive"),
            "Y:",
        )
        self.assertEqual(eng._drive_from_net_use(text, r"\\missing\share"), "")

    def test_short_open_error_prefers_protocol_not_found(self):
        from broll_search.web.media import _short_open_error
        err = "Error opening input: Protocol not found\nDid you mean file:C:/clip.mp4?\nError opening input files: Invalid argument"
        self.assertEqual(
            _short_open_error(r"C:/clip.mp4", err),
            "local file slash: protocol not found",
        )
        self.assertIn(
            "No such file",
            _short_open_error("file://server/share/clip.mp4", "No such file or directory", detail=True),
        )

    def test_real_ffmpeg_opens_a_file_url(self):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("ffmpeg is not installed")
        src = self.root / "color-url.mp4"
        subprocess.check_call(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "color=c=blue:s=160x90:d=1",
             "-pix_fmt", "yuv420p", str(src)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        eng = MediaEngine(ffmpeg_path=ffmpeg, cache_dir=self.root / "cache-url")
        tmp = self.root / "from-url.jpg"
        status = eng._try_frame("file:" + str(src), tmp, [("0", "scale=160:-2", False, 20)])
        self.assertEqual(status, "ok", eng._last_error)
        self.assertTrue(tmp.read_bytes().startswith(b"\xff\xd8"))


class _FoldersThenMissing(MediaEngine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tried = []

    def _net_use_map(self, root):
        return "Y:"

    def _list_dir(self, path):
        return ["2024 Reels", "Council Meetings"], ""

    def _run(self, cmd, timeout):
        src = cmd[cmd.index("-i") + 1]
        self.tried.append(src)
        if src.startswith("Y:") or src.startswith("file:Y:"):
            self._last_error = src + ": No such file or directory"
            return "error"
        self._last_error = "Error opening input: Invalid argument"
        return "error"


class _OnlyShareDrive(MediaEngine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tried = []
        self.mapped = ""

    def _net_use_map(self, root):
        self.mapped = root
        return "Y:"

    def _run(self, cmd, timeout):
        src = cmd[cmd.index("-i") + 1]
        self.tried.append(src)
        if src.startswith("Y:") or src.startswith("file:Y:"):
            Path(cmd[-1]).write_bytes(b"\xff\xd8\xff\xd9")
            return "ok"
        self._last_error = "Error opening input: Invalid argument"
        return "error"


class _AlwaysRejected(MediaEngine):
    def _run(self, cmd, timeout):
        self._last_error = "Error opening input: Invalid argument"
        return "error"


class _InvalidThenExtended(MediaEngine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tried = []

    def _run(self, cmd, timeout):
        src = cmd[cmd.index("-i") + 1]
        self.tried.append(src)
        if not src.startswith("file:") and not src.startswith("\\\\?\\"):
            Path(cmd[-1]).write_bytes(b"\xff\xd8\xff\xd9")
            return "ok"
        self._last_error = "Error opening input: Invalid argument"
        return "error"


class _TimeoutThenOk(MediaEngine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.runs = 0
        self.tried = []

    def _run(self, cmd, timeout):
        self.runs += 1
        src = cmd[cmd.index("-i") + 1]
        self.tried.append(src)
        if src.startswith("\\\\") or src.startswith("//") or src.startswith("file://"):
            self._last_error = "timeout"
            return "timeout"
        Path(cmd[-1]).write_bytes(b"\xff\xd8\xff\xd9")
        return "ok"


class _UnreadableThenOk(MediaEngine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.runs = 0
        self.tried = []

    def _run(self, cmd, timeout):
        self.runs += 1
        src = cmd[cmd.index("-i") + 1]
        self.tried.append(src)
        if src.startswith("\\\\") or src.startswith("//") or src.startswith("file://"):
            self._last_error = "file://server/share/clip.mp4: No such file or directory"
            return "error"
        Path(cmd[-1]).write_bytes(b"\xff\xd8\xff\xd9")
        return "ok"


class _ZscaleEngine(MediaEngine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.runs = 0
        self.filters = []

    def _run(self, cmd, timeout):
        self.runs += 1
        vf = cmd[cmd.index("-vf") + 1]
        self.filters.append(vf)
        if "zscale" not in vf:
            self._last_error = "Error reinitializing filters"
            return "error"
        Path(cmd[-1]).write_bytes(b"\xff\xd8\xff\xd9")
        return "ok"


def _jpeg_width(data: bytes) -> int:
    """SOF width, so a generated poster can be checked without Pillow."""
    i = 2
    while i + 8 < len(data):
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            return int.from_bytes(data[i + 7:i + 9], "big")
        if marker == 0xD8 or marker == 0xD9:
            i += 2
            continue
        size = int.from_bytes(data[i + 2:i + 4], "big")
        if size < 2:
            break
        i += 2 + size
    return 0


if __name__ == "__main__":
    unittest.main()
