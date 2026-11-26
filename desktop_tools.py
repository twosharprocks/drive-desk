"""GTK dialogs for cloud search and scheduled folders."""
import datetime
import shutil
import subprocess
import threading
from pathlib import Path
from urllib.parse import quote
from gi.repository import Gdk, GLib, Gtk

import cloud
import sync
import portable


def button(box, label, callback):
    widget = Gtk.Button(label=label)
    widget.connect("clicked", lambda *_: callback())
    box.pack_start(widget, False, False, 0)
    return widget


def prompt(parent, title, fields):
    dialog = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, title, Gtk.ResponseType.OK)
    box = dialog.get_content_area()
    box.set_spacing(8)
    box.set_border_width(12)
    for label, widget in fields:
        box.pack_start(Gtk.Label(label=label, xalign=0, wrap=True), False, False, 0)
        box.pack_start(widget, False, False, 0)
    dialog.show_all()
    ok = dialog.run() == Gtk.ResponseType.OK
    for _, widget in fields:
        box.remove(widget)
    dialog.destroy()
    return ok


def combo(options):
    field = Gtk.ComboBoxText()
    for option in options:
        field.append_text(option)
    field.set_active(0)
    return field


def async_call(window, operation, done):
    def worker():
        try:
            value, error = operation(), None
        except Exception as exc:
            value, error = None, str(exc)
        def deliver():
            if window.get_visible():
                done(value, error)
        GLib.idle_add(deliver)
    threading.Thread(target=worker, daemon=True).start()


def timer(*args):
    result = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)
    if result.returncode:
        raise ValueError(result.stderr.strip() or "Could not contact the user session scheduler.")


def toggle_transfers():
    if portable.enabled:
        paused = sync.preference("paused") != "yes"
        portable.scheduler.pause(paused)
        return "Scheduled transfers paused." if paused else "Scheduled transfers resumed."
    service = "drive-desk-sync.service"
    if sync.preference("paused") == "yes":
        freezer = subprocess.run(["systemctl", "--user", "show", "-p", "FreezerState", "--value", service],
                                 capture_output=True, text=True)
        if freezer.stdout.strip() in ("frozen", "freezing"):
            timer("thaw", service)
        sync.configure("paused", "no")
        timer("start", "--no-block", service)
        return "Scheduled transfers resumed."
    sync.configure("paused", "yes")
    active = subprocess.run(["systemctl", "--user", "show", "-p", "MainPID", "--value", service],
                            capture_output=True, text=True)
    if active.stdout.strip() not in ("0", ""):
        timer("freeze", service)
    return "Scheduled transfers paused."


def preferences(parent):
    proxy = combo(["Use system proxy environment", "Direct connection"])
    proxy.set_active(int(sync.preference("proxy") == "direct"))
    notes = Gtk.CheckButton(label="Notify me about sync errors")
    notes.set_active(sync.preference("notifications", "on") == "on")
    usb = Gtk.CheckButton(label="Offer to back up removable drives while Drive Desk is open")
    usb.set_active(sync.preference("usb") == "on")
    startup = Gtk.CheckButton(label="Start folder scheduler at sign-in")
    if portable.enabled:
        enabled = sync.preference("portable-login") == "on"
    else:
        enabled = subprocess.run(["systemctl", "--user", "is-enabled", "--quiet", "drive-desk-sync.timer"]).returncode == 0
    startup.set_active(enabled)
    keys = Gtk.Button(label="Open GNOME keyboard shortcuts…")
    keys.connect("clicked", lambda *_: portable.settings_panel("keyboard") if portable.enabled else
                 subprocess.Popen(["gnome-control-center", "keyboard"]))
    if prompt(parent, "Save preferences", [("Proxy for scheduled transfers", proxy),
            ("Notifications", notes), ("Connected devices", usb), ("Background sync", startup),
            ("For a global search shortcut, assign the command drive-desk --search.", keys)]):
        sync.configure("proxy", "direct" if proxy.get_active() else "system")
        sync.configure("notifications", "on" if notes.get_active() else "off")
        sync.configure("usb", "on" if usb.get_active() else "off")
        if startup.get_active() != enabled:
            if portable.enabled:
                portable.login_start(startup.get_active(), lambda value:
                                     sync.configure("portable-login", "on" if value else "off"))
            else:
                timer("enable" if startup.get_active() else "disable", "--now", "drive-desk-sync.timer")


