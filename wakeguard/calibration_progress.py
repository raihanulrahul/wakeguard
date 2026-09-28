"""Resumable numeric captures and explicit per-screen recovery. No images/audio."""
from __future__ import annotations

import json
from dataclasses import asdict
from .model import Observation, atomic_json

TITLES = {
    "main": "Normal working posture", "monitors": "Eyes open",
    "left": "Body slightly left", "right": "Body slightly right",
    "reading": "Reading posture", "neck_down": "Neck down", "neck_up": "Neck up",
    "reclined": "Chair reclined", "half_reclined": "Half-closed eyes · reclined",
    "half_upright": "Half-closed eyes · upright", "closed_main": "Eyes closed",
    "closed_reclined": "Closed eyes · reclined", "closed_left": "Closed eyes · left",
    "closed_right": "Closed eyes · right", "empty": "Empty chair",
    "glasses_on_open": "Glasses on · eyes open", "glasses_on_closed": "Glasses on · eyes closed",
}
SCREEN_MAPS = {"monitors": "monitor_samples", "closed_main": "closed_monitor_samples",
               "glasses_on_open": "glasses_open_samples", "glasses_on_closed": "glasses_closed_samples"}


class CalibrationProgress:
    def capture_tasks(self):
        # Keep the original labels, but collect each work-screen OPEN/CLOSED
        # pair together, before moving on to the next screen or other postures.
        if self.guided_pairs and self.relative:
            tasks = [("main", 0)]
            tasks += [(key, screen) for screen in range(self.monitor_count)
                      for key in ("monitors", "closed_main")]
            tasks += [(s.key, 0) for s in self.stages
                      if s.key not in ("main", *SCREEN_MAPS)]
            if self.glasses_enabled:
                tasks += [(key, screen) for screen in range(self.monitor_count)
                          for key in ("glasses_on_open", "glasses_on_closed")]
            return tasks
        return [(s.key, screen) for s in self.stages
                for screen in range(self.monitor_count if s.key in SCREEN_MAPS
                                     and (s.key != "closed_main" or self.relative or self.guided_pairs) else 1)]

    def capture_position(self):
        key = self.stages[self.index].key
        return key, self.monitor_index if self.screen_stage else 0

    def capture_title(self, key, screen=0):
        title = TITLES[key]
        return f"Monitor {screen + 1} · {title}" if key in SCREEN_MAPS else title

    @staticmethod
    def capture_id(key, screen=0):
        return f"{key}:{screen}"

    def capture_report_key(self, key, screen=0):
        return {"monitors": f"monitors_{screen+1}", "closed_main": f"closed_screen_{screen+1}",
                "glasses_on_open": f"glasses_open_screen_{screen+1}",
                "glasses_on_closed": f"glasses_closed_screen_{screen+1}"}.get(key, key)

    def capture_status(self, key, screen=0):
        ident = self.capture_id(key, screen)
        if ident in self.issues:
            return "Retry needed"
        if (key, screen) in self.pending_pairs:
            return "Needs pair check"
        report = self.capture_reports.get(self.capture_report_key(key, screen), {})
        if report.get("unavailable") or report.get("eye_limited"):
            return "Limited · saved"
        samples = (getattr(self, SCREEN_MAPS[key]).get(screen) if key in SCREEN_MAPS
                   and (key != "closed_main" or self.relative) else self.samples.get(key))
        return "Saved" if samples else "Pending"

    def complete(self, key, screen=0):
        return self.capture_status(key, screen) in ("Saved", "Limited · saved")

    def select_capture(self, key, screen=0):
        if (key, screen) not in self.capture_tasks():
            raise ValueError("Unknown calibration capture")
        self.cancel_capture()
        self.index = [s.key for s in self.stages].index(key)
        self.monitor_index = screen

    def next_needed(self):
        for task in self.capture_tasks():
            if not self.complete(*task):
                self.select_capture(*task)
                return True
        return False

    def finish_preserving_samples(self):
        from .calibration import CalibrationError
        fields = ("samples", "capture_reports", *SCREEN_MAPS.values())
        previous = {name: getattr(self, name).copy() for name in fields}
        key, screen = self.capture_position()
        ident = self.capture_id(key, screen)
        previous_good = self.complete(key, screen)
        self.retake_note = ""
        try:
            self._finish_capture()
            report = self.capture_reports.get(self.capture_report_key(key, screen), {})
            if report.get("unavailable") and previous_good and previous["samples"].get(key):
                for name, value in previous.items():
                    setattr(self, name, value)
                self.retake_note = "This repeat was unavailable; your earlier successful capture is still saved."
                return
            if self.guided_pairs and self.relative and key in ("closed_main", "glasses_on_closed"):
                from .relative_calibration import build_relative
                partial = build_relative(self, partial=True)
                if key == "glasses_on_closed":
                    coverage = partial.glasses_info().get("coverage", {}).get(str(screen+1), {})
                    if not coverage.get("eye_observable", False):
                        self.capture_reports[self.capture_report_key(key, screen)]["eye_limited"] = True
        except CalibrationError as exc:
            # A failed replacement never destroys the prior usable take.
            for name, value in previous.items():
                setattr(self, name, value)
            self.issues[ident] = str(exc)
            if previous_good:
                self.retained_previous.add(ident)
            raise
        self.issues.pop(ident, None)
        self.retained_previous.discard(ident)
        self.pending_pairs.discard((key, screen))
        if self.guided_pairs and self.relative and key in ("monitors", "glasses_on_open"):
            partner = "closed_main" if key == "monitors" else "glasses_on_closed"
            self.pending_pairs.add((partner, screen))

    def mark_repair(self, targets, message):
        valid = self.capture_tasks()
        for task in targets:
            if tuple(task) in valid:
                self.issues[self.capture_id(*task)] = message
                self.retained_previous.discard(self.capture_id(*task))

    def keep_previous(self):
        ident = self.capture_id(*self.capture_position())
        if ident not in self.retained_previous:
            return False
        self.issues.pop(ident, None)
        self.retained_previous.discard(ident)
        return True

    def save_draft(self, path, camera_config):
        # Store only numeric measurements, never preview frames or diagnostics.
        def encode(values):
            return [dict(asdict(o), diagnostics={}) for o in values]
        data = {"schema": 1, "camera_config": camera_config,
                "monitor_count": self.monitor_count, "glasses_enabled": self.glasses_enabled,
                "guided_pairs": self.guided_pairs, "position": list(self.capture_position()),
                "samples": {k: encode(v) for k, v in self.samples.items()},
                "capture_reports": self.capture_reports, "issues": self.issues,
                "pending_pairs": [list(x) for x in sorted(self.pending_pairs)],
                "retained_previous": sorted(self.retained_previous)}
        for field in SCREEN_MAPS.values():
            data[field] = {str(k): encode(v) for k, v in getattr(self, field).items()}
        atomic_json(path, data)

    @classmethod
    def load_draft(cls, path):
        if path.stat().st_size > 20_000_000:
            raise ValueError("Calibration draft is too large")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != 1:
            raise ValueError("Unsupported calibration draft")
        session = cls(data["monitor_count"], data["glasses_enabled"])
        session.guided_pairs = bool(data["guided_pairs"])
        allowed = {s.key for s in session.stages}
        session.samples = {k: [Observation.from_dict(o) for o in v]
                           for k, v in data["samples"].items() if k in allowed}
        for field in SCREEN_MAPS.values():
            values = data[field]
            if any(int(k) not in range(session.monitor_count) for k in values):
                raise ValueError("Invalid draft monitor")
            setattr(session, field, {int(k): [Observation.from_dict(o) for o in v] for k, v in values.items()})
        session.capture_reports = data["capture_reports"]
        session.issues = data["issues"]
        session.pending_pairs = {tuple(x) for x in data["pending_pairs"]}
        session.retained_previous = set(data.get("retained_previous", []))
        if not isinstance(session.capture_reports, dict) or not isinstance(session.issues, dict):
            raise ValueError("Invalid draft progress")
        session.select_capture(*data["position"])
        config = data["camera_config"]
        if not isinstance(config, dict):
            raise ValueError("Invalid draft camera")
        return session, config
