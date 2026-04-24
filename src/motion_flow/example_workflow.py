from __future__ import annotations

from motion_flow.models import ExerciseTemplate, PoseFrame
from motion_flow.orchestrator import AIFitnessCoach
from motion_flow.workout import WorkoutExercisePlan, WorkoutSetPlan


def _fake_pose_stream(length: int, start_ts: int = 0, step_ms: int = 33) -> list[PoseFrame]:
    frames: list[PoseFrame] = []
    for idx in range(length):
        phase = (idx % 40) / 40.0
        y_knee = 0.6 - 0.2 * phase
        points = {
            "mid_hip": (0.5, 0.5),
            "neck": (0.5, 0.3),
            "left_shoulder": (0.42, 0.32),
            "right_shoulder": (0.58, 0.32),
            "left_hip": (0.46, 0.5),
            "right_hip": (0.54, 0.5),
            "left_knee": (0.46, y_knee),
            "right_knee": (0.54, y_knee),
            "left_ankle": (0.46, 0.88),
            "right_ankle": (0.54, 0.88),
            "left_elbow": (0.40, 0.45),
            "right_elbow": (0.60, 0.45),
            "left_wrist": (0.38, 0.58),
            "right_wrist": (0.62, 0.58),
            "nose": (0.5, 0.24),
        }
        conf = {k: 0.95 for k in points}
        frames.append(
            PoseFrame(
                timestamp_ms=start_ts + idx * step_ms,
                keypoints_xy=points,
                keypoint_confidence=conf,
                frame_width=1280,
                frame_height=720,
            )
        )
    return frames


def run_demo() -> None:
    coach = AIFitnessCoach()

    template = ExerciseTemplate(
        template_id="tpl-squat-001",
        name="Bodyweight Squat",
        view="front",
        posture="standing",
        source_uri="trainer://sample",
        mode="rep",
    )

    template_frames = _fake_pose_stream(80)
    coach.ingest_template(template, template_frames)

    plan = WorkoutExercisePlan(
        template=template,
        sets=[WorkoutSetPlan(set_index=1, target_reps=3)],
    )
    coach.start_session(session_id="session-001", plans=[plan])

    user_frames = _fake_pose_stream(140, start_ts=5000)
    for frame in user_frames:
        update = coach.process_realtime_frame(frame)
        if update.set_completed:
            coach.complete_current_set()
            break

    result = coach.finalize_session()
    print(f"Session: {result.session_id}")
    print("Summary feedback:")
    for line in result.summary_feedback:
        print(f"- {line}")


if __name__ == "__main__":
    run_demo()
