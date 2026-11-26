"""Access the public Drive API with the selected GNOME account."""
import json
from urllib.error import HTTPError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

import gi
gi.require_version("Goa", "1.0")
from gi.repository import Goa


def token_for(account_id):
    client = Goa.Client.new_sync(None)
    for obj in client.get_accounts():
        account = obj.get_account()
        if account.props.id == account_id and account.props.provider_type == "google" and obj.get_files():
            token, _ = obj.get_oauth2_based().call_get_access_token_sync(None)
            return token
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
