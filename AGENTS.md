# WakeGuard: local coding-agent instructions

Work inside this repository. Inspect git status/diff and preserve user changes. Never force-push/reset, delete old environments, kill unrelated Python processes, or upload personal calibration/account data. This repository is public.

## Environment

Windows Python 3.12 x64. Vision/UI interpreter: `.venv_wakeguard\Scripts\python.exe`. Phone only: `.venv_phone\Scripts\python.exe`. Setup-WakeGuard.ps1 leaves `.venv`/`.venv312` untouched. Start-WakeGuard.cmd runs the mvsa_app.py compatibility launcher.

Use explicit interpreter paths, not arbitrary PATH python/pip. Never install pyicloud in the vision environment or install a second OpenCV distribution alongside opencv-contrib-python.

## Modules

model.py: observations, calibrated math and private persistence. calibration.py: labelled quality-gated samples. engine.py: deterministic concern state machine. vision_worker.py: isolated camera/FaceMesh/body/preview, unmirrored inference. vision_math.py: head/eye observability. app.py: Tk controller. runtime.py: owned processes, input timestamps and asynchronous TTS. alarms.py: per-monitor screen renderer. phone.py: nonblocking adapter. phone_alarm_findmy.py: separate Apple worker. scripts/voice.ps1: optional offline setup recognition.

## Invariants

No gaze-at-webcam requirement. Neck tilt is not chair recline. Sustained visible eye closure can alarm without corroboration. Camera/eye tracking loss is not AWAY. Fresh open eyes for three seconds clear an alert except continuing Super Alert recline. Stop/Quit must stop calibration, camera, voice, overlays and owned phone work even after exceptions. No camera/network/speech work on the Tk thread. No ten-second blind cooldown. No credential prompts during monitoring alarms.

Test alerts use the same escape behavior as real ones. Controls stay reachable. Native monitor placement must handle negative origins and mixed DPI; text appears on only one screen. No rapid red/white strobes. No PC audio during monitoring. Setup requires confirmed audible speech before eye-closed capture, and capture duration remains bounded on tracking failure. Tactile SPACE/R/B fallback is mandatory; optional voice must not block use.

Calibration: explicit labels, verified sample coverage/separation, last-good backup, no automatic learning of closed/half/tilt anchors. Session adaptation remains bounded and disabled in High/Super Alert. No claims of clinically proven vigilance, zero missed events or guaranteed awakening. Metrics are heuristics, not probabilities.

Phone: free only; exact explicit device selection, heard-test confirmation, single-flight operation, rate limit reserved before request and visible failures. Only Play Sound; never erase/lost mode. No passwords in argv, environment, Git or logs. No automatic terms acceptance. Never promise earbud routing or cancellation of sound already submitted to Apple.

## Verification before commit

1. Inspect diff and staged paths for user changes/secrets.
2. Run vision interpreter `-m pip check` and `scripts\doctor.py`.
3. Run vision interpreter `-m unittest discover -s tests -v`.
4. GUI tests require WAKEGUARD_GUI_TESTS=1 and open actual windows; ask before running those in the office.
5. Phone imports/pip check use phone interpreter only. Never trigger real Apple login/sound without the user's deliberate test action.
6. Run git diff --check. Update docs/QA_REPORT.md with actual results, distinguishing unit/mock/GUI/Windows/hardware verification.

Do not expand into productivity surveillance or infer medical conditions. Do not hide unready phone/calibration behind green status. Where hardware access is needed, organize one short grouped session in VS Code rather than repeated browser relays. Preserve the old prototype in Git history, not as a fallback runtime with unsafe behavior.
