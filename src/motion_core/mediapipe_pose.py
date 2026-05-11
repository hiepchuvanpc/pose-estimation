from __future__ import annotations

from typing import Any

from .types import Keypoint

# Canonical names used by motion_core.
LANDMARK_INDEX = {
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


def to_frame_from_mediapipe_landmarks(landmarks: list[Any], frame_width: int, frame_height: int) -> dict[str, Keypoint]:
    frame: dict[str, Keypoint] = {}

    for name, idx in LANDMARK_INDEX.items():
        if idx >= len(landmarks):
            continue
        lm = landmarks[idx]
        x = float(lm.x) * frame_width
        y = float(lm.y) * frame_height
        score = float(getattr(lm, "visibility", 0.0))
        frame[name] = Keypoint(x=x, y=y, score=score)

    left_hip = frame.get("left_hip")
    right_hip = frame.get("right_hip")
    if left_hip and right_hip:
        frame["mid_hip"] = Keypoint(
            x=(left_hip.x + right_hip.x) / 2,
            y=(left_hip.y + right_hip.y) / 2,
            score=min(left_hip.score, right_hip.score),
        )

    neck_left = frame.get("left_shoulder")
    neck_right = frame.get("right_shoulder")
    if neck_left and neck_right:
        frame["neck"] = Keypoint(
            x=(neck_left.x + neck_right.x) / 2,
            y=(neck_left.y + neck_right.y) / 2,
            score=min(neck_left.score, neck_right.score),
        )

    return frame
