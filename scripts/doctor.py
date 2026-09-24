"""Install checks: no webcam, credentials, microphone or network calls."""
import importlib.metadata as meta
import struct
import sys


def main():
    assert sys.version_info[:2] == (3, 12), f"Expected Python 3.12, got {sys.version}"
    assert struct.calcsize("P") == 8, "64-bit Python required"
    import cv2
    import numpy as np
    import mediapipe as mp
    import tkinter
    import PIL
    variants = []
    for name in ("opencv-python", "opencv-contrib-python", "opencv-python-headless", "opencv-contrib-python-headless"):
        try:
            variants.append(name + "==" + meta.version(name))
        except meta.PackageNotFoundError:
            pass
    assert len(variants) == 1 and variants[0].startswith("opencv-contrib-python=="), f"Overlapping OpenCV installs: {variants}"
    assert mp.__version__ == "0.10.21" and hasattr(mp, "solutions"), "Wrong MediaPipe API"
    assert np.__version__ == "1.26.4", "Wrong NumPy version"
    with mp.solutions.face_mesh.FaceMesh(max_num_faces=1, refine_landmarks=True) as mesh:
        result = mesh.process(np.zeros((480, 640, 3), dtype=np.uint8))
        assert not result.multi_face_landmarks
    with mp.solutions.pose.Pose(model_complexity=1) as pose:
        result = pose.process(np.zeros((480, 640, 3), dtype=np.uint8))
        assert not result.pose_landmarks
    print("PASS: Python x64, NumPy, OpenCV, FaceMesh/Pose blank-image inference, Tkinter and Pillow imports")
    print("Hardware/account tests are still required. This did not open your camera or contact Apple.")


if __name__ == "__main__":
    main()
