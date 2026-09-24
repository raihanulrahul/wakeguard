"""Guided calibration: labelled samples, quality gates, immutable profiles."""
from __future__ import annotations
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from .model import Observation, Profile, SCHEMA, angle_delta, finite, median, robust_spread, scene_distance


@dataclass(frozen=True)
class Stage:
    key: str
    seconds: float
    instruction: str
    eyes: str = "open"
    allow_blind: bool = False


STAGES = (
    Stage("main", 10, "Sit upright in your normal working position. Look at your main work monitor, NOT the camera."),
    Stage("monitors", 12, "Read and look between your usual monitors. Keep eyes normally open and move naturally."),
    Stage("left", 8, "Turn your body slightly left as you might while working. Keep eyes open."),
    Stage("right", 8, "Turn your body slightly right as you might while working. Keep eyes open."),
    Stage("reading", 8, "Look a little down as when reading a document. Stay in an ordinary awake posture."),
    Stage("neck_down", 6, "Keep the CHAIR upright. Lower your CHIN partway toward your chest, eyes open and face still visible to the camera. This labels neck drop.", allow_blind=True),
    Stage("neck_up", 6, "Keep the CHAIR upright. Tilt only your HEAD back a little, eyes open. Do not force your neck.", allow_blind=True),
    Stage("reclined", 8, "Fully recline the chair, eyes normally open. Look in your usual work direction.", allow_blind=True),
    Stage("half_reclined", 5, "Remain reclined. During capture gently half-close your eyelids, staying awake.", "half", True),
    Stage("half_upright", 5, "Return upright. During capture gently half-close your eyelids, staying awake.", "half"),
    Stage("closed_main", 3, "Sit upright facing your main monitor. Briefly close your eyes only when you hear Begin. I will tell you to open them.", "closed"),
    Stage("closed_reclined", 3, "Recline. Briefly close your eyes only when you hear Begin. I will tell you to open them.", "closed", True),
    Stage("closed_left", 3, "Sit upright, slightly turned left. Briefly close your eyes only when you hear Begin.", "closed"),
    Stage("closed_right", 3, "Sit upright, slightly turned right. Briefly close your eyes only when you hear Begin.", "closed"),
    Stage("empty", 12, "After Begin, leave your chair and move fully out of camera view. Wait for the completion message before returning.", "absent"),
)


class CalibrationError(ValueError):
    pass


def summarize(samples: list[Observation]) -> dict:
    result = {"n": len(samples)}
    for name in ("left", "right", "area", "cx", "cy", "brightness", "pitch", "yaw", "roll"):
        xs = [getattr(o, name) for o in samples if finite(getattr(o, name))]
        if name in ("left", "right"):
            xs = [getattr(o, name) for o in samples if o.valid_eye(name)]
            result[name + "_n"] = len(xs)
            if len(xs) < max(5, len(samples) * .55):
                xs = []
        if xs and name in ("pitch", "yaw", "roll"):
            origin = xs[0]
            xs = [origin + angle_delta(x, origin) for x in xs]
        result[name] = median(xs) if xs else None
        result[name + "_spread"] = robust_spread(xs) if xs else None
    return result


def view_clusters(samples: list[Observation]) -> list[dict]:
    buckets: dict[tuple[int, int], list[Observation]] = {}
    for o in samples:
        if o.pose_valid():
            key = (round(o.yaw / 12), round(o.pitch / 12))
            buckets.setdefault(key, []).append(o)
    views = [summarize(xs) for xs in buckets.values() if len(xs) >= 8]
    return [v for v in views if finite(v.get("left")) or finite(v.get("right"))]


