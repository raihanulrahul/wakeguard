"""Dependency-free observations, calibration math and private persistence."""
from __future__ import annotations
import json
import math
import os
import statistics as st
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from .face_context import valid_shape, shape_distance, neck_projection

SCHEMA = 2


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def finite(x: Any) -> bool:
    return isinstance(x, (float, int)) and math.isfinite(x)


def angle_delta(x: float, y: float) -> float:
    return (x - y + 180.0) % 360.0 - 180.0


def median(xs: list[float]) -> float:
    return float(st.median(xs))


def robust_spread(xs: list[float], floor: float = .001) -> float:
    m = median(xs)
    return max(floor, 1.4826 * median([abs(x - m) for x in xs]))


@dataclass
class Observation:
    t: float
    seq: int = 0
    camera_ok: bool = True
    face: bool = False
    body: bool | None = None
    left: float | None = None
    right: float | None = None
    left_q: float = 0.0
    right_q: float = 0.0
    pitch: float | None = None
    yaw: float | None = None
    roll: float | None = None
    area: float | None = None
    cx: float | None = None
    cy: float | None = None
    brightness: float = 0.0
    sharpness: float = 0.0
    scene: list[float] = field(default_factory=list)
    camera_key: str = ""
    error: str = ""
    diagnostics: dict = field(default_factory=dict)
    shape: list[float] = field(default_factory=list)
    eyewear: list[float] = field(default_factory=list)
    body_activity: float | None = None
    hand_activity: float | None = None

    @classmethod
    def from_dict(cls, data: dict) -> Observation:
        result = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        if not finite(result.t):
            raise ValueError("Invalid camera timestamp")
        for name in ("left", "right", "pitch", "yaw", "roll", "area", "cx", "cy", "body_activity", "hand_activity"):
            if not finite(getattr(result, name)):
                setattr(result, name, None)
        for name in ("left_q", "right_q", "brightness", "sharpness"):
            if not finite(getattr(result, name)):
                setattr(result, name, 0.0)
        if not isinstance(result.scene, list) or not all(finite(x) for x in result.scene):
            result.scene = []
        if not valid_shape(result.shape):
            result.shape = []
        from .glasses import valid_descriptor
        if not valid_descriptor(result.eyewear):
            result.eyewear = []
        for name in ("body_activity", "hand_activity"):
            value = getattr(result, name)
            if value is not None and (not finite(value) or value < 0 or value > 10):
                setattr(result, name, None)
        if not isinstance(result.diagnostics, dict):
            result.diagnostics = {}
        result.diagnostics = {str(k)[:40]: v for k, v in result.diagnostics.items()
                              if isinstance(v, str) and len(v) <= 160 or finite(v)}
        return result

    def valid_eye(self, side: str) -> bool:
        value = getattr(self, side)
        return (self.camera_ok and self.face and finite(value)
                and 0.0 <= value <= .7 and getattr(self, side + "_q") >= .55)

    def geometry_valid(self) -> bool:
        return (self.face and self.camera_ok
                and all(finite(getattr(self, k)) for k in ("area", "cx", "cy"))
                and 0 < self.area < 1.5)

    def context_valid(self) -> bool:
        return self.geometry_valid() and (valid_shape(self.shape) or self.pose_valid())

    def pose_valid(self) -> bool:
        return (self.face and self.camera_ok
                and all(finite(getattr(self, k)) for k in ("pitch", "yaw", "roll", "area", "cy"))
                and self.area > 0)


def data_home() -> Path:
    override = os.environ.get("WAKEGUARD_DATA_DIR")
    if override:
        path = Path(override).expanduser().resolve()
    elif os.name == "nt":
        path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "WakeGuard"
    else:
        path = Path.home() / ".local" / "share" / "wakeguard"
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, indent=2, allow_nan=False)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(encoded)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def scene_distance(a: list[float], b: list[float]) -> float:
    if not a or len(a) != len(b):
        return float("inf")
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


