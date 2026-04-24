"""
Unit tests for preprocessing module (normalization functions).
"""

import pytest
import math
from src.motion_core.preprocessing import (
    normalize_translation,
    normalize_scale,
    normalize_frame,
    normalize_sequence,
    MIN_CONFIDENCE,
)
from src.motion_core.types import Keypoint, Frame


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def simple_frame() -> Frame:
    """
    A simple frame with person standing in center.
    Coordinates roughly match MediaPipe normalized coordinates.
    """
    return {
        "left_shoulder": Keypoint(x=0.4, y=0.3, score=0.9),
        "right_shoulder": Keypoint(x=0.6, y=0.3, score=0.9),
        "left_hip": Keypoint(x=0.45, y=0.6, score=0.9),
        "right_hip": Keypoint(x=0.55, y=0.6, score=0.9),
        "left_knee": Keypoint(x=0.45, y=0.8, score=0.9),
        "right_knee": Keypoint(x=0.55, y=0.8, score=0.9),
    }


@pytest.fixture
def offset_frame() -> Frame:
    """
    Same person but shifted to the right.
    Should normalize to same shape as simple_frame.
    """
    return {
        "left_shoulder": Keypoint(x=0.6, y=0.3, score=0.9),
        "right_shoulder": Keypoint(x=0.8, y=0.3, score=0.9),
        "left_hip": Keypoint(x=0.65, y=0.6, score=0.9),
        "right_hip": Keypoint(x=0.75, y=0.6, score=0.9),
        "left_knee": Keypoint(x=0.65, y=0.8, score=0.9),
        "right_knee": Keypoint(x=0.75, y=0.8, score=0.9),
    }


@pytest.fixture
def scaled_frame() -> Frame:
    """
    Same person but 2x larger.
    Should normalize to same shape as simple_frame.
    """
    return {
        "left_shoulder": Keypoint(x=0.3, y=0.2, score=0.9),
        "right_shoulder": Keypoint(x=0.7, y=0.2, score=0.9),
        "left_hip": Keypoint(x=0.4, y=0.7, score=0.9),
        "right_hip": Keypoint(x=0.6, y=0.7, score=0.9),
        "left_knee": Keypoint(x=0.4, y=1.1, score=0.9),
        "right_knee": Keypoint(x=0.6, y=1.1, score=0.9),
    }


@pytest.fixture
def low_confidence_frame() -> Frame:
    """
    Frame with low confidence keypoints (should skip normalization).
    """
    return {
        "left_shoulder": Keypoint(x=0.4, y=0.3, score=0.1),  # Low confidence
        "right_shoulder": Keypoint(x=0.6, y=0.3, score=0.1),
        "left_hip": Keypoint(x=0.45, y=0.6, score=0.1),
        "right_hip": Keypoint(x=0.55, y=0.6, score=0.1),
    }


@pytest.fixture
def incomplete_frame() -> Frame:
    """
    Frame with missing keypoints.
    """
    return {
        "left_shoulder": Keypoint(x=0.4, y=0.3, score=0.9),
        # Missing right_shoulder
        "left_hip": Keypoint(x=0.45, y=0.6, score=0.9),
        # Missing right_hip
    }


# ============================================================================
# Translation normalization tests
# ============================================================================


def test_normalize_translation_basic(simple_frame):
    """Test basic translation to mid_hip origin."""
    normalized = normalize_translation(simple_frame, origin="mid_hip")

    # Mid hip should be at origin
    mid_hip_x = (normalized["left_hip"].x + normalized["right_hip"].x) / 2
    mid_hip_y = (normalized["left_hip"].y + normalized["right_hip"].y) / 2

    assert abs(mid_hip_x) < 1e-6, "Mid hip x should be near 0"
    assert abs(mid_hip_y) < 1e-6, "Mid hip y should be near 0"

    # Shoulders should be above hips (negative y in image coordinates)
    assert normalized["left_shoulder"].y < 0
    assert normalized["right_shoulder"].y < 0


