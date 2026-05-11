import sys
import numpy as np
import matplotlib.pyplot as plt
import cv2
import mediapipe as mp

from core.phase_discovery import PhaseDiscoverer
from core.features import features_from_points
from core.normalization import PoseNormalizer

mp_pose = mp.solutions.pose

def extract_features(video_path):
    cap = cv2.VideoCapture(video_path)
    pose = mp_pose.Pose(static_image_mode=False, min_detection_confidence=0.5)
    normalizer = PoseNormalizer()
    
    features = []
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
            
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = pose.process(frame_rgb)
        
        if results.pose_landmarks:
            landmarks = [[lm.x, lm.y, lm.z] for lm in results.pose_landmarks.landmark]
            normalized = normalizer.normalize(landmarks)
            feat = features_from_points(normalized)
            features.append(feat)
    cap.release()
    return np.array(features)

teacher_video = r"F:\ACV\new folder\APP2\app\uploads\template_debug\template_69695f4a-9bad-4e99-a0ee-a4b914eb887e_53fd2f2d_debug.mp4"
student_video = r"F:\ACV\new folder\APP2\app\uploads\276747b1-c5d7-483b-91c6-4aec03c78a05.webm"

print("Extracting teacher features...")
teacher_feat = extract_features(teacher_video)
print("Extracting student features...")
student_feat = extract_features(student_video)

phase_discoverer = PhaseDiscoverer()
teacher_sig, _ = phase_discoverer.fit_transform(teacher_feat)

student_sig = []
for feat in student_feat:
    student_sig.append(phase_discoverer.transform_student(feat))
student_sig = np.array(student_sig)

from scipy.ndimage import gaussian_filter1d
student_sig = gaussian_filter1d(student_sig, sigma=2)

plt.figure(figsize=(15, 5))
plt.plot(student_sig, label="Student PCA Signal")

from scipy.signal import find_peaks
student_max = np.max(student_sig)
student_min = np.min(student_sig)
s_range = student_max - student_min

teacher_start_val = teacher_sig[0]
teacher_min = phase_discoverer.signal_min
teacher_max = phase_discoverer.signal_max
is_bottom_min = abs(teacher_min - teacher_start_val) > abs(teacher_max - teacher_start_val)

if is_bottom_min:
    min_height = student_max - 0.35 * s_range
    peaks, props = find_peaks(student_sig, prominence=0.15 * s_range, distance=25, height=min_height)
    plt.plot(peaks, student_sig[peaks], "rx", markersize=10, label="Peaks")
    plt.axhline(y=min_height, color='r', linestyle='--', label="Min Height")
else:
    min_height = -student_min - 0.35 * s_range
    peaks, props = find_peaks(-student_sig, prominence=0.15 * s_range, distance=25, height=min_height)
    plt.plot(peaks, student_sig[peaks], "gx", markersize=10, label="Valleys (Peaks of -sig)")
    plt.axhline(y=-min_height, color='g', linestyle='--', label="-Min Height")

plt.title("Lunge PCA Signal for Student")
plt.legend()
plt.savefig("lunge_pca_debug.png")
print("Saved plot to lunge_pca_debug.png")
