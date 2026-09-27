"""Personalized glasses state support.

The automatic classifier is deliberately local and user-specific. It does not
perform identity recognition and it never treats an uncertain visual result as
proof that glasses are on or off. Manual On/Off remains the hard override.
"""
from __future__ import annotations
import math
import statistics as st

FEATURE_COUNT = 12
AUTO_MIN_SEPARATION = 1.25
AUTO_MIN_MARGIN = 0.16
AUTO_MAX_DISTANCE = 6.0


def valid_descriptor(values) -> bool:
    return (isinstance(values, (list, tuple)) and len(values) == FEATURE_COUNT
            and all(isinstance(x, (int, float)) and math.isfinite(x) and -0.05 <= x <= 1.5 for x in values))


def _median(xs):
    return float(st.median(xs))


def _spread(xs, floor=.025):
    m = _median(xs)
    return max(floor, 1.4826 * _median([abs(x - m) for x in xs]))


def build_prototype(samples):
    """Build a numeric descriptor prototype from observations; no image is stored."""
    vectors = [o.eyewear for o in samples if valid_descriptor(getattr(o, "eyewear", []))]
    if len(vectors) < 8:
        return None
    centre = [_median([v[i] for v in vectors]) for i in range(FEATURE_COUNT)]
    spread = [_spread([v[i] for v in vectors]) for i in range(FEATURE_COUNT)]
    return {"features": centre, "spread": spread, "n": len(vectors)}


def prototype_distance(values, prototype) -> float:
    if not valid_descriptor(values) or not isinstance(prototype, dict):
        return float("inf")
    centre, spread = prototype.get("features"), prototype.get("spread")
    if not valid_descriptor(centre) or not valid_descriptor(spread):
        return float("inf")
    return sum(abs(v-c) / max(.025, s) for v,c,s in zip(values, centre, spread)) / FEATURE_COUNT


def prototype_separation(off, on) -> float:
    if not isinstance(off, dict) or not isinstance(on, dict):
        return 0.0
    a,b = off.get("features"),on.get("features")
    sa,sb = off.get("spread"),on.get("spread")
    if not all(valid_descriptor(x) for x in (a,b,sa,sb)):
        return 0.0
    return sum(abs(x-y) / max(.025, sx, sy) for x,y,sx,sy in zip(a,b,sa,sb)) / FEATURE_COUNT


def classify_descriptor(values, pair):
    """Return (on/off/uncertain, confidence, d_off, d_on)."""
    if not valid_descriptor(values) or not isinstance(pair, dict) or not pair.get("auto_ok"):
        return "uncertain", 0.0, float("inf"), float("inf")
    d_off = prototype_distance(values, pair.get("off"))
    d_on = prototype_distance(values, pair.get("on"))
    if not math.isfinite(d_off) or not math.isfinite(d_on):
        return "uncertain", 0.0, d_off, d_on
    winner = "off" if d_off < d_on else "on"
    best, other = min(d_off,d_on), max(d_off,d_on)
    margin = (other-best) / max(.5, other)
    confidence = max(0.0, min(1.0, margin))
    if best > AUTO_MAX_DISTANCE or margin < AUTO_MIN_MARGIN:
        return "uncertain", confidence, d_off, d_on
    return winner, confidence, d_off, d_on


def glasses_descriptor(points, gray):
    """Extract frame/glare cues around the eye perimeter in a normalized crop.

    The descriptor intentionally avoids the central eyelid opening as much as
    possible so eye closure does not itself become a glasses classifier. It is
    only useful after personalized on/off enrollment at the user's real screen
    angles.
    """
    try:
        import cv2
        import numpy as np
        p = np.asarray(points, dtype=float)
        left, right = p[33,:2], p[263,:2]
        dx,dy = right-left
        span = float(np.hypot(dx,dy))
        if not np.isfinite(span) or span < 30:
            return []
        mid = (left+right)/2
        angle = math.degrees(math.atan2(dy,dx))
        h,w = gray.shape[:2]
        matrix = cv2.getRotationMatrix2D((float(mid[0]),float(mid[1])), angle, 1.0)
        rotated = cv2.warpAffine(gray, matrix, (w,h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        x0,x1 = int(mid[0]-span*.72), int(mid[0]+span*.72)
        y0,y1 = int(mid[1]-span*.30), int(mid[1]+span*.34)
        x0,y0=max(0,x0),max(0,y0);x1,y1=min(w,x1),min(h,y1)
        if x1-x0 < 40 or y1-y0 < 18:
            return []
        crop = cv2.resize(rotated[y0:y1,x0:x1], (120,52), interpolation=cv2.INTER_AREA)
        sobelx = cv2.Sobel(crop, cv2.CV_32F, 1, 0, ksize=3)
        sobely = cv2.Sobel(crop, cv2.CV_32F, 0, 1, ksize=3)
        mag = cv2.magnitude(sobelx,sobely)
        edge_threshold = max(18.0, float(np.median(mag))*2.2)
        zones = [
            (slice(5,18),slice(12,50)),   # left upper frame
            (slice(5,18),slice(70,108)),  # right upper frame
            (slice(10,40),slice(5,18)),   # left outer frame
            (slice(10,40),slice(102,115)),# right outer frame
            (slice(12,38),slice(52,68)),  # bridge
        ]
        features=[]
        for ys,xs in zones:
            features.append(float(np.mean(mag[ys,xs] > edge_threshold)))
        for ys,xs in zones:
            features.append(float(np.mean(crop[ys,xs] < 70)))
        for ys,xs in ((slice(12,42),slice(18,52)),(slice(12,42),slice(68,102))):
            features.append(float(np.mean(crop[ys,xs] > 242)))
        return features if valid_descriptor(features) else []
    except Exception:
        return []
