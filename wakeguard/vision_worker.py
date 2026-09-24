"""Camera subprocess: local frames only; a blocked driver cannot block the GUI."""
from __future__ import annotations
import argparse
import base64
import json
import os
import sys
import threading
import time
import zlib
from dataclasses import asdict

from .model import Observation


def emit(message):
    print(json.dumps(message, allow_nan=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--backend", choices=["auto", "dshow", "msmf"], default="auto")
    args = parser.parse_args()
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    cap = face_mesh = pose = None
    stop = threading.Event()
    try:
        import cv2
        import numpy as np
        import mediapipe as mp
        from .vision_math import LEFT, RIGHT, head_pose, eye_measure
        if not hasattr(mp, "solutions"):
            raise RuntimeError("Legacy MediaPipe missing. Run Setup-WakeGuard.ps1; do not install latest MediaPipe here.")
        cv2.setNumThreads(2)
        face_mesh = mp.solutions.face_mesh.FaceMesh(max_num_faces=1, refine_landmarks=True,
                                                   min_detection_confidence=.5, min_tracking_confidence=.5)
        pose = mp.solutions.pose.Pose(static_image_mode=False, model_complexity=1,
                                     min_detection_confidence=.55, min_tracking_confidence=.55)
        backend = cv2.CAP_ANY
        if os.name == "nt":
            backend = cv2.CAP_MSMF if args.backend == "msmf" else cv2.CAP_DSHOW
        cap = cv2.VideoCapture(args.camera, backend)
        if not cap.isOpened() and args.backend == "auto":
            cap.release()
            cap = cv2.VideoCapture(args.camera)
        if not cap.isOpened():
            raise RuntimeError("Camera cannot open. Close other camera apps; try another camera index/backend.")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        seq, last_crc, last_change = 0, None, time.monotonic()
        body = None

        def commands():
            for line in sys.stdin:
                try:
                    if json.loads(line).get("cmd") == "stop":
                        stop.set()
                        return
                except ValueError:
                    pass
            stop.set()  # Parent died/closed pipe: release camera.
        threading.Thread(target=commands, daemon=True).start()
        while not stop.is_set():
            started = time.monotonic()
            okay, frame = cap.read()
            seq += 1
            if not okay or frame is None:
                emit({"event": "frame", "observation": asdict(Observation(started, seq, camera_ok=False, error="Camera read failed"))})
                stop.wait(.15)
                continue
            # Measurements use UNMIRRORED pixels; do not change Euler signs by display flips.
            h, w = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            crc = zlib.crc32(cv2.resize(gray, (160, 90)).tobytes())
            if crc != last_crc:
                last_change, last_crc = started, crc
            o = Observation(started, seq, camera_ok=started - last_change < 3,
                            camera_key=f"camera:{args.camera}:{w}x{h}",
                            brightness=float(gray.mean()),
                            sharpness=float(cv2.Laplacian(gray, cv2.CV_64F).var()),
                            scene=(cv2.resize(gray, (6, 4), interpolation=cv2.INTER_AREA).reshape(-1) / 255).tolist())
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = face_mesh.process(rgb)
            if result.multi_face_landmarks:
                pts = np.array([(p.x * w, p.y * h) for p in result.multi_face_landmarks[0].landmark])
                o.face = True
                o.body = True
                minimum, maximum = pts.min(axis=0), pts.max(axis=0)
                o.area = float(np.prod(maximum - minimum) / (w * h))
                o.cx, o.cy = float((minimum[0] + maximum[0]) / (2*w)), float((minimum[1] + maximum[1]) / (2*h))
                angles = head_pose(pts, w, h)
                if angles is not None:
                    o.pitch, o.yaw, o.roll = angles
                o.left, o.left_q = eye_measure(pts, LEFT, gray)
                o.right, o.right_q = eye_measure(pts, RIGHT, gray)
                for ids in (LEFT, RIGHT):
                    for i in ids:
                        cv2.circle(frame, tuple(pts[i].astype(int)), 2, (100, 230, 100), -1)
                cv2.rectangle(frame, tuple(minimum.astype(int)), tuple(maximum.astype(int)), (100, 230, 100), 2)
            else:
                # No face is NOT evidence of no person. Pose helps catch head-down occlusion.
                body_result = pose.process(rgb)
                body = False
                if body_result.pose_landmarks:
                    landmarks = body_result.pose_landmarks.landmark
                    body = any(landmarks[i].visibility >= .5 for i in (11, 12, 23, 24))
                o.body = body
            if not o.camera_ok:
                o.error = "Identical camera frames for 3 seconds"
            preview = cv2.resize(frame, (480, max(1, int(h * 480 / w))))
            encoded, jpeg = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 65])
            message = {"event": "frame", "observation": asdict(o)}
            if encoded and seq % 2 == 0:
                message["preview"] = base64.b64encode(jpeg).decode("ascii")
            emit(message)
            stop.wait(max(0, .065 - (time.monotonic() - started)))
    except Exception as exc:
        emit({"event": "camera_error", "message": f"{type(exc).__name__}: {exc}"})
    finally:
        for resource in (cap, face_mesh, pose):
            if resource is not None:
                try:
                    resource.release() if resource is cap else resource.close()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
