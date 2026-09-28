"""Exercise actual failures and recovery; synthetic data do not validate hardware."""
import json
import os
import tempfile
import time
import tkinter as tk
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from wakeguard.app import App
from wakeguard.calibration import CalibrationSession, CalibrationError
from wakeguard.dashboard import next_step
from wakeguard.demo import observation
from test_glasses_natural_050 import contextual, natural_session, glasses_session


def take(session, key, screen=0, closed=False, hidden=False):
    session.select_capture(key, screen)
    session.begin(0)
    for i in range(round(session.stage.seconds * 10)):
        t = (i+1)/10
        o = contextual(replace(observation(t, i+1, 'Eyes closed' if closed else 'Awake'), yaw=20+screen*30))
        if hidden:
            o = replace(o, left_q=0, right_q=0)
        session.add(o, t)
    session.finish()


class RecoveryTests(unittest.TestCase):
    def session(self, screens=2, glasses=False):
        c = CalibrationSession(screens, glasses)
        c.guided_pairs = True
        take(c, 'main')
        return c

    def test_pairs_are_collected_together_before_other_postures(self):
        c = self.session()
        self.assertTrue(c.advance())
        self.assertEqual(c.capture_position(), ('monitors', 0))
        take(c, 'monitors')
        self.assertTrue(c.advance())
        self.assertEqual(c.capture_position(), ('closed_main', 0))
        take(c, 'closed_main', closed=True)
        self.assertTrue(c.advance())
        self.assertEqual(c.capture_position(), ('monitors', 1))

    def test_overlapping_monitor_two_eyes_fail_immediately_keep_monitor_one(self):
        c = self.session()
        take(c, 'monitors'); take(c, 'closed_main', closed=True)
        before = list(c.closed_monitor_samples[0])
        take(c, 'monitors', 1)
        with self.assertRaisesRegex(CalibrationError, 'screen 2') as raised:
            take(c, 'closed_main', 1, closed=False)
        self.assertEqual(c.closed_monitor_samples[0], before)
        self.assertNotIn(1, c.closed_monitor_samples)
        self.assertEqual(c.capture_status('closed_main', 1), 'Retry needed')
        self.assertEqual(raised.exception.targets, [('monitors', 1), ('closed_main', 1)])
        take(c, 'closed_main', 1, closed=True)
        self.assertTrue(c.advance())
        self.assertEqual(c.capture_position(), ('left', 0))

    def test_failed_replacement_keeps_previous_good_capture(self):
        c = self.session(1)
        take(c, 'monitors'); take(c, 'closed_main', closed=True)
        saved = list(c.closed_monitor_samples[0])
        with self.assertRaises(CalibrationError):
            take(c, 'closed_main', closed=False)
        self.assertEqual(c.closed_monitor_samples[0], saved)
        self.assertFalse(c.complete('closed_main'))
        self.assertTrue(c.keep_previous())
        self.assertTrue(c.complete('closed_main'))

    def test_failed_optional_replacement_does_not_erase_success(self):
        c=natural_session(2); c.guided_pairs=True
        previous=list(c.samples['neck_down'])
        c.select_capture('neck_down'); c.begin(0)
        c.finish()
        self.assertEqual(c.samples['neck_down'],previous)
        self.assertIn('earlier successful',c.retake_note)

    def test_bare_eye_retry_after_glasses_stage_explicitly_says_glasses_off(self):
        c=self.session(2,True)
        c.select_capture('monitors',1)
        self.assertIn('Glasses OFF',c.stage.instruction)

    def test_retry_pair_skips_all_saved_postures_after_success(self):
        c = natural_session(2); c.guided_pairs = True
        c.mark_repair([('monitors',1), ('closed_main',1)], 'Redo only monitor 2')
        other = list(c.samples['left'])
        c.next_needed(); self.assertEqual(c.capture_position(), ('monitors',1))
        take(c,'monitors',1)
        c.advance(); self.assertEqual(c.capture_position(), ('closed_main',1))
        take(c,'closed_main',1,closed=True)
        self.assertFalse(c.advance())
        self.assertEqual(c.samples['left'],other)

    def test_repeat_open_requires_rechecking_only_its_closed_partner(self):
        c = natural_session(2); c.guided_pairs = True
        take(c,'monitors',1)
        self.assertTrue(c.advance())
        self.assertEqual(c.capture_position(),('closed_main',1))
        self.assertTrue(c.complete('closed_main',0))

    def test_glare_is_limited_at_that_pair_and_does_not_block(self):
        c = glasses_session(2, obscure_screen=1); c.guided_pairs = True
        c.select_capture('glasses_on_closed',1); c.begin(0)
        for i,o in enumerate(c.glasses_closed_samples[1]):
            fresh=replace(o,t=(i+1)/10,seq=i+1)
            c.add(fresh,fresh.t)
        c.finish()
        self.assertEqual(c.capture_status('glasses_on_closed',1),'Limited · saved')
        self.assertFalse(c.advance())
        self.assertFalse(c.build().glasses_info()['coverage']['2']['eye_observable'])

    def test_draft_round_trip_keeps_samples_failures_and_camera(self):
        c=self.session(); take(c,'monitors')
        with self.assertRaises(CalibrationError): take(c,'closed_main')
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'draft.json'
            c.save_draft(path,{'camera':'0','backend':'auto'})
            restored,config=CalibrationSession.load_draft(path)
            self.assertEqual(restored.monitor_samples,c.monitor_samples)
            self.assertEqual(restored.issues,c.issues)
            self.assertEqual(restored.pending_pairs,c.pending_pairs)
            self.assertEqual(config,{'camera':'0','backend':'auto'})
            self.assertFalse(restored.recording)
            restored.next_needed()
            self.assertEqual(restored.capture_position(),('closed_main',0))
            text=path.read_text()
            self.assertNotIn('preview',text)
            self.assertNotIn('base64',text)

    def test_interrupted_take_is_not_in_checkpoint(self):
        c=self.session(); c.advance(); c.begin(10)
        c.add(contextual(observation(10.1,1)),10.1)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'draft.json'; c.save_draft(p,{})
            restored,_=CalibrationSession.load_draft(p)
            self.assertEqual(restored.current,[])
            self.assertTrue(restored.complete('main'))
            self.assertFalse(restored.complete('monitors',0))

    def test_progress_counts_screens_and_glasses_not_only_stage_types(self):
        c=self.session(3,True)
        self.assertEqual(len(c.capture_tasks()),25)
        self.assertEqual(sum(c.complete(*t) for t in c.capture_tasks()),1)

    def test_final_safeguard_has_machine_readable_retry_targets(self):
        c=natural_session(2)
        c.closed_monitor_samples[1]=c.monitor_samples[1]
        with self.assertRaises(CalibrationError) as raised: c.build()
        self.assertEqual(raised.exception.targets,[('monitors',1),('closed_main',1)])

    def test_complete_three_screen_glasses_flow_builds_after_one_targeted_retry(self):
        source=glasses_session(3)
        c=CalibrationSession(3,True); c.guided_pairs=True
        completed=[]; retried=False
        while True:
            key,screen=c.capture_position()
            mapping={'monitors':source.monitor_samples,'closed_main':source.closed_monitor_samples,
                     'glasses_on_open':source.glasses_open_samples,'glasses_on_closed':source.glasses_closed_samples}
            values=mapping[key][screen] if key in mapping else source.samples[key]
            c.begin(0)
            failing=key=='closed_main' and screen==1 and not retried
            for i in range(round(c.stage.seconds*10)):
                o=replace(values[i%len(values)],t=(i+1)/10,seq=i+1)
                if failing: o=replace(o,left=.32,right=.32)
                c.add(o,o.t)
            if failing:
                with self.assertRaises(CalibrationError): c.finish()
                self.assertTrue(c.complete('closed_main',0)); retried=True
                continue
            c.finish();completed.append((key,screen))
            if not c.advance():break
        self.assertTrue(retried)
        self.assertEqual(len(completed),25)
        self.assertEqual(len(set(completed)),25)
        p=c.build()
        self.assertTrue(p.report['valid']); self.assertTrue(p.glasses_info()['enabled'])


