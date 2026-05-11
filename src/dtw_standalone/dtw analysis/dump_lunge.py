import cv2
import numpy as np
from scipy.signal import find_peaks
import json

from core.pose_tracker import PoseTracker
from core.normalizer import PoseNormalizer
from core.features import FeatureExtractor
from analysis.phase_discovery import PhaseDiscoverer

def analyze():
    # Load teacher
    t_tracker = PoseTracker()
    norm = PoseNormalizer()
    feat = FeatureExtractor()
    cap = cv2.VideoCapture("F:\\ACV\\new folder\\APP2\\app\\uploads\\template_debug\\template_69695f4a-9bad-4e99-a0ee-a4b914eb887e_53fd2f2d_debug.mp4")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    t_feats = []
    idx = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break
        lms, _ = t_tracker.process_frame(frame, int(idx*1000/fps))
        if lms is not None:
            f = feat.extract(norm.normalize(lms))
            if f is not None: t_feats.append(f)
        idx += 1
    cap.release()
    t_tracker.close()
    
    t_feats = np.array(t_feats)
    pd = PhaseDiscoverer()
    t_sig, _ = pd.fit_transform(t_feats)
    
    # Load student
    s_tracker = PoseTracker()
    feat = FeatureExtractor()
    cap = cv2.VideoCapture("F:\\ACV\\new folder\\APP2\\app\\uploads\\0c08afcf-abb7-4147-8245-f59c7168964b.webm")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    s_sigs = []
    idx = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break
        lms, _ = s_tracker.process_frame(frame, int(idx*1000/fps))
        if lms is not None:
            f = feat.extract(norm.normalize(lms))
            if f is not None:
                s = pd.transform_student(f)
                s_sigs.append(float(s))
        idx += 1
    cap.release()
    s_tracker.close()
    
    with open("lunge_signal.json", "w") as f:
        json.dump({
            "teacher_signal": t_sig.tolist(),
            "student_signal": s_sigs
        }, f)
        
    print(f"Dumped teacher ({len(t_sig)}) and student ({len(s_sigs)}) signals.")

if __name__ == "__main__":
    analyze()
