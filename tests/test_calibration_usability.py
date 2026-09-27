"""Field-report regressions: per-screen coverage, bounded waits and speech barge-in."""
import os
import tempfile
import time
import unittest
from dataclasses import replace
from unittest.mock import patch
import tkinter as tk
from tkinter import ttk

from wakeguard.app import App
from wakeguard.calibration import CalibrationSession, CalibrationError, STAGES, measurement_issue
from wakeguard.demo import observation
from wakeguard.model import Observation
from test_core import full_calibration


class CaptureQualityTests(unittest.TestCase):
    def feed(self, c, start, seconds, good=True, edit=None):
        for i in range(1, round(seconds * 10) + 1):
            t = round(start + i * .1, 5)
            o = observation(t, round(t * 10))
            if not good:
                o = replace(o, left_q=0, right_q=0)
            if edit:
                o = edit(o)
            c.add(o, t)
        return round(start + seconds, 5)

    def test_eyeopen_collection_waits_for_recovered_coverage(self):
        c=CalibrationSession();c.index=1;c.begin(0)
        self.feed(c,0,4,False)
        self.feed(c,4,4)
        self.assertFalse(c.due(8))
        self.feed(c,8,4)
        self.assertTrue(c.due(12))
        c.finish()
        self.assertGreaterEqual(c.valid_seconds,c.required_seconds)
        self.assertGreaterEqual(len(c.current)/c.total_frames,.65)

    def test_reported_low_coverage_cannot_be_passed_by_waiting(self):
        c=CalibrationSession();c.index=1;c.begin(0)
        for i in range(240):
            t=(i+1)*.1
            o=observation(t,i+1)
            if i%10>=3:o=replace(o,left_q=0,right_q=0)
            c.add(o,t)
        self.assertTrue(c.due(24))
        with self.assertRaisesRegex(CalibrationError,"eyes not measurable"):
            c.finish()
        self.assertFalse(c.recording)

    def test_three_screens_cannot_be_replaced_by_one_good_view(self):
        c=CalibrationSession(monitor_count=3);c.index=1
        for view in range(3):
            self.assertEqual(c.monitor_index,view)
            self.assertIn(("MAIN","SECOND","THIRD")[view],c.stage.instruction)
            c.begin(0);self.feed(c,0,8);c.finish()
            c.advance()
            self.assertEqual(c.index,1 if view<2 else 2)
        self.assertEqual(set(c.monitor_samples),{0,1,2})
        self.assertEqual(len(c.samples['monitors']),240)

    def test_build_rejects_missing_selected_screen(self):
        c=full_calibration();c.monitor_count=2
        c.monitor_samples[0]=c.samples['monitors']
        with self.assertRaisesRegex(CalibrationError,"Each selected screen"):
            c.build()

    def test_repeat_previous_traverses_monitor_views(self):
        c=CalibrationSession(3);c.index=2
        c.repeat_previous();self.assertEqual((c.index,c.monitor_index),(1,2))
        c.repeat_previous();self.assertEqual((c.index,c.monitor_index),(1,1))
        c.repeat_previous();self.assertEqual((c.index,c.monitor_index),(1,0))
        c.repeat_previous();self.assertEqual(c.index,0)

    def test_cancel_discards_partial_not_accepted_views(self):
        c=CalibrationSession(2);c.index=1;c.begin(0);self.feed(c,0,8);c.finish()
        first=list(c.monitor_samples[0]);c.advance();c.begin(10);self.feed(c,10,2)
        c.cancel_capture()
        self.assertFalse(c.recording);self.assertEqual(c.current,[])
        self.assertEqual(c.monitor_samples[0],first)
        self.assertNotIn(1,c.monitor_samples)

    def test_no_credit_across_invalid_or_missing_interval(self):
        c=CalibrationSession();c.begin(0)
        c.add(observation(.1,1),.1)
        c.add(replace(observation(.2,2),left_q=0,right_q=0),.2)
        c.add(observation(.3,3),.3)
        self.assertEqual(c.valid_seconds,0)
        c.add(observation(.4,4),.4)
        self.assertAlmostEqual(c.valid_seconds,.1)
        c.add(observation(2,5),2)
        self.assertAlmostEqual(c.valid_seconds,.1)

    def test_frames_from_countdown_not_counted(self):
        c=CalibrationSession();c.begin(10)
        c.add(observation(9.9,1),10.1)
        self.assertEqual(c.current,[])
        self.assertEqual(c.total_frames,0)

    def test_no_extra_wait_for_half_or_closed_eyes(self):
        for index,stage in enumerate(STAGES):
            if stage.eyes in ('half','closed'):
                with self.subTest(stage=stage.key):
                    c=CalibrationSession();c.index=index;c.begin(0)
                    self.assertFalse(c.due(stage.seconds-.01))
                    self.assertTrue(c.due(stage.seconds))
                    with self.assertRaises(CalibrationError):c.finish()

    def test_eyeopen_no_frames_still_times_out(self):
        c=CalibrationSession();c.begin(0)
        self.assertFalse(c.due(c.stage.seconds))
        self.assertTrue(c.due(c.stage.time_limit))

    def test_quality_diagnostic_distinguishes_lost_pose_and_eyes(self):
        o=observation(1,1);o.pitch=None
        self.assertIn('head pose',measurement_issue(o,1,STAGES[0]))
        o.pitch=0;o.face=False
        self.assertIn('face not detected',measurement_issue(o,1,STAGES[0]))
        o.face=True;o.left_q=o.right_q=0
        o.diagnostics={'left_reason':'eye too small (10px)','right_reason':'eye image is blurred'}
        text=measurement_issue(o,1,STAGES[0])
        self.assertIn('10px',text);self.assertIn('blurred',text)
        self.assertIn('late',measurement_issue(o,2,STAGES[0]))

    def test_completion_cue_matches_every_stage(self):
        for stage in STAGES:
            if stage.eyes in ('closed','half'):self.assertEqual(stage.completion_cue,'Open your eyes.')
            elif stage.eyes=='absent':self.assertIn('return',stage.completion_cue)
            else:self.assertNotIn('Open your eyes',stage.completion_cue)

    def test_monitor_count_is_validated(self):
        for bad in (0,4,-1,'2',True):
            with self.subTest(count=bad),self.assertRaises(ValueError):CalibrationSession(bad)

    def test_bad_diagnostic_payload_is_sanitized(self):
        o=Observation.from_dict({'t':1,'diagnostics':{'a':float('nan'),'b':{},'c':'x'*200,'d':'small'}})
        self.assertEqual(o.diagnostics,{'d':'small'})

    def test_quality_counts_aggregate_variable_eye_width_messages(self):
        c=CalibrationSession();c.begin(0)
        for i in range(1,10):
            o=replace(observation(i*.1,i),left_q=0,right_q=0,
                      diagnostics={'left_reason':f'eye too small ({i}px)'})
            c.add(o,i*.1)
        self.assertEqual(c.rejected['eyes not measurable'],9)
        self.assertIn('9px',c.quality_summary())

    def test_eye_math_reports_too_small_and_blurred_without_lowering_gates(self):
        import numpy as np
        from wakeguard.vision_math import eye_measure
        points=np.array([[20,20],[22,19],[24,19],[25,20],[24,21],[22,21]],dtype=float)
        d={};value,quality=eye_measure(points,list(range(6)),np.full((100,100),100,np.uint8),d)
        self.assertIsNone(value);self.assertIn('small',d['reason'])
        points[:,0]*=3
        value,quality=eye_measure(points,list(range(6)),np.full((100,100),100,np.uint8),d)
        self.assertIsNone(value);self.assertIn('blurred',d['reason'])

    def test_pose_math_reports_geometry_failure(self):
        import numpy as np
        from wakeguard.vision_math import head_pose
        d={};result=head_pose(np.zeros((468,2)),640,480,d)
        self.assertIsNone(result);self.assertIn('invalid',d['pose_reason'])