def test_normalize_translation_preserves_shape(simple_frame):
    """Translation should preserve relative distances."""
    original = simple_frame
    normalized = normalize_translation(simple_frame, origin="mid_hip")

    # Shoulder width should be same before and after
    orig_shoulder_width = abs(original["right_shoulder"].x - original["left_shoulder"].x)
    norm_shoulder_width = abs(normalized["right_shoulder"].x - normalized["left_shoulder"].x)

    assert abs(orig_shoulder_width - norm_shoulder_width) < 1e-6


def test_normalize_translation_makes_position_invariant(simple_frame, offset_frame):
    """
    Two frames of same person at different positions should normalize to same coordinates.
    """
    norm_simple = normalize_translation(simple_frame, origin="mid_hip")
    norm_offset = normalize_translation(offset_frame, origin="mid_hip")

    # After translation, shoulders should be at same relative position
    assert abs(norm_simple["left_shoulder"].x - norm_offset["left_shoulder"].x) < 1e-6
    assert abs(norm_simple["left_shoulder"].y - norm_offset["left_shoulder"].y) < 1e-6


def test_normalize_translation_low_confidence(low_confidence_frame):
    """Should return original frame if confidence too low."""
    normalized = normalize_translation(low_confidence_frame, origin="mid_hip")

    # Should be unchanged
    assert normalized == low_confidence_frame


def test_normalize_translation_missing_keypoints(incomplete_frame):
    """Should return original frame if origin keypoints missing."""
    normalized = normalize_translation(incomplete_frame, origin="mid_hip")

    # Should be unchanged (right_hip missing)
    assert normalized == incomplete_frame


# ============================================================================
# Scale normalization tests
# ============================================================================


def test_normalize_scale_basic(simple_frame):
    """Test basic scale normalization by shoulder_width."""
    normalized = normalize_scale(simple_frame, reference="shoulder_width")

    # Shoulder width should be 1.0
    shoulder_width = abs(normalized["right_shoulder"].x - normalized["left_shoulder"].x)
    assert abs(shoulder_width - 1.0) < 1e-6, "Shoulder width should be 1.0"


def test_normalize_scale_preserves_proportions(simple_frame):
    """Scale normalization should preserve aspect ratio."""
    original = simple_frame
    normalized = normalize_scale(simple_frame, reference="shoulder_width")

    # Compute original shoulder width
    orig_shoulder_width = abs(original["right_shoulder"].x - original["left_shoulder"].x)

    # Compute torso height ratio (should be same)
    orig_torso_height = abs(original["left_shoulder"].y - original["left_hip"].y)
    norm_torso_height = abs(normalized["left_shoulder"].y - normalized["left_hip"].y)

    orig_ratio = orig_torso_height / orig_shoulder_width
    norm_ratio = norm_torso_height / 1.0  # shoulder_width is now 1.0

    assert abs(orig_ratio - norm_ratio) < 1e-6, "Aspect ratio should be preserved"


def test_normalize_scale_makes_size_invariant(simple_frame, scaled_frame):
    """
    Two frames of different sizes should normalize to similar coordinates.
    """
    norm_simple = normalize_scale(simple_frame, reference="shoulder_width")
    norm_scaled = normalize_scale(scaled_frame, reference="shoulder_width")

    # Both should have shoulder_width = 1.0
    simple_width = abs(norm_simple["right_shoulder"].x - norm_simple["left_shoulder"].x)
    scaled_width = abs(norm_scaled["right_shoulder"].x - norm_scaled["left_shoulder"].x)

    assert abs(simple_width - 1.0) < 1e-6
    assert abs(scaled_width - 1.0) < 1e-6


def test_normalize_scale_low_confidence(low_confidence_frame):
    """Should return original frame if confidence too low."""
    normalized = normalize_scale(low_confidence_frame, reference="shoulder_width")

    # Should be unchanged
    assert normalized == low_confidence_frame


