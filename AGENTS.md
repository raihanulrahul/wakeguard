# WakeGuard coding-agent instructions

Inspect status/diff and preserve user edits. This repository is public. Never force-push/reset, delete old environments, kill unrelated Python processes, or upload calibration, cookies, accounts or user images. No medical/zero-missed-sleep claims.

## Private environment and delivery

Windows CPython 3.12 x64. Vision/UI: `.venv_wakeguard\Scripts\python.exe`; phone: `.venv_phone\Scripts\python.exe`. These depend on the app-private `.runtime` interpreter. Use `Setup-WakeGuard-Private.ps1` for setup/dependency changes; do not install system Python or global packages, alter PATH/registry/file associations, install a global uv, or bypass company policies. Do not mix pyicloud with MediaPipe, or multiple cv2 distributions.

`Install-WakeGuard.ps1` is a new-PC folder-selectable package installer; no Git/system Python prerequisite. It refuses existing Git/nonempty-unmanaged folders and preserves managed-source edits during Update. Packaged installs use Update-WakeGuard.cmd. Existing Git checkouts use clean fast-forward pull. No auto-deleting project environments. The source marker and runtimes are ignored by Git.

Start-WakeGuard.cmd and per-user shortcut use explicit pythonw.exe and wakeguard_launcher.pyw, no persistent console. Worker processes MUST use console python.exe with redirected pipes (`runtime.worker_python`), not assume sys.executable is python.exe. InstanceGuard holds one per-user UI mutex and an installer lock. No implicit startup monitoring, camera, microphone or Apple auth.

## Modules

controller.py: preserved 0.2.2 calibration/control flow, including speech interruptions. app.py: desktop facade/alert preferences/brightness lifecycle. dashboard.py: guided view and pure next-step decision. calibration.py/model.py/engine.py: observations, accepted references and concern. vision_worker/math: local camera and measurements. runtime: owned workers/input/TTS. keyboard: private bindtag before Tk button bindings. alarms: per-screen renderer. brightness.py/native/worker: reversible hardware change with journal and heartbeat. phone.py/phone_alarm_findmy.py: separate Apple worker. scripts/voice.ps1: optional offline English grammar.

## Invariants

No requirement to gaze at the webcam; neck tilt != chair recline. Camera/tracking loss != AWAY. Sustained visible eye closure can alarm without corroboration. Fresh open eyes for 3s can clear, except continuing Super Alert recline. No long blind acknowledgement cooldown. Original calibration labels stay immutable; adaptation remains bounded, slow, session-only and disabled in High/Super Alert.

Maintain the 0.2.2 Space/R/B/click/voice interrupt behavior and contextual eye cues. Failed samples cannot be accepted; closed-eye 3s and half-eye 5s captures never extend to chase data. Per-screen quality/coverage cannot be replaced by one good screen. Cancelled callbacks cannot later start capture. Keep window-key handling BEFORE widget class bindings. Do not use bind_all as a substitute; it recreated the step-one loop.

No rapid red/white strobe. Alert palettes are vivid red/white or red/blue at >=1000ms per colour change, or steady white. Each monitor has its own window; one screen has text, stable controls. Brightness is best effort with original read/journal BEFORE write, readback, restore on clear/Stop/Quit/parent EOF, bounded timeout, persistent retry record. Never claim unsupported displays were raised/restored. No gamma tricks, driver installs, power plan or admin changes. All hardware work belongs in a child, not Tk. Own alert illumination must not retrain the baseline or cause perpetual lighting alarms; do not hide eyelid/head/camera warnings.

Stop/Quit stops camera/calibration/speech/microphone/phone/overlays even after faults. Brightness restoration may finish asynchronously for a few seconds. Do not kill other applications. No PC alarm sound during monitoring. No credential prompts inside alerts. Phone has exact selected device, actual heard-test confirmation, single-flight/timeouts/rate limits. Find My is NOT a call, cannot promise earbuds/delivery/waking or remote cancellation. No erase/lost mode, stored plaintext passwords, auto-accepting Apple terms.

## Checks before publish

1. Inspect changed paths for user edits/secrets; use explicit private Python.
2. Vision pip check + scripts/doctor.py (blank inference, not physical camera).
3. Full unittest discover. GUI tests open windows; ask before running on an occupied office desk. They use synthetic observations/recognized-command events and fake brightness, not actual hardware writes.
4. Phone-only pip check/import, never login/sound without deliberate user test.
5. Parse PowerShell with Windows PS5.1. Exercise installer in a writable folder containing spaces; nonempty/edit/instance-lock protections; verify default Python/PATH and unrelated packages unchanged.
6. Inspect actual GUI screenshot; test windowless entry. Never mock an image and label it a working screenshot.
7. git diff --check. Add accurate QA evidence and remaining physical tests to docs/OFFICE_RELEASE_030.md. No claim that tests validate real sleep/false-negative rate.

Keep routine follow-up work in VS Code using these instructions. Do not expand into productivity surveillance. User has other active projects: their interpreters, environments and work take priority.
