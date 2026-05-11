import cv2
import mediapipe as mp
import numpy as np
import os
import urllib.request

class PoseTracker:
    def __init__(self, model_asset_path='pose_landmarker_lite.task'):
        from pathlib import Path
        model_path = str(Path(__file__).parent.parent / model_asset_path)
        if not os.path.exists(model_path):
            print("Downloading Pose Landmarker Model...")
            url = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
            urllib.request.urlretrieve(url, model_path)

        BaseOptions = mp.tasks.BaseOptions
        self.PoseLandmarker = mp.tasks.vision.PoseLandmarker
        PoseLandmarkerOptions = mp.tasks.vision.PoseLandmarkerOptions
        VisionRunningMode = mp.tasks.vision.RunningMode

        options = PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            running_mode=VisionRunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5
        )
        self.landmarker = self.PoseLandmarker.create_from_options(options)

    def process_frame(self, frame, timestamp_ms):
        """
        Xử lý frame và trả về landmarks dạng numpy array (33, 4) -> [x, y, z, visibility]
        Trả về None nếu không phát hiện được người.
        """
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
        
        results = self.landmarker.detect_for_video(mp_image, int(timestamp_ms))
        
        if not results.pose_landmarks:
            return None, results
            
        landmarks = []
        for lm in results.pose_landmarks[0]:
            landmarks.append([lm.x, lm.y, lm.z, getattr(lm, 'visibility', 1.0)])
            
        return np.array(landmarks), results
        
    def close(self):
        self.landmarker.close()
