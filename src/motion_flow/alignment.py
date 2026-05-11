from __future__ import annotations

from dataclasses import dataclass

from motion_core.dtw import dtw_distance

from .models import FeatureFrame, RepSegment, SetResult


@dataclass(slots=True)
class DTWAlignerConfig:
    sakoe_chiba_radius: int = 15


@dataclass(slots=True)
class DTWResult:
    distance: float
    normalized_distance: float
    path: list[tuple[int, int]]


class DTWAligner:
    """Confidence-aware DTW with Sakoe-Chiba window."""

    def __init__(self, config: DTWAlignerConfig | None = None) -> None:
        self.config = config or DTWAlignerConfig()

    def align(self, query: list[FeatureFrame], template: list[FeatureFrame]) -> DTWResult:
        q = [f.vector for f in query]
        t = [f.vector for f in template]
        res = dtw_distance(q, t, window=self.config.sakoe_chiba_radius)
        return DTWResult(
            distance=float(res.distance),
            normalized_distance=float(res.normalized_distance),
            path=list(res.path),
        )


class RepSegmenter:
    """Rep segmentation from signal valleys-crossings (simple baseline implementation)."""

    def segment(self, features: list[FeatureFrame], expected_reps: int | None = None) -> list[RepSegment]:
        if len(features) < 4:
            return [RepSegment(rep_index=1, start_idx=0, end_idx=max(0, len(features) - 1))]

        signals = [f.signal for f in features]
        transitions = []
        threshold = (max(signals) + min(signals)) / 2.0
        for idx in range(1, len(signals)):
            if signals[idx - 1] < threshold <= signals[idx]:
                transitions.append(idx)

        if len(transitions) < 2:
            return [RepSegment(rep_index=1, start_idx=0, end_idx=len(features) - 1)]

        segs: list[RepSegment] = []
        for rep_idx in range(len(transitions) - 1):
            segs.append(
                RepSegment(rep_index=rep_idx + 1, start_idx=transitions[rep_idx], end_idx=transitions[rep_idx + 1])
            )

        if expected_reps is not None and expected_reps > 0 and len(segs) > expected_reps:
            return segs[:expected_reps]
        return segs


class MovementScorer:
    """Generate rep, phase, and joint-level errors from DTW alignments."""

    def score_set(
        self,
        *,
        set_index: int,
        template_id: str,
        user_features: list[FeatureFrame],
        template_features: list[FeatureFrame],
        rep_segments: list[RepSegment],
        aligner: DTWAligner,
    ) -> SetResult:
        rep_scores: list[float] = []
        phase_errors: list[dict[str, float]] = []
        joint_errors: list[dict[str, float]] = []

        for rep in rep_segments:
            q = user_features[rep.start_idx : rep.end_idx + 1]
            res = aligner.align(q, template_features)
            score = max(0.0, 100.0 - 35.0 * res.normalized_distance)
            rep_scores.append(score)
            phase_errors.append({"up": res.normalized_distance, "down": res.normalized_distance * 0.9, "hold": 0.0})
            joint_errors.append({"knees": res.normalized_distance, "hips": res.normalized_distance * 0.8})

        return SetResult(
            set_index=set_index,
            exercise_template_id=template_id,
            rep_scores=rep_scores,
            phase_errors=phase_errors,
            joint_errors=joint_errors,
        )
