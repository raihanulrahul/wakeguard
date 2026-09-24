import tempfile
import unittest
import os
from unittest.mock import patch
from wakeguard.phone import PhoneBackend
from phone_alarm_findmy import FindMyService


class FakeChannel:
    def __init__(self):self.alive=True;self.events=[];self.sent=[]
    def drain(self):r=self.events;self.events=[];return r
    def send(self,data):self.sent.append(data)
    def stop(self):self.alive=False


class PhoneTests(unittest.TestCase):
    def setUp(self):
        self.now=1000.;self.channel=FakeChannel();self.p=PhoneBackend(self.channel,lambda:self.now)
        self.p.ready=self.p.heard_test=self.p.enabled=True
    def test_singleflight_and_reserved_rate_limit(self):
        self.assertTrue(self.p.trigger());self.assertFalse(self.p.trigger())
        self.assertEqual(len(self.channel.sent),1)
        self.channel.events=[{"event":"sound_sent"}];self.p.poll();self.assertFalse(self.p.trigger())
        self.now+=131;self.assertTrue(self.p.trigger())
    def test_disabled_phone_never_silent_autosend(self):
        self.p.enabled=False;self.assertFalse(self.p.trigger())
    def test_request_sent_not_audibility(self):
        self.p.heard_test=False;self.p.enabled=False
        self.assertTrue(self.p.trigger(test=True));self.channel.events=[{"event":"sound_sent"}];self.p.poll()
        self.assertFalse(self.p.heard_test)
        self.p.confirm_heard();self.assertTrue(self.p.enabled)
    def test_cannot_confirm_without_test(self):
        with self.assertRaises(RuntimeError):self.p.confirm_heard()
    def test_timeout_stops_owned_worker(self):
        self.p.trigger();self.now+=46;events=self.p.poll()
        self.assertFalse(self.p.ready);self.assertFalse(self.channel.alive)
        self.assertEqual(events[-1]["event"],"phone_error")
    def test_stop_revokes_phone_ready(self):
        self.p.stop();self.assertFalse(self.p.ready);self.assertFalse(self.p.enabled)
    def test_ack_cancels_pending_not_false_remote_stop(self):
        self.p.trigger();self.p.cancel_pending();self.assertFalse(self.channel.alive)
    def test_backend_error_disables(self):
        self.channel.events=[{"event":"phone_error"}];self.p.poll();self.assertFalse(self.p.enabled)
    def test_worker_death_visible(self):
        self.channel.alive=False;self.assertEqual(self.p.poll()[0]["event"],"phone_error")
    def test_rate_limit_survives_stop(self):
        self.p.trigger();attempt=self.p.last_attempt;self.p.stop();self.assertEqual(self.p.last_attempt,attempt)


class Device:
    data={"id":"exact-id","name":"My phone"}
    sound_available=True
    def __init__(self):self.played=0
    def play_sound(self,subject):self.played+=1


class API:
    requires_2fa=False;requires_2sa=False
    def __init__(self,*args,**kwargs):self.devices=[Device()]
    def validate_2fa_code(self,code):return False
    def trust_session(self):pass


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{"WAKEGUARD_DATA_DIR":self.tmp.name});self.env.start()
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def login(self,factory=API):
        s=FindMyService(factory);r=s.dispatch({"cmd":"login","email":"example","password":"test-only"});return s,r
    def test_no_automatic_device_selection(self):
        s,r=self.login();self.assertIsNone(s.selected);self.assertEqual(r["event"],"devices")
        with self.assertRaises(RuntimeError):s.dispatch({"cmd":"play"})
    def test_unknown_device_rejected(self):
        s,_=self.login()
        with self.assertRaises(ValueError):s.dispatch({"cmd":"select","id":"wrong"})
    def test_exact_device_play(self):
        s,_=self.login();s.dispatch({"cmd":"select","id":"exact-id"})
        self.assertEqual(s.dispatch({"cmd":"play"})["event"],"sound_sent");self.assertEqual(s.selected.played,1)
    def test_invalid_two_factor_never_ready(self):
        class TwoFactor(API):requires_2fa=True
        s,r=self.login(TwoFactor);self.assertEqual(r["event"],"need_2fa")
        self.assertEqual(s.dispatch({"cmd":"otp","code":"wrong"})["event"],"need_2fa")
        self.assertFalse(s.authenticated)
    def test_valid_two_factor_completes(self):
        class GoodCode(API):
            requires_2fa=True
            def validate_2fa_code(self,code):self.requires_2fa=False;return True
        s,_=self.login(GoodCode)
        self.assertEqual(s.dispatch({"cmd":"otp","code":"123456"})["event"],"devices")
        self.assertTrue(s.authenticated)
    def test_otp_attempts_bounded(self):
        class WrongCode(API):requires_2fa=True
        s,_=self.login(WrongCode)
        for _ in range(3):s.dispatch({"cmd":"otp","code":"wrong"})
        with self.assertRaises(RuntimeError):s.dispatch({"cmd":"otp","code":"wrong"})
        self.assertFalse(s.authenticated)
    def test_additional_auth_not_assumed_complete(self):
        class MoreAuth(API):requires_2sa=True
        with self.assertRaises(RuntimeError):self.login(MoreAuth)
    def test_expired_auth_blocks_play(self):
        s,_=self.login();s.dispatch({"cmd":"select","id":"exact-id"});s.api.requires_2fa=True
        with self.assertRaises(RuntimeError):s.dispatch({"cmd":"play"})
    def test_no_destructive_phone_commands(self):
        s,_=self.login()
        for cmd in ("erase","lost","location"):
            with self.assertRaises(ValueError):s.dispatch({"cmd":cmd})

if __name__=="__main__":unittest.main()
