import numpy as np

def calculate_angle(a, b, c):
    """
    Tính góc 3D giữa 3 điểm a, b, c (b là đỉnh góc).
    """
    a = np.array(a[:3])
    b = np.array(b[:3])
    c = np.array(c[:3])
    
    ba = a - b
    bc = c - b
    
    cosine_angle = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-6)
    angle = np.arccos(np.clip(cosine_angle, -1.0, 1.0))
    return np.degrees(angle)

class FeatureExtractor:
    def __init__(self):
        # Các góc quan trọng: L/R Elbow, L/R Shoulder, L/R Hip, L/R Knee
        self.angle_triplets = [
            (11, 13, 15), # L Elbow
            (12, 14, 16), # R Elbow
            (23, 11, 13), # L Shoulder
            (24, 12, 14), # R Shoulder
            (11, 23, 25), # L Hip
            (12, 24, 26), # R Hip
            (23, 25, 27), # L Knee
            (24, 26, 28)  # R Knee
        ]
        self.prev_features = None

    def extract(self, normalized_landmarks):
        if normalized_landmarks is None:
            return None
            
        features = []
        for triplet in self.angle_triplets:
            a, b, c = triplet
            ang = calculate_angle(
                normalized_landmarks[a],
                normalized_landmarks[b],
                normalized_landmarks[c]
            )
            features.append(ang / 180.0)
            
        # Thêm các đặc trưng khoảng cách (Distance Features) cực kỳ quan trọng
        # Khi gập tay hướng vuông góc với camera, góc khuỷu tay 3D bị chiếu sai
        # Khoảng cách trục Y giữa Vai và Cổ tay sẽ luôn thay đổi rõ rệt khi hạ người.
        
        # Vai tới Cổ tay (Phục vụ Push-up)
        features.append(normalized_landmarks[15][1] - normalized_landmarks[11][1]) # Trái
        features.append(normalized_landmarks[16][1] - normalized_landmarks[12][1]) # Phải
        
        # Hông tới Mắt cá chân (Phục vụ Squat)
        features.append(normalized_landmarks[27][1] - normalized_landmarks[23][1]) # Trái
        features.append(normalized_landmarks[28][1] - normalized_landmarks[24][1]) # Phải
        
        features = np.array(features)
        
        # Vận tốc (Velocity)
        if self.prev_features is not None:
            velocities = features - self.prev_features[:len(features)]
        else:
            velocities = np.zeros_like(features)
            
        self.prev_features = np.concatenate([features, velocities])
        return self.prev_features
