from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from .types import Frame

LEFT_SHOULDER = "left_shoulder"
RIGHT_SHOULDER = "right_shoulder"
NECK = "neck"
MID_HIP = "mid_hip"
HEAD_KEYS = ("nose", "left_eye", "right_eye", "left_ear", "right_ear")
ANKLE_KEYS = ("left_ankle", "right_ankle")

DEFAULT_WEIGHTS = {
    "left_shoulder": 1.0,
    "right_shoulder": 1.0,
    "left_hip": 1.0,
    "right_hip": 1.0,
    "left_knee": 1.2,
    "right_knee": 1.2,
    "left_ankle": 1.2,
    "right_ankle": 1.2,
    "left_elbow": 0.8,
    "right_elbow": 0.8,
    "left_wrist": 0.8,
    "right_wrist": 0.8,
}


@dataclass(frozen=True)
class ReadinessParams:
    alpha: float = 0.4
    beta: float = 0.4
    gamma: float = 0.2
    tau_rho: float = 0.25
    tau_center: float = 0.25
    min_keypoint_score: float = 0.2
    min_readiness: float = 0.7
    min_completeness: float = 0.75


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _get_xy(frame: Frame, name: str) -> tuple[float, float] | None:
    kp = frame.get(name)
    if kp is None:
        return None
    return (kp.x, kp.y)


def yaw_proxy(frame: Frame, eps: float = 1e-6) -> float:
    ls = _get_xy(frame, LEFT_SHOULDER)
    rs = _get_xy(frame, RIGHT_SHOULDER)
    neck = _get_xy(frame, NECK)
    hip = _get_xy(frame, MID_HIP)
    if not ls or not rs or not neck or not hip:
        return 0.0

    shoulder_width = _distance(ls, rs)
    torso_height = _distance(neck, hip)
    return shoulder_width / (torso_height + eps)


def orientation_match(student: Frame, teacher: Frame) -> float:
    """
    Check if student and teacher have same vertical orientation (up/down).
    Returns 1.0 if same orientation, 0.0 if flipped (180 degrees).
    
    Logic: In push-up, head is ABOVE hips (head.y < hip.y in image coords).
           In lying face-up, head is BELOW hips (head.y > hip.y).
    """
    # Get head position (use nose as primary)
    student_nose = _get_xy(student, "nose")
    teacher_nose = _get_xy(teacher, "nose")
    student_hip = _get_xy(student, MID_HIP)
    teacher_hip = _get_xy(teacher, MID_HIP)
    
    if not all([student_nose, teacher_nose, student_hip, teacher_hip]):
        return 1.0  # If missing keypoints, assume OK (don't block)
    
    # Check vertical direction: head relative to hip
    # In image coords, y increases downward
    student_head_above = student_nose[1] < student_hip[1]  # head higher than hip
    teacher_head_above = teacher_nose[1] < teacher_hip[1]
    
    # If both have same orientation (both head-above or both head-below), good!
    if student_head_above == teacher_head_above:
        return 1.0
    else:
        return 0.0  # Flipped 180 degrees!


def view_similarity(student: Frame, teacher: Frame, tau_rho: float = 0.25) -> float:
    # Check yaw (left-right orientation)
    rho_s = yaw_proxy(student)
    rho_t = yaw_proxy(teacher)
    yaw_score = math.exp(-abs(rho_s - rho_t) / max(tau_rho, 1e-6))
    
    # Check orientation (up-down, prevent 180-degree flip)
    orientation_score = orientation_match(student, teacher)
    
    # Combine: both must be good
    return yaw_score * orientation_score


def completeness_score(frame: Frame, min_keypoint_score: float = 0.2, weights: dict[str, float] | None = None) -> float:
    use_weights = weights or DEFAULT_WEIGHTS
    weighted_sum = 0.0
    total_w = 0.0

    for name, w in use_weights.items():
        total_w += w
        kp = frame.get(name)
        if kp is None:
            continue
        s = kp.score if kp.score >= min_keypoint_score else 0.0
        weighted_sum += w * min(max(s, 0.0), 1.0)

    if total_w <= 0:
        return 0.0
    return weighted_sum / total_w


def _in_frame(x: float, y: float, width: int, height: int) -> bool:
    return 0 <= x <= width and 0 <= y <= height


def _find_visible(frame: Frame, candidates: Iterable[str], min_keypoint_score: float, width: int, height: int) -> bool:
    for name in candidates:
        kp = frame.get(name)
        if kp is None or kp.score < min_keypoint_score:
            continue
        if _in_frame(kp.x, kp.y, width, height):
            return True
    return False


def framing_score(frame: Frame, frame_width: int, frame_height: int, tau_center: float = 0.25, min_keypoint_score: float = 0.2) -> float:
    if frame_width <= 0 or frame_height <= 0:
        return 0.0

    head_visible = _find_visible(frame, HEAD_KEYS, min_keypoint_score, frame_width, frame_height)
    ankle_visible = _find_visible(frame, ANKLE_KEYS, min_keypoint_score, frame_width, frame_height)
    if not (head_visible and ankle_visible):
        return 0.0

    visible = [kp for kp in frame.values() if kp.score >= min_keypoint_score and _in_frame(kp.x, kp.y, frame_width, frame_height)]
    if not visible:
        return 0.0

    cx = sum(kp.x for kp in visible) / len(visible)
    cy = sum(kp.y for kp in visible) / len(visible)
    dx = (cx - (frame_width / 2)) / frame_width
    dy = (cy - (frame_height / 2)) / frame_height
    center_dist = math.hypot(dx, dy)
    return math.exp(-center_dist / max(tau_center, 1e-6))


def readiness_score(student: Frame, teacher: Frame, frame_width: int, frame_height: int, params: ReadinessParams) -> tuple[float, float, float, float]:
    s_view = view_similarity(student, teacher, tau_rho=params.tau_rho)
    s_comp = completeness_score(student, min_keypoint_score=params.min_keypoint_score)
    s_frame = framing_score(
        student,
        frame_width=frame_width,
        frame_height=frame_height,
        tau_center=params.tau_center,
        min_keypoint_score=params.min_keypoint_score,
    )
    total = params.alpha * s_view + params.beta * s_comp + params.gamma * s_frame
    return total, s_view, s_comp, s_frame


def readiness_feedback(s_view: float, s_comp: float, s_frame: float, params: ReadinessParams) -> list[str]:
    feedback: list[str] = []

    if s_view < params.min_readiness:
        feedback.append("Điều chỉnh góc quay cơ thể hoặc hướng lên/xuống để tương đồng hơn với giáo viên.")
    if s_comp < params.min_completeness:
        feedback.append("Đảm bảo toàn thân vào khung hình, đặc biệt vai-hông-gối-cổ chân.")
    if s_frame < params.min_readiness:
        feedback.append("Đưa cơ thể vào giữa khung hình và kiểm tra không bị cắt đầu/chân.")

    if not feedback:
        feedback.append("Sẵn sàng so khớp động tác.")
    return feedback
