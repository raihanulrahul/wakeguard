"""Real Tk key-event regressions for the reported step-one calibration loop.

No camera, microphone, Apple login or sound: observations/speech are synthetic.
Unlike the original tests these put focus on the actual dashboard buttons.
"""
import os
import tempfile
import time
import unittest
from dataclasses import asdict
from unittest.mock import Mock, patch
import tkinter as tk
from tkinter import ttk

from wakeguard.app import App
from wakeguard.calibration import CalibrationSession
from wakeguard.demo import observation
from test_core import full_calibration


@unittest.skipUnless(os.environ.get("WAKEGUARD_GUI_TESTS") == "1" or os.environ.get("DISPLAY"),
                     "GUI requires Windows desktop or Xvfb")
class SetupKeyboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"WAKEGUARD_DATA_DIR": self.tmp.name})
        self.env.start()
        self.root = tk.Tk()
        self.app = App(self.root, demo=True, testing=True)
        self.root.update()
        self.app.audio_confirmed = True
        self.app.latest = observation(time.monotonic(), 1)
        self.app.state = "PREVIEW"

    def tearDown(self):
        if not self.app.closing:
            self.app.quit()
        self.env.stop()
        self.tmp.cleanup()

    def widgets(self, parent=None):
        parent = parent or self.root
        for child in parent.winfo_children():
            yield child
            yield from self.widgets(child)

    def button(self, text):
        return next(w for w in self.widgets()
                    if isinstance(w, (tk.Button, ttk.Button)) and w.cget("text") == text)

    def pump(self):
        self.app._poll()
        self.root.update()
        if self.app.poll_job:
            self.root.after_cancel(self.app.poll_job)
            self.app.poll_job = None

    def focus(self, widget):
        widget.focus_force()
        self.root.update()
        self.assertEqual(self.root.focus_get(), widget)

    def press(self, widget, keysym="space", release=True):
        # Exercise Tk bindtag order, not a direct call to App.action().
        widget.event_generate("<KeyPress>", keysym=keysym)
        self.root.update()
        if release and not self.app.closing:
            widget.event_generate("<KeyRelease>", keysym=keysym)
            self.root.update()

    def ready(self):
        self.button("Calibrate").invoke()
        self.pump()
        self.assertEqual(self.app.cal_phase, "READY")
        return self.app.cal

    def finish_sample(self):
        sample = full_calibration().samples[self.app.cal.stage.key]
        self.app.cal.current = list(sample)
        self.app.cal.valid_seconds = self.app.cal.stage.seconds
        self.app.cal.total_frames = len(sample)
        self.app._capture_done()
        self.pump()
        self.assertTrue(self.app.cal_good)
        self.assertEqual(self.app.cal_phase, "REVIEW")

    def test_focused_calibrate_space_does_not_restart_session(self):
        original = self.ready()
        button = self.button("Calibrate")
        self.focus(button)
        self.press(button)
        self.pump()
        self.assertIs(self.app.cal, original, "SPACE recreated the calibration session")
        self.assertEqual(self.app.cal_phase, "CAPTURE")

    def test_step_one_accept_reaches_step_two_with_button_focus(self):
        original = self.ready()
        button = self.button("Calibrate")
        self.focus(button)
        self.press(button)
        self.pump()
        self.assertIs(self.app.cal, original)
        self.assertEqual(self.app.cal_phase, "CAPTURE")
        self.finish_sample()
        self.app.last_actions.clear()
        self.focus(button)
        self.press(button)
        self.pump()
        self.assertIs(self.app.cal, original)
        self.assertEqual(self.app.cal.index, 1)
        self.assertEqual(self.app.cal_phase, "READY")
        self.assertIn("Step 2 of 15", self.app.cal_text.get())

    def test_calibrate_command_is_idempotent_during_setup(self):
        original = self.ready()
        self.app.begin_calibration()
        self.assertIs(self.app.cal, original)
        self.assertEqual(self.app.cal_phase, "READY")

    def test_space_during_prompt_never_invokes_focused_button(self):
        self.ready()
        self.app._prompt_stage()
        trap = Mock()
        button = self.button("Test speech")
        button.configure(command=trap)
        self.focus(button)
        self.press(button)
        trap.assert_not_called()
        self.assertEqual(self.app.cal_phase, "PROMPT")

    def test_space_during_capture_never_invokes_focused_button(self):
        self.ready()
        self.app.action("space")
        self.pump()
        trap = Mock()
        button = self.button("Calibrate")
        button.configure(command=trap)
        self.focus(button)
        self.press(button)
        trap.assert_not_called()
        self.assertEqual(self.app.cal_phase, "CAPTURE")

    def test_debounced_space_does_not_fall_through_to_button(self):
        self.ready()
        self.app.last_actions["space"] = time.monotonic()
        trap = Mock()
        button = self.button("Test speech")
        button.configure(command=trap)
        self.focus(button)
        self.press(button)
        trap.assert_not_called()
        self.assertEqual(self.app.cal_phase, "READY")

    def test_held_space_cannot_accept_a_later_phase(self):
        self.ready()
        button = self.button("Calibrate")
        self.focus(button)
        self.press(button, release=False)
        self.pump()
        self.assertEqual(self.app.cal_phase, "CAPTURE")
        self.finish_sample()
        self.app.last_actions.clear()  # Simulate capture taking longer than debounce.
        button.event_generate("<KeyPress>", keysym="space")
        self.root.update()
        self.assertEqual(self.app.cal.index, 0)
        self.assertEqual(self.app.cal_phase, "REVIEW")
        button.event_generate("<KeyRelease>", keysym="space")
        self.root.update()
        self.app.last_actions.clear()
        self.press(button)
        self.pump()
        self.assertEqual(self.app.cal.index, 1)

    def test_failed_sample_space_does_not_restart_or_skip(self):
        original = self.ready()
        self.app.cal_phase = "REVIEW"
        self.app.cal_good = False
        button = self.button("Calibrate")
        self.focus(button)
        self.press(button)
        self.assertIs(self.app.cal, original)
        self.assertEqual(self.app.cal.index, 0)
        self.assertEqual(self.app.cal_phase, "REVIEW")

    def test_queued_space_does_not_duplicate_foreground_tk_input(self):
        self.ready()
        self.focus(self.root)
        self.app.inputs.events.put("space")
        self.pump()
        self.assertEqual(self.app.cal_phase, "READY",
                         "Foreground input must use Tk once, not the global queue too")

    def test_old_global_space_does_not_cross_setup_phase(self):
        self.ready()
        self.app.inputs.events.put({"action": "space", "at": time.monotonic() - 20})
        self.pump()
        self.assertEqual(self.app.state, "CALIBRATING")
        self.assertEqual(self.app.cal_phase, "READY")

    def test_text_in_secondary_dialog_not_used_as_setup_feedback(self):
        self.ready()
        dialog = tk.Toplevel(self.root)
        entry = ttk.Entry(dialog)
        entry.pack()
        self.focus(entry)
        self.press(entry)
        self.assertEqual(entry.get(), " ")
        self.app.inputs.events.put("space")
        self.pump()
        self.assertEqual(self.app.cal_phase, "READY")
        dialog.destroy()

    def test_test_screen_focused_stop_button_space_only_acknowledges(self):
        self.app.test_screen()
        self.root.update()
        button = self.button("STOP EVERYTHING")
        # Locate the overlay's button rather than the dashboard's identical label.
        button = next(w for w in self.widgets() if isinstance(w, tk.Button)
                      and w.cget("text") == "STOP EVERYTHING")
        self.focus(button)
        self.press(button)
        self.assertFalse(self.app.screen.active)
        self.assertEqual(self.app.state, "PREVIEW", "SPACE must ACK, not also click STOP")


if __name__ == "__main__":
    unittest.main()
