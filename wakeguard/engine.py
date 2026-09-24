"""Deterministic concern state machine, independent of camera/GUI/phone APIs."""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from .model import Observation, Profile, clamp


@dataclass(frozen=True)
class Mode:
    closed_s: float
    partial_s: float
    unknown_s: float
    warning: float
    alarm: float
    charge: float
    learning: bool
    no_recline: bool = False


MODES = {
    "Normal": Mode(1.6, 4.0, 3.0, 55, 78, 26, True),
    "High Alert": Mode(1.2, 2.5, 1.5, 40, 62, 42, False),
    "Super Alert": Mode(.8, 1.5, 1.0, 28, 48, 60, False, True),
}


@dataclass
class Decision:
    status: str
    battery: float
    alarm: bool
    reasons: list[str] = field(default_factory=list)
    eye: float | None = None
    recline: float | None = None
    neck: float | None = None
    auto_cleared: bool = False
    learning: bool = False
    fresh: bool = False


class Engine:
    def __init__(self, profile: Profile, mode: str = "Normal") -> None:
        self.profile = profile
        self.mode = mode
        self.battery = 0.0
        self.active = False
        self.reason = ""
        self.timers: dict[str, float] = {}
        self.last_update: float | None = None
        self.last_seq: int | None = None
        self.last_alarm = -float("inf")
        self.quiet_until = -float("inf")
        self.adaptation = {"left": 0.0, "right": 0.0}
        self.motion: deque[tuple[float, float, float]] = deque(maxlen=180)
        self.manual_away = False
        self.manual_away_since = 0.0
        self.manual_away_departed = False

    def dwell(self, name: str, condition: bool, now: float) -> float:
        if not condition:
            self.timers.pop(name, None)
            return 0.0
        return max(0.0, now - self.timers.setdefault(name, now))

    def acknowledge(self, now: float) -> None:
        self.active = False
        self.quiet_until = now + 1
        self.battery = min(self.battery, MODES[self.mode].warning - 5)
        # Sustained closure and forbidden recline are not erased by a tap.
        self.timers.pop("recovered", None)

    def set_away(self, now: float) -> None:
        self.manual_away = True
        self.manual_away_since = now
        self.manual_away_departed = False
        self.active = False
        self.battery = 0
        self.timers.clear()

    def update(self, o: Observation, now: float, input_age: float | None = None) -> Decision:
        cfg = MODES[self.mode]
        dt = 0 if self.last_update is None else clamp(now - self.last_update, 0, .3)
        self.last_update = now
        fresh = o.camera_ok and 0 <= now - o.t <= .8
        new_frame = o.seq != self.last_seq
        if new_frame:
            self.last_seq = o.seq
        if self.manual_away and fresh and not o.face and o.body is False:
            self.manual_away_departed = True
        if self.manual_away and fresh and (o.face or o.body is True) and (self.manual_away_departed or now - self.manual_away_since >= 3):
            self.manual_away = False
        empty = fresh and self.profile.empty_match(o)
        empty_for = self.dwell("empty", empty, now)
        if fresh and (self.manual_away or empty_for >= 3):
            was_active = self.active
            self.active = False
            self.battery = max(0, self.battery - 60 * dt)
            self.timers = {"empty": self.timers["empty"]} if "empty" in self.timers else {}
            self.motion.clear()
            return Decision("AWAY", self.battery, False, ["Leaving-seat grace" if self.manual_away and not self.manual_away_departed else "Empty chair confirmed"], auto_cleared=was_active, fresh=True)

        camera_fault = not fresh
        changed_camera = fresh and o.camera_key != self.profile.camera_key
        # Alert light must not poison the light-change detector or its recovery.
        changed_light = fresh and abs(o.brightness - self.profile.brightness) > 65 and not self.active and now - self.last_alarm > 5
        light_for = self.dwell("light_changed", changed_light, now)
        eye_values = self.profile.eye_ratios(o, self.adaptation) if fresh and not changed_camera else []
        eye = min(eye_values) if eye_values else None
        recline = self.profile.recline(o) if fresh else None
        down = self.profile.neck(o) if fresh else None
        up = self.profile.neck(o, "up") if fresh else None
        neck = max(down or 0, up or 0) if down is not None or up is not None else None
        if new_frame and fresh and o.face and o.cx is not None and o.cy is not None:
            self.motion.append((now, o.cx, o.cy))
        while self.motion and now - self.motion[0][0] > 4:
            self.motion.popleft()
        still = (len(self.motion) >= 8 and self.motion[-1][0] - self.motion[0][0] >= 2
                 and max(x[1] for x in self.motion) - min(x[1] for x in self.motion) < .008
                 and max(x[2] for x in self.motion) - min(x[2] for x in self.motion) < .008)
        closed_for = self.dwell("closed", fresh and eye is not None and eye < .25, now)
        partial_for = self.dwell("partial", fresh and eye is not None and eye < self.profile.partial_limit(o), now)
        unknown = camera_fault or changed_camera or (not empty and (not o.face or eye is None))
        unknown_for = self.dwell("unknown", unknown, now)
        recline_for = self.dwell("recline", fresh and recline is not None and recline >= .68, now)
        neck_concern = (fresh and neck is not None and neck >= .75
                        and (eye is None or eye < .8 or (still and input_age is not None and input_age > 15)))
        neck_for = self.dwell("neck", neck_concern, now)
        reasons = []
        if new_frame and closed_for >= cfg.closed_s:
            reasons.append("Sustained eye closure")
        if new_frame and partial_for >= cfg.partial_s:
            reasons.append("Sustained partly closed eyelids")
        if cfg.no_recline and recline_for >= .35:
            reasons.append("Super Alert: recline forbidden")
        if neck_for >= (2.5 if self.mode == "Normal" else 1.5):
            reasons.append("Calibrated neck tilt with reduced alertness cues")
        if unknown_for >= (1.2 if camera_fault else cfg.unknown_s):
            reasons.append("Camera stopped/stale" if camera_fault else "Eyes/face unobservable: check camera or posture")
        if changed_camera:
            reasons.append("Camera/resolution changed: recalibrate")
        if light_for >= 5:
            reasons.append("Lighting changed substantially: recheck calibration")

        score = (1 - clamp(eye)) * 55 if eye is not None else 35
        score += (recline or 0) * (20 if self.mode == "Normal" else 28)
        score += (neck or 0) * 15 + (8 if still else 0)
        score += 4 if input_age is not None and input_age > 30 else 0
        if fresh and eye is not None and eye >= .85 and not neck_concern:
            self.battery -= 24 * dt
        elif score > 35:
            self.battery += (score - 35) / 65 * cfg.charge * dt
        else:
            self.battery -= 22 * dt
        self.battery = clamp(self.battery, 0, 100)
        if self.battery >= cfg.alarm and not empty:
            reasons.append("Accumulated concern")
        if reasons:
            self.last_alarm = now
            if now >= self.quiet_until:
                self.active = True
                self.reason = "; ".join(reasons)
        hard_recline = cfg.no_recline and recline is not None and recline >= .68
        recovered = (self.active and fresh and eye is not None and eye >= .80
                     and not hard_recline and not changed_camera)
        recovery_for = self.dwell("recovered", recovered, now)
        auto = False
        if new_frame and recovery_for >= 3:
            self.active = False
            self.battery = min(self.battery, 15)
            self.quiet_until = now + .3
            self.timers.pop("recovered", None)
            auto = True

        learning_candidate = (cfg.learning and fresh and not self.active and not reasons
                              and self.battery < 15 and eye is not None and .9 <= eye <= 1.15
                              and (recline or 0) < .25 and (neck or 0) < .25
                              and input_age is not None and input_age < 10
                              and now - self.last_alarm >= 120
                              and abs(o.brightness - self.profile.brightness) < 25)
        learn_for = self.dwell("learn", learning_candidate, now)
        learning = learning_candidate and learn_for >= 30
        if learning and new_frame:
            for side in ("left", "right"):
                views = [v for v in self.profile.open_views if v.get(side) is not None]
                if o.valid_eye(side) and views:
                    ref = min(views, key=lambda v: self.profile._pose_distance(o, v))
                    target = clamp(getattr(o, side) / ref[side] - 1, 0, .05)
                    self.adaptation[side] = clamp(self.adaptation[side] + max(0, target - self.adaptation[side]) * dt / 600, 0, .05)
        if self.active:
            status = "ALARM"
        elif camera_fault:
            status = "CAMERA FAULT"
        elif changed_camera or light_for >= 5:
            status = "RECALIBRATE"
        elif empty:
            status = "CHECKING AWAY"
        elif unknown:
            status = "TRACKING LOST"
        elif self.battery >= cfg.warning or partial_for > .4 or neck_concern:
            status = "WATCH"
        else:
            status = "MONITORING"
        return Decision(status, self.battery, self.active, [self.reason] if self.active else reasons,
                        eye, recline, neck, auto, learning, fresh)
