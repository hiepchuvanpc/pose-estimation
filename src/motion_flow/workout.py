from __future__ import annotations

from dataclasses import dataclass, field

from .models import ExerciseTemplate, FeatureFrame, PoseFrame
from .tracking import HoldTracker, RepCounter


@dataclass(slots=True)
class WorkoutSetPlan:
    set_index: int
    target_reps: int | None = None
    target_hold_seconds: float | None = None


@dataclass(slots=True)
class WorkoutExercisePlan:
    template: ExerciseTemplate
    sets: list[WorkoutSetPlan]


@dataclass(slots=True)
class SetRecorder:
    """Capture per-set artifacts for offline post-analysis."""

    set_index: int
    video_uri: str | None = None
    poses: list[PoseFrame] = field(default_factory=list)
    features: list[FeatureFrame] = field(default_factory=list)

    def append(self, pose: PoseFrame, feature: FeatureFrame) -> None:
        self.poses.append(pose)
        self.features.append(feature)


class WorkoutSession:
    """State machine for exercise and set transitions in one continuous flow."""

    def __init__(self, session_id: str, plans: list[WorkoutExercisePlan]) -> None:
        if not plans:
            raise ValueError("plans must not be empty")
        self.session_id = session_id
        self.plans = plans
        self.exercise_index = 0
        self.set_index = 0
        self.rep_counter = RepCounter()
        self.hold_tracker = HoldTracker()
        self.current_recorder = SetRecorder(set_index=1)

    @property
    def current_plan(self) -> WorkoutExercisePlan:
        return self.plans[self.exercise_index]

    @property
    def current_set_plan(self) -> WorkoutSetPlan:
        return self.current_plan.sets[self.set_index]

    def on_feature(self, pose: PoseFrame, feature: FeatureFrame) -> dict[str, float | int | bool]:
        self.current_recorder.append(pose, feature)
        set_plan = self.current_set_plan
        completed = False

        reps = self.rep_counter.update(feature.signal)
        hold = self.hold_tracker.update(feature.signal, feature.timestamp_ms)

        if set_plan.target_reps is not None and reps >= set_plan.target_reps:
            completed = True
        if set_plan.target_hold_seconds is not None and hold >= set_plan.target_hold_seconds:
            completed = True

        return {
            "reps": reps,
            "hold_seconds": hold,
            "set_completed": completed,
        }

    def complete_set(self) -> SetRecorder:
        completed = self.current_recorder
        self.rep_counter.reset()
        self.hold_tracker.reset()

        self.set_index += 1
        if self.set_index >= len(self.current_plan.sets):
            self.set_index = 0
            self.exercise_index += 1

        if not self.is_finished():
            self.current_recorder = SetRecorder(set_index=self.current_set_plan.set_index)
        return completed

    def is_finished(self) -> bool:
        return self.exercise_index >= len(self.plans)
