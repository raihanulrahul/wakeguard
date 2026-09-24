# WakeGuard 0.2 — desktop testing build

A local Windows desk-alert assistant. Calibrated eyelid measurements, head/neck pose, recline geometry, occupancy evidence and elapsed time drive a visible concern meter and independent screen/iPhone Find My alert channels.

**This is a testable prototype, not a validated sleep detector, medical device, or guarantee an alarm will wake someone. Do not use it to justify driving, machinery operation or working through dangerous sedation/sleepiness.** Cameras can miss events. Find My can be delayed/unavailable. A screen alone is not a reliable alert with eyes closed.

## Upgrade and launch

```powershell
cd E:\Codes\mvsa_day1
git status
# Continue only with a clean working tree:
git pull --ff-only origin main
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup-WakeGuard.ps1
.\Start-WakeGuard.cmd
```

Preserve/review uncommitted edits first. Never force-reset or delete the old locked `.venv`. Setup locates Python 3.12 x64 without the `py` launcher; alternatively pass `-Python312 "C:\path\to\python.exe"`. It creates **`.venv_wakeguard`** for vision/UI and **`.venv_phone`** for the incompatible phone stack. Old `.venv`/`.venv312` remain untouched. Initial package installation requires internet. Setup runs dependency checks, blank-image vision inference and regression tests; it does not authenticate to Apple, capture the webcam or trigger phone sounds.

`mvsa_app.py` remains the compatibility entry. Actual modules are under `wakeguard/`. The old `mvsa_config.json` is no longer read. Runtime settings and version-2 calibration live in `%LOCALAPPDATA%\WakeGuard`, not in Git. Do not copy source into a virtual environment.

## First session

1. **Preview.** Select camera index/backend. Try `dshow` or `msmf` if `auto` fails. Aim the camera so it can see your normal main-monitor pose, neck-down pose and full recline. Do not stare into the webcam unless that is natural. Keep other people's faces out of frame.
2. **Test speech.** Select an audible Windows playback device and confirm you heard the test. Speech is for setup only; PC audio is not used during monitoring. Optional voice recognition uses an installed English Windows recognizer, locally. SPACE/R/B remain available when voice is unavailable.
3. **Calibrate.** Each stage announces itself and waits for SPACE or **“WakeGuard ready”**. A spoken countdown precedes capture. Capture ends automatically; speech tells you to open your eyes. Accept with SPACE/“WakeGuard next”, repeat with R/“WakeGuard repeat”, or go back with B/“WakeGuard back”. **No reading or mouse feedback is required with half-closed eyes.** Keep eyes open until “Begin”. Closed captures are three seconds and failed samples do not extend them. Escape/“WakeGuard stop” aborts.
4. **Verify setup.** Four independent short checks: normal main-monitor pose, neck down, full recline, return upright. Changed placement or reversed geometry should fail visibly before monitoring. This is not clinical validation.
5. **Connect phone.** Enter credentials in the masked local dialog, complete 2FA, explicitly select the exact iPhone, send a sound test, then press **I heard the test** after hearing it. No first-device fallback; a request-sent response alone does not arm the phone.
6. Select **Normal / High Alert / Super Alert**, then **START**. Without a connected/tested phone, the app asks for explicit permission for **screen-only test mode**.

After Stop/relaunch, Preview and Verify are required again. Full calibration is reusable if valid. Reconnect and test the phone when its worker was stopped. Find My has a 130-second minimum interval, including tests. Do not spam the test button.

## Controls

| Control | Action |
|---|---|
| SPACE / Esc / Ctrl+Shift+A | Acknowledge an alert |
| Ctrl+Alt+S | Stop everything |
| Ctrl+Shift+Q | Quit immediately |
| R / B during calibration review | Repeat / previous stage |
| Choose stage | Repeat a specific labelled calibration sample |
| Leaving seat | Brief departure grace; resumes when still visible or upon return |

Every alert has steady ACK, STOP EVERYTHING and QUIT buttons. The close button confirms quit instead of trapping you. One borderless overlay is created per monitor, with text on only one primary screen. Default is steady bright; optional slow pulsing changes background once a second. There is no rapid red/white strobe. Use steady mode when flashing is uncomfortable or unsuitable.

Stop releases owned camera, speech, microphone and phone workers and destroys alerts. It does not kill unrelated Python processes or VS Code. A Find My sound already accepted by Apple cannot be recalled; dismiss it on the phone.

## Detection and modes

Normal allows awake recline and uses it only as contributing evidence. High Alert shortens evidence persistence and disables learning. Super Alert also alarms on calibrated recline after a short 0.35-second debounce. Neck pitch is a separate measurement, not automatically chair tilt.

