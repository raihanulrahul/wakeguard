# WakeGuard 0.2.1: calibration keyboard loop repair

## Report and cause

The user reported repeated step-one instructions and consent/audio dialogs after pressing SPACE. The original dashboard registered setup shortcuts using Tk `bind_all`. A focused ttk.Button processed SPACE through its native class binding before that application handler. With Calibrate focused, this could invoke begin_calibration again during READY, PROMPT or REVIEW and recreate the session. A separate low-level keyboard listener could also enqueue the same command for a second dispatch, including across modal dialogs or phase transitions.

This is a UI/input-routing failure, not evidence that the user's posture was wrong. Genuine sample-quality rejection remains possible and is now logged separately.

## Repair

- New app-scoped KeyboardRouter bindtag runs before widget/class bindings on the dashboard and owned alert controls, not on secondary dialogs.
- Setup and alert keys are consumed even when a phase ignores them or a short debounce suppresses an action. SPACE cannot accidentally click the previously focused Calibrate/Test speech/Stop button.
- Key-up is required before another accepted press; holding SPACE cannot accept a later phase automatically.
- Calibration start is idempotent throughout an active setup session. Accepted samples are not discarded by re-clicking Calibrate.
- Modal consent/audio confirmation is guarded against re-entry. Speech testing cannot replace an already pending speech callback.
- Foreground setup input has one owner: Tk. The low-level hook is a fallback for alert acknowledgement and emergency controls, not a duplicate setup controller. Hook command timestamps reject delayed events.
- Countdown sets its phase before starting speech, so a synchronous speech failure retains AUDIO FAILED and never starts capture.
- Status now identifies instruction, ready, countdown, capture, sample accepted, or repeat needed. The event log includes stage number, usable sample count and duration.
- Existing quality thresholds, detection engine, calibration profile schema, dependencies and installers are unchanged.

## Actual verification

Tested code commit: `24b58ccceeb6e526d354772955bafefc447015e4`.

Windows CI run: https://github.com/raihanulrahul/wakeguard/actions/runs/36285941920
Job: `108526616623`.

On Windows Server 2025 / CPython 3.12.10 x64, **125 tests passed in 8.536 seconds, no skips**. These include 37 Tk GUI tests (the previous 19 plus 18 new keyboard/setup regressions). New tests put focus on real buttons and generate key press/release events instead of calling the application action method alone. The full 15-stage keyboard sequence passes using synthetic valid observations. Tests also cover step one to step two, consent shown once, repeat/back preserving accepted samples, held/repeated SPACE, stale/global duplicate inputs, ordinary dialog typing, failed samples, failed countdown speech, and emergency Stop.

The focused-Calibrate and duplicate-input tests were first run against the old code and reproduced failures. The earlier 107-test suite had not covered these focused-widget interactions.

The complete Windows workflow also passed dependency checks, actual FaceMesh/Pose blank-image inference, separate phone-environment import, PowerShell parsing and speech synthesis to null output. No real webcam, microphone, Apple account, audible speech, or phone call was used. This verifies the repaired UI state progression, not the accuracy of the user's physical calibration or sleep detection.

This report was added in a documentation-only child of the tested commit.

## Apply on the user's existing D: installation

Quit the old WakeGuard instance first. Check that the repository is clean, then pull main with `--ff-only` and relaunch `Start-WakeGuard.cmd`.

**No setup script, pip command, Python installer, global PATH change, environment deletion, or fresh clone is required for this update.** It changes application source, its version label, and regression tests only.

The window title should show WakeGuard 0.2.1. Preview, confirm Test speech once, then click Calibrate once. Keep the WakeGuard window selected while using setup keys; do not look into the camera unless that is your normal work posture.

Step one: wait for READY, tap and release SPACE, listen to the countdown, remain in the requested posture for the approximately 10-second capture, then wait for Sample complete / SAMPLE OK. Tap and release SPACE again to reach step two. Extra presses during instruction/countdown/capture do not restart setup. A failed sample explicitly says REPEAT NEEDED and records why; R repeats it rather than bypassing quality checks.
