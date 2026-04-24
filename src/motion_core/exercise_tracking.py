from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

TrackMode = Literal["reps", "hold"]


# ============================================================================
# Running signal normalizer – stretches raw signal to full [0, 1] range
# ============================================================================

@dataclass
class SignalNormalizer:
    """
    Tracks running min/max of the raw phase signal and normalizes to [0, 1].

    This fixes the issue where the signal doesn't consistently reach the
    rep counter thresholds due to camera angle or body proportion differences.
    After a warmup period, the signal is stretched so that observed extremes
    map to 0 and 1.
    """
    _min: float = 1.0
    _max: float = 0.0
    _count: int = 0
    _warmup: int = 10  # frames before normalizing

    def normalize(self, raw: float) -> float:
        s = max(0.0, min(1.0, raw))

        # Update running min/max
        self._min = min(self._min, s)
        self._max = max(self._max, s)
        self._count += 1

        # During warmup, pass through raw signal
        if self._count < self._warmup:
            return s

        # Normalize using observed range
        span = self._max - self._min
        if span < 0.08:
            # Not enough swing yet – still pass through
            return s
        return max(0.0, min(1.0, (s - self._min) / span))

    def reset(self) -> None:
        self._min = 1.0
        self._max = 0.0
        self._count = 0


# ============================================================================
# Rep counter with timestamp-based debounce
# ============================================================================

@dataclass(frozen=True)
class RepCounterConfig:
    high_enter: float = 0.72
    low_exit: float = 0.38
    min_high_frames: int = 1
    min_rep_duration_ms: int = 500  # minimum time between rep transitions


@dataclass
class RepCounter:
    config: RepCounterConfig = field(default_factory=RepCounterConfig)
    rep_count: int = 0
    normalizer: SignalNormalizer = field(default_factory=SignalNormalizer)
    _state: Literal["down", "up"] = "down"
    _high_frames: int = 0
    _last_rep_ts: int = 0

    def update(self, signal: float, timestamp_ms: int = 0) -> int:
        # Normalize signal using running min/max
        s = self.normalizer.normalize(signal)

        if self._state == "down":
            if s >= self.config.high_enter:
                self._high_frames += 1
                if self._high_frames >= self.config.min_high_frames:
                    self._state = "up"
                    self._high_frames = 0
            else:
                self._high_frames = 0
        else:
            if s <= self.config.low_exit:
                # Check minimum time between reps
                elapsed = timestamp_ms - self._last_rep_ts
                if elapsed >= self.config.min_rep_duration_ms or self._last_rep_ts == 0:
                    self.rep_count += 1
                    self._last_rep_ts = timestamp_ms
                self._state = "down"

        return self.rep_count


@dataclass(frozen=True)
class HoldTimerConfig:
    hold_threshold: float = 0.55
    stop_threshold: float = 0.45


@dataclass
class HoldTimer:
    config: HoldTimerConfig = field(default_factory=HoldTimerConfig)
    hold_seconds: float = 0.0
    active: bool = False
    _last_timestamp_ms: int | None = None

    def update(self, signal: float, timestamp_ms: int) -> float:
        s = max(0.0, min(1.0, signal))
        ts = max(0, int(timestamp_ms))

        if self._last_timestamp_ms is None:
            self._last_timestamp_ms = ts
            self.active = s >= self.config.hold_threshold
            return self.hold_seconds

        dt_ms = max(0, ts - self._last_timestamp_ms)
        self._last_timestamp_ms = ts

        if self.active:
            if s < self.config.stop_threshold:
                self.active = False
            else:
                self.hold_seconds += dt_ms / 1000.0
        elif s >= self.config.hold_threshold:
            self.active = True

        return self.hold_seconds


@dataclass(frozen=True)
class ExerciseSpec:
    name: str
    mode: TrackMode
    target_reps: int | None = None
    target_seconds: float | None = None


@dataclass
class ExerciseProgress:
    name: str
    mode: TrackMode
    rep_count: int = 0
    hold_seconds: float = 0.0
    completed: bool = False


@dataclass
class MultiExerciseSession:
    specs: list[ExerciseSpec]
    index: int = 0
    rep_counter: RepCounter = field(default_factory=RepCounter)
    hold_timer: HoldTimer = field(default_factory=HoldTimer)

    def _current_spec(self) -> ExerciseSpec | None:
        if self.index >= len(self.specs):
            return None
        return self.specs[self.index]

    def current_spec(self) -> ExerciseSpec | None:
        return self._current_spec()

    def update(self, signal: float, timestamp_ms: int) -> ExerciseProgress | None:
        spec = self._current_spec()
        if spec is None:
            return None

        rep_count = self.rep_counter.rep_count
        hold_seconds = self.hold_timer.hold_seconds

        if spec.mode == "reps":
            rep_count = self.rep_counter.update(signal, timestamp_ms)
        else:
            hold_seconds = self.hold_timer.update(signal, timestamp_ms)

        completed = False
        if spec.mode == "reps" and spec.target_reps is not None:
            completed = rep_count >= spec.target_reps
        if spec.mode == "hold" and spec.target_seconds is not None:
            completed = hold_seconds >= spec.target_seconds

        progress = ExerciseProgress(
            name=spec.name,
            mode=spec.mode,
            rep_count=rep_count,
            hold_seconds=hold_seconds,
            completed=completed,
        )

        if completed:
            self.index += 1
            self.rep_counter = RepCounter()
            self.hold_timer = HoldTimer()

        return progress

    def done(self) -> bool:
        return self.index >= len(self.specs)
