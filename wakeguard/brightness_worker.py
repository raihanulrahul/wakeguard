"""Owned brightness worker: restore on STOP, parent EOF, or lost heartbeat.

A wedged hardware driver can defeat restoration. The journal survives and the
next explicit restore attempt uses stable device IDs. No success is fabricated.
"""
from __future__ import annotations
import argparse
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
from .brightness import BrightnessLease


def emit(event):
    try:
        print(json.dumps(event), flush=True)
    except (BrokenPipeError, OSError):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal", required=True)
    parser.add_argument("--restore-only", action="store_true")
    args = parser.parse_args()
    if os.name != "nt":
        emit({"event": "brightness", "state": "unsupported", "message": "Native brightness requires Windows"})
        return
    from .brightness_native import WmiDriver, DdcDriver
    requests = queue.Queue()
    cancelled = threading.Event()
    clock = {"heartbeat": time.monotonic(), "cancelled_at": None}
    finished = threading.Event()

    def reader():
        try:
            for line in sys.stdin:
                data = json.loads(line)
                command = data.get("cmd")
                if command == "heartbeat":
                    clock["heartbeat"] = time.monotonic()
                elif command == "boost":
                    clock["heartbeat"] = time.monotonic()
                    requests.put(command)
                elif command in ("stop", "restore"):
                    cancelled.set()
                    return
        except (ValueError, OSError):
            pass
        finally:
            cancelled.set()

    def watchdog():
        while not finished.wait(.25):
            if time.monotonic() - clock["heartbeat"] > 5:
                cancelled.set()
            if cancelled.is_set():
                clock["cancelled_at"] = clock["cancelled_at"] or time.monotonic()
                if time.monotonic() - clock["cancelled_at"] > 10:
                    emit({"event": "brightness", "state": "restore_needed",
                          "message": "Brightness driver timed out; use monitor buttons / Restore brightness"})
                    os._exit(3)
    threading.Thread(target=reader, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()
    drivers = [WmiDriver()]
    try:
        drivers.append(DdcDriver())
    except OSError:
        pass
    lease = BrightnessLease(drivers, Path(args.journal), emit)
    try:
        recovered = lease.recover()
        if args.restore_only or not recovered:
            return
        while not cancelled.is_set():
            try:
                request = requests.get(timeout=.2)
            except queue.Empty:
                continue
            if request == "boost":
                lease.boost(cancelled.is_set)
    except Exception:
        emit({"event": "brightness", "state": "unsupported",
              "message": "Automatic brightness unavailable; use manual monitor controls"})
    finally:
        try:
            if lease.saved:
                lease.restore()
        finally:
            for driver in drivers:
                try:
                    driver.close()
                except Exception:
                    pass
            finished.set()


if __name__ == "__main__":
    main()
