"""Tests for rep cycle detection from template video features."""

import math
import pytest
from src.motion_core.rep_cycle import detect_rep_cycles, RepCycleInfo


def _sine_features(n_frames, n_reps=2, n_dims=10):
    """Generate synthetic features with sinusoidal pattern (simulates reps)."""
    features = []
    for i in range(n_frames):
        phase = (i / n_frames) * n_reps * 2 * math.pi
        base = math.sin(phase)
        features.append([base + (j * 0.1) for j in range(n_dims)])
    return features


def _dummy_samples(n_frames, n_landmarks=33, n_values=8):
    """Generate dummy pose samples (visibility = 0.9 for all)."""
    return [
        [[0.5, 0.5, 0.0, 0.9, 0.0, 0.0, 0.0, 0.9] for _ in range(n_landmarks)]
        for _ in range(n_frames)
    ]


def test_detect_single_rep():
    """Template with 1 rep should use entire sequence."""
    features = _sine_features(30, n_reps=1)
    samples = _dummy_samples(30)

    result = detect_rep_cycles(features, samples, mode="reps")

    assert isinstance(result, RepCycleInfo)
    assert result.rep_count_in_template >= 1
    assert len(result.single_cycle_features) > 0
    assert len(result.single_cycle_samples) > 0


def test_detect_two_reps():
    """Template with 2 reps should detect both and pick one as reference."""
    features = _sine_features(60, n_reps=2)
    samples = _dummy_samples(60)

    result = detect_rep_cycles(features, samples, mode="reps")

    assert isinstance(result, RepCycleInfo)
    assert result.rep_count_in_template >= 1
    assert 0 <= result.best_cycle_idx < len(result.cycles)
    assert len(result.single_cycle_features) > 0


def test_hold_mode():
    """Hold mode should use entire sequence as hold region."""
    features = _sine_features(30, n_reps=1)
    samples = _dummy_samples(30)

    result = detect_rep_cycles(features, samples, mode="hold")

    assert result.hold_region is not None
    assert result.hold_region == (0, 29)
    assert len(result.single_cycle_features) == 30


def test_very_short_sequence():
    """Very short sequence should not crash."""
    features = [[0.5] * 10 for _ in range(3)]
    samples = _dummy_samples(3)

    result = detect_rep_cycles(features, samples, mode="reps")

    assert isinstance(result, RepCycleInfo)
    assert result.rep_count_in_template >= 1
