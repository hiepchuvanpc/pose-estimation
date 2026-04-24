from __future__ import annotations

from dataclasses import dataclass

from .models import PoseFrame


@dataclass(slots=True)
class PosePipelineConfig:
    root_keypoint: str = "mid_hip"
    scale_pair: tuple[str, str] = ("left_shoulder", "right_shoulder")
    ema_alpha: float = 0.35
    min_confidence: float = 0.2


class PosePipeline:
    """Shared preprocessing for template ingestion, realtime, and post-analysis."""

    def __init__(self, config: PosePipelineConfig | None = None) -> None:
        self.config = config or PosePipelineConfig()
        self._ema_buffer: dict[str, tuple[float, float]] = {}

    def process(self, frame: PoseFrame) -> PoseFrame:
        filled = self._fill_missing_keypoints(frame)
        normalized = self._normalize_translation_and_scale(filled)
        return self._smooth_with_ema(normalized)

    def reset_state(self) -> None:
        self._ema_buffer.clear()

    def _fill_missing_keypoints(self, frame: PoseFrame) -> PoseFrame:
        keypoints = dict(frame.keypoints_xy)
        confidence = dict(frame.keypoint_confidence)
        for name, conf in confidence.items():
            if conf < self.config.min_confidence and name in self._ema_buffer:
                keypoints[name] = self._ema_buffer[name]
        return PoseFrame(
            timestamp_ms=frame.timestamp_ms,
            keypoints_xy=keypoints,
            keypoint_confidence=confidence,
            frame_width=frame.frame_width,
            frame_height=frame.frame_height,
        )

    def _normalize_translation_and_scale(self, frame: PoseFrame) -> PoseFrame:
        keypoints = dict(frame.keypoints_xy)
        root = keypoints.get(self.config.root_keypoint)
        left = keypoints.get(self.config.scale_pair[0])
        right = keypoints.get(self.config.scale_pair[1])
        if root is None or left is None or right is None:
            return frame

        scale = ((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2) ** 0.5
        scale = max(scale, 1e-6)

        normalized = {
            name: ((xy[0] - root[0]) / scale, (xy[1] - root[1]) / scale)
            for name, xy in keypoints.items()
        }

        return PoseFrame(
            timestamp_ms=frame.timestamp_ms,
            keypoints_xy=normalized,
            keypoint_confidence=dict(frame.keypoint_confidence),
            frame_width=frame.frame_width,
            frame_height=frame.frame_height,
        )

    def _smooth_with_ema(self, frame: PoseFrame) -> PoseFrame:
        alpha = self.config.ema_alpha
        smoothed: dict[str, tuple[float, float]] = {}
        for name, point in frame.keypoints_xy.items():
            prev = self._ema_buffer.get(name, point)
            current = (alpha * point[0] + (1 - alpha) * prev[0], alpha * point[1] + (1 - alpha) * prev[1])
            smoothed[name] = current
            self._ema_buffer[name] = current

        return PoseFrame(
            timestamp_ms=frame.timestamp_ms,
            keypoints_xy=smoothed,
            keypoint_confidence=dict(frame.keypoint_confidence),
            frame_width=frame.frame_width,
            frame_height=frame.frame_height,
        )
