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

    @classmethod
    def from_dict(cls, data: dict) -> Observation:
        result = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        if not finite(result.t):
            raise ValueError("Invalid camera timestamp")
        for name in ("left", "right", "pitch", "yaw", "roll", "area", "cx", "cy"):
            if not finite(getattr(result, name)):
                setattr(result, name, None)
        for name in ("left_q", "right_q", "brightness", "sharpness"):
            if not finite(getattr(result, name)):
                setattr(result, name, 0.0)
        if not isinstance(result.scene, list) or not all(finite(x) for x in result.scene):
            result.scene = []
        return result

    def valid_eye(self, side: str) -> bool:
        value = getattr(self, side)
        return (self.camera_ok and self.face and finite(value)
                and 0.0 <= value <= .7 and getattr(self, side + "_q") >= .55)

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
        for view in self.open_views + self.closed_views:
            if not isinstance(view, dict) or not all(finite(view.get(k)) for k in ("pitch", "yaw", "roll")):
                raise ValueError("Invalid pose reference")
        for pose in (self.neutral, self.reclined, self.neck_down, self.neck_up):
            if not isinstance(pose, dict) or not all(finite(pose.get(k)) for k in ("pitch", "yaw", "roll", "area", "cy")) or pose["area"] <= 0:
                raise ValueError("Invalid posture reference")
        if not self.empty_scene or not all(finite(v) for v in self.empty_scene):
            raise ValueError("Missing empty-chair reference")
        for view in self.open_views:
            usable = 0
            for side in ("left", "right"):
                if not finite(view.get(side)):
                    continue
                choices = [c for c in self.closed_views if finite(c.get(side))]
                if not choices:
                    continue
                ref = min(choices, key=lambda c: abs(angle_delta(view["pitch"], c["pitch"])) + abs(angle_delta(view["yaw"], c["yaw"])))
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
    def _pose_distance(o: Observation, view: dict) -> float:
        if not o.pose_valid():
            return float("inf")
        return math.hypot(angle_delta(o.yaw, view["yaw"]), angle_delta(o.pitch, view["pitch"])) + .3 * abs(angle_delta(o.roll, view["roll"]))

    def eye_ratios(self, o: Observation, adaptation: dict | None = None) -> list[float]:
        ratios = []
        if not self.report.get("reclined_eyes_valid", True) and (self.recline(o) or 0) >= .60:
            return ratios
        for side in ("left", "right"):
            if not o.valid_eye(side):
                continue
            opens = [v for v in self.open_views if finite(v.get(side))]
            closes = [v for v in self.closed_views if finite(v.get(side))]
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

    def partial_limit(self, o: Observation) -> float:
        key = "reclined" if (self.recline(o) or 0) >= .5 else "upright"
        value = self.report.get("half_thresholds", {}).get(key, .60)
        return clamp(value, .60, .80) if finite(value) else .60

    def recline(self, o: Observation) -> float | None:
        if not o.pose_valid():
            return None
        # Directional projection; neck pitch is deliberately NOT chair tilt.
        n, r = self.neutral, self.reclined
        axis = [(math.log(r["area"]) - math.log(n["area"])) / .15, (r["cy"] - n["cy"]) / .04]
        point = [(math.log(o.area) - math.log(n["area"])) / .15, (o.cy - n["cy"]) / .04]
        norm = sum(x * x for x in axis)
        if norm < 1:
            return None
        return clamp(sum(a * b for a, b in zip(axis, point)) / norm)

    def neck(self, o: Observation, direction: str = "down") -> float | None:
        if not o.pose_valid():
            return None
        target = self.neck_down if direction == "down" else self.neck_up
        delta = angle_delta(target["pitch"], self.neutral["pitch"])
        if abs(delta) < 8:
            return None
        return clamp(angle_delta(o.pitch, self.neutral["pitch"]) / delta)

    def empty_match(self, o: Observation) -> bool:
        return (self.report.get("auto_away_enabled", True) and o.camera_ok
                and not o.face and o.body is False
                and scene_distance(o.scene, self.empty_scene) <= self.empty_tolerance)
