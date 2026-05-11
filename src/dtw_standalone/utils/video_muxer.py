import cv2
import numpy as np
from dtw_standalone.utils.visualizer import Visualizer

class VideoMuxer:
    def __init__(self, output_path, fps=30, size=(1280, 480)):
        self.output_path = output_path
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        self.writer = cv2.VideoWriter(output_path, fourcc, fps, size)
        self.visualizer = Visualizer()
        
    def write_side_by_side(self, teacher_frame, student_frame, t_results, s_results, state, rep_count, score):
        # Resize if needed to ensure they are the same height
        th, tw = teacher_frame.shape[:2]
        sh, sw = student_frame.shape[:2]
        
        target_h = 480
        target_tw = int(tw * (target_h / th))
        target_sw = int(sw * (target_h / sh))
        
        t_frame = cv2.resize(teacher_frame, (target_tw, target_h))
        s_frame = cv2.resize(student_frame, (target_sw, target_h))
        
        # Draw skeletons
        t_frame = self.visualizer.draw_landmarks(t_frame, t_results)
        s_frame = self.visualizer.draw_landmarks(s_frame, s_results)
        
        # Draw Overlays on Student
        s_frame = self.visualizer.overlay_fsm_state(s_frame, state, rep_count, score)
        t_frame = self.visualizer.overlay_text(t_frame, "TEACHER", (10, 30), (0, 255, 0), 1.0)
        
        # Hstack
        side_by_side = np.hstack((t_frame, s_frame))
        
        # Resize to fixed output size if necessary, or recreate writer if sizes mismatch.
        # Assuming fixed size for simplicity.
        side_by_side = cv2.resize(side_by_side, (1280, 480))
        
        self.writer.write(side_by_side)
        
    def close(self):
        self.writer.release()
