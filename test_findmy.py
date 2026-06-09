
"""
Standalone Find My iPhone Play Sound test.

Run:
    python test_findmy.py

This lets you validate the phone alarm path before relying on MVSA.
"""

import json
import time
from pathlib import Path
from getpass import getpass

CONFIG_PATH = Path("mvsa_config.json")


def load_config():
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps({
            "findmy": {
                "enabled": True,
                "apple_id": "",
                "device_name_contains": "iPhone",
                "min_seconds_between_triggers": 130
            }
        }, indent=2), encoding="utf-8")
        print("Created mvsa_config.json. Edit apple_id first, then run again.")
        raise SystemExit(1)
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def pick_device(api, name_contains):
    devices = list(api.devices)
    if not devices:
        raise RuntimeError("No iCloud devices found.")

    print("\nAvailable devices:")
    for i, d in enumerate(devices):
        name = getattr(d, "data", {}).get("name", str(d))
        print(f"  [{i}] {name}")

    name_contains = (name_contains or "").lower().strip()
    if name_contains:
        for d in devices:
            name = getattr(d, "data", {}).get("name", str(d))
            if name_contains in name.lower():
                return d

    idx = input("\nSelect device number: ").strip()
    return devices[int(idx)]


def main():
    try:
        from pyicloud import PyiCloudService
    except Exception as e:
        print("pyicloud is not installed. Run: pip install pyicloud")
        raise

    cfg = load_config()
    fcfg = cfg.get("findmy", {})
    apple_id = fcfg.get("apple_id") or input("Apple ID: ").strip()
    password = getpass("Apple ID password/app password: ")

    api = PyiCloudService(apple_id, password)

    if getattr(api, "requires_2fa", False):
        print("Two-factor authentication required.")
        code = input("Enter 2FA code: ").strip()
        result = api.validate_2fa_code(code)
        print("2FA validation result:", result)
        try:
            api.trust_session()
        except Exception as e:
            print("Could not trust session:", e)

    device = pick_device(api, fcfg.get("device_name_contains", "iPhone"))

    print("\nTriggering Find My Play Sound now...")
    try:
        device.play_sound(subject="MVSA TEST ALERT")
    except TypeError:
        device.play_sound()
    print("Triggered. Check your iPhone.")
    time.sleep(2)


if __name__ == "__main__":
    main()
