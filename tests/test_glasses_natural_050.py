"""WakeGuard 0.5 regressions: natural motion and personalized glasses support.

Synthetic observations verify software behavior only, not real-camera accuracy.
"""
import math
import os
import tempfile
import time
import tkinter as tk
import unittest
from dataclasses import replace
from unittest.mock import patch

from wakeguard.app import App
from wakeguard.calibration import CalibrationSession, STAGES, measurement_issue
from wakeguard.demo import observation
from wakeguard.engine import Engine
from wakeguard.glasses import FEATURE_COUNT, build_prototype, classify_descriptor, prototype_separation
from wakeguard.target_tracking import FaceBox, TargetTracker
from test_core import full_calibration


def contextual(o, variation=0.0):
    pitch, yaw = o.pitch or 0, o.yaw or 20
    return replace(o, shape=[(yaw-20)*.01, .35+pitch*.010+variation,
                             1.30-pitch*.009+variation, (yaw-20)*.018,
                             variation*10],
                   pitch=None, yaw=None, roll=None)


def natural_session(screens=2):
    c = full_calibration()
    c.monitor_count = screens
    for key, values in c.samples.items():
        c.samples[key] = [contextual(o, .008*math.sin(i*.3)) for i,o in enumerate(values)]
    for screen in range(screens):
        yaw = 20 + screen*30
        c.monitor_samples[screen] = [
            contextual(replace(observation((i+1)*.1, i+1), yaw=yaw), .012*math.sin(i*.2))
            for i in range(90)
        ]
        c.closed_monitor_samples[screen] = [
            contextual(replace(observation((i+1)*.1, i+1, "Eyes closed"), yaw=yaw), .008*math.sin(i*.2))
            for i in range(30)
        ]
    c.samples["monitors"] = [o for values in c.monitor_samples.values() for o in values]
    c.samples["closed_main"] = [o for values in c.closed_monitor_samples.values() for o in values]
    return c


def descriptor(value):
    return [float(value + (i % 3)*.006) for i in range(FEATURE_COUNT)]


def glasses_session(screens=2, obscure_screen=None):
    c = natural_session(screens)
    c.glasses_enabled = True
    for screen in range(screens):
        off = [replace(o, eyewear=descriptor(.12 + .004*math.sin(i)))
               for i,o in enumerate(c.monitor_samples[screen])]
        c.monitor_samples[screen] = off
        on_open = [replace(o, eyewear=descriptor(.68 + .004*math.sin(i)))
                   for i,o in enumerate(off[:60])]
        q = 0 if obscure_screen == screen else 1
        on_closed = [replace(o, eyewear=descriptor(.68 + .004*math.cos(i)),
                             left_q=q, right_q=q)
                     for i,o in enumerate(c.closed_monitor_samples[screen])]
        if obscure_screen == screen:
            on_open = [replace(o, left_q=0, right_q=0) for o in on_open]
        c.glasses_open_samples[screen] = on_open
        c.glasses_closed_samples[screen] = on_closed
    c.samples["monitors"] = [o for values in c.monitor_samples.values() for o in values]
    c.samples["glasses_on_open"] = [o for values in c.glasses_open_samples.values() for o in values]
    c.samples["glasses_on_closed"] = [o for values in c.glasses_closed_samples.values() for o in values]
    return c


class NaturalCalibrationTests(unittest.TestCase):
    def test_head_angle_fit_does_not_veto_usable_eye_context(self):
        o = contextual(observation(1,1))
        self.assertFalse(o.pose_valid())
        self.assertTrue(o.context_valid())
        self.assertEqual(measurement_issue(o, 1, STAGES[1]), "")

    def test_second_monitor_accepts_natural_motion_without_euler_angles(self):
        c = CalibrationSession(2)
        c.index = 1
        c.monitor_index = 1
        c.begin(0)
        for i in range(80):
            t=(i+1)*.1
            o=contextual(replace(observation(t,i+1), yaw=50,
                                 cx=.5+.02*math.sin(i*.2)),
                         .012*math.sin(i*.4))
            c.add(o,t)
        self.assertTrue(c.due(8))
        c.finish()
        self.assertGreater(c.valid_seconds,7)
        self.assertEqual(len(c.monitor_samples[1]),80)

    def test_target_tracker_does_not_switch_to_larger_passer(self):
        tracker=TargetTracker()
        mine=FaceBox(.30,.20,.32,.42)
        self.assertIsNone(tracker.update([mine],0))
        self.assertEqual(tracker.update([mine],1),0)
        passer=FaceBox(.72,.10,.40,.70)
        self.assertEqual(tracker.update([passer,mine],1.1),1)


