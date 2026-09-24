import sys
import time
import unittest
from wakeguard.runtime import Channel, Speech, stop_process


class RuntimeTests(unittest.TestCase):
    def test_channel_json_roundtrip(self):
        c=Channel()
        try:
            c.start([sys.executable,"-u","-c","import sys,json; print(json.dumps({'event':'ready'}),flush=True); print(sys.stdin.readline(),flush=True)"])
            c.send({"cmd":"test"})
            deadline=time.monotonic()+3;items=[]
            while time.monotonic()<deadline:
                items+=c.drain()
                if len(items)>=2:break
                time.sleep(.02)
            self.assertEqual(items[0]["event"],"ready");self.assertEqual(items[1]["cmd"],"test")
        finally:c.stop()
    def test_hung_owned_worker_terminates(self):
        c=Channel();c.start([sys.executable,"-c","import time; time.sleep(999)"])
        proc=c.process;start=time.monotonic();c.stop()
        self.assertIsNotNone(proc.poll());self.assertLess(time.monotonic()-start,3)
    def test_stop_idempotent(self):
        c=Channel();c.stop();c.stop();self.assertFalse(c.alive)
    def test_speech_completion(self):
        s=Speech(demo=True);token=s.say("test");self.assertEqual(s.poll(),(token,True));self.assertIsNone(s.poll())
    def test_stopped_speech_no_stale_completion(self):
        s=Speech(demo=True);s.say("old");s.stop();self.assertIsNone(s.poll())
    def test_replaced_speech_has_new_token(self):
        s=Speech(demo=True);a=s.say("old");b=s.say("new");self.assertGreater(b,a);self.assertEqual(s.poll()[0],b)

if __name__=="__main__":unittest.main()
