import numpy as np

class PoseNormalizer:
    def __init__(self):
        # MediaPipe Indices
        self.LEFT_HIP = 23
        self.RIGHT_HIP = 24
        self.LEFT_SHOULDER = 11
        self.RIGHT_SHOULDER = 12

    def normalize(self, landmarks):
        """
        Chuẩn hoá landmarks: Căn giữa theo điểm giữa hông và scale theo chiều dài thân.
        landmarks: np.array shape (33, 4) [x,y,z,v]
        """
        if landmarks is None or len(landmarks) == 0:
            return None
            
        # 1. Tính toán tâm cơ thể (Mid-hip)
        left_hip = landmarks[self.LEFT_HIP, :3]
        right_hip = landmarks[self.RIGHT_HIP, :3]
        center = (left_hip + right_hip) / 2.0
        
        # 2. Căn giữa
        centered_landmarks = landmarks.copy()
        centered_landmarks[:, :3] -= center
        
        # 3. Tính kích thước cơ thể (Torso size) để scale
        left_shoulder = landmarks[self.LEFT_SHOULDER, :3]
        right_shoulder = landmarks[self.RIGHT_SHOULDER, :3]
        mid_shoulder = (left_shoulder + right_shoulder) / 2.0
        
        # Khoảng cách từ mid-hip đến mid-shoulder
        torso_size = np.linalg.norm(mid_shoulder - center)
        if torso_size < 1e-6:
            torso_size = 1e-6
            
        # 4. Scale
        normalized_landmarks = centered_landmarks
        normalized_landmarks[:, :3] /= torso_size
        
        return normalized_landmarks
