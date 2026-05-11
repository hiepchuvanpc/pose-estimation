from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .exercise_tracking import (
    ExerciseSpec,
    HoldTimer,
    HoldTimerConfig,
    MultiExerciseSession,
    RepCounter,
    RepCounterConfig,
)

Phase = Literal[
    "waiting_readiness",
    "active_set",
    "rest_pending_confirmation",
    "set_pending_confirmation",
    "exercise_pending_confirmation",
    "done",
]


@dataclass(frozen=True)
class WorkoutTemplate:
    template_id: str
    name: str
    mode: Literal["reps", "hold"]
    video_uri: str
    notes: str | None = None
    trim_start_sec: float | None = None
    trim_end_sec: float | None = None


@dataclass(frozen=True)
class WorkoutStepConfig:
    template_id: str
    sets: int = 1
    reps_per_set: int | None = None
    hold_seconds_per_set: float | None = None
    rest_seconds_between_sets: int = 0


@dataclass(frozen=True)
class WorkoutPlan:
    steps: list[WorkoutStepConfig]


@dataclass
class WorkoutProgress:
    phase: Phase
    exercise_name: str | None
    mode: Literal["reps", "hold"] | None
    step_index: int
    set_index: int
    rep_count: int
    hold_seconds: float
    target_reps: int | None
    target_seconds: float | None
    tracking_started: bool
    pending_confirmation: bool
    done: bool
    announcements: list[str]


