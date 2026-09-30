"""CI-only real pythonw launcher check; synthetic UI, no hardware/account use."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys


def child(repository: Path, output: Path) -> None:
    import runpy
    output.mkdir(parents=True, exist_ok=True)
    os.environ['WAKEGUARD_DATA_DIR'] = str(output / 'private-demo-data')
    sys.path.insert(0, str(repository))
    from wakeguard.app import App
    from wakeguard import __version__
    from wakeguard.runtime import worker_python
    from PIL import ImageGrab
    original = App.__init__

    def initialize(self, *args, **kwargs):
        original(self, *args, **kwargs)
        def capture_and_close():
            def snapshot(name):
                self.view.render()
                self.root.update()
                x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
                image = ImageGrab.grab(bbox=(x, y, x + self.root.winfo_width(), y + self.root.winfo_height()))
                image.save(output / ('wakeguard-' + name + '.png'))
            try:
                for page in ('setup', 'alerts', 'live'):
                    self.view.select(page)
                    snapshot(page)
                # Real desktop widgets with synthetic measurements, including the
                # user's failed-monitor recovery path at a narrow laptop size.
                sys.path.insert(0, str(repository / 'tests'))
                from test_glasses_natural_050 import natural_session
                self.root.geometry('944x668')
                self.view.select('setup')
                snapshot('setup-small')
                from test_phone import FakeChannel
                self.phone.channel = FakeChannel()
                self.phone.channel.events = [{"event": "need_2fa", "message": "Enter the six-digit code from Apple below. Keep this connection open."}]
                for event in self.phone.poll():
                    self._phone_event(event)
                snapshot('phone-code')
                self.phone.channel.events = [{"event": "phone_error", "message": "Phone sign-in failed (ConnectionError). Could not reach Apple securely. Check the network and reconnect."}]
                for event in self.phone.poll():
                    self._phone_event(event)
                snapshot('phone-error')
                self.view.select('setup')
                self.audio_confirmed = True
                self.state = 'CALIBRATING'
                self.cal = natural_session(2)
                self.cal.guided_pairs = True
                self.cal.closed_monitor_samples[1] = self.cal.monitor_samples[1]
                self._finish_calibration()
                snapshot('monitor-2-retry')
                self.repeat_capture('closed_main', 1)
                self._cancel_speech()
                self.cal_phase = 'PROMPT'
                self._capture_begin()
                snapshot('capture-progress')
                (output / 'launcher-receipt.json').write_text(json.dumps({
                    'executable': sys.executable, 'worker_executable': worker_python(),
                    'version': __version__, 'real_gui': True, 'demo_only': True
                }, indent=2), encoding='utf-8')
            finally:
                self.quit()
        self.root.after(750, capture_and_close)
    App.__init__ = initialize
    sys.argv = [str(repository / 'wakeguard_launcher.pyw'), '--demo']
    runpy.run_path(str(repository / 'wakeguard_launcher.pyw'), run_name='__main__')


def main():
    child_mode = '--child' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--child']
    if len(args) != 2:
        raise SystemExit('Usage: smoke_windowless.py REPOSITORY OUTPUT')
    repository, output = (Path(a).resolve() for a in args)
    if child_mode:
        child(repository, output)
        return
    pythonw = Path(sys.executable).with_name('pythonw.exe') if os.name == 'nt' else Path(sys.executable)
    if not pythonw.exists():
        raise SystemExit('No windowless interpreter beside the test Python')
    subprocess.run([str(pythonw), '-E', '-s', '-B', str(Path(__file__).resolve()), '--child',
                    str(repository), str(output)], timeout=30, check=True)
    receipt = json.loads((output / 'launcher-receipt.json').read_text(encoding='utf-8'))
    if os.name == 'nt' and (not receipt['executable'].lower().endswith('pythonw.exe')
                           or not receipt['worker_executable'].lower().endswith('python.exe')):
        raise SystemExit('Windowless UI / console-worker interpreter routing is wrong')
    print('PASS: actual windowless launcher, demo dashboard, owned instance shutdown and explicit worker interpreter.')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
