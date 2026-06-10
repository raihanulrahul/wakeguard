
import os
import sys
import cv2
import time
import json
import math
import csv
import threading
import traceback
from pathlib import Path
from dataclasses import dataclass, field
from collections import deque
from getpass import getpass

import numpy as np

try:
    import mediapipe as mp
except Exception:
    mp = None

try:
    from mediapipe.python.solutions import face_mesh as mp_face_mesh_fallback
except Exception:
    mp_face_mesh_fallback = None

try:
    from pynput import keyboard, mouse
except Exception:
    keyboard = None
    mouse = None

try:
    from screeninfo import get_monitors
except Exception:
    get_monitors = None

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog


APP_NAME = "WakeGuard Day-1"
CONFIG_PATH = Path("mvsa_config.json")
CALIB_PATH_DEFAULT = Path("mvsa_calibration.json")
LOG_PATH_DEFAULT = Path("mvsa_log.csv")


# -----------------------------
# Utility
# -----------------------------

def now_str():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def safe_median(vals, default=None):
    vals = [v for v in vals if v is not None and np.isfinite(v)]
    if not vals:
        return default
    return float(np.median(vals))


def safe_percentile(vals, p, default=None):
    vals = [v for v in vals if v is not None and np.isfinite(v)]
    if not vals:
        return default
    return float(np.percentile(vals, p))


def load_or_create_config():
    default = {
        "findmy": {
            "enabled": False,
            "apple_id": "",
            "device_name_contains": "iPhone",
            "min_seconds_between_triggers": 130
        },
        "screen_flash": {
            "enabled": True
        },
        "app": {
            "camera_index": 0,
            "log_file": str(LOG_PATH_DEFAULT),
            "calibration_file": str(CALIB_PATH_DEFAULT)
        }
    }
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(default, indent=2), encoding="utf-8")
        return default

    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        # merge shallow
        for k, v in default.items():
            loaded.setdefault(k, v)
            if isinstance(v, dict):
                for kk, vv in v.items():
                    loaded[k].setdefault(kk, vv)
        return loaded
    except Exception:
        return default


# -----------------------------
# Alarm backends
# -----------------------------

class AlarmBackend:
    name = "base"

    def trigger(self, level: str, reason: str):
        raise NotImplementedError

    def stop(self):
        pass


class ScreenFlashBackend(AlarmBackend):
    name = "screen_flash"

    def __init__(self, root, acknowledge_callback=None):
        self.root = root
        self.acknowledge_callback = acknowledge_callback
        self.overlays = []
        self.text_overlay = None
        self.labels = []
        self.active = False
        self._flash_job = None
        self._state = False

    def _monitor_geometries(self):
        root_x = 0
        root_y = 0
        try:
            self.root.update_idletasks()
            root_x = self.root.winfo_rootx()
            root_y = self.root.winfo_rooty()
        except Exception:
            pass

        if get_monitors is not None:
            try:
                mons = get_monitors()
                if mons:
                    geometries = []
                    for idx, mon in enumerate(mons):
                        contains_dashboard = (
                            mon.x <= root_x < mon.x + mon.width and
                            mon.y <= root_y < mon.y + mon.height
                        )
                        geometries.append({
                            "x": mon.x,
                            "y": mon.y,
                            "w": mon.width,
                            "h": mon.height,
                            "primary": bool(getattr(mon, "is_primary", False)),
                            "dashboard": contains_dashboard,
                            "idx": idx
                        })
                    return geometries
            except Exception:
                pass

        return [{
            "x": 0,
            "y": 0,
            "w": self.root.winfo_screenwidth(),
            "h": self.root.winfo_screenheight(),
            "primary": True,
            "dashboard": True,
            "idx": 0
        }]

    def _text_monitor_index(self, geometries):
        for idx, geo in enumerate(geometries):
            if geo.get("dashboard"):
                return idx
        for idx, geo in enumerate(geometries):
            if geo.get("primary"):
                return idx
        return 0

    def trigger(self, level: str, reason: str):
        if self.active:
            return
        self.active = True
        geometries = self._monitor_geometries()
        text_idx = self._text_monitor_index(geometries)

        for idx, geo in enumerate(geometries):
            overlay = tk.Toplevel(self.root)
            overlay.title("WakeGuard ALARM")
            overlay.overrideredirect(True)
            overlay.attributes("-topmost", True)
            overlay.geometry(f"{geo['w']}x{geo['h']}+{geo['x']}+{geo['y']}")
            for sequence in ("<space>", "<Escape>", "<Control-Shift-A>", "<Control-Shift-a>"):
                overlay.bind(sequence, self._acknowledge_from_overlay)

            label = None
            if idx == text_idx:
                label = tk.Label(
                    overlay,
                    text=f"WakeGuard ALARM\n\n{reason}\n\nPress SPACE to acknowledge",
                    font=("Arial", 48, "bold"),
                    fg="black",
                    bg="white",
                    justify="center",
                    wraplength=max(320, int(geo["w"] * 0.86))
                )
                label.pack(expand=True, fill="both")
                self.text_overlay = overlay
            else:
                overlay.configure(bg="white")

            self.overlays.append(overlay)
            self.labels.append(label)

        try:
            (self.text_overlay or self.overlays[0]).focus_force()
        except Exception:
            pass
        self._flash()

    def _acknowledge_from_overlay(self, event=None):
        if self.acknowledge_callback is not None:
            return self.acknowledge_callback(event)
        return "break"

    def _flash(self):
        if not self.active or not self.overlays:
            return
        self._state = not self._state
        bg = "white" if self._state else "red"
        fg = "black" if self._state else "white"
        for overlay, label in zip(list(self.overlays), list(self.labels)):
            try:
                overlay.configure(bg=bg)
                if label is not None:
                    label.configure(bg=bg, fg=fg)
                overlay.lift()
                overlay.attributes("-topmost", True)
            except Exception:
                pass
        self._flash_job = self.root.after(350, self._flash)

    def stop(self):
        self.active = False
        if self._flash_job is not None:
            try:
                self.root.after_cancel(self._flash_job)
            except Exception:
                pass
        self._flash_job = None
        for overlay in list(self.overlays):
            try:
                overlay.destroy()
            except Exception:
                pass
        self.overlays = []
        self.labels = []
        self.text_overlay = None


