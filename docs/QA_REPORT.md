# WakeGuard 0.2 QA / release-candidate report

## Scope

Functional desktop-testing candidate replacing the old monolithic runtime. NOT a validated drowsiness detector; no measured real-world false-negative rate. Final acceptance requires the user's actual Windows camera, monitors, audio and iPhone.

## Checks actually run before publication

Linux container, CPython 3.13.5, available OpenCV/NumPy, real Tk windows under Xvfb (1600x1000). MediaPipe and pyicloud were NOT installed in that container. Windows-specific package/runtime verification is separate, not inferred from Linux results.

- Python source compilation passed.
- **107 regression tests passed, including 19 Tk GUI tests; no skips in that run.**
- Dashboard and alert screenshots inspected; simulated multiple monitor windows with one instruction panel and steady escape controls.
- Synthetic 3D projection recovered expected head pitch/yaw. Degenerate coincident landmarks initially gave plausible false angles; geometric rejection was added and regression passed.
- State tests cover sustained upright closure, partial closure, Normal/Super recline, neck directions, interrupted recovery, stale camera, body-present occlusion, empty-scene evidence, camera failure, manual-departure grace and restricted adaptation.
- Calibration tests cover frame freshness/counts, open/closed inversion, inadequate separation, camera identity changes, half-closed samples and insufficient observability.
- Phone tests use fake APIs/processes: rejected 2FA cannot arm, attempts bounded, exact device selection, single-flight cooldown, timeout/dead-worker readiness and no destructive commands. **No real Apple login or phone sound was performed in the authoring environment.**
- Lifecycle tests cover test-overlay hotkeys, Stop during calibration/monitoring/speech, repeated Start, callback invalidation and GUI exception cleanup.

## Fixes found during QA

Invalid face geometry now yields unknown, not fabricated angles. Corrupt old calibration can be replaced only after accepted new data, with prior bytes backed up. Absolute Windows screen placement uses pointer-sized native handles. Closed/half-eye stages say keep eyes open until Begin and announce open eyes at a fixed deadline. Stop clears input queues and owned workers. Start blocks pending phone setup. Half-eye samples influence personalized warning thresholds. Optional voice Stop works during spoken instructions. Dashboard content is scrollable. Ordinary installation does not run intrusive GUI tests unless opted in.

## Required physical acceptance — not yet performed here

- New vision/phone environments pass dependency/import checks; actual camera preview remains responsive.
- At the normal side-camera angle, neck-down, head-back and reclined measurements have correct direction. At least one eye is measurable, or uncertainty is shown instead of guessed.
- Setup speech is audible; voice commands work on the installed recognizer or tactile fallback works. Eye-closed capture ends audibly without reading/clicking.
- Calibration and independent setup verification pass. Changed placement/lighting is rejected or visibly uncertain.
- All 2–3 physical monitors (including negative origins/mixed DPI) are covered; text is on one only. SPACE/Esc/STOP/QUIT work. Camera LED turns off after Stop, including during calibration. No VS Code termination needed.
- Fresh open eyes for three seconds clear a screen alert, except ongoing Super Alert recline. Normal blinks do not alert; deliberate closure/half closure do. Use awake test poses, not induced sleep.
- Exact iPhone sounds when tested locked and with/without earbuds. Record actual routing; do not assume it. Confirm heard-test, then test an app-triggered event. Already-submitted sound may require dismissal on the phone.
- Disconnect camera/internet; verify a visible fault/degraded state. A green widget alone is not proof of coverage.

## Limitations

Generic head pose and eye ratios are heuristics, not clinical ground truth. Side angles, glasses, darkness, occlusion, another face and low pixel resolution can defeat tracking. Empty-scene matching is not a physical seat sensor. Calibration may correctly reject an unusable camera position; re-aiming can be necessary. Voice depends on installed English Windows recognition and microphone quality. Find My is unofficial service access, needs internet/authentication and can fail/delay. Audibility, earbud routing, wake-up effectiveness and remote cancellation are not guaranteed.

Windows CI results and subsequent hardware observations must be recorded as actual evidence, not assumed. Do not describe this as fully hardware-validated until the acceptance session has passed.
