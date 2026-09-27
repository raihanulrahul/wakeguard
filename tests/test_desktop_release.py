"""No hardware brightness, camera, microphone or Apple changes in these tests."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from wakeguard.brightness import BrightnessLease, BrightnessController
from wakeguard.alarms import ALERT_COLORS, COLOUR_INTERVAL_MS, TEST_MAX_SECONDS
from wakeguard.dashboard import next_step


class Driver:
    name = "fake"
    def __init__(self, values=None, maximum=100):
        self.values = dict(values or {"panel": 35, "external": 62})
        self.maximum = maximum
        self.writes = []
        self.failed = set()
        self.on_write = lambda identifier, value: None
    def discover(self): return [{"id": key} for key in self.values]
    def read(self, key): return self.values[key], self.maximum
    def write(self, key, value):
        self.on_write(key, value)
        self.writes.append((key, value))
        if key in self.failed: raise OSError("unsupported")
        self.values[key] = value


class BrightnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = Path(self.tmp.name) / "restore.json"
        self.driver = Driver()
        self.events = []
        self.lease = BrightnessLease([self.driver], self.journal, self.events.append)
    def tearDown(self): self.tmp.cleanup()
    def test_boost_all_supported_displays_and_restore_individually(self):
        self.lease.boost()
        self.assertEqual(self.driver.values, {"panel": 100, "external": 100})
        self.assertTrue(self.journal.exists())
        self.lease.restore()
        self.assertEqual(self.driver.values, {"panel": 35, "external": 62})
        self.assertFalse(self.journal.exists())
    def test_journal_exists_before_hardware_write(self):
        def check(key, value):
            saved = json.loads(self.journal.read_text())["displays"]
            self.assertTrue(any(entry["id"] == key and entry["value"] == self.driver.values[key] for entry in saved))
        self.driver.on_write = check
        self.lease.boost()
    def test_repeated_boost_does_not_replace_originals_with_maximum(self):
        self.lease.boost(); first = self.journal.read_text()
        self.lease.boost()
        self.assertEqual(self.journal.read_text(), first)
        self.lease.restore(); self.assertEqual(self.driver.values["panel"], 35)
    def test_crash_recovery_reads_saved_originals(self):
        self.lease.boost()
        second = BrightnessLease([self.driver], self.journal)
        self.assertTrue(second.recover()); self.assertEqual(self.driver.values["external"], 62)
    def test_failed_restore_keeps_only_pending_device(self):
        self.lease.boost(); self.driver.failed.add("external")
        self.assertFalse(self.lease.restore())
        self.assertEqual(len(json.loads(self.journal.read_text())["displays"]), 1)
        self.assertEqual(self.events[-1]["state"], "restore_needed")
        self.driver.failed.clear(); self.assertTrue(self.lease.restore())
        self.assertEqual(self.driver.values["external"], 62)
    def test_cancel_before_boost_does_not_modify_hardware(self):
        self.lease.boost(lambda: True)
        self.assertEqual(self.driver.writes, [])
    def test_cancel_mid_boost_restores_changed_display(self):
        self.lease.boost(lambda: bool(self.driver.writes))
        self.assertEqual(self.driver.values, {"panel": 35, "external": 62})
    def test_unknown_driver_in_journal_blocks_writes(self):
        self.journal.write_text('{"schema":1,"displays":[{"driver":"malicious","id":"x","value":5}]}')
        with self.assertRaises(ValueError): self.lease.recover()
        self.assertEqual(self.driver.writes, [])
    def test_monitor_with_unreadable_original_never_written(self):
        self.driver.read = Mock(side_effect=OSError("not supported"))
        self.lease.boost(); self.assertEqual(self.driver.writes, [])
        self.assertEqual(self.events[-1]["state"], "unsupported")
    def test_monitor_already_at_maximum_does_not_get_restore_write(self):
        self.driver.values = {"maxed": 100}
        self.lease.boost(); self.lease.restore()
        self.assertEqual(self.driver.writes, [])
    def test_monitor_without_support_is_not_claimed_maximum(self):
        self.driver.failed.add("panel")
        self.lease.boost(); self.assertEqual(self.events[-1]["confirmed"], 1)
    def test_invalid_hardware_range_does_not_write(self):
        self.driver.maximum = -1
        self.lease.boost(); self.assertEqual(self.driver.writes, [])
    def test_no_hardware_operations_in_gui_testing_mode(self):
        channel = Mock()
        controller = BrightnessController(Path(self.tmp.name), testing=True, channel=channel)
        controller.begin(); channel.start.assert_not_called()
    def test_restore_is_nonblocking_parent_send(self):
        channel = Mock(); channel.alive = True
        controller = BrightnessController(Path(self.tmp.name), channel=channel)
        controller.stop(); channel.send.assert_called_once_with({"cmd": "stop"})
        channel.stop.assert_not_called()
    def test_no_driver_write_when_prior_recovery_fails(self):
        self.lease.boost(); self.driver.failed.add("external"); self.lease.restore()
        self.driver.writes.clear(); self.lease.boost()
        self.assertFalse(any(value == 100 for _, value in self.driver.writes))
    def test_pure_rgb_palettes_and_slow_interval(self):
        self.assertEqual(ALERT_COLORS["Red / white"], ("#ff0000", "#ffffff"))
        self.assertEqual(ALERT_COLORS["Red / blue"], ("#ff0000", "#0000ff"))
        self.assertGreaterEqual(COLOUR_INTERVAL_MS, 1000)
        self.assertEqual(TEST_MAX_SECONDS, 10)


@unittest.skipUnless(os.environ.get("WAKEGUARD_GUI_TESTS") == "1" or os.environ.get("DISPLAY"), "GUI opt-in")
class DesktopGUITests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from wakeguard.app import App
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"WAKEGUARD_DATA_DIR": self.tmp.name}); self.env.start()
        self.root = tk.Tk(); self.app = App(self.root, demo=True, testing=True)
        self.root.update()
    def tearDown(self):
        if not self.app.closing: self.app.quit()
        self.env.stop(); self.tmp.cleanup()
    def preview(self):
        from wakeguard.demo import observation
        self.app.state = "PREVIEW"; self.app.latest = observation(time.monotonic(), 1)
    def test_guide_starts_with_camera_not_monitoring(self):
        self.assertEqual(next_step(self.app).action, "preview")
        self.assertEqual(self.app.state, "STOPPED")
    def test_camera_then_audio_then_calibration_then_verification(self):
        self.preview(); self.assertEqual(next_step(self.app).action, "speech")
        self.app.audio_confirmed = True; self.app.profile = None
        self.assertEqual(next_step(self.app).action, "calibrate")
        from wakeguard.demo import demo_profile
        self.app.profile = demo_profile()
        self.assertEqual(next_step(self.app).action, "verify")
        self.app.verified = True
        self.assertEqual(next_step(self.app).action, "screen")
    def test_phone_needs_heard_test_before_guide_start(self):
        self.preview(); self.app.audio_confirmed = self.app.verified = self.app.screen_test_done = True
        self.assertEqual(next_step(self.app).action, "phone")
        self.app.phone.ready = True
        self.assertEqual(next_step(self.app).action, "phone_test")
        self.app.phone.test_sent = True
        self.assertEqual(next_step(self.app).action, "heard")
        self.app.phone.heard_test = self.app.phone.enabled = True
        self.assertEqual(next_step(self.app).action, "start")
    def test_screen_only_requires_explicit_choice(self):
        self.preview(); self.app.audio_confirmed = self.app.verified = self.app.screen_test_done = True
        self.assertFalse(self.app.screen_only_choice)
        self.app.view.choose_screen_only()
        self.assertEqual(next_step(self.app).action, "start")
        self.assertEqual(self.app.state, "PREVIEW")
    def test_screen_ack_marks_test_seen(self):
        self.app.test_screen(); self.app.acknowledge()
        self.assertTrue(self.app.screen_test_done)
    def test_timed_test_does_not_claim_user_saw_it(self):
        self.app.test_screen()
        self.app.screen.started = time.monotonic() - 20
        self.app.screen._tick()
        self.assertFalse(self.app.screen.active)
        self.assertFalse(self.app.screen_test_done)
    def test_palette_change_invalidates_screen_test_and_persists(self):
        self.app.screen_test_done = True
        self.app.palette.set("Red / blue")
        self.assertFalse(self.app.screen_test_done)
        saved = json.loads(self.app.settings_path.read_text())
        self.assertEqual(saved["alert_palette"], "Red / blue")
    def test_all_windows_are_pure_red_then_blue(self):
        self.app.screen.monitor_provider = lambda: [dict(x=0,y=0,w=400,h=500,primary=True), dict(x=400,y=0,w=400,h=500,primary=False)]
        self.app.palette.set("Red / blue")
        self.app.test_screen(); self.root.update()
        self.assertEqual(len(self.app.screen.windows), 2)
        self.assertTrue(all(window.cget("bg") == "#ff0000" for window in self.app.screen.windows))
        self.app.screen._tick()
        self.assertTrue(all(window.cget("bg") == "#0000ff" for window in self.app.screen.windows))
        self.assertEqual(len(self.app.screen.fields), 1)
    def test_steady_mode_is_white(self):
        self.app.pulse.set(False); self.app.test_screen()
        self.assertTrue(all(window.cget("bg") == "#ffffff" for window in self.app.screen.windows))
    def test_screen_cleanup_requests_brightness_restore(self):
        fake = Mock(); self.app.screen.brightness = fake
        self.app.test_screen(); fake.begin.assert_called_once()
        self.app.acknowledge(); fake.stop.assert_called()
    def test_brightness_failure_does_not_prevent_visible_alert(self):
        fake = Mock(); fake.begin.side_effect = OSError("driver failure")
        self.app.screen.brightness = fake
        self.app.test_screen(); self.assertTrue(self.app.screen.active)
    def test_pages_and_persistent_stop(self):
        for page in ("setup", "live", "alerts", "diagnostics"):
            self.app.view.select(page); self.root.update()
            self.assertTrue(self.app.view.pages[page].winfo_ismapped())
        self.app.stop_all(); self.assertEqual(self.app.state, "STOPPED")
    def test_guided_capture_has_no_skip_button(self):
        from wakeguard.calibration import CalibrationSession
        self.preview(); self.app.audio_confirmed=True; self.app.state="CALIBRATING"
        self.app.cal=CalibrationSession(); self.app.cal_phase="CAPTURE"
        self.assertTrue(next_step(self.app).disabled)
    def test_failed_sample_guide_offers_repeat_not_accept(self):
        self.app.state="CALIBRATING"; self.app.audio_confirmed=True
        self.app.cal_phase="REVIEW"; self.app.cal_good=False
        self.assertEqual(next_step(self.app).action,"r")
    def test_every_page_fits_requested_minimum_width(self):
        self.root.geometry("860x620")
        for page in ("setup","live","alerts","diagnostics"):
            self.app.view.select(page); self.root.update()
            self.assertLessEqual(self.app.view.canvas.winfo_width(), self.root.winfo_width())
            self.assertTrue(self.app.view.next_button.winfo_ismapped())


@unittest.skipUnless(os.name == 'nt', 'Windows native instance guard')
class WindowsInstanceTests(unittest.TestCase):
    def test_duplicate_ui_is_rejected_without_stopping_the_first(self):
        from wakeguard.instance import InstanceGuard
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); home = root / 'home'; home.mkdir()
            guard = InstanceGuard(home, root)
            try:
                with self.assertRaises(RuntimeError): InstanceGuard(home, root)
            finally:
                guard.close()
            next_guard = InstanceGuard(home, root)
            next_guard.close()


class AlertLightingTests(unittest.TestCase):
    def test_own_alert_does_not_lock_open_eye_recovery_behind_light_drift(self):
        from wakeguard.engine import Engine
        from wakeguard.demo import observation, demo_profile
        e = Engine(demo_profile()); e.active = True
        for i in range(81):
            now = i / 10
            e.display_light_until = now + 3
            o = observation(now, i); o.brightness = 240
            decision = e.update(o, now)
        self.assertFalse(decision.alarm)
        self.assertNotIn('Lighting changed', ';'.join(decision.reasons))
    def test_external_lighting_drift_still_requires_check(self):
        from wakeguard.engine import Engine
        from wakeguard.demo import observation, demo_profile
        e = Engine(demo_profile()); saw_lighting_alert = False
        for i in range(81):
            now = i / 10; o = observation(now, i); o.brightness = 240
            decision = e.update(o, now)
            saw_lighting_alert |= decision.alarm and 'Lighting changed' in ';'.join(decision.reasons)
        self.assertTrue(saw_lighting_alert)
    def test_own_display_guard_does_not_hide_eye_closure_or_change_profile(self):
        from wakeguard.engine import Engine
        from wakeguard.demo import observation, demo_profile
        e = Engine(demo_profile()); original = e.profile.brightness
        for i in range(50):
            now = i / 10; e.display_light_until = now + 3
            o = observation(now, i, 'Eyes closed'); o.brightness = 240
            decision = e.update(o, now)
        self.assertTrue(decision.alarm)
        self.assertEqual(e.profile.brightness, original)


if __name__ == '__main__': unittest.main()
