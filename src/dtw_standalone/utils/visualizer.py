import cv2

class Visualizer:
    def __init__(self):
        self.POSE_CONNECTIONS = frozenset([
            (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5),
            (5, 6), (6, 8), (9, 10), (11, 12), (11, 13),
            (13, 15), (15, 17), (15, 19), (15, 21), (17, 19),
            (12, 14), (14, 16), (16, 18), (16, 20), (16, 22),
            (18, 20), (11, 23), (12, 24), (23, 24), (23, 25),
            (24, 26), (25, 27), (26, 28), (27, 29), (28, 30),
            (29, 31), (30, 32), (27, 31), (28, 32)
        ])
        
    def draw_landmarks(self, frame, results):
        if results and results.pose_landmarks:
            h, w, _ = frame.shape
            for pose_landmarks in results.pose_landmarks:
                # Vẽ điểm
                for lm in pose_landmarks:
                    cx, cy = int(lm.x * w), int(lm.y * h)
                    cv2.circle(frame, (cx, cy), 3, (245, 117, 66), -1)
                
                # Vẽ đường nối
                for connection in self.POSE_CONNECTIONS:
                    start_idx, end_idx = connection
                    if start_idx < len(pose_landmarks) and end_idx < len(pose_landmarks):
                        start_lm = pose_landmarks[start_idx]
                        end_lm = pose_landmarks[end_idx]
                        sx, sy = int(start_lm.x * w), int(start_lm.y * h)
                        ex, ey = int(end_lm.x * w), int(end_lm.y * h)
                        cv2.line(frame, (sx, sy), (ex, ey), (245, 66, 230), 2)
        return frame
        
    def overlay_text(self, frame, text, position=(50, 50), color=(0, 255, 0), font_scale=1.0):
        cv2.putText(frame, text, position, cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, 2, cv2.LINE_AA)
        return frame
        
    def overlay_fsm_state(self, frame, state, rep_count, score=None):
        state_map = {0: "IDLE", 1: "ECCENTRIC", 2: "ISOMETRIC", 3: "CONCENTRIC"}
        state_text = f"State: {state_map.get(state, 'UNKNOWN')}"
        rep_text = f"Reps: {rep_count}"
        
        frame = self.overlay_text(frame, state_text, (10, 30), (255, 255, 0), 0.8)
        frame = self.overlay_text(frame, rep_text, (10, 60), (0, 255, 255), 0.8)
        
        if score is not None:
            score_text = f"Match Score: {score:.2f}"
            frame = self.overlay_text(frame, score_text, (10, 90), (0, 165, 255), 0.8)
            
        return frame
