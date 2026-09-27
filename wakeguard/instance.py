"""One WakeGuard UI per user; hold an install-folder lock for safe updates."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path


class InstanceGuard:
    def __init__(self, home: Path, root: Path):
        self.handle = None
        self.file = None
        self.kernel = None
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
            self.kernel.CreateMutexW.restype = wintypes.HANDLE
            self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            digest = hashlib.sha256(str(home.resolve()).lower().encode()).hexdigest()[:24]
            self.handle = self.kernel.CreateMutexW(None, False, "Local\\WakeGuard-" + digest)
            if not self.handle:
                raise OSError("Cannot create WakeGuard instance guard")
            if ctypes.get_last_error() == 183:
                self.close()
                raise RuntimeError("WakeGuard is already open. Restore it from the taskbar rather than launching another copy.")
        try:
            lock = root / ".bootstrap" / "wakeguard-running.lock"
            lock.parent.mkdir(exist_ok=True)
            self.file = lock.open("a+b")
            if os.name == "nt":
                import msvcrt
                if self.file.tell() == 0:
                    self.file.write(b"0"); self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
        except Exception:
            self.close()
            raise

    def close(self):
        if self.file:
            self.file.close()
            self.file = None
        if self.handle and self.kernel:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
