from __future__ import annotations

from dataclasses import dataclass

from .alignment import DTWAligner, MovementScorer, RepSegmenter
from .features import FeatureExtractor
from .feedback import FeedbackGenerator
from .models import ExerciseTemplate, PoseFrame, SessionResult
from .pipeline import PosePipeline
from .readiness import ReadinessEvaluator, ReadinessReport
from .template_management import TemplateLibrary, TemplateProfile
from .tracking import PhaseDetector, TempoAnalyzer
from .workout import WorkoutExercisePlan, WorkoutSession


@dataclass(slots=True)
class RealtimeUpdate:
    readiness: ReadinessReport
    phase: str
    reps: int
    hold_seconds: float
    set_completed: bool
    tempo_snapshot: dict[str, float]


class AIFitnessCoach:
    """Single continuous workflow: template ingestion -> realtime -> per-set DTW analysis."""

    def __init__(self) -> None:
        self.library = TemplateLibrary()
        self.pipeline = PosePipeline()
        self.extractor = FeatureExtractor()
        self.readiness = ReadinessEvaluator()
        self.phase_detector = PhaseDetector()
        self.tempo = TempoAnalyzer()
        self.aligner = DTWAligner()
        self.segmenter = RepSegmenter()
        self.scorer = MovementScorer()
        self.feedback = FeedbackGenerator()
        self._session: WorkoutSession | None = None
        self._set_results = []

    def ingest_template(self, template: ExerciseTemplate, pose_frames: list[PoseFrame]) -> TemplateProfile:
        self.pipeline.reset_state()
        self.extractor.reset_state()
        features = [self.extractor.extract(self.pipeline.process(f)) for f in pose_frames]
        profile = TemplateProfile.from_feature_sequence(template, features)
        self.library.add_template(profile)
        return profile

    def start_session(self, session_id: str, plans: list[WorkoutExercisePlan]) -> None:
        self._session = WorkoutSession(session_id=session_id, plans=plans)
        self._set_results = []
        self.pipeline.reset_state()
        self.extractor.reset_state()

    def process_realtime_frame(self, frame: PoseFrame) -> RealtimeUpdate:
        if self._session is None:
            raise RuntimeError("Session not started")

        template_id = self._session.current_plan.template.template_id
        profile = self.library.get_template(template_id)
        anchor = self._anchor_pose_from_profile(profile, frame.timestamp_ms)

        normalized = self.pipeline.process(frame)
        readiness = self.readiness.evaluate(normalized, anchor)
        if not readiness.ready:
            return RealtimeUpdate(
                readiness=readiness,
                phase="blocked",
                reps=0,
                hold_seconds=0.0,
                set_completed=False,
                tempo_snapshot=self.tempo.snapshot(),
            )

        feature = self.extractor.extract(normalized)
        phase = self.phase_detector.detect(feature.signal)
        self.tempo.update(phase if phase in {"up", "down"} else "hold", feature.timestamp_ms)
        state = self._session.on_feature(normalized, feature)

        return RealtimeUpdate(
            readiness=readiness,
            phase=phase,
            reps=int(state["reps"]),
            hold_seconds=float(state["hold_seconds"]),
            set_completed=bool(state["set_completed"]),
            tempo_snapshot=self.tempo.snapshot(),
        )

    def complete_current_set(self) -> None:
        if self._session is None:
            raise RuntimeError("Session not started")

        active_template_id = self._session.current_plan.template.template_id
        active_set = self._session.current_set_plan
        recorder = self._session.complete_set()
        profile = self.library.get_template(active_template_id)
        expected_reps = active_set.target_reps
        segments = self.segmenter.segment(recorder.features, expected_reps=expected_reps)
        result = self.scorer.score_set(
            set_index=recorder.set_index,
            template_id=active_template_id,
            user_features=recorder.features,
            template_features=profile.feature_sequence,
            rep_segments=segments,
            aligner=self.aligner,
        )
        result.feedback = self.feedback.per_set_feedback(result)
        self._set_results.append(result)

    def finalize_session(self) -> SessionResult:
        if self._session is None:
            raise RuntimeError("Session not started")
        out = SessionResult(
            session_id=self._session.session_id,
            set_results=list(self._set_results),
            summary_feedback=[],
        )
        out.summary_feedback = self.feedback.session_summary(out)
        return out

    @staticmethod
    def _anchor_pose_from_profile(profile: TemplateProfile, timestamp_ms: int) -> PoseFrame | None:
        if not profile.feature_sequence:
            return None
        _ = timestamp_ms
        return None
