# WakeGuard 0.3 — guided desktop testing build

A local Windows desk-alert assistant with personalized eyelid/head/recline calibration, a guided modern dashboard, independent full-screen/iPhone sound channels, and temporary maximum brightness on supported displays.

**A testable prototype, not a validated sleep detector, medical device, or guarantee of awakening. Do not use it to justify driving, machinery operation or working through dangerous sleepiness. A screen alone may not wake someone with closed eyes.**

## New PC: private installation, your choice of folder

Run `Install-WakeGuard.ps1` in ordinary Windows PowerShell. It asks for a dedicated writable local folder, such as `E:\Apps\WakeGuard`, or accepts the per-user default. No Git or existing Python is required. Initial installation needs internet.

The installer downloads an immutable source revision, runs `Setup-WakeGuard-Private.ps1`, creates application-only Python/package environments, adds a desktop shortcut, and opens WakeGuard. It does not request elevation, modify system Python/PATH/launcher/file associations, disable security software, or change permissions. Existing nonempty folders are protected. Corporate network, application-control, camera or script policies can still block operation; follow the approved IT route rather than bypassing them.

Example after downloading the installer file:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-WakeGuard.ps1
```

Installed folders: `.runtime` holds private Python; `.venv_wakeguard` vision/UI; `.venv_phone` the incompatible phone stack; `.bootstrap` tools/caches/recovery snapshots. Runtime settings, calibration, cookies and events remain in `%LOCALAPPDATA%\WakeGuard`. Keep the private runtime in place. Install separately on each PC instead of copying environments.

The bootstrap uses a pinned, SHA-256-verified portable uv helper with `--no-bin --no-registry --no-config` to obtain app-private CPython 3.12.10 x64. No global uv/Python installer is invoked. Dependencies are confined to application environments; pip redirection/configuration inherited from other projects is disabled only for the setup process. See `docs/PRIVATE_SETUP.md` and `docs/OFFICE_RELEASE_030.md`.

## Everyday launch and updates

Double-click the **WakeGuard desktop shortcut** or **Start-WakeGuard.cmd**. No terminal typing, activation, VS Code, or persistent command window is needed. The explicit app interpreter is used; duplicate UI launches are rejected without stopping the existing instance. Startup errors are displayed and logged locally.

Packaged installation: close WakeGuard, then double-click `Update-WakeGuard.cmd`. It checks that managed source was not locally edited, backs up source, checks the running-instance lock, and reuses private environments. It never force-resets user edits or repurposes an unrelated folder.

Existing Git checkout (such as `D:\Codes\wakeguard`): close the app, inspect `git status`, preserve any edits, then `git pull --ff-only origin main` and launch `Start-WakeGuard.cmd`. This 0.2.2→0.3.0 update needs no dependency reinstall. **Do not run the package installer over a Git checkout.** For dependency updates in an existing checkout, use `Setup-WakeGuard-Private.ps1`, not a global pip command.

## Follow the next-step card

The large **YOUR NEXT STEP** card guides the sequence. The sidebar separates Guided setup, Live view, Alert settings and Diagnostics. Stop, Quit and Acknowledge stay in the footer; technical logs are no longer mixed with every normal action.

1. Start camera preview and select the correct camera/backend. Look at your normal work screen, not necessarily the webcam. Set Screens used for work to 1, 2 or 3.
2. Test speech and confirm you heard it. Optional offline English voice commands can be enabled, but keyboard/buttons remain available.
3. Calibrate, using labelled eye/posture samples. Step 2 has a separate take for each selected work screen. Read on the named screen during that take, not continuously between screens.
4. Verify today's setup. Saved calibration can be reused only when current geometry passes.
5. Test the screen alert and acknowledge it. Configure and test Find My, or explicitly choose **screen-only TEST mode**.
6. Select Normal / High Alert / Super Alert in Live view and Start monitoring.

The app does not silently start monitoring after installation or calibration. After Stop/relaunch, preview and setup verification are required. Phone connection/testing is needed after its worker stops. Work and home PCs require their own calibration and account session.

## Calibration controls

- **Space / Ready-Next** skips long instructions but retains the short state label/countdown, or accepts a good completed sample.
- **R / Repeat** and **B / Previous** interrupt narration/countdown/capture immediately and prepare the same/previous stage with a short reminder. Incomplete takes are discarded; accepted earlier samples remain.
- Optional prefixed commands: “WakeGuard ready”, “WakeGuard next”, “WakeGuard repeat”, “WakeGuard back”, “WakeGuard stop”. Recognition during narration depends on the microphone/recognizer, not just software event routing.
- **Esc** cancels setup. **Ctrl+Alt+S** stops everything. **Ctrl+Shift+Q** quits.

Eyes-open stages say Sample complete. Only closed/half-closed stages require Open your eyes; empty-chair completion says You may return to your chair. The brief reopen cue cannot be skipped to start another eye-closed take. Closed captures remain bounded at 3 seconds; half-closed at 5 seconds. Open-eye captures can extend only to a bounded deadline if quality recovers. Poor measurements are not automatically labelled safe.

The calibration has 15 labelled stages covering normal work, individual screens, side angles, reading, neck down/up, recline, half/closed eyelids and empty chair. It validates separation, direction and sample quality; rejects stale/inverted samples; and backs up prior accepted calibration. Moving the camera requires restarting full calibration so old and new geometry are not mixed. See `docs/CALIBRATION_USABILITY_FIX.md` for technical detail.

## Vivid alerts and brightness

**Red / white** uses `#ff0000` / `#ffffff`; **Red / blue** uses `#ff0000` / `#0000ff`. Each connected monitor has its own fullscreen window; text and steady control buttons occupy one screen only. Alternation changes colour once per second (a full cycle takes two seconds). Uncheck alternation for steady white. There is no rapid strobe. Bright changing colours can be unsuitable for photosensitivity; the screen test asks for explicit confirmation and auto-stops after ten seconds. Timeout alone does not claim you saw the test.

