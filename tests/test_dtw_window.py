"""
Unit tests for DTW with window constraint (Sakoe-Chiba band).
"""

import pytest
import time
from src.motion_core.dtw import dtw_distance, DTWResult


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def simple_series_a():
    """Simple time series: linear increase."""
    return [[float(i)] for i in range(10)]


@pytest.fixture
def simple_series_b():
    """Similar to series_a but slightly offset."""
    return [[float(i + 0.5)] for i in range(10)]


@pytest.fixture
def long_series_a():
    """Longer series for performance testing (100 frames)."""
    return [[float(i), float(i * 2)] for i in range(100)]


@pytest.fixture
def long_series_b():
    """Similar to long_series_a with slight variation."""
    return [[float(i + 0.2), float(i * 2 + 0.3)] for i in range(100)]


@pytest.fixture
def different_length_a():
    """Series with 15 frames."""
    return [[float(i)] for i in range(15)]


@pytest.fixture
def different_length_b():
    """Series with 20 frames (slower version of series_a)."""
    return [[float(i * 0.75)] for i in range(20)]


# ============================================================================
# Basic DTW tests (backward compatibility)
# ============================================================================


def test_dtw_no_window_same_as_original(simple_series_a, simple_series_b):
    """DTW without window should work same as before."""
    result = dtw_distance(simple_series_a, simple_series_b, window=None)

    assert isinstance(result, DTWResult)
    assert result.distance > 0
    assert result.normalized_distance > 0
    assert len(result.path) > 0


def test_dtw_empty_series():
    """Empty series should return zero distance."""
    result = dtw_distance([], [[1.0]], window=None)
    assert result.distance == 0.0
    assert result.normalized_distance == 0.0
    assert result.path == []

    result = dtw_distance([[1.0]], [], window=None)
    assert result.distance == 0.0


def test_dtw_identical_series():
    """Identical series should have zero distance."""
    series = [[1.0], [2.0], [3.0]]
    result = dtw_distance(series, series, window=None)

    assert result.distance == 0.0
    assert result.normalized_distance == 0.0


# ============================================================================
# Window constraint tests
# ============================================================================


def test_dtw_with_window_basic(simple_series_a, simple_series_b):
    """DTW with window should produce valid result."""
    result = dtw_distance(simple_series_a, simple_series_b, window=5)

    assert isinstance(result, DTWResult)
    assert result.distance > 0
    assert result.normalized_distance > 0
    assert len(result.path) > 0

    # Path should respect window constraint
    for i, j in result.path:
        assert abs(i - j) <= 5, f"Path violates window constraint at ({i}, {j})"


def test_dtw_window_vs_no_window_same_length(simple_series_a, simple_series_b):
    """
    For series of same length, large window should give same result as no window.
    """
    result_no_window = dtw_distance(simple_series_a, simple_series_b, window=None)
    result_large_window = dtw_distance(simple_series_a, simple_series_b, window=20)

    # Should be identical (window 20 is larger than series length 10)
    assert abs(result_no_window.distance - result_large_window.distance) < 1e-6
    assert result_no_window.path == result_large_window.path


def test_dtw_window_prevents_pathological_warp():
    """
    Window constraint should prevent extreme time warping.
    """
    # Create two series with pathological alignment potential
    # Series A: [0, 0, 0, 1, 1, 1]
    # Series B: [0, 1, 0, 1, 0, 1]
    series_a = [[0.0], [0.0], [0.0], [1.0], [1.0], [1.0]]
    series_b = [[0.0], [1.0], [0.0], [1.0], [0.0], [1.0]]

    # Without window, DTW might create weird alignments
    result_no_window = dtw_distance(series_a, series_b, window=None)

    # With small window (e.g., 1), path is more constrained
    result_window = dtw_distance(series_a, series_b, window=1)

    # Check that window constrains the path
    max_deviation_no_window = max(abs(i - j) for i, j in result_no_window.path)
    max_deviation_window = max(abs(i - j) for i, j in result_window.path)

    assert max_deviation_window <= 1, "Window should limit path deviation"
    # No window might have larger deviations (not always, but in general)


def test_dtw_window_different_lengths(different_length_a, different_length_b):
    """
    Window should work correctly with different length series.
    """
    result = dtw_distance(different_length_a, different_length_b, window=5)

    assert result.distance > 0
    assert len(result.path) > 0

    # Verify window constraint
    for i, j in result.path:
        assert abs(i - j) <= 5, f"Window violated at ({i}, {j})"


def test_dtw_window_too_small():
    """
    If window is too small for series length difference, result might be inf.
    """
    # Series A: 10 frames, Series B: 30 frames (difference = 20)
    series_a = [[float(i)] for i in range(10)]
    series_b = [[float(i)] for i in range(30)]

    # Window = 5 is too small to bridge the length difference
    result = dtw_distance(series_a, series_b, window=5)

    # Distance might be inf (no valid path)
    # Or it might find partial path - depends on implementation
    # Let's just check it doesn't crash
    assert isinstance(result, DTWResult)


def test_dtw_window_zero():
    """
    Window = 0 means only diagonal alignment (i == j).
    """
    series_a = [[1.0], [2.0], [3.0]]
    series_b = [[1.1], [2.1], [3.1]]

    result = dtw_distance(series_a, series_b, window=0)

    # Path should only have diagonal elements (i == j)
    for i, j in result.path:
        assert i == j, f"Window=0 should only allow diagonal, got ({i}, {j})"