@unittest.skipUnless(os.environ.get('WAKEGUARD_GUI_TESTS')=='1' or os.environ.get('DISPLAY'),'GUI opt-in')
class SpeechInterruptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'WAKEGUARD_DATA_DIR':self.tmp.name});self.env.start()
        self.root=tk.Tk();self.app=App(self.root,demo=True,testing=True);self.root.update()
        self.app.latest=observation(time.monotonic(),1);self.app.audio_confirmed=True;self.app.state='PREVIEW'
        self.app.begin_calibration()
    def tearDown(self):
        if not self.app.closing:self.app.quit()
        self.env.stop();self.tmp.cleanup()
    def pump(self):
        self.app._poll();self.root.update()
        if self.app.poll_job:self.root.after_cancel(self.app.poll_job);self.app.poll_job=None
    def ready(self):
        self.pump();self.assertEqual(self.app.cal_phase,'READY')
    def capture(self,index=0):
        self.app.cal.select_stage(index);self.app._prompt_stage();self.pump()
        self.app.last_actions.clear();self.app.action('space');self.pump()
        self.assertEqual(self.app.cal_phase,'CAPTURE')
    def button(self,text):
        pending=[self.root]
        while pending:
            w=pending.pop()
            if isinstance(w,(tk.Button,ttk.Button)) and w.cget('text')==text:return w
            pending.extend(w.winfo_children())
        raise AssertionError(text)
    def fill_current(self):
        c=self.app.cal
        c.current=list(full_calibration().samples[c.stage.key])
        c.valid_seconds=c.stage.seconds;c.total_frames=len(c.current)

    def test_space_skips_instruction_but_retains_countdown(self):
        old=self.app.speech.token
        self.assertTrue(self.app.speech.busy)
        self.app.action('space')
        self.assertGreater(self.app.speech.token,old)
        self.assertEqual(self.app.speech_role,'countdown')
        self.assertFalse(self.app.cal.recording)
        self.pump();self.assertTrue(self.app.cal.recording)

    def test_repeat_during_instruction_is_short_and_interrupts(self):
        original=self.app.cal;old=self.app.speech.token
        with patch.object(self.app.speech,'say',wraps=self.app.speech.say) as say:
            self.app.action('r')
            text=say.call_args.args[0]
            self.assertNotIn('Sit upright in your normal working position',text)
            self.assertLess(len(text),100)
        self.assertIs(self.app.cal,original);self.assertGreater(self.app.speech.token,old)
        self.pump();self.assertEqual(self.app.cal_phase,'READY')

    def test_back_during_instruction_changes_stage_immediately(self):
        self.app.cal.index=3;self.app._prompt_stage();self.app.action('b')
        self.assertEqual(self.app.cal.index,2)
        self.pump();self.assertEqual(self.app.cal_phase,'READY')
        self.assertFalse(self.app.cal.recording)

    def test_repeat_during_countdown_prevents_old_capture(self):
        self.ready();self.app.action('space');self.assertEqual(self.app.speech_role,'countdown')
        self.app.action('r');self.pump()
        self.assertEqual(self.app.cal_phase,'READY');self.assertFalse(self.app.cal.recording)

    def test_repeat_button_during_speech_uses_same_interrupt_path(self):
        old=self.app.speech.token;self.button('Repeat').invoke()
        self.assertGreater(self.app.speech.token,old)
        self.pump();self.assertEqual(self.app.cal_phase,'READY')

    def test_previous_button_during_speech_uses_same_interrupt_path(self):
        self.app.cal.index=2;self.app._prompt_stage();self.button('Previous').invoke()
        self.assertEqual(self.app.cal.index,1)
        self.pump();self.assertEqual(self.app.cal_phase,'READY')

    def test_voice_repeat_is_not_muted_by_speech(self):
        token=self.app.speech.token;self.app.voice_muted_until=time.monotonic()+100
        self.app._handle_voice_event({'event':'command','text':'wakeguard repeat','at_utc':time.time()})
        self.assertGreater(self.app.speech.token,token)
        self.pump();self.assertEqual(self.app.cal_phase,'READY')

    def test_voice_ready_skips_instruction(self):
        self.app._handle_voice_event({'event':'command','text':'wakeguard ready','at_utc':time.time()})
        self.assertEqual(self.app.speech_role,'countdown')

    def test_old_voice_command_is_not_replayed(self):
        token=self.app.speech.token
        self.app._handle_voice_event({'event':'command','text':'wakeguard repeat','at_utc':time.time()-30})
        self.assertEqual(self.app.speech.token,token)

    def test_voice_next_cannot_start_or_skip_capture(self):
        token=self.app.speech.token
        self.app._handle_voice_event({'event':'command','text':'wakeguard next','at_utc':time.time()})
        self.assertEqual(self.app.speech.token,token)
        self.capture();self.app.last_actions.clear()
        self.app._handle_voice_event({'event':'command','text':'wakeguard next','at_utc':time.time()})
        self.assertEqual(self.app.cal_phase,'CAPTURE')

    def test_normal_completion_does_not_say_open_your_eyes(self):
        self.capture();self.fill_current()
        with patch.object(self.app.speech,'say',wraps=self.app.speech.say) as say:
            self.app._capture_done()
            self.assertNotIn('Open your eyes',say.call_args.args[0])

    def test_empty_completion_says_return_to_chair(self):
        self.capture(14);self.fill_current()
        with patch.object(self.app.speech,'say',wraps=self.app.speech.say) as say:
            self.app._capture_done()
            self.assertIn('return to your chair',say.call_args.args[0])
            self.assertNotIn('Open your eyes',say.call_args.args[0])

    def test_closed_completion_has_separate_recovery_then_review(self):
        self.capture(10);self.fill_current();self.app._capture_done()
        self.assertEqual(self.app.speech_role,'recovery')
        self.pump();self.assertEqual(self.app.speech_role,'review')
        self.pump();self.assertEqual(self.app.cal_phase,'REVIEW')
        self.assertFalse(self.app.eyes_lowered_possible)

    def test_interrupt_half_closed_capture_discards_partial_and_reopens(self):
        self.capture(9);self.app.cal.current=[observation(time.monotonic(),111)]
        self.app.action('r')
        self.assertFalse(self.app.cal.recording);self.assertEqual(self.app.cal.current,[])
        self.assertEqual(self.app.speech_role,'recovery')
        self.app.last_actions.clear();self.app.action('space')
        self.assertEqual(self.app.speech_role,'recovery')
        self.pump();self.pump();self.assertEqual(self.app.cal_phase,'READY')

    def test_repeated_back_cannot_skip_recovery_after_stage_changed(self):
        self.capture(9);self.app.action('b')
        self.app.last_actions.clear();self.app.action('b')
        self.assertEqual(self.app.cal.index,7)  # now an eyes-open stage
        self.assertEqual(self.app.speech_role,'recovery')
        self.assertTrue(self.app.eyes_lowered_possible)
        self.pump();self.pump();self.assertFalse(self.app.eyes_lowered_possible)
        self.assertEqual(self.app.cal_phase,'READY')

    def test_open_capture_interrupt_has_no_unnecessary_eye_cue(self):
        self.capture(3)
        with patch.object(self.app.speech,'say',wraps=self.app.speech.say) as say:
            self.app.action('b')
            self.assertNotIn('Open your eyes',say.call_args.args[0])
        self.assertFalse(self.app.cal.recording)

    def test_review_speech_can_be_accepted_without_finishing(self):
        self.capture();self.fill_current();self.app._capture_done()
        self.assertEqual(self.app.speech_role,'review');self.app.last_actions.clear()
        self.app.action('space');self.assertEqual(self.app.cal.index,1)
        self.pump();self.assertEqual(self.app.cal_phase,'READY')

    def test_bad_review_cannot_be_accepted_by_barge_in(self):
        self.capture();self.app._capture_done();self.app.last_actions.clear()
        self.app.action('space')
        self.assertEqual(self.app.cal.index,0);self.assertFalse(self.app.cal_good)
        self.assertEqual(self.app.cal_phase,'REVIEW')

    def test_stop_cancels_recovery_and_its_next_callback(self):
        self.capture(10);self.app.action('r');self.app.stop_all();self.pump()
        self.assertEqual(self.app.state,'STOPPED');self.assertIsNone(self.app.cal)
        self.assertFalse(self.app.speech.busy)

    def test_verification_instruction_can_be_repeated_and_backed(self):
        self.app._cancel_speech();self.app.state='VERIFYING';self.app.cal=None
        self.app.verify_index=2;self.app._verify_prompt()
        self.app.action('b');self.assertEqual(self.app.verify_index,1)
        self.pump();self.assertEqual(self.app.cal_phase,'READY')
        self.app.action('space');self.pump();self.assertEqual(self.app.cal_phase,'CAPTURE')
        self.app.action('r');self.pump();self.assertEqual(self.app.cal_phase,'READY')

    def test_two_monitor_stage_requires_two_distinct_accept_actions(self):
        self.app._cancel_speech();self.app.cal=CalibrationSession(2);self.app.cal.index=1
        self.app._prompt_stage();self.pump()
        for view in range(2):
            self.app.last_actions.clear();self.app.action('space');self.pump()
            self.fill_current();self.app._capture_done();self.pump()
            self.app.last_actions.clear();self.app.action('space');self.pump()
            self.assertEqual(self.app.cal.index,1 if view==0 else 2)
        self.assertEqual(len(self.app.cal.monitor_samples),2)

    def test_voice_back_during_speech_changes_stage(self):
        self.app.cal.index=3;self.app._prompt_stage()
        self.app._handle_voice_event({'event':'command','text':'wakeguard back','at_utc':time.time()})
        self.assertEqual(self.app.cal.index,2)
        self.pump();self.assertEqual(self.app.cal_phase,'READY')

    def test_full_three_monitor_calibration_sequence(self):
        self.app._cancel_speech();self.app.cal=CalibrationSession(3);self.app.cal.index=0
        self.app._prompt_stage();self.pump()
        n=0
        while self.app.cal is not None and n<18:
            n+=1
            self.app.last_actions.clear();self.app.action('space');self.pump()
            self.assertEqual(self.app.cal_phase,'CAPTURE')
            self.fill_current();self.app._capture_done();self.pump()
            if self.app.cal_phase=='PROMPT' and self.app.speech_role=='review':self.pump()
            self.assertTrue(self.app.cal_good)
            self.app.last_actions.clear();self.app.action('space');self.pump()
        self.assertEqual(n,17)
        self.assertIsNone(self.app.cal)
        self.assertEqual(self.app.profile.report['monitor_count'],3)

    def test_keyboard_r_interrupts_speech_with_calibrate_focused(self):
        button=self.button('Calibrate');button.focus_force();self.root.update()
        before=self.app.speech.token;session=self.app.cal
        button.event_generate('<KeyPress-r>');self.root.update()
        button.event_generate('<KeyRelease-r>');self.root.update()
        self.assertGreater(self.app.speech.token,before)
        self.assertIs(self.app.cal,session)
        self.pump();self.assertEqual(self.app.cal_phase,'READY')

    def test_keyboard_b_interrupts_speech_with_calibrate_focused(self):
        self.app.cal.index=3;self.app._prompt_stage()
        button=self.button('Calibrate');button.focus_force();self.root.update()
        button.event_generate('<KeyPress-b>');self.root.update()
        button.event_generate('<KeyRelease-b>');self.root.update()
        self.assertEqual(self.app.cal.index,2)
        self.pump();self.assertEqual(self.app.cal_phase,'READY')

    def test_audio_failure_cannot_be_bypassed_by_repeat_and_ready(self):
        self.ready()
        with patch.object(self.app.speech,'say',side_effect=OSError('audio failed')):
            self.app.action('space')
        self.assertFalse(self.app.audio_confirmed)
        self.app.action('r');self.pump()
        self.app.last_actions.clear();self.app.action('space');self.pump()
        self.assertFalse(self.app.cal.recording)
        self.assertEqual(self.app.cal_phase,'AUDIO FAILED')

    def test_closed_countdown_keeps_short_state_label_after_skip(self):
        self.app.cal.select_stage(10);self.app._prompt_stage()
        with patch.object(self.app.speech,'say',wraps=self.app.speech.say) as say:
            self.app.action('space')
            self.assertIn('Close your eyes after Begin',say.call_args.args[0])
            self.assertIn('Three, two, one',say.call_args.args[0])
        self.assertFalse(self.app.cal.recording)

    def test_voice_cannot_navigate_behind_secondary_dialog(self):
        self.ready();dialog=tk.Toplevel(self.root);entry=ttk.Entry(dialog);entry.pack()
        entry.focus_force();self.root.update()
        token=self.app.speech.token
        self.app._handle_voice_event({'event':'command','text':'wakeguard repeat','at_utc':time.time()})
        self.assertEqual(self.app.speech.token,token)
        self.assertEqual(self.app.cal_phase,'READY')
        dialog.destroy()

    def test_empty_capture_completion_invites_return_not_open_eyes(self):
        self.capture(14);self.fill_current()
        with patch.object(self.app.speech,'say',wraps=self.app.speech.say) as say:
            self.app._capture_done()
            text=say.call_args.args[0]
            self.assertIn('return to your chair',text)
            self.assertNotIn('Open your eyes',text)