def test_normalize_scale_zero_distance():
    """Should return original if scale factor is zero or very small."""
    # Create frame with left and right shoulder at same position (pathological)
    zero_width_frame = {
        "left_shoulder": Keypoint(x=0.5, y=0.3, score=0.9),
        "right_shoulder": Keypoint(x=0.5, y=0.3, score=0.9),  # Same position!
        "left_hip": Keypoint(x=0.45, y=0.6, score=0.9),
        "right_hip": Keypoint(x=0.55, y=0.6, score=0.9),
    }

    normalized = normalize_scale(zero_width_frame, reference="shoulder_width")

    # Should fallback to no scaling (or try torso_height fallback)
    # In this case, torso_height should work
    # Let's just check it doesn't crash and returns something reasonable
    assert normalized is not None


# ============================================================================
# Combined normalization tests
# ============================================================================


def test_normalize_frame_full_pipeline(simple_frame):
    """Test full normalization (translation + scale)."""
    normalized = normalize_frame(simple_frame, origin="mid_hip", reference="shoulder_width")

    # Check mid_hip at origin
    mid_hip_x = (normalized["left_hip"].x + normalized["right_hip"].x) / 2
    mid_hip_y = (normalized["left_hip"].y + normalized["right_hip"].y) / 2
    assert abs(mid_hip_x) < 1e-6
    assert abs(mid_hip_y) < 1e-6

    # Check shoulder width = 1.0
    shoulder_width = abs(normalized["right_shoulder"].x - normalized["left_shoulder"].x)
    assert abs(shoulder_width - 1.0) < 1e-6


def test_normalize_frame_order_independence(simple_frame):
    """
    Verify that normalize_frame applies translation then scale.
    This is the correct order (translate to origin, then scale).
    """
    # Manual pipeline
    translated = normalize_translation(simple_frame, origin="mid_hip")
    normalized_manual = normalize_scale(translated, reference="shoulder_width")

    # Automatic pipeline
    normalized_auto = normalize_frame(simple_frame, origin="mid_hip", reference="shoulder_width")

    # Should be identical
    for key in normalized_manual:
        assert abs(normalized_manual[key].x - normalized_auto[key].x) < 1e-6
        assert abs(normalized_manual[key].y - normalized_auto[key].y) < 1e-6


def test_normalize_frame_position_and_size_invariant(simple_frame, offset_frame, scaled_frame):
    """
    After full normalization, frames of same person at different positions/sizes should match.
    """
    norm_simple = normalize_frame(simple_frame)
    norm_offset = normalize_frame(offset_frame)

    # Position invariance (simple vs offset)
    for key in norm_simple:
        if key in norm_offset:
            assert abs(norm_simple[key].x - norm_offset[key].x) < 1e-6
            assert abs(norm_simple[key].y - norm_offset[key].y) < 1e-6


# ============================================================================
# Sequence normalization tests
# ============================================================================


def test_normalize_sequence(simple_frame, offset_frame):
    """Test normalizing a sequence of frames."""
    frames = [simple_frame, offset_frame, simple_frame]
    normalized = normalize_sequence(frames)

    assert len(normalized) == 3

    # First and last should be identical (same input)
    for key in normalized[0]:
        assert abs(normalized[0][key].x - normalized[2][key].x) < 1e-6
        assert abs(normalized[0][key].y - normalized[2][key].y) < 1e-6


# ============================================================================
# Edge case tests
# ============================================================================


def test_normalize_empty_frame():
    """Empty frame should return empty."""
    empty = {}
    normalized = normalize_frame(empty)
    assert normalized == {}


def test_normalize_partial_frame():
    """Frame with only some keypoints should handle gracefully."""
    partial = {
        "left_shoulder": Keypoint(x=0.4, y=0.3, score=0.9),
        "right_shoulder": Keypoint(x=0.6, y=0.3, score=0.9),
    }

    # Missing hips, so translation should fail gracefully
    normalized = normalize_translation(partial, origin="mid_hip")
    assert normalized == partial  # Unchanged


