"""
Pose-based sync alignment for student/teacher video comparison.

Replaces MSE pixel-based alignment with PCA phase-signal + peak-anchored DTW:
  1. Compute phase signal from 10-dim features using template profile PCA
  2. Detect peaks (deepest point of rep) and valleys (rest/top position)
  3. Detect rest segments (student standing still between reps)
  4. Align student→teacher using peak-anchored DTW map
  5. Freeze teacher during student rest periods
"""

from __future__ import annotations

import math

import numpy as np

from .dtw import dtw_distance


# ============================================================================
# Phase signal computation from features + profile
# ============================================================================

def compute_phase_signal(
    features: list[list[float]],
    profile: dict,
) -> list[float]:
    """Compute PCA phase signal for a sequence of feature vectors.

    Uses the template profile's PCA (mean, pc1, proj range) to project
    each feature onto the first principal component, then normalize to [0,1].

    Returns:
        List of phase values in [0, 1], one per frame.
    """
    mean = [float(x) for x in (profile.get("feature_mean") or [])]
    pc1 = [float(x) for x in (profile.get("feature_pc1") or [])]
    proj_min = float(profile.get("proj_min", 0.0))
    proj_max = float(profile.get("proj_max", 1.0))

    if not mean or not pc1:
        return [0.0] * len(features)

    denom = max(1e-6, proj_max - proj_min)
    signals: list[float] = []
    for feat in features:
        centered = [feat[i] - (mean[i] if i < len(mean) else 0.0) for i in range(len(feat))]
        proj = sum(centered[i] * (pc1[i] if i < len(pc1) else 0.0) for i in range(len(centered)))
        s = max(0.0, min(1.0, (proj - proj_min) / denom))
        signals.append(s)
    return signals


