"""Tests for unified 10-dim feature extraction."""

import math
import numpy as np
import pytest
from src.motion_core.features import (
    features_from_points,
    features_from_sample,
    features_from_samples,
    frame_features,
    FEATURE_DIM,
    ANGLE_TRIPLETS_IDX,
    VECTOR_PAIRS_IDX,
)


def _make_standing_pose_3d():
    """Create a basic standing pose with 33 3D landmarks."""
    pts = np.zeros((33, 3), dtype=np.float32)
    # Shoulders
    pts[11] = [-0.15, -0.4, 0.0]   # left shoulder
    pts[12] = [0.15, -0.4, 0.0]    # right shoulder
    # Elbows
    pts[13] = [-0.20, -0.15, 0.0]  # left elbow
    pts[14] = [0.20, -0.15, 0.0]   # right elbow
    # Wrists
    pts[15] = [-0.22, 0.05, 0.0]   # left wrist
    pts[16] = [0.22, 0.05, 0.0]    # right wrist
    # Hips
    pts[23] = [-0.10, 0.0, 0.0]    # left hip
    pts[24] = [0.10, 0.0, 0.0]     # right hip
    # Knees
    pts[25] = [-0.10, 0.35, 0.0]   # left knee
    pts[26] = [0.10, 0.35, 0.0]    # right knee
    # Ankles
    pts[27] = [-0.10, 0.7, 0.0]    # left ankle
    pts[28] = [0.10, 0.7, 0.0]     # right ankle
    return pts


def test_feature_dim_is_10():
    assert FEATURE_DIM == 10


def test_features_from_points_shape():
    pts = _make_standing_pose_3d()
    features = features_from_points(pts)
    assert len(features) == FEATURE_DIM
    assert len(features) == 10


def test_features_from_points_angles_positive():
    pts = _make_standing_pose_3d()
    features = features_from_points(pts)
    # First 6 should be angles (radians, 0 to pi)
    for i in range(6):
        assert 0 <= features[i] <= math.pi, f"Angle {i} out of range: {features[i]}"


def test_features_from_points_lengths_positive():
    pts = _make_standing_pose_3d()
    features = features_from_points(pts)
    # Indices 6-9 should be normalized lengths (positive)
    for i in range(6, 10):
        assert features[i] > 0, f"Length {i} should be positive: {features[i]}"


def test_rotation_invariance():
    """Angles should not change when all points are rotated."""
    pts = _make_standing_pose_3d()
    features_original = features_from_points(pts)

    # Rotate 30 degrees around Y axis
    angle = math.radians(30)
    rotation = np.array([
        [math.cos(angle), 0, math.sin(angle)],
        [0, 1, 0],
        [-math.sin(angle), 0, math.cos(angle)],
    ], dtype=np.float32)
    pts_rotated = (rotation @ pts.T).T
    features_rotated = features_from_points(pts_rotated)

    # Angles (first 6) should be identical
    for i in range(6):
        assert abs(features_original[i] - features_rotated[i]) < 1e-4, \
            f"Angle {i} changed under rotation: {features_original[i]} vs {features_rotated[i]}"


def test_scale_invariance():
    """Normalised lengths should not change when all points are scaled uniformly."""
    pts = _make_standing_pose_3d()
    features_original = features_from_points(pts)

    # Scale by 2x
    pts_scaled = pts * 2.0
    features_scaled = features_from_points(pts_scaled)

    # Normalised lengths (indices 6-9) should be similar
    for i in range(6, 10):
        assert abs(features_original[i] - features_scaled[i]) < 0.01, \
            f"Normalised length {i} changed under scaling: {features_original[i]} vs {features_scaled[i]}"


def test_features_from_sample():
    """Sample with world coords should produce valid features."""
    sample = [
        [0.5, 0.5, 0.0, 0.9, float(i * 0.01), float(i * 0.02), 0.0, 0.9]
        for i in range(33)
    ]
    features = features_from_sample(sample)
    assert len(features) == FEATURE_DIM


def test_features_from_samples_batch():
    """Batch version should produce N x 10 features."""
    samples = [
        [[0.5, 0.5, 0.0, 0.9, float(i * 0.01), float(j * 0.02), 0.0, 0.9] for i in range(33)]
        for j in range(5)
    ]
    result = features_from_samples(samples)
    assert len(result) == 5
    assert all(len(f) == FEATURE_DIM for f in result)
