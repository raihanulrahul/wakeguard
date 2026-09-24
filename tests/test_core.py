import copy
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from wakeguard.model import Observation, Profile, angle_delta, atomic_json
from wakeguard.engine import Engine, MODES
from wakeguard.calibration import CalibrationSession, CalibrationError, STAGES
from wakeguard.demo import demo_profile, observation


class Harness:
    def __init__(self, mode="Normal"):
        self.engine = Engine(demo_profile(), mode)
        self.t = 0.0
        self.seq = 0
    def tick(self, scenario="Awake", duration=1, input_age=0, edit=None):
        result = None
        for _ in range(round(duration/.1)):
            self.t += .1
            self.seq += 1
            o = observation(self.t, self.seq, scenario)
            if edit:
                o = edit(o)
            result = self.engine.update(o, self.t, input_age)
        return result


class EngineTests(unittest.TestCase):
    def test_awake_never_accumulates(self):
        h=Harness(); r=h.tick(duration=120, input_age=500)
        self.assertFalse(r.alarm); self.assertEqual(r.battery, 0)
    def test_closed_upright_independent_of_mouse(self):
        h=Harness(); r=h.tick("Eyes closed", 2, input_age=0)
        self.assertTrue(r.alarm); self.assertIn("closure", r.reasons[0])
    def test_blink_not_alarm(self):
        h=Harness()
        for _ in range(20):
            self.assertFalse(h.tick("Eyes closed", .2).alarm)
            self.assertFalse(h.tick("Awake", .5).alarm)
    def test_modes_closure_timings(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                h=Harness(mode); self.assertTrue(h.tick("Eyes closed", MODES[mode].closed_s+.3).alarm)
    def test_half_closed_alone(self):
        h=Harness(); self.assertTrue(h.tick("Half closed", 5).alarm)
    def test_personalized_half_eye_threshold(self):
        h=Harness();h.engine.profile.report["half_thresholds"]={"upright":.78}
        self.assertTrue(h.tick(duration=5,edit=lambda o:replace(o,left=.245,right=.245)).alarm)
    def test_recline_normal_allowed(self):
        h=Harness(); r=h.tick("Reclined awake", 120, input_age=0)
        self.assertFalse(r.alarm); self.assertEqual(r.battery, 0)
    def test_recline_super_forbidden(self):
        h=Harness("Super Alert"); self.assertTrue(h.tick("Reclined awake", .6).alarm)
    def test_super_open_eyes_cannot_cancel_recline(self):
        h=Harness("Super Alert"); self.assertTrue(h.tick("Reclined awake", 12).alarm)
    def test_super_return_upright_clears(self):
        h=Harness("Super Alert"); h.tick("Reclined awake", 1)
        self.assertFalse(h.tick("Awake", 3.3).alarm)
    def test_neck_drop_with_partial_eyes(self):
        h=Harness(); self.assertTrue(h.tick("Neck down", 3).alarm)
    def test_head_down_not_chair_recline(self):
        h=Harness("Super Alert")
        r=h.tick(duration=1, edit=lambda o:replace(o,pitch=20))
        self.assertFalse(r.alarm); self.assertEqual(r.recline, 0)
    def test_occluded_present_is_unknown_not_away(self):
        h=Harness(); r=h.tick("Occluded",4)
        self.assertTrue(r.alarm); self.assertNotEqual(r.status,"AWAY")
    def test_no_face_without_matching_scene_not_away(self):
        h=Harness(); r=h.tick("Occluded",4,edit=lambda o:replace(o,body=False))
        self.assertTrue(r.alarm)
    def test_empty_chair_confirmed_after_dwell(self):
        h=Harness(); self.assertNotEqual(h.tick("Empty chair", 2).status,"AWAY")
        r=h.tick("Empty chair", 2); self.assertEqual(r.status,"AWAY"); self.assertFalse(r.alarm)
    def test_empty_clears_existing_alarm(self):
        h=Harness(); h.tick("Eyes closed",2)
        r=h.tick("Empty chair",3.5); self.assertFalse(r.alarm); self.assertEqual(r.status,"AWAY")
    def test_body_presence_blocks_empty_match(self):
        h=Harness(); r=h.tick("Empty chair",4,edit=lambda o:replace(o,body=True))
        self.assertTrue(r.alarm)
    def test_camera_failure_alarms_not_away(self):
        h=Harness(); r=h.tick("Camera failed",2)
        self.assertTrue(r.alarm); self.assertIn("Camera",r.reasons[0])
    def test_stale_open_frame_cannot_clear_alarm(self):
        h=Harness(); h.tick("Eyes closed",2)
        stale=observation(h.t,999,"Awake")
        for _ in range(45):
            h.t+=.1; r=h.engine.update(stale,h.t,0)
        self.assertTrue(r.alarm)
    def test_three_second_recovery_required(self):
        h=Harness(); h.tick("Eyes closed",2)
        self.assertTrue(h.tick("Awake",2.9).alarm)
        self.assertFalse(h.tick("Awake",.4).alarm)
    def test_recovery_interrupted_by_closed_eyes(self):
        h=Harness(); h.tick("Eyes closed",2); h.tick("Awake",2)
        h.tick("Eyes closed",.2)
        self.assertTrue(h.tick("Awake",2).alarm)
        self.assertFalse(h.tick("Awake",1.2).alarm)
    def test_ack_no_long_blind_cooldown(self):
        h=Harness(); h.tick("Eyes closed",2); h.engine.acknowledge(h.t)
        self.assertFalse(h.tick("Eyes closed",.5).alarm)
        self.assertTrue(h.tick("Eyes closed",.7).alarm)
    def test_one_closed_eye_not_averaged_away(self):
        h=Harness(); self.assertTrue(h.tick(duration=2,edit=lambda o:replace(o,left=.1)).alarm)
    def test_bad_eye_excluded_not_falsely_closed(self):
        h=Harness(); self.assertFalse(h.tick(duration=4,edit=lambda o:replace(o,left=.1,left_q=0)).alarm)
    def test_both_eyes_unobservable_alarm(self):
        h=Harness(); self.assertTrue(h.tick(duration=4,edit=lambda o:replace(o,left_q=0,right_q=0)).alarm)
    def test_view_outside_calibration_unknown(self):
        h=Harness(); self.assertTrue(h.tick(duration=4,edit=lambda o:replace(o,yaw=100)).alarm)
    def test_camera_identity_changed(self):
        h=Harness(); r=h.tick(duration=.2,edit=lambda o:replace(o,camera_key="other"))
        self.assertTrue(r.alarm)
    def test_manual_away_does_not_disable_occupied_chair(self):
        h=Harness(); h.engine.set_away(0)
        r=h.tick("Eyes closed",6); self.assertTrue(r.alarm)
    def test_manual_away_resumes_when_user_returns(self):
        h=Harness(); h.engine.set_away(0); h.tick("Empty chair",1)
        self.assertTrue(h.tick("Eyes closed",2).alarm)
    def test_manual_away_not_hide_camera_failure(self):
        h=Harness(); h.engine.set_away(0)
        self.assertTrue(h.tick("Camera failed",2).alarm)
    def test_learning_high_modes_disabled(self):
        for mode in ["High Alert","Super Alert"]:
            h=Harness(mode); r=h.tick(duration=100,input_age=0,edit=lambda o:replace(o,left=.31,right=.31))
            self.assertFalse(r.learning); self.assertEqual(h.engine.adaptation["left"],0)
    def test_learning_bounded_upward_only(self):
        h=Harness(); h.tick(duration=90,edit=lambda o:replace(o,left=.31,right=.31))
        self.assertGreater(h.engine.adaptation["left"],0)
        self.assertLessEqual(h.engine.adaptation["left"],.05)
        before=h.engine.adaptation["left"]
        h.tick(duration=60,edit=lambda o:replace(o,left=.28,right=.28))
        self.assertEqual(h.engine.adaptation["left"],before)
    def test_no_learning_immediately_after_alarm(self):
        h=Harness(); h.tick("Eyes closed",2); h.tick("Awake",4)
        r=h.tick(duration=60,edit=lambda o:replace(o,left=.31,right=.31))
        self.assertFalse(r.learning); self.assertEqual(h.engine.adaptation["left"],0)
    def test_immutable_original_profile(self):
        h=Harness(); before=copy.deepcopy(h.engine.profile.neutral)
        h.tick(duration=60,edit=lambda o:replace(o,left=.31,right=.31))
        self.assertEqual(h.engine.profile.neutral,before)
    def test_no_autoaway_when_calibration_disables_it(self):
        h=Harness(); h.engine.profile.report["auto_away_enabled"]=False
        self.assertTrue(h.tick("Empty chair",4).alarm)
    def test_light_change_alert(self):
        h=Harness(); r=h.tick(duration=6,edit=lambda o:replace(o,brightness=200))
        self.assertTrue(r.alarm)


class ModelTests(unittest.TestCase):
    def test_circular_angles(self):
        self.assertAlmostEqual(angle_delta(-179,179),2)
    def test_profile_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"p.json"; demo_profile().save(p)
            self.assertEqual(Profile.load(p).camera_key,"DEMO")
    def test_inverted_profile_rejected(self):
        p=demo_profile(); p.open_views[0]["left"]=.05
        with self.assertRaises(ValueError):p.validate()
    def test_nonfinite_observation_sanitized(self):
        o=Observation.from_dict(dict(t=1,left=float("nan"),pitch=float("inf")))
        self.assertIsNone(o.left); self.assertIsNone(o.pitch)
    def test_atomic_invalid_json_preserves_previous(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"p.json"; atomic_json(p,{"good":1})
            with self.assertRaises(ValueError):atomic_json(p,{"bad":float("nan")})
            self.assertIn('"good"',p.read_text())
    def test_neck_direction_learned_not_hardcoded(self):
        p=demo_profile(); p.neck_down["pitch"]=-20;p.neck_up["pitch"]=15
        o=observation(1,1);o.pitch=-20
        self.assertEqual(p.neck(o),1)
        self.assertEqual(p.neck(o,"up"),0)
    def test_recline_opposite_motion_not_convicted(self):
        p=demo_profile();o=observation(1,1);o.area=.17;o.cy=.50
        self.assertEqual(p.recline(o),0)
    def test_failed_pose_is_unknown(self):
        p=demo_profile();o=observation(1,1);o.pitch=None
        self.assertEqual(p.eye_ratios(o),[]);self.assertIsNone(p.recline(o))


def full_calibration():
    session=CalibrationSession()
    seq=0
    for idx,stage in enumerate(STAGES):
        samples=[]
        for i in range(max(20,int(stage.seconds*12))):
            seq+=1
            o=observation(seq*.08,seq)
            noise=.001*math.sin(i)
            o.left+=noise;o.right+=noise
            if stage.key in ("left","closed_left"):o.yaw=5
            if stage.key in ("right","closed_right"):o.yaw=35
            if stage.key=="reading":o.pitch=8
            if stage.key=="neck_down":o.pitch=20
            if stage.key=="neck_up":o.pitch=-15
            if "reclined" in stage.key:
                o.pitch,o.area,o.cy=12,.07,.40
            if stage.eyes=="closed":o.left=o.right=.10+noise
            if stage.eyes=="half":o.left=o.right=.19+noise
            if stage.key=="empty":o.face=o.body=False;o.scene=[.2]*24
            samples.append(o)
        session.samples[stage.key]=samples
    return session


class CalibrationTests(unittest.TestCase):
    def test_complete_profile_passes(self):self.assertTrue(full_calibration().build().report["valid"])
    def test_no_samples_while_waiting(self):
        c=CalibrationSession();c.add(observation(1,1),1);self.assertEqual(c.current,[])
    def test_no_duplicate_frame_counting(self):
        c=CalibrationSession();c.begin(0);o=observation(.1,1)
        for _ in range(10):c.add(o,.1)
        self.assertEqual(len(c.current),1)
    def test_stale_samples_rejected(self):
        c=CalibrationSession();c.begin(0);c.add(observation(0,1),2);self.assertEqual(c.current,[])
    def test_closed_capture_bounded(self):
        c=CalibrationSession();c.index=[s.key for s in STAGES].index("closed_main");c.begin(0)
        self.assertTrue(c.due(3));self.assertFalse(c.due(2.9))
        with self.assertRaises(CalibrationError):c.finish()
        self.assertFalse(c.recording)
    def test_missing_stages_rejected(self):
        c=full_calibration();del c.samples["left"]
        with self.assertRaises(CalibrationError):c.build()
    def test_reversed_labels_rejected(self):
        c=full_calibration()
        for o in c.samples["closed_main"]:o.left=o.right=.35
        with self.assertRaises(CalibrationError):c.build()
    def test_indistinct_recline_rejected(self):
        c=full_calibration()
        for k in ("reclined","closed_reclined","half_reclined"):
            for o in c.samples[k]:o.area=.12;o.cy=.45
        with self.assertRaises(CalibrationError):c.build()
    def test_same_up_down_direction_rejected(self):
        c=full_calibration()
        for o in c.samples["neck_up"]:o.pitch=15
        with self.assertRaises(CalibrationError):c.build()
    def test_half_closed_needs_distinct_sample(self):
        c=full_calibration()
        for o in c.samples["half_upright"]:o.left=o.right=.30
        with self.assertRaises(CalibrationError):c.build()
    def test_angle_change_between_open_closed_rejected(self):
        c=full_calibration()
        for o in c.samples["closed_main"]:o.yaw=100
        with self.assertRaises(CalibrationError):c.build()
    def test_camera_change_during_calibration_rejected(self):
        c=full_calibration();c.samples["left"][0].camera_key="other"
        with self.assertRaises(CalibrationError):c.build()
    def test_no_eye_reclined_is_explicit_unknown(self):
        c=full_calibration()
        for k in ("reclined","half_reclined","closed_reclined"):
            for o in c.samples[k]:o.left_q=o.right_q=0
        p=c.build();self.assertFalse(p.report["reclined_eyes_valid"])
    def test_insufficient_frame_quality_rejected(self):
        c=CalibrationSession();c.begin(0)
        for i in range(50):c.add(replace(observation(i*.1,i),left_q=0,right_q=0),i*.1)
        with self.assertRaises(CalibrationError):c.finish()
    def test_stage_requires_explicit_advance(self):
        c=CalibrationSession();self.assertEqual(c.index,0);c.advance();self.assertEqual(c.index,1)

if __name__=="__main__":unittest.main()
