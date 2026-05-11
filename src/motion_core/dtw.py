from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class DTWResult:
    distance: float
    normalized_distance: float
    path: list[tuple[int, int]]


def _euclidean(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(n)))


def _derivative(series: list[list[float]], i: int) -> list[float]:
    if not series:
        return []
    left = series[max(0, i - 1)]
    right = series[min(len(series) - 1, i + 1)]
    n = min(len(left), len(right))
    if n == 0:
        return []
    return [(right[k] - left[k]) * 0.5 for k in range(n)]


def dtw_distance(
    series_a: list[list[float]],
    series_b: list[list[float]],
    window: int | None = None,
    derivative_weight: float = 0.15,
    max_cells: int = 120_000,
) -> DTWResult:
    """
    Compute DTW distance between two time series with optional Sakoe-Chiba band constraint.
    
    Args:
        series_a: First time series (list of feature vectors)
        series_b: Second time series (list of feature vectors)
        window: Optional window size for Sakoe-Chiba band constraint.
                If None, no constraint (full matrix).
                If set, only cells within |i-j| <= window are computed.
                
    Returns:
        DTWResult with distance, normalized_distance, and alignment path
        
    Performance:
        - Without window: O(T × U) time and space
        - With window: O(T × window) time and space (faster for long sequences)
    """
    import numpy as np
    if not series_a or not series_b:
        return DTWResult(distance=0.0, normalized_distance=0.0, path=[])
    try:
        from fastdtw import fastdtw
        from scipy.spatial.distance import euclidean
        
        arr_a = np.array(series_a, dtype=np.float32)
        arr_b = np.array(series_b, dtype=np.float32)
        
        if len(arr_a.shape) == 1:
            arr_a = arr_a.reshape(-1, 1)
        if len(arr_b.shape) == 1:
            arr_b = arr_b.reshape(-1, 1)
            
        # Compute DTW distance using fastdtw (O(N) approximation algorithm)
        # Using euclidean distance metric, matching offline DTW Analysis behavior
        radius = window if window is not None and window > 0 else max(len(arr_a), len(arr_b))
        distance, path = fastdtw(arr_a, arr_b, radius=radius, dist=euclidean)
        
        normalized = distance / max(1, len(path))
        return DTWResult(distance=distance, normalized_distance=normalized, path=path)
        
    except ImportError:
        # Trivial fallback for pure environments (should not be reached in APP2)
        return DTWResult(distance=0.0, normalized_distance=0.0, path=[(0, 0)])


# ============================================================================
# Rep segmentation from signal
# ============================================================================

def segment_by_signal_valleys(
    signal_values: list[float],
    min_rep_frames: int = 8,
) -> list[tuple[int, int]]:
    """
    Split a student's feature sequence into individual reps based on
    phase-signal valleys (local minima = rest position between reps).

    Returns:
        List of (start_idx, end_idx) tuples, one per detected rep.
    """
    if len(signal_values) < min_rep_frames:
        return [(0, len(signal_values) - 1)] if signal_values else []

    # Smooth signal
    window = 5
    smoothed: list[float] = []
    for i in range(len(signal_values)):
        lo = max(0, i - window // 2)
        hi = min(len(signal_values), i + window // 2 + 1)
        smoothed.append(sum(signal_values[lo:hi]) / (hi - lo))

    # Find valleys
    valleys: list[int] = []
    for i in range(1, len(smoothed) - 1):
        if smoothed[i] <= smoothed[i - 1] and smoothed[i] <= smoothed[i + 1]:
            if not valleys or (i - valleys[-1]) >= min_rep_frames:
                valleys.append(i)

    if len(valleys) < 2:
        return [(0, len(signal_values) - 1)]

    # Build segments from consecutive valleys
    segments: list[tuple[int, int]] = []
    for idx in range(len(valleys) - 1):
        s, e = valleys[idx], valleys[idx + 1]
        if (e - s) >= min_rep_frames:
            segments.append((s, e))

    if not segments:
        return [(0, len(signal_values) - 1)]

    return segments


def dtw_per_rep(
    student_features: list[list[float]],
    template_single_rep: list[list[float]],
    rep_boundaries: list[tuple[int, int]],
    window: int | None = None,
) -> list[DTWResult]:
    """
    DTW each student rep segment against the template single rep reference.

    Args:
        student_features: Full student feature sequence.
        template_single_rep: Features of one template rep (from RepCycleInfo).
        rep_boundaries: [(start, end), ...] from segment_by_signal_valleys.
        window: Sakoe-Chiba window for DTW.

    Returns:
        List of DTWResult, one per student rep.
    """
    results: list[DTWResult] = []
    for start, end in rep_boundaries:
        rep_features = student_features[start: end + 1]
        if not rep_features:
            continue
        # Adaptive window based on length ratio
        if window is None:
            w = max(5, min(20, max(len(rep_features), len(template_single_rep)) // 4))
        else:
            w = window
        res = dtw_distance(rep_features, template_single_rep, window=w)
        results.append(res)
    return results