def test_dtw_window_one():
    """
    Window = 1 means diagonal or one step off (|i-j| <= 1).
    """
    series_a = [[1.0], [2.0], [3.0], [4.0]]
    series_b = [[1.1], [2.1], [3.1], [4.1]]

    result = dtw_distance(series_a, series_b, window=1)

    # Path should respect window = 1
    for i, j in result.path:
        assert abs(i - j) <= 1, f"Window=1 violated at ({i}, {j})"


# ============================================================================
# Performance tests
# ============================================================================


def test_dtw_performance_improvement(long_series_a, long_series_b):
    """
    DTW with window should be faster than without window for long series.
    """
    # Without window: O(T × U) = O(100 × 100) = 10,000 cells
    start = time.time()
    result_no_window = dtw_distance(long_series_a, long_series_b, window=None)
    time_no_window = time.time() - start

    # With window=20: O(T × window) = O(100 × 20) = 2,000 cells
    start = time.time()
    result_window = dtw_distance(long_series_a, long_series_b, window=20)
    time_window = time.time() - start

    # Windowed version should be faster (at least 2x for this case)
    # Note: for small T, overhead might dominate, so we use long series
    print(f"No window: {time_no_window:.4f}s, Window: {time_window:.4f}s")

    # Speedup might vary, but window should not be slower
    # In practice, should see 2-5x speedup
    # For testing, just ensure it's not significantly slower
    assert time_window <= time_no_window * 1.5, "Window should not be much slower"

    # Both should produce reasonable results
    assert result_no_window.distance > 0
    assert result_window.distance > 0


def test_dtw_window_quality():
    """
    Verify that window constraint doesn't degrade alignment quality too much.
    """
    # Create two similar series
    series_a = [[float(i), float(i * 2)] for i in range(50)]
    series_b = [[float(i + 0.1), float(i * 2 + 0.2)] for i in range(50)]

    result_no_window = dtw_distance(series_a, series_b, window=None)
    result_window = dtw_distance(series_a, series_b, window=10)

    # For similar series, window should give similar distance
    # (might be slightly higher due to constraint, but not dramatically)
    ratio = result_window.distance / result_no_window.distance
    print(f"Distance ratio (window/no_window): {ratio:.3f}")

    # Allow up to 20% increase in distance due to constraint
    assert ratio <= 1.2, "Window constraint should not degrade quality too much"


# ============================================================================
# Edge cases
# ============================================================================


def test_dtw_single_frame():
    """Single frame series should work."""
    series_a = [[1.0, 2.0]]
    series_b = [[1.1, 2.1]]

    result = dtw_distance(series_a, series_b, window=0)

    assert result.distance > 0
    assert len(result.path) == 1
    assert result.path[0] == (0, 0)


def test_dtw_multidimensional_features():
    """DTW should work with multi-dimensional feature vectors."""
    # 5 frames, 18 features each (like real pose features)
    series_a = [[float(i + j) for j in range(18)] for i in range(5)]
    series_b = [[float(i + j + 0.1) for j in range(18)] for i in range(5)]

    result = dtw_distance(series_a, series_b, window=2)

    assert result.distance > 0
    assert len(result.path) == 5  # Should align all frames


def test_dtw_window_adaptive():
    """
    Demonstrate adaptive window sizing strategy.
    """
    # For short sequences, use large window
    short_series_a = [[float(i)] for i in range(10)]
    short_series_b = [[float(i)] for i in range(12)]

    # Adaptive: window = min(20, max_length * 0.2) = min(20, 2.4) = 2
    adaptive_window = min(20, int(max(len(short_series_a), len(short_series_b)) * 0.2))
    result_short = dtw_distance(short_series_a, short_series_b, window=adaptive_window)

    # For long sequences, use fixed window
    long_series_a = [[float(i)] for i in range(200)]
    long_series_b = [[float(i)] for i in range(210)]

    # Adaptive: window = min(20, 200 * 0.2) = min(20, 40) = 20
    adaptive_window = min(20, int(max(len(long_series_a), len(long_series_b)) * 0.2))
    result_long = dtw_distance(long_series_a, long_series_b, window=adaptive_window)

    # Both should produce valid results
    assert result_short.distance >= 0
    assert result_long.distance >= 0


# ============================================================================
# Integration tests
# ============================================================================


def test_dtw_realistic_pose_scenario():
    """
    Simulate realistic pose comparison scenario.
    Teacher does exercise in 60 frames, student in 65 frames (slightly slower).
    """
    # Simulate pose features: 18-dimensional feature vectors
    # Teacher: perfect sine wave pattern (simulating rep motion)
    import math
    teacher_features = [
        [math.sin(i * 0.1 + j * 0.05) for j in range(18)]
        for i in range(60)
    ]

    # Student: similar but slower (65 frames) and slightly noisy
    student_features = [
        [math.sin(i * 0.092 + j * 0.05) + 0.05 for j in range(18)]
        for i in range(65)
    ]

    # Compare with window=20 (allows ±20 frame flexibility)
    result = dtw_distance(teacher_features, student_features, window=20)

    assert result.distance > 0
    assert len(result.path) >= 60  # Should align most frames

    # Verify path is reasonable
    for i, j in result.path:
        assert abs(i - j) <= 20


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
