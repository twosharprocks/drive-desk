import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import cloud
import sync


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, XDG_STATE_HOME=str(self.base / "state"))
        self.env.start()
        self.addCleanup(self.env.stop)
        self.local, self.remote = self.base / "local", self.base / "remote"
        self.local.mkdir()
        self.remote.mkdir()

    def job(self, kind):
        key = sync.add_job("fake-account", kind, self.local, "root", "My Drive", up=10000)
        with sync.database() as db:
            return dict(db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone())

    def test_mirror(self):
        (self.remote / "cloud.txt").write_text("first")
        job = self.job("mirror")
        def run():
            sync.transfer(job, str(self.remote), os.environ)
        run()
        self.assertEqual((self.local / "cloud.txt").read_text(), "first")
        job["initialized"] = True
        (self.local / "offline.txt").write_text("offline editing")
        run()
        self.assertEqual((self.remote / "offline.txt").read_text(), "offline editing")
        time.sleep(1.1)
        (self.local / "cloud.txt").write_text("local conflict")
        (self.remote / "cloud.txt").write_text("remote conflict")
        run()
        for folder in (self.local, self.remote):
            self.assertTrue({"local conflict", "remote conflict"} <=
                            {p.read_text() for p in folder.iterdir() if p.is_file()})
        (self.local / "offline.txt").unlink()
        run()
        self.assertFalse((self.remote / "offline.txt").exists())
        (self.local / (".drive-desk-" + job["id"])).unlink()
        with self.assertRaisesRegex(ValueError, "identity"):
            run()

    def test_activity_after_repeated_failure_and_recovery(self):
        job = self.job("backup")
        with sync.database() as db:
            for status in ("Needs attention — offline", "Needs attention — offline", "Up to date"):
                prior = db.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()
                sync.record_result(db, prior, status)
            rows = db.execute("SELECT account,error,unread FROM activity ORDER BY seq").fetchall()
            self.assertEqual([tuple(row) for row in rows], [("fake-account", 1, 1), ("fake-account", 0, 0)])

    def test_backup_and_replaced_folder(self):
        job = self.job("backup")
        (self.local / "photo").write_text("photo")
        sync.transfer(job, str(self.remote), os.environ)
        (self.local / "photo").unlink()
        sync.transfer(job, str(self.remote), os.environ)
        self.assertTrue((self.remote / "photo").exists())
        self.local.rename(self.base / "moved")
        self.local.mkdir()
        with self.assertRaisesRegex(ValueError, "replaced"):
            sync.transfer(job, str(self.remote), os.environ)

    def test_overlap_and_initial_contents(self):
        (self.local / "before").touch()
        with self.assertRaisesRegex(ValueError, "empty"):
            self.job("mirror")
        self.job("backup")
        with self.assertRaisesRegex(ValueError, "overlap"):
            self.job("backup")

    def test_pinned_file(self):
        original = self.remote / "one file.txt"
        original.write_text("first")
        (self.remote / "other").write_text("unrelated")
        key = sync.add_job("fake", "pin", self.local, "parent", original.name, pin=("id", original.name))
        with sync.database() as db:
            job = dict(db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone())
        sync.transfer(job, str(self.remote), os.environ)
        self.assertFalse((self.local / "other").exists())
        job["initialized"] = True
        time.sleep(1.1)
        (self.local / original.name).write_text("offline edit")
        sync.transfer(job, str(self.remote), os.environ)
        self.assertEqual(original.read_text(), "offline edit")
        original.rename(self.remote / "moved")
        with self.assertRaisesRegex(ValueError, "moved"):
            sync.transfer(job, str(self.remote), os.environ)

    def test_legacy_bisync_listings(self):
        work = self.base
        first = work / "desk{old}_folder.path1.lst"
        second = work / "desk{old}_folder.path2.lst"
        first.write_bytes(b"remote baseline")
        with self.assertRaises(ValueError):
            sync.bisync_workdir(work)
        second.write_bytes(b"local baseline")
        lock = work / "desk{old}_folder.lck"
        lock.touch()
        with self.assertRaises(ValueError):
            sync.bisync_workdir(work)
        lock.unlink()
        dest = sync.bisync_workdir(work)
        self.assertEqual((dest / "desk_folder.path1.lst").read_bytes(), first.read_bytes())
        self.assertEqual((dest / "desk_folder.path2.lst").read_bytes(), second.read_bytes())
        (dest / "desk_folder.path1.lst").unlink()
        self.assertEqual(sync.bisync_workdir(work), dest)
        self.assertFalse((dest / "desk_folder.path1.lst").exists())

    def test_duplicate_detection(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            sync.check_unique(['"folder/a,b"', '"folder/a,b"'])

    def test_worker_retries_and_respects_pause(self):
        job = self.job("sync local")
        (self.local / "laptop").write_text("new local file")
        with mock.patch.object(sync, "token_for", side_effect=ValueError("offline")), \
                mock.patch.object(sync.subprocess, "run", side_effect=FileNotFoundError("notify-send")):
            sync.run()
        def status():
            with sync.database() as db:
                return db.execute("SELECT status FROM jobs WHERE id=?", (job["id"],)).fetchone()[0]
        self.assertIn("offline", status())
        transfer = sync.transfer
        def local_target(row, destination, env):
            self.assertTrue(destination.startswith("desk:Drive Desk computers/"))
            transfer(row, str(self.remote), env)
        with mock.patch.object(sync, "token_for", return_value="test"), mock.patch.object(sync, "transfer", local_target):
            sync.run()
            self.assertEqual(status(), "Up to date")
            self.assertTrue((self.remote / "laptop").exists())
            sync.configure("paused", "yes")
            (self.local / "deferred").touch()
            sync.run()
            self.assertFalse((self.remote / "deferred").exists())
            sync.configure("paused", "no")
            sync.run()
            self.assertTrue((self.remote / "deferred").exists())

    def test_api_requests(self):
        with mock.patch.object(cloud, "request", return_value={}) as api:
            cloud.files("test", "Shared with me", "a'b", "next")
            params = api.call_args.args[2]
            self.assertIn("a\\'b", params["q"])
            self.assertIn("sharedWithMe", params["q"])
            self.assertEqual(params["pageToken"], "next")
            cloud.share("test", {"id": "ab"}, "tester@example.invalid", "reader")
            self.assertEqual(api.call_args.args[1], "files/ab/permissions")
            self.assertEqual(api.call_args.args[4]["role"], "reader")


if __name__ == "__main__":
    unittest.main(verbosity=2)
