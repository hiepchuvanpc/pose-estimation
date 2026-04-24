from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PhaseDetectorConfig:
    up_threshold: float = 0.65
    down_threshold: float = 0.35


class PhaseDetector:
    """Simple phase classifier based on normalized movement signal."""

    def __init__(self, config: PhaseDetectorConfig | None = None) -> None:
        self.config = config or PhaseDetectorConfig()

    def detect(self, signal: float) -> str:
        if signal >= self.config.up_threshold:
            return "up"
        if signal <= self.config.down_threshold:
            return "down"
        return "transition"


@dataclass(slots=True)
class RepCounterConfig:
    high_enter: float = 0.72
    low_exit: float = 0.38


class RepCounter:
    """Hysteresis rep counter from a scalar signal."""

    def __init__(self, config: RepCounterConfig | None = None) -> None:
        self.config = config or RepCounterConfig()
        self._high_seen = False
        self.reps = 0

    def reset(self) -> None:
        self._high_seen = False
        self.reps = 0

    def update(self, signal: float) -> int:
        if not self._high_seen and signal >= self.config.high_enter:
            self._high_seen = True
        elif self._high_seen and signal <= self.config.low_exit:
            self._high_seen = False
            self.reps += 1
        return self.reps


class HoldTracker:
    """Tracks continuous hold time while signal is over threshold."""

    def __init__(self, hold_threshold: float = 0.65) -> None:
        self.hold_threshold = hold_threshold
        self.hold_seconds = 0.0
        self._last_ts: int | None = None

    def reset(self) -> None:
        self.hold_seconds = 0.0
        self._last_ts = None

    def update(self, signal: float, timestamp_ms: int) -> float:
        if self._last_ts is None:
            self._last_ts = timestamp_ms
            return self.hold_seconds

        dt = max((timestamp_ms - self._last_ts) / 1000.0, 0.0)
        self._last_ts = timestamp_ms
        if signal >= self.hold_threshold:
            self.hold_seconds += dt
        return self.hold_seconds


class TempoAnalyzer:
    """Tracks rough per-phase durations for realtime pacing feedback."""

    def __init__(self) -> None:
        self._phase_ts: dict[str, int | None] = {"up": None, "down": None, "hold": None}
        self._durations: dict[str, list[float]] = {"up": [], "down": [], "hold": []}

    def update(self, phase: str, timestamp_ms: int) -> None:
        if phase not in self._phase_ts:
            return
        prev = self._phase_ts[phase]
        if prev is not None:
            self._durations[phase].append(max((timestamp_ms - prev) / 1000.0, 0.0))
        self._phase_ts[phase] = timestamp_ms

    def snapshot(self) -> dict[str, float]:
        return {
            name: (sum(vals) / len(vals) if vals else 0.0)
            for name, vals in self._durations.items()
        }
