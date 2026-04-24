"""
Rep cycle detection from template video features.

Detects rep boundaries (valley-to-valley in phase signal) from a template
video that typically contains 1-2 reps.  Extracts a single "best" rep cycle
as the reference for per-rep DTW comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class RepCycleInfo:
    """Result of rep cycle detection from template video."""
    start_pose_idx: int                         # index of start/resting pose
    cycles: list[tuple[int, int]]               # [(start, end), ...] per detected rep
    best_cycle_idx: int                         # which cycle is the reference
    hold_region: tuple[int, int] | None         # (start, end) for hold exercises
    single_cycle_features: list[list[float]]    # features of the best single rep
    single_cycle_samples: list[list[list[float]]]  # pose samples of the best single rep
    rep_count_in_template: int                  # number of reps detected


def _smooth_signal(values: list[float], window: int = 5) -> list[float]:
    """Simple moving-average smoothing."""
    if len(values) <= window:
        return list(values)
    out: list[float] = []
    for i in range(len(values)):
        lo = max(0, i - window // 2)
        hi = min(len(values), i + window // 2 + 1)
        out.append(sum(values[lo:hi]) / (hi - lo))
    return out


def _find_valleys(signal: list[float], min_distance: int = 8) -> list[int]:
    """
    Find local minima (valleys) in signal.
    Valleys mark rep boundaries (rest position between reps).
    """
    if len(signal) < 3:
        return []

    valleys: list[int] = []
    for i in range(1, len(signal) - 1):
        if signal[i] <= signal[i - 1] and signal[i] <= signal[i + 1]:
            # Check minimum distance from previous valley
            if not valleys or (i - valleys[-1]) >= min_distance:
                valleys.append(i)

    return valleys


def _compute_phase_signal(features: list[list[float]]) -> list[float]:
    """Compute PCA-based phase signal for rep detection."""
    arr = np.array(features, dtype=np.float32)
    mean = np.mean(arr, axis=0)
    centered = arr - mean

    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    pc1 = vt[0]
    proj = centered @ pc1

    proj_min = float(np.min(proj))
    proj_max = float(np.max(proj))
    denom = max(proj_max - proj_min, 1e-6)

    return [float((p - proj_min) / denom) for p in proj]


def _cycle_visibility_score(
    samples: list[list[list[float]]],
    start: int,
    end: int,
) -> float:
    """Average core keypoint visibility for a range of samples."""
    core_indices = [11, 12, 23, 24, 25, 26]
    total = 0.0
    count = 0
    for i in range(start, min(end + 1, len(samples))):
        for idx in core_indices:
            if idx < len(samples[i]):
                point = samples[i][idx]
                vis = float(point[3]) if len(point) > 3 else 0.0
                total += vis
                count += 1
    return total / max(count, 1)


def detect_rep_cycles(
    features: list[list[float]],
    samples: list[list[list[float]]],
    mode: str,
    min_rep_frames: int = 8,
) -> RepCycleInfo:
    """
    Detect rep boundaries from template video features.

    For reps mode:
      - Compute phase signal, find valleys, split into cycles.
      - Template typically has 1-2 reps.
      - Pick cycle with highest visibility as reference.

    For hold mode:
      - Entire sequence is the hold region.

    Args:
        features: Feature vectors per frame (from features_from_samples).
        samples: Raw pose samples per frame.
        mode: "reps" or "hold".
        min_rep_frames: Minimum frames for a valid rep segment.
    """
    n = len(features)
    if n < 4:
        return RepCycleInfo(
            start_pose_idx=0,
            cycles=[(0, n - 1)],
            best_cycle_idx=0,
            hold_region=(0, n - 1) if mode == "hold" else None,
            single_cycle_features=features,
            single_cycle_samples=samples[:n],
            rep_count_in_template=1,
        )

    if mode == "hold":
        return RepCycleInfo(
            start_pose_idx=0,
            cycles=[(0, n - 1)],
            best_cycle_idx=0,
            hold_region=(0, n - 1),
            single_cycle_features=features,
            single_cycle_samples=samples[:n],
            rep_count_in_template=1,
        )

    # --- Reps mode ---
    signal = _compute_phase_signal(features)
    smoothed = _smooth_signal(signal, window=5)

    # Find valleys (rest positions between reps)
    valleys = _find_valleys(smoothed, min_distance=min_rep_frames)

    # Build cycles from valleys
    cycles: list[tuple[int, int]] = []

    if len(valleys) >= 2:
        # Each consecutive valley pair is one rep
        for i in range(len(valleys) - 1):
            start = valleys[i]
            end = valleys[i + 1]
            if (end - start) >= min_rep_frames:
                cycles.append((start, end))

        # Also consider start-to-first-valley and last-valley-to-end
        if valleys[0] > min_rep_frames:
            cycles.insert(0, (0, valleys[0]))
        if (n - 1 - valleys[-1]) > min_rep_frames:
            cycles.append((valleys[-1], n - 1))

    elif len(valleys) == 1:
        # One valley: could mark boundary of 1 rep
        v = valleys[0]
        if v > min_rep_frames:
            cycles.append((0, v))
        if (n - 1 - v) > min_rep_frames:
            cycles.append((v, n - 1))

    # Fallback: treat entire sequence as 1 rep
    if not cycles:
        cycles = [(0, n - 1)]

    # Find the start pose (frame closest to signal minimum)
    start_pose_idx = int(np.argmin(smoothed))

    # Pick best cycle by visibility
    if len(cycles) > 1 and len(samples) > 0:
        vis_scores = [
            _cycle_visibility_score(samples, s, e) for s, e in cycles
        ]
        best_cycle_idx = int(np.argmax(vis_scores))
    else:
        best_cycle_idx = 0

    best_start, best_end = cycles[best_cycle_idx]
    single_features = features[best_start: best_end + 1]
    single_samples = samples[best_start: best_end + 1] if samples else []

    return RepCycleInfo(
        start_pose_idx=start_pose_idx,
        cycles=cycles,
        best_cycle_idx=best_cycle_idx,
        hold_region=None,
        single_cycle_features=single_features,
        single_cycle_samples=single_samples,
        rep_count_in_template=len(cycles),
    )
