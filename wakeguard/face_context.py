"""Local 2-D face context, independent of a generic 3-D head model.

These coordinates are not head angles. They describe visible facial geometry
for matching eye references and labelled neck movement at this one camera.
No images or identity-recognition embeddings are used. Numeric calibration
context is stored with the other local eye/posture references.
"""
from __future__ import annotations
import math

# Nose horizontal/vertical, chin vertical, eye-width asymmetry, image roll.
SCALES = (.12, .12, .28, .40, 15.0)


def valid_shape(values) -> bool:
    return (isinstance(values, (list, tuple)) and len(values) == 5
            and all(isinstance(x, (int, float)) and math.isfinite(x) for x in values)
            and abs(values[0]) < 3 and abs(values[1]) < 3
            and .15 < values[2] < 6 and abs(values[3]) < 3
            and abs(values[4]) <= 180)


def delta_shape(a, b):
    if not valid_shape(a) or not valid_shape(b):
        return None
    return [(x - y) / scale if i != 4 else ((x - y + 180) % 360 - 180) / scale
            for i, (x, y, scale) in enumerate(zip(a, b, SCALES))]


def shape_distance(a, b) -> float:
    delta = delta_shape(a, b)
    return math.sqrt(sum(x*x for x in delta)) if delta is not None else float('inf')


def face_context(points):
    """Use corners/nose/chin, NOT eyelid opening, for reference selection.

    points may be ndarray or nested lists in pixel coordinates. Translation,
    uniform scale and roll do not change the first four features. An invalid
    mesh remains unknown; no fallback fabricates Euler angles.
    """
    try:
        get = lambda i: (float(points[i][0]), float(points[i][1]))
        left, right, nose, chin = [get(i) for i in (33, 263, 1, 152)]
        vals = left + right + nose + chin + get(133) + get(362)
        if not all(math.isfinite(x) for x in vals):
            return []
        dx, dy = right[0]-left[0], right[1]-left[1]
        span = math.hypot(dx, dy)
        if span < 25:
            return []
        ux, uy = dx/span, dy/span
        midpoint = ((left[0]+right[0])/2, (left[1]+right[1])/2)
        def normalized(point):
            x,y = point[0]-midpoint[0], point[1]-midpoint[1]
            return ((x*ux+y*uy)/span, (-x*uy+y*ux)/span)
        nx, ny = normalized(nose)
        _, cy = normalized(chin)
        lw = math.dist(left, get(133)); rw = math.dist(right, get(362))
        if min(lw, rw) < 4:
            return []
        values = [nx, ny, cy, math.log(lw/rw), math.degrees(math.atan2(dy,dx))]
        return values if valid_shape(values) else []
    except (ValueError, TypeError, IndexError, OverflowError):
        return []


def neck_separation(neutral: dict, target: dict) -> float:
    """Separation of labelled nose/chin vertical geometry, in local units."""
    delta = delta_shape(target.get('shape'), neutral.get('shape'))
    return math.hypot(delta[1], delta[2]) if delta is not None else 0.0


def neck_projection(shape, neutral: dict, target: dict, normal_views=()):
    axis = delta_shape(target.get('shape'), neutral.get('shape'))
    point = delta_shape(shape, neutral.get('shape'))
    if axis is None or point is None or neck_separation(neutral, target) < .65:
        return None
    # Use observed vertical nose/chin movement; don't call a side turn a nod.
    dims = (1, 2)
    norm = sum(axis[i]**2 for i in dims)
    raw = sum(point[i]*axis[i] for i in dims)/norm
    # Ordinary working views are zero-risk anchors, including reading down.
    # Only subtract normal variation; never change the labelled danger anchor.
    normal = 0.0
    for view in normal_views:
        context = view.get('shape')
        if not valid_shape(context):
            continue
        # Match horizontal orientation without relying on PnP yaw.
        if abs(context[0]-shape[0]) > .12 or abs(context[3]-shape[3]) > .45:
            continue
        offset = delta_shape(context, neutral.get('shape'))
        value = sum(offset[i]*axis[i] for i in dims)/norm
        if 0 <= value < .6:
            normal = max(normal, value)
    return max(0.0, min(1.0, (raw-normal)/max(.4, 1-normal)))
