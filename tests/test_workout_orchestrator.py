from motion_core.workout_orchestrator import WorkoutPlan, WorkoutSession, WorkoutStepConfig, WorkoutTemplate


def test_workout_session_reps_with_confirmation_flow():
    squat = WorkoutTemplate(
        template_id="t-squat",
        name="squat",
        mode="reps",
        video_uri="file:///tmp/squat.mp4",
    )

    session = WorkoutSession(
        templates={squat.template_id: squat},
        plan=WorkoutPlan(
            steps=[WorkoutStepConfig(template_id="t-squat", sets=2, reps_per_set=2, rest_seconds_between_sets=15)]
        ),
    )

    start = session.ensure_started()
    assert start.phase == "waiting_readiness"

    enter = session.frame_update(signal=0.2, timestamp_ms=0, readiness_passed=True)
    assert enter.phase == "active_set"

    # Warmup the SignalNormalizer with some frames first
    ts = 100
    warmup_signals = [0.2, 0.5, 0.8, 0.2, 0.5, 0.8, 0.2, 0.5, 0.8, 0.2]
    for s in warmup_signals:
        session.frame_update(signal=s, timestamp_ms=ts, readiness_passed=True)
        ts += 600  # 600ms spacing to satisfy min_rep_duration_ms

    # Complete two reps with clear high/low transitions and enough time between them.
    rep_signals = [0.8, 0.85, 0.2, 0.85, 0.9, 0.2]
    for s in rep_signals:
        progress = session.frame_update(signal=s, timestamp_ms=ts, readiness_passed=True)
        ts += 600

    assert progress.phase == "rest_pending_confirmation"
    assert progress.pending_confirmation is True

    confirmed = session.confirm()
    assert confirmed.phase == "waiting_readiness"
    assert confirmed.set_index == 1


def test_workout_session_hold_then_done():
    plank = WorkoutTemplate(
        template_id="t-plank",
        name="plank",
        mode="hold",
        video_uri="file:///tmp/plank.mp4",
    )

    session = WorkoutSession(
        templates={plank.template_id: plank},
        plan=WorkoutPlan(
            steps=[WorkoutStepConfig(template_id="t-plank", sets=1, hold_seconds_per_set=1.0)]
        ),
    )

    session.ensure_started()
    session.frame_update(signal=0.3, timestamp_ms=0, readiness_passed=True)

    p1 = session.frame_update(signal=0.9, timestamp_ms=100, readiness_passed=True)
    p2 = session.frame_update(signal=0.9, timestamp_ms=700, readiness_passed=True)
    p3 = session.frame_update(signal=0.9, timestamp_ms=1300, readiness_passed=True)

    assert p3.done is True
    assert p3.phase == "done"
    assert p3.hold_seconds >= 1.0


def test_workout_session_hold_pauses_when_user_drops_posture():
    plank = WorkoutTemplate(
        template_id="t-plank",
        name="plank",
        mode="hold",
        video_uri="file:///tmp/plank.mp4",
    )

    session = WorkoutSession(
        templates={plank.template_id: plank},
        plan=WorkoutPlan(
            steps=[WorkoutStepConfig(template_id="t-plank", sets=1, hold_seconds_per_set=1.0)]
        ),
    )

    session.ensure_started()
    session.frame_update(signal=0.3, timestamp_ms=0, readiness_passed=True)

    p1 = session.frame_update(signal=0.9, timestamp_ms=100, readiness_passed=True)
    dropped_1 = session.frame_update(signal=0.95, timestamp_ms=700, readiness_passed=False)
    dropped_2 = session.frame_update(signal=0.95, timestamp_ms=1300, readiness_passed=False)

    # Hold time must not increase while out-of-pose.
    assert dropped_2.hold_seconds == p1.hold_seconds
    assert any("Tạm dừng đếm" in msg for msg in dropped_2.announcements)

    resumed_1 = session.frame_update(signal=0.9, timestamp_ms=1900, readiness_passed=True)
    resumed_2 = session.frame_update(signal=0.9, timestamp_ms=2500, readiness_passed=True)
    final = session.frame_update(signal=0.9, timestamp_ms=3100, readiness_passed=True)

    assert any("Tiếp tục đếm" in msg for msg in resumed_1.announcements)
    assert resumed_2.hold_seconds > p1.hold_seconds
    assert final.done is True
