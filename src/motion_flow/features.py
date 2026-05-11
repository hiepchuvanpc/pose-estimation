from __future__ import annotations

from dataclasses import dataclass

from motion_core.features import frame_features, FEATURE_DIM

from ._core_bridge import to_core_frame
from .models import FeatureFrame, PoseFrame


@dataclass(slots=True)
class FeatureExtractorConfig:
    signal_feature_index: int = 2  # left knee angle in motion_core 10D layout


class FeatureExtractor:
    """Build confidence-aware features using the unified motion_core 10D pipeline."""

    def __init__(self, config: FeatureExtractorConfig | None = None) -> None:
        self.config = config or FeatureExtractorConfig()
        self._prev_angles: list[float] | None = None
        self._prev_ts: int | None = None

    def reset_state(self) -> None:
        self._prev_angles = None
        self._prev_ts = None

    def extract(self, frame: PoseFrame) -> FeatureFrame:
        vector = frame_features(to_core_frame(frame))
        if len(vector) != FEATURE_DIM:
            vector = [0.0 for _ in range(FEATURE_DIM)]
        signal_idx = max(0, min(self.config.signal_feature_index, len(vector) - 1))
        signal = max(0.0, min(1.0, float(vector[signal_idx]) / 3.141592653589793))
        return FeatureFrame(timestamp_ms=frame.timestamp_ms, vector=vector, signal=signal)
