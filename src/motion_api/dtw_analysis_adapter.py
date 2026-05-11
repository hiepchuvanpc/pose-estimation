from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from motion_core.dtw import dtw_distance


@dataclass(slots=True)
class DTWAnalysisSummary:
    estimated_reps: int
    normalized_distance: float
    similarity: float
    rep_ranges: list[tuple[int, int]]


class DTWAnalysisAdapter:
    """Lean post-analysis adapter inspired by the standalone dtw analysis pipeline."""

    def run(
        self,
        *,
        template_features: list[list[float]],
        student_features: list[list[float]],
        expected_reps: int | None,
    ) -> DTWAnalysisSummary:
        if not template_features or not student_features:
            return DTWAnalysisSummary(estimated_reps=0, normalized_distance=1.0, similarity=0.0, rep_ranges=[])

        t_arr = np.asarray(template_features, dtype=np.float32)
        s_arr = np.asarray(student_features, dtype=np.float32)
        dim = min(t_arr.shape[1], s_arr.shape[1]) if t_arr.ndim == 2 and s_arr.ndim == 2 else 0
        if dim <= 0:
            return DTWAnalysisSummary(estimated_reps=0, normalized_distance=1.0, similarity=0.0, rep_ranges=[])

        t_arr = t_arr[:, :dim]
        s_arr = s_arr[:, :dim]

        signal_t, signal_s = self._build_phase_signals(t_arr, s_arr)
        rep_ranges = self._detect_rep_ranges(signal_t, signal_s, expected_reps)

        if not rep_ranges:
            all_dtw = dtw_distance(signal_t.reshape(-1, 1).tolist(), signal_s.reshape(-1, 1).tolist(), window=20)
            norm = float(all_dtw.normalized_distance)
            return DTWAnalysisSummary(
                estimated_reps=0,
                normalized_distance=norm,
                similarity=self._similarity_from_norm(norm),
                rep_ranges=[],
            )

        rep_distances: list[float] = []
        t_norm = self._normalize_signal(signal_t)
        for start_idx, end_idx in rep_ranges:
            seg = signal_s[start_idx : end_idx + 1]
            if len(seg) < 4:
                continue
            s_norm = self._normalize_signal(seg)
            dtw = dtw_distance(t_norm.reshape(-1, 1).tolist(), s_norm.reshape(-1, 1).tolist(), window=20)
            rep_distances.append(float(dtw.normalized_distance))

        if not rep_distances:
            rep_distances = [1.0]

        avg_norm = float(np.mean(rep_distances))
        return DTWAnalysisSummary(
            estimated_reps=len(rep_ranges),
            normalized_distance=avg_norm,
            similarity=self._similarity_from_norm(avg_norm),
            rep_ranges=rep_ranges,
        )

    def _build_phase_signals(self, template_arr: np.ndarray, student_arr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        t_centered = template_arr - np.mean(template_arr, axis=0, keepdims=True)
        _, _, vt = np.linalg.svd(t_centered, full_matrices=False)
        principal_axis = vt[0]

        t_signal = (template_arr - np.mean(template_arr, axis=0, keepdims=True)) @ principal_axis
        s_signal = (student_arr - np.mean(template_arr, axis=0, keepdims=True)) @ principal_axis

        return self._smooth_signal(t_signal), self._smooth_signal(s_signal)

    @staticmethod
    def _smooth_signal(signal: np.ndarray) -> np.ndarray:
        if signal.size < 5:
            return signal.astype(np.float32)
        kernel = np.ones(5, dtype=np.float32) / 5.0
        return np.convolve(signal, kernel, mode="same").astype(np.float32)

    def _detect_rep_ranges(
        self,
        teacher_signal: np.ndarray,
        student_signal: np.ndarray,
        expected_reps: int | None,
    ) -> list[tuple[int, int]]:
        if student_signal.size < 10:
            return []

        t0 = float(teacher_signal[0])
        t_min = float(np.min(teacher_signal))
        t_max = float(np.max(teacher_signal))
        bottom_is_min = abs(t_min - t0) > abs(t_max - t0)

        peaks = self._find_major_peaks(student_signal, find_max=bottom_is_min)
        if len(peaks) < 2:
            return []

        ranges: list[tuple[int, int]] = []
        for idx in range(len(peaks) - 1):
            start_idx = int(peaks[idx])
            end_idx = int(peaks[idx + 1])
            if end_idx - start_idx < 6:
                continue
            ranges.append((start_idx, end_idx))

        if expected_reps and expected_reps > 0 and len(ranges) > expected_reps:
            ranges = ranges[:expected_reps]
        return ranges

    @staticmethod
    def _find_major_peaks(signal: np.ndarray, *, find_max: bool) -> list[int]:
        values = signal if find_max else (-signal)
        span = float(np.max(values) - np.min(values))
        if span <= 1e-6:
            return [0, len(values) - 1]

        min_height = float(np.min(values) + 0.65 * span)
        min_distance = max(12, int(len(values) * 0.08))
        peaks: list[int] = []
        last = -10_000

        for i in range(1, len(values) - 1):
            left = float(values[i - 1])
            center = float(values[i])
            right = float(values[i + 1])
            if center >= left and center >= right and center >= min_height and (i - last) >= min_distance:
                peaks.append(i)
                last = i

        if not peaks:
            return [0, len(values) - 1]

        if peaks[0] > min_distance:
            peaks.insert(0, 0)
        if (len(values) - 1 - peaks[-1]) > min_distance:
            peaks.append(len(values) - 1)
        return peaks

    @staticmethod
    def _normalize_signal(signal: np.ndarray) -> np.ndarray:
        lo = float(np.min(signal))
        hi = float(np.max(signal))
        if hi - lo < 1e-6:
            return np.zeros_like(signal, dtype=np.float32)
        return ((signal - lo) / (hi - lo)).astype(np.float32)

    @staticmethod
    def _similarity_from_norm(norm_dist: float) -> float:
        if not np.isfinite(norm_dist):
            return 0.0
        if norm_dist <= 0.0:
            return 1.0
        return max(0.0, min(1.0, 1.0 / (1.0 + norm_dist)))


def build_clean_segment_result(*, template_id: str, exercise_name: str, mode: str, segment: dict[str, Any], summary: DTWAnalysisSummary) -> dict[str, Any]:
    return {
        "template_id": template_id,
        "exercise_name": exercise_name,
        "mode": mode,
        "step_index": int(segment.get("step_index", 0)),
        "set_index": int(segment.get("set_index", 0)),
        "video_uri": str(segment.get("video_uri", "")),
        "duration_seconds": round(float(segment.get("duration_seconds", 0.0)), 2),
        "samples": 0,
        "distance": round(float(summary.normalized_distance), 4),
        "normalized_distance": round(float(summary.normalized_distance), 4),
        "similarity": round(float(summary.similarity), 4),
        "top_issues": [],
        "feedback": [],
        "scoring": {
            "overall": round(float(summary.similarity) * 100.0, 2),
            "technique": round(float(summary.similarity) * 100.0, 2),
            "consistency": round(float(summary.similarity) * 100.0, 2),
            "camera_view_mismatch": False,
            "axis_hint": "",
            "vertical_axis_delta_deg": 0.0,
        },
        "reference_plane": {
            "type": "body_vertical",
            "vertical_axis_delta_deg": 0.0,
            "camera_view_mismatch": False,
            "note": "",
        },
        "joint_analyses": [],
        "active_joints": [],
        "top_joint_issues": [],
        "pose_connections": [],
        "template_pose_samples": [],
        "student_pose_samples": [],
        "pose_frame_count": 0,
        "template_cycles": 1,
        "observed_student_reps": int(segment.get("observed_rep_count") or 0),
        "estimated_student_reps": int(summary.estimated_reps),
        "effective_rep_target": int(segment.get("observed_rep_count") or summary.estimated_reps or 1),
        "student_motion_score": 0.0,
        "student_low_motion": False,
        "template_assumed_single_rep": bool(mode == "reps"),
        "template_video_uri": "",
        "comparison_video_uri": str(segment.get("video_uri", "")),
        "comparison_video_generated": False,
        "comparison_video_source": "disabled",
        "sync_video_stats": {},
        "timing_ms": {
            "extract_student_pose": 0,
            "student_features": 0,
            "dtw": 0,
            "post_process": 0,
            "render_comparison_video": 0,
            "total": 0,
        },
        "frame_analyses": [],
        "rep_feedback": [
            {
                "rep_index": idx + 1,
                "quality": "ok" if summary.similarity >= 0.6 else "needs_work",
                "note": "Ổn định nhịp tốt" if summary.similarity >= 0.6 else "Biên độ/chuyển pha chưa ổn định",
            }
            for idx in range(max(0, summary.estimated_reps))
        ],
        "dtw_analysis_rep_ranges": [[int(a), int(b)] for a, b in summary.rep_ranges],
    }
