"""Drive actions on streamed files in GNOME Files."""
from urllib.parse import urlencode

import gi
gi.require_version("Nautilus", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, GObject, Nautilus


class DriveDeskActions(GObject.GObject, Nautilus.MenuProvider):
    def get_file_items(self, files):
        if len(files) != 1 or files[0].get_uri_scheme() != "google-drive":
            return []
        location = files[0].get_location()
        items = []
        for name, title in [("open", "View in Google Drive"), ("copy", "Copy Google Drive link")]:
            item = Nautilus.MenuItem(name="DriveDesk::" + name, label=title)
            item.connect("activate", self.activate, location, name)
            items.append(item)
        return items

    def activate(self, item, location, action):
        def received(file, result):
            try:
                info = file.query_info_finish(result)
                identifier = info.get_attribute_string("id::file")
                if not identifier:
                    return
                link = "https://drive.google.com/open?" + urlencode({"id": identifier})
                if action == "open":
                    Gio.AppInfo.launch_default_for_uri_async(link, None, None, None)
                else:
                    Gdk.Display.get_default().get_clipboard().set(link)
            except GLib.Error as exc:
                GLib.log_default_handler("Drive Desk", GLib.LogLevelFlags.LEVEL_WARNING, exc.message)
        location.query_info_async("id::file", Gio.FileQueryInfoFlags.NONE, GLib.PRIORITY_DEFAULT,
                                  None, received)
