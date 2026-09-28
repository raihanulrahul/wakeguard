"""Guided, keyboard-accessible desktop UI; no vision or hardware policy here."""
from __future__ import annotations
from dataclasses import dataclass
import time
import tkinter as tk
from tkinter import ttk
from . import __version__
from .engine import MODES

INK = "#16243a"
MUTED = "#607086"
BG = "#f2f5fa"
CARD = "#ffffff"
LINE = "#dce4ee"
NAVY = "#101d32"
ACCENT = "#007f78"
RED = "#c42a39"

@dataclass(frozen=True)
class NextStep:
    stage: int
    title: str
    detail: str
    button: str
    action: str
    disabled: bool = False


def next_step(app, now=None):
    """Single next-action decision, without bypassing any controller gates."""
    now = time.monotonic() if now is None else now
    if app.state == "MONITORING":
        return NextStep(6, "Monitoring is running", "Keep the camera view clear. An alert means check in, not a medical diagnosis.", "Open live view", "live")
    if app.state in ("CALIBRATING", "VERIFYING"):
        index = 3 if app.state == "CALIBRATING" else 4
        if app.cal_phase == "AUDIO FAILED" or not app.audio_confirmed:
            return NextStep(index, "Audio needs attention", "Stop setup, check your sound output, then test speech again.", "Stop setup", "stop")
        if getattr(app, "cal_save_failed", False):
            return NextStep(index, "Captures complete · save needs attention", app.cal_text.get(), "Try saving again", "save_calibration")
        if app.cal_phase == "CAPTURE":
            return NextStep(index, "Collecting your sample", "Move naturally within this view. Repeat or Previous cancels only this take.", "Capturing…", "none", True)
        if app.speech_role == "recovery":
            return NextStep(index, "Return to eyes open", "The short recovery cue finishes before another recording can begin.", "Finishing eye cue…", "none", True)
        if app.cal_phase == "REVIEW" or app.speech_role == "review":
            okay = app.cal_good if app.state == "CALIBRATING" else True
            if getattr(app, "capture_limited", False):
                return NextStep(index, "Eye setup kept; support unavailable", "This optional channel could not be measured. Continue without it or repeat the take.", "Continue with limitation", "space")
            return NextStep(index, "Capture saved" if okay else "Retry needed · other captures kept",
                            "Continue when ready. Earlier accepted samples are kept." if okay else "Read the measurement reason below; adjust the view, then repeat.",
                            "Continue  ·  Space" if okay else "Retry this capture", "space" if okay else "r")
        if app.speech_role == "countdown":
            return NextStep(index, "Get ready for capture", "The short countdown marks exactly when recording starts.", "Countdown…", "none", True)
        return NextStep(index, "Follow the current instruction", "Already know the posture? Continue skips long narration, but retains the countdown.", "I'm ready  ·  Space", "space")
    if not (app.latest and app.latest.camera_ok and 0 <= now - app.latest.t <= .8):
        return NextStep(1, "Let’s check your camera", "Start the preview. Look at your normal work screen, not the webcam.", "Start camera preview", "preview")
    target = app.latest.diagnostics.get("target_status", "locked")
    if target != "locked":
        return NextStep(1, "Keep tracking on you", "Wait briefly for the GREEN box, or click your face in Preview. Other people must not provide your eye measurements.", "Select your face in preview", "target")
    if not app.audio_confirmed:
        return NextStep(2, "Check spoken guidance", "You need to hear the instructions while your eyes are partly or fully closed.",
                        "Testing speech…" if app.speech.busy else "Test spoken instructions", "speech", app.speech.busy)
    if getattr(app, "draft", None) is not None:
        return NextStep(3, "Continue your saved calibration", "Completed captures are kept. Resume with the same camera position and lighting.", "Resume calibration", "calibrate")
    if app.profile is None:
        return NextStep(3, "Make it personal", "Choose how many screens you use, then build your eye and posture references.", "Begin guided calibration", "calibrate")
    if getattr(app, "glasses_setup_var", None) is not None and app.glasses_setup_var.get() and not app.profile.glasses_info().get("enabled"):
        return NextStep(3, "Add your glasses profile", "Calibration was collected without glasses support. Re-run once: start without glasses, then the final two short steps add your glasses-on views.", "Recalibrate with glasses", "calibrate")
    if not app.verified:
        return NextStep(4, "Check today’s setup", "Your saved calibration is reusable. Verify this camera position before starting.", "Verify my posture", "verify")
    if not app.screen_test_done:
        return NextStep(5, "Check the screen alert", "A brief bright red/white or red/blue test. Press Space to confirm you saw it.", "Test my screen alert", "screen")
    if not app.screen_only_choice and not (app.phone.ready and app.phone.heard_test and app.phone.enabled):
        if app.phone.pending:
            return NextStep(5, "Phone operation in progress", "Complete any account or device dialog. No password is stored in the repository.", "Waiting for phone…", "none", True)
        if app.phone.test_sent and not app.phone.heard_test:
            return NextStep(5, "Did your phone sound?", "Only confirm after hearing the actual iPhone. A sent request is not proof of delivery.", "I heard the phone test", "heard")
        if app.phone.ready:
            remaining = max(0, app.phone.cooldown - (now - app.phone.last_attempt))
            return NextStep(5, "Test your iPhone alert", "Phone must be audible before it is armed. The PC alarm stays silent.",
                            f"Test available in {remaining:.0f}s" if remaining else "Send phone sound test", "phone_test", remaining > 0)
        return NextStep(5, "Connect the private phone alert", "Set up Find My, or explicitly choose a screen-only test in Alert settings.", "Set up phone alert", "phone")
    return NextStep(6, "Ready for your desk test", "Review the mode in Live view. Monitoring starts only when you press Start.",
                    "Start screen-only test" if app.screen_only_choice and not app.phone.enabled else "Start monitoring", "start")


