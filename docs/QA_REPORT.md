# WakeGuard 0.2 QA / testing-release report

## Release status

**Ready for the user's hardware acceptance session. Automated Windows checks passed.**

Code revision: `67898eef55e533c4b881efe7d2515867344e2450`.
Windows run: https://github.com/raihanulrahul/wakeguard/actions/runs/35980076220
Job: `107569603186`, completed successfully on 24 September 2026.

This is a functional desktop-testing candidate, NOT a validated drowsiness detector. No real-world false-negative rate or guaranteed awakening has been established. The final documentation commit does not change the tested application code.

## Actual Windows verification

Hosted Windows Server 2025 runner; CPython **3.12.10 x64**.

- Clean vision environment installed successfully. `pip check`: **No broken requirements found**.
- Actual MediaPipe **FaceMesh and Pose blank-image inference passed**. OpenCV, NumPy, Tkinter and Pillow imports passed. This did not use a camera.
- **107 regression tests passed in 6.172 seconds**, including **19 real Tk GUI tests**; no test skips.
- Separate phone environment installed **pyicloud 2.6.5** successfully. Import and `pip check` passed. **No Apple login or real phone sound was performed.**
- Windows PowerShell parsed the setup, speech and optional voice scripts without syntax errors.
- Native System.Speech synthesis to a null output passed. **Speaker audibility and microphone recognition were not tested.**
- All workflow steps completed successfully. Dependency deprecation notices were not test failures.

The setup script itself was parsed; CI performed its environment installation/check operations separately rather than executing the full interactive setup script. Actual mixed-DPI physical monitors and camera drivers still need the user's check.

## Additional local verification

Linux container, CPython 3.13.5, available OpenCV/NumPy, real Tk windows under Xvfb (1600x1000). Local MediaPipe and pyicloud were not installed; their import/inference checks above were run on Windows instead.

- Python source compilation passed.
- **107 regression tests passed**, including the same 19 Tk GUI tests; no skips.
- Dashboard and alert screenshots inspected. Simulated multiple monitor windows use one instruction panel with steady escape controls.
- Synthetic 3D projections recovered expected pitch/yaw. Degenerate coincident landmarks initially yielded plausible false angles; geometric rejection was added and the regression passed.
- State tests cover sustained upright eye closure, partial closure, Normal/Super recline, neck directions, interrupted recovery, stale camera, body-present occlusion, empty-scene evidence, camera failure, manual-departure grace and restricted adaptation.
- Calibration tests cover frame freshness/counts, inverted open/closed labels, insufficient separation, camera identity changes, half-closed samples and insufficient observability.
- Phone tests use fake APIs/processes: rejected 2FA cannot arm, verification attempts are bounded, device selection is exact, cooldown is reserved before requests, and timeout/dead-worker failures revoke readiness. No destructive device commands are exposed.
- Lifecycle tests cover test-overlay hotkeys, Stop during calibration/monitoring/speech, repeated Start, callback invalidation and GUI exception cleanup.

## Fixes made during QA

Invalid face geometry yields unknown, not fabricated angles. Corrupt old calibration is replaced only after accepted new data, with its previous bytes backed up. Windows screen placement uses pointer-sized native handles and absolute coordinates. Closed/half-eye stages tell the user to keep eyes open until Begin and announce open eyes at the capture deadline. Stop clears owned workers and input queues. Start blocks pending phone setup. Half-eye samples affect personalized warning thresholds. Optional voice Stop works during spoken instructions. Dashboard content scrolls. Ordinary installation does not open intrusive GUI tests unless explicitly enabled.

## Physical acceptance still required

1. Preview stays responsive using the actual camera. Normal main-monitor posture, neck down/back and full recline have correctly directed metrics. At least one eye is measurable, or the system visibly reports uncertainty instead of guessing.
2. Setup speech is audible. Optional voice works with the installed English recognizer, or SPACE/R/B works as the fallback. Eye-closed capture ends audibly without reading or clicking.
3. Calibration and the independent setup-verification sequence pass. Changed placement/lighting is rejected or visibly uncertain.
4. All 2–3 physical monitors, including negative origins/mixed DPI, are covered; text appears on one only. SPACE/Esc/STOP/QUIT work. The camera indicator turns off after Stop, including during calibration, without terminating VS Code.
5. Fresh open eyes for three seconds clear an alert except ongoing Super Alert recline. Ordinary blinks do not alert; deliberate closure/half closure does. Use awake test poses, not induced sleep.
6. The exact iPhone sounds when tested locked and with/without earbuds. Record actual routing; do not assume it. Confirm the heard-test, then test an app-triggered alert after the rate limit. Already-submitted sound may require dismissal on the phone.
7. Disconnect camera/internet and verify a visible fault/degraded state. A green widget alone does not prove coverage.

## Remaining limitations

Head pose and eye ratios are heuristic, not clinical ground truth. Side angles, glasses, darkness, occlusion, other faces and low resolution can defeat tracking. Empty-scene matching is not a physical seat sensor. Calibration may correctly reject an unusable camera position, requiring re-aiming. Optional voice depends on installed English Windows recognition and microphone quality. Find My uses unofficial service access and needs internet/authentication; it may fail or be delayed. Audibility, earbud routing, wake-up effectiveness and cancellation of a submitted remote sound are not guaranteed.

Do not call the build fully hardware-validated until the physical acceptance session passes. Do not use it as permission to drive, operate machinery, or work through dangerous sleepiness/sedation.
