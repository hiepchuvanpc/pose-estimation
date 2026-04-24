from motion_core.exercise_tracking import (
    MultiExerciseSession,
    ExerciseSpec,
    RepCounter,
    RepCounterConfig,
    SignalNormalizer,
)


def test_rep_counter_session_progression():
    session = MultiExerciseSession(
        specs=[
            ExerciseSpec(name="squat", mode="reps", target_reps=2),
            ExerciseSpec(name="plank", mode="hold", target_seconds=2.0),
        ]
    )

    # Two rep cycles: up then down. Now pass timestamp_ms.
    signals = [0.2, 0.8, 0.85, 0.2, 0.85, 0.9, 0.2]
    ts = 0
    last = None
    for s in signals:
        ts += 600  # 600ms between frames - above min_rep_duration_ms
        last = session.update(signal=s, timestamp_ms=ts)

    assert last is not None
    assert last.name == "squat"
    assert last.completed is True


def test_hold_timer_completion():
    session = MultiExerciseSession(
        specs=[ExerciseSpec(name="plank", mode="hold", target_seconds=1.0)]
    )

    # Start hold and keep stable for 1.2 seconds.
    updates = [
        (0.8, 0),
        (0.85, 400),
        (0.9, 800),
        (0.88, 1200),
    ]

    progress = None
    for signal, ts in updates:
        progress = session.update(signal=signal, timestamp_ms=ts)

    assert progress is not None
    assert progress.mode == "hold"
    assert progress.hold_seconds >= 1.0
    assert progress.completed is True


def test_signal_normalizer_stretches_range():
    """SignalNormalizer should stretch a narrow signal to full [0,1]."""
    normalizer = SignalNormalizer()

    # Warmup: first 10 frames
    for i in range(10):
        normalizer.normalize(0.5)

    # After warmup, feed narrow range [0.4, 0.6]
    low_result = normalizer.normalize(0.4)
    high_result = normalizer.normalize(0.6)

    # Should stretch: 0.4 → near 0, 0.6 → near 1
    assert low_result < 0.15, f"Expected low to be near 0, got {low_result}"
    assert high_result > 0.85, f"Expected high to be near 1, got {high_result}"


def test_signal_normalizer_warmup():
    """During warmup, raw signal is returned unchanged."""
    normalizer = SignalNormalizer()

    for i in range(5):
        result = normalizer.normalize(0.5)
        assert abs(result - 0.5) < 0.01, "During warmup, should return raw signal"


def test_rep_counter_min_duration():
    """Reps too close together should be debounced."""
    counter = RepCounter(config=RepCounterConfig(
        high_enter=0.7,
        low_exit=0.3,
        min_rep_duration_ms=500,
    ))

    # First rep (valid)
    counter.update(0.8, timestamp_ms=0)
    counter.update(0.2, timestamp_ms=600)  # 600ms after start, valid
    assert counter.rep_count == 1

    # Second rep too quickly (invalid - less than 500ms since last rep)
    counter.update(0.8, timestamp_ms=700)
    counter.update(0.2, timestamp_ms=800)  # only 200ms since last rep counted at 600ms
    # Should still be 1 due to debounce
    assert counter.rep_count == 1

    # Third rep after enough time (valid)
    counter.update(0.8, timestamp_ms=1200)
    counter.update(0.2, timestamp_ms=1400)  # 800ms since last valid rep
    assert counter.rep_count == 2
