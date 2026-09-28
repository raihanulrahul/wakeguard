"""WakeGuard desktop with independent, camera-relative calibration channels.

The base controller retains keyboard/speech/lifecycle handling. This shell
adds channel availability, target selection and the guided desktop.
"""
from __future__ import annotations
import argparse
import copy
import json
import time
import tkinter as tk
from tkinter import messagebox

from .controller import App as CalibrationController
from .alarms import dpi_awareness
from .brightness import BrightnessController
from .dashboard import Dashboard
from .model import atomic_json
from .calibration import CalibrationError, CalibrationSession
from .face_context import valid_shape
from .runtime import worker_python


class App(CalibrationController):
    guided_calibration = True

    def __init__(self, root, demo=False, testing=False):
        self.screen_test_done = False
        self.screen_only_choice = False
        self.alert_consent = False
        self.capture_limited = False
        self.limitations_confirmed = False
        self.draft = None
        self.draft_config = {}
        self.draft_save_error = ""
        self.repair_targets = []
        self.cal_save_failed = False
        super().__init__(root, demo=demo, testing=testing)
        self.draft_path = self.home / "calibration-draft-v1.json"
        if self.draft_path.exists() and not self.demo:
            try:
                self.draft, self.draft_config = CalibrationSession.load_draft(self.draft_path)
                self.monitor_count_var.set(str(self.draft.monitor_count))
                self.glasses_setup_var.set(self.draft.glasses_enabled)
                self.detail.set("Saved calibration progress found. Preview the unchanged camera setup, then resume.")
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                self.detail.set("The saved draft could not be read. Your finished calibration is unchanged.")
                self.log("Calibration draft could not be loaded: " + type(exc).__name__, "DRAFT_ERROR")
        self.screen.brightness = self.brightness
        self._fit_window()
        if not self.demo and not self.testing and self.profile is not None and self.profile.report.get("context_method") != "face-relative-v1":
            self.profile = None
            self.detail.set("This update separates eye and head channels. Collect new eye references once; your old saved file is kept as a backup.")
            self.log("Older head-angle-dependent calibration kept on disk; new camera setup requested.", "CALIBRATION_UPDATE")
        self.view.render()
        self.preview_label.bind("<Button-1>", self.select_tracking_target)
        if not testing and self.brightness.journal.exists():
            self.brightness.restore_previous()

    def _fit_window(self):
        width = min(1060, max(860, self.root.winfo_screenwidth() - 80))
        height = min(850, max(620, self.root.winfo_screenheight() - 100))
        self.root.minsize(860, 620)
        self.root.geometry(f"{width}x{height}")

    def _settings(self):
        settings = super()._settings()
        settings.update(alert_pulse=True, alert_palette="Red / white", brightness_boost=True,
                        glasses_setup=False, glasses_mode="Auto")
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in ("alert_pulse", "alert_palette", "brightness_boost", "glasses_setup", "glasses_mode"):
                    if key in data:
                        settings[key] = data[key]
        except (OSError, ValueError):
            pass
        if settings["alert_palette"] not in ("Red / white", "Red / blue"):
            settings["alert_palette"] = "Red / white"
        if settings.get("glasses_mode") not in ("Auto", "On", "Off"):
            settings["glasses_mode"] = "Auto"
        settings["glasses_setup"] = bool(settings.get("glasses_setup", False))
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

    def save_glasses_preferences(self):
        if not hasattr(self, "glasses_mode_var"):
            return
        if self.cal is not None and self.state == "CALIBRATING":
            # The setup control is disabled during capture; also guard programmatic
            # changes so a preference cannot silently disagree with the active plan.
            self.glasses_setup_var.set(self.cal.glasses_enabled)
        self.settings["glasses_setup"] = bool(self.glasses_setup_var.get())
        self.settings["glasses_mode"] = self.glasses_mode_var.get() if self.glasses_mode_var.get() in ("Auto", "On", "Off") else "Auto"
        try:
            atomic_json(self.settings_path, self.settings)
        except OSError:
            self.detail.set("Glasses preferences could not be saved; current session still uses them.")
        if self.engine is not None:
            self.engine.glasses_mode = self.settings["glasses_mode"]

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
        if self.state in ("CALIBRATING", "VERIFYING", "MONITORING") or self.speech.busy or self._dialog_depth:
            return super().begin_calibration()
        if not self.audio_confirmed or self.latest is None or not self.latest.camera_ok or not 0 <= time.monotonic()-self.latest.t <= 1:
            return super().begin_calibration()
        if self.latest and self.latest.diagnostics.get("target_status", "locked") != "locked":
            self.detail.set("Select your face in Preview first. Only the GREEN tracking box provides calibration data.")
            return
        if self.draft is not None:
            return self.resume_calibration()
        self.save_glasses_preferences()
        if self.glasses_setup_var.get() and not (self.testing or self.demo):
            if not self._ask_setup(messagebox.askokcancel, "Glasses calibration",
                    "Start the main calibration with your glasses OFF. Use your normal posture; do not freeze your head.\n\n"
                    "At the end WakeGuard will tell you to put your glasses ON, then collect and check a short open/closed pair for each work screen.\n\n"
                    "Automatic glasses detection is personalized. If the visual signatures overlap, Auto will report uncertainty and the On/Off switch remains the hard override.",
                    parent=self.root):
                return
            if self.closing or self.latest is None:
                return
        self.draft_config = {"camera": self.camera_var.get(), "backend": self.backend.get()}
        super().begin_calibration()
        if self.cal is not None:
            self.cal.guided_pairs = True
            self.draft_config = {"camera": self.camera_var.get(), "backend": self.backend.get()}
            self._save_calibration_progress()
            self.view.render()

    def _save_calibration_progress(self):
        if self.cal is None:
            return
        self.draft = self.cal
        if self.demo and not self.testing:
            return
        try:
            self.cal.save_draft(self.draft_path, self.draft_config)
            self.draft_save_error = ""
        except (OSError, ValueError, TypeError) as exc:
            self.draft_save_error = "Progress is kept in this window, but could not be saved to disk."
            self.log(self.draft_save_error + " " + type(exc).__name__, "DRAFT_ERROR")

    def resume_calibration(self):
        if self.draft is None or self.state in ("CALIBRATING", "VERIFYING", "MONITORING") or self.speech.busy:
            return
        if not self.audio_confirmed:
            self.detail.set("Test spoken instructions first, then resume your saved captures.")
            return
        if self.latest is None or not self.latest.camera_ok or not 0 <= time.monotonic()-self.latest.t <= 1:
            self.detail.set("Start camera preview before resuming.")
            return
        if self.latest.diagnostics.get("target_status", "locked") != "locked":
            self.detail.set("Select your face in Preview before resuming.")
            return
        expected = {o.camera_key for values in self.draft.samples.values() for o in values}
        config = {"camera": self.camera_var.get(), "backend": self.backend.get()}
        if (expected and expected != {self.latest.camera_key}) or config != self.draft_config:
            self.detail.set("This draft belongs to a different camera setup. Restore that camera, or explicitly start a new calibration.")
            return
        if not self.testing and not self._ask_setup(messagebox.askokcancel, "Resume saved calibration",
                "Resume only if the camera position, chair setup and lighting have not changed.\n\n"
                "Completed captures will be kept. If you moved the camera, cancel and choose Start new calibration instead.", parent=self.root):
            return
        if self.closing or self.latest is None:
            return
        self.cal = self.draft
        self.monitor_count_var.set(str(self.cal.monitor_count))
        self.glasses_setup_var.set(self.cal.glasses_enabled)
        self.state, self.verified = "CALIBRATING", False
        self.cal_save_failed = False
        self.root.focus_set()
        if self.voice_enabled.get():
            self._start_voice()
        if self.cal.next_needed():
            self._prompt_stage()
        else:
            self._finish_calibration()
        self.view.render()

    def new_calibration(self):
        if self.state in ("CALIBRATING", "VERIFYING", "MONITORING") or self.speech.busy:
            return
        if self.draft is not None:
            if not self.testing and not self._ask_setup(messagebox.askyesno, "Start a new calibration?",
                    "Your saved progress will be archived locally. Start again only if you changed the camera setup or want new references.\n\n"
                    "To keep working on these captures, choose Resume instead.", parent=self.root):
                return
            if self.closing or self.state not in ("STOPPED", "PREVIEW"):
                return
            try:
                self.draft.save_draft(self.draft_path, self.draft_config)
            except (OSError, ValueError, TypeError):
                self.detail.set("Could not archive the saved progress. It has been kept in this window; a new calibration was not started.")
                return
            if self.draft_path.exists():
                from datetime import datetime
                try:
                    self.draft_path.rename(self.home / ("calibration-draft-backup-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json"))
                except OSError:
                    self.detail.set("Could not archive the saved draft. It has been kept; new calibration was not started.")
                    return
            self.draft = None
        self.begin_calibration()

    def repeat_capture(self, key, screen=0):
        if self.state != "CALIBRATING" or self.cal is None or self._dialog_depth:
            return
        lowered = self.eyes_lowered_possible
        self._cancel_speech()
        self.cal.select_capture(key, screen)
        self.cal_phase = "PROMPT"
        prepare = lambda: self._prompt_stage(brief=False)
        if lowered:
            self._recover_eyes(prepare)
        else:
            prepare()

    def retry_screen_pair(self):
        if self.cal is None or not self.repair_targets:
            return
        self.cal.mark_repair(self.repair_targets, "Repeat this monitor's open/closed pair")
        self.repeat_capture(*self.repair_targets[0])

    def keep_previous_capture(self):
        if self.cal is None or self.state != "CALIBRATING" or self.cal_phase != "REVIEW":
            return
        if self.cal.keep_previous():
            self._cancel_speech()
            self.cal_good = True
            self.repair_targets = []
            self.cal_text.set("Earlier successful capture kept. Continue when ready.")
            self._save_calibration_progress()
            self.view.render()

    def add_glasses_steps(self):
        if self.cal is None or self.cal.glasses_enabled or self.cal_phase not in ("READY", "REVIEW") or self.speech.busy:
            return
        session = self.cal
        if not self.testing and not self._ask_setup(messagebox.askyesno, "Add glasses without restarting",
                "Were your glasses OFF for all base captures so far?\n\n"
                "If yes, the completed captures stay saved and short glasses-on pairs are added at the end. Keep glasses OFF until instructed.\n\n"
                "If no, choose No; these captures cannot be labelled glasses-off.", parent=self.root):
            self.detail.set("Keep this draft. Base eye captures made with glasses need corrected references before adding an off/on comparison.")
            return
        if self.closing or self.state != "CALIBRATING" or self.cal is not session:
            return
        self.cal.glasses_enabled = True
        self.glasses_setup_var.set(True)
        self.save_glasses_preferences()
        self._save_calibration_progress()
        self.detail.set("Glasses steps added. All saved captures kept. Stay glasses-OFF until prompted.")
        self.view.render()

    def choose_stage(self):
        if self.state != "CALIBRATING" or self.cal is None:
            return
        # The visible checklist selects an actual capture, including monitor.
        self.view.show_capture_list()

    def _calibration_failed(self, exc):
        self.cal_phase, self.cal_good = "REVIEW", False
        self.cal_save_failed = isinstance(exc, OSError)
        self.repair_targets = getattr(exc, "targets", [])
        if self.repair_targets:
            self.cal.mark_repair(self.repair_targets, str(exc))
            self.cal.select_capture(*self.repair_targets[0])
        self.detail.set(str(exc))
        self.cal_text.set(("Could not save the completed calibration. Try saving again; no captures need repeating. "
                           if self.cal_save_failed else "Needs attention: ") + str(exc))
        self._save_calibration_progress()
        self._say(self.cal_text.get(), role="notice")
        self.log("Calibration kept for repair: " + str(exc), "CALIBRATION_RETRY")

    def begin_verification(self):
        self.view.select("setup")
        if self.profile is not None and self.profile.report.get("context_method") == "face-relative-v1":
            # Current-session capabilities may be downgraded by a verification
            # check; the saved immutable calibration is never retrained here.
            self.profile = copy.deepcopy(self.profile)
            stages = [self.VERIFY[0]]
            channels = self.profile.report.get("channels", {})
            if channels.get("neck_down"):
                stages.append(CalibrationController.VERIFY[1])
            if channels.get("recline"):
                stages.append(CalibrationController.VERIFY[2])
            stages.append(CalibrationController.VERIFY[3])
            self.VERIFY = tuple(stages)
        super().begin_verification()

    def start_monitoring(self):
        limits = self._channel_limits()
        if self.mode.get() == "Super Alert" and self.profile is not None and not self.profile.report.get("channels", {}).get("recline", True):
            self.detail.set("Super Alert requires measured recline. Choose Normal/High Alert or collect a usable recline reference.")
            return
        if self.state == "PREVIEW" and self.verified and limits and not self.limitations_confirmed:
            if not self.testing and not messagebox.askyesno("Limited sensor coverage", "These support channels are unavailable: " + ", ".join(limits) +
                    ".\n\nEye monitoring and tracking-loss alerts remain active. Continue with these limitations?", parent=self.root):
                return
            self.limitations_confirmed = True
        if self.state == "PREVIEW" and self.verified and not self.screen_test_done and not self.testing:
            self.view.select("alerts")
            self.detail.set("Test and acknowledge the screen alert before monitoring.")
            return
        super().start_monitoring()
        if self.state == "MONITORING":
            self.engine.glasses_mode = self.glasses_mode_var.get()
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
            if self.cal is not None:
                self.cal.cancel_capture()
                self._save_calibration_progress()
            super().stop_all()
        finally:
            if hasattr(self, "brightness"):
                self.brightness.stop()
            if not self.closing and hasattr(self, "view"):
                self.preview_label.configure(height=5)
                if self.draft is not None:
                    self.cal_text.set("Calibration paused. Completed captures are kept; Preview and Resume when ready.")
                    self.detail.set(self.draft_save_error or "Completed captures saved locally. The unfinished take will need repeating.")
                self.view.render()

    def quit(self):
        if self.closing:
            return
        self.brightness.close()
        super().quit()

    def _channel_limits(self):
        if self.profile is None:
            return []
        return [name.replace("_", " ") for name, ready in self.profile.report.get("channels", {}).items() if not ready]

    def select_tracking_target(self, event):
        if self.state != "PREVIEW" or self.preview_photo is None:
            return
        width, height = self.preview_photo.width(), self.preview_photo.height()
        x = (event.x - (self.preview_label.winfo_width() - width)/2) / width
        y = (event.y - (self.preview_label.winfo_height() - height)/2) / height
        if not (0 <= x <= 1 and 0 <= y <= 1):
            return
        try:
            self.camera.send({"cmd":"select_target", "x":x, "y":y})
            self.verified = False
            self.detail.set("Tracking selection requested. The GREEN box must stay on you; other faces are not eye data.")
        except RuntimeError:
            self.detail.set("Start the camera preview before selecting your face.")

    def _capture_done(self):
        self.capture_limited = False
        self.repair_targets = []
        if not self.cal.relative:
            return super()._capture_done()
        stage = self.cal.stage
        try:
            self.cal.finish()
            self.cal_good = True
            report = self.cal.capture_reports.get(self.cal.capture_report_key(*self.cal.capture_position()), {})
            self.capture_limited = bool(report.get("unavailable") or report.get("eye_limited"))
            if self.capture_limited:
                result = ("This glasses view is eye-limited. Saved with eyes marked unknown; posture and movement provide support. Continue, or repeat if you want another take."
                          if report.get("eye_limited") else "This supporting measurement is unavailable. Your eye setup is kept. Continue, or repeat this optional measurement.")
                self.log(f"{self.cal.label}: supporting channel unavailable; earlier eye references retained.", "CALIBRATION_LIMIT")
            else:
                result = self.cal.retake_note or ("Capture saved. " + ("Open and closed eyes checked together. " if stage.key in ("closed_main", "glasses_on_closed") else "") + "Continue when ready, or repeat only this capture.")
                self.log(f"{self.cal.label}: {self.cal.quality_summary()}. Head-angle fit is not an eye-data requirement.", "CALIBRATION_SAMPLE")
        except CalibrationError as exc:
            self.cal_good = False
            self.repair_targets = getattr(exc, "targets", [])
            self.detail.set(str(exc))
            self.log(str(exc), "CALIBRATION_SENSOR_LIMIT")
            reason = str(exc) if self.repair_targets else (self.cal.final_issue or self.cal.latest_issue or "Not enough usable eye measurements in this take.")
            result = self.cal.label + " needs a retry. " + reason + " Other saved captures are kept."
        self._save_calibration_progress()
        self.cal_phase = "PROMPT"
        self.cal_text.set(result)
        def review():
            if self.state == "CALIBRATING" and self.cal is not None:
                self._say(result, self._review_ready, role="review")
        if stage.eyes in ("half", "closed"):
            self._recover_eyes(review)
        else:
            prefix = stage.completion_cue + " " if stage.eyes == "absent" else ""
            self._say(prefix+result, self._review_ready, role="review")

    def _prompt_stage(self, brief=False):
        self.capture_limited = False
        self.cal_save_failed = False
        self.repair_targets = []
        super()._prompt_stage(brief=brief)
        if self.cal is not None:
            self._save_calibration_progress()
        if hasattr(self, "view"):
            self.view.canvas.yview_moveto(0)
            self.view.render()

    def _finish_calibration(self):
        super()._finish_calibration()
        if self.state == "PREVIEW" and self.cal is None:
            self.draft = None
            self.draft_save_error = ""
            try:
                self.draft_path.unlink(missing_ok=True)
            except OSError:
                self.log("Calibration saved, but old draft could not be removed.", "DRAFT_ERROR")
        if self.state == "PREVIEW" and self.profile and self.profile.report.get("context_method") == "face-relative-v1":
            limits = self._channel_limits()
            self.limitations_confirmed = False
            summary = "Eye references collected for your working screens. "
            summary += ("Unavailable support: " + ", ".join(limits) + ". ") if limits else "Neck and recline support collected. "
            glasses = self.profile.glasses_info()
            if glasses.get("enabled"):
                summary += ("Glasses Auto learned for all work screens. " if glasses.get("auto_available") else
                            "Glasses eye references are ready; Auto is uncertain on at least one view, so use the On/Off override there. ")
            self.detail.set(summary + "Check today's camera setup next.")
            self._say(summary + "Next, check the camera setup.")
            self.log(summary, "CALIBRATION_CHANNELS")

    def _verify_finish(self):
        if self.profile.report.get("context_method") != "face-relative-v1":
            return super()._verify_finish()
        name = self.VERIFY[self.verify_index][0]
        samples = self.verify_samples
        good = 0
        for o in samples:
            if not o.context_valid() or o.camera_key != self.profile.camera_key:
                continue
            ratios = self.profile.eye_ratios(o)
            if name in ("upright", "return"):
                # Match the measured natural-work distribution, not exact Euler
                # angles from a generic head mesh. Small normal motion is expected.
                okay = bool(ratios) and min(ratios) >= .70 and .55 <= o.area/self.profile.neutral["area"] <= 1.7
            elif name == "neck":
                value = self.profile.neck(o)
                okay = value is not None and value >= .6
            else:
                value = self.profile.recline(o)
                okay = value is not None and value >= .65
            good += bool(okay)
        accepted = len(samples)>=10 and good >= len(samples)*.65
        if not accepted and name in ("neck", "recline"):
            key = "neck_down" if name == "neck" else "recline"
            self.profile.report["channels"][key] = False
            self.limitations_confirmed = False
            self.log(f"{key}: supporting measurement unavailable in this session; eye references kept.", "VERIFY_LIMIT")
        elif not accepted:
            self.cal_phase = "";self.state = "PREVIEW";self.verified = False
            self.detail.set("Camera check needs attention: open eyes are not reliably measurable at your current position. Check the GREEN target box and eye detail; do not force a still pose.")
            self._say("The camera cannot reliably measure your eyes in this view. Check the preview; you do not need to hold your head still.")
            return
        self.verify_index += 1
        if self.verify_index < len(self.VERIFY):
            self._verify_prompt()
        else:
            self.state,self.cal_phase,self.verified = "PREVIEW","",True
            self.detail.set("Camera check complete. " + ("Unavailable support: " + ", ".join(self._channel_limits()) if self._channel_limits() else "Eye, neck and recline references available."))
            self._say("Camera check complete. Test your alerts, then start monitoring.")
            self.log(self.detail.get(), "VERIFY")

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
        if self.engine is not None:
            self.engine.glasses_mode = self.glasses_mode_var.get()
        if self.engine is not None and (self.screen.active or
                (self.brightness.restore_started is not None and self.brightness.channel.alive)):
            self.engine.display_light_until = time.monotonic() + 3
        super()._poll()
        if not self.closing:
            o = self.latest
            if o is not None and valid_shape(o.shape):
                if self.profile and self.profile.report.get("context_method") == "face-relative-v1":
                    mode = self.glasses_mode_var.get()
                    if self.engine is not None and self.state == "MONITORING":
                        gstate, gconf = self.engine.glasses_state, self.engine.glasses_confidence
                    elif mode in ("On", "Off"):
                        gstate, gconf = mode.lower(), 1.0
                    else:
                        gstate, gconf = self.profile.classify_glasses(o)
                    ratios = self.profile.eye_ratios(o, glasses_state=gstate)
                    auto = self.profile.glasses_info().get("auto_available", False)
                    glasses_text = (f"{mode} → {gstate.upper()} ({gconf:.0%})" if self.profile.glasses_info().get("enabled") else "not configured")
                    if mode == "Auto" and self.profile.glasses_info().get("enabled") and not auto:
                        glasses_text += " · Auto partial/uncertain; On/Off override available"
                    self.glasses_status.set("Glasses: " + glasses_text)
                    self.metrics.set(f"Eyes {self.fmt(min(ratios) if ratios else None)} · neck marker {self.fmt(self.profile.neck(o))} · recline {self.fmt(self.profile.recline(o))}\nTracking: {o.diagnostics.get('target_status', 'demo')} · {self.glasses_status.get()} · head/body/hand activity supports eye-obscured periods")
                else:
                    self.metrics.set(f"Left eye {self.fmt(o.left)} · right eye {self.fmt(o.right)} · local face context available\nSmall head movements are expected. Check the GREEN box stays on you; click your face to select it.")
            limits = self._channel_limits()
            if limits and self.state == "MONITORING":
                self.detail.set(self.detail.get().split(" | Unavailable support:")[0] + " | Unavailable support: " + ", ".join(limits))
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
