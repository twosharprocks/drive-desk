"""Exercise the real loopback callback with simulated Google endpoints."""
import base64
import hashlib
import json
import time
import os
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

import oauth


class DirectConnectionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.enterContext(patch.dict(os.environ, XDG_STATE_HOME=tmp.name))
        self.client = dict(client_id="test", client_secret="test")
        self.user = dict(permissionId="123", emailAddress="test@example.invalid")

    def browser(self, url, denied=False):
        self.options = parse_qs(urlsplit(url).query)
        base = self.options["redirect_uri"][0]
        self.assertEqual(urlsplit(base).hostname, "127.0.0.1")
        def visit():
            try:
                urlopen(base + "?state=wrong&code=ignore", timeout=5).close()
            except HTTPError as error:
                self.bad_status = error.code
            params = dict(state=self.options["state"][0])
            params.update(dict(error="access_denied") if denied else dict(code="accepted"))
            urlopen(base + "?" + urlencode(params), timeout=5).close()
        thread = threading.Thread(target=visit)
        thread.start()
        self.addCleanup(thread.join, 6)

    def test_connection_refresh_and_forget(self):
        def exchange(fields):
            if fields["grant_type"] == "refresh_token":
                self.assertEqual(fields["refresh_token"], "renew")
                return dict(access_token="second", expires_in=3600)
            self.assertEqual(fields["code"], "accepted")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(fields["code_verifier"].encode()).digest())
            self.assertEqual(challenge.decode().rstrip("="), self.options["code_challenge"][0])
            return dict(access_token="first", refresh_token="renew", expires_in=0, scope=oauth.SCOPE)
        with patch.object(oauth, "exchange", side_effect=exchange) as calls:
            ident = oauth.connect(self.client, self.browser, lambda: False, lambda token: self.user)
            self.assertEqual(self.bad_status, 400)
            self.assertEqual(oauth.accounts(), [(ident, self.user["emailAddress"])])
            self.assertEqual(oauth.token_for(ident), "second")
            self.assertEqual(oauth.token_for(ident), "second")
            self.assertEqual(calls.call_count, 2)
        oauth.forget(ident)
        with self.assertRaisesRegex(ValueError, "Reconnect"):
            oauth.token_for(ident)

    def test_transfer_renewal_preserves_newer_account_state(self):
        ident = "direct:123"
        with oauth.database() as db:
            db.execute("INSERT INTO accounts VALUES(?,?,?,?,?,?,?)",
                       (ident, "a@example.invalid", "client", "secret", "original", "old", time.time()+300))
        account = oauth.current_account(ident)
        credentials = oauth.transfer_credentials(account)
        self.assertEqual(credentials["client_id"], "client")
        token = json.loads(credentials["token"])
        self.assertTrue(token["expiry"].endswith("+00:00"))
        self.assertEqual(token["refresh_token"], "original")
        token.update(access_token="new", refresh_token="rotated", expiry="2099-10-31T12:34:56.123456789Z")
        oauth.save_transfer_token(account, token)
        self.assertEqual(oauth.current_account(ident)["refresh"], "rotated")
        oauth.save_transfer_token(account, dict(token, access_token="stale"))
        self.assertEqual(oauth.token_for(ident), "new")
        oauth.forget(ident)
        oauth.save_transfer_token(account, token)
        self.assertEqual(oauth.accounts(), [])

    def test_temporary_token_service_failure(self):
        for code in (429, 503):
            with self.subTest(code=code), patch.object(oauth, "urlopen", side_effect=HTTPError(
                    "https://oauth2.googleapis.com/token", code, "Temporary error", {}, None)):
                with self.assertRaisesRegex(ValueError, "Try again later"):
                    oauth.exchange({"grant_type": "refresh_token"})

    def test_denial_saves_nothing(self):
        with self.assertRaisesRegex(ValueError, "declined"), patch.object(oauth, "exchange") as exchange:
            oauth.connect(self.client, lambda url: self.browser(url, True), lambda: False, lambda _: self.user)
        exchange.assert_not_called()
        self.assertEqual(oauth.accounts(), [])
