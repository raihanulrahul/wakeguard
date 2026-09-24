"""Owned workers and input. No worker ever calls Tk; no keys/frames logged."""
from __future__ import annotations
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def stop_process(process: subprocess.Popen | None) -> None:
    """Bounded shutdown of THIS process only, never taskkill-all-Python."""
    if process is None:
        return
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=.7)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=.7)
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                if stream:
                    stream.close()
            except (OSError, ValueError):
                pass


class Channel:
    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.events: queue.Queue = queue.Queue(maxsize=64)
        self.started = 0.0
        self.generation = 0

    def start(self, args: list[str]) -> None:
        self.stop()
        self.generation += 1
        token = self.generation
        self.started = time.monotonic()
        self.process = subprocess.Popen(args, cwd=ROOT, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        text=True, encoding="utf-8", errors="replace",
                                        bufsize=1, creationflags=NO_WINDOW)
        proc = self.process

        def reader() -> None:
            try:
                for line in proc.stdout:
                    if token != self.generation:
                        return
                    try:
                        item = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(item, dict):
                        continue
                    try:
                        self.events.put_nowait(item)
                    except queue.Full:
                        try:
                            self.events.get_nowait()
                        except queue.Empty:
                            pass
                        try:
                            self.events.put_nowait(item)
                        except queue.Full:
                            pass
            except (OSError, ValueError):
                pass
        threading.Thread(target=reader, name="wakeguard-worker-reader", daemon=True).start()

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def send(self, data: dict) -> None:
        if not self.alive:
            raise RuntimeError("Worker is not running")
        # Small commands only; never put passwords in argv, environment or logs.
        self.process.stdin.write(json.dumps(data, ensure_ascii=True) + "\n")
        self.process.stdin.flush()

    def drain(self) -> list[dict]:
        items = []
        for _ in range(64):
            try:
                items.append(self.events.get_nowait())
            except queue.Empty:
                break
        return items

    def stop(self) -> None:
        self.generation += 1
        process = self.process
        if process is not None and process.poll() is None:
            try:
                self.send({"cmd": "stop"})
                process.wait(timeout=.25)
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
                pass
        self.process = None
        stop_process(process)
        self.drain()


class Speech:
    """Only used in calibration; monitoring never invokes PC sound."""
    def __init__(self, demo: bool = False) -> None:
        self.process = None
        self.token = 0
        self.started = 0.0
        self.demo = demo
        self.pending = False

    @property
    def available(self) -> bool:
        return self.demo or (os.name == "nt" and powershell_path() is not None)

    @property
    def busy(self) -> bool:
        return self.pending

    def say(self, text: str) -> int:
        self.stop()
        self.token += 1
        self.started = time.monotonic()
        self.pending = True
        if self.demo:
            return self.token
        if not self.available:
            raise RuntimeError("Windows speech unavailable. Check audio/PowerShell before calibration.")
        self.process = subprocess.Popen([powershell_path(), "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts" / "speak.ps1"),
            "-Text", text], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        return self.token

    def poll(self) -> tuple[int, bool] | None:
        if not self.pending:
            return None
        if self.demo or (self.process and self.process.poll() is not None):
            okay = self.demo or self.process.returncode == 0
            self.pending = False
            stop_process(self.process)
            self.process = None
            return self.token, okay
        if time.monotonic() - self.started > 60:
            token = self.token
            self.stop()
            return token, False
        return None

    def stop(self) -> None:
        self.token += 1
        self.pending = False
        process, self.process = self.process, None
        stop_process(process)


def powershell_path() -> str | None:
    if os.name != "nt":
        return None
    path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    return str(path) if path.exists() else shutil.which("powershell.exe")


class InputMonitor:
    """Activity timestamps + a tiny control vocabulary. Does NOT record keys."""
    def __init__(self) -> None:
        self.last_activity = time.monotonic()
        self.events: queue.SimpleQueue = queue.SimpleQueue()
        self.listeners = []
        self.available = False

    def start(self) -> None:
        if self.listeners:
            return
        try:
            from pynput import keyboard, mouse
            held: set[str] = set()

            def name(key) -> str:
                value = str(getattr(key, "char", None) or key).lower()
                if value.startswith("key."):
                    value = value[4:]
                if value in ("ctrl_l", "ctrl_r"):
                    value = "ctrl"
                if value in ("shift_l", "shift_r"):
                    value = "shift"
                if value in ("alt_l", "alt_r"):
                    value = "alt"
                return {"\x01": "a", "\x11": "q", "\x13": "s", " ": "space"}.get(value, value)

            def press(key) -> None:
                self.last_activity = time.monotonic()
                k = name(key)
                if k in held:
                    return
                held.add(k)
                action = None
                if {"ctrl", "shift", "q"} <= held:
                    action = "quit"
                elif {"ctrl", "alt", "s"} <= held:
                    action = "stop"
                elif {"ctrl", "shift", "a"} <= held:
                    action = "space"
                elif k in ("space", "esc", "r", "b"):
                    action = k
                if action:
                    self.events.put(action)

            def release(key) -> None:
                held.discard(name(key))

            def touch(*args) -> None:
                self.last_activity = time.monotonic()

            self.listeners = [keyboard.Listener(on_press=press, on_release=release),
                              mouse.Listener(on_move=touch, on_click=touch, on_scroll=touch)]
            for listener in self.listeners:
                listener.start()
            self.available = True
        except Exception:
            self.stop()

    def age(self) -> float | None:
        return time.monotonic() - self.last_activity if self.available else None

    def stop(self) -> None:
        for listener in self.listeners:
            try:
                listener.stop()
            except Exception:
                pass
        self.listeners = []
        self.available = False
        while not self.events.empty():
            try:
                self.events.get_nowait()
            except queue.Empty:
                break
