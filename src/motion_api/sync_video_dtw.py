from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from motion_core.dtw import dtw_distance, segment_by_signal_valleys
from motion_core.features import features_from_samples
from motion_core.mediapipe_runtime import create_pose_estimator
from motion_core.template_profile import build_template_profile_from_features


@dataclass(frozen=True)
class VideoPoseTrack:
    video_path: Path
    fps: float
    frame_count: int
    sample_frame_indices: list[int]
    samples: list[list[list[float]]]


class VideoFrameReader:
    def __init__(self, path: Path, flip_h: bool = False) -> None:
        self.path = path
        self.flip_h = flip_h
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open video: {path}")
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 0.0)
        # Some containers (notably WebM from browser MediaRecorder) may report 0 frame count
        # even though frames are readable sequentially.
        self._unknown_length = self.frame_count <= 0
        self._seq_next_index = 0
        self._cache: dict[int, np.ndarray] = {}
        self._cache_order: list[int] = []
        self._cache_size = 64

    def _cache_frame(self, idx: int, frame: np.ndarray) -> None:
        self._cache[idx] = frame
        self._cache_order.append(idx)
        if len(self._cache_order) > self._cache_size:
            drop = self._cache_order.pop(0)
            self._cache.pop(drop, None)

    def _read_unknown_length_at(self, idx: int) -> np.ndarray:
        if idx < self._seq_next_index:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            self._seq_next_index = idx

        while self._seq_next_index <= idx:
            ok, frame = self.cap.read()
            if not ok or frame is None:
                break
            if self.flip_h:
                frame = cv2.flip(frame, 1)
            self._cache_frame(self._seq_next_index, frame)
            self._seq_next_index += 1

        cached = self._cache.get(idx)
        if cached is not None:
            return cached.copy()
        if self._cache_order:
            return self._cache[self._cache_order[-1]].copy()
        raise RuntimeError(f"Cannot read frame {idx} from {self.path}")

    def read_at(self, frame_index: int) -> np.ndarray:
        idx = max(0, int(frame_index))
        if not self._unknown_length and self.frame_count > 0:
            idx = min(idx, self.frame_count - 1)
        cached = self._cache.get(idx)
        if cached is not None:
            return cached.copy()

        if self._unknown_length:
            return self._read_unknown_length_at(idx)

        self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = self.cap.read()
        if not ok or frame is None:
            if self._cache_order:
                return self._cache[self._cache_order[-1]].copy()
            raise RuntimeError(f"Cannot read frame {idx} from {self.path}")

        if self.flip_h:
            frame = cv2.flip(frame, 1)

        self._cache_frame(idx, frame)
        return frame.copy()

    def close(self) -> None:
        self.cap.release()


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _phase_signal(feature: list[float], mean: list[float], pc1: list[float], proj_min: float, proj_max: float) -> float:
    centered = [feature[i] - (mean[i] if i < len(mean) else 0.0) for i in range(len(feature))]
    proj = sum(centered[i] * (pc1[i] if i < len(pc1) else 0.0) for i in range(len(centered)))
    denom = max(1e-6, float(proj_max) - float(proj_min))
    return _clamp((proj - float(proj_min)) / denom, 0.0, 1.0)


