import numpy as np
from fastdtw import fastdtw
from scipy.spatial.distance import euclidean

class DTWAligner:
    def __init__(self, window_size=15):
        self.window_size = window_size
        
    def align(self, teacher_template, student_rep_segment):
        """
        teacher_template: np.array shape (N, D) - Đặc trưng 1 rep chuẩn của giáo viên
        student_rep_segment: np.array shape (M, D) - Đặc trưng rep vừa hoàn thành của học viên
        """
        if teacher_template is None or student_rep_segment is None:
            return None, float('inf')
            
        radius_size = max(len(teacher_template), len(student_rep_segment))
        distance, path = fastdtw(
            teacher_template, 
            student_rep_segment, 
            radius=radius_size, 
            dist=euclidean
        )
        
        # path is a list of tuples: [(t_0, s_0), (t_1, s_1), ..., (t_n, s_m)]
        return path, distance
