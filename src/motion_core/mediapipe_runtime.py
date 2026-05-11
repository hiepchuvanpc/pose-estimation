from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.request import urlretrieve

import numpy as np

_POSE_TASK_URLS = {
    "lite": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
    "full": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task",
    "heavy": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task",
}


def _resolve_legacy_pose_class() -> Any:
    import mediapipe as mp

    try:
        return mp.solutions.pose.Pose
    except Exception:
        pass

    try:
        from mediapipe.python.solutions.pose import Pose  # type: ignore

        return Pose
    except Exception:
        return None


def _variant_from_complexity(model_complexity: int) -> str:
    if model_complexity >= 2:
        return "heavy"
    if model_complexity <= 0:
        return "lite"
    return "full"


def _ensure_pose_task_model(model_complexity: int) -> Path:
    explicit = os.getenv("MEDIAPIPE_POSE_TASK_PATH", "").strip()
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if p.exists():
            return p
        raise RuntimeError(f"MEDIAPIPE_POSE_TASK_PATH does not exist: {p}")

    variant = os.getenv("MEDIAPIPE_POSE_MODEL_VARIANT", "").strip().lower() or _variant_from_complexity(model_complexity)
    if variant not in _POSE_TASK_URLS:
        variant = _variant_from_complexity(model_complexity)

    app_root = Path(__file__).resolve().parents[2]
    model_dir = app_root / "data" / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / f"pose_landmarker_{variant}.task"
    if model_path.exists():
        return model_path

    url = _POSE_TASK_URLS[variant]
    tmp_path = model_path.with_suffix(model_path.suffix + ".tmp")
    urlretrieve(url, str(tmp_path))
    tmp_path.replace(model_path)
    return model_path


class _TasksPoseAdapter:
    def __init__(self, landmarker: Any, mp_module: Any) -> None:
        self._landmarker = landmarker
        self._mp = mp_module
        self._timestamp_ms = 0

    def process(self, rgb_image: Any) -> Any:
        mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb_image)
        self._timestamp_ms += 33
        result = self._landmarker.detect_for_video(mp_image, self._timestamp_ms)
        poses = getattr(result, "pose_landmarks", None)
        if not poses:
            return SimpleNamespace(pose_landmarks=None)

        first_pose = poses[0]
        landmarks = [
            SimpleNamespace(
                x=float(lm.x),
                y=float(lm.y),
                z=float(lm.z),
                visibility=float(getattr(lm, "visibility", getattr(lm, "presence", 0.0))),
            )
            for lm in first_pose
        ]
        return SimpleNamespace(pose_landmarks=SimpleNamespace(landmark=landmarks))

    def close(self) -> None:
        if hasattr(self._landmarker, "close"):
            self._landmarker.close()


def _create_tasks_pose_estimator(
    model_complexity: int,
    min_detection_confidence: float,
    min_tracking_confidence: float,
) -> Any:
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    model_path = _ensure_pose_task_model(model_complexity)
    options = vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=min_detection_confidence,
        min_pose_presence_confidence=min_detection_confidence,
        min_tracking_confidence=min_tracking_confidence,
        output_segmentation_masks=False,
    )
    landmarker = vision.PoseLandmarker.create_from_options(options)
    return _TasksPoseAdapter(landmarker=landmarker, mp_module=mp)


def create_pose_estimator(
    static_image_mode: bool = False,
    model_complexity: int = 2,
    smooth_landmarks: bool = False,
    min_detection_confidence: float = 0.5,
    min_tracking_confidence: float = 0.5,
) -> Any:
    # Prefer Tasks Pose Landmarker in VIDEO mode to keep behavior aligned with
    # notebook/runtime pipelines. Fallback to legacy solution only if Tasks init fails.
    try:
        return _create_tasks_pose_estimator(
            model_complexity=model_complexity,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
    except Exception:
        pose_class = _resolve_legacy_pose_class()
        if pose_class is None:
            raise
        return pose_class(
            static_image_mode=static_image_mode,
            model_complexity=model_complexity,
            smooth_landmarks=smooth_landmarks,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
