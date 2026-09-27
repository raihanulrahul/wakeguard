"""Replaceable screen renderer. Per-monitor windows with an escape on each."""
from __future__ import annotations
import os
import tkinter as tk
import time

ALERT_COLORS = {"Red / white": ("#ff0000", "#ffffff"), "Red / blue": ("#ff0000", "#0000ff")}
COLOUR_INTERVAL_MS = 1000  # A full two-colour cycle takes TWO seconds, not a strobe.
TEST_MAX_SECONDS = 10


def dpi_awareness():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


def monitors(root):
    try:
        from screeninfo import get_monitors
        result = [{"x": m.x, "y": m.y, "w": m.width, "h": m.height,
                   "primary": bool(getattr(m, "is_primary", False))} for m in get_monitors()]
        if result:
            return result
    except Exception:
        pass
    return [{"x": 0, "y": 0, "w": root.winfo_screenwidth(), "h": root.winfo_screenheight(), "primary": True}]


def place(window, geometry):
    """Set absolute desktop coordinates including monitors left of primary."""
    w, h, x, y = (int(geometry[k]) for k in ("w", "h", "x", "y"))
    window.geometry(f"{w}x{h}+0+0")
    window.update_idletasks()
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        user32.SetWindowPos.restype = wintypes.BOOL
        hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
        if not user32.SetWindowPos(hwnd, wintypes.HWND(-1), x, y, w, h, 0x0040 | 0x0010):
            raise OSError("Cannot position monitor overlay")
    else:
        window.geometry(f"{w}x{h}{x:+d}{y:+d}")


class ScreenBackend:
    name = "Screen alert"

    def __init__(self, root, acknowledge, stop_all, quit_app, monitor_provider=None, brightness=None):
        self.root = root
        self.brightness = brightness
        self.palette = "Red / white"
        self.started = 0.0
        self.acknowledge = acknowledge
        self.stop_all = stop_all
        self.quit_app = quit_app
        self.monitor_provider = monitor_provider or (lambda: monitors(root))
        self.windows = []
        self.fields = []
        self.job = None
        self.active = False
        self.test = False
        self.pulse = True
        self.phase = True
        self.reason = ""

    def start(self, reason, test=False):
        self.reason = reason
        if self.active:
            for field in self.fields:
                field.configure(text=reason)
            return
        self.active = True
        self.test = test
        self.phase = True
        self.started = time.monotonic()
        layout = self.monitor_provider()
        selected = next((i for i, m in enumerate(layout) if m.get("primary")), 0)
        text_window = None
        try:
            for i, geometry in enumerate(layout):
                window = tk.Toplevel(self.root)
                window.title("WakeGuard alert")
                window.overrideredirect(True)
                window.attributes("-topmost", True)
                window.configure(bg=ALERT_COLORS.get(self.palette, ALERT_COLORS["Red / white"])[0] if self.pulse else "#ffffff")
                self.windows.append(window)
                place(window, geometry)
                for seq, action in (("<space>", self.acknowledge), ("<Escape>", self.acknowledge),
                                    ("<Control-Shift-A>", self.acknowledge),
                                    ("<Control-Shift-a>", self.acknowledge),
                                    ("<Control-Alt-s>", self.stop_all),
                                    ("<Control-Shift-Q>", self.quit_app),
                                    ("<Control-Shift-q>", self.quit_app)):
                    window.bind(seq, lambda event, cb=action: self._key(cb))
                if i == selected:
                    panel = tk.Frame(window, bg="#172333", padx=36, pady=24)
                    panel.place(relx=.5, rely=.5, anchor="center")
                    tk.Label(panel, text="WakeGuard • CHECK IN", font=("Segoe UI", 26, "bold"),
                             fg="white", bg="#172333").pack(pady=(0, 12))
                    field = tk.Label(panel, text=reason, wraplength=min(620, int(geometry["w"] * .7)),
                                     font=("Segoe UI", 15), fg="white", bg="#172333")
                    field.pack(pady=8)
                    self.fields.append(field)
                    tk.Label(panel, text="SPACE / ESC: acknowledge     Ctrl+Alt+S: STOP EVERYTHING",
                             fg="white", bg="#172333", wraplength=580).pack(pady=12)
                    tk.Button(panel, text="ACKNOWLEDGE", command=self.acknowledge, width=22).pack(pady=4)
                    tk.Button(panel, text="STOP EVERYTHING", command=self.stop_all, width=22).pack(pady=4)
                    tk.Button(panel, text="QUIT", command=self.quit_app, width=22).pack(pady=4)
                    text_window = window
            if text_window is not None:
                text_window.focus_force()
            if self.brightness:
                try:
                    self.brightness.begin()
                except Exception:
                    self.brightness.status = "Automatic brightness failed; alert colours remain active"
            self.job = self.root.after(COLOUR_INTERVAL_MS, self._tick)
        except Exception:
            self.stop()
            raise

    @staticmethod
    def _key(callback):
        callback()
        return "break"

    def _tick(self):
        if self.job is not None:
            try:
                self.root.after_cancel(self.job)
            except tk.TclError:
                pass
        self.job = None
        if not self.active:
            return
        if self.test and time.monotonic() - self.started >= TEST_MAX_SECONDS:
            self.stop()
            return
        self.phase = not self.phase if self.pulse else True
        for window in self.windows:
            colours = ALERT_COLORS.get(self.palette, ALERT_COLORS["Red / white"])
            window.configure(bg=colours[0 if self.phase else 1] if self.pulse else "#ffffff")
        self.job = self.root.after(COLOUR_INTERVAL_MS, self._tick)

    def stop(self):
        if self.brightness:
            self.brightness.stop()
        self.active = self.test = False
        if self.job is not None:
            try:
                self.root.after_cancel(self.job)
            except tk.TclError:
                pass
        self.job = None
        for window in self.windows:
            try:
                window.destroy()
            except tk.TclError:
                pass
        self.windows.clear()
        self.fields.clear()
