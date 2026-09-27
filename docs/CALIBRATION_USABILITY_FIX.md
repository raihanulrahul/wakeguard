# WakeGuard 0.2.2: per-screen capture and interruptible setup

## Release scope

This update addresses three field reports: step 2 repeatedly rejected too few usable measurements; ordinary eyes-open stages unnecessarily said "Open your eyes"; and long spoken instructions could not be interrupted with keys/buttons/voice.

The step-one keyboard restart was fixed in 0.2.1. The user's subsequent log showed step one accepted with 70 usable frames / 7.0 seconds, then step two rejected 42 frames / 4.1 seconds and 37 frames / 3.6 seconds. The old 12-second step required at least 48 frames, 7.8 usable seconds and 65% frame coverage. Those recordings did not meet its gates. The old log did NOT identify whether the physical cause was head-pose failure, eye size/detail, face loss or delayed data; it would be unjustified to diagnose the user's lighting from that log alone.

## Per-screen capture

The dashboard now has **Screens used for work: 1 / 2 / 3**. Set the number of screens you actually look at while working, not an unused connected screen. Main means your usual work screen, not necessarily the Windows primary display or webcam screen.

There are still 15 labelled stages. Step 2 now contains one separate capture for each selected screen: main work screen, second work screen, and third if selected. The user reads normally at ONE screen for that capture rather than continually sweeping between monitors. It is expected to stay at "Step 2" while its screen counter advances.

Each screen capture has an 8-second nominal duration. If usable coverage has not recovered, it continues up to a hard maximum of 24 seconds. Other eyes-open/empty-chair stages similarly permit bounded recovery time, up to three times their nominal duration and never above 36 seconds. Closed-eye captures remain at 3 seconds and half-closed-eye captures at 5 seconds; neither is extended to chase data.

Each individual screen must still meet the frame-count, 65% coverage and usable-time checks; one observable screen cannot stand in for another. For the 8-second screen sample this is at least 32 usable frames and 5.2 seconds of accepted adjacent-frame intervals. Quality gating is not disabled to make calibration pass. Time spanning rejected or missing frames is not credited. Buffered frames from before Begin and frames after the hard deadline are excluded. A stale or invalid final observation cannot be hidden by earlier good frames.

Preview and capture now explain the first blocking measurement gate: face missing, head geometry unavailable, eyes too small, eye crop outside frame, poor exposure/detail, delayed measurements, or camera failure. Rejection logs aggregate the reasons and include usable/total frames and accepted duration. These are measurement diagnostics, not proof of a medical condition or a complete physical diagnosis.

If a work-screen angle is genuinely unobservable, the user may still need to re-aim the camera. **After moving the camera, restart the whole calibration** so earlier reference positions are not mixed with the new geometry. Do not label an invisible work position as safe. Final profile creation also checks that each accepted screen view has usable matching eye references.

## Interruptible instructions

All of these use the same setup controller:

| Input | Effect during speech/setup |
|---|---|
| SPACE / Ready-Next button | Skip a long instruction to the short state label/countdown; accept an already good sample during review narration. |
| R / Repeat button | Stop current narration/countdown/capture and prepare the same stage with a short reminder. |
| B / Previous button | Stop current narration/countdown/capture and prepare the preceding stage or screen with a short reminder. |
| WakeGuard ready / next / repeat / back | Corresponding actions when optional voice recognition produces a command. |
| Esc / WakeGuard stop / Stop Everything | Abort setup. |

Setup keyboard input requires the WakeGuard window to remain selected; looking into the camera is not required. The app-scoped keyboard fix from 0.2.1 remains in place. Long instructions need not finish, and R/B no longer replay the full narration on familiar stages. SPACE does not skip an active recording or accept a failed sample.

Interrupting a capture discards that incomplete take and preserves already accepted stages. Cancelling speech invalidates its pending callback, so an old countdown cannot subsequently begin recording. A short state label and countdown are retained before each take. If eyes may have been closed or half closed, a brief reopen-eyes cue precedes the next take and cannot be bypassed by SPACE. Stop/Quit still cancel immediately.

Optional voice is no longer blanket-muted while narration is playing. It requires the full prefixed command, filters stale command events, and does not navigate setup behind a secondary dialog. Spoken instructions do not themselves contain the recognized full command phrases. Actual recognition over the speaker output still depends on the installed recognizer/microphone; headphones may help. The keyboard/button fallback remains available. No microphone audio is saved or sent to an online recognition service.

## Context-appropriate completion

- Eyes-open stage: "Sample complete" or the specific repeat reason, without an unnecessary reopen-eyes instruction.
- Closed/half-closed stage: "Open your eyes," then the skippable sample-review narration.
- Empty-chair stage: "You may return to your chair," then the result.

The brief reopen cue is a separate operation so an impatient Next press cannot truncate it and start another eyes-closed task. Audio failure prevents a new capture until Test speech is confirmed again.

## Actual verification

Application/test revision: `097292855779028eb6170b8eb53908665e55416a`.

Windows Actions run: https://github.com/raihanulrahul/wakeguard/actions/runs/36287809994
Job: `108531808331`, completed successfully on 27 September 2026.

**175 tests passed in 22.946 seconds, no skips**, on Windows Server 2025 / CPython 3.12.10 x64. This includes **66 real Tk GUI tests** (19 existing GUI tests, 18 keyboard regressions, 29 speech/setup interaction tests). Fifty new tests cover bounded capture recovery, every selected screen, stale/deadline rejection, diagnostic categories, stage-appropriate speech, real key/button interruption, injected recognized voice commands, discarded partial takes, blocked quality bypass, audio failure and the full three-screen calibration flow using synthetic observations.

The complete workflow also passed clean vision dependency installation and pip check, actual MediaPipe FaceMesh/Pose blank-image inference, separate phone-environment installation/check/import, PowerShell parsing including the changed voice script, and native System.Speech synthesis to a null output.

Additional local checks: 175 tests passed in 6.789 seconds on Linux/Python 3.13.5 with actual Tk windows under Xvfb; Python compilation and git diff whitespace checks passed. A dashboard screenshot was inspected for the new screen selector and quality-progress display.

**Not tested:** the user's actual camera positions, audible speaker output, physical microphone recognition during narration, Apple credentials, delivered phone sound, real sleep or false-negative rate. Voice tests inject recognized commands rather than pretending a microphone was used. Passing the tests verifies the software paths, not guaranteed physical detection.

Documentation changes follow the tested revision; they do not alter its application code. See `CALIBRATION_KEYBOARD_FIX.md` for the prior 0.2.1 repair and `QA_REPORT.md` for the original 0.2 testing history.

## Update an already installed private-runtime copy

Quit the old WakeGuard instance. In the exact repository folder, check for local edits, pull main with `--ff-only`, and relaunch `Start-WakeGuard.cmd`. The title must show **WakeGuard 0.2.2**.

**No Python installation, setup script, pip operation, PATH change, environment deletion, or new clone is required for this source-only update.** The dependency files, private installer, detection engine and phone backend are unchanged. Existing saved calibration is not automatically deleted. An incomplete live calibration session must be started again after restarting the app.

First test: set Screens used for work correctly, Preview each normal working direction, Test speech once, and Calibrate. Try R/B during an instruction, then SPACE to proceed without waiting for the long text. At step two hold only the screen currently named by the prompt. If a screen still fails, use the new detailed rejection rather than repeating indefinitely. Recalibrate from the beginning after a physical camera move.