def _moving_average(signal: list[float], window: int = 5) -> list[float]:
    if not signal:
        return []
    win = max(1, int(window))
    out: list[float] = []
    for i in range(len(signal)):
        lo = max(0, i - win // 2)
        hi = min(len(signal), i + win // 2 + 1)
        out.append(sum(signal[lo:hi]) / max(1, hi - lo))
    return out


def _serialize_sample(result) -> list[list[float]]:
    world_landmarks = getattr(result, "pose_world_landmarks", None)
    world_points = getattr(world_landmarks, "landmark", None)
    packed: list[list[float]] = []
    for idx, lm in enumerate(result.pose_landmarks.landmark):
        point = [
            float(lm.x),
            float(lm.y),
            float(lm.z),
            float(getattr(lm, "visibility", 0.0)),
        ]
        if world_points is not None and idx < len(world_points):
            w = world_points[idx]
            point.extend(
                [
                    float(w.x),
                    float(w.y),
                    float(w.z),
                    float(getattr(w, "visibility", getattr(w, "presence", 0.0))),
                ]
            )
        packed.append(point)
    return packed


def extract_pose_track(video_path: Path, frame_stride: int = 1, flip_h: bool = False) -> VideoPoseTrack:
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    pose = create_pose_estimator(
        static_image_mode=False,
        model_complexity=2,
        smooth_landmarks=False,
        min_detection_confidence=0.65,
        min_tracking_confidence=0.65,
    )

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 1e-6:
        fps = 30.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    samples: list[list[list[float]]] = []
    sample_indices: list[int] = []
    frame_idx = 0

    try:
        while cap.isOpened():
            ok, frame = cap.read()
            if not ok:
                break

            if frame_idx % max(1, int(frame_stride)) != 0:
                frame_idx += 1
                continue

            if flip_h:
                frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = pose.process(rgb)
            if result.pose_landmarks is not None:
                samples.append(_serialize_sample(result))
                sample_indices.append(frame_idx)
            frame_idx += 1
    finally:
        cap.release()

    if len(samples) < 10:
        raise RuntimeError(
            f"Not enough pose samples from {video_path}. Need >= 10, got {len(samples)}."
        )

    return VideoPoseTrack(
        video_path=video_path,
        fps=fps,
        frame_count=frame_count,
        sample_frame_indices=sample_indices,
        samples=samples,
    )


def _resize_pad(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    h, w = frame.shape[:2]
    if h <= 0 or w <= 0:
        return np.zeros((height, width, 3), dtype=np.uint8)

    scale = min(width / float(w), height / float(h))
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)

    canvas = np.full((height, width, 3), 18, dtype=np.uint8)
    ox = (width - nw) // 2
    oy = (height - nh) // 2
    canvas[oy : oy + nh, ox : ox + nw] = resized
    return canvas


def _sample_path(path: list[tuple[int, int]], limit: int) -> list[tuple[int, int]]:
    if len(path) <= limit:
        return path
    if limit <= 2:
        return [path[0], path[-1]]

    out: list[tuple[int, int]] = [path[0]]
    step = (len(path) - 1) / float(limit - 1)
    for i in range(1, limit - 1):
        out.append(path[int(round(i * step))])
    out.append(path[-1])
    return out


def _sample_indices(length: int, limit: int) -> list[int]:
    if length <= 0:
        return []
    if length <= limit:
        return list(range(length))
    if limit <= 2:
        return [0, length - 1]

    out: list[int] = [0]
    step = (length - 1) / float(limit - 1)
    for i in range(1, limit - 1):
        idx = int(round(i * step))
        if idx <= out[-1]:
            idx = min(length - 1, out[-1] + 1)
        out.append(idx)
    out.append(length - 1)
    return out


def _dense_teacher_map_from_dtw_path(
    path: list[tuple[int, int]],
    student_len: int,
    teacher_len: int,
) -> list[int]:
    if student_len <= 0 or teacher_len <= 0:
        return []
    if not path:
        return [
            int(round((i / max(1, student_len - 1)) * max(0, teacher_len - 1)))
            for i in range(student_len)
        ]

    buckets: dict[int, list[int]] = {}
    for s_idx, t_idx in path:
        s = int(s_idx)
        t = int(t_idx)
        if s < 0 or s >= student_len:
            continue
        if t < 0 or t >= teacher_len:
            continue
        buckets.setdefault(s, []).append(t)

    if not buckets:
        return [
            int(round((i / max(1, student_len - 1)) * max(0, teacher_len - 1)))
            for i in range(student_len)
        ]

    xs = np.array(sorted(buckets.keys()), dtype=np.float32)
    ys = np.array(
        [sum(buckets[int(x)]) / float(len(buckets[int(x)])) for x in xs],
        dtype=np.float32,
    )

    if len(xs) == 1:
        dense = np.full((student_len,), ys[0], dtype=np.float32)
    else:
        dense = np.interp(
            np.arange(student_len, dtype=np.float32),
            xs,
            ys,
        ).astype(np.float32)

    dense = np.clip(np.round(dense), 0, max(0, teacher_len - 1)).astype(np.int32)
    return dense.tolist()


def _active_span_from_signal(signals: list[float], expected_reps: int = 1) -> tuple[int, int]:
    if not signals:
        return (0, -1)
    arr = np.asarray(signals, dtype=np.float32)
    if arr.size <= 1:
        return (0, int(arr.size - 1))

    lo = float(np.min(arr))
    hi = float(np.max(arr))
    span = hi - lo
    if span < 0.10:
        return (0, int(arr.size - 1))

    threshold = lo + (0.22 * span)
    active = np.where(arr >= threshold)[0]
    if active.size == 0:
        return (0, int(arr.size - 1))

    margin = max(2, int(arr.size * 0.02))
    start = max(0, int(active[0]) - margin)
    end = min(int(arr.size - 1), int(active[-1]) + margin)
    min_required = max(12, int(expected_reps) * 8)
    if (end - start + 1) < min_required:
        return (0, int(arr.size - 1))
    return (start, end)


def _split_even_segments(start_idx: int, end_idx: int, n_segments: int) -> list[tuple[int, int]]:
    start = int(start_idx)
    end = int(end_idx)
    n = max(1, int(n_segments))
    if end < start:
        return []
    total = end - start + 1
    if n <= 1 or total < n:
        return [(start, end)]

    edges = np.linspace(start, end + 1, n + 1)
    segments: list[tuple[int, int]] = []
    for i in range(n):
        s = int(round(edges[i]))
        e = int(round(edges[i + 1])) - 1
        if i == n - 1:
            e = end
        s = max(start, min(s, end))
        e = max(s, min(e, end))
        segments.append((s, e))
    return segments


def _open_writer(out_path: Path, fps: float, width: int, height: int) -> cv2.VideoWriter:
    # Use mp4v directly - output will be re-encoded by ffmpeg to H.264
    writer = cv2.VideoWriter(
        str(out_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        float(max(8.0, fps)),
        (int(width), int(height)),
    )
    if writer.isOpened():
        return writer
    writer.release()
    raise RuntimeError("Cannot initialize mp4 writer")


def build_synced_video(
    teacher_track: VideoPoseTrack,
    student_track: VideoPoseTrack,
    output_path: Path,
    max_frames_per_rep: int = 140,
    panel_width: int = 640,
    panel_height: int = 720,
    student_flip_h: bool = False,
    expected_reps: int | None = None,
) -> dict[str, float | int]:
    teacher_features = features_from_samples(teacher_track.samples)
    student_features = features_from_samples(student_track.samples)

    profile = build_template_profile_from_features(teacher_features)
    signals = [
        _phase_signal(
            feat,
            profile.feature_mean,
            profile.feature_pc1,
            profile.proj_min,
            profile.proj_max,
        )
        for feat in student_features
    ]
    signals = _moving_average(signals, window=5)

    expected = max(0, int(expected_reps or 0))
    if expected > 1:
        a_start, a_end = _active_span_from_signal(signals, expected_reps=expected)
        rep_segments = _split_even_segments(a_start, a_end, expected)
    else:
        min_rep_frames = max(6, int(len(teacher_features) * 0.45))
        rep_segments = segment_by_signal_valleys(signals, min_rep_frames=min_rep_frames)

    if not rep_segments:
        rep_segments = [(0, len(student_features) - 1)]

    teacher_reader = VideoFrameReader(teacher_track.video_path)
    student_reader = VideoFrameReader(student_track.video_path, flip_h=student_flip_h)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    out_w = int(panel_width) * 2
    out_h = int(panel_height)
    fps = max(12.0, min(30.0, student_track.fps or teacher_track.fps or 24.0))
    writer = _open_writer(output_path, fps=fps, width=out_w, height=out_h)

    total_written = 0
    sum_norm_dist = 0.0
    valid_reps = 0

    try:
        for rep_idx, (start, end) in enumerate(rep_segments, start=1):
            start_idx = max(0, min(start, len(student_features) - 1))
            end_idx = max(start_idx, min(end, len(student_features) - 1))
            rep_features = student_features[start_idx : end_idx + 1]
            if not rep_features:
                continue

            length_gap = abs(len(rep_features) - len(teacher_features))
            # Keep Sakoe-Chiba window wide enough so end cell stays reachable.
            window = max(length_gap + 2, max(6, max(len(rep_features), len(teacher_features)) // 4))
            dtw = dtw_distance(rep_features, teacher_features, window=window)
            if not np.isfinite(dtw.normalized_distance):
                # Fallback to unconstrained DTW for pathological length differences.
                dtw = dtw_distance(rep_features, teacher_features, window=None)
            dense_teacher_map = _dense_teacher_map_from_dtw_path(
                dtw.path,
                student_len=len(rep_features),
                teacher_len=len(teacher_features),
            )
            sampled_student_locals = _sample_indices(len(dense_teacher_map), max_frames_per_rep)
            if not sampled_student_locals:
                continue

            dtw_norm = float(dtw.normalized_distance) if np.isfinite(dtw.normalized_distance) else 0.0
            sum_norm_dist += dtw_norm
            valid_reps += 1

            for step_idx, s_local in enumerate(sampled_student_locals, start=1):
                t_idx = dense_teacher_map[s_local]
                s_global = start_idx + int(s_local)
                s_global = max(0, min(s_global, len(student_track.sample_frame_indices) - 1))
                t_global = max(0, min(int(t_idx), len(teacher_track.sample_frame_indices) - 1))

                student_frame_no = student_track.sample_frame_indices[s_global]
                teacher_frame_no = teacher_track.sample_frame_indices[t_global]

                teacher_frame = teacher_reader.read_at(teacher_frame_no)
                student_frame = student_reader.read_at(student_frame_no)

                left = _resize_pad(teacher_frame, int(panel_width), int(panel_height))
                right = _resize_pad(student_frame, int(panel_width), int(panel_height))
                merged = np.hstack([left, right])

                cv2.putText(
                    merged,
                    "Giao vien (1 rep mau)",
                    (16, 36),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (100, 220, 100),
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    merged,
                    f"Hoc vien - rep {rep_idx}",
                    (int(panel_width) + 16, 36),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (100, 220, 100),
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    merged,
                    f"DTW norm: {dtw_norm:.4f} | step {step_idx}/{len(sampled_student_locals)}",
                    (16, int(panel_height) - 22),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    (230, 230, 230),
                    1,
                    cv2.LINE_AA,
                )

                writer.write(merged)
                total_written += 1

            spacer = np.full((out_h, out_w, 3), 8, dtype=np.uint8)
            cv2.putText(
                spacer,
                f"Ket thuc rep {rep_idx}",
                (16, out_h // 2),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (190, 190, 190),
                2,
                cv2.LINE_AA,
            )
            for _ in range(4):
                writer.write(spacer)
                total_written += 1
    finally:
        writer.release()
        teacher_reader.close()
        student_reader.close()

    return {
        "rep_count": valid_reps,
        "frames_written": total_written,
        "avg_normalized_dtw": (sum_norm_dist / valid_reps) if valid_reps > 0 else 0.0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dong bo video giao vien (1 rep) va video hoc vien (nhieu rep) bang DTW, "
            "xuat 1 video merged theo tung rep cua hoc vien."
        )
    )
    parser.add_argument("--teacher-video", required=True, help="Duong dan video giao vien (1 rep)")
    parser.add_argument("--student-video", required=True, help="Duong dan video hoc vien (nhieu rep)")
    parser.add_argument("--output", required=True, help="Duong dan file mp4 dau ra")
    parser.add_argument("--frame-stride", type=int, default=1, help="Lay pose moi N frame (mac dinh: 1)")
    parser.add_argument(
        "--max-frames-per-rep",
        type=int,
        default=140,
        help="Gioi han so frame render cho moi rep sau DTW (mac dinh: 140)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    teacher_video = Path(args.teacher_video).expanduser().resolve()
    student_video = Path(args.student_video).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()

    teacher_track = extract_pose_track(teacher_video, frame_stride=max(1, int(args.frame_stride)))
    student_track = extract_pose_track(student_video, frame_stride=max(1, int(args.frame_stride)))

    stats = build_synced_video(
        teacher_track=teacher_track,
        student_track=student_track,
        output_path=output,
        max_frames_per_rep=max(20, int(args.max_frames_per_rep)),
    )

    print("Done")
    print(f"Output: {output}")
    print(f"Detected reps: {stats['rep_count']}")
    print(f"Frames written: {stats['frames_written']}")
    print(f"Average normalized DTW: {stats['avg_normalized_dtw']:.4f}")


if __name__ == "__main__":
    main()