class GlassesTests(unittest.TestCase):
    def test_glasses_add_only_two_labelled_stage_types(self):
        c=CalibrationSession(2, glasses_enabled=True)
        self.assertEqual(c.total_steps,17)
        c.index=15
        self.assertEqual(c.stage.key,"glasses_on_open")
        self.assertTrue(c.advance())
        self.assertEqual(c.monitor_index,1)
        self.assertTrue(c.advance())
        self.assertEqual(c.stage.key,"glasses_on_closed")
        self.assertEqual(c.monitor_index,0)

    def test_personalized_auto_classifier_separates_enrolled_conditions(self):
        class O: pass
        off=[]; on=[]
        for i in range(20):
            a=O(); a.eyewear=descriptor(.12+i*.0005); off.append(a)
            b=O(); b.eyewear=descriptor(.68+i*.0005); on.append(b)
        po,pi=build_prototype(off),build_prototype(on)
        self.assertGreater(prototype_separation(po,pi),1.25)
        pair={"off":po,"on":pi,"auto_ok":True}
        self.assertEqual(classify_descriptor(descriptor(.13),pair)[0],"off")
        self.assertEqual(classify_descriptor(descriptor(.69),pair)[0],"on")

    def test_glare_hidden_screen_becomes_unknown_not_failed_calibration(self):
        c=glasses_session(2, obscure_screen=1)
        p=c.build()
        info=p.glasses_info()
        self.assertEqual(info["eye_screen_support"]["2"],[])
        hidden=replace(c.glasses_open_samples[1][10],left_q=0,right_q=0)
        self.assertEqual(p.eye_ratios(hidden,glasses_state="on"),[])
        self.assertTrue(p.eye_ratios(c.monitor_samples[1][10],glasses_state="off"))

    def test_manual_override_wins_over_auto_visual_result(self):
        c=glasses_session(1)
        e=Engine(c.build())
        e.glasses_mode="Off"
        o=replace(c.glasses_open_samples[0][0],t=1,seq=1,eyewear=descriptor(.68))
        d=e.update(o,1,0)
        self.assertEqual(d.glasses_state,"off")
        self.assertIsNotNone(d.eye)

    def test_activity_can_delay_glasses_unknown_but_never_fabricates_open_eyes(self):
        c=glasses_session(1)
        p=c.build()
        quiet=Engine(p); quiet.glasses_mode="On"
        active=Engine(p); active.glasses_mode="On"
        for i in range(30):
            t=i*.1
            base=c.glasses_open_samples[0][0]
            lost=replace(base,t=t,seq=i,left_q=0,right_q=0,
                         body_activity=None,hand_activity=None)
            moving=replace(lost,body_activity=.08,hand_activity=.12)
            dq=quiet.update(lost,t,100)
            da=active.update(moving,t,100)
        self.assertTrue(dq.alarm)
        self.assertFalse(da.alarm)
        self.assertIsNone(da.eye)
        self.assertTrue(da.activity)

    def test_measurable_closed_eyes_still_alarm_despite_hand_motion(self):
        c=glasses_session(1)
        e=Engine(c.build())
        e.glasses_mode="On"
        for i in range(25):
            src=c.glasses_closed_samples[0][i % len(c.glasses_closed_samples[0])]
            o=replace(src,t=(i+1)*.1,seq=i,hand_activity=.2)
            d=e.update(o,o.t,0)
        self.assertTrue(d.alarm)
        self.assertIn("closure",d.reasons[0].lower())


@unittest.skipUnless(os.environ.get("WAKEGUARD_GUI_TESTS")=="1" or os.environ.get("DISPLAY"),
                     "Actual Tk desktop required")
class GlassesGUITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{"WAKEGUARD_DATA_DIR":self.tmp.name})
        self.env.start()
        self.root=tk.Tk()
        self.app=App(self.root,demo=True,testing=True)
    def tearDown(self):
        self.app.quit()
        self.env.stop()
        self.tmp.cleanup()
    def test_auto_on_off_switch_and_glasses_setup_checkbox_exist(self):
        self.assertEqual(self.app.glasses_mode_var.get(),"Auto")
        self.assertEqual(tuple(self.app.view.glasses_combo.cget("values")),("Auto","On","Off"))
        self.app.glasses_setup_var.set(True)
        self.app.save_glasses_preferences()
        self.assertTrue(self.app.settings["glasses_setup"])
    def test_branding_copy_stays_locked(self):
        self.assertEqual(self.app.view.heading.cget("text"),"Stay Alert")
        self.assertEqual(self.app.view.subtitle.cget("text"),"Look awake, keep your KPI")


if __name__=="__main__":
    unittest.main()
