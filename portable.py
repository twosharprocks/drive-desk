"""Desktop integration for Flatpak and Snap builds."""
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from gi.repository import Gio, GLib

import sync


enabled = os.environ.get("DRIVE_DESK_FORMAT") in ("flatpak", "snap")


def login_start(active, finished):
    if os.environ["DRIVE_DESK_FORMAT"] == "snap":
        path = Path(os.environ["SNAP_USER_DATA"]) / ".config/autostart/drive-desk.desktop"
        if active:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("[Desktop Entry]\nType=Application\nName=Drive Desk\nExec=drive-desk --background\n")
        else:
            path.unlink(missing_ok=True)
        finished(active)
        return
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    token = "drivedesk" + uuid.uuid4().hex
    sender = bus.get_unique_name()[1:].replace(".", "_")
    path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
    portal = "org.freedesktop.portal.Desktop"
    def response(connection, sender_name, object_path, interface, member, params):
        bus.signal_unsubscribe(subscription)
        code, results = params.unpack()
        if code == 0:
            finished(bool(results.get("autostart")))
    subscription = bus.signal_subscribe(portal, "org.freedesktop.portal.Request", "Response", path,
                                        None, Gio.DBusSignalFlags.NONE, response)
    options = {"handle_token": GLib.Variant("s", token), "autostart": GLib.Variant("b", active),
               "reason": GLib.Variant("s", "Check scheduled Google Drive folders after sign-in."),
               "commandline": GLib.Variant("as", ["drive-desk", "--background"])}
    try:
        bus.call_sync(portal, "/org/freedesktop/portal/desktop", "org.freedesktop.portal.Background",
                      "RequestBackground", GLib.Variant("(sa{sv})", ("", options)),
                      None, Gio.DBusCallFlags.NONE, 5000, None)
    except GLib.Error:
        bus.signal_unsubscribe(subscription)
        raise


def open_folder(uri):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    bus.call_sync("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                  "org.freedesktop.FileManager1", "ShowFolders", GLib.Variant("(ass)", ([uri], "")),
                  None, Gio.DBusCallFlags.NONE, 5000, None)


def settings_panel(panel):
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        args = GLib.Variant("(sava{sv})", ("launch-panel", [GLib.Variant("(sav)", (panel, []))], {}))
        bus.call_sync("org.gnome.Settings", "/org/gnome/Settings", "org.freedesktop.Application",
                      "ActivateAction", args, None, Gio.DBusCallFlags.NONE, 5000, None)
    except GLib.Error:
        return "Open system Settings → Online Accounts or Keyboard to change this setting."
    return "Opened system Settings."


class Scheduler:
    """Keep a single app instance alive between syncs, even after its window closes."""
    def __init__(self):
        self.app = None
        self.child = None
        self.held = False
        self.next_run = 0

    def startup(self, app):
        self.app = app
        if sync.preference("portable-scheduler") == "on":
            self.enable(app)
        GLib.timeout_add_seconds(2, self.tick)

    def enable(self, app):
        if not self.held:
            app.hold()
            self.held = True
        sync.configure("portable-scheduler", "on")

    def disable(self):
        sync.configure("portable-scheduler", "off")
        if self.held and self.child is None:
            self.app.release()
            self.held = False

    def start(self):
        if self.child is None and sync.preference("paused") != "yes":
            self.child = subprocess.Popen([sys.executable, str(Path(sync.__file__).resolve())],
                                          start_new_session=True)
            if not self.held:
                self.app.hold()
                self.held = True

    def tick(self):
        if self.child is not None and self.child.poll() is not None:
            self.child = None
            self.next_run = time.monotonic() + 120
            if sync.preference("portable-scheduler") != "on":
                self.disable()
        if self.held and self.child is None and time.monotonic() >= self.next_run:
            with sync.database() as db:
                if db.execute("SELECT 1 FROM jobs LIMIT 1").fetchone() is None:
                    self.disable()
                    return True
            self.start()
        return True

    def pause(self, paused):
        if self.child is not None and self.child.poll() is None:
            try:
                os.killpg(self.child.pid, signal.SIGSTOP if paused else signal.SIGCONT)
            except ProcessLookupError:
                pass
        sync.configure("paused", "yes" if paused else "no")
        if not paused:
            self.start()


scheduler = Scheduler()