def schedule(parent, account, kind, remote="root", name="My Drive", team="", local_start=None, pin=None):
    if portable.enabled:
        # The worker needs a persistent filesystem path, including after logout.
        folder_dialog = Gtk.FileChooserDialog(title="Local folder", transient_for=parent,
                                              action=Gtk.FileChooserAction.SELECT_FOLDER)
        folder_dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Select", Gtk.ResponseType.ACCEPT)
        chooser = Gtk.FileChooserButton.new_with_dialog(folder_dialog)
    else:
        chooser = Gtk.FileChooserButton.new("Local folder", Gtk.FileChooserAction.SELECT_FOLDER)
    chooser.set_local_only(True)
    if local_start:
        chooser.set_filename(local_start)
    up, down = (Gtk.SpinButton.new_with_range(0, 10000000, 1) for _ in range(2))
    wording = {
        "pin": "Choose an empty folder for " + name + ". Changes to this file sync both ways. Other files placed here stay local.",
        "mirror": "Choose an empty folder. Offline edits and deletions sync both ways with " + name + ".",
        "sync local": "Choose a local folder. Its files will sync both ways, including deletions, with a new folder in My Drive / Drive Desk computers.",
        "backup": "Choose a folder to upload into My Drive / Drive Desk backups. Local deletions leave cloud copies intact."
    }[kind]
    if not prompt(parent, "Create " + kind, [(wording, chooser), ("Upload KiB/s (0 = unlimited)", up),
                                             ("Download KiB/s (0 = unlimited)", down)]):
        return ""
    if not chooser.get_filename():
        raise ValueError("Select a local folder.")
    if not portable.enabled:
        timer("enable", "--now", "drive-desk-sync.timer")
    key = sync.add_job(account, kind, chooser.get_filename(), remote, name, team,
                       up.get_value_as_int(), down.get_value_as_int(), pin)
    if portable.enabled:
        portable.scheduler.enable(portable.scheduler.app)
        portable.scheduler.start()
    else:
        timer("start", "--no-block", "drive-desk-sync.service")
    return key


