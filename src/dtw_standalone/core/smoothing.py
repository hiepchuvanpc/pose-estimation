import numpy as np
from scipy.signal import savgol_filter

class ExponentialMovingAverage:
    def __init__(self, alpha=0.5):
        self.alpha = alpha
        self.value = None
        
    def process(self, x):
        if self.value is None:
            self.value = x
        else:
            self.value = self.alpha * x + (1 - self.alpha) * self.value
        return self.value

def apply_savgol_filter(signal_1d, window_length=11, polyorder=3):
    """
    Dùng cho offline processing (ví dụ: filter PC1 signal của giáo viên)
    """
    if len(signal_1d) < window_length:
        return signal_1d
    return savgol_filter(signal_1d, window_length, polyorder)
