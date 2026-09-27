"""Camera subprocess: local frames only; a blocked driver cannot block the GUI."""
from __future__ import annotations
import argparse
import base64
import json
import math
import queue
import os
import sys
import threading
import time
import zlib
from dataclasses import asdict

from .model import Observation
from .face_context import face_context
from .target_tracking import FaceBox, TargetTracker
from .glasses import glasses_descriptor


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
        face_mesh = mp.solutions.face_mesh.FaceMesh(max_num_faces=3, refine_landmarks=True,
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
        tracker = TargetTracker()
        selections = queue.SimpleQueue()
        last_pose_points = None
        last_pose_t = None

        def commands():
            for line in sys.stdin:
                try:
                    command = json.loads(line)
                    if command.get("cmd") == "stop":
                        stop.set()
                        return
                    if command.get("cmd") == "select_target":
                        x,y = command.get("x"),command.get("y")
                        if isinstance(x,(int,float)) and isinstance(y,(int,float)) and 0<=x<=1 and 0<=y<=1:
                            selections.put((x,y,time.monotonic()))
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
            candidates = [np.array([(p.x*w,p.y*h) for p in landmarks.landmark])
                          for landmarks in (result.multi_face_landmarks or [])]
            boxes=[]
            for pts in candidates:
                lo,hi=pts.min(axis=0),pts.max(axis=0)
                boxes.append(FaceBox(float(lo[0]/w),float(lo[1]/h),float((hi[0]-lo[0])/w),float((hi[1]-lo[1])/h)))
            selected=tracker.update(boxes,started)
            while not selections.empty():
                x,y,at=selections.get_nowait()
                if time.monotonic()-at<1:
                    selected=tracker.select(boxes,x,y,started)
            o.diagnostics["target_status"]=tracker.status
            o.diagnostics["faces_detected"]=len(boxes)
            for i,box in enumerate(boxes):
                colour=(100,230,100) if i==selected else (60,170,240)
                p1=(int(box.x*w),int(box.y*h));p2=(int((box.x+box.w)*w),int((box.y+box.h)*h))
                cv2.rectangle(frame,p1,p2,colour,2)
                cv2.putText(frame,"TRACKED" if i==selected else "OTHER / CLICK TO SELECT",
                            (p1[0],max(15,p1[1]-6)),cv2.FONT_HERSHEY_SIMPLEX,.45,colour,1)
            if selected is not None:
                pts=candidates[selected]
                o.face=True;o.body=True
                minimum,maximum=pts.min(axis=0),pts.max(axis=0)
                o.area=float(np.prod(maximum-minimum)/(w*h))
                o.cx,o.cy=float((minimum[0]+maximum[0])/(2*w)),float((minimum[1]+maximum[1])/(2*h))
                o.shape=face_context(pts)
                o.eyewear=glasses_descriptor(pts, gray)
                angles=head_pose(pts,w,h,o.diagnostics)
                if angles is not None:
                    o.pitch,o.yaw,o.roll=angles
                # Exposure tracking follows the selected face, not people or
                # bright objects walking through the rest of the room.
                x0,y0=np.maximum(minimum.astype(int),0)
                x1,y1=np.minimum(maximum.astype(int),(w,h))
                face_gray=gray[y0:y1,x0:x1]
                if face_gray.size:
                    o.brightness=float(face_gray.mean())
                # Sample pose at a lower cadence. Movement only counts when the
                # pose nose belongs to the selected face, so a passer cannot
                # provide fake "awake" hand/body activity.
                if seq % 3 == 0:
                    pose_result = pose.process(rgb)
                    associated = False
                    if pose_result.pose_landmarks:
                        lm = pose_result.pose_landmarks.landmark
                        box = boxes[selected]
                        nose = lm[0]
                        associated = (nose.visibility >= .45 and
                                      box.x-.08 <= nose.x <= box.x+box.w+.08 and
                                      box.y-.10 <= nose.y <= box.y+box.h+.12)
                        if associated:
                            torso = (11,12,23,24)
                            o.body = any(lm[i].visibility >= .5 for i in torso)
                            ids = (11,12,23,24,15,16)
                            current = {i:(float(lm[i].x),float(lm[i].y),float(lm[i].visibility)) for i in ids}
                            shoulder_span = max(.03, math.hypot(current[11][0]-current[12][0], current[11][1]-current[12][1]))
                            if last_pose_points is not None and last_pose_t is not None and 0 < started-last_pose_t <= 1.0:
                                def movement(indices):
                                    values=[]
                                    for i in indices:
                                        if current[i][2] >= .45 and last_pose_points[i][2] >= .45:
                                            values.append(math.hypot(current[i][0]-last_pose_points[i][0], current[i][1]-last_pose_points[i][1]) / shoulder_span)
                                    return values
                                body_moves=movement((11,12,23,24));hand_moves=movement((15,16))
                                if body_moves: o.body_activity=float(np.median(body_moves))
                                if hand_moves: o.hand_activity=float(max(hand_moves))
                            last_pose_points=current;last_pose_t=started
                    if not associated:
                        last_pose_points=None;last_pose_t=None
                for side,ids in (("left",LEFT),("right",RIGHT)):
                    diagnostic={}
                    value,quality=eye_measure(pts,ids,gray,diagnostic)
                    setattr(o,side,value);setattr(o,side+"_q",quality)
                    o.diagnostics.update({side+"_"+k:v for k,v in diagnostic.items()})
                    for i in ids:
                        cv2.circle(frame,tuple(pts[i].astype(int)),2,(100,230,100),-1)
            else:
                last_pose_points=None;last_pose_t=None
                # An unselected/ambiguous face can never supply open-eye data
                # or establish AWAY. Keep uncertainty explicit.
                body_result=pose.process(rgb)
                body=False
                if body_result.pose_landmarks:
                    landmarks=body_result.pose_landmarks.landmark
                    body=any(landmarks[i].visibility>=.5 for i in (11,12,23,24))
                o.body=True if candidates else body
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
