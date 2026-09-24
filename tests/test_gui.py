import os
import tempfile
import time
import unittest
from unittest.mock import patch, Mock
import tkinter as tk
from dataclasses import asdict

from wakeguard.app import App
from wakeguard.calibration import CalibrationSession
from wakeguard.demo import observation, demo_profile
from wakeguard.engine import Engine
from test_core import full_calibration


@unittest.skipUnless(os.environ.get("WAKEGUARD_GUI_TESTS")=="1" or os.environ.get("DISPLAY"),"GUI requires Windows desktop or Xvfb")
class GUITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{"WAKEGUARD_DATA_DIR":self.tmp.name});self.env.start()
        self.root=tk.Tk();self.app=App(self.root,demo=True,testing=True)
        self.root.update()
    def tearDown(self):
        if not self.app.closing:self.app.quit()
        self.env.stop();self.tmp.cleanup()
    def pump(self):
        self.app._poll();self.root.update()
        if self.app.poll_job:
            self.root.after_cancel(self.app.poll_job);self.app.poll_job=None
    def test_test_flash_space_acknowledges(self):
        self.app.test_screen();self.root.update();self.assertTrue(self.app.screen.active)
        self.app.screen.windows[0].event_generate("<space>");self.root.update()
        self.assertFalse(self.app.screen.active)
    def test_escape_acknowledges(self):
        self.app.test_screen();self.root.update()
        self.app.screen.windows[0].event_generate("<Escape>");self.root.update()
        self.assertFalse(self.app.screen.active)
    def test_ctrl_shift_a_acknowledges(self):
        self.app.test_screen();self.root.update()
        self.app.screen.windows[0].event_generate("<Control-Shift-A>");self.root.update()
        self.assertFalse(self.app.screen.active)
    def test_per_monitor_windows_single_text(self):
        self.app.screen.monitor_provider=lambda:[dict(x=0,y=0,w=700,h=800,primary=True),dict(x=700,y=0,w=700,h=800,primary=False)]
        self.app.test_screen();self.root.update()
        self.assertEqual(len(self.app.screen.windows),2);self.assertEqual(len(self.app.screen.fields),1)
        self.app.stop_all();self.assertEqual(self.app.screen.windows,[])
    def test_stop_during_calibration_cancels_all(self):
        self.app.state="CALIBRATING";self.app.cal=CalibrationSession();self.app.cal.begin(time.monotonic())
        self.app.cal_phase="CAPTURE";self.app.speech.say("test");self.app.test_screen()
        with patch.object(self.app.camera,"stop") as camera_stop,patch.object(self.app.phone,"stop") as phone_stop:
            self.app.stop_all();camera_stop.assert_called_once();phone_stop.assert_called_once()
        self.assertEqual(self.app.state,"STOPPED");self.assertIsNone(self.app.cal)
        self.assertFalse(self.app.speech.busy);self.assertIsNone(self.app.latest)
    def test_stop_during_monitoring(self):
        self.app.state="MONITORING";self.app.engine=Engine(demo_profile());self.app.test_screen()
        self.app.stop_all();self.assertIsNone(self.app.engine);self.assertFalse(self.app.screen.active)
    def test_start_requires_verification(self):
        self.app.state="PREVIEW";self.app.latest=observation(time.monotonic(),1)
        self.app.start_monitoring();self.assertEqual(self.app.state,"PREVIEW")
    def test_start_after_verification_and_idempotent(self):
        self.app.state="PREVIEW";self.app.latest=observation(time.monotonic(),1);self.app.verified=True
        self.app.start_monitoring();engine=self.app.engine;self.app.start_monitoring()
        self.assertEqual(self.app.state,"MONITORING");self.assertIs(self.app.engine,engine)
    def test_calibration_needs_audio_confirmation(self):
        self.app.latest=observation(time.monotonic(),1);self.app.state="PREVIEW"
        self.app.begin_calibration();self.assertNotEqual(self.app.state,"CALIBRATING")
    def test_stage_waits_for_ready_before_capture(self):
        self.app.audio_confirmed=True;self.app.latest=observation(time.monotonic(),1);self.app.state="PREVIEW"
        self.app.begin_calibration();self.pump();self.assertEqual(self.app.cal_phase,"READY")
        self.assertFalse(self.app.cal.recording)
        self.app.action("space");self.pump();self.assertTrue(self.app.cal.recording)
    def test_failed_capture_opens_eyes_and_allows_repeat(self):
        self.app.cal=CalibrationSession();self.app.cal.index=10;self.app.cal.begin(0)
        self.app.state="CALIBRATING";self.app.cal_phase="CAPTURE"
        with patch.object(self.app.speech,"say",return_value=1) as say:
            self.app._capture_done();self.assertIn("Open your eyes",say.call_args[0][0])
        self.assertFalse(self.app.cal_good);self.assertFalse(self.app.cal.recording)
    def test_bad_saved_profile_can_be_replaced(self):
        self.app.profile_path.write_text("broken old record")
        self.app.cal=full_calibration();self.app.state="CALIBRATING"
        self.app._finish_calibration()
        self.assertIsNone(self.app.cal);self.assertEqual(self.app.state,"PREVIEW")
        self.assertTrue(list(self.app.home.glob("calibration-backup-*")))
    def test_speech_failure_prevents_closed_capture(self):
        self.app.state="CALIBRATING";self.app.cal=CalibrationSession();self.app.cal_phase="READY"
        with patch.object(self.app.speech,"say",side_effect=OSError()):self.app.action("space")
        self.assertFalse(self.app.cal.recording)
    def test_stop_while_speech_callback_pending(self):
        self.app.state="CALIBRATING";self.app.cal=CalibrationSession()
        self.app._say("test",self.app._capture_begin);self.app.stop_all();self.pump()
        self.assertEqual(self.app.state,"STOPPED")
    def test_global_stop_action_accessible(self):
        self.app.test_screen();self.app.action("stop");self.assertFalse(self.app.screen.active)
    def test_quit_destroys_windows(self):
        self.app.test_screen();self.app.quit();self.assertTrue(self.app.closing)
    def test_window_fault_stops_camera(self):
        self.app.state="MONITORING";self.app.engine=Engine(demo_profile())
        with patch.object(self.app.camera,"stop") as stop:
            self.app._callback_error(ValueError,ValueError(),None);stop.assert_called_once()
        self.assertEqual(self.app.state,"STOPPED")
    def test_voice_stop_works_during_spoken_prompt(self):
        self.app.state="CALIBRATING";self.app.cal=CalibrationSession();self.app.cal_phase="PROMPT"
        self.app.speech.pending=True;self.app.voice_muted_until=time.monotonic()+100
        self.app.voice.events.put({"event":"command","text":"wakeguard stop"})
        with patch.object(self.app.speech,"poll",return_value=None):self.pump()
        self.assertEqual(self.app.state,"STOPPED")
    def test_wrong_posture_verification_blocks_start(self):
        self.app.state="VERIFYING";self.app.verify_index=0
        self.app.verify_samples=[observation(time.monotonic(),i,"Reclined awake") for i in range(20)]
        self.app._verify_finish();self.assertFalse(self.app.verified);self.assertEqual(self.app.state,"PREVIEW")

if __name__=="__main__":unittest.main()
