"""Linux desktop smoke and copy regression tests. No Google credentials used."""
import os
import runpy
import tempfile
import unittest
from unittest import mock
from pathlib import Path

app = runpy.run_path(str(Path(__file__).with_name("drive-desk")), run_name="drive_desk")
Gio, GLib, Gtk = (app[name] for name in ("Gio", "GLib", "Gtk"))


class DriveTests(unittest.TestCase):
    def test_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            src, dst = folder / "source", folder / "download"
            src.write_bytes(b"drive" * 400000)
            file = Gio.File.new_for_path(str(src))
            app["save_copy"](file, dst, Gio.Cancellable())
            self.assertEqual(src.read_bytes(), dst.read_bytes())
            src.write_bytes(b"changed")
            with self.assertRaises(FileExistsError):
                app["save_copy"](file, dst, Gio.Cancellable())
            self.assertEqual(dst.stat().st_size, 2000000)
            stopped = Gio.Cancellable()
            stopped.cancel()
            with self.assertRaises(GLib.Error):
                app["save_copy"](file, folder / "cancelled", stopped)
            with self.assertRaises(GLib.Error):
                app["save_copy"](Gio.File.new_for_path(str(folder / "missing")), dst, Gio.Cancellable())
            self.assertEqual(set(folder.iterdir()), {src, dst})

    def test_window(self):
        application = Gtk.Application(application_id="org.example.DriveDeskTest")
        application.register(None)
        window = app["Window"](application)
        self.assertIsNotNone(window.client)
        self.assertTrue(window.get_visible())
        self.assertEqual(window.get_title(), "Drive Desk")
        if os.getenv("DRIVE_DESK_TEST_ACCOUNT"):
            self.assertEqual(window.accounts.get_active_text(), "tester@example.invalid")
            self.assertTrue(window.accounts.get_active_id().startswith("google-drive://"))
            self.assertTrue(window.actions.get_sensitive())
        if not window.accounts.get_active_id():
            self.assertFalse(window.actions.get_sensitive())
            self.assertIn("Online Accounts", window.status.get_text())
        window.destroy()

    def test_search_and_jobs_windows(self):
        import desktop_tools
        parent = Gtk.Window()
        parent.show()
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, XDG_STATE_HOME=temp):
            jobs = desktop_tools.Jobs(parent, None)
            self.assertIn("Scheduled folders", jobs.detail.get_text())
            jobs.destroy()
        result = {"files": [{"id": "test", "name": "Example", "mimeType": "text/plain"}]}
        with mock.patch.object(desktop_tools, "async_call", side_effect=lambda win, op, cb: cb(result, None)):
            search = desktop_tools.Search(parent, "sample")
            self.assertEqual(search.store[0][0], "Example")
            self.assertFalse(search.more.get_sensitive())
            search.destroy()
        parent.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