class Jobs(Gtk.Window):
    def __init__(self, parent, account):
        super().__init__(title="Scheduled folders", transient_for=parent)
        self.set_destroy_with_parent(True)
        self.account = account
        self.set_default_size(680, 340)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=14)
        self.add(box)
        self.picker = Gtk.ComboBoxText()
        box.pack_start(self.picker, False, False, 0)
        self.detail = Gtk.Label(xalign=0, wrap=True, selectable=True)
        box.pack_start(self.detail, True, True, 0)
        add = Gtk.Box(spacing=5)
        box.pack_start(add, False, False, 0)
        for label, kind in [("Mirror My Drive…", "mirror"), ("Sync local folder…", "sync local"),
                            ("Back up…", "backup")]:
            widget = button(add, label, lambda k=kind: self.action(k))
            widget.set_sensitive(bool(account))
        self.row = Gtk.Box(spacing=5)
        box.pack_start(self.row, False, False, 0)
        for label, action in [("Open folder", "open"), ("Storage", "storage"), ("Activity", "activity"), ("Pause / Resume", "pause"),
                              ("Limits…", "limits"), ("Disconnect…", "remove")]:
            button(self.row, label, lambda a=action: self.action(a))
        button(add, "Run enabled jobs", lambda: self.action("run"))
        self.pause_all = button(add, "Pause all", lambda: self.action("toggle"))
        self.message = Gtk.Label(xalign=0, wrap=True)
        box.pack_start(self.message, False, False, 0)
        self.picker.connect("changed", lambda *_: self.describe())
        self.show_all()
        self.refresh()
        source = GLib.timeout_add_seconds(3, self.refresh)
        self.connect("destroy", lambda *_: GLib.source_remove(source))

    def refresh(self):
        self.pause_all.set_label("Resume all" if sync.preference("paused") == "yes" else "Pause all")
        key = self.picker.get_active_id()
        with sync.database() as db:
            self.jobs = {j["id"]: j for j in db.execute(
                "SELECT * FROM jobs WHERE account=? OR ? IS NULL ORDER BY folder", (self.account, self.account))}
        self.picker.remove_all()
        for job in self.jobs.values():
            self.picker.append(job["id"], job["folder"])
        if not key or not self.picker.set_active_id(key):
            self.picker.set_active(0)
        self.describe()
        return True

    def describe(self):
        job = self.jobs.get(self.picker.get_active_id())
        self.row.set_sensitive(bool(job))
        if job:
            date = datetime.datetime.fromtimestamp(job["updated"]).strftime("%x %X") if job["updated"] else "—"
            status = ("Paused after current run. " if job["paused"] else "") + job["status"]
            self.detail.set_text(f"{job['kind'].title()} · {job['label']}\n{status}\nLast run: {date}")
        else:
            self.detail.set_text("Scheduled folders sync about every two minutes while you’re logged in.")

    def action(self, action):
        job = self.jobs.get(self.picker.get_active_id())
        try:
            if action in ("mirror", "backup", "sync local"):
                schedule(self, self.account, action)
            elif action == "toggle":
                self.message.set_text(toggle_transfers())
            elif action == "run" and sync.preference("paused") == "yes":
                raise ValueError("Resume all scheduled transfers first.")
            elif action == "run":
                if portable.enabled:
                    portable.scheduler.start()
                else:
                    timer("start", "--no-block", "drive-desk-sync.service")
            elif action == "open":
                if portable.enabled:
                    portable.open_folder(Path(job["folder"]).as_uri())
                else:
                    subprocess.Popen(["nautilus", job["folder"]])
            elif action == "storage":
                def inspect():
                    local = subprocess.run(["du", "-sx", "--block-size=1", "--", job["folder"]],
                                           capture_output=True, check=True, text=True)
                    used = int(local.stdout.split()[0])
                    free = shutil.disk_usage(job["folder"]).free
                    summary = f"Local folder: {used/2**30:.2f} GiB · Disk free: {free/2**30:.2f} GiB"
                    try:
                        quota = cloud.request(cloud.token_for(job["account"]), "about",
                                              {"fields": "storageQuota"})["storageQuota"]
                        summary += f" · Google storage used: {int(quota['usage'])/2**30:.2f} GiB"
                        if quota.get("limit"):
                            summary += f" of {int(quota['limit'])/2**30:.2f} GiB"
                    except Exception:
                        summary += " · Google storage unavailable"
                    return summary
                self.message.set_text("Checking storage…")
                async_call(self, inspect, lambda result, err: self.message.set_text(err or result))
            elif action == "activity":
                logdir = sync.state() / job["id"]
                entries = []
                for path in (logdir / "previous-run.log", logdir / "last-run.log"):
                    if path.exists():
                        with path.open("rb") as stream:
                            stream.seek(max(0, path.stat().st_size - 65536))
                            entries.append(stream.read().decode(errors="replace"))
                dialog = Gtk.Dialog(title="Recent transfer activity", transient_for=self)
                dialog.set_default_size(720, 420)
                dialog.add_button("Close", Gtk.ResponseType.CLOSE)
                text = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
                text.get_buffer().set_text("\n".join(entries) or job["status"])
                scroll = Gtk.ScrolledWindow()
                scroll.add(text)
                dialog.get_content_area().pack_start(scroll, True, True, 0)
                dialog.show_all()
                dialog.run()
                dialog.destroy()
            elif action == "pause":
                with sync.database() as db:
                    db.execute("UPDATE jobs SET paused=1-paused WHERE id=?", (job["id"],))
            elif action == "limits":
                fields = [Gtk.SpinButton.new_with_range(0, 10000000, 1) for _ in range(2)]
                for field, prop in zip(fields, ("up", "down")):
                    field.set_value(job[prop])
                if prompt(self, "Save limits", list(zip(("Upload KiB/s (0 = unlimited)",
                                                       "Download KiB/s (0 = unlimited)"), fields))):
                    with sync.database() as db:
                        db.execute("UPDATE jobs SET up=?,down=? WHERE id=?",
                                   (*[f.get_value_as_int() for f in fields], job["id"]))
            elif action == "remove" and prompt(self, "Disconnect folder", [
                    ("Stop scheduled transfers for this folder? Local and cloud files are retained.",
                     Gtk.Label(label=job["folder"]))]):
                with sync.database() as db:
                    result = db.execute("DELETE FROM jobs WHERE id=? AND status!='Running'", (job["id"],))
                    if not result.rowcount:
                        raise ValueError("A transfer is active. Pause future runs and disconnect after it finishes.")
            self.refresh()
        except (ValueError, OSError) as exc:
            self.message.set_text(str(exc))


