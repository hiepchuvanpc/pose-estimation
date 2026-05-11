import numpy as np
from sklearn.decomposition import PCA
from scipy.signal import find_peaks
from core.smoothing import apply_savgol_filter

class PhaseDiscoverer:
    def __init__(self):
        self.pca = PCA(n_components=1)
        self.signal_min = 0.0
        self.signal_max = 0.0
        
    def fit_transform(self, teacher_features_matrix):
        """
        teacher_features_matrix: np.array shape (T, D)
        Trả về 1D signal (T,) và index của các key poses.
        """
        # 1. Chiếu xuống 1D
        signal_1d = self.pca.fit_transform(teacher_features_matrix).flatten()
        
        # 2. Smooth signal
        smoothed_signal = apply_savgol_filter(signal_1d, window_length=15, polyorder=3)
        
        # Cập nhật Min/Max để config FSM
        self.signal_min = np.min(smoothed_signal)
        self.signal_max = np.max(smoothed_signal)
        
        # 3. Tìm Peaks và Valleys
        # Nghịch đảo signal để tìm valleys bằng find_peaks
        peaks, _ = find_peaks(smoothed_signal, prominence=0.05)
        valleys, _ = find_peaks(-smoothed_signal, prominence=0.05)
        
        extrema = np.sort(np.concatenate([peaks, valleys]))
        
        # Key poses là các điểm đảo chiều
        return smoothed_signal, extrema

    def transform_student(self, student_feature_vector):
        """
        Chiếu 1 vector đặc trưng của student xuống không gian PCA của teacher
        """
        if self.pca.components_ is None:
            return 0.0
        # reshape to (1, D)
        vec = student_feature_vector.reshape(1, -1)
        return self.pca.transform(vec)[0, 0]
