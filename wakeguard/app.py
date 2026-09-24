"""WakeGuard desktop controller. Tk never runs inference or network calls."""
from __future__ import annotations
import argparse
import base64
import csv
import io
import json
import os
import shutil
import sys
import time
import tkinter as tk
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox, simpledialog

from . import __version__
from .alarms import ScreenBackend, dpi_awareness
from .calibration import CalibrationSession, CalibrationError, STAGES
from .engine import Engine, MODES
from .model import Observation, Profile, data_home, atomic_json, angle_delta
from .phone import PhoneBackend
from .runtime import Channel, InputMonitor, Speech, ROOT, powershell_path


class App:
    def __init__(self, root, demo=False, testing=False):
        self.root, self.demo, self.testing = root, demo, testing
        self.home = data_home()
        self.profile_path = self.home / "calibration-v2.json"
        self.settings_path = self.home / "settings.json"
        self.settings = self._settings()
        self.camera = Channel()
        self.voice = Channel()
        self.speech = Speech(demo=demo or testing)
        self.phone = PhoneBackend()
        self.inputs = InputMonitor()
        self.profile = None
        self.engine = None
        self.latest = None
        self.last_decision = None
        self.state = "STOPPED"
        self.verified = False
        self.audio_confirmed = False
        self.cal = None
        self.cal_phase = ""
        self.cal_good = False
        self.speech_after = None
        self.voice_muted_until = 0.0
        self.verify_index = 0
        self.verify_samples = []
        self.verify_started = 0.0
        self.verify_last_seq = None
        self.last_actions = {}
        self.last_log_key = None
        self.last_log_time = 0.0
        self.seq = 0
        self.poll_job = None
        self.closing = False
        self.preview_photo = None
        self.root.title(f"WakeGuard {__version__}" + (" — SYNTHETIC DEMO" if demo else ""))
        self.root.geometry("600x820")
        self.root.minsize(560, 700)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self.request_quit)
        self.root.report_callback_exception = self._callback_error
        self._build_ui()
        self.screen = ScreenBackend(root, self.acknowledge, self.stop_all, self.quit)
        self._bind_keys()
        self._load_profile()
        if demo:
            from .demo import demo_profile
            self.profile = demo_profile()
        if not testing:
            self.poll_job = self.root.after(80, self._poll)

    def _settings(self):
        defaults = {"camera": 0, "backend": "auto", "slow_pulse": False, "voice": False}
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                defaults.update({k: data[k] for k in defaults if k in data})
        except (OSError, ValueError):
            pass
        return defaults

    def _build_ui(self):
        style = ttk.Style()
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"))
        style.configure("State.TLabel", font=("Segoe UI", 14, "bold"))
        shell = ttk.Frame(self.root)
        shell.pack(fill="both", expand=True)
        canvas = tk.Canvas(shell, highlightthickness=0)
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        outer = ttk.Frame(canvas, padding=12)
        body = canvas.create_window((0, 0), anchor="nw", window=outer)
        outer.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(body, width=event.width))
        ttk.Label(outer, text="WakeGuard" + (" · DEMO" if self.demo else ""), style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Local desk alert assistant · not a sleep diagnosis or safety guarantee").pack(anchor="w")
        top = ttk.Frame(outer); top.pack(fill="x", pady=6)
        self.mode = tk.StringVar(value="Normal")
        ttk.Combobox(top, textvariable=self.mode, values=list(MODES), state="readonly", width=14).pack(side="left")
        self.status = tk.StringVar(value="STOPPED — camera off")
        ttk.Label(top, textvariable=self.status, style="State.TLabel").pack(side="left", padx=12)
        self.battery = tk.DoubleVar(value=0)
        ttk.Progressbar(outer, maximum=100, variable=self.battery).pack(fill="x")
        self.battery_label = tk.StringVar(value="Concern 0 / 100 · higher = more concern, NOT probability")
        ttk.Label(outer, textvariable=self.battery_label).pack(anchor="w", pady=4)
        self.detail = tk.StringVar(value="Preview → test speech → calibrate → verify setup → connect/test phone → Start")
        ttk.Label(outer, textvariable=self.detail, wraplength=550).pack(fill="x", pady=4)
        self.metrics = tk.StringVar(value="Eyes / neck / chair: not measured")
        ttk.Label(outer, textvariable=self.metrics, wraplength=550).pack(fill="x", pady=4)
        controls = ttk.Frame(outer); controls.pack(fill="x", pady=4)
        self.camera_var = tk.StringVar(value=str(self.settings["camera"]))
        ttk.Label(controls, text="Camera").pack(side="left")
        ttk.Spinbox(controls, from_=0, to=9, textvariable=self.camera_var, width=3).pack(side="left", padx=4)
        self.backend = tk.StringVar(value=self.settings["backend"])
        ttk.Combobox(controls, textvariable=self.backend, values=["auto", "dshow", "msmf"], state="readonly", width=8).pack(side="left")
        ttk.Button(controls, text="Preview", command=self.preview).pack(side="left", padx=4)
        ttk.Button(controls, text="Test speech", command=self.test_speech).pack(side="left")
        self.voice_enabled = tk.BooleanVar(value=bool(self.settings["voice"]))
        ttk.Checkbutton(controls, text="Optional voice", variable=self.voice_enabled).pack(side="left", padx=4)
        row = ttk.Frame(outer); row.pack(fill="x", pady=4)
        ttk.Button(row, text="Calibrate", command=self.begin_calibration).pack(side="left")
        ttk.Button(row, text="Verify setup", command=self.begin_verification).pack(side="left", padx=4)
        ttk.Button(row, text="START", command=self.start_monitoring).pack(side="left", padx=4)
        ttk.Button(row, text="STOP EVERYTHING", command=self.stop_all).pack(side="left", padx=4)
        ttk.Button(row, text="Quit", command=self.request_quit).pack(side="left")
        self.cal_text = tk.StringVar(value="SPACE: acknowledge / ready / next · R: repeat · B: previous · Esc: cancel setup")
        ttk.Label(outer, textvariable=self.cal_text, wraplength=550).pack(fill="x", pady=5)
        row = ttk.Frame(outer); row.pack(fill="x")
        ttk.Button(row, text="Ready / Next / ACK", command=lambda: self.action("space")).pack(side="left")
        ttk.Button(row, text="Repeat", command=lambda: self.action("r")).pack(side="left", padx=4)
        ttk.Button(row, text="Previous", command=lambda: self.action("b")).pack(side="left")
        ttk.Button(row, text="Choose stage…", command=self.choose_stage).pack(side="left", padx=4)
        ttk.Button(row, text="Leaving seat", command=self.leaving_seat).pack(side="left")
        self.preview_label = ttk.Label(outer, text="Camera preview appears here. No frames are saved.", anchor="center")
        self.preview_label.pack(fill="both", expand=True, pady=6)
        row = ttk.Frame(outer); row.pack(fill="x")
        self.pulse = tk.BooleanVar(value=bool(self.settings["slow_pulse"]))
        ttk.Checkbutton(row, text="Slow pulse (otherwise steady bright)", variable=self.pulse).pack(side="left")
        ttk.Button(row, text="Test screen", command=self.test_screen).pack(side="left", padx=4)
        ttk.Button(row, text="ACK", command=self.acknowledge).pack(side="left")
        row = ttk.Frame(outer); row.pack(fill="x", pady=5)
        ttk.Button(row, text="Connect phone", command=self.connect_phone).pack(side="left")
        ttk.Button(row, text="Test phone sound", command=self.test_phone).pack(side="left", padx=4)
        ttk.Button(row, text="I heard the test", command=self.confirm_phone).pack(side="left")
        self.phone_text = tk.StringVar(value="Phone: DISCONNECTED — screen-only until connected and tested")
        ttk.Label(outer, textvariable=self.phone_text, wraplength=550).pack(anchor="w")
        self.logbox = tk.Text(outer, height=4, font=("Consolas", 9), state="disabled")
        self.logbox.pack(fill="x", pady=5)
        ttk.Label(outer, text="EMERGENCY: Ctrl+Alt+S stops everything · Ctrl+Shift+Q quits").pack(anchor="w")
        if self.demo:
            self.scenario = tk.StringVar(value="Awake")
            ttk.Combobox(outer, textvariable=self.scenario, state="readonly", values=["Awake", "Eyes closed", "Half closed", "Reclined awake", "Neck down", "Occluded", "Empty chair", "Camera failed"]).pack(fill="x")

    def _bind_keys(self):
        for sequence, action in (("<space>", "space"), ("<Escape>", "esc"), ("<r>", "r"), ("<b>", "b"),
                                 ("<Control-Shift-A>", "space"), ("<Control-Shift-a>", "space"),
                                 ("<Control-Alt-s>", "stop"), ("<Control-Shift-Q>", "quit"), ("<Control-Shift-q>", "quit")):
            self.root.bind_all(sequence, lambda event, a=action: self._key(event, a))
        self.root.bind("<Unmap>", self._restore_if_monitoring)

    def _restore_if_monitoring(self, event):
        if event.widget is self.root and self.state == "MONITORING" and not self.closing:
            self.root.after_idle(self.root.deiconify)

    def _key(self, event, action):
        if action not in ("stop", "quit", "esc") and isinstance(event.widget, (tk.Entry, ttk.Entry, ttk.Combobox, ttk.Spinbox, tk.Text)):
            return None
        if self.action(action):
            return "break"
        return None

    def action(self, action):
        now = time.monotonic()
        if now - self.last_actions.get(action, -100) < .35:
            return False
        self.last_actions[action] = now
        if action == "quit":
            self.quit(); return True
        if action == "stop":
            self.stop_all(); return True
        if self.screen.active and action in ("space", "esc"):
            self.acknowledge(); return True
        if action == "esc" and self.state in ("CALIBRATING", "VERIFYING"):
            self.stop_all(); return True
        if self.state == "CALIBRATING":
            if self.cal_phase == "READY" and action == "space":
                self._say("Prepare the requested posture. Three, two, one. Begin.", self._capture_begin)
                self.cal_phase = "PROMPT"
            elif self.cal_phase == "REVIEW" and action == "space" and self.cal_good:
                if self.cal.advance():
                    self._prompt_stage()
                else:
                    self._finish_calibration()
            elif self.cal_phase in ("REVIEW", "READY") and action == "r":
                self._prompt_stage()
            elif self.cal_phase in ("REVIEW", "READY") and action == "b":
                self.cal.repeat_previous(); self._prompt_stage()
            else:
                return False
            return True
        if self.state == "VERIFYING" and action == "space" and self.cal_phase == "READY":
            self.verify_samples = []
            self.verify_started = time.monotonic()
            self.verify_last_seq = None
            self.cal_phase = "CAPTURE"
            return True
        return False

    def log(self, message, event="INFO", decision=None):
        text = f"{datetime.now().strftime('%H:%M:%S')}  {message}"
        self.logbox.configure(state="normal")
        self.logbox.insert("end", text + "\n")
        if int(self.logbox.index("end-1c").split(".")[0]) > 100:
            self.logbox.delete("1.0", "20.0")
        self.logbox.see("end"); self.logbox.configure(state="disabled")
        try:
            path = self.home / ("events-" + datetime.now().strftime("%Y-%m-%d") + ".csv")
            new = not path.exists()
            with path.open("a", encoding="utf-8", newline="") as out:
                writer = csv.writer(out)
                if new:
                    writer.writerow(["time", "event", "mode", "state", "concern", "message"])
                writer.writerow([datetime.now().isoformat(timespec="seconds"), event, self.mode.get(), self.state,
                                 round(decision.battery, 1) if decision else "", message])
        except OSError:
            self.detail.set("Cannot write local event log; monitoring does not depend on it.")

    def _load_profile(self):
        if self.profile_path.exists():
            try:
                self.profile = Profile.load(self.profile_path)
                self.log("Validated saved calibration loaded. Current camera placement still needs verification.")
            except (ValueError, OSError, TypeError, KeyError):
                self.log("Saved calibration rejected. Run guided calibration; the old file was not overwritten.")

    def _start_camera(self):
        self.latest = None
        self.verified = False
        if not self.testing:
            self.inputs.start()
        if self.demo:
            return
        index = int(self.camera_var.get())
        if index < 0 or index > 9:
            raise ValueError("Camera index must be 0–9")
        self.camera.start([sys.executable, "-u", "-m", "wakeguard.vision_worker", "--camera", str(index), "--backend", self.backend.get()])
        self.settings.update(camera=index, backend=self.backend.get(), slow_pulse=self.pulse.get(), voice=self.voice_enabled.get())
        atomic_json(self.settings_path, self.settings)

    def preview(self):
        if self.state == "MONITORING":
            messagebox.showinfo("WakeGuard", "Stop monitoring before changing camera setup.", parent=self.root); return
        if self.state in ("CALIBRATING", "VERIFYING"):
            return
        try:
            self.camera.stop()
            self.state = "PREVIEW"
            self._start_camera()
            self.status.set("CAMERA STARTING")
            self.detail.set("Look at your MAIN monitor normally. Check that at least one eye and your face stay measurable.")
        except Exception as exc:
            self.stop_all()
            self.detail.set(f"Preview failed: {exc}")

    def _say(self, message, callback=None):
        self.speech_after = callback
        try:
            self.speech.say(message)
        except Exception:
            self.speech_after = None
            self.audio_confirmed = False
            self.cal_phase = "AUDIO FAILED"
            self.speech.stop()
            self.detail.set("Speech unavailable. Setup capture has stopped. Check Windows playback device, then Test speech.")

    def test_speech(self):
        if self.state == "MONITORING":
            messagebox.showinfo("WakeGuard", "Stop monitoring before testing calibration audio.", parent=self.root); return
        if self.state in ("CALIBRATING", "VERIFYING"):
            return
        def confirm():
            self.audio_confirmed = self.testing or self.demo or messagebox.askyesno("Calibration audio", "Did you clearly hear the speech?\nUse your preferred output device; monitoring will stay silent on the PC.", parent=self.root)
            self.log("Calibration speech confirmed." if self.audio_confirmed else "Calibration speech not confirmed.")
        self._say("WakeGuard audio check. Instructions will be spoken before each setup step. You may respond with the space key without looking at the screen.", confirm)

    def begin_calibration(self):
        if self.state == "MONITORING":
            messagebox.showinfo("WakeGuard", "Press Stop before calibration.", parent=self.root); return
        if self.cal_phase == "CAPTURE":
            return
        if not self.audio_confirmed:
            self.detail.set("First press Test speech and confirm you can hear it. Eye-closed stages will not start without audio.")
            return
        if self.latest is None or time.monotonic() - self.latest.t > 1 or not self.latest.camera_ok:
            self.detail.set("Open Preview and wait for live camera measurements first."); return
        if not self.testing and not messagebox.askokcancel("Calibration", "This is setup, not an alertness test. Remain safely seated; do not attempt it while unable to stay awake.\n\nOnly the labelled closed-eye captures last 3 seconds. Spoken prompts tell you when to open your eyes. SPACE confirms each step; R repeats; Esc stops everything.\n\nAllow calibration speech now?", parent=self.root):
            return
        self.state, self.verified = "CALIBRATING", False
        self.cal = CalibrationSession()
        if self.voice_enabled.get():
            self._start_voice()
        self._prompt_stage()

    def _start_voice(self):
        executable = powershell_path()
        if not executable:
            self.log("Offline voice unavailable here. SPACE/R/B still work."); return
        try:
            self.voice.start([executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts/voice.ps1")])
        except Exception:
            self.log("Offline voice could not start. Use the keyboard fallback.")

    def _prompt_stage(self):
        self.cal.recording = False
        self.cal_good = False
        self.cal_phase = "PROMPT"
        stage = self.cal.stage
        eye_notice = "Keep your eyes OPEN until you hear Begin. " if stage.eyes in ("closed", "half") else ""
        text = f"Step {self.cal.index + 1} of {len(STAGES)}. {eye_notice}{stage.instruction} Press space when ready."
        self.cal_text.set(text)
        self.detail.set("Prepare first. Collection starts ONLY after ready and countdown. R repeats; B goes back.")
        self._say(text, lambda: self._ready("CALIBRATING"))

    def _ready(self, state):
        if self.state == state:
            self.cal_phase = "READY"
            self.status.set("SETUP · READY")

    def _capture_begin(self):
        if self.state != "CALIBRATING":
            return
        self.cal.begin(time.monotonic())
        self.cal_phase = "CAPTURE"

    def _capture_done(self):
        try:
            self.cal.finish()
            self.cal_good = True
            result = "Sample complete. Press space to accept and continue, or R to repeat."
        except CalibrationError as exc:
            self.cal_good = False
            result = str(exc) + ". Press R to repeat, B to go back, or Escape to stop."
        self.cal_phase = "PROMPT"
        self.cal_text.set(result)
        self._say("Open your eyes. " + result, lambda: self._review_ready())

    def _review_ready(self):
        if self.state == "CALIBRATING":
            self.cal_phase = "REVIEW"

    def choose_stage(self):
        if self.state != "CALIBRATING" or self.cal_phase == "CAPTURE":
            return
        dialog = tk.Toplevel(self.root); dialog.title("Repeat a calibration stage"); dialog.attributes("-topmost", True)
        selected = tk.StringVar(value=STAGES[self.cal.index].key)
        ttk.Combobox(dialog, textvariable=selected, values=[s.key for s in STAGES], state="readonly", width=30).pack(padx=15, pady=15)
        def go():
            self.cal.index = [s.key for s in STAGES].index(selected.get())
            dialog.destroy(); self._prompt_stage()
        ttk.Button(dialog, text="Repeat selected stage", command=go).pack(pady=10)

    def _finish_calibration(self):
        try:
            profile = self.cal.build()
            if self.profile_path.exists():
                shutil.copy2(self.profile_path, self.home / ("calibration-backup-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json"))
            profile.save(self.profile_path)
            self.profile = profile
            self.voice.stop()
            self.cal = None
            self.state = "PREVIEW"
            self.cal_phase = ""
            self.detail.set("Calibration passed. Press Verify setup for a short independent posture check before Start.")
            self._say("Calibration passed. Keep your eyes open. Next, verify the setup before monitoring.")
            self.log("Calibration accepted and saved; prior valid baseline retained as a backup.", "CALIBRATION")
            if not profile.report.get("auto_away_enabled"):
                self.log("Automatic AWAY could not be distinguished. Use Leaving seat, or recalibrate camera placement.")
            if not profile.report.get("reclined_eyes_valid"):
                self.log("Reclined eyes are unobservable. Recline will cause tracking warnings; re-aim camera for eye coverage.")
        except (ValueError, TypeError, OSError) as exc:
            self.cal_phase, self.cal_good = "REVIEW", False
            self.detail.set("Calibration REJECTED: " + str(exc))
            self._say("Calibration was not accepted. " + str(exc) + ". Use Choose stage to repeat a labelled sample. Your previous calibration was not overwritten.")
            self.log("Calibration rejected: " + str(exc), "CALIBRATION_REJECTED")

    VERIFY = (
        ("upright", 5.0, "Sit upright with eyes normally open, looking at your MAIN monitor. Press space to check."),
        ("neck", 3.0, "Keep the chair upright. Lower your chin like the labelled neck-down sample, eyes open. Press space."),
        ("recline", 3.0, "Fully recline your chair, staying awake. Press space."),
        ("return", 3.0, "Return upright, eyes normally open. Press space for the final check."),
    )

    def begin_verification(self):
        if self.state not in ("PREVIEW", "STOPPED") or self.profile is None:
            self.detail.set("A valid calibration and live Preview are required first."); return
        if self.latest is None or time.monotonic() - self.latest.t > 1:
            self.detail.set("Start Preview first."); return
        if not self.audio_confirmed and not self.demo:
            self.detail.set("Test speech first so all verification instructions are audible."); return
        self.state = "VERIFYING"
        self.verify_index = 0
        self.verified = False
        self._verify_prompt()

    def _verify_prompt(self):
        self.cal_phase = "PROMPT"
        text = self.VERIFY[self.verify_index][2]
        self.cal_text.set(text)
        self._say(text, lambda: self._ready("VERIFYING"))

    def _verify_finish(self):
        name = self.VERIFY[self.verify_index][0]
        samples = self.verify_samples
        good = 0
        for o in samples:
            ratios = self.profile.eye_ratios(o)
            recline = self.profile.recline(o)
            neck = self.profile.neck(o)
            if o.camera_key != self.profile.camera_key or not o.pose_valid():
                continue
            if name in ("upright", "return"):
                n = self.profile.neutral
                okay = (ratios and min(ratios) >= .8 and recline is not None and recline < .3
                        and .72 <= o.area / n["area"] <= 1.35
                        and abs(angle_delta(o.pitch, n["pitch"])) < 15
                        and abs(angle_delta(o.yaw, n["yaw"])) < 20
                        and abs(o.brightness - self.profile.brightness) < 50)
            elif name == "neck":
                okay = neck is not None and neck >= .65
            else:
                okay = recline is not None and recline >= .7
            good += bool(okay)
        if len(samples) < 10 or good < len(samples) * .7:
            self.cal_phase = ""
            self.state = "PREVIEW"
            self.detail.set(f"Verification failed: {name}. Check camera angle/lighting and recalibrate or retry. Start remains blocked.")
            self._say("Setup verification failed. Keep your eyes open. Check the camera or repeat calibration.")
            self.log(f"Verification rejected: {name} ({good}/{len(samples)} usable matches).", "VERIFY_REJECTED")
            return
        self.verify_index += 1
        if self.verify_index < len(self.VERIFY):
            self._verify_prompt()
        else:
            self.state, self.cal_phase, self.verified = "PREVIEW", "", True
            self.detail.set("Setup checks passed. Connect/test the phone, then Start. Monitoring is NOT running yet.")
            self._say("Setup checks passed. Return to normal work posture. Monitoring starts only when you press Start.")
            self.log("Session posture verification passed.", "VERIFY")

    def start_monitoring(self):
        if self.state == "MONITORING":
            return
        if self.state != "PREVIEW" or not self.verified or self.profile is None:
            self.detail.set("Start blocked: run Preview, guided calibration if needed, and Verify setup."); return
        if self.phone.pending:
            self.detail.set("Wait for the phone setup operation to complete before Start."); return
        if self.latest is None or not self.latest.camera_ok or time.monotonic() - self.latest.t > .8:
            self.detail.set("Start blocked: camera data is not fresh."); return
        if not (self.phone.ready and self.phone.heard_test and self.phone.enabled):
            if not self.testing and not messagebox.askyesno("Phone not ready", "The phone alert is NOT ready. With eyes closed, a screen alone may not alert you.\n\nContinue explicitly in SCREEN-ONLY TEST mode?", parent=self.root):
                return
        self.speech.stop(); self.speech_after = None; self.voice.stop()
        self.screen.stop()
        self.engine = Engine(self.profile, self.mode.get())
        self.state = "MONITORING"
        self.status.set("MONITORING")
        self.cal_text.set("SPACE / ESC acknowledges · Ctrl+Alt+S stops everything · 3s open eyes clears (except forbidden recline)")
        self.log("Monitoring started; " + ("phone enabled." if self.phone.enabled else "SCREEN-ONLY TEST."), "START")

    def test_screen(self):
        if self.state in ("CALIBRATING", "VERIFYING"):
            return
        self.screen.pulse = self.pulse.get()
        self.screen.start("Screen test. Press SPACE or ESC. The STOP EVERYTHING button also remains available.", test=True)

    def acknowledge(self):
        had_alarm = self.screen.active or (self.engine is not None and self.engine.active)
        self.screen.stop()
        if self.engine:
            self.engine.acknowledge(time.monotonic())
        self.phone.cancel_pending()
        if had_alarm:
            self.log("Acknowledged. Sustained dangerous/unobservable conditions can re-alert after 1 second.", "ACK")

    def leaving_seat(self):
        if self.engine is not None and self.state == "MONITORING":
            self.engine.set_away(time.monotonic())
            self.screen.stop(); self.phone.cancel_pending()
            self.log("Leaving-seat grace. Monitoring resumes if you remain visible or return.", "AWAY")

    def connect_phone(self):
        if self.state in ("CALIBRATING", "VERIFYING", "MONITORING"):
            messagebox.showinfo("WakeGuard", "Connect the phone while in Preview or Stopped, before monitoring.", parent=self.root); return
        dialog = tk.Toplevel(self.root); dialog.title("Find My connection"); dialog.attributes("-topmost", True)
        ttk.Label(dialog, text="Runtime-only password. Session cookies stay in local Windows app data.\nNo account credentials are stored in the repository.", wraplength=430).pack(padx=15, pady=12)
        email = ttk.Entry(dialog, width=45); email.pack(padx=15, pady=5)
        password = ttk.Entry(dialog, width=45, show="*"); password.pack(padx=15, pady=5)
        def submit():
            account, secret = email.get(), password.get()
            password.delete(0, "end"); dialog.destroy()
            try:
                self.phone.connect(account, secret)
            except Exception as exc:
                self.detail.set(str(exc))
            finally:
                secret = ""
        ttk.Button(dialog, text="Connect", command=submit).pack(pady=10)
        ttk.Label(dialog, text="Email above; Apple account password below. Network access is required.").pack(padx=15, pady=5)
        email.focus_set()

    def _phone_event(self, event):
        kind = event.get("event")
        if kind == "need_2fa":
            code = simpledialog.askstring("Apple verification", event.get("message", "Enter the verification code sent by Apple:"), parent=self.root)
            if code:
                self.phone.otp(code)
            else:
                self.phone.stop()
        elif kind == "devices":
            devices = event.get("devices", [])
            dialog = tk.Toplevel(self.root); dialog.title("Select the EXACT phone"); dialog.attributes("-topmost", True)
            choices = [f"{i+1}. {d['name']}" for i, d in enumerate(devices)]
            var = tk.StringVar(value="")
            ttk.Label(dialog, text="Select your iPhone. No device is chosen automatically.").pack(padx=15, pady=8)
            combo = ttk.Combobox(dialog, values=choices, textvariable=var, state="readonly", width=42); combo.pack(padx=15, pady=8)
            def select():
                if var.get() in choices:
                    self.phone.select(devices[choices.index(var.get())]["id"]); dialog.destroy()
            ttk.Button(dialog, text="Use this device", command=select).pack(pady=8)
        elif kind == "sound_sent":
            self.detail.set("Find My request sent. After hearing the phone, press 'I heard the test'. PC cannot confirm audibility or cancel sound already sent.")
            self.log("Phone sound request submitted; physical audibility not verified automatically.", "PHONE_REQUEST")
        elif kind == "phone_error":
            self.detail.set(event.get("message", "Phone unavailable; reconnect before relying on it."))
            self.log("Phone backend unavailable. Screen alert remains local.", "PHONE_ERROR")

    def test_phone(self):
        if self.state in ("CALIBRATING", "VERIFYING"):
            return
        try:
            if not self.phone.trigger(test=True):
                self.detail.set("Phone test not sent: connect/select first, wait for pending operation, or allow the 130s rate limit to expire.")
        except Exception as exc:
            self.detail.set(str(exc))

    def confirm_phone(self):
        try:
            self.phone.confirm_heard()
            self.log("User confirmed audible phone test. Phone alerts enabled for this connection.", "PHONE_CONFIRMED")
        except Exception as exc:
            self.detail.set(str(exc))

    def stop_all(self):
        self.state = "STOPPED"
        self.cal_phase = ""
        self.cal = None
        self.speech_after = None
        self.verified = False
        self.engine = None
        self.latest = self.last_decision = None
        self.verify_samples = []
        errors = []
        for resource in (self.screen, self.speech, self.voice, self.camera, self.phone, self.inputs):
            try:
                resource.stop()
            except Exception as exc:
                errors.append(type(exc).__name__)
        self.status.set("STOPPED — camera off")
        self.battery.set(0)
        self.preview_label.configure(image="", text="Stopped. Camera, microphone and phone worker released.")
        self.preview_photo = None
        self.detail.set("All owned workers and screen alerts stopped. A Find My sound already sent must be dismissed on the phone.")
        self.log("All owned services stopped." + (" Cleanup errors: " + ", ".join(errors) if errors else ""), "STOP")

    def request_quit(self):
        if self.testing or messagebox.askyesno("Quit WakeGuard", "Stop all services and close WakeGuard?", parent=self.root):
            self.quit()

    def quit(self):
        if self.closing:
            return
        self.closing = True
        try:
            self.stop_all()
        finally:
            if self.poll_job is not None:
                try:
                    self.root.after_cancel(self.poll_job)
                except tk.TclError:
                    pass
            self.poll_job = None
            self.root.destroy()

    def _callback_error(self, typ, value, tb):
        self.stop_all()
        self.detail.set(f"Stopped after {typ.__name__}. Check the local diagnostic event; no silent restart.")
        self.log("GUI callback failed: " + typ.__name__, "FAULT")

    def _frame(self, event):
        o = Observation.from_dict(event["observation"])
        self.latest = o
        if event.get("preview"):
            try:
                from PIL import Image, ImageTk
                image = Image.open(io.BytesIO(base64.b64decode(event["preview"])))
                self.preview_photo = ImageTk.PhotoImage(image)
                self.preview_label.configure(image=self.preview_photo, text="")
            except Exception:
                pass
        if self.state == "CALIBRATING" and self.cal_phase == "CAPTURE":
            self.cal.add(o, time.monotonic())
        if self.state == "VERIFYING" and self.cal_phase == "CAPTURE" and o.seq != self.verify_last_seq:
            self.verify_last_seq = o.seq
            if o.camera_ok and time.monotonic() - o.t <= .8:
                self.verify_samples.append(o)

    @staticmethod
    def fmt(value):
        return "unknown" if value is None else f"{value:.2f}"

    def _poll(self):
        self.poll_job = None
        if self.closing:
            return
        try:
            now = time.monotonic()
            if self.demo and self.state != "STOPPED":
                from .demo import observation
                self.seq += 1
                self._frame({"observation": asdict(observation(now, self.seq, self.scenario.get()))})
            for event in self.camera.drain():
                if event.get("event") == "frame" and self.state != "STOPPED":
                    self._frame(event)
                elif event.get("event") == "camera_error":
                    self.detail.set(event.get("message", "Camera failed"))
                    self.log("Camera worker reported failure.", "CAMERA_ERROR")
            speech_result = self.speech.poll()
            if speech_result:
                _, okay = speech_result
                callback, self.speech_after = self.speech_after, None
                self.voice_muted_until = now + 1.0
                if okay:
                    if callback:
                        callback()
                else:
                    self.audio_confirmed = False
                    self.speech_after = None
                    if self.state in ("CALIBRATING", "VERIFYING"):
                        self.cal_phase = "AUDIO FAILED"
                        if self.cal:
                            self.cal.recording = False
                    self.detail.set("Speech failed. Open your eyes. Stop setup and check audio before trying again.")
            for event in self.voice.drain():
                if event.get("event") == "voice_error":
                    self.log(event.get("message", "Voice unavailable; use keyboard."))
                if event.get("event") == "command" and self.state == "CALIBRATING":
                    action = {"wakeguard ready": "space", "wakeguard next": "space", "wakeguard repeat": "r", "wakeguard back": "b", "wakeguard stop": "stop"}.get(event.get("text"))
                    if action and (action == "stop" or (not self.speech.busy and now >= self.voice_muted_until)):
                        self.action(action)
            for _ in range(50):
                if self.inputs.events.empty():
                    break
                self.action(self.inputs.events.get())
            for event in self.phone.poll():
                self._phone_event(event)
            self.phone_text.set("Phone: " + self.phone.status + (" · tested" if self.phone.heard_test else " · NOT VERIFIED AUDIBLE"))
            self.screen.pulse = self.pulse.get()
            o = self.latest
            if self.state == "CALIBRATING" and self.cal_phase == "CAPTURE":
                self.status.set(f"CAPTURE {max(0, self.cal.stage.seconds-(now-self.cal.started)):.1f}s")
                if self.cal.due(now):
                    self._capture_done()
            if self.state == "VERIFYING" and self.cal_phase == "CAPTURE":
                if now - self.verify_started >= self.VERIFY[self.verify_index][1]:
                    self._verify_finish()
            if self.state == "MONITORING":
                observation = o or Observation(now - 100, camera_ok=False)
                self.engine.mode = self.mode.get()
                decision = self.engine.update(observation, now, self.inputs.age())
                self.last_decision = decision
                self.status.set(decision.status)
                self.battery.set(decision.battery)
                self.battery_label.set(f"Concern {decision.battery:.0f} / 100 · heuristic, NOT probability")
                self.detail.set("; ".join(decision.reasons) or ("Monitoring · phone ready" if self.phone.enabled else "SCREEN-ONLY TEST · phone not armed"))
                if decision.auto_cleared:
                    self.screen.stop(); self.phone.cancel_pending()
                    self.log("Alert cleared by fresh open-eye recovery or confirmed empty chair.", "AUTO_CLEAR", decision)
                if decision.alarm:
                    try:
                        self.screen.start("; ".join(decision.reasons))
                    except Exception:
                        self.log("Screen renderer failed. Stop remains available; phone attempted separately.", "SCREEN_ERROR")
                    try:
                        self.phone.trigger()
                    except Exception:
                        self.log("Phone trigger failed; check backend status.", "PHONE_ERROR")
                elif self.screen.active and not self.screen.test:
                    self.screen.stop()
                key = decision.status + "|" + ";".join(decision.reasons)
                if key != self.last_log_key and now - self.last_log_time >= 1:
                    self.log(key, "STATE", decision)
                    self.last_log_key, self.last_log_time = key, now
            elif self.state == "PREVIEW":
                self.status.set("PREVIEW" if o and now - o.t < .8 else "WAITING FOR CAMERA")
                if not self.demo and self.camera.process and now - self.camera.started > 25 and (o is None or now - o.t > 3):
                    self.camera.stop()
                    self.latest = None
                    self.detail.set("Camera timed out. Press Stop, select another backend/index, then Preview. No driver call can trap the UI.")
            if o and self.profile:
                eyes = self.profile.eye_ratios(o)
                self.metrics.set(f"Eye openness {self.fmt(min(eyes) if eyes else None)} · neck down {self.fmt(self.profile.neck(o))} · recline {self.fmt(self.profile.recline(o))}\nPitch {self.fmt(o.pitch)}  yaw {self.fmt(o.yaw)}  roll {self.fmt(o.roll)} · face {o.face} / body {o.body}")
            elif o:
                self.metrics.set(f"Left eye {self.fmt(o.left)} (quality {o.left_q:.2f}) · right {self.fmt(o.right)} (quality {o.right_q:.2f})\nPitch {self.fmt(o.pitch)} · yaw {self.fmt(o.yaw)} · roll {self.fmt(o.roll)} · face {o.face} / body {o.body}")
        except Exception as exc:
            self._callback_error(type(exc), exc, None)
        if not self.closing:
            self.poll_job = self.root.after(80, self._poll)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="Synthetic input, no actual webcam or sleep inference")
    args = parser.parse_args(argv)
    dpi_awareness()
    root = tk.Tk()
    App(root, demo=args.demo)
    root.mainloop()


if __name__ == "__main__":
    main()
