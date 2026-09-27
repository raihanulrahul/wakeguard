"""WakeGuard 0.3 desktop shell over the verified 0.2.2 setup controller.

The calibration/risk logic stays in controller.py; this module owns the new
view, alert preferences, brightness lifecycle and GUI-launcher integration.
"""
from __future__ import annotations
import argparse
import json
import time
import tkinter as tk
from tkinter import messagebox

from .controller import App as CalibrationController
from .alarms import dpi_awareness
from .brightness import BrightnessController
from .dashboard import Dashboard
from .model import atomic_json
from .runtime import worker_python


class App(CalibrationController):
    def __init__(self, root, demo=False, testing=False):
        self.screen_test_done = False
        self.screen_only_choice = False
        self.alert_consent = False
        super().__init__(root, demo=demo, testing=testing)
        self.screen.brightness = self.brightness
        self._fit_window()
        self.view.render()
        if not testing and self.brightness.journal.exists():
            self.brightness.restore_previous()

    def _fit_window(self):
        width = min(1060, max(860, self.root.winfo_screenwidth() - 80))
        height = min(850, max(620, self.root.winfo_screenheight() - 100))
        self.root.minsize(860, 620)
        self.root.geometry(f"{width}x{height}")

    def _settings(self):
        settings = super()._settings()
        settings.update(alert_pulse=True, alert_palette="Red / white", brightness_boost=True)
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in ("alert_pulse", "alert_palette", "brightness_boost"):
                    if key in data:
                        settings[key] = data[key]
        except (OSError, ValueError):
            pass
        if settings["alert_palette"] not in ("Red / white", "Red / blue"):
            settings["alert_palette"] = "Red / white"
        return settings

    def _build_ui(self):
        self.brightness = BrightnessController(self.home, enabled=self.settings.get("brightness_boost", True),
                                               testing=self.demo or self.testing)
        self.view = Dashboard(self)

    def save_alert_preferences(self):
        self.settings.update(alert_palette=self.palette.get(), alert_pulse=self.pulse.get(),
                             brightness_boost=self.boost.get())
        self.brightness.enabled = self.boost.get()
        self.alert_consent = False
        if not self.boost.get():
            self.brightness.stop()
        try:
            atomic_json(self.settings_path, self.settings)
        except OSError:
            self.detail.set("Alert preferences could not be saved; current session still uses them.")

    def restore_brightness(self):
        self.screen.stop()
        self.brightness.restore_previous()

    def _start_camera(self):
        self.latest = None
        self.verified = False
        if not self.testing:
            self.inputs.start()
        if self.demo:
            return
        index = int(self.camera_var.get())
        if not 0 <= index <= 9:
            raise ValueError("Camera index must be 0–9")
        self.camera.start([worker_python(), "-E", "-s", "-u", "-m", "wakeguard.vision_worker",
                           "--camera", str(index), "--backend", self.backend.get()])
        self.settings.update(camera=index, backend=self.backend.get(), voice=self.voice_enabled.get())
        atomic_json(self.settings_path, self.settings)

    def begin_calibration(self):
        self.view.select("setup")
        super().begin_calibration()

    def begin_verification(self):
        self.view.select("setup")
        super().begin_verification()

    def start_monitoring(self):
        if self.state == "PREVIEW" and self.verified and not self.screen_test_done and not self.testing:
            self.view.select("alerts")
            self.detail.set("Test and acknowledge the screen alert before monitoring.")
            return
        super().start_monitoring()
        if self.state == "MONITORING":
            self.view.select("live")

    def _show_screen(self, reason, test=False):
        self.screen.palette = self.palette.get()
        self.screen.pulse = self.pulse.get()
        self.brightness.enabled = self.boost.get()
        super()._show_screen(reason, test=test)

    def test_screen(self):
        if self.state in ("CALIBRATING", "VERIFYING"):
            return
        if self.state == "MONITORING" and not self.testing:
            self.detail.set("Stop monitoring before running a manual screen test.")
            return
        if not self.testing and not self.demo and not self.alert_consent:
            message = ("This test fills ALL screens with vivid colours, changing once per second when alternation is selected. "
                       "Supported displays may temporarily go to maximum brightness.\n\n"
                       "Bright changing colours may be unsuitable for photosensitivity. Use steady mode instead when needed.\n\n"
                       "SPACE acknowledges; Ctrl+Alt+S stops everything. The test auto-stops after 10 seconds. Continue?")
            if not messagebox.askokcancel("Bright alert test", message, parent=self.root):
                return
            self.alert_consent = True
        super().test_screen()

    def acknowledge(self):
        if self.screen.active and self.screen.test:
            self.screen_test_done = True
        super().acknowledge()

    def stop_all(self):
        try:
            super().stop_all()
        finally:
            if hasattr(self, "brightness"):
                self.brightness.stop()
            if not self.closing and hasattr(self, "view"):
                self.preview_label.configure(height=5)

    def quit(self):
        if self.closing:
            return
        self.brightness.close()
        super().quit()

    def _frame(self, event):
        super()._frame(event)
        if self.preview_photo is not None:
            self.preview_label.configure(height=0)

    def _poll(self):
        if self.closing:
            return
        try:
            for event in self.brightness.poll():
                self.log(event.get("message", "Brightness status changed"), "BRIGHTNESS")
        except Exception:
            self.brightness.status = "Automatic brightness unavailable; use monitor controls"
        if self.engine is not None and (self.screen.active or
                (self.brightness.restore_started is not None and self.brightness.channel.alive)):
            self.engine.display_light_until = time.monotonic() + 3
        super()._poll()
        if not self.closing:
            self.view.render()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="Synthetic measurements; no camera/account or hardware brightness")
    args = parser.parse_args(argv)
    dpi_awareness()
    root = tk.Tk()
    App(root, demo=args.demo)
    root.mainloop()


if __name__ == "__main__":
    main()
