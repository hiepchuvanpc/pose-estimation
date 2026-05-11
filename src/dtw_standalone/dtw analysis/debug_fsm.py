import cv2
import numpy as np
from core.pose_tracker import PoseTracker
from core.normalizer import PoseNormalizer
from core.features import FeatureExtractor
from analysis.phase_discovery import PhaseDiscoverer
from analysis.fsm_counter import FSMCounter

def debug():
    # Load teacher
    print("Loading teacher...")
    t_tracker = PoseTracker()
    norm = PoseNormalizer()
    feat = FeatureExtractor()
    cap = cv2.VideoCapture("F:\\ACV\\new folder\\Pushup teacher.mp4")
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
    print("Loading student...")
    s_tracker = PoseTracker()
    feat = FeatureExtractor() # recreate to reset prev_features!
    cap = cv2.VideoCapture("F:\\ACV\\new folder\\APP2\\app\\uploads\\push up 1.webm")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    s_sigs = []
    velocities = []
    idx = 0
    fsm = FSMCounter({'fsm': {'velocity_epsilon': 0.002, 'max_hold_time_frames': 150}})
    fsm.set_teacher_signal_range(pd.signal_min, pd.signal_max)
    states = []
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break
        lms, _ = s_tracker.process_frame(frame, int(idx*1000/fps))
        if lms is not None:
            f = feat.extract(norm.normalize(lms))
            if f is not None:
                s = pd.transform_student(f)
                s_sigs.append(s)
                velocities.append(np.mean(np.abs(f[len(f)//2:])))
                _, _, _, _, state = fsm.process(f, s, idx)
                states.append(state)
        idx += 1
    cap.release()
    s_tracker.close()
    
    print("Teacher min:", pd.signal_min, "max:", pd.signal_max)
    print("Dynamic thresh:", 0.15 * fsm.teacher_signal_range)
    if velocities:
        print("Student max velocity:", np.max(velocities))
        print("Student min signal:", np.min(s_sigs))
        print("Student max signal:", np.max(s_sigs))
        print("States count:", np.bincount(states))
        
        # In ra log của signal và state
        for i, (sig, state) in enumerate(zip(s_sigs, states)):
            if i % 10 == 0 or state != 0:
                print(f"Frame {i:3d}: Sig={sig:6.3f}, State={state}")

if __name__ == "__main__":
    debug()