class CalibrationSession:
    """UI owns prompts; this object accepts data only while RECORDING."""
    def __init__(self) -> None:
        self.index = 0
        self.samples: dict[str, list[Observation]] = {}
        self.current: list[Observation] = []
        self.started: float | None = None
        self.last_t: float | None = None
        self.last_seq: int | None = None
        self.valid_seconds = 0.0
        self.total_frames = 0
        self.recording = False

    @property
    def stage(self) -> Stage:
        return STAGES[self.index]

    def begin(self, now: float) -> None:
        self.current = []
        self.started = now
        self.last_t = None
        self.last_seq = None
        self.valid_seconds = 0
        self.total_frames = 0
        self.recording = True

    def add(self, o: Observation, now: float) -> None:
        if not self.recording or o.seq == self.last_seq or not 0 <= now - o.t <= .7:
            return
        self.last_seq = o.seq
        dt = min(.25, max(0.0, o.t - self.last_t)) if self.last_t is not None else 0.0
        self.last_t = o.t
        self.total_frames += 1
        if self.stage.eyes == "absent":
            good = o.camera_ok and not o.face and o.body is False and bool(o.scene)
        else:
            good = o.pose_valid() and (self.stage.allow_blind or o.valid_eye("left") or o.valid_eye("right"))
        if good:
            self.current.append(o)
            self.valid_seconds += dt

    def due(self, now: float) -> bool:
        return self.recording and self.started is not None and now - self.started >= self.stage.seconds

    def finish(self) -> None:
        self.recording = False
        required = max(8, int(self.stage.seconds * 4))
        if (len(self.current) < required or self.valid_seconds < self.stage.seconds * .65
                or len(self.current) < self.total_frames * .65):
            raise CalibrationError(f"{self.stage.key}: only {len(self.current)} usable frames / {self.valid_seconds:.1f}s. Adjust camera or lighting and repeat this stage.")
        self.samples[self.stage.key] = list(self.current)

    def advance(self) -> bool:
        if self.index + 1 >= len(STAGES):
            return False
        self.index += 1
        return True

    def repeat_previous(self) -> None:
        self.index = max(0, self.index - 1)
        self.recording = False

    def build(self) -> Profile:
        missing = [s.key for s in STAGES if s.key not in self.samples]
        if missing:
            raise CalibrationError("Missing stages: " + ", ".join(missing))
        reports = {k: summarize(v) for k, v in self.samples.items()}
        camera_keys = {o.camera_key for values in self.samples.values() for o in values}
        if len(camera_keys) != 1 or not next(iter(camera_keys)):
            raise CalibrationError("Camera/resolution changed during calibration; start again")
        opens = [o for s in STAGES if s.eyes == "open" for o in self.samples[s.key]]
        closes = [o for s in STAGES if s.eyes == "closed" for o in self.samples[s.key]]
        ov, cv = view_clusters(opens), view_clusters(closes)
        if not ov or not cv:
            raise CalibrationError("Insufficient stable open/closed views")
        reclined_eyes_valid = True
        for op_name, cl_name in (("main", "closed_main"), ("reclined", "closed_reclined"), ("left", "closed_left"), ("right", "closed_right")):
            op, cl = reports[op_name], reports[cl_name]
            if any(abs(angle_delta(op[k], cl[k])) > 20 for k in ("pitch", "yaw", "roll")):
                raise CalibrationError(f"{op_name}/{cl_name}: posture changed between open and closed samples. Repeat at the SAME angle.")
            usable = 0
            for side in ("left", "right"):
                if op[side] is None or cl[side] is None:
                    continue
                gap = op[side] - cl[side]
                noise = max(op[side + "_spread"], cl[side + "_spread"])
                if gap < max(.035, 3 * noise):
                    raise CalibrationError(f"{op_name}/{cl_name}: {side} samples overlap or are reversed. Repeat these stages.")
                usable += 1
            if not usable:
                if op_name == "reclined":
                    reclined_eyes_valid = False
                else:
                    raise CalibrationError(f"No reliable eye in {op_name}; re-aim the camera")
        half_thresholds = {}
        for half_name, op_name, cl_name in (("half_upright", "main", "closed_main"), ("half_reclined", "reclined", "closed_reclined")):
            half, op, cl = reports[half_name], reports[op_name], reports[cl_name]
            if half_name == "half_reclined" and not reclined_eyes_valid:
                continue
            ratios = [(half[s] - cl[s]) / (op[s] - cl[s]) for s in ("left", "right")
                      if all(x[s] is not None for x in (half, op, cl)) and op[s] - cl[s] >= .035]
            if not ratios and half_name == "half_reclined":
                reclined_eyes_valid = False
                continue
            if not ratios or not .12 < min(ratios) < .80:
                raise CalibrationError(f"{half_name}: half-closed state not distinct. Repeat with gently lowered eyelids.")
            half_thresholds["reclined" if half_name == "half_reclined" else "upright"] = min(.80, max(.60, min(ratios) + .08))
        neutral, reclined = reports["main"], reports["reclined"]
        separation = math.hypot(math.log(reclined["area"] / neutral["area"]) / .15, (reclined["cy"] - neutral["cy"]) / .04)
        if separation < 1:
            raise CalibrationError("Upright/reclined geometry is not separable; re-aim camera or repeat recline")
        for name in ("neck_down", "neck_up"):
            if abs(angle_delta(reports[name]["pitch"], neutral["pitch"])) < 8:
                raise CalibrationError(f"{name}: pitch changed less than 8 degrees; check preview and repeat")
        down_delta = angle_delta(reports["neck_down"]["pitch"], neutral["pitch"])
        up_delta = angle_delta(reports["neck_up"]["pitch"], neutral["pitch"])
        if down_delta * up_delta >= 0:
            raise CalibrationError("Neck-up and neck-down mapped to the SAME direction. Repeat labelled neck stages.")
        empty = self.samples["empty"]
        length = len(empty[0].scene)
        if not length or any(len(o.scene) != length for o in empty):
            raise CalibrationError("Invalid empty-chair samples")
        signature = [median([o.scene[i] for o in empty]) for i in range(length)]
        distances = [scene_distance(o.scene, signature) for o in empty]
        tolerance = min(.045, max(.008, max(distances) * 1.5 + .005))
        occupied_distance = median([scene_distance(o.scene, signature) for o in self.samples["main"]])
        automatic_away = occupied_distance > tolerance * 1.6
        report = {"valid": True, "stages": reports, "reclined_eyes_valid": reclined_eyes_valid,
                  "auto_away_enabled": automatic_away, "recline_separation": separation, "half_thresholds": half_thresholds,
                  "neck_down_delta": down_delta, "neck_up_delta": up_delta,
                  "occupied_empty_separation": occupied_distance,
                  "notes": "Heuristic calibration; not a sleep diagnosis."}
        result = Profile(SCHEMA, next(iter(camera_keys)), datetime.now(timezone.utc).isoformat(), ov, cv,
                         neutral, reclined, reports["neck_down"], reports["neck_up"], signature,
                         tolerance, median([o.brightness for o in opens]), report)
        result.validate()
        return result
