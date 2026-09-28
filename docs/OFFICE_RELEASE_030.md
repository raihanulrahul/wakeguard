# WakeGuard 0.3.0 release verification

Tested application revision: 57aab62ae4c1a3fe7413fbfdf58f60c80f7b4ad7.

Windows workflow: https://github.com/raihanulrahul/wakeguard/actions/runs/36290754630
Job: 108540242649. Result: success.

The complete office package was downloaded from GitHub and installed in a selected folder containing spaces. Private CPython 3.12.10 x64 was used. All 211 tests passed with no skips (17.749 seconds), including 82 Tk GUI tests. During the repeat update test, all 211 passed again (18.138 seconds).

The workflow checked preservation of the existing default Python, PATH and an unrelated environment's package inventory; refusal of nonempty unmanaged folders, running-instance locks and locally edited source; and reuse of the private environments. The actual pythonw launcher opened the demo dashboard and exited cleanly. Its Windows setup, alerts and live-view screenshots were inspected. The initial window now fits the tested 1024 by 768 desktop.

Brightness transaction tests used fake monitor drivers. Native DDC enumeration was read-only and found zero physical controls on the virtual runner. No physical brightness change or restoration was tested. Actual office monitor support must be checked by the user. Camera and voice interaction tests use synthetic observations or recognized commands. No real user camera, microphone, Apple account, delivered phone sound, sleep event or false-negative rate was tested.

Delivered changes: modern guided next-step dashboard; vivid red/white or red/blue fullscreen alerts with one colour change per second; optional steady white; temporary maximum brightness requests for supported monitors with recorded originals and restoration attempts; explicit failure reporting and Restore brightness; selectable-folder private installer; desktop shortcut and launch without a persistent console; protected package updates.

See README.md for use, installation, controls and limitations. New office installations must use a dedicated empty writable folder. Existing Git checkouts use a clean fast-forward pull rather than the package installer. Each desk needs its own calibration and phone test. Company software/network/camera restrictions still apply.

Installer SHA-256:
55d450303aff3c8129f018cbd585aa8c5cbe914fa467cff73291084f65195594

This report follows the tested revision without changing application or installer code.


## 0.5.1 calibration recovery and progress

The glasses/screen choices and calibration instructions/actions are now in the fixed top card. Per-monitor open/closed pairs are collected consecutively and validated immediately. The checklist identifies every actual capture and its saved/retry/limited state. Targeted retries skip completed captures. Failed replacement takes preserve the prior successful sample. Local numeric drafts support Stop/Quit/relaunch/resume, with camera identity checks and an explicit unchanged-placement confirmation. Late glasses enrollment appends references without discarding base captures. Final disk-write failures offer saving again without recapture.

Local Linux QA: full suite on a private Python 3.12 environment and an isolated virtual Tk display; actual setup, capture and Monitor 2 retry windows inspected at 944×668. Windows CI evidence is recorded below after the candidate passes. No physical camera, glasses recognition, microphone, phone delivery or display-brightness behavior is claimed by these checks.
