"""Image geometry helpers. Quality scores are observability gates, not probabilities."""
from __future__ import annotations
import cv2
import numpy as np

LEFT = [33, 160, 158, 133, 153, 144]
RIGHT = [362, 385, 387, 263, 373, 380]
POSE_INDEX = [1, 152, 33, 263, 61, 291]
MODEL = np.array([(0, 0, 0), (0, 63.6, -12.5), (-43.3, -32.7, -26),
                  (43.3, -32.7, -26), (-28.9, 28.9, -24.1), (28.9, 28.9, -24.1)], dtype=np.float64)


def head_pose(points, width, height, diagnostics=None):
    diagnostics = {} if diagnostics is None else diagnostics
    diagnostics["pose_reason"] = ""
    def fail(reason):
        diagnostics["pose_reason"] = reason
        return None
    image = np.array([points[i][:2] for i in POSE_INDEX], dtype=np.float64)
    if not np.all(np.isfinite(image)) or np.ptp(image[:, 0]) < 20 or np.ptp(image[:, 1]) < 30:
        return fail("face landmarks too small or invalid")
    camera = np.array([[width, 0, width / 2], [0, width, height / 2], [0, 0, 1]], dtype=np.float64)
    try:
        good, rotation, translation = cv2.solvePnP(MODEL, image, camera, np.zeros((4, 1)), flags=cv2.SOLVEPNP_ITERATIVE)
        if not good or translation[2, 0] <= 0:
            return fail("head geometry could not be solved")
        projected, _ = cv2.projectPoints(MODEL, rotation, translation, camera, np.zeros((4, 1)))
        error = float(np.mean(np.linalg.norm(projected.reshape(-1, 2) - image, axis=1)))
        face_width = float(np.max(points[:, 0]) - np.min(points[:, 0]))
        if not np.isfinite(error) or error > max(6, .10 * face_width):
            return fail("head geometry fit is unreliable at this angle")
        matrix, _ = cv2.Rodrigues(rotation)
        angles = cv2.RQDecomp3x3(matrix)[0]
        if not all(np.isfinite(x) for x in angles):
            return fail("head angles were invalid")
        return tuple(float((x + 180) % 360 - 180) for x in angles)
    except cv2.error:
        return fail("head geometry calculation failed")


def eye_measure(points, ids, gray, diagnostics=None):
    diagnostics = {} if diagnostics is None else diagnostics
    diagnostics["reason"] = ""
    def fail(reason):
        diagnostics["reason"] = reason
        return None, 0.0
    p = np.array([points[i][:2] for i in ids])
    if not np.all(np.isfinite(p)):
        return fail("eye landmarks invalid")
    w = float(np.linalg.norm(p[0] - p[3]))
    diagnostics["width_px"] = w
    if w < 14:
        return fail(f"eye too small ({w:.1f}px)")
    h, width = gray.shape
    x0, x1 = int(p[:, 0].min()) - 5, int(p[:, 0].max()) + 6
    y0, y1 = int(p[:, 1].min()) - 7, int(p[:, 1].max()) + 8
    if x0 < 0 or y0 < 0 or x1 >= width or y1 >= h:
        return fail("eye crop outside camera frame")
    roi = gray[y0:y1, x0:x1]
    brightness = float(roi.mean())
    sharpness = float(cv2.Laplacian(roi, cv2.CV_64F).var())
    diagnostics["brightness"] = brightness
    diagnostics["sharpness"] = sharpness
    if not 15 < brightness < 245:
        return fail("eye image too dark or overexposed")
    if sharpness < 4:
        return fail("eye image lacks detail or is blurred")
    ear = float((np.linalg.norm(p[1] - p[5]) + np.linalg.norm(p[2] - p[4])) / (2 * w))
    if not 0 <= ear <= .7:
        return fail("eye geometry outside allowed range")
    quality = min(1.0, w / 28)
    if quality < .55:
        diagnostics["reason"] = f"eye too small for accepted quality ({w:.1f}px)"
    return ear, quality