The concern meter is a **heuristic 0–100 accumulation, not a probability of sleep**. Observable sustained eye closure alarms independently of keyboard/mouse activity. Fresh, measurable open eyes for three seconds clear an alert, except while Super Alert recline persists. Manual acknowledgement does not erase hard-condition timers or create a long blind cooldown; continuing trouble can re-alert after one second.

Missing face is **not** AWAY. Tracking loss/camera failure produces uncertainty alerts. Automatic AWAY requires no detected face/body plus a stable match to the calibrated coarse empty-scene descriptor for three seconds. Automatic AWAY is disabled if occupied and empty scenes cannot be separated. This is still camera-based evidence, not a physical seat sensor.

## Calibration and adaptation

Fifteen labelled stages cover normal main-monitor work, other monitors, left/right body angles, reading, neck down/up, full recline, upright/reclined half-closed eyes, closed eyes at main/reclined/left/right angles, and empty chair. About two minutes of samples plus prompts and confirmations are collected. Do not attempt calibration while unable to remain safely awake.

Only sufficiently observable, fresh frames count. Quality gates require adequate sample coverage, distinct open/closed and half-closed states, opposite labelled neck directions, and separable upright/recline geometry. Bad or reversed samples are rejected, not silently swapped. Prior records are backed up before an accepted profile replaces them.

Eye references are viewpoint-dependent and side-specific. An occluded eye is excluded; a clearly closed visible eye is not averaged away by the other eye. Unresolvable reclined eyes are marked unknown, not filled with generic thresholds. Sometimes the only workable fix is physically re-aiming the camera.

Half-closed samples set bounded personalized early-warning limits. Continuous adaptation is restricted to Normal mode, clearly open eyes, recent interaction, low concern, no alarm for two minutes, and 30 continuous qualifying seconds. Session-only eye-reference adjustments are slow, upward-only and capped at 5%. Closed-eye, neck and chair anchors do not drift automatically. Camera/resolution changes and substantial lighting changes request rechecking; not every possible camera movement can be automatically identified.

## Find My integration

The main app does not import `pyicloud`. `phone_alarm_findmy.py` runs in the separate phone environment and communicates over private subprocess pipes. Network/authentication never runs in the Tk thread. Timeouts, dead workers and expired authentication revoke readiness visibly. Only Play Sound is exposed—no erase or lost-mode commands.

Find My is **not a cellular call**. API acceptance does not prove delivery, audibility, earbud routing or awakening. Authentication/service behavior may change. Complete Apple's account/terms prompts yourself; WakeGuard does not auto-accept terms. Additional unsupported authentication may require another integration. The upstream library may retrieve location/device metadata while listing devices; WakeGuard does not display, save or log locations.

```powershell
# Optional standalone manual test; asks before sending sound:
.\.venv_phone\Scripts\python.exe .\phone_alarm_findmy.py --interactive
```

Passwords are not put in command lines, logs, Git or runtime configuration. The authenticated library retains credentials in worker memory; session cookies remain in private app data. Protect that directory like browser session data. Never upload it to GitHub or chat.

## Privacy and tests

No webcam video, screenshots or microphone audio are recorded. Preview images stay in local memory/pipes. Calibration stores numeric feature summaries and a coarse 6×4 grayscale scene descriptor, not full frames. Daily event CSVs, settings and profiles are outside the repository.

```powershell
.\.venv_wakeguard\Scripts\python.exe -m unittest discover -s tests -v
.\Start-WakeGuard.cmd --demo
```

GUI tests open real alert windows; enable only in a suitable setting:

```powershell
$env:WAKEGUARD_GUI_TESTS='1'
.\.venv_wakeguard\Scripts\python.exe -m unittest discover -s tests -v
Remove-Item Env:WAKEGUARD_GUI_TESTS
```

The demo uses synthetic observations, not your webcam. `docs/QA_REPORT.md` separates actual checks from required hardware acceptance. `AGENTS.md` gives Codex the working instructions so routine fixes can stay in VS Code. Passing automated tests does not establish a real-world false-negative rate.

## Primary implementation references

- https://pypi.org/project/mediapipe/0.10.21/
- https://pypi.org/project/jaxlib/0.4.38/
- https://pypi.org/project/pyicloud/2.6.5/
- https://github.com/timlaing/pyicloud/tree/59e43fc26005f20cc5ce2b5520b9484d269af404
- https://learn.microsoft.com/en-us/dotnet/api/system.speech.synthesis.speechsynthesizer
- https://learn.microsoft.com/en-us/dotnet/api/system.speech.recognition.speechrecognitionengine
- https://support.apple.com/guide/icloud/play-a-sound-on-a-device-mmfc0f19b5/icloud