class Dashboard:
    def __init__(self, app):
        self.app = app
        self.root = app.root
        self.page = "setup"
        self.cache = None
        self.checks = []
        self.pages = {}
        self.navigation = {}
        self._build()

    def _label(self, parent, text="", size=10, bold=False, color=INK, bg=CARD, **kw):
        return tk.Label(parent, text=text, font=("Segoe UI", size, "bold" if bold else "normal"),
                        fg=color, bg=bg, anchor="w", justify="left", **kw)

    def _card(self, parent, padding=18):
        frame = tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        inner = tk.Frame(frame, bg=CARD)
        inner.pack(fill="both", expand=True, padx=padding, pady=padding)
        return frame, inner

    def _button(self, parent, text, command, style="WG.TButton", **kw):
        return ttk.Button(parent, text=text, command=command, style=style, **kw)

    def _build(self):
        a = self.app
        self.root.configure(bg=BG)
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("WG.TButton", font=("Segoe UI", 10), padding=(12, 8), background=CARD,
                        foreground=INK, bordercolor=LINE, lightcolor=CARD, darkcolor=LINE, relief="flat")
        style.map("WG.TButton", background=[("active", "#eaf3f3"), ("pressed", "#d4e8e6")],
                  foreground=[("disabled", "#94a0b1")])
        style.configure("Primary.WG.TButton", background=ACCENT, foreground="white", bordercolor=ACCENT,
                        lightcolor=ACCENT, darkcolor=ACCENT, font=("Segoe UI", 11, "bold"), padding=(18, 11))
        style.map("Primary.WG.TButton", background=[("disabled", "#e0e7ee"), ("active", "#006961")],
                  foreground=[("disabled", "#657589")])
        style.configure("Stop.WG.TButton", foreground=RED, background="#fff3f3", bordercolor="#f0d2d6")
        style.configure("WG.TCheckbutton", background=CARD, foreground=INK, font=("Segoe UI", 10), padding=4)
        style.configure("WG.TCombobox", font=("Segoe UI", 10), padding=6, fieldbackground=CARD,
                        background=CARD, foreground=INK)
        style.map("WG.TCombobox", fieldbackground=[("readonly", CARD)], selectbackground=[("readonly", CARD)],
                  selectforeground=[("readonly", INK)])
        style.configure("WG.Horizontal.TProgressbar", background=ACCENT, troughcolor="#e6edf4", borderwidth=0)
        self.root.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))
        self.root.option_add("*TCombobox*Listbox.background", CARD)
        self.root.option_add("*TCombobox*Listbox.foreground", INK)
        a.mode = tk.StringVar(value="Normal")
        a.status = tk.StringVar(value="STOPPED — camera off")
        a.battery = tk.DoubleVar(value=0)
        a.battery_label = tk.StringVar(value="Concern 0 / 100 · heuristic, not probability")
        a.detail = tk.StringVar(value="Start with the camera preview. The guide will show the next action.")
        a.metrics = tk.StringVar(value="Eyes / neck / chair: not measured")
        a.cal_text = tk.StringVar(value="No monitoring yet. Follow the next-step card above.")
        a.camera_var = tk.StringVar(value=str(a.settings["camera"]))
        a.backend = tk.StringVar(value=a.settings["backend"])
        a.voice_enabled = tk.BooleanVar(value=bool(a.settings["voice"]))
        a.monitor_count_var = tk.StringVar(value=str(a.settings["monitor_count"]))
        a.glasses_setup_var = tk.BooleanVar(value=bool(a.settings.get("glasses_setup", False)))
        a.glasses_mode_var = tk.StringVar(value=a.settings.get("glasses_mode", "Auto"))
        a.glasses_status = tk.StringVar(value="Glasses: not configured")
        a.pulse = tk.BooleanVar(value=bool(a.settings.get("alert_pulse", True)))
        a.palette = tk.StringVar(value=a.settings.get("alert_palette", "Red / white"))
        a.boost = tk.BooleanVar(value=bool(a.settings.get("brightness_boost", True)))
        a.phone_text = tk.StringVar(value="Phone: DISCONNECTED · NOT VERIFIED AUDIBLE")
        self.brightness_text = tk.StringVar(value="Temporary max brightness • tested when an alert starts")
        header = tk.Frame(self.root, bg=NAVY, height=76)
        header.pack(fill="x"); header.pack_propagate(False)
        brand = tk.Frame(header, bg=NAVY); brand.pack(side="left", padx=24)
        self._label(brand, "WakeGuard", 23, True, "white", NAVY).pack(anchor="w")
        self._label(brand, f"DESK VIGILANCE  /  {__version__}" + ("  /  DEMO" if a.demo else ""), 9, False, "#94a6bf", NAVY).pack(anchor="w")
        self._label(header, "LOCAL CAMERA  ·  PRIVATE BY DESIGN", 9, True, "#a3d4ce", NAVY).pack(side="right", padx=24)
        footer = tk.Frame(self.root, bg=CARD, height=64, highlightbackground=LINE, highlightthickness=1)
        footer.pack(side="bottom", fill="x"); footer.pack_propagate(False)
        self._label(footer, "Ctrl+Alt+S stops everything\nCtrl+Shift+Q quits", 9, False, MUTED).pack(side="left", padx=20)
        self._button(footer, "Quit", a.request_quit).pack(side="right", padx=(6, 20), pady=12)
        self._button(footer, "STOP EVERYTHING", a.stop_all, "Stop.WG.TButton").pack(side="right", padx=6, pady=12)
        self._button(footer, "ACK", a.acknowledge).pack(side="right", padx=6, pady=12)
        body = tk.Frame(self.root, bg=BG); body.pack(fill="both", expand=True)
        sidebar = tk.Frame(body, bg=NAVY, width=166); sidebar.pack(side="left", fill="y"); sidebar.pack_propagate(False)
        self._label(sidebar, "WORKSPACE", 9, True, "#7187a5", NAVY).pack(anchor="w", padx=20, pady=(24, 12))
        for name, label in (("setup", "01   Guided setup"), ("live", "02   Live view"), ("alerts", "03   Alert settings"), ("diagnostics", "04   Diagnostics")):
            button = tk.Button(sidebar, text=label, font=("Segoe UI", 10), bg=NAVY, fg="#9daec4",
                               activebackground="#243851", activeforeground="white", relief="flat", bd=0,
                               anchor="w", padx=18, pady=13, highlightthickness=0, cursor="hand2", command=lambda n=name: self.select(n))
            button.pack(fill="x", padx=8, pady=3)
            self.navigation[name] = button
        self._label(sidebar, "No video saved.\nNo PC alarm sound.\nYou stay in control.", 9, False, "#7f96b4", NAVY, wraplength=133).pack(side="bottom", anchor="w", padx=20, pady=24)
        right = tk.Frame(body, bg=BG); right.pack(fill="both", expand=True)
        self.control_area = tk.Frame(right, bg=BG); self.control_area.pack(fill="x")
        scroll_area = tk.Frame(right, bg=BG); scroll_area.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(scroll_area, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(scroll_area, orient="vertical", command=self.canvas.yview)
        scroll.pack(side="right", fill="y"); self.canvas.pack(fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.workspace = tk.Frame(self.canvas, bg=BG)
        self.canvas_window = self.canvas.create_window((0, 0), anchor="nw", window=self.workspace)
        self.workspace.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._resize)
        self.root.bind("<MouseWheel>", self._wheel, add="+")
        self.root.bind("<Button-4>", lambda e: self._wheel(e, -3), add="+")
        self.root.bind("<Button-5>", lambda e: self._wheel(e, 3), add="+")
        top = tk.Frame(self.control_area, bg=BG); top.pack(fill="x", padx=22, pady=(10, 6))
        self.heading = self._label(top, "Stay Alert", 20, True, bg=BG); self.heading.pack(anchor="w")
        self.subtitle = self._label(top, "Look awake, keep your KPI", 10, color=MUTED, bg=BG)
        self.subtitle.pack(anchor="w", pady=(4, 0))
        rail = tk.Frame(self.control_area, bg=BG); rail.pack(fill="x", padx=22, pady=(0, 6))
        for i, name in enumerate(("Camera", "Audio", "Calibrate", "Verify", "Alerts"), 1):
            badge = self._label(rail, f"{i}  {name}", 9, True, MUTED, "#e5ebf3", padx=10, pady=7)
            badge.pack(side="left", padx=(0, 5)); self.checks.append(badge)
        card, hero = self._card(self.control_area, 12)
        card.pack(fill="x", padx=22, pady=(0, 8))
        self.hero = hero
        self._label(hero, "YOUR NEXT STEP", 9, True, ACCENT).pack(anchor="w")
        self.next_title = self._label(hero, "Let’s check your camera", 16, True); self.next_title.pack(fill="x", pady=(5, 3))
        self.next_detail = self._label(hero, "", 10, color=MUTED, wraplength=620); self.next_detail.pack(fill="x")
        self.setup_choices = tk.Frame(hero, bg=CARD)
        self._label(self.setup_choices, "BEFORE YOU BEGIN", 9, True, ACCENT).pack(anchor="w", pady=(8, 3))
        row = tk.Frame(self.setup_choices, bg=CARD); row.pack(fill="x")
        self._label(row, "Work monitors", 10).pack(side="left")
        self.screen_count = ttk.Combobox(row, textvariable=a.monitor_count_var, values=["1", "2", "3"],
                                        state="readonly", width=3, style="WG.TCombobox")
        self.screen_count.pack(side="left", padx=(8, 18))
        self.glasses_check = ttk.Checkbutton(row, text="I wear glasses at this desk", variable=a.glasses_setup_var,
                                             style="WG.TCheckbutton", command=a.save_glasses_preferences)
        self.glasses_check.pack(side="left")
        self.setup_hint = self._label(self.setup_choices, "Start with glasses OFF. If selected, short glasses-ON pairs follow at the end.",
                                     9, color=MUTED, wraplength=600)
        self.setup_hint.pack(fill="x", pady=(3, 0))
        self.session_summary = self._label(hero, "", 9, color=MUTED)
        self.progress_area = tk.Frame(hero, bg=CARD)
        self.progress_text = self._label(self.progress_area, "", 10, True)
        self.progress_text.pack(fill="x", pady=(7, 3))
        self.cal_progress = ttk.Progressbar(self.progress_area, maximum=100, style="WG.Horizontal.TProgressbar")
        self.cal_progress.pack(fill="x")
        self.take_progress = ttk.Progressbar(self.progress_area, maximum=100, style="WG.Horizontal.TProgressbar")
        self.take_label = self._label(self.progress_area, "", 9, color=MUTED)
        self.save_note = self._label(self.progress_area, "", 9, color=MUTED, wraplength=620)
        self.save_note.pack(fill="x", pady=(3, 0))
        actionrow = tk.Frame(hero, bg=CARD); actionrow.pack(fill="x", pady=(8, 0))
        self.actionrow = actionrow
        self.next_button = self._button(actionrow, "Start camera preview", self.advance, "Primary.WG.TButton")
        self.next_button.pack(side="left")
        self.repeat_button = self._button(actionrow, "Repeat", lambda: a.action("r"))
        self.previous_button = self._button(actionrow, "Previous", lambda: a.action("b"))
        # Status gets its own row so actions remain visible on a narrow laptop.
        self.state_badge = self._label(hero, "", 9, True, MUTED, CARD, wraplength=650)
        self.state_badge.pack(fill="x", pady=(5, 0))
        self.repair_button = self._button(actionrow, "Repeat monitor pair", a.retry_screen_pair)
        self.keep_previous_button = self._button(hero, "Keep earlier successful capture", a.keep_previous_capture)
        self.add_glasses_button = self._button(hero, "Add glasses steps to this calibration", a.add_glasses_steps)
        for name in self.navigation:
            self.pages[name] = tk.Frame(self.workspace, bg=BG)
        self._setup_page(self.pages["setup"])
        self._live_page(self.pages["live"])
        self._alerts_page(self.pages["alerts"])
        self._diagnostics_page(self.pages["diagnostics"])
        self.select("setup", focus=False)

    def _setup_page(self, page):
        a = self.app
        self.capture_card, inner = self._card(page, 12)
        self.capture_heading = self._label(inner, "Your calibration captures", 12, True)
        self.capture_heading.pack(anchor="w", pady=(0, 6))
        row = tk.Frame(inner, bg=CARD); row.pack(fill="x")
        self.capture_list = ttk.Treeview(row, columns=("capture", "state"), show="headings", height=5, selectmode="browse")
        self.capture_list.heading("capture", text="Capture / monitor")
        self.capture_list.heading("state", text="Status")
        self.capture_list.column("capture", width=350, minwidth=180)
        self.capture_list.column("state", width=150, minwidth=140, stretch=False)
        self.capture_list.tag_configure("saved", foreground=ACCENT)
        self.capture_list.tag_configure("retry", foreground=RED)
        self.capture_list.tag_configure("limited", foreground="#986513")
        self.capture_list.pack(side="left", fill="x", expand=True)
        self.capture_tree_row = row
        scrollbar = ttk.Scrollbar(row, orient="vertical", command=self.capture_list.yview)
        scrollbar.pack(side="right", fill="y"); self.capture_list.configure(yscrollcommand=scrollbar.set)
        row = tk.Frame(inner, bg=CARD); row.pack(fill="x", pady=(6, 0))
        row.pack_configure(before=self.capture_tree_row, pady=(0, 6))
        self.repeat_selected = self._button(row, "Repeat selected capture", self.repeat_selected_capture)
        self.repeat_selected.pack(side="left")
        self._label(row, "Only the selected capture is repeated.", 9, color=MUTED).pack(side="left", padx=10)
        self.capture_rows = []
        self.capture_cache = None
        card, inner = self._card(page, 16); card.pack(fill="x", padx=22, pady=(0, 12))
        self.preview_card = card
        line = tk.Frame(inner, bg=CARD); line.pack(fill="x")
        self._label(line, "Your view", 13, True).pack(side="left")
        self._label(line, "Use your normal working posture", 9, color=MUTED).pack(side="right")
        a.preview_label = tk.Label(inner, text="CAMERA OFF\n\nStart preview to check your normal work angle.\nNo frames are recorded.",
                                   bg="#eaf0f6", fg=MUTED, font=("Segoe UI", 11), height=5, anchor="center")
        a.preview_label.pack(fill="x", pady=12)
        self._label(inner, "", 10, color=MUTED, textvariable=a.metrics, wraplength=680).pack(fill="x", pady=(0, 8))
        row = tk.Frame(inner, bg=CARD); row.pack(fill="x")
        self._label(row, "Camera", 10).pack(side="left")
        ttk.Spinbox(row, from_=0, to=9, textvariable=a.camera_var, width=3).pack(side="left", padx=(8, 12))
        ttk.Combobox(row, textvariable=a.backend, values=["auto", "dshow", "msmf"], state="readonly", width=7, style="WG.TCombobox").pack(side="left")
        self._button(row, "Preview", a.preview).pack(side="left", padx=8)
        self._button(row, "Test speech", a.test_speech).pack(side="left")
        ttk.Checkbutton(inner, text="Optional spoken commands", variable=a.voice_enabled,
                        style="WG.TCheckbutton").pack(anchor="w", pady=(8, 0))
        card, inner = self._card(page, 12); card.pack(fill="x", padx=22, pady=(0, 12))
        self.instruction_label = self._label(inner, "", 10, color=MUTED, textvariable=a.detail, wraplength=650)
        self.instruction_label.pack(fill="x")
        row = tk.Frame(inner, bg=CARD); row.pack(fill="x", pady=(8, 0))
        self._button(row, "Calibrate", a.begin_calibration).pack(side="left")
        self._button(row, "Start new calibration…", a.new_calibration).pack(side="left", padx=6)
        self._button(row, "Verify setup", a.begin_verification).pack(side="left")

    def show_capture_list(self):
        self.select("setup")
        self.render()
        self.canvas.yview_moveto(0)
        self.capture_list.focus_set()

    def repeat_selected_capture(self):
        selection = self.capture_list.selection()
        if selection:
            index = int(selection[0])
            if index < len(self.capture_rows):
                self.app.repeat_capture(*self.capture_rows[index])

    def render_calibration(self):
        a = self.app
        session = a.cal if a.cal is not None else getattr(a, "draft", None)
        active = a.state == "CALIBRATING" and a.cal is not None
        for widget in (self.setup_choices, self.session_summary, self.progress_area, self.add_glasses_button):
            widget.pack_forget()
        if self.page == "setup" and session is None and a.state not in ("MONITORING", "VERIFYING"):
            self.setup_choices.pack(fill="x", before=self.actionrow)
        if session is None:
            self.capture_card.pack_forget()
            return
        self.session_summary.configure(text=f"{session.monitor_count} work monitor(s) · Glasses {'included' if session.glasses_enabled else 'not included'} · Setup choices fixed for this session")
        self.session_summary.pack(fill="x", before=self.actionrow, pady=(6, 0))
        self.progress_area.pack(fill="x", before=self.actionrow)
        tasks = session.capture_tasks()
        statuses = [session.capture_status(*task) for task in tasks]
        count = sum(session.complete(*task) for task in tasks)
        self.progress_text.configure(text=f"{count} of {len(tasks)} captures saved" + (" · paused" if not active else ""))
        self.cal_progress.configure(value=100*count/max(1, len(tasks)))
        self.save_note.configure(text=getattr(a, "draft_save_error", "") or "Saved locally after each capture · Stop / Quit keeps progress",
                                 fg=RED if getattr(a, "draft_save_error", "") else MUTED)
        self.take_progress.pack_forget(); self.take_label.pack_forget()
        if active and a.cal_phase == "CAPTURE":
            fraction = min(session.valid_seconds / session.required_seconds, len(session.current) / session.required_frames, 1)
            self.take_progress.configure(value=100*fraction)
            self.take_progress.pack(fill="x", before=self.save_note, pady=(5, 0))
            self.take_label.configure(text=f"This take: {session.valid_seconds:.1f} / {session.required_seconds:.1f}s usable · {session.latest_issue or 'collecting'}")
            self.take_label.pack(fill="x", before=self.save_note)
        if active and not session.glasses_enabled:
            self.add_glasses_button.pack(anchor="w", pady=(4, 0))
            self.add_glasses_button.configure(state="normal" if a.cal_phase in ("READY", "REVIEW") and not a.speech.busy else "disabled")
        self.capture_card.pack(fill="x", padx=22, pady=(0, 8), before=self.preview_card)
        self.repeat_selected.configure(state="normal" if active else "disabled")
        signature = (tuple(tasks), tuple(statuses), session.capture_position(), active, a.cal_phase)
        if signature != self.capture_cache:
            selection = self.capture_list.selection()
            selected = selection[0] if selection else None
            self.capture_list.delete(*self.capture_list.get_children())
            self.capture_rows = tasks
            for i, (task, status) in enumerate(zip(tasks, statuses)):
                current = active and task == session.capture_position()
                label = session.capture_title(*task)
                tag = "retry" if status == "Retry needed" else "limited" if status.startswith("Limited") else "saved" if status == "Saved" else ""
                self.capture_list.insert("", "end", iid=str(i), values=(("→ " if current else "") + label, status), tags=(tag,))
            current_index = tasks.index(session.capture_position())
            self.capture_list.selection_set(selected if selected in self.capture_list.get_children() else str(current_index))
            self.capture_list.see(str(current_index))
            self.capture_cache = signature

    def _live_page(self, page):
        a = self.app
        card, inner = self._card(page); card.pack(fill="x", padx=22, pady=(0, 14))
        self._label(inner, "LIVE CONCERN", 10, True, MUTED).pack(anchor="w")
        self.concern = self._label(inner, "0", 52, True); self.concern.pack(anchor="w", pady=8)
        self._label(inner, "Higher means more concern. This is not a probability of sleep.", 10, color=MUTED, wraplength=650).pack(anchor="w")
        ttk.Progressbar(inner, variable=a.battery, maximum=100, style="WG.Horizontal.TProgressbar").pack(fill="x", pady=16)
        self._label(inner, "", 11, textvariable=a.detail, wraplength=650).pack(fill="x")
        row = tk.Frame(inner, bg=CARD); row.pack(fill="x", pady=16)
        self._label(row, "Monitoring mode", 10).pack(side="left")
        ttk.Combobox(row, textvariable=a.mode, values=list(MODES), state="readonly", width=15, style="WG.TCombobox").pack(side="left", padx=12)
        self._button(row, "START", a.start_monitoring, "Primary.WG.TButton").pack(side="left", padx=6)
        self._button(row, "Leaving seat", a.leaving_seat).pack(side="left")
        grow = tk.Frame(inner, bg=CARD); grow.pack(fill="x", pady=(0,10))
        self._label(grow, "Glasses", 10).pack(side="left")
        self.glasses_combo = ttk.Combobox(grow, textvariable=a.glasses_mode_var, values=["Auto", "On", "Off"],
                                           state="readonly", width=8, style="WG.TCombobox")
        self.glasses_combo.pack(side="left", padx=(12,8))
        self._label(grow, "", 9, color=MUTED, textvariable=a.glasses_status, wraplength=430).pack(side="left", fill="x", expand=True)
        a.glasses_mode_var.trace_add("write", lambda *_: a.save_glasses_preferences())
        self.mode_note = self._label(inner, "", 10, color=MUTED, wraplength=650); self.mode_note.pack(fill="x")
        card, inner = self._card(page); card.pack(fill="x", padx=22, pady=(0, 14))
        self._label(inner, "Measurement status", 13, True).pack(anchor="w")
        self._label(inner, "", 11, textvariable=a.metrics, wraplength=650).pack(fill="x", pady=10)
        self._label(inner, "A camera can miss events. Screen-only is a test mode, not dependable awakening.", 10, color=MUTED, wraplength=650).pack(fill="x")
        if a.demo:
            a.scenario = tk.StringVar(value="Awake")
            ttk.Combobox(inner, textvariable=a.scenario, state="readonly", values=["Awake", "Eyes closed", "Half closed", "Reclined awake", "Neck down", "Occluded", "Empty chair", "Camera failed"]).pack(fill="x", pady=8)

    def _alerts_page(self, page):
        a = self.app
        card, inner = self._card(page); card.pack(fill="x", padx=22, pady=(0, 14))
        self._label(inner, "Screen alert", 15, True).pack(anchor="w")
        self._label(inner, "Full-screen colour on every display. One steady panel keeps controls reachable.", 10, color=MUTED, wraplength=650).pack(fill="x", pady=(4, 12))
        row = tk.Frame(inner, bg=CARD); row.pack(fill="x")
        self._label(row, "Colours", 10).pack(side="left")
        self.palette_combo = ttk.Combobox(row, textvariable=a.palette, values=["Red / white", "Red / blue"], state="readonly", width=16, style="WG.TCombobox")
        self.palette_combo.pack(side="left", padx=12)
        swatches = tk.Frame(row, bg=CARD); swatches.pack(side="left")
        self.swatch1 = tk.Label(swatches, bg="#ff0000", width=5, height=2); self.swatch1.pack(side="left", padx=3)
        self.swatch2 = tk.Label(swatches, bg="white", highlightbackground=LINE, highlightthickness=1, width=5, height=2); self.swatch2.pack(side="left", padx=3)
        ttk.Checkbutton(inner, text="Alternate slowly (one colour change per second)", variable=a.pulse, style="WG.TCheckbutton").pack(anchor="w", pady=(10, 0))
        ttk.Checkbutton(inner, text="Boost supported displays to maximum during the alert", variable=a.boost, style="WG.TCheckbutton").pack(anchor="w")
        self._label(inner, "Uncheck alternation for steady white. Bright changing colours may be unsuitable for photosensitivity. Stop at any time.", 10, color=MUTED, wraplength=650).pack(fill="x", pady=8)
        self._label(inner, "", 10, color=ACCENT, textvariable=self.brightness_text, wraplength=650).pack(fill="x", pady=8)
        row = tk.Frame(inner, bg=CARD); row.pack(fill="x")
        self._button(row, "Test screen", a.test_screen, "Primary.WG.TButton").pack(side="left")
        self._button(row, "Restore brightness", a.restore_brightness).pack(side="left", padx=8)
        self._label(inner, "Test auto-stops after 10 seconds. ACK confirms you saw it. Unsupported monitors require their own brightness controls.", 9, color=MUTED, wraplength=650).pack(fill="x", pady=(10, 0))
        card, inner = self._card(page); card.pack(fill="x", padx=22, pady=(0, 14))
        self._label(inner, "iPhone Find My", 15, True).pack(anchor="w")
        self._label(inner, "Independent phone sound, not a cellular call. Complete setup and hear a real test before enabling.", 10, color=MUTED, wraplength=650).pack(fill="x", pady=(4, 10))
        self._label(inner, "", 10, True, textvariable=a.phone_text, wraplength=650).pack(fill="x", pady=6)
        row = tk.Frame(inner, bg=CARD); row.pack(fill="x", pady=8)
        self._button(row, "Connect phone", a.connect_phone).pack(side="left")
        self._button(row, "Test phone sound", a.test_phone).pack(side="left", padx=6)
        self._button(row, "I heard the test", a.confirm_phone).pack(side="left")
        self._button(inner, "Use screen-only TEST mode", self.choose_screen_only).pack(anchor="w", pady=(8, 0))
        self._label(inner, "A screen may not wake you with closed eyes. Phone delivery and earbud routing cannot be guaranteed.", 9, color=MUTED, wraplength=650).pack(fill="x", pady=(10, 0))
        for var in (a.palette, a.pulse, a.boost):
            var.trace_add("write", lambda *_: self.preferences_changed())

    def _diagnostics_page(self, page):
        a = self.app
        card, inner = self._card(page); card.pack(fill="both", expand=True, padx=22, pady=(0, 14))
        self._label(inner, "What WakeGuard is seeing", 15, True).pack(anchor="w")
        self._label(inner, "", 11, textvariable=a.metrics, wraplength=650).pack(fill="x", pady=14)
        self._label(inner, "", 10, textvariable=a.detail, wraplength=650).pack(fill="x", pady=8)
        a.logbox = tk.Text(inner, height=12, font=("Consolas", 10), bg="#f5f8fb", fg=INK, bd=0,
                           highlightbackground=LINE, highlightthickness=1, state="disabled", wrap="word")
        a.logbox.pack(fill="both", expand=True, pady=12)
        self._label(inner, "Logs contain numeric diagnostics and events, not webcam frames or microphone recordings.", 9, color=MUTED, wraplength=650).pack(fill="x")

    def _resize(self, event):
        self.canvas.itemconfigure(self.canvas_window, width=event.width)
        width = max(300, event.width - 90)
        self.next_detail.configure(wraplength=width)
        self.instruction_label.configure(wraplength=width)
        self.setup_hint.configure(wraplength=width)
        self.save_note.configure(wraplength=width)
        self.state_badge.configure(wraplength=width)

    def _wheel(self, event, amount=None):
        try:
            if event.widget.winfo_toplevel() != self.root:
                return
            x = event.x_root - self.canvas.winfo_rootx()
            y = event.y_root - self.canvas.winfo_rooty()
            if 0 <= x <= self.canvas.winfo_width() and 0 <= y <= self.canvas.winfo_height():
                self.canvas.yview_scroll(amount if amount is not None else -int(event.delta / 120) * 3, "units")
        except (tk.TclError, AttributeError):
            pass

    def select(self, name, focus=True):
        if name not in self.pages:
            return
        self.page = name
        for key, frame in self.pages.items():
            frame.pack_forget()
            self.navigation[key].configure(bg="#23364d" if key == name else NAVY,
                                            fg="white" if key == name else "#9daec4")
        self.pages[name].pack(fill="both", expand=True)
        titles = {"setup": ("Stay Alert", "Look awake, keep your KPI"),
                  "live": ("Your live workspace", "Clear status. Independent alerts. Immediate stop."),
                  "alerts": ("Make the alert unmistakable", "Vivid colour, temporary brightness, a separate phone channel."),
                  "diagnostics": ("Details without the guesswork", "Measurement quality and event history, when you need them.")}
        self.heading.configure(text=titles[name][0]); self.subtitle.configure(text=titles[name][1])
        self.canvas.yview_moveto(0)
        if focus:
            self.root.focus_set()

    def advance(self):
        a = self.app
        step = next_step(a)
        if step.disabled:
            return
        if step.action in ("preview", "speech", "calibrate", "verify", "space", "r"):
            self.select("setup")
        if step.action == "preview": a.preview()
        elif step.action == "speech": a.test_speech()
        elif step.action == "calibrate": a.begin_calibration()
        elif step.action == "verify": a.begin_verification()
        elif step.action == "save_calibration": a._finish_calibration()
        elif step.action in ("space", "r"): a.action(step.action)
        elif step.action == "screen": self.select("alerts"); a.test_screen()
        elif step.action == "phone": self.select("alerts"); a.connect_phone()
        elif step.action == "phone_test": self.select("alerts"); a.test_phone()
        elif step.action == "heard": a.confirm_phone()
        elif step.action == "start": a.start_monitoring()
        elif step.action == "stop": a.stop_all()
        elif step.action == "live": self.select("live")
        elif step.action == "target": self.select("setup")
        self.render()

    def choose_screen_only(self):
        self.app.screen_only_choice = True
        self.app.detail.set("Screen-only TEST selected. A screen is not a dependable wake-up channel with eyes closed.")
        self.render()

    def preferences_changed(self):
        a = self.app
        if hasattr(a, "brightness"):
            a.save_alert_preferences()
        self.swatch2.configure(bg="#0000ff" if a.palette.get() == "Red / blue" else "#ffffff")
        a.screen_test_done = False

    def render(self):
        a = self.app
        step = next_step(a)
        self.render_calibration()
        data = (step, a.status.get(), round(a.battery.get()), a.mode.get(), a.cal_text.get(), a.glasses_mode_var.get(), a.glasses_status.get())
        if data != self.cache:
            self.next_title.configure(text=step.title)
            self.next_detail.configure(text=a.cal_text.get() if a.state in ("CALIBRATING", "VERIFYING") else step.detail)
            self.next_button.configure(text=step.button, state="disabled" if step.disabled else "normal")
            self.state_badge.configure(text=a.status.get(), fg=RED if "ALARM" in a.status.get() else MUTED)
            self.concern.configure(text=str(round(a.battery.get())), fg=RED if a.battery.get() >= 60 else INK)
            for index, badge in enumerate(self.checks, 1):
                badge.configure(bg="#dcefe9" if index < step.stage else ("#d8e9f1" if index == step.stage else "#e5ebf3"),
                                fg=ACCENT if index <= step.stage else MUTED)
            notes = {"Normal": "Normal: awake recline is allowed; eyelids and posture contribute evidence.",
                     "High Alert": "High Alert: earlier warnings, shorter persistence, no baseline adaptation.",
                     "Super Alert": "Super Alert: full recline is forbidden. Open eyes alone do not cancel that condition."}
            self.mode_note.configure(text=notes.get(a.mode.get(), notes["Normal"]))
            self.cache = data
        self.repair_button.pack_forget()
        self.keep_previous_button.pack_forget()
        if a.state in ("CALIBRATING", "VERIFYING"):
            self.repeat_button.pack(side="left", padx=6)
            self.previous_button.pack(side="left")
            if getattr(a, "repair_targets", []) and not a.cal_good and a.cal_phase == "REVIEW":
                self.repeat_button.pack_forget()
                self.previous_button.pack_forget()
                self.repair_button.pack(side="left", padx=6)
            if a.cal is not None and a.cal_phase == "REVIEW" and a.cal.capture_id(*a.cal.capture_position()) in a.cal.retained_previous:
                self.keep_previous_button.pack(anchor="w", pady=(4, 0))
        else:
            self.repeat_button.pack_forget()
            self.previous_button.pack_forget()
        if hasattr(a, "brightness"):
            self.brightness_text.set(a.brightness.status)
        o = a.latest
        if o is not None and hasattr(a, "_channel_limits"):
            target = o.diagnostics.get("target_status", "")
            if target and target != "locked" and a.state in ("PREVIEW", "CALIBRATING"):
                self.state_badge.configure(text="TARGET " + target.upper() + " — check GREEN box")
            elif target == "locked" and not o.pose_valid() and o.context_valid():
                self.state_badge.configure(text="Eye context available · head ANGLES unavailable")
