from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PoseFrame:
    """Normalized pose frame with confidence values per keypoint."""

    timestamp_ms: int
    keypoints_xy: dict[str, tuple[float, float]]
    keypoint_confidence: dict[str, float]
    frame_width: int | None = None
    frame_height: int | None = None


@dataclass(slots=True)
class FeatureFrame:
    """Feature vector extracted from a pose frame."""

    timestamp_ms: int
    vector: list[float]
    signal: float
    phase: str | None = None


@dataclass(slots=True)
class RepSegment:
    """Frame index span for one repetition."""

    rep_index: int
    start_idx: int
    end_idx: int
    phase_boundaries: dict[str, tuple[int, int]] = field(default_factory=dict)


@dataclass(slots=True)
class ExerciseTemplate:
    """User-facing metadata for an exercise template."""

    template_id: str
    name: str
    view: str
    posture: str
    source_uri: str
    mode: str
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SetResult:
    """Post-analysis output for a completed set."""

    set_index: int
    exercise_template_id: str
    rep_scores: list[float]
    phase_errors: list[dict[str, float]]
    joint_errors: list[dict[str, float]]
    aligned_video_uri: str | None = None
    feedback: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SessionResult:
    """Aggregated full-session report."""

    session_id: str
    set_results: list[SetResult]
    summary_feedback: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)
