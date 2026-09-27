"""Temporary monitor brightness, isolated from Tk and from Python installation.

Hardware calls run in a child process with a renewable lease. Restoration is
journalled BEFORE the first write; a failed restore is never labelled success.
"""
from __future__ import annotations
import json
import os
import threading
import time
from pathlib import Path

from .model import atomic_json
from .runtime import Channel, ROOT, worker_python


class BrightnessLease:
    """Hardware-independent transaction. Drivers are injected for unit tests."""
    def __init__(self, drivers, journal: Path, emit=lambda event: None):
        self.drivers = {driver.name: driver for driver in drivers}
        self.journal = journal
        self.emit = emit
        self.saved = []
        self.errors = []
        self.active = False

    def _save(self):
        atomic_json(self.journal, {"schema": 1, "displays": self.saved})

    def recover(self):
        if self.journal.exists():
            raw = json.loads(self.journal.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("schema") != 1 or not isinstance(raw.get("displays"), list):
                raise ValueError("Brightness recovery record is invalid; use monitor controls")
            checked = []
            for entry in raw["displays"]:
                if (not isinstance(entry, dict) or entry.get("driver") not in self.drivers
                        or not isinstance(entry.get("id"), str)
                        or not isinstance(entry.get("value"), int)
                        or not 0 <= entry["value"] <= 100000):
                    raise ValueError("Invalid monitor recovery entry; no values written")
                checked.append(entry)
            self.saved = checked
            return self.restore()
        return True

    def boost(self, cancelled=lambda: False):
        if self.active:
            return
        if self.saved or self.journal.exists():
            if not self.recover():
                self.emit({"event": "brightness", "state": "restore_needed",
                           "message": "Previous brightness could not be restored. No new boost attempted."})
                return
        self.active = True
        self.errors = []
        raised = 0
        found = 0
        for name, driver in self.drivers.items():
            if cancelled():
                break
            try:
                displays = driver.discover()
            except Exception:
                self.errors.append(name + ": unavailable")
                continue
            for display in displays:
                if cancelled():
                    break
                found += 1
                try:
                    original, maximum = driver.read(display["id"])
                    if not (isinstance(original, int) and isinstance(maximum, int)
                            and 0 <= original <= maximum <= 100000 and maximum > 0):
                        raise ValueError("Unsafe brightness range")
                    if original == maximum:
                        raised += 1
                        continue
                    self.saved.append({"driver": name, "id": display["id"], "value": original})
                    self._save()
                    if cancelled():
                        break
                    driver.write(display["id"], maximum)
                    actual, _ = driver.read(display["id"])
                    if actual >= maximum - 1:
                        raised += 1
                    else:
                        self.errors.append(name + ": maximum not confirmed")
                except Exception:
                    self.errors.append(name + ": display unsupported or write failed")
        self.emit({"event": "brightness", "state": "boosted" if raised else "unsupported",
                   "confirmed": raised, "detected": found,
                   "message": f"Maximum brightness confirmed for {raised} display control(s). "
                              + ("Other controls unavailable; set those monitors manually." if self.errors or not found else "Previous settings will be restored.")})
        if cancelled():
            self.restore()

    def restore(self):
        pending = []
        total = len(self.saved)
        for entry in list(self.saved):
            try:
                driver = self.drivers[entry["driver"]]
                driver.discover()
                driver.write(entry["id"], entry["value"])
                actual, _ = driver.read(entry["id"])
                if abs(actual - entry["value"]) > 1:
                    raise RuntimeError("Brightness restore not confirmed")
            except Exception:
                pending.append(entry)
        self.saved = pending
        self.active = False
        if pending:
            self._save()
        elif self.journal.exists():
            self.journal.unlink()
        self.emit({"event": "brightness", "state": "restore_needed" if pending else "restored",
                   "message": (f"{len(pending)} display setting(s) could not be restored. Use Restore brightness or monitor controls."
                               if pending else (f"Previous brightness restored ({total} changed display control(s))."))})
        return not pending


class BrightnessController:
    """Nonblocking parent. No driver or network call occurs on the Tk thread."""
    def __init__(self, home: Path, enabled=True, testing=False, channel=None, clock=time.monotonic):
        self.home = home
        self.enabled = enabled
        self.testing = testing
        self.channel = channel or Channel()
        self.clock = clock
        self.active = False
        self.closing = False
        self.restore_started = None
        self.last_ping = 0.0
        self.status = "Brightness boost ready • hardware support checked during an alert"
        self.journal = home / "brightness-restore.json"
        self.generation = 0

    def begin(self):
        if self.testing or not self.enabled or os.name != "nt":
            self.status = "Brightness hardware not changed" if self.testing else "Automatic brightness disabled or unsupported here"
            return
        if self.active:
            return
        if self.channel.alive:
            self.status = "Previous brightness restore in progress; this alert remains visible"
            return
        self.channel.start([worker_python(), "-E", "-s", "-u", "-m", "wakeguard.brightness_worker",
                            "--journal", str(self.journal)])
        self.generation += 1
        self.active = True
        self.restore_started = None
        self.last_ping = self.clock()
        self.status = "Requesting maximum brightness on supported displays…"
        self.channel.send({"cmd": "boost"})

    def poll(self):
        result = []
        for event in self.channel.drain():
            if event.get("event") == "brightness":
                self.status = event.get("message", "Brightness status unavailable")
                result.append(event)
        if self.active and self.channel.alive and self.clock() - self.last_ping >= 1:
            self.channel.send({"cmd": "heartbeat"})
            self.last_ping = self.clock()
        if self.active and not self.channel.alive:
            self.active = False
            self.status = ("Brightness worker stopped; recovery available" if self.journal.exists()
                           else "Automatic brightness unavailable on these displays")
        if self.restore_started is not None and self.channel.alive and self.clock() - self.restore_started > 12:
            self.channel.stop()
            self.restore_started = None
            self.status = "Brightness restore timed out; use monitor controls / Restore brightness"
        return result

    def stop(self):
        self.active = False
        if self.channel.alive and self.restore_started is None:
            self.restore_started = self.clock()
            self.status = "Restoring previous display brightness…"
            try:
                self.channel.send({"cmd": "stop"})
            except Exception:
                self.status = "Brightness restore unconfirmed; use monitor controls"

    def restore_previous(self):
        self.stop()
        if self.testing or os.name != "nt" or self.channel.alive:
            return
        if not self.journal.exists():
            self.status = "No pending brightness restoration"
            return
        self.channel.start([worker_python(), "-E", "-s", "-u", "-m", "wakeguard.brightness_worker",
                            "--journal", str(self.journal), "--restore-only"])
        self.restore_started = self.clock()
        self.status = "Retrying previous brightness restoration…"

    def close(self):
        self.stop()
        process = self.channel.process
        if process:
            def reap():
                try:
                    process.wait(timeout=12)
                except Exception:
                    try:
                        process.kill()
                    except OSError:
                        pass
            threading.Thread(target=reap, daemon=True).start()
