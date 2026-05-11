import numpy as np

class States:
    IDLE = 0
    ECCENTRIC = 1
    ISOMETRIC = 2
    CONCENTRIC = 3

class FSMCounter:
    def __init__(self, config):
        self.state = States.IDLE
        self.config = config
        self.rep_count = 0
        self.current_rep_frames = []
        self.current_rep_frame_indices = [] # Thêm index để mapping với DTW
        
        self.velocity_epsilon = config.get('fsm', {}).get('velocity_epsilon', 0.002)
        self.max_hold_frames = config.get('fsm', {}).get('max_hold_time_frames', 150)
        
        self.hold_counter = 0
        self.base_signal_val = None
        self.teacher_signal_range = 1.0 # (Max - Min)
        self.eccentric_direction = 1
        self.max_excursion = 0.0
        
    def set_teacher_signal_range(self, signal_min, signal_max):
        self.teacher_signal_range = max(0.1, signal_max - signal_min)
        
    def process(self, feature_vector, motion_signal_1d, frame_idx):
        """
        feature_vector: vector D chiều của current frame
        motion_signal_1d: giá trị scalar (PC1) của current frame
        """
        # Lấy vận tốc từ feature_vector (giả sử nửa sau là velocity)
        half_idx = len(feature_vector) // 2
        velocities = feature_vector[half_idx:]
        avg_velocity = np.mean(np.abs(velocities))
        
        is_moving = avg_velocity > self.velocity_epsilon
        
        rep_completed = False
        segment_features = None
        segment_indices = None
        
        # Ngưỡng kích hoạt bằng 25% của tổng Range bài tập để tránh dính ngưỡng hoàn thành (20%)
        dynamic_threshold = 0.25 * self.teacher_signal_range

        if self.state == States.IDLE:
            if self.base_signal_val is None:
                self.base_signal_val = motion_signal_1d
            else:
                # Update base rất chậm (chỉ 1%) để sửa lỗi drift, không được lớn hơn nếu không sẽ bị "ăn mất" biên độ của rep
                self.base_signal_val = 0.99 * self.base_signal_val + 0.01 * motion_signal_1d
                
            if abs(motion_signal_1d - self.base_signal_val) > dynamic_threshold:
                self.state = States.ECCENTRIC # Bắt đầu Rep
                self.current_rep_frames = [feature_vector]
                self.current_rep_frame_indices = [frame_idx]
                self.max_excursion = motion_signal_1d
                
        elif self.state in [States.ECCENTRIC, States.CONCENTRIC]:
            self.current_rep_frames.append(feature_vector)
            self.current_rep_frame_indices.append(frame_idx)
            
            # Luôn cập nhật điểm xa nhất (Max Excursion)
            dist_to_base = abs(motion_signal_1d - self.base_signal_val)
            if dist_to_base > abs(self.max_excursion - self.base_signal_val):
                self.max_excursion = motion_signal_1d
                
            # Đổi trạng thái hiển thị (ECCENTRIC đi xa base, CONCENTRIC về lại base)
            excursion_diff = abs(self.max_excursion - motion_signal_1d)
            if excursion_diff > (0.15 * self.teacher_signal_range):
                self.state = States.CONCENTRIC
            else:
                self.state = States.ECCENTRIC
                
            # Kiểm tra hoàn thành Rep: Phải đang ở pha đi lên (CONCENTRIC) và quay về gần vị trí ban đầu
            if self.state == States.CONCENTRIC and dist_to_base < (0.2 * self.teacher_signal_range):
                # Kiểm tra độ sâu (Depth Check): Phải đạt ít nhất 35% ROM của Teacher (hỗ trợ Half-rep/Góc máy)
                actual_rom = abs(self.max_excursion - self.base_signal_val)
                if actual_rom > (0.35 * self.teacher_signal_range):
                    self.rep_count += 1
                    rep_completed = True
                    segment_features = np.array(self.current_rep_frames)
                    segment_indices = self.current_rep_frame_indices.copy()
                else:
                    # Lọc nhiễu (Wobble/False Positive): Hủy rep
                    rep_completed = False
                    
                self.state = States.IDLE
                self.current_rep_frames = []
                self.current_rep_frame_indices = []
                self.base_signal_val = motion_signal_1d
                
            # Timeout: Nếu kẹt quá lâu trong 1 rep (300 frames ~ 10s), tự hủy để tránh lỗi
            elif len(self.current_rep_frames) > 300:
                self.state = States.IDLE
                self.current_rep_frames = []
                self.current_rep_frame_indices = []
                self.base_signal_val = motion_signal_1d

        return rep_completed, segment_features, segment_indices, self.rep_count, self.state
