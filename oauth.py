"""Google's installed-app OAuth flow for Drive search and scheduled sync."""
import base64
from contextlib import closing, contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
import threading
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

SCOPE = "https://www.googleapis.com/auth/drive"
PREFIX = "direct:"


def load_client(path):
    try:
        client = json.loads(Path(path).read_text())["installed"]
        if all(isinstance(client[k], str) and client[k] for k in ("client_id", "client_secret")):
            return {k: client[k] for k in ("client_id", "client_secret")}
    except (KeyError, ValueError, TypeError):
        pass
    raise ValueError("Choose a Google OAuth client JSON for a Desktop app.")


@contextmanager
def database():
    root = Path(os.getenv("XDG_STATE_HOME") or Path.home() / ".local/state") / "drive-desk" / "accounts"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = root / "google.sqlite"
    os.close(os.open(path, os.O_CREAT | os.O_RDWR, 0o600))
    with closing(sqlite3.connect(path, timeout=45)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE IF NOT EXISTS accounts
            (id TEXT PRIMARY KEY, email TEXT, client_id TEXT, client_secret TEXT,
             refresh TEXT, access TEXT, expires REAL)""")
        yield db


def accounts():
    with database() as db:
        return [(r["id"], r["email"]) for r in db.execute("SELECT id,email FROM accounts ORDER BY email")]


def forget(ident):
    with database() as db:
        db.execute("DELETE FROM accounts WHERE id=?", (ident,))


def exchange(fields):
    req = Request("https://oauth2.googleapis.com/token", data=urlencode(fields).encode())
    try:
        with urlopen(req, timeout=25) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code == 429 or 500 <= exc.code < 600:
            raise ValueError(f"Google authorization temporarily unavailable (HTTP {exc.code}). Try again later.") from None
        raise ValueError(f"Google declined the token request (HTTP {exc.code}). Reconnect Google Drive.") from None


def current_account(ident, min_validity=90):
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM accounts WHERE id=?", (ident,)).fetchone()
        if not row:
            raise ValueError("Reconnect this Google Drive account.")
        if row["expires"] > time.time() + min_validity:
            return row
        result = exchange(dict(client_id=row["client_id"], client_secret=row["client_secret"],
                               grant_type="refresh_token", refresh_token=row["refresh"]))
        db.execute("UPDATE accounts SET access=?, expires=?, refresh=? WHERE id=?",
                   (result["access_token"], time.time() + result["expires_in"],
                    result.get("refresh_token") or row["refresh"], ident))
        return db.execute("SELECT * FROM accounts WHERE id=?", (ident,)).fetchone()


def token_for(ident):
    return current_account(ident)["access"]


# Refresh ahead of expiry so requests that already carry the old token can finish.
TRANSFER_MARGIN = 300


@contextmanager
def transfer_credentials(ident):
    account = current_account(ident)
    key = secrets.token_urlsafe(32)

    class RefreshHandler(BaseHTTPRequestHandler):
        timeout = 5

        def log_message(self, *args):
            pass

        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", 0))
                if self.path != "/token" or not 0 < size <= 4096:
                    self.send_error(400)
                    return
                form = parse_qs(self.rfile.read(size).decode("ascii"))
                if (form.get("grant_type") != ["refresh_token"] or
                        form.get("refresh_token") != [key]):
                    self.send_error(403)
                    return
                renewed = current_account(ident, TRANSFER_MARGIN + 90)
                reply = json.dumps(dict(access_token=renewed["access"], token_type="Bearer",
                                        expires_in=max(1, int(renewed["expires"] - time.time()) - TRANSFER_MARGIN)))
            except (ValueError, OSError, sqlite3.Error):
                self.send_error(503)
                return
            body = reply.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with ThreadingHTTPServer(("127.0.0.1", 0), RefreshHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            expiry = datetime.fromtimestamp(account["expires"] - TRANSFER_MARGIN, timezone.utc).isoformat()
            token = dict(access_token=account["access"], refresh_token=key, expiry=expiry, token_type="Bearer")
            # Only this worker's ephemeral key goes into rclone's private config.
            yield dict(client_id="drive-desk", client_secret="local",
                       token_url=f"http://127.0.0.1:{server.server_port}/token", token=json.dumps(token))
        finally:
            server.shutdown()
            thread.join()


def connect(client, open_browser, cancelled, identify):
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    reply = {}

    class Callback(BaseHTTPRequestHandler):
        timeout = 2

        def log_message(self, *args):
            pass  # Callback URLs contain one-time authorization codes.

        def do_GET(self):
            parts = urlsplit(self.path)
            params = parse_qs(parts.query)
            if parts.path != "/" or params.get("state") != [state]:
                self.send_error(400)
                return
            reply.update(params)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b"Return to Drive Desk to see your connection status.")

    with HTTPServer(("127.0.0.1", 0), Callback) as server:
        server.timeout = 0.3
        redirect = f"http://127.0.0.1:{server.server_port}/"
        options = dict(client_id=client["client_id"], scope=SCOPE, redirect_uri=redirect,
                       response_type="code", access_type="offline", prompt="consent select_account",
                       state=state, code_challenge=challenge, code_challenge_method="S256")
        open_browser("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(options))
        deadline = time.monotonic() + 600
        while not reply:
            if cancelled() or time.monotonic() >= deadline:
                raise ValueError("Google sign-in cancelled or timed out.")
            server.handle_request()
    if "error" in reply or len(reply.get("code", [])) != 1 or cancelled():
        raise ValueError("Google sign-in was cancelled or access was declined.")
    result = exchange(dict(**client, grant_type="authorization_code", redirect_uri=redirect,
                           code_verifier=verifier, code=reply["code"][0]))
    if not result.get("refresh_token") or SCOPE not in result.get("scope", "").split():
        raise ValueError("Offline Drive access was not granted. Reconnect and allow Drive access.")
    user = identify(result["access_token"])
    ident = PREFIX + user["permissionId"]
    if cancelled():
        raise ValueError("Google sign-in cancelled.")
    with database() as db:
        db.execute("INSERT OR REPLACE INTO accounts VALUES(?,?,?,?,?,?,?)",
                   (ident, user["emailAddress"], client["client_id"], client["client_secret"],
                    result["refresh_token"], result["access_token"], time.time() + result["expires_in"]))
    return ident
