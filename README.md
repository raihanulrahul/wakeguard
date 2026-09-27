# WakeGuard 0.2.2 — desktop testing build

A local Windows desk-alert assistant. Calibrated eyelid measurements, head/neck pose, recline geometry, occupancy evidence and elapsed time drive a visible concern meter and independent screen/iPhone Find My alert channels.

**This is a testable prototype, not a validated sleep detector, medical device, or guarantee an alarm will wake someone. Do not use it to justify driving, machinery operation or working through dangerous sedation/sleepiness.** Cameras can miss events. Find My can be delayed/unavailable. A screen alone is not a reliable alert with eyes closed.

## Upgrade an already installed copy

Quit WakeGuard first. Preserve/review local edits; never force-reset the repository.

```powershell
cd D:\Codes\wakeguard
git status
# Continue only with a clean working tree:
git pull --ff-only origin main
.\Start-WakeGuard.cmd
```

**The 0.2.1 to 0.2.2 update is source-only: no setup script, pip command or Python installer is needed.** It adds per-screen calibration, diagnostic rejection reasons and interruptible setup speech. Read `docs/CALIBRATION_USABILITY_FIX.md` for the changes, actual Windows QA and hardware limitations.

## First installation on another PC

Clone the repository into its own folder, then run the private setup there:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup-WakeGuard-Private.ps1
.\Start-WakeGuard.cmd
```

This supplies an app-private Python 3.12.10 x64 under `.runtime`, with `.venv_wakeguard` for vision/UI and `.venv_phone` for the incompatible phone stack. It does not request changes to existing system Python installations, PATH, launcher registrations or file associations. It checks relevant before/after values and refuses incompatible pre-existing application environments. No old environment is automatically deleted. See `docs/PRIVATE_SETUP.md` for exact scope and limitations.

Install separately on each PC; do not copy populated virtual environments. Initial package installation needs internet. Private setup performs dependency checks and regression tests but does not authenticate to Apple or open the actual camera. For future dependency changes use the private setup again, not the old generic setup alone. Ordinary launches require only double-clicking `Start-WakeGuard.cmd`; no activation, typed command or VS Code is needed. Keep its console minimized rather than closing it while the app runs.

`mvsa_app.py` is the compatibility entry. Actual modules are under `wakeguard/`. The old `mvsa_config.json` is not read. Settings, calibration and logs live in `%LOCALAPPDATA%\WakeGuard`, outside Git. Keep `.runtime` in place: the application environments depend on it.

## First session

1. **Screens used for work.** Choose 1, 2 or 3. Count screens you actually look at while working. Main means your normal work monitor, not necessarily the Windows primary screen or the camera's screen.
2. **Preview.** Select camera index/backend. Try `dshow` or `msmf` if `auto` fails. Check your normal main-monitor pose, other work screens, neck down and full recline. Setup visibility explains missing face/pose/eyes or delayed frames. Do not stare at the webcam unless that is natural. Keep other people's faces out of frame.
3. **Test speech.** Confirm that instructions are audible using your Windows playback device. Speech is for setup only; monitoring does not play PC alarm audio. Optional voice uses an installed English Windows recognizer locally. Enable it before calibration; keyboard/buttons remain the fallback.
4. **Calibrate.** There are 15 labelled stages. Step 2 checks each selected screen separately: read normally on just the named screen, not a continuous sweep. SPACE can interrupt a long instruction and go to the short state label/countdown. R/Repeat retries, B/Previous goes back, including during speech or capture. Only an unfinished take is discarded; accepted stages remain. Closed-eye captures last 3 seconds; half-eye captures 5 seconds; neither is extended. Eyes-open captures can wait a bounded extra interval for usable coverage. Capture finishes automatically and the result is shown/spoken. SPACE accepts a good sample; it cannot bypass a failed one. Keep eyes open until Begin.
5. **Verify setup.** Separate checks cover normal main-monitor posture, neck down, full recline and return upright. R/B/SPACE also control its narration. This is not clinical validation.
6. **Connect phone.** Enter credentials in the masked local dialog, complete 2FA, explicitly select the exact iPhone, send a sound test, and press **I heard the test** only after hearing it. A request-sent response alone does not arm the phone.
7. Select **Normal / High Alert / Super Alert**, then **START**. Without a connected/tested phone, the app requires explicit permission for **screen-only test mode**.

After Stop/relaunch, Preview and Verify are required again. Full saved calibration is reusable if valid. Restart full calibration after physically moving the camera, rather than mixing old and new geometry. Reconnect/test the phone after its worker was stopped. Find My has a 130-second minimum interval, including tests.

## Controls and interruptible speech

| Control | Action |
|---|---|
| SPACE / Ready-Next button during instruction | Skip long narration and begin the short countdown |
| SPACE during good-sample review | Accept and continue, without waiting for review narration |
| R / Repeat | Interrupt current setup operation; retry with a short reminder |
| B / Previous | Interrupt current setup operation; previous stage/screen |
| SPACE / Esc / Ctrl+Shift+A during an alert | Acknowledge |
| Ctrl+Alt+S / Stop Everything | Stop owned services |
| Ctrl+Shift+Q | Quit immediately |
| Choose stage | Repeat a specific labelled stage |
| Leaving seat | Brief departure grace; resumes if still visible or upon return |

Keep the WakeGuard window selected for setup keyboard controls. Optional voice commands are **WakeGuard ready**, **WakeGuard next**, **WakeGuard repeat**, **WakeGuard back**, **WakeGuard stop**. Recognized commands can interrupt narration; physical recognition depends on your microphone/Windows recognizer. Next accepts review only, not an unfinished capture. SPACE cannot skip a recording, accept failed data, or bypass the brief reopen-eyes safety cue before another closed/half-eye take. Stop/Quit remain immediate.

Ordinary eyes-open stages say "Sample complete." Closed/half-eye stages first say "Open your eyes." The empty-chair stage says "You may return to your chair." No reading/clicking is needed while eyes are half closed. R/B during closed/half capture cancel the partial sample and cue reopening before continuing.

Every alert has steady ACK, STOP EVERYTHING and QUIT buttons. One borderless window covers each monitor; text is on only one primary screen. Default is steady bright. Optional slow pulsing changes background once per second, not a rapid red/white strobe. Stop releases owned camera, speech, microphone and phone workers and removes overlays; it does not kill unrelated Python programs or VS Code. A Find My sound already accepted by Apple cannot be recalled; dismiss it on the phone.

## Detection and calibration safeguards

Normal permits awake recline as supporting evidence, not an automatic offence. High Alert shortens persistence thresholds and disables learning. Super Alert also alarms on calibrated recline after a 0.35-second debounce. Neck pitch is separate from chair recline.

The concern meter is a **heuristic 0–100 accumulation, not a probability of sleep**. Sustained visible eye closure can alarm independently of input activity. Fresh, measurable open eyes for three seconds clear alerts except continuing forbidden Super Alert recline. Acknowledgement does not erase hard-condition timers or create a long blind cooldown.

Missing face is **not** AWAY. Tracking loss/camera failure raises uncertainty. Automatic AWAY requires no detected face/body plus a stable match to the calibrated coarse empty-scene descriptor for three seconds; it is disabled when occupied/empty views cannot be separated. This is camera evidence, not a physical seat sensor.

Each selected work screen must pass its own quality gate. Samples require sufficient fresh frames, usable duration, open/closed/half-eye separation, opposite neck directions and separable upright/recline geometry. Bad/reversed labels are rejected, not swapped or bypassed. Prior profiles are backed up before accepted replacement. Diagnostics expose blocking measurement gates without recording video. A genuinely unobservable camera angle can still require physical repositioning.

Eye references are viewpoint-dependent and side-specific; an occluded eye is excluded, and one clearly closed visible eye is not averaged away by the other. Unresolvable reclined eyes are marked unknown, not filled with generic values. Session-only adaptation is restricted to Normal, clearly open eyes, recent interaction, low concern, no recent alarm and 30 qualifying seconds; it is slow, upward-only and capped at 5%. Closed-eye, neck and chair anchors do not auto-drift. Camera/resolution changes and substantial lighting changes request rechecking; not every physical camera movement is automatically detectable.

## Find My, privacy and limitations

`phone_alarm_findmy.py` runs in the separate phone environment over private subprocess pipes. The main app does not import `pyicloud`. Network/authentication never runs on the Tk interface thread. Timeouts/dead workers/expired authentication revoke readiness visibly. Only Play Sound is exposed, never erase/lost mode. No automatic terms acceptance.

Find My is **not a cellular call**. API acceptance proves neither delivery, audibility, earbud routing nor awakening. It requires internet/authentication and uses unofficial service access that may change. The upstream library may retrieve device/location metadata during listing; WakeGuard does not display/save/log locations.

Passwords are not put in command lines, logs, Git or settings. The worker retains authentication data in memory; private app data may contain session cookies. Protect it like browser-session data and never upload it. No webcam video, screenshots or microphone audio are recorded. Preview images stay in local memory/pipes. Saved calibration contains numeric summaries and a coarse 6-by-4 grayscale scene descriptor, not full video frames.

## Tests

```powershell
.\.venv_wakeguard\Scripts\python.exe -m unittest discover -s tests -v
.\Start-WakeGuard.cmd --demo
```

GUI tests open actual windows; enable them only in a suitable setting:

```powershell
$env:WAKEGUARD_GUI_TESTS='1'
.\.venv_wakeguard\Scripts\python.exe -m unittest discover -s tests -v
Remove-Item Env:WAKEGUARD_GUI_TESTS
```

The demo uses synthetic observations. Latest QA: `docs/CALIBRATION_USABILITY_FIX.md` (175 Windows tests, including 66 Tk GUI tests). Earlier reports: `docs/CALIBRATION_KEYBOARD_FIX.md` and `docs/QA_REPORT.md`. Physical camera/microphone/phone acceptance is still required. Passing automated tests establishes no real-world false-negative rate. `AGENTS.md` gives local coding agents project safeguards.

Primary references: the pinned MediaPipe/Pyicloud packages, upstream timlaing/pyicloud, Microsoft System.Speech documentation, Astral uv Python-install documentation, Python venv documentation and Apple's Find My Play Sound documentation. No paid service is required by this implementation.