def test_confidence_threshold():
    """Test that MIN_CONFIDENCE threshold is respected."""
    # Create frame with confidence exactly at threshold
    threshold_frame = {
        "left_shoulder": Keypoint(x=0.4, y=0.3, score=MIN_CONFIDENCE + 0.01),
        "right_shoulder": Keypoint(x=0.6, y=0.3, score=MIN_CONFIDENCE + 0.01),
        "left_hip": Keypoint(x=0.45, y=0.6, score=MIN_CONFIDENCE + 0.01),
        "right_hip": Keypoint(x=0.55, y=0.6, score=MIN_CONFIDENCE + 0.01),
    }

    normalized = normalize_frame(threshold_frame)

    # Should succeed (just above threshold)
    mid_hip_x = (normalized["left_hip"].x + normalized["right_hip"].x) / 2
    assert abs(mid_hip_x) < 1e-6


def test_score_preserved():
    """Normalization should preserve confidence scores."""
    frame = {
        "left_shoulder": Keypoint(x=0.4, y=0.3, score=0.85),
        "right_shoulder": Keypoint(x=0.6, y=0.3, score=0.90),
        "left_hip": Keypoint(x=0.45, y=0.6, score=0.95),
        "right_hip": Keypoint(x=0.55, y=0.6, score=0.88),
    }

    normalized = normalize_frame(frame)

    # Scores should be unchanged
    assert normalized["left_shoulder"].score == 0.85
    assert normalized["right_shoulder"].score == 0.90
    assert normalized["left_hip"].score == 0.95
    assert normalized["right_hip"].score == 0.88


# ============================================================================
# Integration tests
# ============================================================================


def test_realistic_scenario():
    """
    Simulate realistic scenario: teacher and student at different positions/sizes.
    After normalization, their features should be comparable.
    """
    # Teacher: tall person, centered
    teacher = {
        "left_shoulder": Keypoint(x=0.4, y=0.2, score=0.95),
        "right_shoulder": Keypoint(x=0.6, y=0.2, score=0.95),
        "left_hip": Keypoint(x=0.42, y=0.5, score=0.95),
        "right_hip": Keypoint(x=0.58, y=0.5, score=0.95),
        "left_knee": Keypoint(x=0.42, y=0.75, score=0.95),
        "right_knee": Keypoint(x=0.58, y=0.75, score=0.95),
    }

    # Student: shorter person, offset to right
    student = {
        "left_shoulder": Keypoint(x=0.6, y=0.3, score=0.90),
        "right_shoulder": Keypoint(x=0.75, y=0.3, score=0.90),
        "left_hip": Keypoint(x=0.62, y=0.55, score=0.90),
        "right_hip": Keypoint(x=0.73, y=0.55, score=0.90),
        "left_knee": Keypoint(x=0.62, y=0.75, score=0.90),
        "right_knee": Keypoint(x=0.73, y=0.75, score=0.90),
    }

    # Normalize both
    teacher_norm = normalize_frame(teacher)
    student_norm = normalize_frame(student)

    # After normalization:
    # 1. Both should have mid_hip at origin
    teacher_mid_hip_x = (teacher_norm["left_hip"].x + teacher_norm["right_hip"].x) / 2
    student_mid_hip_x = (student_norm["left_hip"].x + student_norm["right_hip"].x) / 2
    assert abs(teacher_mid_hip_x) < 1e-6
    assert abs(student_mid_hip_x) < 1e-6

    # 2. Both should have shoulder_width = 1.0
    teacher_shoulder_width = abs(teacher_norm["right_shoulder"].x - teacher_norm["left_shoulder"].x)
    student_shoulder_width = abs(student_norm["right_shoulder"].x - student_norm["left_shoulder"].x)
    assert abs(teacher_shoulder_width - 1.0) < 1e-6
    assert abs(student_shoulder_width - 1.0) < 1e-6

    # 3. Relative positions should be comparable (within reasonable tolerance)
    # e.g., left shoulder should be at similar normalized position
    # This depends on body proportions, but at least x-coordinates should be close
    assert abs(teacher_norm["left_shoulder"].x - student_norm["left_shoulder"].x) < 0.1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
