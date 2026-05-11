from __future__ import annotations

import argparse

from motion_core.mediapipe_runtime import create_pose_estimator


def main() -> None:
    parser = argparse.ArgumentParser(description="Single-person live capture with MediaPipe Pose")
    parser.add_argument("--camera", type=int, default=0, help="Camera index")
    args = parser.parse_args()

    try:
        import cv2
    except ImportError as exc:
        raise SystemExit("Please install opencv-python and mediapipe in the active environment.") from exc

    pose = create_pose_estimator(
        static_image_mode=False,
        model_complexity=1,
        smooth_landmarks=False,
        min_detection_confidence=0.65,
        min_tracking_confidence=0.65,
    )

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise SystemExit("Cannot open camera")

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = pose.process(rgb)

        # MediaPipe Pose tracks a single prominent person in frame.
        person_detected = result.pose_landmarks is not None
        label = "single-person locked" if person_detected else "no person"
        cv2.putText(frame, label, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (60, 220, 60), 2)

        cv2.imshow("Live Pose - Single Person", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
