import unittest
import math
try:
    import numpy as np
    import cv2
    from wakeguard.vision_math import MODEL, POSE_INDEX, LEFT, head_pose, eye_measure
except ImportError:
    np=None


@unittest.skipIf(np is None,"OpenCV/NumPy not installed")
class VisionMathTests(unittest.TestCase):
    def test_synthetic_pose_pitch_and_yaw(self):
        for pitch,yaw in [(0,0),(20,25),(-15,-30)]:
            x,y=map(math.radians,(pitch,yaw))
            rx=np.array([[1,0,0],[0,math.cos(x),-math.sin(x)],[0,math.sin(x),math.cos(x)]])
            ry=np.array([[math.cos(y),0,math.sin(y)],[0,1,0],[-math.sin(y),0,math.cos(y)]])
            rot,_=cv2.Rodrigues(ry@rx)
            camera=np.array([[1280.,0,640],[0,1280.,360],[0,0,1]])
            image,_=cv2.projectPoints(MODEL,rot,np.array([[0.],[0.],[700.]]),camera,np.zeros((4,1)))
            pts=np.tile([640.,360.],(478,1));pts[POSE_INDEX]=image.reshape(-1,2)
            out=head_pose(pts,1280,720)
            self.assertIsNotNone(out)
            self.assertAlmostEqual(out[0],pitch,places=3);self.assertAlmostEqual(out[1],yaw,places=3)
    def test_tiny_eye_unknown(self):
        pts=np.zeros((478,2));gray=np.ones((200,200),dtype=np.uint8)*100
        self.assertEqual(eye_measure(pts,LEFT,gray),(None,0.))
    def test_featureless_eye_unknown(self):
        pts=np.zeros((478,2));pts[LEFT]=[(50,80),(65,72),(85,72),(100,80),(85,88),(65,88)]
        gray=np.ones((200,200),dtype=np.uint8)*100
        self.assertEqual(eye_measure(pts,LEFT,gray),(None,0.))
    def test_bad_pose_not_reported_as_zero(self):
        pts=np.ones((478,2))*100
        self.assertIsNone(head_pose(pts,1280,720))

if __name__=="__main__":unittest.main()