class FindMyBackend(AlarmBackend):
    name = "find_my"

    def __init__(self, root, config, log_callback=None):
        self.root = root
        self.config = config
        self.log_callback = log_callback or (lambda msg: None)
        self.enabled = bool(config.get("findmy", {}).get("enabled", False))
        self.api = None
        self.device = None
        self.last_trigger = 0.0
        self.auth_attempted = False
        self.auth_ok = False

    def authenticate_interactive(self):
        if not self.enabled:
            self.log_callback("Find My disabled in config.")
            return False

        if self.auth_ok and self.device is not None:
            return True

        try:
            from pyicloud import PyiCloudService
        except Exception as e:
            self.log_callback("Find My unavailable: pyicloud not installed.")
            return False

        fcfg = self.config.get("findmy", {})
        apple_id = fcfg.get("apple_id", "").strip()
        if not apple_id:
            apple_id = simpledialog.askstring("Find My", "Apple ID:", parent=self.root)
            if not apple_id:
                return False

        password = simpledialog.askstring("Find My", "Apple ID password:", parent=self.root, show="*")
        if not password:
            return False

        try:
            self.log_callback("Authenticating with iCloud...")
            api = PyiCloudService(apple_id, password)

            if getattr(api, "requires_2fa", False):
                code = simpledialog.askstring("Find My 2FA", "Enter Apple 2FA code:", parent=self.root)
                if not code:
                    self.log_callback("2FA cancelled.")
                    return False
                ok = api.validate_2fa_code(code.strip())
                self.log_callback(f"2FA result: {ok}")
                try:
                    api.trust_session()
                except Exception as e:
                    self.log_callback(f"Could not trust iCloud session: {e}")

            devices = list(api.devices)
            if not devices:
                self.log_callback("No iCloud devices found.")
                return False

            wanted = fcfg.get("device_name_contains", "iPhone").lower().strip()
            selected = None
            for d in devices:
                name = getattr(d, "data", {}).get("name", str(d))
                if wanted and wanted in name.lower():
                    selected = d
                    break
            if selected is None:
                selected = devices[0]

            name = getattr(selected, "data", {}).get("name", str(selected))
            self.log_callback(f"Find My target device: {name}")

            self.api = api
            self.device = selected
            self.auth_ok = True
            return True
        except Exception as e:
            self.log_callback("Find My auth failed: " + str(e))
            self.log_callback(traceback.format_exc())
            self.auth_ok = False
            return False

    def trigger(self, level: str, reason: str):
        if not self.enabled:
            return

        now = time.time()
        cooldown = float(self.config.get("findmy", {}).get("min_seconds_between_triggers", 130))
        if now - self.last_trigger < cooldown:
            return

        def worker():
            try:
                if not self.auth_ok or self.device is None:
                    # Authentication must be done on UI thread because of dialogs.
                    self.root.after(0, self._auth_then_trigger, level, reason)
                    return
                self._play_sound(level, reason)
            except Exception as e:
                self.log_callback("Find My trigger failed: " + str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _auth_then_trigger(self, level, reason):
        if self.authenticate_interactive():
            threading.Thread(target=lambda: self._play_sound(level, reason), daemon=True).start()

    def _play_sound(self, level, reason):
        if self.device is None:
            return
        self.log_callback("Triggering Find My Play Sound...")
        try:
            self.device.play_sound(subject=f"WakeGuard {level}: {reason[:80]}")
        except TypeError:
            self.device.play_sound()
        self.last_trigger = time.time()
        self.log_callback("Find My Play Sound triggered.")


class AlarmManager:
    def __init__(self, backends, log_callback=None):
        self.backends = backends
        self.log_callback = log_callback or (lambda msg: None)
        self.active = False
        self.last_level = None
        self.last_reason = ""
        self.last_alarm_time = 0.0

    def trigger(self, level, reason):
        if not self.active:
            self.log_callback(f"ALARM START: {level} - {reason}")
        self.active = True
        self.last_level = level
        self.last_reason = reason
        self.last_alarm_time = time.time()
        for b in self.backends:
            try:
                b.trigger(level, reason)
            except Exception as e:
                self.log_callback(f"Alarm backend {b.name} failed: {e}")

    def stop(self):
        if self.active:
            self.log_callback("ALARM STOPPED/ACKNOWLEDGED")
        self.active = False
        for b in self.backends:
            try:
                b.stop()
            except Exception:
                pass


# -----------------------------
# Vision
# -----------------------------

LEFT_EYE = [33, 160, 158, 133, 153, 144]
RIGHT_EYE = [362, 385, 387, 263, 373, 380]


@dataclass
class FeaturePacket:
    t: float
    face_present: bool = False
    face_confidence: float = 0.0
    ear: float = None
    face_area: float = None
    face_center_x: float = None
    face_center_y: float = None
    pitch: float = None
    yaw: float = None
    roll: float = None
    nose_x: float = None
    nose_y: float = None
    movement: float = None
    raw_debug: dict = field(default_factory=dict)


class VisionEngine:
    def __init__(self, camera_index=0):
        if mp is None and mp_face_mesh_fallback is None:
            raise RuntimeError("mediapipe not installed. Run: pip install mediapipe")
        self.camera_index = camera_index
        self.mp_face_mesh = self._load_face_mesh_module()
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.45,
            min_tracking_confidence=0.45
        )
        self.cap = None
        self.history = deque(maxlen=150)

    def _load_face_mesh_module(self):
        if mp is not None:
            solutions = getattr(mp, "solutions", None)
            face_mesh = getattr(solutions, "face_mesh", None) if solutions is not None else None
            if face_mesh is not None:
                return face_mesh

        if mp_face_mesh_fallback is not None:
            return mp_face_mesh_fallback

        version = getattr(mp, "__version__", "unknown") if mp is not None else "not importable"
        location = getattr(mp, "__file__", "unknown") if mp is not None else "unknown"
        raise RuntimeError(
            "mediapipe FaceMesh API not found. "
            f"mediapipe version={version}, location={location}. "
            "Try reinstalling a standard mediapipe package in the active Python environment."
        )

    def open(self):
        if self.face_mesh is None:
            self.mp_face_mesh = self._load_face_mesh_module()
            self.face_mesh = self.mp_face_mesh.FaceMesh(
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.45,
                min_tracking_confidence=0.45
            )
        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open webcam index {self.camera_index}")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    def close(self):
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
        self.cap = None
        if self.face_mesh is not None:
            try:
                self.face_mesh.close()
            except Exception:
                pass
        self.face_mesh = None

    def read_features(self):
        if self.cap is None:
            self.open()
        ok, frame = self.cap.read()
        if not ok:
            return FeaturePacket(t=time.time(), face_present=False), None

        frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb)
        pkt = FeaturePacket(t=time.time())

        if not results.multi_face_landmarks:
            self.history.append(pkt)
            return pkt, frame

        lms = results.multi_face_landmarks[0].landmark
        pts = np.array([(lm.x * w, lm.y * h, lm.z) for lm in lms], dtype=np.float32)

        xs = pts[:, 0]
        ys = pts[:, 1]
        x1, x2 = float(np.min(xs)), float(np.max(xs))
        y1, y2 = float(np.min(ys)), float(np.max(ys))
        area = max(1.0, (x2 - x1) * (y2 - y1))

        ear = self._ear(pts, LEFT_EYE, RIGHT_EYE)
        pitch, yaw, roll = self._head_pose(pts, w, h)

        nose = pts[1]
        pkt.face_present = True
        pkt.face_confidence = 1.0
        pkt.ear = ear
        pkt.face_area = area
        pkt.face_center_x = (x1 + x2) / 2.0 / w
        pkt.face_center_y = (y1 + y2) / 2.0 / h
        pkt.pitch = pitch
        pkt.yaw = yaw
        pkt.roll = roll
        pkt.nose_x = nose[0] / w
        pkt.nose_y = nose[1] / h

        self.history.append(pkt)
        pkt.movement = self._movement_metric()

        # Draw minimal debug overlay.
        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 1)
        cv2.putText(frame, f"EAR:{ear:.3f} pitch:{pitch:.1f} area:{area:.0f}",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

        return pkt, frame

    def _ear_one(self, pts, idxs):
        p1, p2, p3, p4, p5, p6 = [pts[i][:2] for i in idxs]
        vertical1 = np.linalg.norm(p2 - p6)
        vertical2 = np.linalg.norm(p3 - p5)
        horizontal = np.linalg.norm(p1 - p4)
        if horizontal <= 1e-6:
            return None
        return float((vertical1 + vertical2) / (2.0 * horizontal))

    def _ear(self, pts, left_idxs, right_idxs):
        vals = []
        for idxs in (left_idxs, right_idxs):
            v = self._ear_one(pts, idxs)
            if v is not None and np.isfinite(v):
                vals.append(v)
        return safe_median(vals, default=None)

    def _head_pose(self, pts, w, h):
        # 2D image points from MediaPipe landmarks.
        image_points = np.array([
            pts[1][:2],    # Nose tip
            pts[152][:2],  # Chin
            pts[33][:2],   # Left eye outer
            pts[263][:2],  # Right eye outer
            pts[61][:2],   # Mouth left
            pts[291][:2],  # Mouth right
        ], dtype=np.float64)

        # Generic 3D model points.
        model_points = np.array([
            (0.0, 0.0, 0.0),
            (0.0, -63.6, -12.5),
            (-43.3, 32.7, -26.0),
            (43.3, 32.7, -26.0),
            (-28.9, -28.9, -24.1),
            (28.9, -28.9, -24.1),
        ], dtype=np.float64)

        focal_length = w
        center = (w / 2.0, h / 2.0)
        camera_matrix = np.array([
            [focal_length, 0, center[0]],
            [0, focal_length, center[1]],
            [0, 0, 1]
        ], dtype=np.float64)
        dist_coeffs = np.zeros((4, 1))

        try:
            success, rotation_vector, translation_vector = cv2.solvePnP(
                model_points, image_points, camera_matrix, dist_coeffs, flags=cv2.SOLVEPNP_ITERATIVE
            )
            if not success:
                return 0.0, 0.0, 0.0
            rotation_mat, _ = cv2.Rodrigues(rotation_vector)
            proj_mat = np.hstack((rotation_mat, translation_vector))
            _, _, _, _, _, _, euler = cv2.decomposeProjectionMatrix(proj_mat)
            pitch, yaw, roll = [float(v) for v in euler.flatten()]
            # Normalize to a practical range.
            return pitch, yaw, roll
        except Exception:
            return 0.0, 0.0, 0.0

    def _movement_metric(self, seconds=4.0):
        if len(self.history) < 5:
            return None
        now = self.history[-1].t
        recent = [p for p in self.history if p.face_present and now - p.t <= seconds]
        if len(recent) < 5:
            return None

        xs = np.array([p.nose_x for p in recent if p.nose_x is not None])
        ys = np.array([p.nose_y for p in recent if p.nose_y is not None])
        pitch = np.array([p.pitch for p in recent if p.pitch is not None])
        if len(xs) < 5 or len(pitch) < 5:
            return None

        # Movement in normalized screen coordinate plus small head angle variation.
        movement = float(np.std(xs) + np.std(ys) + 0.002 * np.std(pitch))
        return movement


# -----------------------------
# Calibration
# -----------------------------

CALIB_STAGES = [
    ("normal", 6, "NORMAL WORKING POSTURE\nWork naturally. Do NOT look into camera unless you normally do."),
    ("variation", 8, "AWAKE WORK VARIATIONS\nLook at main monitor, type, read, lean/turn slightly as you normally do."),
    ("tilted", 5, "FULL CHAIR TILT\nTilt fully back, stay awake, eyes open."),
    ("eyes_closed", 4, "EYES CLOSED\nSit normally and close eyes."),
    ("relaxed_eyes", 4, "RELAXED EYELIDS\nSit normally, relax eyelids but stay awake.")
]


class Calibrator:
    def __init__(self):
        self.samples = {name: [] for name, _, _ in CALIB_STAGES}

    def add_sample(self, stage, pkt: FeaturePacket):
        if pkt.face_present:
            self.samples[stage].append(pkt)

    def build(self):
        result = {
            "created_at": now_str(),
            "stages": {},
            "derived": {}
        }
        for stage, packets in self.samples.items():
            result["stages"][stage] = self._summarize(packets)

        normal_packets = self.samples.get("normal", []) + self.samples.get("variation", [])
        safe = self._summarize(normal_packets)
        tilted = result["stages"].get("tilted", {})
        closed = result["stages"].get("eyes_closed", {})
        relaxed = result["stages"].get("relaxed_eyes", {})

        open_ear = safe.get("ear_p50")
        closed_ear = closed.get("ear_p50")
        relaxed_ear = relaxed.get("ear_p50")

        result["derived"] = {
            "safe_ear_open": open_ear,
            "closed_ear": closed_ear,
            "relaxed_ear": relaxed_ear,
            "safe_area": safe.get("area_p50"),
            "tilt_area": tilted.get("area_p50"),
            "safe_pitch": safe.get("pitch_p50"),
            "safe_yaw": safe.get("yaw_p50"),
            "safe_roll": safe.get("roll_p50"),
            "tilt_pitch": tilted.get("pitch_p50"),
            "safe_center_y": safe.get("cy_p50"),
            "tilt_center_y": tilted.get("cy_p50"),
            "safe_movement_p25": safe.get("movement_p25"),
            "safe_movement_p50": safe.get("movement_p50"),
            "safe_pitch_low": safe.get("pitch_p10"),
            "safe_pitch_high": safe.get("pitch_p90"),
            "safe_yaw_low": safe.get("yaw_p10"),
            "safe_yaw_high": safe.get("yaw_p90"),
            "safe_roll_low": safe.get("roll_p10"),
            "safe_roll_high": safe.get("roll_p90"),
        }
        return result

    def _summarize(self, packets):
        def vals(attr):
            return [getattr(p, attr) for p in packets if getattr(p, attr) is not None and np.isfinite(getattr(p, attr))]
        return {
            "n": len(packets),
            "ear_p10": safe_percentile(vals("ear"), 10),
            "ear_p50": safe_percentile(vals("ear"), 50),
            "ear_p90": safe_percentile(vals("ear"), 90),
            "area_p10": safe_percentile(vals("face_area"), 10),
            "area_p50": safe_percentile(vals("face_area"), 50),
            "area_p90": safe_percentile(vals("face_area"), 90),
            "pitch_p10": safe_percentile(vals("pitch"), 10),
            "pitch_p50": safe_percentile(vals("pitch"), 50),
            "pitch_p90": safe_percentile(vals("pitch"), 90),
            "yaw_p10": safe_percentile(vals("yaw"), 10),
            "yaw_p50": safe_percentile(vals("yaw"), 50),
            "yaw_p90": safe_percentile(vals("yaw"), 90),
            "roll_p10": safe_percentile(vals("roll"), 10),
            "roll_p50": safe_percentile(vals("roll"), 50),
            "roll_p90": safe_percentile(vals("roll"), 90),
            "cy_p10": safe_percentile(vals("face_center_y"), 10),
            "cy_p50": safe_percentile(vals("face_center_y"), 50),
            "cy_p90": safe_percentile(vals("face_center_y"), 90),
            "movement_p25": safe_percentile(vals("movement"), 25),
            "movement_p50": safe_percentile(vals("movement"), 50),
        }


# -----------------------------
# Risk engine
# -----------------------------

MODE_CONFIGS = {
    "Normal": {
        "threshold_warning": 60,
        "threshold_alarm": 78,
        "critical_score": 92,
        "charge_factor": 32,
        "recovery_factor": 32,
        "eye_weight": 45,
        "tilt_weight": 20,
        "head_weight": 12,
        "stillness_weight": 15,
        "interaction_weight": 8,
        "eye_closed_seconds": 2.0,
        "learning": True,
        "tilt_hard_alarm": False
    },
    "High Alert": {
        "threshold_warning": 45,
        "threshold_alarm": 65,
        "critical_score": 85,
        "charge_factor": 55,
        "recovery_factor": 22,
        "eye_weight": 50,
        "tilt_weight": 32,
        "head_weight": 15,
        "stillness_weight": 18,
        "interaction_weight": 10,
        "eye_closed_seconds": 1.4,
        "learning": False,
        "tilt_hard_alarm": False
    },
    "Super Alert": {
        "threshold_warning": 30,
        "threshold_alarm": 50,
        "critical_score": 75,
        "charge_factor": 85,
        "recovery_factor": 12,
        "eye_weight": 55,
        "tilt_weight": 60,
        "head_weight": 18,
        "stillness_weight": 20,
        "interaction_weight": 12,
        "eye_closed_seconds": 1.0,
        "learning": False,
        "tilt_hard_alarm": True
    }
}


class InteractionMonitor:
    def __init__(self):
        self.last_activity = time.time()
        self.enabled = False
        self._keyboard_listener = None
        self._mouse_listener = None

    def start(self):
        if keyboard is None or mouse is None:
            return
        try:
            self._keyboard_listener = keyboard.Listener(on_press=lambda key: self._touch())
            self._mouse_listener = mouse.Listener(on_move=lambda x, y: self._touch(),
                                                  on_click=lambda x, y, button, pressed: self._touch(),
                                                  on_scroll=lambda x, y, dx, dy: self._touch())
            self._keyboard_listener.daemon = True
            self._mouse_listener.daemon = True
            self._keyboard_listener.start()
            self._mouse_listener.start()
            self.enabled = True
        except Exception:
            self.enabled = False

    def _touch(self):
        self.last_activity = time.time()

    def seconds_since_activity(self):
        return time.time() - self.last_activity


class RiskEngine:
    def __init__(self, calibration, interaction_monitor=None, log_callback=None):
        self.calibration = calibration
        self.interaction = interaction_monitor
        self.log_callback = log_callback or (lambda msg: None)
        self.battery = 0.0
        self.last_t = time.time()
        self.eye_closed_timer = 0.0
        self.tilt_timer = 0.0
        self.last_save = time.time()
        self.last_packet = None
        self.learning_dirty = False

    def update(self, pkt: FeaturePacket, mode="Normal"):
        now = pkt.t
        dt = clamp(now - self.last_t, 0.01, 0.5)
        self.last_t = now

        cfg = MODE_CONFIGS[mode]
        reasons = []
        debug = {}

        if not pkt.face_present:
            # Presence rule: if not in the chair, assume not asleep/drowsy at desk.
            self.battery = max(0.0, self.battery - 85 * dt)
            self.eye_closed_timer = 0.0
            self.tilt_timer = 0.0
            return {
                "status": "AWAY",
                "risk_score": 0.0,
                "battery": self.battery,
                "warning": False,
                "alarm": False,
                "reasons": ["face absent: away from chair"],
                "debug": {"presence": 0}
            }

        derived = self.calibration.get("derived", {}) if self.calibration else {}

        eye_risk, eye_ratio = self._eye_risk(pkt, derived)
        tilt_risk = self._tilt_risk(pkt, derived)
        head_risk = self._head_risk(pkt, derived)
        stillness_risk = self._stillness_risk(pkt, derived)
        interaction_risk = self._interaction_risk()

        if eye_risk > 0.55:
            reasons.append(f"eyelids {eye_risk:.2f}")
        if tilt_risk > 0.45:
            reasons.append(f"tilt/distance {tilt_risk:.2f}")
        if head_risk > 0.45:
            reasons.append(f"head posture {head_risk:.2f}")
        if stillness_risk > 0.45:
            reasons.append(f"stillness {stillness_risk:.2f}")
        if interaction_risk > 0.7:
            reasons.append("no keyboard/mouse")

        if eye_ratio is not None and eye_ratio < 0.28:
            self.eye_closed_timer += dt
        else:
            self.eye_closed_timer = max(0.0, self.eye_closed_timer - 2 * dt)

        if tilt_risk > 0.58:
            self.tilt_timer += dt
        else:
            self.tilt_timer = max(0.0, self.tilt_timer - 2 * dt)

        risk_score = (
            eye_risk * cfg["eye_weight"] +
            tilt_risk * cfg["tilt_weight"] +
            head_risk * cfg["head_weight"] +
            stillness_risk * cfg["stillness_weight"] +
            interaction_risk * cfg["interaction_weight"]
        )
        risk_score = clamp(risk_score, 0, 100)

        # Battery: dangerous evidence charges; healthy evidence discharges.
        if risk_score > 35:
            self.battery += ((risk_score - 35) / 65.0) * cfg["charge_factor"] * dt
        else:
            # keyboard/mouse activity and natural movement help discharge faster
            activity_bonus = 1.3 if interaction_risk < 0.2 else 1.0
            self.battery -= cfg["recovery_factor"] * activity_bonus * dt

        # Direct healthy state discharge.
        if eye_risk < 0.25 and tilt_risk < 0.25 and stillness_risk < 0.35:
            self.battery -= 8 * dt

        self.battery = clamp(self.battery, 0, 100)

        alarm = False
        warning = False

        if cfg["tilt_hard_alarm"] and tilt_risk > 0.60:
            alarm = True
            reasons.append("SUPER ALERT: tilt forbidden")

        if self.eye_closed_timer >= cfg["eye_closed_seconds"]:
            alarm = True
            reasons.append(f"eyes nearly closed {self.eye_closed_timer:.1f}s")

        if risk_score >= cfg["critical_score"]:
            alarm = True
            reasons.append(f"critical score {risk_score:.0f}")

        if self.battery >= cfg["threshold_alarm"]:
            alarm = True
            reasons.append(f"battery {self.battery:.0f}")

        if self.battery >= cfg["threshold_warning"] or risk_score >= cfg["threshold_warning"]:
            warning = True

        if alarm:
            status = "ALARM"
        elif warning:
            status = "WARNING"
        else:
            status = "SAFE"

        # Safe online learning: Normal mode only, battery low, clearly open eyes, not tilted.
        if cfg.get("learning") and status == "SAFE" and self.battery < 18 and eye_risk < 0.25 and tilt_risk < 0.25:
            self._safe_learn(pkt, derived)

        debug.update({
            "presence": 1,
            "eye_risk": eye_risk,
            "eye_ratio": eye_ratio,
            "tilt_risk": tilt_risk,
            "head_risk": head_risk,
            "pitch": pkt.pitch,
            "yaw": pkt.yaw,
            "roll": pkt.roll,
            "stillness_risk": stillness_risk,
            "interaction_risk": interaction_risk,
            "eye_closed_timer": self.eye_closed_timer,
            "tilt_timer": self.tilt_timer,
            "risk_score": risk_score,
            "seconds_since_input": self.interaction.seconds_since_activity() if self.interaction else None,
            "mode": mode
        })

        return {
            "status": status,
            "risk_score": risk_score,
            "battery": self.battery,
            "warning": warning,
            "alarm": alarm,
            "reasons": reasons or ["combined risk"],
            "debug": debug
        }

    def _eye_risk(self, pkt, d):
        if pkt.ear is None:
            return 0.25, None

        open_ref = d.get("safe_ear_open")
        closed_ref = d.get("closed_ear")
        if not open_ref or not closed_ref or abs(open_ref - closed_ref) < 0.02:
            # Fallback generic scale.
            ratio = clamp((pkt.ear - 0.16) / (0.30 - 0.16), 0, 1)
        else:
            ratio = clamp((pkt.ear - closed_ref) / (open_ref - closed_ref), 0, 1)

        # Nonlinear: punish very low eye openness strongly.
        risk = clamp(1.0 - ratio, 0, 1)
        if ratio < 0.35:
            risk = clamp(risk * 1.25, 0, 1)
        return risk, ratio

    def _tilt_risk(self, pkt, d):
        safe_area = d.get("safe_area")
        tilt_area = d.get("tilt_area")
        area_score = 0.0

        if pkt.face_area and safe_area and tilt_area and safe_area > tilt_area * 1.10:
            area_score = clamp((safe_area - pkt.face_area) / (safe_area - tilt_area), 0, 1)

        # Use face center y and pitch as secondary evidence toward the calibrated tilted state.
        cy_score = 0.0
        safe_cy = d.get("safe_center_y")
        tilt_cy = d.get("tilt_center_y")
        if pkt.face_center_y is not None and safe_cy is not None and tilt_cy is not None and abs(tilt_cy - safe_cy) > 0.03:
            cy_score = clamp(abs(pkt.face_center_y - safe_cy) / abs(tilt_cy - safe_cy), 0, 1)

        pitch_score = 0.0
        safe_pitch = d.get("safe_pitch")
        tilt_pitch = d.get("tilt_pitch")
        if pkt.pitch is not None and safe_pitch is not None and tilt_pitch is not None and abs(tilt_pitch - safe_pitch) > 5:
            pitch_score = clamp(abs(pkt.pitch - safe_pitch) / abs(tilt_pitch - safe_pitch), 0, 1)
        elif pkt.pitch is not None:
            pitch_score = self._axis_deviation(pkt.pitch, d.get("safe_pitch_low"), d.get("safe_pitch_high"), safe_pitch, 18.0)

        # Area is reliable for chair back distance, while pitch catches neck/head tilt
        # relative to the user's calibrated safe envelope without assuming Euler sign.
        weighted = 0.50 * area_score + 0.20 * cy_score + 0.30 * pitch_score
        pitch_guard = 0.68 * pitch_score
        return clamp(max(weighted, pitch_guard), 0, 1)

    def _head_risk(self, pkt, d):
        pitch_score = self._axis_deviation(
            pkt.pitch, d.get("safe_pitch_low"), d.get("safe_pitch_high"), d.get("safe_pitch"), 25.0
        )
        yaw_score = self._axis_deviation(
            pkt.yaw, d.get("safe_yaw_low"), d.get("safe_yaw_high"), d.get("safe_yaw"), 35.0
        )
        roll_score = self._axis_deviation(
            pkt.roll, d.get("safe_roll_low"), d.get("safe_roll_high"), d.get("safe_roll"), 28.0
        )
        return clamp(max(pitch_score, yaw_score * 0.85, roll_score * 0.9), 0, 1)

    def _axis_deviation(self, value, low, high, center, scale):
        if value is None:
            return 0.0

        # Use calibration-relative envelopes; Euler signs vary by camera and pose solve.
        if low is not None and high is not None:
            margin = max(7.0, 0.35 * abs(high - low) + 4.0)
            if value < low - margin:
                return clamp((low - value) / scale, 0, 1)
            if value > high + margin:
                return clamp((value - high) / scale, 0, 1)
            return 0.0

        if center is not None:
            return clamp(abs(value - center) / scale, 0, 1)
        return 0.0

    def _stillness_risk(self, pkt, d):
        if pkt.movement is None:
            return 0.15
        safe_move = d.get("safe_movement_p25") or d.get("safe_movement_p50")
        if not safe_move or safe_move <= 1e-5:
            # absolute fallback
            return 0.8 if pkt.movement < 0.0025 else 0.0

        # If current movement is far below awake movement, risk.
        ratio = pkt.movement / safe_move
        return clamp(1.0 - ratio, 0, 1)

    def _interaction_risk(self):
        if not self.interaction or not self.interaction.enabled:
            return 0.25
        s = self.interaction.seconds_since_activity()
        if s < 5:
            return 0.0
        if s > 60:
            return 1.0
        return clamp((s - 5) / 55.0, 0, 1)

    def _safe_learn(self, pkt, d):
        # Slow memory. Avoid learning drowsiness by requiring SAFE + low battery.
        alpha = 0.0015
        def upd(key, val):
            if val is None or not np.isfinite(val):
                return
            old = d.get(key)
            if old is None or not np.isfinite(old):
                d[key] = float(val)
            else:
                d[key] = float((1 - alpha) * old + alpha * val)

        upd("safe_ear_open", pkt.ear)
        upd("safe_area", pkt.face_area)
        upd("safe_pitch", pkt.pitch)
        upd("safe_center_y", pkt.face_center_y)
        self.learning_dirty = True


# -----------------------------
# Main App
# -----------------------------

class MVSAApp:
    def __init__(self, root):
        self.root = root
        self.root.title("WakeGuard Dashboard")
        self.root.attributes("-topmost", True)
        self.root.geometry("430x520+50+50")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._refuse_close)
        self.root.bind("<Control-Shift-Q>", lambda e: self.quit())

        self.config = load_or_create_config()
        self.calibration_file = Path(self.config.get("app", {}).get("calibration_file", str(CALIB_PATH_DEFAULT)))
        self.log_file = Path(self.config.get("app", {}).get("log_file", str(LOG_PATH_DEFAULT)))
        self.camera_index = int(self.config.get("app", {}).get("camera_index", 0))

        self.vision = None
        self.interaction = InteractionMonitor()
        self.interaction.start()

        self.calibration = self._load_calibration()
        self.risk_engine = RiskEngine(self.calibration, self.interaction, self.log_message)

        self.screen_backend = ScreenFlashBackend(root, self._acknowledge_from_key)
        self.findmy_backend = FindMyBackend(root, self.config, self.log_message)
        backends = []
        if self.config.get("screen_flash", {}).get("enabled", True):
            backends.append(self.screen_backend)
        backends.append(self.findmy_backend)
        self.alarms = AlarmManager(backends, self.log_message)

        self.running = False
        self.monitor_job_id = None
        self.calibrating = False
        self.calibrator = None
        self.current_stage_idx = 0
        self.stage_end_time = None

        self.last_alarm_logged = 0
        self.ack_cooldown_until = 0
        self.open_eyes_since = None
        self.face_absent_alarm_since = None

        self._build_ui()
        self._bind_acknowledgement_keys()
        self._ensure_log_header()
        self._keep_on_top()

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        ttk.Label(self.root, text=APP_NAME, font=("Arial", 16, "bold")).pack(pady=6)

        row = ttk.Frame(self.root)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="Mode:").pack(side="left")
        self.mode_var = tk.StringVar(value="Normal")
        self.mode_combo = ttk.Combobox(row, textvariable=self.mode_var, values=["Normal", "High Alert", "Super Alert"], state="readonly", width=16)
        self.mode_combo.pack(side="left", padx=8)

        self.status_var = tk.StringVar(value="IDLE")
        ttk.Label(self.root, textvariable=self.status_var, font=("Arial", 18, "bold")).pack(pady=4)

        self.battery_var = tk.DoubleVar(value=0)
        self.battery = ttk.Progressbar(self.root, variable=self.battery_var, maximum=100, length=380)
        self.battery.pack(pady=6)
        self.battery_text = tk.StringVar(value="Battery: 0")
        ttk.Label(self.root, textvariable=self.battery_text).pack()

        self.reason_var = tk.StringVar(value="Reason: none")
        ttk.Label(self.root, textvariable=self.reason_var, wraplength=390, justify="left").pack(fill="x", **pad)

        self.metrics_var = tk.StringVar(value="Metrics: none")
        ttk.Label(self.root, textvariable=self.metrics_var, wraplength=390, justify="left").pack(fill="x", **pad)

        btns = ttk.Frame(self.root)
        btns.pack(fill="x", pady=8)
        ttk.Button(btns, text="Calibrate", command=self.start_calibration).pack(side="left", padx=4)
        ttk.Button(btns, text="Start", command=self.start_monitoring).pack(side="left", padx=4)
        ttk.Button(btns, text="Stop", command=self.stop_monitoring).pack(side="left", padx=4)

        btns2 = ttk.Frame(self.root)
        btns2.pack(fill="x", pady=4)
        ttk.Button(btns2, text="ACKNOWLEDGE", command=self.acknowledge).pack(side="left", padx=4)
        ttk.Button(btns2, text="Test Flash", command=lambda: self.screen_backend.trigger("TEST", "screen flash test")).pack(side="left", padx=4)
        ttk.Button(btns2, text="Stop Flash", command=self.screen_backend.stop).pack(side="left", padx=4)

        btns3 = ttk.Frame(self.root)
        btns3.pack(fill="x", pady=4)
        ttk.Button(btns3, text="Auth FindMy", command=self.findmy_backend.authenticate_interactive).pack(side="left", padx=4)
        ttk.Button(btns3, text="Test FindMy", command=lambda: self.findmy_backend.trigger("TEST", "manual test")).pack(side="left", padx=4)

        self.log_box = tk.Text(self.root, height=10, width=52, font=("Consolas", 8))
        self.log_box.pack(padx=8, pady=6)

        ttk.Label(self.root, text="Quit: Ctrl+Shift+Q", foreground="gray").pack()

    def _refuse_close(self):
        messagebox.showinfo("WakeGuard", "WakeGuard is designed not to close accidentally.\nUse Ctrl+Shift+Q to quit.")

    def _bind_acknowledgement_keys(self):
        for sequence in ("<space>", "<Escape>", "<Control-Shift-A>", "<Control-Shift-a>"):
            self.root.bind_all(sequence, self._acknowledge_from_key)

    def _acknowledge_from_key(self, event=None):
        if self.alarms.active:
            self.acknowledge()
            return "break"
        return None

    def quit(self):
        self.stop_monitoring()
        try:
            self.screen_backend.stop()
        except Exception:
            pass
        self.root.destroy()

    def _keep_on_top(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
        except Exception:
            pass
        self.root.after(1500, self._keep_on_top)

    def log_message(self, msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line)
        try:
            self.log_box.insert("end", line + "\n")
            self.log_box.see("end")
        except Exception:
            pass

    def _ensure_log_header(self):
        if not self.log_file.exists():
            with self.log_file.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "event", "mode", "status", "battery", "risk_score", "reason", "debug_json"])

    def _write_event(self, event, result):
        with self.log_file.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                now_str(),
                event,
                self.mode_var.get(),
                result.get("status"),
                f"{result.get('battery', 0):.1f}",
                f"{result.get('risk_score', 0):.1f}",
                "; ".join(result.get("reasons", [])),
                json.dumps(result.get("debug", {}))
            ])

    def _load_calibration(self):
        if self.calibration_file.exists():
            try:
                return json.loads(self.calibration_file.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def _save_calibration(self):
        if self.calibration:
            self.calibration_file.write_text(json.dumps(self.calibration, indent=2), encoding="utf-8")

    def _ensure_vision(self):
        if self.vision is None:
            self.vision = VisionEngine(self.camera_index)
            self.vision.open()

    def start_calibration(self):
        if self.running:
            messagebox.showwarning("WakeGuard", "Stop monitoring before calibration.")
            return

        try:
            self._ensure_vision()
        except Exception as e:
            messagebox.showerror("Camera error", str(e))
            return

        self.calibrating = True
        self.calibrator = Calibrator()
        self.current_stage_idx = 0
        stage, seconds, instruction = CALIB_STAGES[0]
        self.stage_end_time = time.time() + seconds
        self.status_var.set("CALIBRATING")
        self.reason_var.set(instruction)
        self.log_message("Calibration started.")
        self._calibration_loop()

    def _calibration_loop(self):
        if not self.calibrating:
            return

        stage, seconds, instruction = CALIB_STAGES[self.current_stage_idx]
        remaining = self.stage_end_time - time.time()

        try:
            pkt, frame = self.vision.read_features()
        except Exception as e:
            self.log_message(f"Calibration camera error: {e}")
            self.calibrating = False
            return

        if remaining > 0:
            self.status_var.set(f"CALIBRATING: {stage} ({remaining:.0f}s)")
            self.reason_var.set(instruction)
            if pkt.face_present:
                self.calibrator.add_sample(stage, pkt)
            self.root.after(50, self._calibration_loop)
            return

        self.current_stage_idx += 1
        if self.current_stage_idx >= len(CALIB_STAGES):
            self.calibration = self.calibrator.build()
            self._save_calibration()
            self.risk_engine = RiskEngine(self.calibration, self.interaction, self.log_message)
            self.calibrating = False
            self.status_var.set("CALIBRATION DONE")
            self.reason_var.set(f"Saved: {self.calibration_file}")
            self.log_message("Calibration completed and saved.")
            return

        stage, seconds, instruction = CALIB_STAGES[self.current_stage_idx]
        self.stage_end_time = time.time() + seconds
        self.root.after(200, self._calibration_loop)

    def start_monitoring(self):
        if self.calibration is None:
            messagebox.showwarning("WakeGuard", "Calibrate first.")
            return
        if self.running:
            return
        try:
            self._ensure_vision()
        except Exception as e:
            messagebox.showerror("Camera error", str(e))
            return

        self.running = True
        self.open_eyes_since = None
        self.face_absent_alarm_since = None
        self.status_var.set("STARTING")
        self.log_message(f"Monitoring started. Mode={self.mode_var.get()}")
        self._monitor_loop()

    def stop_monitoring(self):
        self.running = False
        if self.monitor_job_id is not None:
            try:
                self.root.after_cancel(self.monitor_job_id)
            except Exception:
                pass
            self.monitor_job_id = None
        self.alarms.stop()
        self.screen_backend.stop()
        try:
            if self.vision:
                self.vision.close()
        except Exception as e:
            self.log_message(f"Camera close error: {e}")
        self.vision = None
        self.open_eyes_since = None
        self.face_absent_alarm_since = None
        self.status_var.set("STOPPED")
        self.log_message("Monitoring stopped.")

    def acknowledge(self):
        self.alarms.stop()
        self.risk_engine.battery = max(0, self.risk_engine.battery - 40)
        self.ack_cooldown_until = time.time() + 10
        self.open_eyes_since = None
        self.face_absent_alarm_since = None
        result = {
            "status": "ACK",
            "battery": self.risk_engine.battery,
            "risk_score": 0,
            "reasons": ["manual acknowledge"],
            "debug": {}
        }
        self._write_event("ACK", result)
        self.log_message("Acknowledged. Short cooldown active.")

    def _auto_clear_alarm_if_awake(self, pkt, result):
        if not self.alarms.active:
            self.open_eyes_since = None
            self.face_absent_alarm_since = None
            return

        now = time.time()
        debug = result.get("debug", {})
        eye_ratio = debug.get("eye_ratio")
        tilt_risk = debug.get("tilt_risk", 0) or 0
        cfg = MODE_CONFIGS[self.mode_var.get()]
        hard_tilt_active = bool(cfg.get("tilt_hard_alarm") and tilt_risk > 0.60)

        if not pkt.face_present:
            self.open_eyes_since = None
            if self.face_absent_alarm_since is None:
                self.face_absent_alarm_since = now
            if now - self.face_absent_alarm_since >= 3.0:
                self.alarms.stop()
                self.ack_cooldown_until = now + 5
                away_result = dict(result)
                away_result["reasons"] = ["face absent during alarm"]
                self._write_event("AUTO_STOP_FACE_ABSENT", away_result)
                self.log_message("Alarm flash stopped: face absent for 3.0s.")
            return

        self.face_absent_alarm_since = None
        clearly_open = eye_ratio is not None and eye_ratio >= 0.75
        if clearly_open and not hard_tilt_active:
            if self.open_eyes_since is None:
                self.open_eyes_since = now
            if now - self.open_eyes_since >= 3.0:
                self.alarms.stop()
                self.ack_cooldown_until = now + 5
                auto_result = dict(result)
                auto_result["status"] = "ACK"
                auto_result["reasons"] = ["open eyes visible for 3.0s"]
                self._write_event("AUTO_ACK_OPEN_EYES", auto_result)
                self.log_message("Auto-acknowledged: open eyes visible for 3.0s.")
        else:
            self.open_eyes_since = None

    def _monitor_loop(self):
        self.monitor_job_id = None
        if not self.running:
            return

        try:
            pkt, frame = self.vision.read_features()
            result = self.risk_engine.update(pkt, self.mode_var.get())
            status = result["status"]
            battery = result["battery"]
            risk_score = result["risk_score"]
            reasons = result["reasons"]
            debug = result["debug"]

            self.status_var.set(status)
            self.battery_var.set(battery)
            self.battery_text.set(f"Battery: {battery:.0f} / 100    Risk score: {risk_score:.0f}")
            self.reason_var.set("Reason: " + "; ".join(reasons))
            self.metrics_var.set(
                f"eye={debug.get('eye_risk', 0):.2f} "
                f"tilt={debug.get('tilt_risk', 0):.2f} "
                f"head={debug.get('head_risk', 0):.2f} "
                f"pitch={self._fmt_metric(debug.get('pitch'))} "
                f"yaw={self._fmt_metric(debug.get('yaw'))} "
                f"roll={self._fmt_metric(debug.get('roll'))} "
                f"still={debug.get('stillness_risk', 0):.2f} "
                f"input={debug.get('interaction_risk', 0):.2f} "
                f"eyeClosed={debug.get('eye_closed_timer', 0):.1f}s"
            )

            self._auto_clear_alarm_if_awake(pkt, result)

            # Alarm behavior. After acknowledge, allow flash to stop briefly but still monitor.
            if result["alarm"] and time.time() > self.ack_cooldown_until:
                self.alarms.trigger("ALARM", "; ".join(reasons))
                if time.time() - self.last_alarm_logged > 5:
                    self._write_event("ALARM", result)
                    self.last_alarm_logged = time.time()
            elif result["warning"]:
                if time.time() - self.last_alarm_logged > 30:
                    self._write_event("WARNING", result)
                    self.last_alarm_logged = time.time()
            else:
                if self.alarms.active and battery < 35:
                    self.alarms.stop()

            # Save online learning occasionally.
            if self.risk_engine.learning_dirty and time.time() - self.risk_engine.last_save > 120:
                self._save_calibration()
                self.risk_engine.learning_dirty = False
                self.risk_engine.last_save = time.time()
                self.log_message("Safe baseline updated.")

        except Exception as e:
            self.log_message("Monitor error: " + str(e))
            self.log_message(traceback.format_exc())

        if self.running:
            self.monitor_job_id = self.root.after(50, self._monitor_loop)

    def _fmt_metric(self, value):
        if value is None:
            return "n/a"
        try:
            return f"{float(value):.1f}"
        except Exception:
            return "n/a"


def main():
    root = tk.Tk()
    app = MVSAApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
