"""
Unified feature extraction for pose comparison.

Produces a 10-dimensional feature vector per frame:
  - 6 joint angles (rotation-invariant)
  - 4 normalised limb lengths (scale-invariant via torso normalisation)

Both template (from stored pose samples) and realtime (from Frame/Frame3D)
paths produce the SAME feature layout so DTW comparison is consistent.
"""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np

from .types import Frame, Frame3D, Keypoint, Keypoint3D

# ---------------------------------------------------------------------------
# Angle triplets – same joints as before, using MediaPipe landmark indices
# ---------------------------------------------------------------------------
ANGLE_TRIPLETS_IDX = [
    (11, 13, 15),   # left elbow
    (12, 14, 16),   # right elbow
    (23, 25, 27),   # left knee
    (24, 26, 28),   # right knee
    (11, 23, 25),   # left hip
    (12, 24, 26),   # right hip
]

ANGLE_TRIPLETS_NAME = [
    ("left_shoulder", "left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow", "right_wrist"),
    ("left_hip", "left_knee", "left_ankle"),
    ("right_hip", "right_knee", "right_ankle"),
    ("left_shoulder", "left_hip", "left_knee"),
    ("right_shoulder", "right_hip", "right_knee"),
]

# ---------------------------------------------------------------------------
# Vector pairs – for normalised limb length features
# ---------------------------------------------------------------------------
VECTOR_PAIRS_IDX = [
    (23, 25),   # left hip-knee
    (24, 26),   # right hip-knee
    (11, 15),   # left shoulder-wrist
    (12, 16),   # right shoulder-wrist
]

VECTOR_PAIRS_NAME = [
    ("left_hip", "left_knee"),
    ("right_hip", "right_knee"),
    ("left_shoulder", "left_wrist"),
    ("right_shoulder", "right_wrist"),
]

FEATURE_DIM = len(ANGLE_TRIPLETS_IDX) + len(VECTOR_PAIRS_IDX)  # 10


# ============================================================================
# Low-level helpers
# ============================================================================

def _angle_3pts(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """Angle at point *b* formed by segments ba and bc (radians)."""
    ba = a - b
    bc = c - b
    nba = float(np.linalg.norm(ba))
    nbc = float(np.linalg.norm(bc))
    if nba < 1e-6 or nbc < 1e-6:
        return 0.0
    cos_val = float(np.clip(np.dot(ba, bc) / (nba * nbc), -1.0, 1.0))
    return float(np.arccos(cos_val))


def _torso_height(pts: np.ndarray) -> float:
    """Distance from mid-shoulder to mid-hip (for length normalisation)."""
    mid_shoulder = (pts[11] + pts[12]) / 2.0
    mid_hip = (pts[23] + pts[24]) / 2.0
    return max(float(np.linalg.norm(mid_shoulder - mid_hip)), 1e-6)


def _vec_length(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(b - a))


# ============================================================================
# Feature from raw 3D point array  (shared by template & sample paths)
# ============================================================================

def features_from_points(pts: np.ndarray) -> list[float]:
    """
    Extract 10-dim feature from an (N, 3) array of 3D landmark positions.
    
    Returns:
        [angle0..angle5, norm_len0..norm_len3]
    """
    features: list[float] = []
    torso = _torso_height(pts)

    # 6 angles
    for a, b, c in ANGLE_TRIPLETS_IDX:
        features.append(_angle_3pts(pts[a], pts[b], pts[c]))

    # 4 normalised lengths
    for a, b in VECTOR_PAIRS_IDX:
        features.append(_vec_length(pts[a], pts[b]) / torso)

    return features


# ============================================================================
# Feature from stored pose sample  (list of per-landmark lists)
# ============================================================================

def _sample_point_xyz(point: list[float]) -> np.ndarray:
    """Pick world coordinates if available (indices 4-6), else image coords."""
    if len(point) >= 7:
        return np.array([point[4], point[5], point[6]], dtype=np.float32)
    return np.array([point[0], point[1], point[2]], dtype=np.float32)


def features_from_sample(sample: list[list[float]]) -> list[float]:
    """Extract 10-dim feature from a stored pose sample (list of 33 points)."""
    pts = np.array([_sample_point_xyz(p) for p in sample], dtype=np.float32)
    return features_from_points(pts)


def features_from_samples(samples: list[list[list[float]]]) -> list[list[float]]:
    """Batch version of features_from_sample."""
    return [features_from_sample(s) for s in samples]


# ============================================================================
# Feature from MediaPipe landmarks (live detection result)
# ============================================================================

def features_from_landmarks(landmarks: list, world_landmarks: list | None = None) -> list[float]:
    """
    Extract 10-dim feature from MediaPipe landmark objects.
    Prefers world_landmarks (metric 3D) when available.
    """
    pts = np.zeros((max(33, len(landmarks)), 3), dtype=np.float32)
    for idx, lm in enumerate(landmarks):
        if world_landmarks and idx < len(world_landmarks):
            wlm = world_landmarks[idx]
            pts[idx] = [float(wlm.x), float(wlm.y), float(wlm.z)]
        else:
            pts[idx] = [float(lm.x), float(lm.y), float(lm.z)]
    return features_from_points(pts)


# ============================================================================
# Feature from Frame / Frame3D  (named-keypoint dicts used by readiness etc.)
# ============================================================================

_NAME_TO_IDX = {
    "nose": 0,
    "left_eye": 2,
    "right_eye": 5,
    "left_ear": 7,
    "right_ear": 8,
    "left_shoulder": 11,
    "right_shoulder": 12,
    "left_elbow": 13,
    "right_elbow": 14,
    "left_wrist": 15,
    "right_wrist": 16,
    "left_hip": 23,
    "right_hip": 24,
    "left_knee": 25,
    "right_knee": 26,
    "left_ankle": 27,
    "right_ankle": 28,
}


def frame_features(frame: Frame) -> list[float]:
    """
    Extract 10-dim feature from a Frame (2D keypoints).
    Uses (x, y, 0) as 3D coords – suitable for angle computation.
    """
    pts = np.zeros((33, 3), dtype=np.float32)
    for name, idx in _NAME_TO_IDX.items():
        kp = frame.get(name)
        if kp is not None:
            pts[idx] = [kp.x, kp.y, 0.0]
    return features_from_points(pts)


def frame3d_features(frame3d: Frame3D) -> list[float]:
    """
    Extract 10-dim feature from a Frame3D (3D keypoints with world coords).
    Uses world coordinates when available.
    """
    pts = np.zeros((33, 3), dtype=np.float32)
    for name, idx in _NAME_TO_IDX.items():
        kp = frame3d.get(name)
        if kp is not None:
            # Prefer world coordinates
            if abs(kp.wx) > 1e-9 or abs(kp.wy) > 1e-9 or abs(kp.wz) > 1e-9:
                pts[idx] = [kp.wx, kp.wy, kp.wz]
            else:
                pts[idx] = [kp.x, kp.y, kp.z]
    return features_from_points(pts)


def sequence_features(frames: Iterable[Frame]) -> list[list[float]]:
    """Extract features for a sequence of Frame dicts."""
    return [frame_features(f) for f in frames]
