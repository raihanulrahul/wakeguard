"""Windows WMI + documented DXVA2 brightness API. Called only in a worker.

Brightness is the only monitor setting written. No gamma tricks or driver
installation. Unsupported/denied controls remain unchanged and are reported.
"""
from __future__ import annotations
import json
import os
import subprocess
from .runtime import powershell_path, ROOT, NO_WINDOW


class WmiDriver:
    name = "wmi"

    def _run(self, operation, payload=None):
        executable = powershell_path()
        if not executable:
            raise OSError("Windows PowerShell unavailable")
        process = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                  "-File", str(ROOT / "scripts/brightness.ps1"), "-Operation", operation],
                                 input=json.dumps(payload or {}), text=True, encoding="utf-8",
                                 capture_output=True, timeout=4, creationflags=NO_WINDOW)
        if process.returncode:
            raise OSError("WMI brightness unavailable or access denied")
        return json.loads(process.stdout.lstrip("\ufeff"))

    def discover(self):
        result = self._run("list")
        if not isinstance(result, list):
            raise ValueError("Unexpected WMI result")
        return result

    def read(self, identifier):
        result = self._run("read", {"id": identifier})
        return int(result["value"]), int(result["maximum"])

    def write(self, identifier, value):
        self._run("write", {"id": identifier, "value": int(value)})

    def close(self):
        pass


class DdcDriver:
    name = "ddc"

    def __init__(self):
        if os.name != "nt":
            raise OSError("Windows required")
        import ctypes as c
        from ctypes import wintypes as w
        self.c, self.w = c, w
        self.user = c.WinDLL("user32", use_last_error=True)
        self.dx = c.WinDLL("Dxva2", use_last_error=True)
        class Physical(c.Structure):
            _fields_ = [("handle", w.HANDLE), ("description", w.WCHAR * 128)]
        class Info(c.Structure):
            _fields_ = [("cbSize", w.DWORD), ("monitor", w.RECT), ("work", w.RECT),
                        ("flags", w.DWORD), ("device", w.WCHAR * 32)]
        class Device(c.Structure):
            _fields_ = [("cb", w.DWORD), ("name", w.WCHAR * 32), ("description", w.WCHAR * 128),
                        ("flags", w.DWORD), ("id", w.WCHAR * 128), ("key", w.WCHAR * 128)]
        self.Physical, self.Info, self.Device = Physical, Info, Device
        self.callback = c.WINFUNCTYPE(w.BOOL, w.HMONITOR, w.HDC, c.POINTER(w.RECT), w.LPARAM)
        self.user.EnumDisplayMonitors.argtypes = [w.HDC, c.POINTER(w.RECT), self.callback, w.LPARAM]
        self.user.EnumDisplayMonitors.restype = w.BOOL
        self.user.GetMonitorInfoW.argtypes = [w.HMONITOR, c.POINTER(Info)]
        self.user.GetMonitorInfoW.restype = w.BOOL
        self.user.EnumDisplayDevicesW.argtypes = [w.LPCWSTR, w.DWORD, c.POINTER(Device), w.DWORD]
        self.user.EnumDisplayDevicesW.restype = w.BOOL
        self.dx.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes = [w.HMONITOR, c.POINTER(w.DWORD)]
        self.dx.GetNumberOfPhysicalMonitorsFromHMONITOR.restype = w.BOOL
        self.dx.GetPhysicalMonitorsFromHMONITOR.argtypes = [w.HMONITOR, w.DWORD, c.POINTER(Physical)]
        self.dx.GetPhysicalMonitorsFromHMONITOR.restype = w.BOOL
        self.dx.DestroyPhysicalMonitors.argtypes = [w.DWORD, c.POINTER(Physical)]
        self.dx.DestroyPhysicalMonitors.restype = w.BOOL
        self.dx.GetMonitorCapabilities.argtypes = [w.HANDLE, c.POINTER(w.DWORD), c.POINTER(w.DWORD)]
        self.dx.GetMonitorCapabilities.restype = w.BOOL
        self.dx.GetMonitorBrightness.argtypes = [w.HANDLE, c.POINTER(w.DWORD), c.POINTER(w.DWORD), c.POINTER(w.DWORD)]
        self.dx.GetMonitorBrightness.restype = w.BOOL
        self.dx.SetMonitorBrightness.argtypes = [w.HANDLE, w.DWORD]
        self.dx.SetMonitorBrightness.restype = w.BOOL
        self.arrays = []
        self.handles = {}

    def discover(self):
        self.close()
        c, w = self.c, self.w
        monitors = []
        @self.callback
        def collect(handle, hdc, rect, data):
            monitors.append(handle)
            return True
        if not self.user.EnumDisplayMonitors(None, None, collect, 0):
            raise OSError("Cannot enumerate display monitors")
        for monitor in monitors:
            info = self.Info(); info.cbSize = c.sizeof(info)
            if not self.user.GetMonitorInfoW(monitor, c.byref(info)):
                continue
            device = self.Device(); device.cb = c.sizeof(device)
            if not self.user.EnumDisplayDevicesW(info.device, 0, c.byref(device), 1) or not device.id:
                continue
            count = w.DWORD()
            if not self.dx.GetNumberOfPhysicalMonitorsFromHMONITOR(monitor, c.byref(count)):
                continue
            if not 1 <= count.value <= 16:
                continue
            array = (self.Physical * count.value)()
            if not self.dx.GetPhysicalMonitorsFromHMONITOR(monitor, count, array):
                continue
            self.arrays.append(array)
            for index, physical in enumerate(array):
                caps, temps = w.DWORD(), w.DWORD()
                if not self.dx.GetMonitorCapabilities(physical.handle, c.byref(caps), c.byref(temps)) or not caps.value & 2:
                    continue
                identity = device.id + "|" + physical.description + "|" + str(index)
                self.handles[identity] = physical.handle
        return [{"id": identifier} for identifier in self.handles]

    def read(self, identifier):
        c, w = self.c, self.w
        handle = self.handles[identifier]
        minimum, current, maximum = w.DWORD(), w.DWORD(), w.DWORD()
        if not self.dx.GetMonitorBrightness(handle, c.byref(minimum), c.byref(current), c.byref(maximum)):
            raise OSError("Monitor does not support brightness readback")
        if not minimum.value <= current.value <= maximum.value:
            raise ValueError("Invalid monitor brightness range")
        return current.value, maximum.value

    def write(self, identifier, value):
        if not self.dx.SetMonitorBrightness(self.handles[identifier], int(value)):
            raise OSError("Monitor brightness write failed")

    def close(self):
        for array in self.arrays:
            self.dx.DestroyPhysicalMonitors(len(array), array)
        self.arrays = []
        self.handles = {}