class DeadlineCoverageTests(unittest.TestCase):
    def test_stale_finish_cannot_pass_with_old_good_frames(self):
        c=CalibrationSession();c.begin(0)
        for i in range(1,91):c.add(observation(i*.1,i),i*.1)
        self.assertTrue(c.quality_met)
        self.assertTrue(c.due(30))
        with self.assertRaisesRegex(CalibrationError,'no fresh camera'):c.finish()

    def test_invalid_end_cannot_pass_with_old_good_frames(self):
        c=CalibrationSession();c.begin(0)
        for i in range(1,291):c.add(observation(i*.1,i),i*.1)
        c.add(replace(observation(30,300),face=False),30)
        self.assertTrue(c.quality_met);self.assertTrue(c.due(30))
        with self.assertRaisesRegex(CalibrationError,'face not detected'):c.finish()

    def test_frames_past_closed_eye_deadline_never_count(self):
        c=CalibrationSession();c.index=10;c.begin(0)
        for i in range(1,51):c.add(observation(i*.1,i),i*.1)
        self.assertEqual(len(c.current),30)
        self.assertLessEqual(c.last_t,3)

    def test_selected_screen_outside_closed_reference_is_not_claimed_covered(self):
        c=full_calibration();c.monitor_count=2
        c.monitor_samples={0:list(c.samples['monitors']),
                           1:[replace(o,yaw=100) for o in c.samples['monitors']]}
        c.samples['monitors']=sum(c.monitor_samples.values(),[])
        with self.assertRaisesRegex(CalibrationError,'Work screen 2'):c.build()
