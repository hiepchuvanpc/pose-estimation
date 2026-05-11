from __future__ import annotations

from dataclasses import dataclass

from motion_core.readiness import ReadinessParams, readiness_score, readiness_feedback

from ._core_bridge import to_core_frame
from .models import PoseFrame


@dataclass(slots=True)
class ReadinessThresholds:
    min_view: float = 0.55
    min_completeness: float = 0.65
    min_framing: float = 0.60
    weights: tuple[float, float, float] = (0.4, 0.4, 0.2)


@dataclass(slots=True)
class ReadinessReport:
    score: float
    view_similarity: float
    completeness: float
    framing: float
    ready: bool
    feedback: list[str]


class ReadinessEvaluator:
    """Readiness gate before tracking or scoring can proceed."""

    def __init__(self, thresholds: ReadinessThresholds | None = None) -> None:
        self.thresholds = thresholds or ReadinessThresholds()

    def evaluate(self, frame: PoseFrame, template_anchor: PoseFrame | None = None) -> ReadinessReport:
        width = int(frame.frame_width or 1)
        height = int(frame.frame_height or 1)
        student_core = to_core_frame(frame)
        anchor_core = to_core_frame(template_anchor) if template_anchor is not None else student_core

        params = ReadinessParams(
            alpha=self.thresholds.weights[0],
            beta=self.thresholds.weights[1],
            gamma=self.thresholds.weights[2],
            min_readiness=self.thresholds.min_view,
            min_completeness=self.thresholds.min_completeness,
        )
        score, view, completeness, framing = readiness_score(
            student=student_core,
            teacher=anchor_core,
            frame_width=max(1, width),
            frame_height=max(1, height),
            params=params,
        )
        ready = score >= params.min_readiness and completeness >= params.min_completeness and framing >= self.thresholds.min_framing
        return ReadinessReport(
            score=score,
            view_similarity=view,
            completeness=completeness,
            framing=framing,
            ready=ready,
            feedback=readiness_feedback(view, completeness, framing, params),
        )
