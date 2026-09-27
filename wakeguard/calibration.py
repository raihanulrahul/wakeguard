"""Guided calibration: labelled samples, quality gates, immutable profiles."""
from __future__ import annotations
import math
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from .model import Observation, Profile, SCHEMA, angle_delta, finite, median, robust_spread, scene_distance


@dataclass(frozen=True)
class Stage:
    key: str
    seconds: float
    instruction: str
    eyes: str = "open"
    allow_blind: bool = False

    @property
    def time_limit(self) -> float:
        # Never extend an eye-closed/half-closed exposure to chase good frames.
        return self.seconds if self.eyes in ("closed", "half") else min(36.0, self.seconds * 3)

    @property
    def completion_cue(self) -> str:
        if self.eyes in ("closed", "half"):
            return "Open your eyes."
        if self.eyes == "absent":
            return "You may return to your chair."
        return "Capture complete."


STAGES = (
    Stage("main", 10, "Sit upright in your normal working position. Look at your main work monitor, NOT the camera."),
    Stage("monitors", 8, "Read normally on this ONE screen. Keep your usual working posture and eyes open. Do not sweep between screens during capture."),
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


def measurement_issue(o: Observation, now: float, stage: Stage) -> str:
    """First blocking quality gate; no images or raw video are logged."""
    if not o.camera_ok:
        return "camera read failed or frozen"
    if not 0 <= now - o.t <= .7:
        return "camera measurements arriving too late"
    if stage.eyes == "absent":
        if o.face or o.body is not False:
            return "a person is still detected in the empty-chair sample"
        return "" if o.scene else "empty-scene measurement unavailable"
    if not o.face:
        return "face not detected at this position"
    if not o.pose_valid():
        reason = o.diagnostics.get("pose_reason", "")
        return "head pose unavailable" + (": " + reason if reason else "")
    if not stage.allow_blind and not (o.valid_eye("left") or o.valid_eye("right")):
        details = []
        for side in ("left", "right"):
            reason = o.diagnostics.get(side + "_reason", "")
            if reason:
                details.append(side + " " + reason)
        return "eyes not measurable" + (": " + "; ".join(details) if details else "")
    return ""


class CalibrationSession:
    """Labelled capture with bounded recovery time and per-screen coverage."""
    def __init__(self, monitor_count: int = 1) -> None:
        if isinstance(monitor_count, bool) or monitor_count not in (1, 2, 3):
            raise ValueError("Screens used must be 1, 2 or 3")
        self.index = 0
        self.monitor_count = monitor_count
        self.monitor_index = 0
        self.monitor_samples: dict[int, list[Observation]] = {}
        self.samples: dict[str, list[Observation]] = {}
        self.capture_reports: dict[str, dict] = {}
        self.current: list[Observation] = []
        self.started: float | None = None
        self.last_t: float | None = None
        self.last_seq: int | None = None
        self.last_good = False
        self.valid_seconds = 0.0
        self.total_frames = 0
        self.rejected: Counter = Counter()
        self.blocker_examples: dict[str, str] = {}
        self.latest_issue = ""
        self.final_issue = ""
        self.recording = False

    @property
    def stage(self) -> Stage:
        base = STAGES[self.index]
        if base.key == "monitors":
            name = ("MAIN work screen", "SECOND work screen", "THIRD work screen")[self.monitor_index]
            return replace(base, instruction=f"Screen {self.monitor_index + 1} of {self.monitor_count}. "
                           f"Look at your {name}. " + base.instruction)
        return base

    @property
    def label(self) -> str:
        label = f"Step {self.index + 1}/{len(STAGES)}"
        if self.stage.key == "monitors":
            label += f" · screen {self.monitor_index + 1}/{self.monitor_count}"
        return label

    @property
    def required_seconds(self) -> float:
        return self.stage.seconds * .65

    @property
    def required_frames(self) -> int:
        return max(8, int(self.stage.seconds * 4))

    @property
    def quality_met(self) -> bool:
        return (len(self.current) >= self.required_frames
                and self.valid_seconds + 1e-7 >= self.required_seconds
                and len(self.current) >= self.total_frames * .65)

    def begin(self, now: float) -> None:
        self.current = []
        self.started = now
        self.last_t = None
        self.last_seq = None
        self.last_good = False
        self.valid_seconds = 0
        self.total_frames = 0
        self.rejected.clear()
        self.blocker_examples.clear()
        self.latest_issue = ""
        self.final_issue = ""
        self.recording = True

    def cancel_capture(self) -> None:
        # Keep previously accepted stages/views; throw away the unfinished take.
        self.recording = False
        self.current = []
        self.started = None
        self.last_t = None
        self.last_seq = None
        self.last_good = False
        self.valid_seconds = 0.0
        self.total_frames = 0
        self.rejected.clear()
        self.blocker_examples.clear()
        self.latest_issue = ""
        self.final_issue = ""

    def add(self, o: Observation, now: float) -> None:
        if not self.recording or o.seq == self.last_seq:
            return
        self.last_seq = o.seq
        # Buffered frames belonging to the spoken countdown must not count.
        if self.started is not None and not self.started <= o.t <= self.started + self.stage.time_limit:
            return
        self.total_frames += 1
        issue = measurement_issue(o, now, self.stage)
        gap = o.t - self.last_t if self.last_t is not None else 0.0
        if self.last_t is not None and gap <= 0:
            issue = "camera timestamps not advancing"
        good = not issue
        # Never credit an interval spanning rejected/missing frames as good time.
        if good and self.last_good and 0 < gap <= .35:
            self.valid_seconds += min(.25, gap)
        self.last_t, self.last_good = o.t, good
        self.latest_issue = issue
        if good:
            self.current.append(o)
        else:
            category = issue.partition(":")[0]
            self.rejected[category] += 1
            self.blocker_examples[category] = issue

    def due(self, now: float) -> bool:
        if not self.recording or self.started is None:
            return False
        elapsed = now - self.started
        if elapsed >= self.stage.time_limit:
            if self.last_t is None or not 0 <= now - self.last_t <= .7:
                self.final_issue = "no fresh camera measurements at the capture deadline"
            elif not self.last_good:
                self.final_issue = self.latest_issue or "measurements not usable at the capture deadline"
            return True
        fresh = self.last_t is not None and 0 <= now - self.last_t <= .7
        return elapsed >= self.stage.seconds and self.quality_met and self.last_good and fresh

    def quality_summary(self) -> str:
        fraction = len(self.current) / self.total_frames if self.total_frames else 0
        text = (f"{len(self.current)}/{self.total_frames} usable frames ({fraction:.0%}); "
                f"{self.valid_seconds:.1f}/{self.required_seconds:.1f}s usable; "
                f"minimum {self.required_frames} frames and 65% coverage")
        if self.rejected:
            text += ". Rejected: " + "; ".join(f"{self.blocker_examples.get(reason, reason)} ({n})" for reason, n in self.rejected.most_common(3))
        return text

    def progress(self, now: float) -> str:
        elapsed = max(0.0, now - self.started) if self.started is not None else 0
        if self.last_t is None:
            reason = "waiting for camera measurements"
        elif not 0 <= now - self.last_t <= .7:
            reason = "camera measurements arriving too late"
        else:
            reason = self.latest_issue or "measurement usable now"
        return (f"Usable {self.valid_seconds:.1f}/{self.required_seconds:.1f}s, "
                f"{len(self.current)}/{self.required_frames} frames. {reason}. "
                f"Time limit {max(0, self.stage.time_limit - elapsed):.0f}s. R retries; B goes back.")

    def finish(self) -> None:
        self.recording = False
        if self.final_issue:
            raise CalibrationError(f"{self.label} ({self.stage.key}): {self.final_issue}. " + self.quality_summary())
        if not self.quality_met:
            raise CalibrationError(f"{self.label} ({self.stage.key}): {self.quality_summary()}. "
                                   "Hold only the requested screen position. If you reposition the camera, restart the full calibration.")
        if self.stage.key == "monitors":
            self.monitor_samples[self.monitor_index] = list(self.current)
            self.samples["monitors"] = [o for i in sorted(self.monitor_samples) for o in self.monitor_samples[i]]
            key = f"monitors_{self.monitor_index + 1}"
        else:
            self.samples[self.stage.key] = list(self.current)
            key = self.stage.key
        self.capture_reports[key] = {"usable_frames": len(self.current), "total_frames": self.total_frames,
                                     "usable_seconds": self.valid_seconds, "rejected": dict(self.rejected)}

    def advance(self) -> bool:
        if self.stage.key == "monitors" and self.monitor_index + 1 < self.monitor_count:
            self.monitor_index += 1
            return True
        if self.index + 1 >= len(STAGES):
            return False
        self.index += 1
        if STAGES[self.index].key == "monitors":
            self.monitor_index = 0
        return True

    def repeat_previous(self) -> None:
        if self.stage.key == "monitors" and self.monitor_index > 0:
            self.monitor_index -= 1
        else:
            self.index = max(0, self.index - 1)
            if self.stage.key == "monitors":
                self.monitor_index = self.monitor_count - 1
        self.recording = False

    def select_stage(self, index: int) -> None:
        if not 0 <= index < len(STAGES):
            raise ValueError("Unknown calibration stage")
        self.cancel_capture()
        self.index = index
        self.monitor_index = 0

    def build(self) -> Profile:
        missing = [s.key for s in STAGES if s.key not in self.samples]
        if missing:
            raise CalibrationError("Missing stages: " + ", ".join(missing))
        if self.monitor_count > 1 and set(self.monitor_samples) != set(range(self.monitor_count)):
            raise CalibrationError("Each selected screen needs its own accepted sample; repeat the monitors stage")
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
                  "monitor_count": self.monitor_count, "capture_quality": self.capture_reports,
                  "notes": "Heuristic calibration; not a sleep diagnosis."}
        result = Profile(SCHEMA, next(iter(camera_keys)), datetime.now(timezone.utc).isoformat(), ov, cv,
                         neutral, reclined, reports["neck_down"], reports["neck_up"], signature,
                         tolerance, median([o.brightness for o in opens]), report)
        result.validate()
        view_coverage = {}
        for screen, values in sorted(self.monitor_samples.items()):
            usable = sum(bool(result.eye_ratios(o)) for o in values)
            fraction = usable / len(values) if values else 0.0
            view_coverage[str(screen + 1)] = fraction
            if fraction < .65:
                raise CalibrationError(
                    f"Work screen {screen + 1}: accepted images lack matching eye references at this angle. "
                    "Recheck this screen and the labelled open/closed positions; do not ignore this view.")
        result.report["monitor_reference_coverage"] = view_coverage
        return result
