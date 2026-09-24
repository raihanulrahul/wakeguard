"""Clearly labelled synthetic inputs for demos and regression tests."""
from .model import Observation, Profile, SCHEMA


def demo_profile():
    def pose(p=0, y=20, area=.12, cy=.45, eye=.30):
        return dict(pitch=p, yaw=y, roll=0, area=area, cy=cy, left=eye, right=eye)
    neutral, reclined = pose(), pose(12, area=.07, cy=.40)
    views = [pose(), pose(20), pose(-15), pose(y=5), pose(y=35), reclined]
    closed = [dict(v, left=.10, right=.10) for v in views]
    return Profile(SCHEMA, "DEMO", "synthetic", views, closed, neutral, reclined,
                   pose(20), pose(-15), [.2]*24, .02, 110,
                   {"valid": True, "auto_away_enabled": True, "reclined_eyes_valid": True})


def observation(now, seq, scenario="Awake"):
    o = Observation(t=now, seq=seq, camera_key="DEMO", face=True, body=True,
                    left=.3, right=.3, left_q=1, right_q=1, pitch=0, yaw=20, roll=0,
                    area=.12, cx=.5, cy=.45, brightness=110, sharpness=60, scene=[.5]*24)
    if scenario == "Eyes closed":
        o.left = o.right = .10
    elif scenario == "Half closed":
        o.left = o.right = .19
    elif scenario == "Reclined awake":
        o.area, o.cy, o.pitch = .07, .40, 12
    elif scenario == "Neck down":
        o.pitch, o.left, o.right = 20, .20, .20
    elif scenario == "Occluded":
        o.face = False
        o.left = o.right = None
        o.left_q = o.right_q = 0
    elif scenario == "Empty chair":
        o.face = o.body = False
        o.scene = [.2]*24
    elif scenario == "Camera failed":
        o.camera_ok = False
    return o
