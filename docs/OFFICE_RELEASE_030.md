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

Local Linux QA: full suite on a private Python 3.12 environment and an isolated virtual Tk display; actual setup, capture and Monitor 2 retry windows inspected at 944×668. Windows CI evidence is recorded below. No physical camera, glasses recognition, microphone, phone delivery or display-brightness behavior is claimed by these checks.

### Final 0.5.1 verification — 28 September 2026 UTC

Tested application revision: `1082a89451eb73a3fbd7983c4304552ac6cea58c`.

- [Windows verification](https://github.com/raihanulrahul/wakeguard/actions/runs/36465211983): success. All **247 tests passed**, with no skips (42.627 seconds). Vision dependency check and MediaPipe blank-image inference passed. The separate phone environment passed dependency/import checks without Apple login or sound. Windows PowerShell parsing and silent speech synthesis passed.
- [Office package and isolation](https://github.com/raihanulrahul/wakeguard/actions/runs/36465211986): success. Private CPython 3.12.10 installation in a path with spaces and repeat package update passed. All **247 tests passed** after install (39.020 seconds), then again after update (38.452 seconds). Default Python, PATH and unrelated environment checks passed; unmanaged folders, edited source and running-instance protections passed.
- The actual pythonw launcher opened and closed cleanly. Windows screenshots of setup, live/alerts, Monitor 2 repair and active capture were inspected. The final 944×668 calibration layout keeps primary actions, progress, the checklist retry control and multiple capture rows visible. A regression test checks that minimum usable checklist space remains.
- New synthetic coverage includes complete three-monitor/glasses collection with an injected Monitor 2 failure and targeted retry, immediate pair validation, failed replacements retaining prior samples, late glasses addition, local draft round trips, Stop/Quit/relaunch/resume, camera mismatch refusal, and saving failures without recapture.

The release documentation follows these checks; no application, dependency or installer files changed after the tested revision. Physical glasses/glare/tracking/monitor behavior still requires the office test. Version 0.5.0 did not persist unfinished capture samples, so an unfinished 0.5.0 session cannot be carried across the update.

## 0.5.2 Apple verification recovery

The 2.6.5 Apple client could request a verification code and then fail inside login before WakeGuard received its pending-verification state. Upgrade the isolated phone environment to pyicloud 2.7.0, with its required rich import explicitly pinned. Keep the API object before authenticating and defer Find My device discovery until verification succeeds.

The phone panel now contains persistent six-digit code entry, Verify and Cancel controls, and automatically scrolls into view when Apple requests verification. Rejected codes retain the session for bounded retries. Phone failures retain their operation stage, exception/cause types and HTTP status where available in both the panel and saved event log. Exception text, URLs, response bodies, passwords, codes and cookies are excluded from diagnostics. Test sound and heard confirmation remain separate, with exact device selection and the existing rate limit.

Local offline checks: 24 phone adapter/service/privacy tests and 7 real-library synthetic HTTP integration tests passed. Integration covers missing token, unusable pre-verification token, incomplete account metadata, wrong credentials, rejected-code retry, and worker-to-panel state propagation. Network socket connections are prohibited by the integration tests. Windows CI additionally exercises inline entry at 944×668, windowless screenshots, private dependency migration from 2.6.5, package folder/lock/edit protections, PowerShell parsing and the full regression suite.

Release gate: Windows verification and screenshot inspection must pass before main is updated. No real Apple account sign-in or physical phone sound has been performed by these tests; the user must deliberately connect, select their iPhone, send a test and confirm hearing it after updating. Existing local calibration files are preserved.
