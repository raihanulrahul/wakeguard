"""Main-process phone adapter: no pyicloud dependency and no blocking network."""
from __future__ import annotations
import os
import time
from pathlib import Path
from .runtime import Channel, ROOT


class PhoneBackend:
    name = "Find My iPhone"

    def __init__(self, channel=None, clock=time.monotonic):
        self.channel = channel or Channel()
        self.clock = clock
        self.status = "DISCONNECTED"
        self.pending = ""
        self.deadline = 0.0
        self.ready = False
        self.heard_test = False
        self.enabled = False
        self.last_attempt = -float("inf")
        self.cooldown = 130.0
        self.device_name = ""
        self.test_sent = False
        self.current_test = False

    def connect(self, email: str, password: str):
        self.stop()
        python = ROOT / ".venv_phone" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python.exists():
            raise RuntimeError("Phone environment missing. Run Setup-WakeGuard.ps1 first.")
        self.channel.start([str(python), "-u", str(ROOT / "phone_alarm_findmy.py")])
        self._send({"cmd": "login", "email": email, "password": password}, "login", 90)
        self.status = "CONNECTING"

    def _send(self, request, operation, timeout=45):
        if self.pending:
            raise RuntimeError("Wait for the current phone operation")
        self.pending = operation
        self.deadline = self.clock() + timeout
        try:
            self.channel.send(request)
        except Exception:
            self.pending = ""
            self.ready = False
            self.status = "ERROR"
            raise

    def otp(self, code):
        self._send({"cmd": "otp", "code": code}, "otp", 60)

    def select(self, identifier):
        self._send({"cmd": "select", "id": identifier}, "select")

    def trigger(self, test=False):
        if not self.ready or self.pending or (not test and not (self.enabled and self.heard_test)):
            return False
        now = self.clock()
        if now - self.last_attempt < self.cooldown:
            return False
        # Reserve BEFORE starting request: no duplicate flood during slow API calls.
        self.last_attempt = now
        self.current_test = test
        self._send({"cmd": "play"}, "play")
        self.status = "SENDING SOUND"
        return True

    def confirm_heard(self):
        if not self.ready or not self.test_sent:
            raise RuntimeError("Send and hear a test first")
        self.heard_test = True
        self.enabled = True
        self.status = "READY / TEST HEARD"

    def poll(self):
        events = []
        for event in self.channel.drain():
            kind = event.get("event")
            if kind == "phone_started":
                continue
            self.pending = ""
            if kind == "need_2fa":
                self.status = "VERIFY ACCOUNT"
            elif kind == "devices":
                self.status = "SELECT EXACT DEVICE"
            elif kind == "ready":
                self.ready = True
                self.status = "CONNECTED / TEST REQUIRED"
                self.device_name = event.get("name", "Selected device")
            elif kind == "sound_sent":
                self.status = "SOUND REQUEST SENT"
                self.test_sent = self.test_sent or self.current_test
            elif kind == "phone_error":
                self.ready = self.enabled = self.heard_test = False
                self.status = "ERROR / RECONNECT"
            events.append(event)
        if self.pending and self.clock() >= self.deadline:
            self.stop()
            self.status = "TIMED OUT / RECONNECT"
            events.append({"event": "phone_error", "message": "Phone request timed out. It may already have reached Apple; check the phone."})
        elif self.ready and not self.channel.alive:
            self.stop()
            self.status = "DISCONNECTED"
            events.append({"event": "phone_error", "message": "Phone worker stopped. Screen alerts remain available."})
        return events

    def stop(self):
        self.channel.stop()
        self.pending = ""
        self.ready = self.enabled = self.heard_test = self.test_sent = False
        self.current_test = False
        self.status = "DISCONNECTED"
        # Preserve last_attempt through reconnect/Stop to respect rate limit.

    def cancel_pending(self):
        if self.pending:
            self.stop()
        # No API here can retract a Play Sound request already accepted by Apple.
