"""Real pinned pyicloud + real worker; synthetic HTTP only, no Apple account.
Run explicitly with the private phone interpreter, not the vision interpreter.
"""
import base64
import contextlib
import io
import json
import logging
import os
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
import pyicloud
from pyicloud.services.findmyiphone import FindMyiPhoneServiceManager
import phone_alarm_findmy as worker
from wakeguard.phone import PhoneBackend

class AppleResponses:
    def __init__(self, case):
        self.case = case
        self.calls = []
        self.deliveries = 0
        self.verified = False

    def send(self, req, **kwargs):
        path = urlsplit(req.url).path
        self.calls.append(req.method + ' ' + path)
        status, payload, headers = 200, {}, {}
        if path.endswith('/authorize/signin'):
            pass
        elif path.endswith('/signin/init'):
            payload = {'salt': base64.b64encode(b'synthetic-salt').decode(),
                       'b': base64.b64encode(b'\x05' * 256).decode(),
                       'c': 'synthetic-challenge', 'iteration': 1, 'protocol': 's2k'}
        elif path.endswith('/signin/complete'):
            if self.case == 'wrong_password':
                status, payload = 401, {'error': 'Synthetic bad credentials'}
            else:
                status, payload = 409, {'authType': 'hsa2'}
                if self.case != 'challenge_without_token':
                    headers['X-Apple-Session-Token'] = 'synthetic-token'
        elif path.endswith('/appleauth/auth'):
            payload = {'mode': 'sms', 'trustedPhoneNumber': {'id': 1, 'pushMode': 'sms'}}
        elif path.endswith('/verify/trusteddevice') or (path.endswith('/verify/phone') and req.method == 'PUT'):
            self.deliveries += 1
        elif path.endswith('/verify/phone/securitycode') or path.endswith('/verify/trusteddevice/securitycode'):
            if self.case == 'rejected_code':
                status, payload = 400, {'error': 'Synthetic invalid code'}
            else:
                self.verified = True
                headers['X-Apple-Session-Token'] = 'synthetic-token'
        elif path.endswith('/2sv/trust'):
            headers['X-Apple-Session-Token'] = 'synthetic-token'
        elif path.endswith('/accountLogin'):
            if not self.verified and self.case == 'challenge_token_rejected':
                status, payload = 401, {'error': 'Synthetic token not usable before 2FA'}
            else:
                payload = {'hsaTrustedBrowser': self.verified,
                           'dsInfo': {'dsid': 'synthetic-dsid', 'hsaVersion': 2},
                           'webservices': {'findme': {'url': 'https://example.invalid/fmip'}}}
                if not self.verified and self.case == 'challenge_missing_hsa_version':
                    payload.pop('dsInfo')
        elif path.endswith('/initClient') or path.endswith('/refreshClient'):
            if not self.verified:
                status, payload = 403, {'error': 'Synthetic unauthenticated device access'}
            else:
                payload = {'content': [{'id': 'synthetic-device', 'name': 'Synthetic iPhone', 'features': {'SND': True}}],
                           'serverContext': {}, 'userInfo': {}}
        else:
            raise AssertionError('Unplanned request: ' + req.method + ' ' + path)
        r = requests.Response()
        r.request, r.url, r.status_code, r.reason = req, req.url, status, 'Synthetic response'
        r.headers.update({'Content-Type': 'application/json', **headers})
        r._content = json.dumps(payload).encode()
        return r


class RealAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.dict(os.environ, {"WAKEGUARD_DATA_DIR": temp}))
        self.stack.enter_context(patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")))
        self.http = AppleResponses("challenge_without_token")
        self.stack.enter_context(patch.object(requests.Session, "send", new=lambda session, req, **kw: self.http.send(req, **kw)))
        self.stack.enter_context(patch.object(FindMyiPhoneServiceManager, "_start_monitor_thread",
            new=lambda manager: setattr(manager, "_monitor", SimpleNamespace(is_alive=lambda: True))))
        self.service = worker.FindMyService()
        self.addCleanup(self.service.close)
        logging.disable(logging.CRITICAL)

    def login(self):
        return self.service.dispatch({"cmd": "login", "email": "synthetic@example.invalid", "password": "synthetic-only"})

    def complete(self, case):
        self.http.case = case
        result = self.login()
        self.assertEqual(result["event"], "need_2fa")
        self.assertIsNotNone(self.service.api)
        self.assertFalse(self.service.authenticated)
        self.assertEqual(self.http.deliveries, 1)
        self.assertFalse(any("accountLogin" in call or "initClient" in call for call in self.http.calls))
        self.assertEqual(self.service.dispatch({"cmd": "otp", "code": "000000"})["event"], "devices")
        self.assertIsNone(self.service.selected)
        self.assertEqual(self.service.dispatch({"cmd": "select", "id": "synthetic-device"})["event"], "ready")

    def test_challenge_without_token(self): self.complete("challenge_without_token")
    def test_token_unusable_until_verified(self): self.complete("challenge_token_rejected")
    def test_missing_hsa_version(self): self.complete("challenge_missing_hsa_version")
    def test_partial_account_metadata(self): self.complete("challenge_partial_account")

    def test_bad_credentials_are_not_presented_as_verification(self):
        self.http.case = "wrong_password"
        with self.assertRaises(Exception): self.login()
        self.assertFalse(self.service.authenticated)
        self.assertEqual(self.http.deliveries, 0)

    def test_bad_code_preserves_session_for_retry(self):
        self.http.case = "rejected_code"
        self.login()
        api = self.service.api
        self.assertEqual(self.service.dispatch({"cmd": "otp", "code": "000000"})["event"], "need_2fa")
        self.assertIs(self.service.api, api)
        self.assertFalse(self.service.authenticated)
        self.http.case = "challenge_without_token"
        self.assertEqual(self.service.dispatch({"cmd": "otp", "code": "000000"})["event"], "devices")

    def test_worker_protocol_reaches_verification_ui_state(self):
        data = json.dumps({"cmd": "login", "email": "synthetic@example.invalid", "password": "synthetic-only"}) + "\n"
        output = io.StringIO()
        with patch.object(sys, "argv", ["phone_alarm_findmy.py"]), patch.object(sys, "stdin", io.StringIO(data)), contextlib.redirect_stdout(output):
            self.assertEqual(worker.main(), 0)
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        backend = PhoneBackend(SimpleNamespace(drain=lambda: events, alive=True))
        backend.poll()
        self.assertEqual(backend.status, "VERIFY ACCOUNT")
        self.assertTrue(backend.needs_code)
        self.assertFalse(backend.ready)
        self.assertNotIn("synthetic-only", output.getvalue())
        self.assertNotIn("synthetic@example.invalid", output.getvalue())

if __name__ == "__main__": unittest.main()