def smooth_signal(signal: list[float], window: int = 5) -> list[float]:
    """Moving-average smoothing."""
    if not signal or window <= 1:
        return list(signal)
    win = max(1, int(window))
    out: list[float] = []
    for i in range(len(signal)):
        lo = max(0, i - win // 2)
        hi = min(len(signal), i + win // 2 + 1)
        out.append(sum(signal[lo:hi]) / max(1, hi - lo))
    return out


# ============================================================================
# Extrema detection (peaks and valleys)
# ============================================================================

def detect_phase_extrema(
    signal: list[float],
    min_distance: int = 8,
    prominence_ratio: float = 0.15,
) -> dict:
    """Detect peaks (deepest point of rep) and valleys (rest/top position).

    Convention: signal near 1.0 = peak of movement (deepest squat etc.),
                signal near 0.0 = valley/rest position (standing).

    Args:
        signal: Phase signal [0, 1].
        min_distance: Minimum frames between consecutive extrema.
        prominence_ratio: Minimum height difference as fraction of signal range.

    Returns:
        {"peaks": [idx, ...], "valleys": [idx, ...]}
    """
    if len(signal) < 3:
        return {"peaks": [], "valleys": []}

    arr = np.asarray(signal, dtype=np.float32)
    smoothed = np.convolve(arr, np.ones(5) / 5.0, mode="same").astype(np.float32)

    lo = float(np.min(smoothed))
    hi = float(np.max(smoothed))
    span = hi - lo
    if span < 0.05:
        return {"peaks": [], "valleys": []}

    prominence = span * prominence_ratio

    # Find peaks (local maxima)
    peaks: list[int] = []
    for i in range(1, len(smoothed) - 1):
        if smoothed[i] >= smoothed[i - 1] and smoothed[i] >= smoothed[i + 1]:
            if smoothed[i] >= lo + prominence:
                if not peaks or (i - peaks[-1]) >= min_distance:
                    peaks.append(i)
                elif smoothed[i] > smoothed[peaks[-1]]:
                    peaks[-1] = i

    # Find valleys (local minima)
    valleys: list[int] = []
    for i in range(1, len(smoothed) - 1):
        if smoothed[i] <= smoothed[i - 1] and smoothed[i] <= smoothed[i + 1]:
            if smoothed[i] <= hi - prominence:
                if not valleys or (i - valleys[-1]) >= min_distance:
                    valleys.append(i)
                elif smoothed[i] < smoothed[valleys[-1]]:
                    valleys[-1] = i

    return {"peaks": peaks, "valleys": valleys}


# ============================================================================
# Rest segment detection
# ============================================================================

def _feature_motion(features: list[list[float]], i: int, window: int = 5) -> float:
    """Average per-dimension change around frame i."""
    if not features or i < 0 or i >= len(features):
        return 0.0
    lo = max(0, i - window // 2)
    hi = min(len(features), i + window // 2 + 1)
    if hi - lo < 2:
        return 0.0
    total = 0.0
    count = 0
    for j in range(lo + 1, hi):
        prev = features[j - 1]
        curr = features[j]
        n = min(len(prev), len(curr))
        for k in range(n):
            total += abs(curr[k] - prev[k])
            count += 1
    return total / max(1, count)


def detect_rest_segments(
    signal: list[float],
    features: list[list[float]],
    min_rest_frames: int = 15,
    signal_flatness_threshold: float = 0.08,
    motion_threshold: float = 0.015,
) -> list[tuple[int, int]]:
    """Detect rest segments where student is standing still between reps.

    A rest segment is where:
      - The signal stays flat (low variance) for at least min_rest_frames
      - Feature motion is below threshold (body not moving)

    Args:
        signal: Phase signal [0, 1].
        features: Feature vectors per frame.
        min_rest_frames: Minimum consecutive frames to qualify as rest.
        signal_flatness_threshold: Max signal range within a window to be "flat".
        motion_threshold: Max feature motion to be "still".

    Returns:
        List of (start, end) tuples marking rest segments.
    """
    if len(signal) < min_rest_frames:
        return []

    n = len(signal)
    is_resting = [False] * n
    lo = float(min(signal))
    hi = float(max(signal))
    span = max(1e-6, hi - lo)
    # Rest should happen near top posture band, not at deep/hold positions.
    top_band = lo + (0.38 * span)

    # Mark frames where signal is flat and motion is low
    half_win = min_rest_frames // 2
    for i in range(n):
        lo = max(0, i - half_win)
        hi = min(n, i + half_win + 1)
        window_sig = signal[lo:hi]
        sig_range = max(window_sig) - min(window_sig)
        motion = _feature_motion(features, i, window=min_rest_frames)
        near_top = float(np.median(np.asarray(window_sig, dtype=np.float32))) <= top_band
        is_resting[i] = sig_range < signal_flatness_threshold and motion < motion_threshold and near_top

    # Group consecutive resting frames into segments
    segments: list[tuple[int, int]] = []
    start = None
    for i in range(n):
        if is_resting[i]:
            if start is None:
                start = i
        else:
            if start is not None:
                length = i - start
                if length >= min_rest_frames:
                    segments.append((start, i - 1))
                start = None
    if start is not None and (n - start) >= min_rest_frames:
        segments.append((start, n - 1))

    return segments


def detect_leading_still_prefix(
    signal: list[float],
    features: list[list[float]],
    min_prefix_frames: int = 8,
) -> int:
    """Detect leading still span before the first real movement.

    Returns the end index of the prefix that should stay at teacher top pose,
    or -1 if no stable leading still span is found.
    """
    if not signal:
        return -1
    n = len(signal)
    if n < max(4, min_prefix_frames):
        return -1

    arr = np.asarray(signal, dtype=np.float32)
    lo = float(np.min(arr))
    hi = float(np.max(arr))
    span = hi - lo
    if span < 0.04:
        return n - 1

    low_band = lo + (0.18 * span)
    motions = np.asarray([_feature_motion(features, i, window=7) for i in range(n)], dtype=np.float32)
    motion_thr = max(0.010, float(np.quantile(motions, 0.70)) * 0.85)

    active_streak = 0
    active_start = n
    for i in range(n):
        slope = float(arr[i] - arr[max(0, i - 2)])
        is_active = bool((arr[i] > low_band and slope > (0.03 * span)) or (motions[i] > motion_thr))
        if is_active:
            active_streak += 1
        else:
            active_streak = 0
        if active_streak >= 3:
            active_start = i - 2
            break

    if active_start <= 0:
        return -1
    prefix_end = int(active_start - 1)
    return prefix_end if prefix_end >= int(min_prefix_frames) else -1


# ============================================================================
# Rep segmentation with rest exclusion
# ============================================================================

def segment_reps_by_phase(
    signal: list[float],
    expected_reps: int,
    rest_segments: list[tuple[int, int]] | None = None,
    min_rep_frames: int = 8,
) -> list[tuple[int, int]]:
    """Segment student signal into reps using valley detection, excluding rest periods.

    Args:
        signal: Phase signal [0, 1].
        expected_reps: Expected number of reps.
        rest_segments: Known rest segments to exclude.
        min_rep_frames: Minimum frames per rep.

    Returns:
        List of (start, end) tuples, one per detected rep.
    """
    if not signal:
        return []

    n = len(signal)
    rests = rest_segments or []

    def _in_rest(idx: int) -> bool:
        return any(s <= idx <= e for s, e in rests)

    # Find valleys (potential rep boundaries) - these are low-signal frames not in rest
    smoothed = smooth_signal(signal, window=5)
    valleys: list[int] = []
    min_dist = max(min_rep_frames, 6)

    for i in range(1, n - 1):
        if _in_rest(i):
            continue
        if smoothed[i] <= smoothed[i - 1] and smoothed[i] <= smoothed[i + 1]:
            if not valleys or (i - valleys[-1]) >= min_dist:
                valleys.append(i)

    if len(valleys) < 2:
        # Fallback: one big segment excluding rest
        active_start = 0
        active_end = n - 1
        for s, e in rests:
            if s == 0:
                active_start = e + 1
        for s, e in rests:
            if e == n - 1:
                active_end = s - 1
        if active_end > active_start:
            return [(active_start, active_end)]
        return [(0, n - 1)]

    # Build rep segments from consecutive valleys, skipping rest
    segments: list[tuple[int, int]] = []
    for idx in range(len(valleys) - 1):
        s, e = valleys[idx], valleys[idx + 1]
        if (e - s) < min_rep_frames:
            continue
        # Check if this segment is mostly rest
        rest_frames = sum(1 for i in range(s, e + 1) if _in_rest(i))
        if rest_frames > (e - s) * 0.6:
            continue
        segments.append((s, e))

    if not segments:
        return [(0, n - 1)]

    return segments


# ============================================================================
# Multi-anchor alignment
# ============================================================================

def _find_nearest(candidates: list[int], target: int) -> int | None:
    """Find the candidate closest to target."""
    if not candidates:
        return None
    return min(candidates, key=lambda x: abs(x - target))


def _choose_top_extrema(signal: list[float], valleys: list[int], peaks: list[int]) -> list[int]:
    """Select extrema set representing top/rest posture for current signal convention."""
    if not signal:
        return valleys or peaks or [0]
    if valleys and not peaks:
        return valleys
    if peaks and not valleys:
        return peaks
    if not valleys and not peaks:
        return [0]

    head_n = max(3, int(len(signal) * 0.12))
    head_ref = float(np.median(np.asarray(signal[:head_n], dtype=np.float32)))
    valley_ref = float(np.median(np.asarray([signal[i] for i in valleys], dtype=np.float32))) if valleys else head_ref
    peak_ref = float(np.median(np.asarray([signal[i] for i in peaks], dtype=np.float32))) if peaks else head_ref
    return valleys if abs(head_ref - valley_ref) <= abs(head_ref - peak_ref) else peaks


def _safe_dtw_signal(student_signal: list[float], teacher_signal: list[float]):
    student_series = [[float(v)] for v in student_signal]
    teacher_series = [[float(v)] for v in teacher_signal]
    if not student_series or not teacher_series:
        return dtw_distance([], [], window=None)
    length_gap = abs(len(student_series) - len(teacher_series))
    window = max(length_gap + 2, max(6, max(len(student_series), len(teacher_series)) // 4))
    res = dtw_distance(student_series, teacher_series, window=window)
    if not np.isfinite(res.normalized_distance):
        res = dtw_distance(student_series, teacher_series, window=None)
    return res


def _dense_map_from_path(path: list[tuple[int, int]], student_len: int, teacher_len: int) -> np.ndarray:
    if student_len <= 0 or teacher_len <= 0:
        return np.zeros((0,), dtype=np.int32)
    if not path:
        return np.round(np.linspace(0, max(0, teacher_len - 1), student_len)).astype(np.int32)

    buckets: dict[int, list[int]] = {}
    for s_idx, t_idx in path:
        s = int(s_idx)
        t = int(t_idx)
        if s < 0 or s >= student_len or t < 0 or t >= teacher_len:
            continue
        buckets.setdefault(s, []).append(t)
    if not buckets:
        return np.round(np.linspace(0, max(0, teacher_len - 1), student_len)).astype(np.int32)

    xs = np.array(sorted(buckets.keys()), dtype=np.float32)
    ys = np.array([sum(buckets[int(x)]) / float(len(buckets[int(x)])) for x in xs], dtype=np.float32)
    if len(xs) == 1:
        dense = np.full((student_len,), ys[0], dtype=np.float32)
    else:
        dense = np.interp(np.arange(student_len, dtype=np.float32), xs, ys).astype(np.float32)
    dense = np.clip(np.round(dense), 0, max(0, teacher_len - 1)).astype(np.int32)

    # Keep teacher timeline always moving forward to avoid visual rewinds.
    for i in range(1, len(dense)):
        if dense[i] < dense[i - 1]:
            dense[i] = dense[i - 1]
    return dense


def _peak_anchored_dtw_signal_map(
    student_signal: list[float],
    teacher_signal: list[float],
    *,
    student_peak_idx: int,
    teacher_peak_idx: int,
) -> np.ndarray:
    s_len = len(student_signal)
    t_len = len(teacher_signal)
    if s_len <= 0 or t_len <= 0:
        return np.zeros((0,), dtype=np.int32)

    s_peak = max(0, min(int(student_peak_idx), s_len - 1))
    t_peak = max(0, min(int(teacher_peak_idx), t_len - 1))
    if s_peak <= 0 or s_peak >= (s_len - 1) or t_peak <= 0 or t_peak >= (t_len - 1):
        dtw = _safe_dtw_signal(student_signal, teacher_signal)
        return _dense_map_from_path(list(dtw.path), s_len, t_len)

    left = _safe_dtw_signal(student_signal[: s_peak + 1], teacher_signal[: t_peak + 1])
    right = _safe_dtw_signal(student_signal[s_peak:], teacher_signal[t_peak:])
    if not np.isfinite(left.normalized_distance) or not np.isfinite(right.normalized_distance):
        dtw = _safe_dtw_signal(student_signal, teacher_signal)
        return _dense_map_from_path(list(dtw.path), s_len, t_len)

    left_path = list(left.path)
    right_path = [(s_peak + s_idx, t_peak + t_idx) for s_idx, t_idx in right.path]
    if left_path and right_path and left_path[-1] == right_path[0]:
        merged_path = left_path + right_path[1:]
    else:
        merged_path = left_path + right_path
    return _dense_map_from_path(merged_path, s_len, t_len)


def anchor_align_rep(
    student_signal: list[float],
    teacher_signal: list[float],
    rest_segments: list[tuple[int, int]] | None = None,
) -> np.ndarray:
    """Peak-anchored DTW mapping student frames → teacher frames.

    Strategy:
    1. Detect dominant peak in both student and teacher signals
    2. Split DTW around the peaks so deepest posture is explicitly aligned
    3. Build dense monotonic student→teacher frame map from DTW path
    4. During rest segments: freeze teacher at nearest top/rest frame

    Args:
        student_signal: Student phase signal for one rep [0, 1].
        teacher_signal: Teacher phase signal (full template) [0, 1].
        rest_segments: Rest segments within this rep (relative indices).

    Returns:
        np.ndarray mapping student frame index → teacher frame index.
    """
    s_len = len(student_signal)
    t_len = len(teacher_signal)

    if s_len == 0 or t_len == 0:
        return np.array([], dtype=np.int32)

    rests = rest_segments or []

    # Detect extrema and lock the dominant peak of each rep.
    s_extrema = detect_phase_extrema(student_signal, min_distance=max(4, s_len // 8))
    t_extrema = detect_phase_extrema(teacher_signal, min_distance=max(4, t_len // 8))

    s_peaks = s_extrema["peaks"]
    t_peaks = t_extrema["peaks"]
    t_valleys = t_extrema["valleys"]
    t_top = _choose_top_extrema(teacher_signal, t_valleys, t_peaks)

    student_peak_idx = int(np.argmax(np.asarray(student_signal, dtype=np.float32)))
    teacher_peak_idx = int(np.argmax(np.asarray(teacher_signal, dtype=np.float32)))
    if s_peaks:
        student_peak_idx = max(s_peaks, key=lambda idx: float(student_signal[idx]))
    if t_peaks:
        teacher_peak_idx = max(t_peaks, key=lambda idx: float(teacher_signal[idx]))

    mapping = _peak_anchored_dtw_signal_map(
        student_signal,
        teacher_signal,
        student_peak_idx=student_peak_idx,
        teacher_peak_idx=teacher_peak_idx,
    ).astype(np.float32)

    # Apply rest detection: freeze teacher at nearest valley during rest
    if rests and t_top:
        for rest_start, rest_end in rests:
            # Freeze to teacher top/rest posture, not deep posture.
            freeze_frame = _find_nearest(t_top, int(mapping[min(rest_start, s_len - 1)]))
            if freeze_frame is None:
                freeze_frame = 0
            for i in range(max(0, rest_start), min(s_len, rest_end + 1)):
                mapping[i] = freeze_frame

    return np.clip(np.round(mapping), 0, max(0, t_len - 1)).astype(np.int32)


# ============================================================================
# Full sync pipeline for comparison video
# ============================================================================

def build_sync_mapping(
    student_samples: list[list[list[float]]],
    teacher_samples: list[list[list[float]]],
    profile: dict,
    expected_reps: int = 1,
    student_rep_indices: list[int] | None = None,
) -> dict:
    """Build complete frame mapping for student→teacher sync.

    This uses the new 1D Peak-Anchored DTW pipeline with Auto-Mirroring.
    """
    from scipy.signal import find_peaks
    from scipy.ndimage import gaussian_filter1d
    from .features import features_from_samples
    import copy

    def mirror_pose_samples(samples: list[list[list[float]]]) -> list[list[list[float]]]:
        if not samples: return []
        mirrored = copy.deepcopy(samples)
        swap_pairs = [(1,4), (2,5), (3,6), (7,8), (9,10), (11,12), (13,14), (15,16), (17,18), (19,20), (21,22), (23,24), (25,26), (27,28), (29,30), (31,32)]
        for frame_idx, frame_data in enumerate(mirrored):
            temp_frame = samples[frame_idx]
            for left, right in swap_pairs:
                if left < len(frame_data) and right < len(frame_data):
                    frame_data[left][0] = 1.0 - temp_frame[right][0]
                    frame_data[left][1:4] = temp_frame[right][1:4]
                    if len(frame_data[left]) > 4:
                        frame_data[left][4] = 1.0 - temp_frame[right][4]
                        frame_data[left][5:] = temp_frame[right][5:]
                    frame_data[right][0] = 1.0 - temp_frame[left][0]
                    frame_data[right][1:4] = temp_frame[left][1:4]
                    if len(frame_data[right]) > 4:
                        frame_data[right][4] = 1.0 - temp_frame[left][4]
                        frame_data[right][5:] = temp_frame[left][5:]
            if len(frame_data) > 0:
                frame_data[0][0] = 1.0 - temp_frame[0][0]
                if len(frame_data[0]) > 4:
                    frame_data[0][4] = 1.0 - temp_frame[0][4]
        return mirrored

    teacher_features = features_from_samples(teacher_samples)
    t_len = len(teacher_features)
    s_len = len(student_samples)

    if s_len == 0 or t_len == 0:
        return {
            "teacher_map": np.zeros(max(s_len, 1), dtype=np.int32),
            "frame_rep": np.ones(max(s_len, 1), dtype=np.int32),
            "frame_phase": np.zeros(max(s_len, 1), dtype=np.float32),
            "rest_segments": [],
            "rep_windows": [(0, max(0, s_len - 1))],
            "student_signal": [0.0] * s_len,
            "teacher_signal": [0.0] * t_len,
        }

    # Signal của giáo viên
    teacher_signals = compute_phase_signal(teacher_features, profile)
    
    # Chuẩn bị 2 bộ signal của học viên (Normal & Mirrored)
    student_features_normal = features_from_samples(student_samples)
    student_features_mirrored = features_from_samples(mirror_pose_samples(student_samples))

    student_signals_normal = compute_phase_signal(student_features_normal, profile)
    student_signals_mirrored = compute_phase_signal(student_features_mirrored, profile)

    # Xác định tư thế chuẩn (standing) là Peak (đỉnh) hay Valley (đáy)
    t_sig_np = np.array(teacher_signals)
    t_range = max(1e-6, np.max(t_sig_np) - np.min(t_sig_np))
    teacher_start_val = t_sig_np[0] if t_len > 0 else 0
    is_bottom_min = abs(np.min(t_sig_np) - teacher_start_val) > abs(np.max(t_sig_np) - teacher_start_val)

    if len(student_signals_normal) > 15:
        from scipy.signal import savgol_filter
        student_signals_normal = savgol_filter(student_signals_normal, 15, 3)
        student_signals_mirrored = savgol_filter(student_signals_mirrored, 15, 3)

    # Kết hợp tín hiệu 2 chân để tìm Peak (đảm bảo không rớt nhịp bài tập Lunge/từng bên)
    combined_signals = []
    for i in range(len(student_signals_normal)):
        if is_bottom_min:
            combined_signals.append(min(student_signals_normal[i], student_signals_mirrored[i]))
        else:
            combined_signals.append(max(student_signals_normal[i], student_signals_mirrored[i]))
            
    s_sig_np = np.array(combined_signals)
    student_max = np.max(s_sig_np)
    student_min = np.min(s_sig_np)
    s_range = max(1e-6, student_max - student_min)
    
    if is_bottom_min:
        min_height = student_max - 0.35 * s_range
        peaks, _ = find_peaks(s_sig_np, prominence=0.15 * s_range, distance=35, height=min_height)
    else:
        min_height = -student_min - 0.35 * s_range
        peaks, _ = find_peaks(-s_sig_np, prominence=0.15 * s_range, distance=35, height=min_height)
        
    if len(peaks) > 0:
        if peaks[0] > 30:
            val_0 = s_sig_np[0] if is_bottom_min else -s_sig_np[0]
            if val_0 > min_height - 0.1 * s_range:
                peaks = np.insert(peaks, 0, 0)
        if s_len - 1 - peaks[-1] > 30:
            val_end = s_sig_np[-1] if is_bottom_min else -s_sig_np[-1]
            if val_end > min_height - 0.1 * s_range:
                peaks = np.append(peaks, s_len - 1)
    else:
        peaks = np.array([0, s_len - 1])

    rep_windows = []
    for i in range(len(peaks) - 1):
        rep_windows.append((int(peaks[i]), int(peaks[i+1])))

    global_dtw_mapping = {i: 0.0 for i in range(s_len)}
    
    # Normalize teacher signal to [0, 1]
    t_min = np.min(t_sig_np)
    t_sig_norm = (t_sig_np - t_min) / t_range
    t_sig_reshaped = [[float(v)] for v in t_sig_norm]
    
    for i in range(len(peaks) - 1):
        start_idx = peaks[i]
        end_idx = peaks[i+1]
        
        # Chọn chân (Normal/Mirrored) phù hợp nhất cho nhịp này
        seg_norm = student_signals_normal[start_idx:end_idx]
        seg_mirr = student_signals_mirrored[start_idx:end_idx]
        rom_norm = np.max(seg_norm) - np.min(seg_norm) if len(seg_norm) > 0 else 0
        rom_mirr = np.max(seg_mirr) - np.min(seg_mirr) if len(seg_mirr) > 0 else 0
        
        if rom_mirr > rom_norm * 1.05:
            segment_sig = np.array(seg_mirr)
        else:
            segment_sig = np.array(seg_norm)
        
        if len(segment_sig) < 10:
            continue
            
        actual_rom = np.max(segment_sig) - np.min(segment_sig)
        if actual_rom > 0.30 * t_range:
            # Normalize student segment to [0, 1]
            s_sig_norm = (segment_sig - np.min(segment_sig)) / actual_rom
            s_sig_reshaped = [[float(v)] for v in s_sig_norm]
            dtw_res = dtw_distance(t_sig_reshaped, s_sig_reshaped, window=None)
            path = dtw_res.path
            
            s_to_t = {}
            for t_idx, s_idx in path:
                if s_idx not in s_to_t:
                    s_to_t[s_idx] = []
                s_to_t[s_idx].append(t_idx)
                
            for s_local in sorted(s_to_t.keys()):
                global_dtw_mapping[start_idx + s_local] = np.mean(s_to_t[s_local])
                
    # Nội suy và Filter Mapping
    keys = sorted(global_dtw_mapping.keys())
    values = [global_dtw_mapping[k] for k in keys]
    last_val = values[0]
    for i in range(len(values)):
        if values[i] == 0.0 and i > 0:
            next_val = last_val
            for j in range(i+1, len(values)):
                if values[j] != 0.0:
                    next_val = values[j]
                    break
            values[i] = (last_val + next_val) / 2
        else:
            last_val = values[i]
            
    monotonic_vals = [values[0]]
    for i in range(1, len(values)):
        monotonic_vals.append(max(monotonic_vals[-1], values[i]))
        
    # Smooth with gaussian_filter1d while anchoring endpoints
    if len(monotonic_vals) > 3:
        smoothed_map = gaussian_filter1d(monotonic_vals, sigma=2.0)
        smoothed_map[0] = monotonic_vals[0]
        smoothed_map[-1] = monotonic_vals[-1]
        final_map = np.clip(np.round(smoothed_map), 0, t_len - 1).astype(np.int32)
    else:
        final_map = np.clip(np.round(monotonic_vals), 0, t_len - 1).astype(np.int32)

    frame_rep = np.ones(s_len, dtype=np.int32)
    for rep_idx, (start, end) in enumerate(rep_windows, start=1):
        frame_rep[start:end+1] = rep_idx

    frame_phase = np.zeros(s_len, dtype=np.float32)
    for i in range(s_len):
        frame_phase[i] = float(final_map[i]) / max(1, t_len - 1)

    return {
        "teacher_map": final_map,
        "frame_rep": frame_rep,
        "frame_phase": frame_phase,
        "rest_segments": [],
        "rep_windows": rep_windows,
        "student_signal": student_signals,
        "teacher_signal": teacher_signals,
    }
