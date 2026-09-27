"""Double-click/shortcut entry. App-only interpreter; failures stay visible."""
from pathlib import Path
import os
import sys
import traceback

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
for name in ("TCL_LIBRARY", "TK_LIBRARY"):
    os.environ.pop(name, None)


def notify(message):
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "WakeGuard", 0x10)
    else:
        print(message, file=sys.stderr)


def run():
    from wakeguard.model import data_home
    from wakeguard.instance import InstanceGuard
    from wakeguard.app import main
    home = data_home()
    guard = None
    try:
        guard = InstanceGuard(home, ROOT)
        main()
    except RuntimeError as exc:
        notify(str(exc))
    except Exception:
        log = home / "startup-error.log"
        log.write_text(traceback.format_exc(), encoding="utf-8")
        notify("WakeGuard could not start. Details are in:\n" + str(log) + "\n\nYour other Python installations were not changed.")
    finally:
        if guard:
            guard.close()


if __name__ == "__main__":
    try:
        run()
    except Exception:
        error_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "WakeGuard"
        error_dir.mkdir(parents=True, exist_ok=True)
        error_file = error_dir / "startup-error.log"
        error_file.write_text(traceback.format_exc(), encoding="utf-8")
        notify("WakeGuard could not load. Diagnostic: " + str(error_file))