Maximum brightness is requested through native Windows WMI and DDC/CI APIs **where supported**, not a gamma hack or a display-driver installation. The original value is recorded before a write; changes are read back. A worker keeps hardware calls out of the UI, restores after acknowledgement/auto-clear/Stop/Quit, and restores on parent disconnection or lost heartbeat when the driver remains responsive. A journal and Restore brightness control allow retry after a failure. Settings on unreadable/unsupported monitors are not guessed.

A hung driver, unplugged monitor, restricted control or unusual monitor firmware can prevent a successful change or restore. Such results are reported as unavailable/unconfirmed, not silently called success. Monitor buttons may still be required. Test on the actual office displays before relying on automatic brightness. The assistant's test environments do not prove compatibility with your physical monitors.

Own alert illumination is excluded from learning and lighting-drift classification during its short recovery window, without suppressing sustained eye closure, head/recline rules or camera-failure warnings.

## Detection and independent phone channel

Normal allows awake recline as contributing evidence, not an immediate violation. High Alert is stricter and disables learning. Super Alert forbids calibrated recline. Neck drop is distinct from chair recline. The concern meter is a heuristic, **not a probability of sleep**.

Sustained observable eye closure can alarm independently of keyboard activity. Fresh open eyes for three seconds clear the alarm except continuing forbidden recline in Super Alert. Missing face/eyes is uncertainty, not automatically AWAY. Automatic AWAY requires absent face/body plus a stable calibrated empty-scene match. Continuous adaptation is slow, bounded, session-only and never rewrites closed-eye/neck/recline anchors.

Find My runs in the separate phone environment. Complete account/2FA and explicitly select the exact iPhone, send a sound test, then confirm **I heard the test**. There is a 130-second minimum interval including tests. No credentials are requested during an alarm, and no erase/lost-mode commands exist. Only Play Sound is exposed.

**Find My is not a cellular call.** Delivery, audible output, earbud routing and awakening are not guaranteed. A sound already submitted to Apple cannot be recalled by closing WakeGuard; dismiss it on the phone. Expired authentication/timeouts revoke readiness visibly. Passwords are not placed in command lines, Git, settings or logs. Protect local session cookies like browser session data.

No video, screenshots of the user's work, or microphone recordings are saved. Numeric calibration/diagnostics and a coarse empty-scene descriptor are local. Monitoring does not use PC alarm sound. Setup speech is local Windows synthesis. User-invoked phone operations contact Apple.

## Development and evidence

`wakeguard/controller.py` preserves the 0.2.2 calibration/control layer. `app.py` and `dashboard.py` provide the guided desktop. Brightness has transaction, native-driver and worker modules. `AGENTS.md` describes invariants for Codex. Use explicit private interpreter paths and preserve edits.

```powershell
.\.venv_wakeguard\Scripts\python.exe -m unittest discover -s tests -v
.\Start-WakeGuard.cmd --demo
```

GUI tests are opt-in because they open real windows: set `WAKEGUARD_GUI_TESTS=1` only in a suitable test setting. No physical brightness writes are performed by the regression suite. Review `docs/OFFICE_RELEASE_030.md` for actual Windows/installer results and the remaining hardware acceptance checklist.
