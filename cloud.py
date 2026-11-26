"""Access the public Drive API with the selected GNOME account."""
import json
from urllib.error import HTTPError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from gi.repository import Gio

GOA = "org.gnome.OnlineAccounts"


def account_manager():
    return Gio.DBusObjectManagerClient.new_for_bus_sync(
        Gio.BusType.SESSION, Gio.DBusObjectManagerClientFlags.NONE, GOA,
        "/org/gnome/OnlineAccounts", None, None, None)


def google_accounts(manager):
    for obj in manager.get_objects():
        account = obj.get_interface(GOA + ".Account")
        files = obj.get_interface(GOA + ".Files")
        if account and files and account.get_cached_property("ProviderType").unpack() == "google":
            yield (account.get_cached_property("Id").unpack(),
                   account.get_cached_property("PresentationIdentity").unpack(),
                   files.get_cached_property("Uri").unpack(), obj)


def token_for(account_id):
    for ident, _, _, obj in google_accounts(account_manager()):
        if ident == account_id:
            oauth = obj.get_interface(GOA + ".OAuth2Based")
            return oauth.call_sync("GetAccessToken", None, Gio.DBusCallFlags.NONE, 60000, None).unpack()[0]
    raise ValueError("Reconnect this Google account and enable Files in Online Accounts.")


def request(token, resource, params=None, method="GET", data=None):
    url = "https://www.googleapis.com/drive/v3/" + resource
    if params:
        url += "?" + urlencode(params)
    body = json.dumps(data).encode() if data is not None else None
    req = Request(url, data=body, method=method, headers={
        "Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=35) as response:
            return json.load(response)
    except HTTPError as exc:
        raise ValueError(f"Google Drive returned HTTP {exc.code}. Check account access and permissions.") from exc


def files(token, view, text="", page=""):
    clauses = ["trashed = " + ("true" if view == "Trash" else "false")]
    if view == "Starred":
        clauses.append("starred = true")
    if view == "Shared with me":
        clauses.append("sharedWithMe")
    if text.strip():
        literal = text.strip().replace("\\", "\\\\").replace("'", "\\'")
        clauses.append(f"fullText contains '{literal}'")
    params = dict(q=" and ".join(clauses), pageSize=100,
                  fields="nextPageToken,incompleteSearch,files(id,name,parents,mimeType,webViewLink,driveId,starred)",
                  supportsAllDrives="true", includeItemsFromAllDrives="true",
                  orderBy="viewedByMeTime desc" if view == "Recent" else "modifiedTime desc")
    if page:
        params["pageToken"] = page
    return request(token, "files", params)


def file_resource(item):
    return "files/" + quote(item["id"], safe="")


def share(token, item, email, role):
    if role not in ("reader", "commenter", "writer") or "@" not in email:
        raise ValueError("Enter an email address and a sharing role.")
    return request(token, file_resource(item) + "/permissions",
                   dict(supportsAllDrives="true", sendNotificationEmail="true"),
                   "POST", dict(type="user", role=role, emailAddress=email))