def history(parent, account, notifications):
    title = "Notifications" if notifications else "Sync activity"
    dialog = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    dialog.set_default_size(620, 360)
    dialog.add_button("Close", Gtk.ResponseType.CLOSE)
    with sync.database() as db:
        rows = db.execute("""SELECT * FROM activity WHERE account=? AND (error=1 OR ?=0)
                          ORDER BY seq DESC""", (account, int(notifications))).fetchall()
        if notifications and rows:
            db.execute("UPDATE activity SET unread=0 WHERE account=? AND seq<=?", (account, rows[0]["seq"]))
    text = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                        left_margin=12, right_margin=12, top_margin=12)
    lines = []
    for row in rows:
        stamp = datetime.datetime.fromtimestamp(row["stamp"]).strftime("%x %X")
        lines.append(f"{stamp}   {row['folder']}\n{row['message']}")
    text.get_buffer().set_text("\n\n".join(lines) or ("No notifications." if notifications else "No recorded sync activity yet."))
    scroll = Gtk.ScrolledWindow()
    scroll.add(text)
    dialog.get_content_area().pack_start(scroll, True, True, 0)
    dialog.show_all()
    dialog.run()
    dialog.destroy()


class Search(Gtk.Window):
    def __init__(self, parent, account):
        super().__init__(title="Search Google Drive", transient_for=parent)
        self.set_destroy_with_parent(True)
        self.account = account
        self.page = ""
        self.serial = 0
        self.set_default_size(740, 480)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=12)
        self.add(box)
        bar = Gtk.Box(spacing=5)
        box.pack_start(bar, False, False, 0)
        self.entry = Gtk.SearchEntry(placeholder_text="Search files and contents")
        self.entry.connect("activate", lambda *_: self.load())
        bar.pack_start(self.entry, True, True, 0)
        self.view = combo(["All files", "Recent", "Starred", "Shared with me", "Trash"])
        bar.pack_start(self.view, False, False, 0)
        button(bar, "Search", self.load)
        self.store = Gtk.ListStore(str, str, object)
        self.tree = Gtk.TreeView(model=self.store)
        for i, title in enumerate(("Name", "Type")):
            self.tree.append_column(Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i))
        self.tree.connect("row-activated", lambda *_: self.action("open"))
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.tree)
        box.pack_start(scroll, True, True, 0)
        actions = Gtk.Box(spacing=5)
        box.pack_start(actions, False, False, 0)
        for label, key in [("Open", "open"), ("Copy link", "link"), ("Share…", "share"),
                           ("Star / Unstar", "star"), ("Keep offline…", "mirror")]:
            button(actions, label, lambda a=key: self.action(a))
        extra = Gtk.Box(spacing=5)
        box.pack_start(extra, False, False, 0)
        button(extra, "Email link…", lambda: self.action("email"))
        button(extra, "Trash / Restore…", lambda: self.action("trash"))
        self.more = button(actions, "More", lambda: self.load(True))
        self.note = Gtk.Label(xalign=0, wrap=True)
        box.pack_start(self.note, False, False, 0)
        self.view.connect("changed", lambda *_: self.load())
        self.show_all()
        self.load()

    def load(self, more=False):
        self.serial += 1
        serial = self.serial
        if not more:
            self.query = (self.view.get_active_text(), self.entry.get_text())
            self.store.clear()
            self.page = ""
        query, page = self.query, self.page
        self.more.set_sensitive(False)
        self.note.set_text("Searching…")
        def loaded(result, error):
            if serial != self.serial:
                return
            if error:
                self.note.set_text(error)
                self.more.set_sensitive(bool(page))
                return
            for item in result.get("files", []):
                kind = item["mimeType"].split("/")[-1].removeprefix("vnd.google-apps.")
                self.store.append([item["name"], kind, item])
            self.page = result.get("nextPageToken", "")
            self.more.set_sensitive(bool(self.page))
            suffix = " · Google returned a partial search." if result.get("incompleteSearch") else ""
            self.note.set_text(f"{len(self.store)} results loaded{suffix}")
        async_call(self, lambda: cloud.files(cloud.token_for(self.account), *query, page), loaded)

    def action(self, action):
        model, row = self.tree.get_selection().get_selected()
        if row is None:
            self.note.set_text("Select a search result.")
            return
        item = model[row][2]
        link = item.get("webViewLink") or "https://drive.google.com/open?id=" + quote(item["id"], safe="")
        try:
            if action == "open":
                Gtk.show_uri_on_window(self, link, Gtk.get_current_event_time())
            elif action == "link":
                Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(link, -1)
                self.note.set_text("Copied the link. Existing access permissions apply.")
            elif action == "email":
                subprocess.Popen(["xdg-email", "--subject", item["name"], "--body", link])
            elif action == "trash":
                trash = self.query[0] != "Trash"
                title = "Move to Trash" if trash else "Restore file"
                if prompt(self, title, [("Apply this change in Google Drive?", Gtk.Label(label=item["name"]))]):
                    async_call(self, lambda: cloud.request(cloud.token_for(self.account), cloud.file_resource(item),
                               {"supportsAllDrives": "true"}, "PATCH", {"trashed": trash}),
                               lambda _, err: self.note.set_text(err) if err else self.load())
            elif action == "mirror":
                if self.query[0] == "Trash":
                    raise ValueError("Restore this item in Drive before syncing it.")
                folder = item["mimeType"] == "application/vnd.google-apps.folder"
                if not folder and (item["mimeType"].startswith("application/vnd.google-apps.") or not item.get("parents")):
                    raise ValueError("Select a downloadable file with an accessible parent, or use Drive on the web for native documents.")
                if schedule(self, self.account, "mirror" if folder else "pin",
                            item["id"] if folder else item["parents"][0], item["name"], item.get("driveId", ""),
                            pin=None if folder else (item["id"], item["name"])):
                    self.note.set_text("Mirror scheduled.")
            elif action == "share":
                email, role = Gtk.Entry(), combo(["reader", "commenter", "writer"])
                if prompt(self, "Share and notify", [("Email address for access to " + item["name"], email),
                                                    ("Permission", role)]):
                    address, chosen = email.get_text().strip(), role.get_active_text()
                    async_call(self, lambda: cloud.share(cloud.token_for(self.account), item, address, chosen),
                               lambda _, err: self.note.set_text(err or "Sharing permission granted."))
            else:
                async_call(self, lambda: cloud.request(cloud.token_for(self.account), cloud.file_resource(item),
                           {"supportsAllDrives": "true"}, "PATCH", {"starred": not item.get("starred", False)}),
                           lambda _, err: self.note.set_text(err) if err else self.load())
        except (OSError, GLib.Error, ValueError) as exc:
            self.note.set_text(str(exc))