@dataclass
class Profile:
    schema: int
    camera_key: str
    created_at: str
    open_views: list[dict]
    closed_views: list[dict]
    neutral: dict
    reclined: dict
    neck_down: dict
    neck_up: dict
    empty_scene: list[float]
    empty_tolerance: float
    brightness: float
    report: dict

    def save(self, path: Path) -> None:
        self.validate()
        atomic_json(path, asdict(self))

    @classmethod
    def load(cls, path: Path) -> Profile:
        obj = cls(**json.loads(path.read_text(encoding="utf-8")))
        obj.validate()
        return obj

    def validate(self) -> None:
        if self.schema != SCHEMA or not self.camera_key or not self.open_views or not self.closed_views:
            raise ValueError("Calibration is old/incomplete; run guided calibration")
        if not isinstance(self.report, dict) or not self.report.get("valid"):
            raise ValueError("Calibration has not passed quality checks")
        relative = self.report.get("context_method") == "face-relative-v1"
        if not isinstance(self.report.get("channels", {}), dict):
            raise ValueError("Invalid channel availability record")
        masks = self.report.get("view_masks", [])
        if not isinstance(masks, list) or any(not isinstance(v, dict) or not valid_shape(v.get("shape"))
                or not isinstance(v.get("sides"), list) or not v["sides"]
                or any(side not in ("left", "right") for side in v["sides"]) for v in masks):
            raise ValueError("Invalid eye-view support mask")
        for view in self.open_views + self.closed_views:
            if not isinstance(view, dict) or not (
                    valid_shape(view.get("shape")) if relative else
                    all(finite(view.get(k)) for k in ("pitch", "yaw", "roll"))):
                raise ValueError("Invalid eye-view reference")
        glasses = self.report.get("glasses", {})
        if glasses:
            if not isinstance(glasses, dict) or not isinstance(glasses.get("enabled", False), bool):
                raise ValueError("Invalid glasses calibration record")
            if glasses.get("enabled"):
                on_open = glasses.get("open_views", [])
                on_closed = glasses.get("closed_views", [])
                on_masks = glasses.get("view_masks", [])
                if glasses.get("eye_supported") and (not on_open or not on_closed):
                    raise ValueError("Glasses-on eye references are incomplete")
                if any(not isinstance(v, dict) or not valid_shape(v.get("shape")) for v in on_open + on_closed):
                    raise ValueError("Invalid glasses-on eye reference")
                if any(not isinstance(v, dict) or not valid_shape(v.get("shape"))
                       or not isinstance(v.get("sides"), list) or not v["sides"]
                       or any(side not in ("left", "right") for side in v["sides"]) for v in on_masks):
                    raise ValueError("Invalid glasses-on view mask")
                from .glasses import valid_descriptor
                pairs = glasses.get("pairs", [])
                if not isinstance(pairs, list):
                    raise ValueError("Invalid glasses classifier pairs")
                for pair in pairs:
                    if not isinstance(pair, dict) or not valid_shape(pair.get("shape")):
                        raise ValueError("Invalid glasses classifier context")
                    for name in ("off", "on"):
                        proto = pair.get(name)
                        if proto is None:
                            continue
                        if not isinstance(proto, dict) or not valid_descriptor(proto.get("features")) or not valid_descriptor(proto.get("spread")):
                            raise ValueError("Invalid glasses classifier prototype")
        for name, pose in (("neutral", self.neutral), ("recline", self.reclined),
                           ("neck_down", self.neck_down), ("neck_up", self.neck_up)):
            if relative and name != "neutral" and not self.report.get("channels", {}).get(name, True):
                continue
            required = ("area", "cx", "cy") if relative else ("pitch", "yaw", "roll", "area", "cy")
            if not isinstance(pose, dict) or not all(finite(pose.get(k)) for k in required) or pose["area"] <= 0:
                raise ValueError("Invalid posture reference")
        if self.report.get("auto_away_enabled", True) and (
                not self.empty_scene or not all(finite(v) for v in self.empty_scene)):
            raise ValueError("Missing empty-chair reference")
        for view in self.open_views:
            usable = 0
            for side in ("left", "right"):
                if not finite(view.get(side)):
                    continue
                choices = [c for c in self.closed_views if finite(c.get(side))]
                if not choices:
                    continue
                ref = min(choices, key=lambda c: self.view_distance(view, c))
                if view[side] - ref[side] < .035:
                    raise ValueError("Stored eye calibration is inverted/overlapping")
                usable += 1
            if not usable:
                raise ValueError("Stored view has no usable eye")
        if not finite(self.empty_tolerance) or not .001 <= self.empty_tolerance <= .08:
            raise ValueError("Invalid empty-chair tolerance")
        if not finite(self.brightness):
            raise ValueError("Invalid light reference")

    @staticmethod
    def view_distance(a: dict, b: dict) -> float:
        # Scale only to retain existing context-distance thresholds. This is NOT degrees.
        if valid_shape(a.get("shape")) or valid_shape(b.get("shape")):
            return 10 * shape_distance(a.get("shape"), b.get("shape"))
        if not all(finite(v.get(k)) for v in (a, b) for k in ("yaw", "pitch", "roll")):
            return float("inf")
        return math.hypot(angle_delta(a["yaw"], b["yaw"]), angle_delta(a["pitch"], b["pitch"])) + .3 * abs(angle_delta(a["roll"], b["roll"]))

    @staticmethod
    def _pose_distance(o: Observation, view: dict) -> float:
        if not o.context_valid():
            return float("inf")
        return Profile.view_distance({"shape": o.shape, "pitch": o.pitch, "yaw": o.yaw, "roll": o.roll}, view)

    def glasses_info(self) -> dict:
        value = self.report.get("glasses", {})
        return value if isinstance(value, dict) else {}

    def classify_glasses(self, o: Observation) -> tuple[str, float]:
        """Personalized glasses state. Uncertain is preferred over guessing."""
        info = self.glasses_info()
        if not info.get("enabled"):
            return "off", 1.0
        from .glasses import classify_descriptor
        pairs = info.get("pairs", [])
        if not pairs or not valid_shape(o.shape):
            return "uncertain", 0.0
        usable = [p for p in pairs if isinstance(p, dict) and valid_shape(p.get("shape"))]
        if not usable:
            return "uncertain", 0.0
        pair = min(usable, key=lambda p: shape_distance(o.shape, p["shape"]))
        if shape_distance(o.shape, pair["shape"]) > 3.5:
            return "uncertain", 0.0
        state, confidence, _, _ = classify_descriptor(o.eyewear, pair)
        return state, confidence

    def _eye_ratios_from(self, o: Observation, open_views: list[dict], closed_views: list[dict],
                         masks: list[dict], adaptation: dict | None = None) -> list[float]:
        ratios = []
        allowed = ("left", "right")
        if masks:
            mask = min(masks, key=lambda v: self._pose_distance(o, v))
            if self._pose_distance(o, mask) > 32:
                return ratios
            allowed = mask["sides"]
        for side in ("left", "right"):
            if side not in allowed or not o.valid_eye(side):
                continue
            opens = [v for v in open_views if finite(v.get(side))]
            closes = [v for v in closed_views if finite(v.get(side))]
            if not opens or not closes:
                continue
            op = min(opens, key=lambda v: self._pose_distance(o, v))
            cl = min(closes, key=lambda v: self._pose_distance(o, v))
            if self._pose_distance(o, op) > 32 or self._pose_distance(o, cl) > 48:
                continue
            baseline = op[side] * (1 + clamp((adaptation or {}).get(side, 0), 0, .05))
            gap = baseline - cl[side]
            if gap >= .035:
                ratios.append(clamp((getattr(o, side) - cl[side]) / gap, 0, 1.5))
        return ratios

    def eye_ratios(self, o: Observation, adaptation: dict | None = None, glasses_state: str | None = None) -> list[float]:
        if not self.report.get("reclined_eyes_valid", True) and (self.recline(o) or 0) >= .60:
            return []
        info = self.glasses_info()
        if glasses_state == "uncertain":
            return []
        if glasses_state == "on" and info.get("enabled"):
            return self._eye_ratios_from(o, info.get("open_views", []), info.get("closed_views", []),
                                         info.get("view_masks", []), adaptation)
        return self._eye_ratios_from(o, self.open_views, self.closed_views, self.report.get("view_masks", []), adaptation)

    def partial_limit(self, o: Observation) -> float:
        key = "reclined" if (self.recline(o) or 0) >= .5 else "upright"
        value = self.report.get("half_thresholds", {}).get(key, .60)
        return clamp(value, .60, .80) if finite(value) else .60

    def recline(self, o: Observation) -> float | None:
        if not self.report.get("channels", {}).get("recline", True) or not o.geometry_valid():
            return None
        # Directional projection; neck pitch is deliberately NOT chair tilt.
        n, r = self.neutral, self.reclined
        axis = [(math.log(r["area"]) - math.log(n["area"])) / .15, (r["cy"] - n["cy"]) / .04]
        reference = n
        if self.report.get("context_method") == "face-relative-v1" and valid_shape(o.shape):
            # Turning toward a side monitor shrinks projected face size too.
            # Compare with that NORMAL screen view, not only front-facing size.
            def horizontal_distance(view):
                v = view["shape"]
                return math.hypot((o.shape[0]-v[0])/.12, (o.shape[3]-v[3])/.40)
            views = [v for v in self.report.get("normal_views", []) if valid_shape(v.get("shape"))
                     and finite(v.get("area")) and v["area"]>0 and finite(v.get("cy"))]
            if views:
                reference = min(views, key=horizontal_distance)
                if horizontal_distance(reference)>2:
                    return None
        point = [(math.log(o.area) - math.log(reference["area"])) / .15, (o.cy - reference["cy"]) / .04]
        norm = sum(x * x for x in axis)
        if norm < 1:
            return None
        return clamp(sum(a * b for a, b in zip(axis, point)) / norm)

    def neck(self, o: Observation, direction: str = "down") -> float | None:
        if not self.report.get("channels", {}).get("neck_" + direction, True):
            return None
        target = self.neck_down if direction == "down" else self.neck_up
        if self.report.get("context_method") == "face-relative-v1":
            if not o.geometry_valid():
                return None
            return neck_projection(o.shape, self.neutral, target, self.report.get("normal_views", []))
        if not o.pose_valid():
            return None
        delta = angle_delta(target["pitch"], self.neutral["pitch"])
        if abs(delta) < 8:
            return None
        return clamp(angle_delta(o.pitch, self.neutral["pitch"]) / delta)

    def empty_match(self, o: Observation) -> bool:
        return (self.report.get("auto_away_enabled", True) and o.camera_ok
                and not o.face and o.body is False
                and scene_distance(o.scene, self.empty_scene) <= self.empty_tolerance)
