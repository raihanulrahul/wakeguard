"""Isolated Find My worker. Run ONLY in .venv_phone; protocol on stdin/stdout.
Credentials never enter argv/logs/config. Only Play Sound is exposed.
"""
from __future__ import annotations
import argparse
import getpass
import json
import logging
import sys
from pathlib import Path

from wakeguard.model import data_home
from wakeguard.phone_errors import phone_error


def emit(event: str, **values) -> None:
    print(json.dumps({"event": event, **values}, ensure_ascii=True), flush=True)


class FindMyService:
    def __init__(self, factory=None):
        self.stage = "startup"
        self.factory = factory
        self.api = None
        self.selected = None
        self.available = {}
        self.authenticated = False
        self.otp_attempts = 0

    def dispatch(self, cmd: dict) -> dict:
        action = cmd.get("cmd")
        if action == "login":
            self.close()
            self.stage = "sign-in"
            if self.factory is None:
                from pyicloud import PyiCloudService
                self.factory = PyiCloudService
            email = str(cmd.get("email", "")).strip()
            password = str(cmd.get("password", ""))
            if not email or not password:
                raise ValueError("Email and password required")
            cookies = data_home() / "icloud_session"
            cookies.mkdir(parents=True, exist_ok=True)
            self.api = self.factory(email, password, cookie_directory=str(cookies),
                                    with_family=False, accept_terms=False, authenticate=False)
            self.api.authenticate()
            password = ""  # Library retains its own memory for this worker session.
            if getattr(self.api, "requires_2fa", False):
                return self._challenge()
            return self._devices()
        if action == "otp":
            self.stage = "verification"
            if self.api is None:
                raise RuntimeError("Connect first")
            self.otp_attempts += 1
            if self.otp_attempts > 3:
                self.close()
                raise RuntimeError("Too many verification attempts; reconnect deliberately")
            if not self.api.validate_2fa_code(str(cmd.get("code", "")).strip()):
                return self._challenge("Code rejected. Check the latest Apple code and try again.")
            if getattr(self.api, "requires_2fa", False):
                return {"event": "need_2fa", "message": "Authentication incomplete"}
            return self._devices()
        if action == "select":
            self.stage = "device selection"
            identifier = str(cmd.get("id", ""))
            if not self.authenticated or identifier not in self.available:
                raise ValueError("Select an exact listed device")
            self.selected = self.available[identifier]
            if getattr(self.selected, "sound_available", True) is False:
                self.selected = None
                raise RuntimeError("This device cannot play sound")
            return {"event": "ready", "name": self._data(self.selected).get("name", "Selected device")}
        if action == "play":
            self.stage = "sound request"
            if not self.authenticated or self.selected is None:
                raise RuntimeError("Phone not selected/authenticated")
            if getattr(self.api, "requires_2fa", False) or getattr(self.api, "requires_2sa", False):
                self.authenticated = False
                raise RuntimeError("Authentication expired")
            self.selected.play_sound(subject="WakeGuard alert")
            return {"event": "sound_sent", "message": "Request sent; audibility is not confirmed by the API."}
        if action == "stop":
            self.close()
            return {"event": "stopped"}
        raise ValueError("Unknown phone command")

    @staticmethod
    def _data(device):
        data = getattr(device, "data", None)
        return data if isinstance(data, dict) else {}

    def _challenge(self, message="Enter the six-digit code from Apple below. Keep this connection open."):
        self.stage = "code delivery"
        requester = getattr(self.api, "request_2fa_code", None)
        diagnostic = ""
        if callable(requester):
            try:
                if not requester():
                    message += " Automatic delivery was unavailable; use the code already shown on your iPhone, or cancel and reconnect."
            except Exception as exc:
                diagnostic = phone_error(exc, self.stage)["message"]
                message += " Delivery could not be confirmed. Use an existing code, or cancel and reconnect."
        return {"event": "need_2fa", "message": message, "diagnostic": diagnostic}

    def _devices(self):
        self.stage = "device discovery"
        if getattr(self.api, "requires_2fa", False) or getattr(self.api, "requires_2sa", False):
            raise RuntimeError("Account needs additional authentication not completed here")
        devices = list(self.api.devices)
        self.available = {}
        choices = []
        for device in devices:
            data = self._data(device)
            identifier = data.get("id")
            if identifier:
                self.available[str(identifier)] = device
                choices.append({"id": str(identifier), "name": str(data.get("name", "Unnamed device"))})
        if not choices:
            raise RuntimeError("No selectable devices returned")
        self.authenticated = True
        return {"event": "devices", "devices": choices}

    def close(self):
        if self.api is not None:
            try:
                manager = getattr(self.api, "_devices", None)
                if manager is not None and hasattr(manager, "stop_event"):
                    manager.stop_event.set()
            except Exception:
                pass
        self.api = self.selected = None
        self.available = {}
        self.authenticated = False
        self.otp_attempts = 0


def interactive():
    service = FindMyService()
    print("Find My Play Sound test. Credentials stay in this process; session files are local.")
    try:
        response = service.dispatch({"cmd": "login", "email": input("Apple account email: "),
                                     "password": getpass.getpass("Apple account password: ")})
        while response["event"] == "need_2fa":
            response = service.dispatch({"cmd": "otp", "code": input("Apple verification code: ")})
        choices = response["devices"]
        for index, item in enumerate(choices):
            print(f"{index + 1}. {item['name']}")
        selected = int(input("Exact device number: ")) - 1
        if not 0 <= selected < len(choices):
            raise ValueError("Invalid selection")
        service.dispatch({"cmd": "select", "id": choices[selected]["id"]})
        if input("Send Play Sound now? Type YES: ").strip() == "YES":
            response = service.dispatch({"cmd": "play"})
            print(response["message"])
    finally:
        service.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    if args.interactive:
        try:
            interactive()
        except Exception as exc:
            print(f"Phone test failed ({type(exc).__name__}). Check account/authentication/network. No credentials logged.")
            return 1
        return 0
    service = FindMyService()
    emit("phone_started")
    try:
        for line in sys.stdin:
            request = {}
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("Object expected")
                response = service.dispatch(request)
                emit(response.pop("event"), **response)
                if request.get("cmd") == "stop":
                    break
            except Exception as exc:
                event = phone_error(exc, service.stage)
                emit(event.pop("event"), **event)
            finally:
                if isinstance(request, dict):
                    request.clear()
                line = ""
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
