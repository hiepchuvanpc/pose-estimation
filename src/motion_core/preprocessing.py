"""
Pose normalization utilities for coordinate preprocessing.

Implements translation and scale normalization to make pose comparison
position-invariant and scale-invariant.
"""

from __future__ import annotations
from typing import Optional
import math
from .types import Frame, Keypoint


# Confidence threshold for normalization (only normalize if keypoints are reliable)
MIN_CONFIDENCE = 0.45


def normalize_translation(frame: Frame, origin: str = "mid_hip") -> Frame:
    """
    Normalize frame by translating coordinate system to specified origin.

    Args:
        frame: Dictionary of keypoint name -> Keypoint
        origin: Reference point for translation ("mid_hip" or keypoint name)

    Returns:
        Translated frame with origin at (0, 0)

    Edge cases:
        - If origin keypoints missing or low confidence: return original frame
        - If origin is "mid_hip" but left/right_hip missing: try pelvis
    """
    # Compute origin point
    origin_point = _get_origin_point(frame, origin)
    if origin_point is None:
        return frame  # Fallback: no normalization

    # Translate all keypoints
    translated = {}
    for name, kp in frame.items():
        translated[name] = Keypoint(
            x=kp.x - origin_point.x,
            y=kp.y - origin_point.y,
            score=kp.score
        )

    return translated


def normalize_scale(frame: Frame, reference: str = "shoulder_width") -> Frame:
    """
    Normalize frame by scaling to unit reference length.

    Args:
        frame: Dictionary of keypoint name -> Keypoint
        reference: Reference measurement ("shoulder_width" or "torso_height")

    Returns:
        Scaled frame where reference measurement = 1.0

    Edge cases:
        - If reference keypoints missing or low confidence: return original frame
        - If reference distance is zero or very small (<0.01): return original frame
    """
    # Compute scale factor
    scale_factor = _get_scale_factor(frame, reference)
    if scale_factor is None or scale_factor < 0.01:
        return frame  # Fallback: no scaling

    # Scale all keypoints
    scaled = {}
    for name, kp in frame.items():
        scaled[name] = Keypoint(
            x=kp.x / scale_factor,
            y=kp.y / scale_factor,
            score=kp.score
        )

    return scaled


def normalize_frame(
    frame: Frame,
    origin: str = "mid_hip",
    reference: str = "shoulder_width"
) -> Frame:
    """
    Apply both translation and scale normalization.

    Order: translate first (to origin), then scale (by reference).
    This makes the result independent of camera position and subject size.

    Args:
        frame: Dictionary of keypoint name -> Keypoint
        origin: Reference point for translation
        reference: Reference measurement for scaling

    Returns:
        Normalized frame (translated to origin, scaled by reference)
    """
    # Step 1: Translate
    translated = normalize_translation(frame, origin)

    # Step 2: Scale
    normalized = normalize_scale(translated, reference)

    return normalized


def normalize_sequence(
    frames: list[Frame],
    origin: str = "mid_hip",
    reference: str = "shoulder_width"
) -> list[Frame]:
    """
    Normalize a sequence of frames.

    Args:
        frames: List of frame dictionaries
        origin: Reference point for translation
        reference: Reference measurement for scaling

    Returns:
        List of normalized frames
    """
    return [normalize_frame(f, origin, reference) for f in frames]


# ============================================================================
# Helper functions
# ============================================================================


def _get_origin_point(frame: Frame, origin: str) -> Optional[Keypoint]:
    """
    Compute origin point for translation normalization.

    Returns None if origin cannot be computed reliably.
    """
    if origin == "mid_hip":
        # Compute midpoint of left and right hip
        left_hip = frame.get("left_hip")
        right_hip = frame.get("right_hip")

        if (left_hip and left_hip.score > MIN_CONFIDENCE and
            right_hip and right_hip.score > MIN_CONFIDENCE):
            return Keypoint(
                x=(left_hip.x + right_hip.x) / 2.0,
                y=(left_hip.y + right_hip.y) / 2.0,
                score=min(left_hip.score, right_hip.score)
            )

        # Fallback: try single pelvis keypoint if available
        pelvis = frame.get("pelvis")
        if pelvis and pelvis.score > MIN_CONFIDENCE:
            return pelvis

        return None

    else:
        # Use specific keypoint as origin
        kp = frame.get(origin)
        if kp and kp.score > MIN_CONFIDENCE:
            return kp
        return None


def _get_scale_factor(frame: Frame, reference: str) -> Optional[float]:
    """
    Compute scale factor for normalization.

    Returns None if scale cannot be computed reliably.
    """
    if reference == "shoulder_width":
        # Distance between left and right shoulder
        left_shoulder = frame.get("left_shoulder")
        right_shoulder = frame.get("right_shoulder")

        if (left_shoulder and left_shoulder.score > MIN_CONFIDENCE and
            right_shoulder and right_shoulder.score > MIN_CONFIDENCE):
            dx = right_shoulder.x - left_shoulder.x
            dy = right_shoulder.y - left_shoulder.y
            distance = math.sqrt(dx * dx + dy * dy)
            return distance if distance > 0.01 else None

        # Fallback: try torso_height
        return _get_scale_factor(frame, "torso_height")

    elif reference == "torso_height":
        # Distance from mid_shoulder to mid_hip
        left_shoulder = frame.get("left_shoulder")
        right_shoulder = frame.get("right_shoulder")
        left_hip = frame.get("left_hip")
        right_hip = frame.get("right_hip")

        if all(kp and kp.score > MIN_CONFIDENCE for kp in [
            left_shoulder, right_shoulder, left_hip, right_hip
        ]):
            mid_shoulder_x = (left_shoulder.x + right_shoulder.x) / 2.0
            mid_shoulder_y = (left_shoulder.y + right_shoulder.y) / 2.0
            mid_hip_x = (left_hip.x + right_hip.x) / 2.0
            mid_hip_y = (left_hip.y + right_hip.y) / 2.0

            dx = mid_shoulder_x - mid_hip_x
            dy = mid_shoulder_y - mid_hip_y
            distance = math.sqrt(dx * dx + dy * dy)
            return distance if distance > 0.01 else None

        return None

    else:
        # Unknown reference type
        return None