@dataclass
class WorkoutSession:
    templates: dict[str, WorkoutTemplate]
    plan: WorkoutPlan
    adaptive_thresholds_by_template: dict[str, dict[str, float]] = field(default_factory=dict)
    step_index: int = 0
    set_index: int = 0
    phase: Phase = "waiting_readiness"
    pending_confirmation: bool = False
    _tracker: MultiExerciseSession | None = None
    _hold_not_ready_frames: int = 0
    _hold_paused_announced: bool = False

    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, float(value)))

    def _thresholds_for_current_template(self) -> dict[str, float]:
        template = self._current_template()
        if template is None:
            return {}
        raw = self.adaptive_thresholds_by_template.get(template.template_id, {})
        return raw if isinstance(raw, dict) else {}

    def _current_step(self) -> WorkoutStepConfig | None:
        if self.step_index >= len(self.plan.steps):
            return None
        return self.plan.steps[self.step_index]

    def _current_template(self) -> WorkoutTemplate | None:
        step = self._current_step()
        if step is None:
            return None
        return self.templates.get(step.template_id)

    def _build_tracker(self) -> MultiExerciseSession:
        step = self._current_step()
        template = self._current_template()
        if step is None or template is None:
            return MultiExerciseSession(specs=[])

        adaptive = self._thresholds_for_current_template()
        rep_high = self._clamp(float(adaptive.get("rep_high_enter", 0.72)), 0.5, 0.95)
        rep_low = self._clamp(float(adaptive.get("rep_low_exit", 0.38)), 0.05, rep_high - 0.08)
        hold_threshold = self._clamp(float(adaptive.get("hold_threshold", 0.55)), 0.2, 0.95)
        hold_stop = self._clamp(float(adaptive.get("hold_stop_threshold", 0.45)), 0.05, hold_threshold - 0.05)
        min_high_frames = max(1, int(adaptive.get("rep_min_high_frames", 1)))
        rep_counter = RepCounter(
            config=RepCounterConfig(
                high_enter=rep_high,
                low_exit=rep_low,
                min_high_frames=min_high_frames,
            )
        )
        hold_timer = HoldTimer(
            config=HoldTimerConfig(
                hold_threshold=hold_threshold,
                stop_threshold=hold_stop,
            )
        )

        if template.mode == "reps":
            target = step.reps_per_set or 1
            spec = ExerciseSpec(name=template.name, mode="reps", target_reps=target)
        else:
            target = step.hold_seconds_per_set or 10.0
            spec = ExerciseSpec(name=template.name, mode="hold", target_seconds=target)

        return MultiExerciseSession(
            specs=[spec],
            rep_counter=rep_counter,
            hold_timer=hold_timer,
        )

    def current_step(self) -> WorkoutStepConfig | None:
        return self._current_step()

    def current_template(self) -> WorkoutTemplate | None:
        return self._current_template()

    def _progress(
        self,
        announcements: list[str],
        rep_count: int = 0,
        hold_seconds: float = 0.0,
        tracking_started: bool = False,
    ) -> WorkoutProgress:
        step = self._current_step()
        template = self._current_template()

        target_reps = step.reps_per_set if step else None
        target_seconds = step.hold_seconds_per_set if step else None

        return WorkoutProgress(
            phase=self.phase,
            exercise_name=template.name if template else None,
            mode=template.mode if template else None,
            step_index=self.step_index,
            set_index=self.set_index,
            rep_count=rep_count,
            hold_seconds=hold_seconds,
            target_reps=target_reps,
            target_seconds=target_seconds,
            tracking_started=tracking_started,
            pending_confirmation=self.pending_confirmation,
            done=self.phase == "done",
            announcements=announcements,
        )

    def ensure_started(self) -> WorkoutProgress:
        step = self._current_step()
        if step is None:
            self.phase = "done"
            return self._progress(["Buổi tập đã hoàn tất."])

        template = self._current_template()
        if template is None:
            self.phase = "done"
            return self._progress(["Không tìm thấy template cho bài tập hiện tại."])

        if self._tracker is None:
            self._tracker = self._build_tracker()
        self._hold_not_ready_frames = 0
        self._hold_paused_announced = False

        if self.phase == "waiting_readiness":
            return self._progress([f"Sẵn sàng bài {template.name}. Hãy vào tư thế chuẩn để hệ thống tự bắt đầu."])

        return self._progress([])

    def frame_update(self, signal: float, timestamp_ms: int, readiness_passed: bool) -> WorkoutProgress:
        step = self._current_step()
        template = self._current_template()
        if step is None or template is None:
            self.phase = "done"
            return self._progress(["Buổi tập đã hoàn tất."])

        if self.phase in ("rest_pending_confirmation", "set_pending_confirmation", "exercise_pending_confirmation", "done"):
            return self._progress(["Đang chờ xác nhận để tiếp tục."], rep_count=0, hold_seconds=0.0)

        if self.phase == "waiting_readiness":
            if not readiness_passed:
                return self._progress(["Cần chỉnh lại tư thế chuẩn trước khi bắt đầu."], rep_count=0, hold_seconds=0.0)
            self.phase = "active_set"
            return self._progress([f"Bắt đầu set {self.set_index + 1} bài {template.name}."], rep_count=0, hold_seconds=0.0)

        if self._tracker is None:
            self._tracker = self._build_tracker()

        announcements: list[str] = []

        # Hold mode: if user drops posture, pause counting immediately.
        if template.mode == "hold":
            adaptive = self._thresholds_for_current_template()
            pause_frames = max(1, int(adaptive.get("hold_pause_not_ready_frames", 2)))
            if not readiness_passed:
                self._hold_not_ready_frames += 1
                if self._hold_not_ready_frames >= pause_frames and not self._hold_paused_announced:
                    announcements.append("Bạn đang rời tư thế giữ. Tạm dừng đếm, hãy vào lại tư thế.")
                    self._hold_paused_announced = True

                paused_progress = self._tracker.update(signal=0.0, timestamp_ms=timestamp_ms)
                rep_count = paused_progress.rep_count if paused_progress else 0
                hold_seconds = paused_progress.hold_seconds if paused_progress else 0.0
                return self._progress(announcements, rep_count=rep_count, hold_seconds=hold_seconds, tracking_started=False)

            if self._hold_paused_announced and self._hold_not_ready_frames >= pause_frames:
                announcements.append("Đã vào lại tư thế giữ. Tiếp tục đếm.")
            self._hold_not_ready_frames = 0
            self._hold_paused_announced = False
        else:
            self._hold_not_ready_frames = 0
            self._hold_paused_announced = False

        progress = self._tracker.update(signal=signal, timestamp_ms=timestamp_ms)
        rep_count = progress.rep_count if progress else 0
        hold_seconds = progress.hold_seconds if progress else 0.0
        tracking_started = False
        if template.mode == "hold":
            tracking_started = hold_seconds > 0.0 or bool(self._tracker.hold_timer.active)
        else:
            tracking_started = bool(
                rep_count > 0
                or self._tracker.rep_counter._high_frames > 0
                or self._tracker.rep_counter._state == "up"
            )

        if template.mode == "reps" and rep_count > 0:
            announcements.append(f"Rep {rep_count}")

        if progress and progress.completed:
            total_sets = step.sets
            is_last_set = (self.set_index + 1) >= total_sets

            if not is_last_set:
                self.phase = "rest_pending_confirmation"
                self.pending_confirmation = True
                announcements.append(f"Hoàn thành set {self.set_index + 1}. Bấm tiếp tục để vào set tiếp theo.")
            else:
                is_last_step = (self.step_index + 1) >= len(self.plan.steps)
                if is_last_step:
                    self.phase = "done"
                    announcements.append(f"Hoàn thành bài {template.name}. Kết thúc buổi tập.")
                else:
                    self.phase = "exercise_pending_confirmation"
                    self.pending_confirmation = True
                    announcements.append(f"Hoàn thành bài {template.name}. Bấm xác nhận để sang bài tiếp theo.")

        return self._progress(
            announcements,
            rep_count=rep_count,
            hold_seconds=hold_seconds,
            tracking_started=tracking_started,
        )

    def confirm(self) -> WorkoutProgress:
        step = self._current_step()
        template = self._current_template()

        if self.phase == "done":
            return self._progress(["Buổi tập đã hoàn tất."])

        if self.phase == "rest_pending_confirmation":
            self.set_index += 1
            self._tracker = self._build_tracker()
            self._hold_not_ready_frames = 0
            self._hold_paused_announced = False
            self.phase = "waiting_readiness"
            self.pending_confirmation = False
            return self._progress([f"Sẵn sàng set {self.set_index + 1}. Hãy vào lại tư thế chuẩn để hệ thống tự bắt đầu."], rep_count=0, hold_seconds=0.0)

        if self.phase == "exercise_pending_confirmation":
            self.step_index += 1
            self.set_index = 0
            self._tracker = self._build_tracker()
            self._hold_not_ready_frames = 0
            self._hold_paused_announced = False
            self.phase = "waiting_readiness"
            self.pending_confirmation = False
            next_template = self._current_template()
            if next_template is None:
                self.phase = "done"
                return self._progress(["Buổi tập đã hoàn tất."])
            return self._progress([f"Sẵn sàng bài {next_template.name}. Hãy vào lại tư thế chuẩn để hệ thống tự bắt đầu."], rep_count=0, hold_seconds=0.0)

        if self.phase == "set_pending_confirmation":
            self.phase = "waiting_readiness"
            self.pending_confirmation = False
            return self._progress(["Đã tiếp tục. Hãy vào lại tư thế chuẩn để hệ thống tự bắt đầu."], rep_count=0, hold_seconds=0.0)

        if self.phase == "waiting_readiness":
            if template is None or step is None:
                self.phase = "done"
                return self._progress(["Buổi tập đã hoàn tất."])
            self.phase = "active_set"
            self.pending_confirmation = False
            return self._progress([f"Bắt đầu set {self.set_index + 1} bài {template.name}."], rep_count=0, hold_seconds=0.0)

        return self._progress(["Không có xác nhận nào đang chờ xử lý."])
