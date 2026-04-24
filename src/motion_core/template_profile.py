from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading

import cv2
import numpy as np

from .mediapipe_runtime import create_pose_estimator
from .features import (
    features_from_sample,
    features_from_samples,
    features_from_landmarks,
    features_from_points,
    ANGLE_TRIPLETS_IDX,
    VECTOR_PAIRS_IDX,
    FEATURE_DIM,
)

CURRENT_FEATURE_VERSION = "v3_angle_length_10d"


@dataclass(frozen=True)
class TemplateProfile:
    feature_mean: list[float]
    feature_pc1: list[float]
    proj_min: float
    proj_max: float
    features: list[list[float]]
    samples: int
    feature_version: str = CURRENT_FEATURE_VERSION


FEATURE_GROUPS = {
    "tay trai": [0, 8, 9],   # left_elbow angle, left_shoulder-wrist length indices
    "tay phai": [1, 9],       # right_elbow angle, right_shoulder-wrist length
    "chan trai": [2, 4, 6],   # left_knee angle, left_hip angle, left_hip-knee length
    "chan phai": [3, 5, 7],   # right_knee angle, right_hip angle, right_hip-knee length
}

POSE_CONNECTIONS = [
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
    (11, 23),
    (12, 24),
    (23, 24),
    (23, 25),
    (25, 27),
    (24, 26),
    (26, 28),
]

JOINT_ANALYSIS_SPECS = [
    {"name": "left_elbow", "label": "khuyu tay trai", "points": (11, 13, 15)},
    {"name": "right_elbow", "label": "khuyu tay phai", "points": (12, 14, 16)},
    {"name": "left_shoulder", "label": "vai trai", "points": (13, 11, 23)},
    {"name": "right_shoulder", "label": "vai phai", "points": (14, 12, 24)},
    {"name": "left_hip", "label": "hong trai", "points": (11, 23, 25)},
    {"name": "right_hip", "label": "hong phai", "points": (12, 24, 26)},
    {"name": "left_knee", "label": "goi trai", "points": (23, 25, 27)},
    {"name": "right_knee", "label": "goi phai", "points": (24, 26, 28)},
]

_POSE_TLS = threading.local()


def _get_pose_estimator():
    pose = getattr(_POSE_TLS, "pose", None)
    if pose is None:
        pose = create_pose_estimator(
            static_image_mode=False,
            model_complexity=2,
            smooth_landmarks=False,
            min_detection_confidence=0.65,
            min_tracking_confidence=0.65,
        )
        _POSE_TLS.pose = pose
    return pose

# ============================================================================
# Profile building
# ============================================================================

def build_template_profile_from_features(features: list[list[float]]) -> TemplateProfile:
    arr = np.array(features, dtype=np.float32)
    mean = np.mean(arr, axis=0)
    centered = arr - mean

    # Principal motion direction for exercise-agnostic progress signal.
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    pc1 = vt[0]
    proj = centered @ pc1

    proj_min = float(np.min(proj))
    proj_max = float(np.max(proj))

    return TemplateProfile(
        feature_mean=mean.tolist(),
        feature_pc1=pc1.tolist(),
        proj_min=proj_min,
        proj_max=proj_max,
        features=arr.tolist(),
        samples=len(features),
        feature_version=CURRENT_FEATURE_VERSION,
    )


# ============================================================================
# Video processing
# ============================================================================

def extract_video_pose_samples(
    video_path: str,
    max_samples: int | None = None,
    frame_stride: int = 1,
    trim_start_sec: float | None = None,
    trim_end_sec: float | None = None,
    flip_h: bool = False,
) -> list[list[list[float]]]:
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    pose = _get_pose_estimator()

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    samples: list[list[list[float]]] = []
    frame_idx = 0

    try:
        while cap.isOpened() and (max_samples is None or len(samples) < max_samples):
            ok, frame = cap.read()
            if not ok:
                break

            current_time_sec = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            
            # Skip frames before start time
            if trim_start_sec is not None and current_time_sec < trim_start_sec:
                frame_idx += 1
                continue
                
            # Stop if past end time
            if trim_end_sec is not None and current_time_sec > trim_end_sec:
                break

            if frame_idx % max(frame_stride, 1) != 0:
                frame_idx += 1
                continue

            if flip_h:
                frame = cv2.flip(frame, 1)

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = pose.process(rgb)
            if result.pose_landmarks is not None:
                world_landmarks = getattr(result, "pose_world_landmarks", None)
                world_points = getattr(world_landmarks, "landmark", None)
                samples.append(
                    [
                        (
                            [
                                float(lm.x),
                                float(lm.y),
                                float(lm.z),
                                float(getattr(lm, "visibility", 0.0)),
                            ]
                            + (
                                [
                                    float(world_points[idx].x),
                                    float(world_points[idx].y),
                                    float(world_points[idx].z),
                                    float(getattr(world_points[idx], "visibility", getattr(world_points[idx], "presence", 0.0))),
                                ]
                                if world_points is not None and idx < len(world_points)
                                else []
                            )
                        )
                        for idx, lm in enumerate(result.pose_landmarks.landmark)
                    ]
                )

            frame_idx += 1
    finally:
        cap.release()

    if len(samples) < 10:
        raise RuntimeError("Not enough valid pose frames from template video")

    return samples


def extract_video_features(
    video_path: str,
    max_samples: int | None = None,
    frame_stride: int = 1,
    trim_start_sec: float | None = None,
    trim_end_sec: float | None = None,
) -> list[list[float]]:
    samples = extract_video_pose_samples(
        video_path,
        max_samples=max_samples,
        frame_stride=frame_stride,
        trim_start_sec=trim_start_sec,
        trim_end_sec=trim_end_sec,
    )
    return features_from_samples(samples)


def build_template_profile_from_video(
    video_path: str,
    max_samples: int | None = None,
    frame_stride: int = 1,
    trim_start_sec: float | None = None,
    trim_end_sec: float | None = None,
) -> TemplateProfile:
    samples = extract_video_pose_samples(
        video_path,
        max_samples=max_samples,
        frame_stride=frame_stride,
        trim_start_sec=trim_start_sec,
        trim_end_sec=trim_end_sec,
    )
    features = features_from_samples(samples)
    return build_template_profile_from_features(features)
