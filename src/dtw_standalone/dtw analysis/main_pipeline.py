import cv2
import yaml
import numpy as np
import os
from core.pose_tracker import PoseTracker
from core.normalizer import PoseNormalizer
from core.features import FeatureExtractor
from analysis.phase_discovery import PhaseDiscoverer
from analysis.fsm_counter import FSMCounter
from analysis.dtw_aligner import DTWAligner
from utils.video_muxer import VideoMuxer

def load_config(path="config/exercises.yaml"):
    with open(path, "r", encoding='utf-8') as f:
        return yaml.safe_load(f)

class AIFitnessPipeline:
    def __init__(self, config_path="config/exercises.yaml"):
        self.config = load_config(config_path)
        self.teacher_tracker = PoseTracker()
        self.student_tracker = PoseTracker()
        self.normalizer = PoseNormalizer()
        self.feat_extractor = FeatureExtractor()
        
        self.phase_discoverer = PhaseDiscoverer()
        self.fsm = FSMCounter(self.config)
        self.dtw = DTWAligner(window_size=self.config.get('dtw', {}).get('window_size', 15))
        
        self.teacher_template = []
        self.teacher_frames = []
        self.teacher_results = []
        
    def mirror_landmarks(self, landmarks):
        if landmarks is None: return None
        import numpy as np
        mirrored = np.copy(landmarks)
        swap_pairs = [(1,4), (2,5), (3,6), (7,8), (9,10), (11,12), (13,14), (15,16), (17,18), (19,20), (21,22), (23,24), (25,26), (27,28), (29,30), (31,32)]
        
        for left, right in swap_pairs:
            mirrored[left, 0] = 1.0 - landmarks[right, 0]
            mirrored[left, 1:] = landmarks[right, 1:]
            
            mirrored[right, 0] = 1.0 - landmarks[left, 0]
            mirrored[right, 1:] = landmarks[left, 1:]
            
        mirrored[0, 0] = 1.0 - landmarks[0, 0]
        return mirrored
        
    def process_teacher_video(self, video_path):
        print(f"Processing Teacher Video: {video_path}")
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps == 0 or np.isnan(fps):
            fps = 30.0
            
        features_list = []
        frame_idx = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
                
            self.teacher_frames.append(frame)
            timestamp_ms = int(frame_idx * 1000 / fps)
            landmarks, results = self.teacher_tracker.process_frame(frame, timestamp_ms)
            self.teacher_results.append(results)
            
            if landmarks is not None:
                norm_lm = self.normalizer.normalize(landmarks)
                feats = self.feat_extractor.extract(norm_lm)
                if feats is not None:
                    features_list.append(feats)
            frame_idx += 1
        cap.release()
        
        self.teacher_template = np.array(features_list)
        # Phase Discovery to find PC1
        self.teacher_signal_1d, self.teacher_extrema = self.phase_discoverer.fit_transform(self.teacher_template)
        print(f"Teacher PC1 Signal Range: {self.phase_discoverer.signal_min:.3f} to {self.phase_discoverer.signal_max:.3f}")
        print(f"Teacher PC1 Extrema found: {self.teacher_extrema}")
        
        # Pass signal range to FSM to dynamically compute thresholds
        self.fsm.set_teacher_signal_range(self.phase_discoverer.signal_min, self.phase_discoverer.signal_max)
        
    def process_student_video(self, video_path, output_path):
        print(f"Pass 1: Analyzing Student Video: {video_path}")
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        # Fix WebM weird FPS issues
        if fps == 0 or np.isnan(fps) or fps > 60 or fps < 15:
            fps = 30.0
            
        student_results = []
        student_frames_count = 0
        
        # Mapping mapping global student frame_idx to teacher frame_idx
        # Default is 0 (Teacher stands still at frame 0)
        global_dtw_mapping = {}
        frame_idx = 0
        student_signals_normal = []
        student_signals_mirrored = []
        student_features_normal = []
        student_features_mirrored = []
        student_valid_indices = []
        
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret: break
            
            # Phân tích Pose
            timestamp = int(frame_idx * 1000 / fps)
            landmarks, results = self.student_tracker.process_frame(frame, timestamp)
            student_results.append(results)
            
            if landmarks is not None:
                # Bình thường
                feat_norm = self.feat_extractor.extract(self.normalizer.normalize(landmarks))
                # Mirrored (để chống lỗi khác chân)
                feat_mirr = self.feat_extractor.extract(self.normalizer.normalize(self.mirror_landmarks(landmarks)))
                
                if feat_norm is not None and feat_mirr is not None:
                    student_signals_normal.append(float(self.phase_discoverer.transform_student(feat_norm)))
                    student_signals_mirrored.append(float(self.phase_discoverer.transform_student(feat_mirr)))
                    
                    student_features_normal.append(feat_norm)
                    student_features_mirrored.append(feat_mirr)
                    student_valid_indices.append(frame_idx)
                            
            student_frames_count += 1
            frame_idx += 1
            
        cap.release()
        
        # Xác định tư thế chuẩn (standing) là Peak (đỉnh) hay Valley (đáy)
        teacher_start_val = self.teacher_signal_1d[0]
        teacher_min = self.phase_discoverer.signal_min
        teacher_max = self.phase_discoverer.signal_max
        is_bottom_min = abs(teacher_min - teacher_start_val) > abs(teacher_max - teacher_start_val)

        # Làm mượt tín hiệu học viên để xoá bỏ Jitter do nhiễu khung xương (rất quan trọng để DTW không bị nhiễu)
        if len(student_signals_normal) > 15:
            from scipy.signal import savgol_filter
            student_signals_normal = savgol_filter(student_signals_normal, window_length=15, polyorder=3)
            student_signals_mirrored = savgol_filter(student_signals_mirrored, window_length=15, polyorder=3)

        # Xây dựng tín hiệu hợp nhất cho Peak Detection: Kết hợp cả 2 chân để không bị mất nhịp khi đổi chân (Lunge)
        combined_signals = []
        for i in range(len(student_signals_normal)):
            if is_bottom_min:
                combined_signals.append(min(student_signals_normal[i], student_signals_mirrored[i]))
            else:
                combined_signals.append(max(student_signals_normal[i], student_signals_mirrored[i]))
        
        student_signals = np.array(combined_signals)

        # --- OFFLINE REP DETECTION & DTW MAPPING ---
        print("Pass 1: Running Offline Peak Detection...")
        global_dtw_mapping = {i: 0.0 for i in range(student_frames_count)}
        fsm_states_mapping = {i: 0 for i in range(student_frames_count)}
        rep_count_mapping = {i: 0 for i in range(student_frames_count)}
        scores_mapping = {i: 0.0 for i in range(student_frames_count)}
        
        if len(student_signals) > 0:
            from scipy.signal import find_peaks
            t_range = self.phase_discoverer.signal_max - self.phase_discoverer.signal_min
            
            student_max = np.max(student_signals)
            student_min = np.min(student_signals)
            s_range = student_max - student_min
            
            if is_bottom_min:
                # Bottom là min -> Standing là Peak
                min_height = student_max - 0.35 * s_range
                peaks, _ = find_peaks(student_signals, prominence=0.15 * s_range, distance=35, height=min_height)
            else:
                # Bottom là max -> Standing là Valley (Peak của -signal)
                min_height = -student_min - 0.35 * s_range
                peaks, _ = find_peaks(-student_signals, prominence=0.15 * s_range, distance=35, height=min_height)
                
            # Đảm bảo điểm bắt đầu và kết thúc cũng được tính nếu user đứng thẳng ở đầu/cuối video
            if len(peaks) > 0:
                first_peak = peaks[0]
                last_peak = peaks[-1]
                
                # Chỉ thêm frame 0 nếu nó cách xa first_peak và nó đúng là tư thế đứng
                if first_peak > 30:
                    val_0 = student_signals[0] if is_bottom_min else -student_signals[0]
                    if val_0 > min_height - 0.1 * s_range:
                        peaks = np.insert(peaks, 0, 0)
                        
                if len(student_signals) - 1 - last_peak > 30:
                    val_end = student_signals[-1] if is_bottom_min else -student_signals[-1]
                    if val_end > min_height - 0.1 * s_range:
                        peaks = np.append(peaks, len(student_signals) - 1)
            else:
                peaks = np.array([0, len(student_signals) - 1])

            rep_count = 0
            for i in range(len(peaks) - 1):
                start_idx = peaks[i]
                end_idx = peaks[i+1]
                
                # Xác định chân nào được sử dụng trong rep này
                seg_norm = student_signals_normal[start_idx:end_idx]
                seg_mirr = student_signals_mirrored[start_idx:end_idx]
                rom_norm = np.max(seg_norm) - np.min(seg_norm) if len(seg_norm) > 0 else 0
                rom_mirr = np.max(seg_mirr) - np.min(seg_mirr) if len(seg_mirr) > 0 else 0
                
                if rom_mirr > rom_norm * 1.05:
                    segment_sig = np.array(seg_mirr)
                    segment_features = np.array(student_features_mirrored[start_idx:end_idx])
                    active_leg = "Mirrored"
                else:
                    segment_sig = np.array(seg_norm)
                    segment_features = np.array(student_features_normal[start_idx:end_idx])
                    active_leg = "Normal"
                    
                actual_rom = np.max(segment_sig) - np.min(segment_sig)
                
                # Kiểm tra độ sâu (Depth Check >= 30% teacher range)
                if actual_rom > 0.30 * t_range and len(segment_sig) > 15:
                    rep_count += 1
                    real_frame_indices = student_valid_indices[start_idx:end_idx]
                    
                    print(f"Rep {rep_count} detected: frames {real_frame_indices[0]} to {real_frame_indices[-1]} (ROM: {actual_rom:.2f}, Leg: {active_leg})")
                    
                    # Chuẩn hoá cả 2 tín hiệu về [0, 1] để loại bỏ sự khác biệt về biên độ/nền của PCA
                    t_sig_norm = (self.teacher_signal_1d - teacher_min) / t_range
                    s_sig_norm = (segment_sig - np.min(segment_sig)) / actual_rom
                    
                    t_sig_reshaped = t_sig_norm.reshape(-1, 1)
                    s_sig_reshaped = s_sig_norm.reshape(-1, 1)
                    path, dist = self.dtw.align(t_sig_reshaped, s_sig_reshaped)
                    
                    # Tính điểm (Score) dựa trên Full Features (N-D) để phát hiện sai tư thế/sai chân
                    feature_dist = 0.0
                    for t_idx, s_idx in path:
                        # Euclidean distance
                        feature_dist += np.linalg.norm(self.teacher_template[t_idx] - segment_features[s_idx])
                    
                    avg_feature_dist = feature_dist / len(path)
                    # avg_feature_dist thường nằm trong khoảng 1.0 (chuẩn) đến 6.0 (sai chân/sai tư thế hoàn toàn)
                    last_score = max(0.0, 1.0 - (avg_feature_dist / 6.0))
                    
                    print(f"  -> Alignment 1D dist: {dist:.2f} | Pose N-D dist: {avg_feature_dist:.2f} -> Score: {last_score:.2f}")
                    
                    # Tìm index của điểm sâu nhất (valley)
                    if is_bottom_min:
                        valley_local_idx = np.argmin(segment_sig)
                    else:
                        valley_local_idx = np.argmax(segment_sig)
                    
                    s_to_t = {}
                    for t_idx, s_seg_idx in path:
                        if s_seg_idx not in s_to_t:
                            s_to_t[s_seg_idx] = []
                        s_to_t[s_seg_idx].append(t_idx)
                        
                    s_indices_local = sorted(list(s_to_t.keys()))
                    t_averages = [np.mean(s_to_t[s]) for s in s_indices_local]
                    
                    from scipy.ndimage import gaussian_filter1d
                    if len(t_averages) > 3:
                        t_smooth = gaussian_filter1d(t_averages, sigma=2)
                        # Fix edge effect
                        t_smooth[0] = t_averages[0]
                        t_smooth[-1] = t_averages[-1]
                    else:
                        t_smooth = t_averages
                        
                    t_monotonic = [t_smooth[0]]
                    for val in t_smooth[1:]:
                        t_monotonic.append(max(t_monotonic[-1], val))
                        
                    for j, s_seg_idx in enumerate(s_indices_local):
                        s_global_idx = real_frame_indices[s_seg_idx]
                        t_val = float(t_monotonic[j])
                        t_val = max(0.0, min(t_val, len(self.teacher_frames) - 1.0))
                        global_dtw_mapping[s_global_idx] = t_val
                        scores_mapping[s_global_idx] = last_score
                        
                        # Phân chia ECCENTRIC và CONCENTRIC
                        if s_seg_idx <= valley_local_idx:
                            fsm_states_mapping[s_global_idx] = 1 # ECCENTRIC
                        else:
                            fsm_states_mapping[s_global_idx] = 3 # CONCENTRIC
                            
                        rep_count_mapping[s_global_idx] = rep_count - 1
                        
                    # Cập nhật số Rep cho các khoảng nghỉ (từ sau nhịp này đến hết video)
                    # Các nhịp sau sẽ tự động ghi đè lên giá trị này
                    last_s_global_idx = real_frame_indices[-1]
                    for k in range(last_s_global_idx + 1, student_frames_count):
                        rep_count_mapping[k] = rep_count
        # --- END OFFLINE DETECTION ---
        
        print("Pass 2: Rendering Output Video...")
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        muxer = VideoMuxer(output_path, fps=fps)
        
        cap = cv2.VideoCapture(video_path)
        frame_idx = 0
        
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret or frame_idx >= student_frames_count:
                break
                
            t_val = global_dtw_mapping.get(frame_idx, 0.0)
            state = fsm_states_mapping.get(frame_idx, 0)
            rep = rep_count_mapping.get(frame_idx, 0)
            score = scores_mapping.get(frame_idx, None)
            
            # --- Frame Blending & Motion Blur Logic ---
            if frame_idx == 0:
                last_t_val = t_val
            else:
                last_t_val = global_dtw_mapping.get(frame_idx - 1, 0.0)
                
            if len(self.teacher_frames) > 0:
                if t_val - last_t_val > 1.2:
                    # Fast-forward (Tua nhanh): Sinh ra Motion Blur bằng cách Average tất cả frames bị lướt qua
                    # ĐẢM BẢO KHÔNG MẤT MỘT FRAME NÀO CỦA GIÁO VIÊN
                    start_idx = int(np.floor(last_t_val))
                    end_idx = int(np.ceil(t_val))
                    end_idx = min(end_idx, len(self.teacher_frames) - 1)
                    
                    if end_idx > start_idx:
                        frames_to_blend = self.teacher_frames[start_idx:end_idx+1]
                        blended = frames_to_blend[0].astype(np.float32)
                        for f in frames_to_blend[1:]:
                            blended += f.astype(np.float32)
                        blended = (blended / len(frames_to_blend)).astype(np.uint8)
                        t_frame = blended
                        t_res = self.teacher_results[end_idx]
                    else:
                        t_frame = self.teacher_frames[end_idx]
                        t_res = self.teacher_results[end_idx]
                        
                elif t_val - last_t_val > 0.0 and t_val - last_t_val <= 1.2:
                    # Slow-motion (Tua chậm): Linear Interpolation để làm mượt chuyển động khựng
                    t_idx_lower = int(np.floor(t_val))
                    t_idx_upper = int(np.ceil(t_val))
                    t_idx_upper = min(t_idx_upper, len(self.teacher_frames) - 1)
                    
                    if t_idx_upper > t_idx_lower:
                        weight_upper = t_val - t_idx_lower
                        weight_lower = 1.0 - weight_upper
                        t_frame = cv2.addWeighted(self.teacher_frames[t_idx_lower], weight_lower, 
                                                  self.teacher_frames[t_idx_upper], weight_upper, 0)
                    else:
                        t_frame = self.teacher_frames[t_idx_lower]
                    t_res = self.teacher_results[int(round(t_val))]
                else:
                    # Đứng im (IDLE hoặc Freeze)
                    t_idx = int(round(t_val))
                    t_idx = min(t_idx, len(self.teacher_frames) - 1)
                    t_frame = self.teacher_frames[t_idx]
                    t_res = self.teacher_results[t_idx]
            else:
                t_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                t_res = None
            # ------------------------------------------
            
            s_res = student_results[frame_idx]
            
            muxer.write_side_by_side(t_frame, frame, t_res, s_res, state, rep, score)
            frame_idx += 1
            
        cap.release()
        muxer.close()
        print(f"Output saved to {output_path}")
        
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--teacher", type=str, help="Path to teacher video")
    parser.add_argument("--student", type=str, help="Path to student video")
    parser.add_argument("--output", type=str, default="output.mp4", help="Output path")
    
    args = parser.parse_args()
    if args.teacher and args.student:
        pipeline = AIFitnessPipeline()
        pipeline.process_teacher_video(args.teacher)
        pipeline.process_student_video(args.student, args.output)
    else:
        print("Vui lòng cung cấp --teacher và --student video paths.")