@unittest.skipUnless(os.environ.get('WAKEGUARD_GUI_TESTS')=='1' or os.environ.get('DISPLAY'),'Actual Tk desktop required')
class RecoveryGUITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'WAKEGUARD_DATA_DIR':self.tmp.name}); self.env.start()
        self.root=tk.Tk(); self.app=App(self.root,testing=True)
    def tearDown(self):
        if not self.app.closing: self.app.quit()
        self.env.stop(); self.tmp.cleanup()
    def setup_session(self):
        a=self.app
        a.state='CALIBRATING'; a.audio_confirmed=True
        a.cal=natural_session(2); a.cal.guided_pairs=True
        a.draft_config={'camera':'0','backend':'auto'}
        a.cal.select_capture('closed_main',1)
        a.cal_phase='REVIEW'; a.cal_good=True
        a.latest=contextual(observation(time.monotonic(),1))
        return a

    def test_glasses_choice_and_primary_action_stay_visible_on_small_screen(self):
        a=self.app; self.root.geometry('944x668'); a.view.render(); self.root.update()
        bottom=self.root.winfo_rooty()+self.root.winfo_height()-64
        for widget in (a.view.glasses_check,a.view.screen_count,a.view.next_button):
            self.assertTrue(widget.winfo_ismapped())
            self.assertLess(widget.winfo_rooty()+widget.winfo_height(),bottom)
        a.view.canvas.yview_moveto(1); self.root.update()
        self.assertLess(a.view.glasses_check.winfo_rooty()+a.view.glasses_check.winfo_height(),bottom)

    def test_preferences_cannot_silently_change_active_plan(self):
        a=self.setup_session()
        a.glasses_setup_var.set(True); a.save_glasses_preferences()
        self.assertFalse(a.glasses_setup_var.get())
        self.assertFalse(a.cal.glasses_enabled)

    def test_active_calibration_keeps_checklist_and_retry_control_visible(self):
        a=self.setup_session(); self.root.geometry('944x668')
        a.cal.issues['closed_main:1']='Retry Monitor 2'
        a.cal_text.set('Monitor 2 · Eyes closed needs a retry. Other saved captures are kept.')
        a.cal_good=False
        a.view.render(); self.root.update()
        bottom=self.root.winfo_rooty()+self.root.winfo_height()-64
        self.assertGreater(a.view.canvas.winfo_height(),170)
        self.assertLess(a.view.repeat_selected.winfo_rooty()+a.view.repeat_selected.winfo_height(),bottom)
        self.assertLess(a.view.capture_list.winfo_rooty()+60,bottom)

    def test_explicit_late_addition_keeps_completed_samples(self):
        a=self.setup_session(); saved=list(a.cal.monitor_samples[1])
        a.add_glasses_steps()
        self.assertTrue(a.cal.glasses_enabled)
        self.assertEqual(a.cal.monitor_samples[1],saved)
        self.assertTrue(a.cal.next_needed())
        self.assertEqual(a.cal.capture_position(),('glasses_on_open',0))

    def test_stop_quit_reopen_resume_keeps_numeric_captures(self):
        a=self.setup_session(); saved=list(a.cal.monitor_samples[1])
        a.cal.issues['closed_main:1']='Retry closed eyes'
        a.stop_all()
        self.assertIsNone(a.cal); self.assertTrue(a.draft_path.exists())
        a.quit()
        self.root=tk.Tk(); self.app=App(self.root,testing=True); a=self.app
        self.assertEqual(a.draft.monitor_samples[1],saved)
        a.state='PREVIEW'; a.audio_confirmed=True
        a.latest=contextual(observation(time.monotonic(),1))
        a.resume_calibration()
        self.assertEqual(a.cal.capture_position(),('closed_main',1))
        self.assertEqual(a.cal.monitor_samples[1],saved)

    def test_camera_mismatch_refuses_resume_without_discard(self):
        a=self.setup_session(); a.stop_all()
        a.state='PREVIEW'; a.audio_confirmed=True
        a.latest=replace(contextual(observation(time.monotonic(),1)),camera_key='another-camera')
        draft=a.draft; a.resume_calibration()
        self.assertIs(a.draft,draft); self.assertIsNone(a.cal)
        self.assertIn('different camera',a.detail.get())

    def test_final_failure_goes_to_named_monitor_and_pair_action(self):
        a=self.setup_session()
        a.cal.closed_monitor_samples[1]=a.cal.monitor_samples[1]
        a._finish_calibration(); a.view.render()
        self.assertEqual(a.cal.capture_position(),('monitors',1))
        self.assertIn('screen 2',a.cal_text.get())
        self.assertIn('RETRY NEEDED',a.status.get())
        self.assertTrue(a.cal.complete('closed_main',0))
        self.assertEqual(a.repair_targets,[('monitors',1),('closed_main',1)])

    def test_save_failure_offers_save_retry_without_recapture(self):
        a=self.setup_session()
        with patch('wakeguard.model.atomic_json',side_effect=OSError('disk full')):
            a._finish_calibration()
        self.assertEqual(next_step(a).action,'save_calibration')
        self.assertTrue(a.cal.complete('monitors',1))
        a._cancel_speech()
        a._finish_calibration()
        self.assertIsNone(a.cal); self.assertIsNone(a.draft)
        self.assertTrue(a.profile_path.exists())

    def test_choose_capture_cancels_stale_countdown_and_keeps_screen_index(self):
        a=self.setup_session()
        a._say('Countdown',a._capture_begin,role='countdown')
        a.repeat_capture('monitors',1)
        self.assertEqual(a.cal.capture_position(),('monitors',1))
        self.assertEqual(a.speech_role,'instruction')
        self.assertNotEqual(a.speech_after,a._capture_begin)

if __name__=='__main__': unittest.main()
