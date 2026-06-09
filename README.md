
# MVSA Day-1 Build

MVSA = Minimum Viable Save-My-Ass.

This is a local Python vigilance assistant for Rahul's office use.

## What it does

- Uses webcam vision to estimate drowsiness risk.
- Uses a "vigilance battery" from 0–100.
- Uses calibration at startup.
- Does NOT rely on gaze-at-monitor detection, because the webcam is on the left/laptop monitor and you usually look at another monitor.
- Treats absence from chair as AWAY, not sleep/drowsiness.
- Has three modes:
  - Normal
  - High Alert
  - Super Alert
- Keeps alarm channels modular:
  - screen flashing
  - Find My iPhone Play Sound
  - future alarm backends can be added later

## Install

Open Command Prompt in this folder and run:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## First test Find My separately

```bash
python test_findmy.py
```

This tests whether Python can trigger iPhone Find My Play Sound.

You need:
- Find My enabled on iPhone
- Apple ID credentials
- Internet connection
- 2FA code during first login

## Run MVSA

```bash
python mvsa_app.py
```

## Startup sequence

1. Select mode.
2. Calibrate.
3. Start monitoring.

## Calibration sequence

The app will guide you through:

1. Normal working posture
2. Awake working variations
3. Full chair tilt posture
4. Eyes closed posture
5. Relaxed eyelids

Important: During normal/variation calibration, do NOT stare into the camera unless you normally do that. Work naturally. The system should learn your actual office geometry, not a fake straight-camera posture.

## Modes

### Normal
Tilt adds risk but does not immediately alarm.

### High Alert
Tilt has higher weight. Learning is off. Alarms happen faster.

### Super Alert
Tilt while present in the chair is forbidden. If tilt is detected, screen flashing starts and Find My can trigger.

## Alarm channels

### Screen flashing
Always local, free, immediate. It attempts to cover all monitors.

### Find My iPhone
Free workaround using iCloud Find Devices "Play Sound". Not a phone call UI, but phone makes a loud Find My sound.

Edit `mvsa_config.json` after first run:

```json
{
  "findmy": {
    "enabled": true,
    "apple_id": "your@email.com",
    "device_name_contains": "iPhone",
    "min_seconds_between_triggers": 130
  }
}
```

For security, MVSA does not store your Apple ID password in the config. It asks at startup when needed.

## Quit

The dashboard tries to stay always on top. Use:

Ctrl + Shift + Q

to quit.

## Notes

- No video is saved.
- Only logs are saved to CSV.
- If face is absent, MVSA assumes you are away from the chair and discharges risk.
- On high-risk days, use Super Alert.
- Do not rely on this as a medical or safety system. Do not drive or operate dangerous machinery when sleep deprived or affected by sedatives.
