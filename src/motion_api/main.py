from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi import Query
from fastapi.responses import FileResponse
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from motion_core.dtw import dtw_distance, segment_by_signal_valleys, dtw_per_rep
from motion_core.exercise_tracking import (
    ExerciseSpec,
    HoldTimerConfig,
    MultiExerciseSession,
    RepCounter,
    RepCounterConfig,
    SignalNormalizer,
)
from motion_core.features import (
    frame_features,
    sequence_features,
    features_from_sample,
    features_from_samples,
    FEATURE_DIM,
)
from motion_core.mediapipe_pose import LANDMARK_INDEX
from motion_core.preprocessing import normalize_frame, normalize_sequence
from motion_core.readiness import (
    ReadinessParams,
    completeness_score,
    framing_score,
    readiness_feedback,
    readiness_score,
    view_similarity,
)
from motion_core.template_profile import (
    FEATURE_GROUPS,
    JOINT_ANALYSIS_SPECS,
    POSE_CONNECTIONS,
    build_template_profile_from_features,
    extract_video_pose_samples,
)
from motion_core.rep_cycle import detect_rep_cycles, RepCycleInfo
from motion_core.types import Keypoint
from motion_core.workout_orchestrator import WorkoutPlan, WorkoutSession, WorkoutStepConfig, WorkoutTemplate
from .persistence import SqliteStore, StoredTemplate

from .schemas import (
    AlignRequest,
    AlignResponse,
    AnalysisVideoItem,
    AnalysisVideoListResponse,
    HealthResponse,
    LiveSessionFrameRequest,
    LiveSessionFrameResponse,
    LiveSessionStartRequest,
    LiveSessionStartResponse,
    DeleteResponse,
    TemplateCreateRequest,
    TemplateItem,
    TemplateListResponse,
    TemplateUpdateRequest,
    TemplateProfileResponse,
    VideoUploadResponse,
    WorkoutConfirmRequest,
    WorkoutFinalizeRequest,
    WorkoutFinalizeResponse,
    WorkoutFrameRequest,
    WorkoutProgressResponse,
    WorkoutSegmentCreateRequest,
    WorkoutSegmentResponse,
    WorkoutSessionStartRequest,
    WorkoutSessionStartResponse,
    ReadinessRequest,
    ReadinessResponse,
)
from .speaker import Speaker

app = FastAPI(title="Motion Coach API", version="0.1.0")
WEB_DIR = Path(__file__).resolve().parents[2] / "web"
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
ANALYSIS_DIR = UPLOAD_DIR / "analysis_sync"
TEMPLATE_FROZEN_DIR = UPLOAD_DIR / "template_frozen"
TEMPLATE_DEBUG_DIR = UPLOAD_DIR / "template_debug"
TEMPLATE_POSE_TIMELINE_DIR = UPLOAD_DIR / "template_pose_timeline"
TEMPLATE_STORE_PATH = DATA_DIR / "templates.json"
UPLOAD_INDEX_PATH = DATA_DIR / "upload_index.json"
TEMPLATE_PROFILE_STORE_PATH = DATA_DIR / "template_profiles.json"
SQLITE_DB_PATH = DATA_DIR / "motion_coach.db"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATE_FROZEN_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATE_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATE_POSE_TIMELINE_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="web_static")
app.mount("/data/models", StaticFiles(directory=str(DATA_DIR / "models")), name="data_models")

LIVE_SESSIONS: dict[str, MultiExerciseSession] = {}
TEMPLATE_LIBRARY: dict[str, WorkoutTemplate] = {}
WORKOUT_SESSIONS: dict[str, WorkoutSession] = {}
WORKOUT_SPEAKERS: dict[str, Speaker] = {}
WORKOUT_EVENT_LOGS: dict[str, list[dict[str, Any]]] = {}
WORKOUT_SEGMENTS: dict[str, list[dict[str, Any]]] = {}
TEMPLATE_PROFILES: dict[str, dict[str, Any]] = {}
STORE = SqliteStore(SQLITE_DB_PATH)
WORKOUT_EVENT_BUFFER: dict[str, list[dict[str, Any]]] = {}
WORKOUT_LAST_STATE_PERSIST: dict[str, dict[str, Any]] = {}
WORKOUT_SPEECH_STATE: dict[str, dict[str, Any]] = {}
EVENT_BUFFER_FLUSH_SIZE = 30
MAX_IN_MEMORY_EVENTS = 3000
SPEECH_COOLDOWN_SECONDS = 2.5

# Unified skeleton style across live/debug/post-analysis views.
OVERLAY_BGR = (99, 111, 19)  # #136f63 in BGR
OVERLAY_LINE_THICKNESS = 3
OVERLAY_POINT_RADIUS = 4
DEBUG_BASE_POINT_BGR = (0, 255, 0)
DEBUG_BASE_LINE_BGR = (255, 200, 0)
DEBUG_BASE_POINT_RADIUS = 3
DEBUG_BASE_LINE_THICKNESS = 2
POSE_TIMELINE_SCHEMA_VERSION = "pose_timeline_v1"
DEBUG_BASE_POSE_CONNECTIONS = [
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 7),
    (0, 4),
    (4, 5),
    (5, 6),
    (6, 8),
    (9, 10),
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
    (15, 17),
    (16, 18),
    (15, 19),
    (16, 20),
    (15, 21),
    (16, 22),
    (11, 23),
    (12, 24),
    (23, 24),
    (23, 25),
    (25, 27),
    (27, 29),
    (29, 31),
    (24, 26),
    (26, 28),
    (28, 30),
    (30, 32),
]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _quantile(values: list[float], q: float, default: float = 0.0) -> float:
    nums = sorted(float(v) for v in values)
    if not nums:
        return default
    q = _clamp(q, 0.0, 1.0)
    if len(nums) == 1:
        return nums[0]
    pos = q * (len(nums) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return nums[lo]
    frac = pos - lo
    return nums[lo] * (1.0 - frac) + nums[hi] * frac


def _phase_signal_from_feature(feature: list[float], profile: dict[str, Any]) -> float:
    mean = [float(x) for x in profile.get("feature_mean", [])]
    pc1 = [float(x) for x in profile.get("feature_pc1", [])]
    if not mean or not pc1:
        return 0.0
    centered = [feature[i] - (mean[i] if i < len(mean) else 0.0) for i in range(len(feature))]
    proj = sum(centered[i] * (pc1[i] if i < len(pc1) else 0.0) for i in range(len(centered)))
    min_p = float(profile.get("proj_min", 0.0))
    max_p = float(profile.get("proj_max", 1.0))
    denom = max(1e-6, max_p - min_p)
    return _clamp((proj - min_p) / denom, 0.0, 1.0)


def _build_adaptive_thresholds(profile: dict[str, Any], template_mode: str) -> dict[str, Any]:
    features = profile.get("features", [])
    if not isinstance(features, list) or not features:
        return {}

    phase_values: list[float] = []
    similarities: list[float] = []
    signals: list[float] = []
    for raw_feature in features:
        feature = [float(x) for x in raw_feature]
        phase = _phase_signal_from_feature(feature, profile)
        signal, similarity = _signal_and_similarity(feature, profile)
        phase_values.append(phase)
        similarities.append(float(similarity))
        signals.append(float(signal))

    sample_count = len(features)
    short_template = sample_count < 30

    if sample_count < 10:
        # Too few samples for stable quantile estimates: prefer conservative defaults.
        readiness = {
            "similarity_min": 0.35,
            "mean_min": 0.38,
            "spread_max": 0.32,
            "anchor_tolerance": 0.34,
            "min_readiness": 0.6,
            "min_completeness": 0.72,
        }
        tracking = {
            "rep_high_enter": 0.64,
            "rep_low_exit": 0.28,
            "rep_min_high_frames": 1,
            "hold_threshold": 0.46,
            "hold_stop_threshold": 0.34,
            "hold_pause_not_ready_frames": 2,
        }
        signal = {
            "phase_weight": 0.55,
            "similarity_weight": 0.45,
            "distance_scale": 3.0,
        }
        return {
            **tracking,
            **{
                "readiness_similarity_min": readiness["similarity_min"],
                "readiness_mean_min": readiness["mean_min"],
                "readiness_spread_max": readiness["spread_max"],
                "readiness_anchor_tolerance": readiness["anchor_tolerance"],
                "readiness_min": readiness["min_readiness"],
                "readiness_min_completeness": readiness["min_completeness"],
                "signal_phase_weight": signal["phase_weight"],
                "signal_similarity_weight": signal["similarity_weight"],
                "similarity_distance_scale": signal["distance_scale"],
                "template_sample_count": sample_count,
                "short_template_mode": True,
                "adaptive_reliability": "low-sample-fallback",
            },
            "readiness": readiness,
            "tracking": tracking,
            "signal": signal,
        }

    sim_q25 = _quantile(similarities, 0.25, default=0.35)
    sim_q45 = _quantile(similarities, 0.45, default=0.45)
    sim_q60 = _quantile(similarities, 0.60, default=0.55)
    sim_q72 = _quantile(similarities, 0.72, default=0.62)
    sim_q75 = _quantile(similarities, 0.75, default=0.65)
    sim_iqr = max(0.02, sim_q75 - sim_q25)
    phase_iqr = max(0.03, _quantile(phase_values, 0.75, default=0.8) - _quantile(phase_values, 0.25, default=0.2))

    rep_high = _clamp(_quantile(signals, 0.72, default=0.72), 0.55, 0.92)
    rep_low = _clamp(_quantile(signals, 0.28, default=0.38), 0.08, rep_high - 0.08)
    if short_template:
        scarcity = _clamp((30 - sample_count) / 30.0, 0.0, 1.0)
        rep_high = _clamp(rep_high - (0.09 * scarcity), 0.50, 0.90)
        rep_low = _clamp(rep_low + (0.06 * scarcity), 0.10, rep_high - 0.08)

    hold_threshold = _clamp(max(sim_q60, 0.35), 0.28, 0.9)
    hold_stop = _clamp(hold_threshold - max(0.05, sim_iqr * 0.65), 0.10, hold_threshold - 0.04)

    readiness_similarity_min = _clamp(sim_q45, 0.34, 0.8)
    readiness_mean_min = _clamp(sim_q60, 0.38, 0.86)
    readiness_spread_max = _clamp((sim_iqr * 1.55) + 0.06, 0.08, 0.35)
    readiness_anchor_tolerance = _clamp((phase_iqr * 0.75) + 0.05, 0.08, 0.34)
    readiness_min = _clamp(0.5 + (0.3 * readiness_similarity_min), 0.58, 0.82)
    readiness_min_completeness = _clamp(0.72 + (0.08 * sim_q25), 0.72, 0.86)
    if short_template:
        scarcity = _clamp((30 - sample_count) / 30.0, 0.0, 1.0)
        readiness_similarity_min = _clamp(readiness_similarity_min - (0.08 * scarcity), 0.26, 0.78)
        readiness_mean_min = _clamp(readiness_mean_min - (0.07 * scarcity), 0.30, 0.84)
        readiness_spread_max = _clamp(readiness_spread_max + (0.09 * scarcity), 0.08, 0.42)
        readiness_anchor_tolerance = _clamp(readiness_anchor_tolerance + (0.10 * scarcity), 0.08, 0.46)
        readiness_min = _clamp(readiness_min - (0.06 * scarcity), 0.54, 0.82)
        readiness_min_completeness = _clamp(readiness_min_completeness - (0.05 * scarcity), 0.68, 0.86)

    proj_span = abs(float(profile.get("proj_max", 1.0)) - float(profile.get("proj_min", 0.0)))
    if template_mode == "hold":
        phase_weight = 0.35
        sim_weight = 0.65
    elif proj_span < 0.22:
        phase_weight = 0.5
        sim_weight = 0.5
    else:
        phase_weight = 0.62
        sim_weight = 0.38

    similarity_distance_scale = _clamp(2.4 + (sim_iqr * 4.0), 1.8, 4.8)

    readiness = {
        "similarity_min": round(readiness_similarity_min, 4),
        "mean_min": round(readiness_mean_min, 4),
        "spread_max": round(readiness_spread_max, 4),
        "anchor_tolerance": round(readiness_anchor_tolerance, 4),
        "min_readiness": round(readiness_min, 4),
        "min_completeness": round(readiness_min_completeness, 4),
    }

    tracking = {
        "rep_high_enter": round(rep_high, 4),
        "rep_low_exit": round(rep_low, 4),
        "rep_min_high_frames": 1,
        "hold_threshold": round(hold_threshold, 4),
        "hold_stop_threshold": round(hold_stop, 4),
        "hold_pause_not_ready_frames": 2,
    }

    signal = {
        "phase_weight": round(phase_weight, 4),
        "similarity_weight": round(sim_weight, 4),
        "distance_scale": round(similarity_distance_scale, 4),
    }

    # Duplicate key fields at top-level for backward compatibility with existing consumers.
    return {
        **tracking,
        **{
            "readiness_similarity_min": readiness["similarity_min"],
            "readiness_mean_min": readiness["mean_min"],
            "readiness_spread_max": readiness["spread_max"],
            "readiness_anchor_tolerance": readiness["anchor_tolerance"],
            "readiness_min": readiness["min_readiness"],
            "readiness_min_completeness": readiness["min_completeness"],
            "signal_phase_weight": signal["phase_weight"],
            "signal_similarity_weight": signal["similarity_weight"],
            "similarity_distance_scale": signal["distance_scale"],
            "template_sample_count": sample_count,
            "short_template_mode": short_template,
        },
        "readiness": readiness,
        "tracking": tracking,
        "signal": signal,
    }


def _profile_rep_counter_config(profile: dict[str, Any] | None) -> RepCounterConfig:
    data = profile if isinstance(profile, dict) else {}
    adaptive = data.get("adaptive_thresholds", {}) if isinstance(data.get("adaptive_thresholds"), dict) else {}
    high_enter = _clamp(float(adaptive.get("rep_high_enter", 0.72)), 0.5, 0.95)
    low_exit = _clamp(float(adaptive.get("rep_low_exit", 0.38)), 0.05, high_enter - 0.08)
    min_high_frames = max(1, int(adaptive.get("rep_min_high_frames", 1)))
    return RepCounterConfig(high_enter=high_enter, low_exit=low_exit, min_high_frames=min_high_frames)


def _profile_hold_timer_config(profile: dict[str, Any] | None) -> HoldTimerConfig:
    data = profile if isinstance(profile, dict) else {}
    adaptive = data.get("adaptive_thresholds", {}) if isinstance(data.get("adaptive_thresholds"), dict) else {}
    hold_threshold = _clamp(float(adaptive.get("hold_threshold", 0.55)), 0.2, 0.95)
    stop_threshold = _clamp(float(adaptive.get("hold_stop_threshold", 0.45)), 0.05, hold_threshold - 0.05)
    return HoldTimerConfig(hold_threshold=hold_threshold, stop_threshold=stop_threshold)


def _profile_readiness_params(profile: dict[str, Any] | None) -> ReadinessParams:
    data = profile if isinstance(profile, dict) else {}
    adaptive = data.get("adaptive_thresholds", {}) if isinstance(data.get("adaptive_thresholds"), dict) else {}
    nested = adaptive.get("readiness", {}) if isinstance(adaptive.get("readiness"), dict) else {}
    min_readiness = float(nested.get("min_readiness", adaptive.get("readiness_min", 0.7)))
    min_completeness = float(nested.get("min_completeness", adaptive.get("readiness_min_completeness", 0.75)))
    return ReadinessParams(
        min_readiness=_clamp(min_readiness, 0.55, 0.9),
        min_completeness=_clamp(min_completeness, 0.65, 0.95),
    )


def _frame_from_pose_sample(sample: list[list[float]], frame_width: int, frame_height: int) -> dict[str, Keypoint]:
    frame: dict[str, Keypoint] = {}
    width = max(1, int(frame_width))
    height = max(1, int(frame_height))
    for name, idx in LANDMARK_INDEX.items():
        if idx >= len(sample):
            continue
        point = sample[idx]
        x_norm = float(point[0]) if len(point) > 0 else 0.0
        y_norm = float(point[1]) if len(point) > 1 else 0.0
        score = float(point[3]) if len(point) > 3 else 0.0
        frame[name] = Keypoint(x=x_norm * width, y=y_norm * height, score=score)

    left_hip = frame.get("left_hip")
    right_hip = frame.get("right_hip")
    if left_hip and right_hip:
        frame["mid_hip"] = Keypoint(
            x=(left_hip.x + right_hip.x) / 2.0,
            y=(left_hip.y + right_hip.y) / 2.0,
            score=min(left_hip.score, right_hip.score),
        )

    left_shoulder = frame.get("left_shoulder")
    right_shoulder = frame.get("right_shoulder")
    if left_shoulder and right_shoulder:
        frame["neck"] = Keypoint(
            x=(left_shoulder.x + right_shoulder.x) / 2.0,
            y=(left_shoulder.y + right_shoulder.y) / 2.0,
            score=min(left_shoulder.score, right_shoulder.score),
        )
    return frame


def _sample_core_visibility(sample: list[list[float]]) -> float:
    core_indices = [11, 12, 23, 24, 25, 26, 27, 28]
    if not isinstance(sample, list) or not sample:
        return 0.0
    scores: list[float] = []
    for idx in core_indices:
        if idx >= len(sample):
            continue
        point = sample[idx]
        vis = float(point[3]) if len(point) > 3 else 0.0
        scores.append(_clamp(vis, 0.0, 1.0))
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def _build_anchor_pose_bank(pose_samples: list[list[list[float]]], max_anchors: int = 8) -> list[list[list[float]]]:
    if not pose_samples:
        return []

    n = len(pose_samples)
    if n < 30:
        # Short templates (4-10s, 1-2 reps): keep broader temporal coverage,
        # then select visibility-aware anchors across the full sequence.
        window = pose_samples
        max_anchors = min(10, max_anchors + 2)
    else:
        # Longer templates: focus on early frames for start-pose readiness.
        early = len(pose_samples) // 4 if len(pose_samples) >= 16 else len(pose_samples)
        window = pose_samples[: max(8, min(24, early))]

    candidates = [sample for sample in window if _sample_core_visibility(sample) >= 0.30]
    if not candidates:
        candidates = window

    if len(candidates) <= max_anchors:
        return candidates

    anchors: list[list[list[float]]] = []
    for idx in range(max_anchors):
        pos = round(idx * (len(candidates) - 1) / max(1, max_anchors - 1))
        anchors.append(candidates[pos])
    return anchors


def _feature_similarity(a: list[float], b: list[float], distance_scale: float = 2.8) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    if n <= 0:
        return 0.0
    total = 0.0
    for idx in range(n):
        d = float(a[idx]) - float(b[idx])
        total += d * d
    dist = math.sqrt(total)
    scale = _clamp(distance_scale, 0.5, 8.0)
    return math.exp(-dist / scale)


def _profile_anchor_pose_samples(profile: dict[str, Any]) -> list[list[list[float]]]:
    anchors = profile.get("anchor_pose_samples")
    if isinstance(anchors, list) and anchors:
        return [sample for sample in anchors if isinstance(sample, list) and sample]
    anchor = profile.get("anchor_pose_sample")
    if isinstance(anchor, list) and anchor:
        return [anchor]
    return []


def _compute_anchor_readiness(session: WorkoutSession, student_frame_model: Any) -> bool | None:
    template = session.current_template()
    if template is None:
        return None

    profile = TEMPLATE_PROFILES.get(template.template_id)
    if profile is None:
        profile = STORE.get_template_profile(template.template_id)
        if isinstance(profile, dict):
            TEMPLATE_PROFILES[template.template_id] = profile
    if not isinstance(profile, dict):
        return None

    anchor_samples = _profile_anchor_pose_samples(profile)
    if not anchor_samples:
        return None

    width = getattr(student_frame_model, "frame_width", None)
    height = getattr(student_frame_model, "frame_height", None)
    if not width or not height:
        return None

    student_raw = _to_core_frame(student_frame_model)
    student = normalize_frame(student_raw)
    params = _profile_readiness_params(profile)
    adaptive = profile.get("adaptive_thresholds", {}) if isinstance(profile.get("adaptive_thresholds"), dict) else {}
    nested_readiness = adaptive.get("readiness", {}) if isinstance(adaptive.get("readiness"), dict) else {}

    dist_scale = _clamp(float(profile.get("similarity_distance_scale", adaptive.get("similarity_distance_scale", 2.8))), 0.5, 8.0)
    similarity_min = _clamp(float(nested_readiness.get("similarity_min", adaptive.get("readiness_similarity_min", 0.5))) - 0.08, 0.2, 0.9)
    min_view = _clamp(float(adaptive.get("readiness_view_min", 0.4)) - 0.08, 0.2, 0.85)
    min_frame = _clamp(float(adaptive.get("readiness_framing_min", 0.32)) - 0.06, 0.1, 0.8)
    template_sample_count = int(adaptive.get("template_sample_count", len(profile.get("features", []) or [])) or 0)

    s_comp = completeness_score(student, min_keypoint_score=params.min_keypoint_score)
    s_frame = framing_score(
        student_raw,
        frame_width=int(width),
        frame_height=int(height),
        tau_center=params.tau_center,
        min_keypoint_score=params.min_keypoint_score,
    )
    student_feature = frame_features(student)

    best_view = 0.0
    best_similarity = 0.0
    for anchor_sample in anchor_samples:
        teacher = normalize_frame(_frame_from_pose_sample(anchor_sample, int(width), int(height)))
        best_view = max(best_view, view_similarity(student, teacher, tau_rho=params.tau_rho))
        teacher_feature = frame_features(teacher)
        best_similarity = max(best_similarity, _feature_similarity(student_feature, teacher_feature, distance_scale=dist_scale))

    if len(anchor_samples) >= 4:
        similarity_min = max(0.22, similarity_min - 0.05)
    if template_sample_count and template_sample_count < 30:
        scarcity = _clamp((30 - template_sample_count) / 30.0, 0.0, 1.0)
        similarity_min = max(0.20, similarity_min - (0.08 * scarcity))
        min_view = max(0.24, min_view - (0.08 * scarcity))
        min_frame = max(0.16, min_frame - (0.07 * scarcity))

    comp_min = params.min_completeness - (0.14 if template_sample_count and template_sample_count < 30 else 0.1)
    if best_view >= min_view and best_similarity >= similarity_min and s_comp >= comp_min and s_frame >= min_frame:
        return True

    # Soft fallback for noisy camera orientations: rely more on similarity + body completeness.
    return bool(best_similarity >= max(0.24, similarity_min - 0.08) and s_comp >= max(0.62, comp_min - 0.06) and s_frame >= 0.1)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="tmp_", suffix=".json", dir=str(path.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _persist_templates() -> None:
    payload = {
        "items": [
            {
                "template_id": item.template_id,
                "name": item.name,
                "mode": item.mode,
                "video_uri": item.video_uri,
                "notes": item.notes,
                "trim_start_sec": item.trim_start_sec,
                "trim_end_sec": item.trim_end_sec,
            }
            for item in TEMPLATE_LIBRARY.values()
        ]
    }
    _write_json_atomic(TEMPLATE_STORE_PATH, payload)


def _persist_template_to_store(template: WorkoutTemplate) -> None:
    STORE.upsert_template(
        StoredTemplate(
            template_id=template.template_id,
            name=template.name,
            mode=template.mode,
            video_uri=template.video_uri,
            notes=template.notes,
            trim_start_sec=getattr(template, "trim_start_sec", None),
            trim_end_sec=getattr(template, "trim_end_sec", None),
        )
    )


def _load_templates() -> None:
    data = _read_json(TEMPLATE_STORE_PATH, {"items": []})
    items = data.get("items", []) if isinstance(data, dict) else []
    for raw in items:
        try:
            template = WorkoutTemplate(
                template_id=str(raw["template_id"]),
                name=str(raw["name"]),
                mode=str(raw["mode"]),
                video_uri=str(raw["video_uri"]),
                notes=raw.get("notes"),
                trim_start_sec=raw.get("trim_start_sec"),
                trim_end_sec=raw.get("trim_end_sec"),
            )
        except Exception:
            continue

        # Keep template only when referenced uploaded file still exists.
        try:
            _resolve_video_path(template.video_uri)
        except Exception:
            continue
        TEMPLATE_LIBRARY[template.template_id] = template


def _load_templates_from_store() -> int:
    count = 0
    for row in STORE.list_templates():
        template = WorkoutTemplate(
            template_id=row.template_id,
            name=row.name,
            mode=row.mode,
            video_uri=row.video_uri,
            notes=row.notes,
            trim_start_sec=getattr(row, "trim_start_sec", None),
            trim_end_sec=getattr(row, "trim_end_sec", None),
        )
        try:
            _resolve_video_path(template.video_uri)
        except Exception:
            continue
        TEMPLATE_LIBRARY[template.template_id] = template
        count += 1
    return count


def _load_upload_index() -> dict[str, Any]:
    data = _read_json(UPLOAD_INDEX_PATH, {"sha256": {}})
    if not isinstance(data, dict):
        return {"sha256": {}}
    if "sha256" not in data or not isinstance(data["sha256"], dict):
        data["sha256"] = {}
    return data


def _save_upload_index(index: dict[str, Any]) -> None:
    _write_json_atomic(UPLOAD_INDEX_PATH, index)


def _purge_upload_index_by_video_uris(video_uris: list[str]) -> int:
    targets = {str(uri).strip() for uri in video_uris if isinstance(uri, str) and str(uri).strip()}
    if not targets:
        return 0
    index = _load_upload_index()
    sha_map = index.get("sha256", {})
    if not isinstance(sha_map, dict):
        return 0
    removed = 0
    next_map: dict[str, Any] = {}
    for sha, entry in sha_map.items():
        if isinstance(entry, dict) and str(entry.get("video_uri", "")) in targets:
            removed += 1
            continue
        next_map[str(sha)] = entry
    if removed > 0:
        index["sha256"] = next_map
        _save_upload_index(index)
    return removed


def _persist_template_profiles() -> None:
    payload: dict[str, Any] = {"items": {}}
    for template_id, profile in TEMPLATE_PROFILES.items():
        template = TEMPLATE_LIBRARY.get(template_id)
        if template is None:
            continue
        payload["items"][template_id] = {
            "video_uri": template.video_uri,
            "profile": profile,
        }
    _write_json_atomic(TEMPLATE_PROFILE_STORE_PATH, payload)


def _persist_template_profile_to_store(template_id: str, profile: dict[str, Any]) -> None:
    STORE.upsert_template_profile(template_id, profile)


def _load_template_profiles() -> None:
    data = _read_json(TEMPLATE_PROFILE_STORE_PATH, {"items": {}})
    items = data.get("items", {}) if isinstance(data, dict) else {}
    if not isinstance(items, dict):
        return

    for template_id, entry in items.items():
        if not isinstance(entry, dict):
            continue
        template = TEMPLATE_LIBRARY.get(str(template_id))
        if template is None:
            continue

        stored_video_uri = str(entry.get("video_uri", ""))
        profile = entry.get("profile")
        if not isinstance(profile, dict):
            continue

        # Invalidate cache when template source video changed or missing.
        if stored_video_uri != template.video_uri:
            continue
        try:
            _resolve_video_path(template.video_uri)
        except Exception:
            continue

        TEMPLATE_PROFILES[str(template_id)] = profile

    # Invalidate profiles with stale feature version
    from motion_core.template_profile import CURRENT_FEATURE_VERSION
    stale_ids = [
        tid for tid, p in TEMPLATE_PROFILES.items()
        if isinstance(p, dict) and p.get("feature_version") != CURRENT_FEATURE_VERSION
    ]
    for tid in stale_ids:
        del TEMPLATE_PROFILES[tid]


def _load_template_profiles_from_store() -> int:
    count = 0
    for template_id, profile in STORE.list_template_profiles().items():
        template = TEMPLATE_LIBRARY.get(template_id)
        if template is None:
            continue
        try:
            _resolve_video_path(template.video_uri)
        except Exception:
            continue
        TEMPLATE_PROFILES[template_id] = profile
        count += 1

    # Invalidate profiles with stale feature version
    from motion_core.template_profile import CURRENT_FEATURE_VERSION
    stale_ids = [
        tid for tid, p in TEMPLATE_PROFILES.items()
        if isinstance(p, dict) and p.get("feature_version") != CURRENT_FEATURE_VERSION
    ]
    for tid in stale_ids:
        del TEMPLATE_PROFILES[tid]
        count -= 1
    return count


@app.on_event("startup")
def startup_load_persistent_data() -> None:
    STORE.initialize()

    loaded_templates = _load_templates_from_store()
    if loaded_templates == 0:
        _load_templates()
        for template in TEMPLATE_LIBRARY.values():
            _persist_template_to_store(template)

    loaded_profiles = _load_template_profiles_from_store()
    if loaded_profiles == 0:
        _load_template_profiles()
        for template_id, profile in TEMPLATE_PROFILES.items():
            _persist_template_profile_to_store(template_id, profile)


@app.on_event("shutdown")
def shutdown_persistence() -> None:
    # Ensure queued event writes are drained before process exits.
    STORE.close(timeout_seconds=3.0)


@app.get("/")
def web_test_page() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    # Silence browser auto-request to avoid noisy 404 logs.
    return Response(status_code=204)


def _to_core_frame(frame_model) -> dict[str, Keypoint]:
    frame = {
        name: Keypoint(x=kp.x, y=kp.y, score=kp.score)
        for name, kp in frame_model.keypoints.items()
    }

    left_hip = frame.get("left_hip")
    right_hip = frame.get("right_hip")
    if left_hip and right_hip and "mid_hip" not in frame:
        frame["mid_hip"] = Keypoint(
            x=(left_hip.x + right_hip.x) / 2.0,
            y=(left_hip.y + right_hip.y) / 2.0,
            score=min(left_hip.score, right_hip.score),
        )

    left_shoulder = frame.get("left_shoulder")
    right_shoulder = frame.get("right_shoulder")
    if left_shoulder and right_shoulder and "neck" not in frame:
        frame["neck"] = Keypoint(
            x=(left_shoulder.x + right_shoulder.x) / 2.0,
            y=(left_shoulder.y + right_shoulder.y) / 2.0,
            score=min(left_shoulder.score, right_shoulder.score),
        )
    return frame


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/v1/system/persistence-health")
def persistence_health() -> dict[str, int | str]:
    stats = STORE.queue_stats()
    return {
        "status": "ok",
        "pending_events": int(stats.get("pending", 0)),
        "dropped_events": int(stats.get("dropped", 0)),
    }


@app.get("/v1/tts/voices")
def tts_voices() -> dict[str, Any]:
    inspector = Speaker(enabled=False)
    voices = inspector.list_voices()
    selected = next((voice for voice in voices if voice.get("selected") == "true"), None)
    return {
        "count": len(voices),
        "selected": selected,
        "voices": voices,
        "note": "Nếu không có Microsoft An thì backend pyttsx3 chưa nhìn thấy voice Vietnamese.",
    }


@app.post("/v1/readiness", response_model=ReadinessResponse)
def compute_readiness(payload: ReadinessRequest) -> ReadinessResponse:
    teacher = _to_core_frame(payload.teacher_frame)
    student = _to_core_frame(payload.student_frame)

    width = payload.student_frame.frame_width or payload.teacher_frame.frame_width
    height = payload.student_frame.frame_height or payload.teacher_frame.frame_height
    if not width or not height:
        raise HTTPException(status_code=400, detail="frame_width/frame_height are required in teacher or student frame")

    p = payload.params
    core_params = ReadinessParams(
        alpha=p.alpha,
        beta=p.beta,
        gamma=p.gamma,
        tau_rho=p.tau_rho,
        tau_center=p.tau_center,
        min_keypoint_score=p.min_keypoint_score,
        min_readiness=p.min_readiness,
        min_completeness=p.min_completeness,
    )

    # Apply normalization for position & scale invariance
    student_norm = normalize_frame(student)
    teacher_norm = normalize_frame(teacher)

    total, s_view, s_comp, s_frame = readiness_score(student_norm, teacher_norm, width, height, core_params)
    gate_passed = total >= core_params.min_readiness and s_comp >= core_params.min_completeness
    feedback = readiness_feedback(s_view, s_comp, s_frame, core_params)

    return ReadinessResponse(
        readiness=total,
        view_score=s_view,
        completeness_score=s_comp,
        framing_score=s_frame,
        gate_passed=gate_passed,
        feedback=feedback,
    )


@app.post("/v1/align", response_model=AlignResponse)
def align_sequences(payload: AlignRequest) -> AlignResponse:
    if not payload.teacher_frames or not payload.student_frames:
        raise HTTPException(status_code=400, detail="teacher_frames and student_frames must be non-empty")

    teacher_seq = [_to_core_frame(f) for f in payload.teacher_frames]
    student_seq = [_to_core_frame(f) for f in payload.student_frames]

    # Apply normalization for position & scale invariance
    teacher_seq_norm = normalize_sequence(teacher_seq)
    student_seq_norm = normalize_sequence(student_seq)

    teacher_features = sequence_features(teacher_seq_norm)
    student_features = sequence_features(student_seq_norm)

    # Use DTW window from params (default=20)
    dtw_window = payload.dtw_params.window
    result = dtw_distance(teacher_features, student_features, window=dtw_window)

    return AlignResponse(
        distance=result.distance,
        normalized_distance=result.normalized_distance,
        path_length=len(result.path),
    )


def _progress_response(session_id: str, progress) -> WorkoutProgressResponse:
    return WorkoutProgressResponse(
        session_id=session_id,
        phase=progress.phase,
        exercise_name=progress.exercise_name,
        mode=progress.mode,
        step_index=progress.step_index,
        set_index=progress.set_index,
        rep_count=progress.rep_count,
        hold_seconds=progress.hold_seconds,
        target_reps=progress.target_reps,
        target_seconds=progress.target_seconds,
        tracking_started=progress.tracking_started,
        pending_confirmation=progress.pending_confirmation,
        done=progress.done,
        announcements=progress.announcements,
    )


def _speak_announcements_throttled(session_id: str, speaker: Speaker | None, announcements: list[str]) -> None:
    if speaker is None or not announcements:
        return

    now = time.time()
    state = WORKOUT_SPEECH_STATE.get(session_id, {"last_key": "", "last_at": 0.0})
    key = "|".join(msg.strip() for msg in announcements if msg and msg.strip())
    if not key:
        return

    should_speak = True
    if key == str(state.get("last_key", "")):
        elapsed = now - float(state.get("last_at", 0.0) or 0.0)
        if elapsed < SPEECH_COOLDOWN_SECONDS:
            should_speak = False

    if should_speak:
        speaker.speak_many(announcements)
        WORKOUT_SPEECH_STATE[session_id] = {"last_key": key, "last_at": now}


def _flush_event_buffer(session_id: str) -> None:
    buffer = WORKOUT_EVENT_BUFFER.get(session_id, [])
    if not buffer:
        return
    STORE.append_workout_events_batch(session_id, buffer)
    WORKOUT_EVENT_BUFFER[session_id] = []


def _should_persist_state(session_id: str, response: WorkoutProgressResponse) -> bool:
    last = WORKOUT_LAST_STATE_PERSIST.get(session_id)
    hold_bucket = int(response.hold_seconds)
    if last is None:
        WORKOUT_LAST_STATE_PERSIST[session_id] = {
            "phase": response.phase,
            "rep_count": response.rep_count,
            "hold_bucket": hold_bucket,
            "done": response.done,
        }
        return True

    changed = (
        response.phase != last.get("phase")
        or response.rep_count != int(last.get("rep_count", -1))
        or hold_bucket != int(last.get("hold_bucket", -1))
        or response.done != bool(last.get("done", False))
    )
    if changed:
        WORKOUT_LAST_STATE_PERSIST[session_id] = {
            "phase": response.phase,
            "rep_count": response.rep_count,
            "hold_bucket": hold_bucket,
            "done": response.done,
        }
    return changed


def _group_issue_scores(template_features: list[list[float]], student_features: list[list[float]], path: list[tuple[int, int]]) -> list[dict[str, float | str]]:
    if not path:
        return []

    issues: list[dict[str, float | str]] = []
    for label, dims in FEATURE_GROUPS.items():
        total = 0.0
        samples = 0
        for ti, si in path:
            template_vec = template_features[ti]
            student_vec = student_features[si]
            for dim in dims:
                if dim >= len(template_vec) or dim >= len(student_vec):
                    continue
                total += abs(template_vec[dim] - student_vec[dim])
                samples += 1
        if samples == 0:
            continue
        issues.append({"label": label, "score": round(total / samples, 4)})

    issues.sort(key=lambda item: float(item["score"]), reverse=True)
    return issues


def _issue_feedback(issues: list[dict[str, float | str]]) -> list[str]:
    feedback: list[str] = []
    for issue in issues[:3]:
        label = str(issue["label"])
        score = float(issue["score"])
        if score < 0.12:
            continue
        if "tay" in label:
            feedback.append(f"Cần chỉnh {label}: góc khuỷu/cơ tay đang lệch so với video mẫu.")
        else:
            feedback.append(f"Cần chỉnh {label}: biên độ hoặc hướng chuyển động đang lệch so với video mẫu.")
    if not feedback:
        feedback.append("Động tác gần với video mẫu, không thấy sai lệch lớn ở tay/chân.")
    return feedback


def _sample_point_3d(sample: list[list[float]], idx: int) -> list[float]:
    point = sample[idx]
    if len(point) >= 7:
        return [float(point[4]), float(point[5]), float(point[6])]
    return [float(point[0]), float(point[1]), float(point[2])]


def _angle_3d(sample: list[list[float]], a: int, b: int, c: int) -> float:
    pa = _sample_point_3d(sample, a)
    pb = _sample_point_3d(sample, b)
    pc = _sample_point_3d(sample, c)
    ba = [pa[0] - pb[0], pa[1] - pb[1], pa[2] - pb[2]]
    bc = [pc[0] - pb[0], pc[1] - pb[1], pc[2] - pb[2]]
    norm_ba = sum(x * x for x in ba) ** 0.5
    norm_bc = sum(x * x for x in bc) ** 0.5
    if norm_ba < 1e-6 or norm_bc < 1e-6:
        return 0.0
    cos_val = sum(ba[i] * bc[i] for i in range(3)) / (norm_ba * norm_bc)
    cos_val = max(-1.0, min(1.0, cos_val))
    return math.degrees(math.acos(cos_val))


def _direction_labels(dx: float, dy: float, dz: float) -> list[str]:
    directions: list[str] = []
    if dx <= -0.035:
        directions.append("lech trai")
    elif dx >= 0.035:
        directions.append("lech phai")
    if dy <= -0.035:
        directions.append("cao hon")
    elif dy >= 0.035:
        directions.append("thap hon")
    if dz <= -0.08:
        directions.append("gan camera hon")
    elif dz >= 0.08:
        directions.append("xa camera hon")
    return directions or ["gan dung vi tri mau"]


def _sample_path(path: list[tuple[int, int]], limit: int = 48) -> list[tuple[int, int]]:
    if len(path) <= limit:
        return path
    if limit <= 1:
        return [path[0]]
    result: list[tuple[int, int]] = []
    for idx in range(limit):
        pos = round(idx * (len(path) - 1) / (limit - 1))
        result.append(path[pos])
    return result


def _compress_dtw_path_for_display(path: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Remove long horizontal/vertical DTW runs that visually freeze one side."""
    if not path:
        return []

    compressed: list[tuple[int, int]] = [path[0]]
    prev_ti, prev_si = path[0]
    for ti, si in path[1:]:
        # If only one side advances, replace the last pair to keep progress moving
        # without replaying identical student/template frames for too long.
        if ti == prev_ti or si == prev_si:
            compressed[-1] = (ti, si)
        else:
            compressed.append((ti, si))
        prev_ti, prev_si = ti, si

    if len(compressed) < 2 and len(path) >= 2:
        return [path[0], path[-1]]
    return compressed


def _sample_motion_score(samples: list[list[list[float]]]) -> float:
    """Return average per-point 2D motion in normalized coordinates."""
    if len(samples) < 2:
        return 0.0

    total = 0.0
    count = 0
    for i in range(1, len(samples)):
        prev = samples[i - 1]
        curr = samples[i]
        n = min(len(prev), len(curr))
        for j in range(n):
            p0 = prev[j]
            p1 = curr[j]
            if len(p0) < 4 or len(p1) < 4:
                continue
            if float(p0[3]) < 0.2 or float(p1[3]) < 0.2:
                continue
            dx = float(p1[0]) - float(p0[0])
            dy = float(p1[1]) - float(p0[1])
            total += (dx * dx + dy * dy) ** 0.5
            count += 1
    if count <= 0:
        return 0.0
    return total / float(count)


def _joint_analysis(template_samples: list[list[list[float]]], student_samples: list[list[list[float]]], path: list[tuple[int, int]]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    if not path:
        return outputs

    for spec in JOINT_ANALYSIS_SPECS:
        a, b, c = spec["points"]
        angle_deltas: list[float] = []
        dx_values: list[float] = []
        dy_values: list[float] = []
        dz_values: list[float] = []
        for ti, si in path:
            template_sample = template_samples[ti]
            student_sample = student_samples[si]
            angle_deltas.append(_angle_3d(student_sample, a, b, c) - _angle_3d(template_sample, a, b, c))
            student_point = _sample_point_3d(student_sample, b)
            template_point = _sample_point_3d(template_sample, b)
            dx_values.append(student_point[0] - template_point[0])
            dy_values.append(student_point[1] - template_point[1])
            dz_values.append(student_point[2] - template_point[2])

        angle_delta = sum(angle_deltas) / max(len(angle_deltas), 1)
        dx = sum(dx_values) / max(len(dx_values), 1)
        dy = sum(dy_values) / max(len(dy_values), 1)
        dz = sum(dz_values) / max(len(dz_values), 1)
        outputs.append(
            {
                "joint": spec["name"],
                "label": spec["label"],
                "point_index": b,
                "angle_delta_deg": round(angle_delta, 2),
                "magnitude_deg": round(abs(angle_delta), 2),
                "direction": _direction_labels(dx, dy, dz),
                "position_delta": {
                    "x": round(dx, 4),
                    "y": round(dy, 4),
                    "z": round(dz, 4),
                },
            }
        )

    outputs.sort(key=lambda item: float(item["magnitude_deg"]), reverse=True)
    return outputs


def _sample_bbox(sample: list[list[float]]) -> dict[str, float]:
    visible = [point for point in sample if len(point) >= 4 and point[3] >= 0.25]
    if not visible:
        return {"min_x": 0.0, "min_y": 0.0, "max_x": 1.0, "max_y": 1.0, "center_x": 0.5, "center_y": 0.5}

    min_x = min(point[0] for point in visible)
    min_y = min(point[1] for point in visible)
    max_x = max(point[0] for point in visible)
    max_y = max(point[1] for point in visible)
    pad_x = max(0.06, (max_x - min_x) * 0.18)
    pad_y = max(0.06, (max_y - min_y) * 0.14)
    min_x = max(0.0, min_x - pad_x)
    min_y = max(0.0, min_y - pad_y)
    max_x = min(1.0, max_x + pad_x)
    max_y = min(1.0, max_y + pad_y)
    return {
        "min_x": round(min_x, 4),
        "min_y": round(min_y, 4),
        "max_x": round(max_x, 4),
        "max_y": round(max_y, 4),
        "center_x": round((min_x + max_x) / 2, 4),
        "center_y": round((min_y + max_y) / 2, 4),
    }


def _signal_and_similarity(feature: list[float], profile: dict[str, Any]) -> tuple[float, float]:
    """Compute phase signal (for rep counting) and similarity (for feedback).
    
    IMPORTANT: The returned signal is phase-only (no similarity mixing).
    This ensures the signal has full [0,1] swing for reliable rep counting.
    Similarity is returned separately for readiness/feedback use.
    """
    mean = [float(x) for x in profile.get("feature_mean", [])]
    pc1 = [float(x) for x in profile.get("feature_pc1", [])]
    ref_features = profile.get("features", [])
    if not mean or not pc1 or not ref_features:
        return 0.0, 0.0

    centered = [feature[i] - (mean[i] if i < len(mean) else 0.0) for i in range(len(feature))]
    proj = sum(centered[i] * (pc1[i] if i < len(pc1) else 0.0) for i in range(len(centered)))
    min_p = float(profile.get("proj_min", 0.0))
    max_p = float(profile.get("proj_max", 1.0))
    denom = max(1e-6, max_p - min_p)
    phase_signal = max(0.0, min(1.0, (proj - min_p) / denom))

    # Similarity for feedback only (not mixed into rep counting signal)
    min_dist = float("inf")
    for ref in ref_features:
        total = 0.0
        for idx, value in enumerate(feature):
            other = float(ref[idx]) if idx < len(ref) else 0.0
            total += (value - other) ** 2
        min_dist = min(min_dist, math.sqrt(total))

    dist_scale = _clamp(float(profile.get("similarity_distance_scale", 2.8)), 0.5, 8.0)
    similarity = math.exp(-min_dist / dist_scale) if min_dist != float("inf") else 0.0

    # Return phase-only signal for rep counting
    return phase_signal, similarity


def _rep_indices_for_student(student_features: list[list[float]], profile: dict[str, Any], mode: str) -> list[int | None]:
    if mode != "reps":
        return [None for _ in student_features]

    rep_counter = RepCounter(config=_profile_rep_counter_config(profile))
    normalizer = SignalNormalizer()
    current_rep = 1
    indices: list[int | None] = []
    for i, feature in enumerate(student_features):
        signal_raw, _ = _signal_and_similarity(feature, profile)
        signal = normalizer.normalize(signal_raw)
        before = rep_counter.rep_count
        rep_counter.update(signal, timestamp_ms=i * 100)
        after = rep_counter.rep_count
        indices.append(current_rep)
        if after > before:
            current_rep = after + 1
    return indices


def _estimate_student_reps(student_features: list[list[float]], profile: dict[str, Any], mode: str) -> int:
    if mode != "reps":
        return 1
    rep_counter = RepCounter(config=_profile_rep_counter_config(profile))
    normalizer = SignalNormalizer()
    for i, feature in enumerate(student_features):
        signal_raw, _ = _signal_and_similarity(feature, profile)
        signal = normalizer.normalize(signal_raw)
        rep_counter.update(signal, timestamp_ms=i * 100)
    estimated = max(1, int(rep_counter.rep_count))

    # Fallback: derive rep count from valleys when counter is too conservative.
    if estimated <= 1 and student_features:
        signals: list[float] = []
        normalizer2 = SignalNormalizer()
        for feature in student_features:
            raw, _ = _signal_and_similarity(feature, profile)
            signals.append(normalizer2.normalize(raw))
        valleys = segment_by_signal_valleys(signals, min_rep_frames=6)
        if valleys:
            estimated = max(estimated, len(valleys))
    return estimated


def _repeat_template_cycles(
    template_features: list[list[float]],
    template_samples: list[list[list[float]]],
    cycles: int,
) -> tuple[list[list[float]], list[list[list[float]]]]:
    if cycles <= 1:
        return template_features, template_samples

    repeated_features: list[list[float]] = []
    repeated_samples: list[list[list[float]]] = []
    for _ in range(cycles):
        repeated_features.extend(template_features)
        repeated_samples.extend(template_samples)
    return repeated_features, repeated_samples


def _effective_rep_target(observed_rep_count: int, estimated_rep_count: int) -> int:
    observed = int(observed_rep_count or 0)
    estimated = int(estimated_rep_count or 0)
    # Prefer live observed reps from workout session; estimator is only a fallback.
    if observed > 0:
        return observed
    if estimated > 0:
        return estimated
    return 1


def _slice_template_to_rep_target(
    template_features: list[list[float]],
    template_samples: list[list[list[float]]],
    profile: dict[str, Any],
    mode: str,
    target_reps: int,
) -> tuple[list[list[float]], list[list[list[float]]]]:
    if mode != "reps" or target_reps <= 0:
        return template_features, template_samples
    if len(template_features) != len(template_samples) or not template_features:
        return template_features, template_samples

    rep_indices = _rep_indices_for_student(template_features, profile, mode)
    if not rep_indices:
        return template_features, template_samples

    known_reps = [int(v) for v in rep_indices if v is not None]
    if not known_reps:
        return template_features, template_samples

    template_rep_count = max(known_reps)
    if target_reps >= template_rep_count:
        return template_features, template_samples

    keep_upto = max(1, int(target_reps))
    kept_features: list[list[float]] = []
    kept_samples: list[list[list[float]]] = []
    for i, rep_idx in enumerate(rep_indices):
        current_rep = int(rep_idx) if rep_idx is not None else 1
        if current_rep <= keep_upto:
            kept_features.append(template_features[i])
            kept_samples.append(template_samples[i])

    # Guard against pathological split when rep detection is noisy.
    min_keep = max(8, int(len(template_features) * 0.25))
    if len(kept_features) < min_keep:
        return template_features, template_samples
    return kept_features, kept_samples


def _frame_joint_errors(template_sample: list[list[float]], student_sample: list[list[float]]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for spec in JOINT_ANALYSIS_SPECS:
        a, b, c = spec["points"]
        angle_delta = _angle_3d(student_sample, a, b, c) - _angle_3d(template_sample, a, b, c)
        student_point = _sample_point_3d(student_sample, b)
        template_point = _sample_point_3d(template_sample, b)
        dx = student_point[0] - template_point[0]
        dy = student_point[1] - template_point[1]
        dz = student_point[2] - template_point[2]
        outputs.append(
            {
                "joint": spec["name"],
                "label": spec["label"],
                "point_index": b,
                "angle_delta_deg": round(angle_delta, 2),
                "magnitude_deg": round(abs(angle_delta), 2),
                "direction": _direction_labels(dx, dy, dz),
                "highlight": abs(angle_delta) >= 12.0,
            }
        )

    outputs.sort(key=lambda item: float(item["magnitude_deg"]), reverse=True)
    return outputs


def _rep_feedback_entries(exercise_name: str, set_index: int, mode: str, frame_analyses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if mode != "reps":
        worst = sorted(
            (
                joint
                for frame in frame_analyses
                for joint in frame["joint_errors"]
                if float(joint["magnitude_deg"]) >= 12.0
            ),
            key=lambda item: float(item["magnitude_deg"]),
            reverse=True,
        )[:6]
        return [
            {
                "exercise_name": exercise_name,
                "set_index": set_index,
                "rep_index": None,
                "details": worst,
                "text": [
                    f"Bai tap {exercise_name} set thu {set_index + 1}: {item['label']} lech {item['angle_delta_deg']} do, {', '.join(item['direction'])}."
                    for item in worst
                ],
            }
        ]

    per_rep: dict[int, dict[str, dict[str, Any]]] = {}
    for frame in frame_analyses:
        rep_index = frame.get("rep_index")
        if rep_index is None:
            continue
        bucket = per_rep.setdefault(int(rep_index), {})
        for joint in frame["joint_errors"]:
            existing = bucket.get(str(joint["joint"]))
            if existing is None or float(joint["magnitude_deg"]) > float(existing["magnitude_deg"]):
                bucket[str(joint["joint"])] = joint

    entries: list[dict[str, Any]] = []
    for rep_index in sorted(per_rep):
        top = sorted(per_rep[rep_index].values(), key=lambda item: float(item["magnitude_deg"]), reverse=True)[:6]
        text = [
            f"Bai tap {exercise_name} set thu {set_index + 1} rep thu {rep_index}: {item['label']} lech {item['angle_delta_deg']} do, {', '.join(item['direction'])}."
            for item in top
            if float(item["magnitude_deg"]) >= 12.0
        ]
        if not text:
            text = [f"Bai tap {exercise_name} set thu {set_index + 1} rep thu {rep_index}: khong co sai lech lon."]
        entries.append(
            {
                "exercise_name": exercise_name,
                "set_index": set_index,
                "rep_index": rep_index,
                "details": top,
                "text": text,
            }
        )
    return entries


def _validate_trim_window(trim_start_sec: float | None, trim_end_sec: float | None) -> tuple[float, float | None]:
    start_sec = float(trim_start_sec) if trim_start_sec is not None else 0.0
    end_sec = float(trim_end_sec) if trim_end_sec is not None else None
    if start_sec < 0.0:
        raise HTTPException(status_code=400, detail="trim_start_sec must be >= 0")
    if end_sec is not None and end_sec <= start_sec:
        raise HTTPException(status_code=400, detail="trim_end_sec must be greater than trim_start_sec")
    return start_sec, end_sec


def _open_mp4_writer(path: Path, fps: float, width: int, height: int) -> cv2.VideoWriter:
    for fourcc in ("avc1", "H264", "mp4v"):
        writer = cv2.VideoWriter(
            str(path),
            cv2.VideoWriter_fourcc(*fourcc),
            fps,
            (int(width), int(height)),
        )
        if writer.isOpened():
            return writer
        writer.release()
    raise RuntimeError("cannot initialize mp4 writer")


def _freeze_template_video(
    *,
    source_video_uri: str,
    template_id: str,
    trim_start_sec: float | None,
    trim_end_sec: float | None,
) -> tuple[str, dict[str, Any]]:
    source_path = _resolve_video_path(source_video_uri)
    start_sec, end_sec = _validate_trim_window(trim_start_sec, trim_end_sec)

    out_name = f"template_{template_id}_{uuid.uuid4().hex[:8]}.mp4"
    out_path = TEMPLATE_FROZEN_DIR / out_name

    cap = cv2.VideoCapture(str(source_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open template source video: {source_video_uri}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 1e-6:
        fps = 30.0

    writer: cv2.VideoWriter | None = None
    written = 0
    last_ts_sec = start_sec
    try:
        while cap.isOpened():
            ok, frame = cap.read()
            if not ok:
                break

            ts_sec = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if start_sec > 0.0 and ts_sec + 1e-6 < start_sec:
                continue
            if end_sec is not None and ts_sec - 1e-6 > end_sec:
                break

            if writer is None:
                h, w = frame.shape[:2]
                writer = _open_mp4_writer(out_path, fps=fps, width=w, height=h)
            writer.write(frame)
            written += 1
            last_ts_sec = ts_sec
    finally:
        cap.release()
        if writer is not None:
            writer.release()

    if written <= 0:
        out_path.unlink(missing_ok=True)
        raise RuntimeError("trim window does not contain valid frames")

    frozen_uri = f"/uploads/template_frozen/{out_name}"
    frozen_meta = {
        "source_video_uri": source_video_uri,
        "source_video_name": source_path.name,
        "trim_start_sec": trim_start_sec,
        "trim_end_sec": trim_end_sec,
        "frozen_video_uri": frozen_uri,
        "frozen_frame_count": written,
        "frozen_last_timestamp_sec": round(float(last_ts_sec), 4),
        "created_at_ms": int(time.time() * 1000),
    }
    return frozen_uri, frozen_meta


def _resolve_heavy_pose_task_model_path() -> Path:
    model_candidates = [
        DATA_DIR / "models" / "pose_landmarker_heavy.task",
        Path("app/data/models/pose_landmarker_heavy.task"),
    ]
    model_path = next((p.resolve() for p in model_candidates if p.exists()), None)
    if model_path is None:
        raise RuntimeError("Khong tim thay pose_landmarker_heavy.task")
    return model_path


def _first_landmark_set(container: Any) -> list[Any]:
    if container is None:
        return []

    if hasattr(container, "landmark"):
        try:
            return list(getattr(container, "landmark"))
        except Exception:
            return []

    if isinstance(container, list):
        if not container:
            return []
        first = container[0]
        if hasattr(first, "landmark"):
            try:
                return list(getattr(first, "landmark"))
            except Exception:
                return []
        if isinstance(first, list):
            return first
    return []


def _serialize_landmarks_for_timeline(landmarks: list[Any]) -> list[list[float]]:
    payload: list[list[float]] = []
    for lm in landmarks:
        payload.append(
            [
                round(float(getattr(lm, "x", 0.0)), 6),
                round(float(getattr(lm, "y", 0.0)), 6),
                round(float(getattr(lm, "z", 0.0)), 6),
                round(float(getattr(lm, "visibility", getattr(lm, "presence", 0.0))), 6),
            ]
        )
    return payload


def _draw_base_pose_overlay(frame: np.ndarray, landmarks: list[Any]) -> None:
    if not landmarks:
        return
    h, w = frame.shape[:2]
    if h <= 0 or w <= 0:
        return

    points: list[tuple[int, int] | None] = []
    for lm in landmarks:
        x = float(getattr(lm, "x", 0.0))
        y = float(getattr(lm, "y", 0.0))
        if x < 0.0 or x > 1.0 or y < 0.0 or y > 1.0:
            points.append(None)
            continue
        px = int(round(x * (w - 1)))
        py = int(round(y * (h - 1)))
        in_bounds = 0 <= px < w and 0 <= py < h
        points.append((px, py) if in_bounds else None)

    for a, b in DEBUG_BASE_POSE_CONNECTIONS:
        if a >= len(points) or b >= len(points):
            continue
        pa = points[a]
        pb = points[b]
        if pa is None or pb is None:
            continue
        cv2.line(frame, pa, pb, DEBUG_BASE_LINE_BGR, DEBUG_BASE_LINE_THICKNESS, cv2.LINE_AA)

    for pt in points:
        if pt is None:
            continue
        cv2.circle(frame, pt, DEBUG_BASE_POINT_RADIUS, DEBUG_BASE_POINT_BGR, -1, cv2.LINE_AA)


def _export_template_pose_artifacts(
    *,
    template_id: str,
    source_video_uri: str,
    frozen_video_uri: str,
) -> dict[str, Any]:
    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision
    except Exception as exc:
        raise RuntimeError("MediaPipe Tasks is required to export template pose artifacts") from exc

    # Post-processing/offline export flow: keep HEAVY model for maximum analysis quality.
    model_path = _resolve_heavy_pose_task_model_path()

    video_path = _resolve_video_path(frozen_video_uri)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open frozen template video: {frozen_video_uri}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 1e-6:
        fps = 30.0

    debug_name = f"template_{template_id}_{uuid.uuid4().hex[:8]}_debug.mp4"
    debug_path = TEMPLATE_DEBUG_DIR / debug_name
    timeline_name = f"template_{template_id}_{uuid.uuid4().hex[:8]}_pose.json"
    timeline_path = TEMPLATE_POSE_TIMELINE_DIR / timeline_name

    options = vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    timeline_frames: list[dict[str, Any]] = []
    writer: cv2.VideoWriter | None = None
    width = 0
    height = 0
    frame_index = 0

    try:
        with vision.PoseLandmarker.create_from_options(options) as landmarker:
            while cap.isOpened():
                ok, frame = cap.read()
                if not ok:
                    break

                if writer is None:
                    height, width = frame.shape[:2]
                    writer = _open_mp4_writer(debug_path, fps=fps, width=width, height=height)

                timestamp_sec = frame_index / fps
                timestamp_ms = int(round(timestamp_sec * 1000.0))

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                result = landmarker.detect_for_video(mp_image, timestamp_ms)

                pose_landmarks = _first_landmark_set(getattr(result, "pose_landmarks", None))
                world_landmarks = _first_landmark_set(getattr(result, "pose_world_landmarks", None))

                overlay = frame.copy()
                _draw_base_pose_overlay(overlay, pose_landmarks)
                writer.write(overlay)

                frame_payload: dict[str, Any] = {
                    "frame_index": frame_index,
                    "timestamp_ms": timestamp_ms,
                    "timestamp_sec": round(float(timestamp_sec), 6),
                    "pose_landmarks": _serialize_landmarks_for_timeline(pose_landmarks),
                }
                if world_landmarks:
                    frame_payload["pose_world_landmarks"] = _serialize_landmarks_for_timeline(world_landmarks)
                timeline_frames.append(frame_payload)
                frame_index += 1
    finally:
        cap.release()
        if writer is not None:
            writer.release()

    if frame_index <= 0:
        debug_path.unlink(missing_ok=True)
        timeline_path.unlink(missing_ok=True)
        raise RuntimeError("cannot export pose artifacts: frozen video has no readable frames")

    timeline_payload = {
        "schema_version": POSE_TIMELINE_SCHEMA_VERSION,
        "template_id": template_id,
        "source_video_uri": source_video_uri,
        "frozen_video_uri": frozen_video_uri,
        "fps": round(float(fps), 4),
        "width": int(width),
        "height": int(height),
        "frame_count": int(frame_index),
        "frames": timeline_frames,
    }
    try:
        _write_json_atomic(timeline_path, timeline_payload)
    except Exception:
        debug_path.unlink(missing_ok=True)
        timeline_path.unlink(missing_ok=True)
        raise

    return {
        "debug_overlay_video_uri": f"/uploads/template_debug/{debug_name}",
        "pose_timeline_json_uri": f"/uploads/template_pose_timeline/{timeline_name}",
        "pose_timeline_frame_count": int(frame_index),
        "pose_timeline_schema_version": POSE_TIMELINE_SCHEMA_VERSION,
    }


def _build_profile_dict_from_video(
    *,
    mode: str,
    video_uri: str,
    trim_start_sec: float | None,
    trim_end_sec: float | None,
    frozen_meta: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    video_path = _resolve_video_path(video_uri)
    pose_samples = extract_video_pose_samples(
        str(video_path),
        trim_start_sec=trim_start_sec,
        trim_end_sec=trim_end_sec,
    )
    features = features_from_samples(pose_samples)
    profile = build_template_profile_from_features(features)

    profile_seed = {
        "feature_version": profile.feature_version,
        "feature_mean": profile.feature_mean,
        "feature_pc1": profile.feature_pc1,
        "proj_min": profile.proj_min,
        "proj_max": profile.proj_max,
        "features": profile.features,
        "pose_samples": pose_samples,
        "samples": profile.samples,
    }

    rep_cycle_info = detect_rep_cycles(
        features=profile.features,
        samples=pose_samples,
        mode=mode,
    )

    anchor_bank = _build_anchor_pose_bank(pose_samples)
    adaptive_thresholds = _build_adaptive_thresholds(profile_seed, mode)
    signal_cfg = adaptive_thresholds.get("signal", {}) if isinstance(adaptive_thresholds, dict) else {}

    profile_dict = {
        **profile_seed,
        "anchor_pose_sample": (anchor_bank[0] if anchor_bank else (pose_samples[0] if pose_samples else None)),
        "anchor_pose_samples": anchor_bank,
        "adaptive_thresholds": adaptive_thresholds,
        "signal_phase_weight": float(signal_cfg.get("phase_weight", 0.65)),
        "signal_similarity_weight": float(signal_cfg.get("similarity_weight", 0.35)),
        "similarity_distance_scale": float(signal_cfg.get("distance_scale", 2.8)),
        "single_rep_features": rep_cycle_info.single_cycle_features,
        "single_rep_samples": rep_cycle_info.single_cycle_samples,
        "start_pose_sample": pose_samples[rep_cycle_info.start_pose_idx] if pose_samples else None,
        "rep_count_in_template": rep_cycle_info.rep_count_in_template,
        "rep_cycles": [(s, e) for s, e in rep_cycle_info.cycles],
    }
    if isinstance(frozen_meta, dict) and frozen_meta:
        profile_dict["frozen_artifact"] = frozen_meta
    return profile_dict, int(profile.samples)


def _build_frozen_template_assets(
    *,
    template_id: str,
    mode: str,
    source_video_uri: str,
    trim_start_sec: float | None,
    trim_end_sec: float | None,
) -> tuple[str, dict[str, Any], int]:
    frozen_video_uri, frozen_meta = _freeze_template_video(
        source_video_uri=source_video_uri,
        template_id=template_id,
        trim_start_sec=trim_start_sec,
        trim_end_sec=trim_end_sec,
    )
    try:
        pose_artifacts = _export_template_pose_artifacts(
            template_id=template_id,
            source_video_uri=source_video_uri,
            frozen_video_uri=frozen_video_uri,
        )
        frozen_meta.update(pose_artifacts)
        profile_dict, samples = _build_profile_dict_from_video(
            mode=mode,
            video_uri=frozen_video_uri,
            trim_start_sec=None,
            trim_end_sec=None,
            frozen_meta=frozen_meta,
        )
    except Exception:
        _remove_any_uploaded_video_if_safe(str(frozen_meta.get("debug_overlay_video_uri", "")))
        _remove_any_uploaded_video_if_safe(str(frozen_meta.get("pose_timeline_json_uri", "")))
        _remove_frozen_template_video_if_safe(frozen_video_uri)
        raise
    return frozen_video_uri, profile_dict, samples


def _collect_template_related_video_uris(template: WorkoutTemplate | None, profile: dict[str, Any] | None) -> list[str]:
    ordered: list[str] = []

    def add(uri: Any) -> None:
        if not isinstance(uri, str):
            return
        value = uri.strip()
        if not value or value in ordered:
            return
        ordered.append(value)

    if template is not None:
        add(getattr(template, "video_uri", None))
    if isinstance(profile, dict):
        frozen = profile.get("frozen_artifact")
        if isinstance(frozen, dict):
            add(frozen.get("frozen_video_uri"))
            add(frozen.get("source_video_uri"))
            add(frozen.get("debug_overlay_video_uri"))
            add(frozen.get("pose_timeline_json_uri"))
    return ordered


def _is_video_uri_referenced_by_other_templates(video_uri: str, exclude_template_id: str | None = None) -> bool:
    if not isinstance(video_uri, str) or not video_uri.startswith("/uploads/"):
        return False
    for tid, tpl in TEMPLATE_LIBRARY.items():
        if exclude_template_id is not None and tid == exclude_template_id:
            continue
        if str(getattr(tpl, "video_uri", "")) == video_uri:
            return True
        profile = TEMPLATE_PROFILES.get(tid)
        if isinstance(profile, dict):
            frozen = profile.get("frozen_artifact")
            if isinstance(frozen, dict):
                if str(frozen.get("frozen_video_uri", "")) == video_uri:
                    return True
                if str(frozen.get("source_video_uri", "")) == video_uri:
                    return True
                if str(frozen.get("debug_overlay_video_uri", "")) == video_uri:
                    return True
                if str(frozen.get("pose_timeline_json_uri", "")) == video_uri:
                    return True
    return False


def _remove_any_uploaded_video_if_safe(video_uri: str) -> bool:
    if not isinstance(video_uri, str) or not video_uri.startswith("/uploads/"):
        return False
    rel = video_uri[len("/uploads/") :]
    path = (UPLOAD_DIR / rel).resolve()
    try:
        if not str(path).startswith(str(UPLOAD_DIR.resolve())):
            return False
        if not path.exists():
            return False
        path.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _cleanup_template_media_uris(
    *,
    candidate_video_uris: list[str],
    exclude_template_id: str | None,
    keep_video_uris: list[str] | None = None,
) -> dict[str, Any]:
    keep = {str(uri).strip() for uri in (keep_video_uris or []) if isinstance(uri, str) and str(uri).strip()}
    outcomes: list[dict[str, str]] = []
    purged: list[str] = []
    seen: set[str] = set()
    for raw in candidate_video_uris:
        uri = str(raw).strip() if isinstance(raw, str) else ""
        if not uri or uri in seen:
            continue
        seen.add(uri)

        if uri in keep:
            outcomes.append({"video_uri": uri, "status": "kept_current"})
            continue

        if _is_video_uri_referenced_by_other_templates(uri, exclude_template_id=exclude_template_id):
            outcomes.append({"video_uri": uri, "status": "kept_referenced"})
            continue

        deleted = _remove_any_uploaded_video_if_safe(uri)
        outcomes.append({"video_uri": uri, "status": "deleted" if deleted else "missing_or_failed"})
        purged.append(uri)

    index_removed = _purge_upload_index_by_video_uris(purged)
    return {"items": outcomes, "index_entries_removed": index_removed}


def _template_artifact_uris(template_id: str) -> tuple[str | None, str | None]:
    profile = TEMPLATE_PROFILES.get(template_id)
    if not isinstance(profile, dict):
        profile = STORE.get_template_profile(template_id)
        if isinstance(profile, dict):
            TEMPLATE_PROFILES[template_id] = profile

    if not isinstance(profile, dict):
        return None, None

    frozen = profile.get("frozen_artifact")
    if not isinstance(frozen, dict):
        return None, None

    debug_video_uri = str(frozen.get("debug_overlay_video_uri", "")).strip() or None
    pose_timeline_json_uri = str(frozen.get("pose_timeline_json_uri", "")).strip() or None
    return debug_video_uri, pose_timeline_json_uri


@app.post("/v1/library/templates", response_model=TemplateItem, response_model_exclude_none=True)
def create_template(payload: TemplateCreateRequest) -> TemplateItem:
    template_id = str(uuid.uuid4())
    try:
        frozen_video_uri, profile_dict, _ = _build_frozen_template_assets(
            template_id=template_id,
            mode=payload.mode,
            source_video_uri=payload.video_uri,
            trim_start_sec=payload.trim_start_sec,
            trim_end_sec=payload.trim_end_sec,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"cannot prepare template artifact: {exc}") from exc

    t = WorkoutTemplate(
        template_id=template_id,
        name=payload.name,
        mode=payload.mode,
        video_uri=frozen_video_uri,
        notes=payload.notes,
        trim_start_sec=None,
        trim_end_sec=None,
    )
    TEMPLATE_LIBRARY[template_id] = t
    TEMPLATE_PROFILES[template_id] = profile_dict
    _persist_templates()
    _persist_template_profiles()
    _persist_template_to_store(t)
    _persist_template_profile_to_store(template_id, profile_dict)
    debug_video_uri, pose_timeline_json_uri = _template_artifact_uris(template_id)
    return TemplateItem(
        template_id=t.template_id,
        name=t.name,
        mode=t.mode,
        video_uri=t.video_uri,
        notes=t.notes,
        trim_start_sec=t.trim_start_sec,
        trim_end_sec=t.trim_end_sec,
        debug_overlay_video_uri=debug_video_uri,
        pose_timeline_json_uri=pose_timeline_json_uri,
    )


@app.put("/v1/library/templates/{template_id}", response_model=TemplateItem, response_model_exclude_none=True)
def update_template(template_id: str, payload: TemplateUpdateRequest) -> TemplateItem:
    template = TEMPLATE_LIBRARY.get(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="template not found")

    existing_profile = TEMPLATE_PROFILES.get(template_id) or STORE.get_template_profile(template_id) or {}
    old_related_uris = _collect_template_related_video_uris(template, existing_profile if isinstance(existing_profile, dict) else None)
    frozen_info = existing_profile.get("frozen_artifact") if isinstance(existing_profile, dict) else {}

    requested_mode = payload.mode if payload.mode is not None else template.mode
    requested_source_video_uri = (
        payload.video_uri
        if payload.video_uri is not None
        else str(frozen_info.get("source_video_uri") or template.video_uri)
    )
    requested_trim_start = (
        payload.trim_start_sec
        if payload.trim_start_sec is not None
        else frozen_info.get("trim_start_sec")
    )
    requested_trim_end = (
        payload.trim_end_sec
        if payload.trim_end_sec is not None
        else frozen_info.get("trim_end_sec")
    )

    should_rebuild_frozen = (
        payload.video_uri is not None
        or payload.trim_start_sec is not None
        or payload.trim_end_sec is not None
    )

    profile_dict: dict[str, Any] | None = None
    if should_rebuild_frozen:
        try:
            requested_video_uri, profile_dict, _ = _build_frozen_template_assets(
                template_id=template_id,
                mode=requested_mode,
                source_video_uri=requested_source_video_uri,
                trim_start_sec=requested_trim_start,
                trim_end_sec=requested_trim_end,
            )
            requested_trim_start = None
            requested_trim_end = None
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"cannot rebuild template artifact: {exc}") from exc
    else:
        requested_video_uri = template.video_uri
        requested_trim_start = getattr(template, "trim_start_sec", None)
        requested_trim_end = getattr(template, "trim_end_sec", None)

    should_rebuild_profile = should_rebuild_frozen or (payload.mode is not None)
    if should_rebuild_profile and profile_dict is None:
        try:
            profile_dict, _ = _build_profile_dict_from_video(
                mode=requested_mode,
                video_uri=requested_video_uri,
                trim_start_sec=requested_trim_start,
                trim_end_sec=requested_trim_end,
                frozen_meta=(frozen_info if isinstance(frozen_info, dict) else None),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"cannot rebuild profile: {exc}") from exc

    updated = WorkoutTemplate(
        template_id=template.template_id,
        name=payload.name if payload.name is not None else template.name,
        mode=requested_mode,
        video_uri=requested_video_uri,
        notes=payload.notes if payload.notes is not None else template.notes,
        trim_start_sec=requested_trim_start,
        trim_end_sec=requested_trim_end,
    )
    TEMPLATE_LIBRARY[template_id] = updated
    _persist_templates()
    _persist_template_to_store(updated)

    if profile_dict is not None:
        TEMPLATE_PROFILES[template_id] = profile_dict
        _persist_template_profiles()
        _persist_template_profile_to_store(template_id, profile_dict)
    else:
        _persist_template_profiles()

    keep_profile = profile_dict if isinstance(profile_dict, dict) else (existing_profile if isinstance(existing_profile, dict) else None)
    keep_related_uris = _collect_template_related_video_uris(updated, keep_profile)
    _cleanup_template_media_uris(
        candidate_video_uris=old_related_uris,
        exclude_template_id=template_id,
        keep_video_uris=keep_related_uris,
    )

    debug_video_uri, pose_timeline_json_uri = _template_artifact_uris(template_id)

    return TemplateItem(
        template_id=updated.template_id,
        name=updated.name,
        mode=updated.mode,
        video_uri=updated.video_uri,
        notes=updated.notes,
        trim_start_sec=getattr(updated, "trim_start_sec", None),
        trim_end_sec=getattr(updated, "trim_end_sec", None),
        debug_overlay_video_uri=debug_video_uri,
        pose_timeline_json_uri=pose_timeline_json_uri,
    )


@app.delete("/v1/library/templates/{template_id}", response_model=DeleteResponse)
def delete_template(template_id: str, force: bool = Query(default=True)) -> DeleteResponse:
    template = TEMPLATE_LIBRARY.get(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="template not found")

    blocking_session_ids: list[str] = []
    for sid, session in WORKOUT_SESSIONS.items():
        for step in session.plan.steps:
            if step.template_id == template_id and session.phase != "done":
                blocking_session_ids.append(sid)
                break

    if blocking_session_ids and not force:
        raise HTTPException(status_code=409, detail="template is being used by an active workout session")

    for sid in blocking_session_ids:
        _flush_event_buffer(sid)
        WORKOUT_SESSIONS.pop(sid, None)
        WORKOUT_SPEAKERS.pop(sid, None)
        WORKOUT_EVENT_LOGS.pop(sid, None)
        WORKOUT_SEGMENTS.pop(sid, None)
        WORKOUT_EVENT_BUFFER.pop(sid, None)
        WORKOUT_LAST_STATE_PERSIST.pop(sid, None)
        WORKOUT_SPEECH_STATE.pop(sid, None)
        try:
            STORE.update_workout_session_state(sid, latest_phase="done", done=True, status="cancelled")
        except Exception:
            pass

    existing_profile = TEMPLATE_PROFILES.get(template_id) or STORE.get_template_profile(template_id) or {}
    related_uris = _collect_template_related_video_uris(template, existing_profile if isinstance(existing_profile, dict) else None)

    TEMPLATE_LIBRARY.pop(template_id, None)
    TEMPLATE_PROFILES.pop(template_id, None)
    _persist_templates()
    _persist_template_profiles()
    STORE.delete_template(template_id)
    STORE.delete_template_profile(template_id)

    cleanup = _cleanup_template_media_uris(
        candidate_video_uris=related_uris,
        exclude_template_id=template_id,
        keep_video_uris=None,
    )

    cancelled = len(blocking_session_ids)
    removed_files = sum(1 for item in cleanup.get("items", []) if item.get("status") == "deleted")
    msg = f"Template da duoc xoa. Da don {removed_files} file lien quan"
    if cancelled > 0:
        msg += f"; da dong {cancelled} session dang dung template"

    return DeleteResponse(ok=True, message=msg)


@app.post("/v1/library/upload-video", response_model=VideoUploadResponse)
async def upload_video(video: UploadFile = File(...)) -> VideoUploadResponse:
    original_name = video.filename or "video.mp4"
    extension = Path(original_name).suffix or ".mp4"
    content = await video.read()
    sha = hashlib.sha256(content).hexdigest()
    upload_index = _load_upload_index()
    existing = upload_index.get("sha256", {}).get(sha)
    if isinstance(existing, dict):
        existing_uri = str(existing.get("video_uri", ""))
        if existing_uri:
            try:
                _resolve_video_path(existing_uri)
                return VideoUploadResponse(
                    video_uri=existing_uri,
                    original_name=str(existing.get("original_name") or original_name),
                )
            except Exception:
                pass

    stored_name = f"{uuid.uuid4()}{extension}"
    target = UPLOAD_DIR / stored_name
    target.write_bytes(content)

    video_uri = f"/uploads/{stored_name}"
    upload_index.setdefault("sha256", {})[sha] = {
        "video_uri": video_uri,
        "original_name": original_name,
        "size": len(content),
    }
    _save_upload_index(upload_index)

    return VideoUploadResponse(
        video_uri=video_uri,
        original_name=original_name,
    )


@app.get("/v1/library/templates", response_model=TemplateListResponse, response_model_exclude_none=True)
def list_templates() -> TemplateListResponse:
    if not TEMPLATE_LIBRARY:
        _load_templates_from_store()
    items = []
    for t in TEMPLATE_LIBRARY.values():
        debug_video_uri, pose_timeline_json_uri = _template_artifact_uris(t.template_id)
        items.append(
            TemplateItem(
                template_id=t.template_id,
                name=t.name,
                mode=t.mode,
                video_uri=t.video_uri,
                notes=t.notes,
                trim_start_sec=getattr(t, "trim_start_sec", None),
                trim_end_sec=getattr(t, "trim_end_sec", None),
                debug_overlay_video_uri=debug_video_uri,
                pose_timeline_json_uri=pose_timeline_json_uri,
            )
        )
    return TemplateListResponse(items=items)


def _resolve_video_path(video_uri: str) -> Path:
    if video_uri.startswith("/uploads/"):
        rel = video_uri[len("/uploads/") :]
        path = (UPLOAD_DIR / rel).resolve()
        if path.exists() and str(path).startswith(str(UPLOAD_DIR.resolve())):
            return path
    raise HTTPException(status_code=400, detail="video_uri must point to uploaded file under /uploads")


def _remove_uploaded_video_if_safe(video_uri: str) -> bool:
    if not isinstance(video_uri, str) or not video_uri.startswith("/uploads/"):
        return False
    rel = video_uri[len("/uploads/") :]
    path = (UPLOAD_DIR / rel).resolve()
    try:
        if not path.exists():
            return False
        analysis_root = ANALYSIS_DIR.resolve()
        if not str(path).startswith(str(analysis_root)):
            return False
        path.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _remove_frozen_template_video_if_safe(video_uri: str) -> bool:
    if not isinstance(video_uri, str) or not video_uri.startswith("/uploads/template_frozen/"):
        return False
    return _remove_any_uploaded_video_if_safe(video_uri)


def _read_video_frames(video_path: Path) -> tuple[list[np.ndarray], float]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frames: list[np.ndarray] = []
    try:
        while cap.isOpened():
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(frame)
    finally:
        cap.release()

    if not frames:
        raise RuntimeError(f"no frame data in video: {video_path}")
    return frames, fps


class _VideoFrameReader:
    def __init__(self, video_path: Path) -> None:
        self.video_path = video_path
        self.cap = cv2.VideoCapture(str(video_path))
        if not self.cap.isOpened():
            raise RuntimeError(f"cannot open video: {video_path}")
        self.fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 0.0)
        count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.frame_count = max(0, count)
        self._next_index = 0
        self._last_frame: np.ndarray | None = None

    def read_at(self, frame_index: int) -> np.ndarray:
        if frame_index < 0:
            frame_index = 0
        if self.frame_count > 0:
            frame_index = min(frame_index, self.frame_count - 1)

        # Fast path for repeated requests of the same index.
        if self._last_frame is not None and frame_index == self._next_index - 1:
            return self._last_frame

        # Seek backwards only when needed.
        if frame_index < self._next_index:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            self._next_index = frame_index

        while self._next_index <= frame_index:
            ok, frame = self.cap.read()
            if not ok:
                if self._last_frame is not None:
                    return self._last_frame
                raise RuntimeError(f"cannot decode frame {frame_index} from {self.video_path}")
            self._last_frame = frame
            self._next_index += 1

        if self._last_frame is None:
            raise RuntimeError(f"cannot decode frame {frame_index} from {self.video_path}")
        return self._last_frame

    def close(self) -> None:
        self.cap.release()


def _resize_pad_with_rect(frame: np.ndarray, target_w: int, target_h: int) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    h, w = frame.shape[:2]
    scale = min(target_w / max(1, w), target_h / max(1, h))
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
    x0 = (target_w - new_w) // 2
    y0 = (target_h - new_h) // 2
    canvas[y0 : y0 + new_h, x0 : x0 + new_w] = resized
    return canvas, (x0, y0, new_w, new_h)


def _resize_pad(frame: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
    canvas, _ = _resize_pad_with_rect(frame, target_w, target_h)
    return canvas


def _draw_pose_overlay_on_padded(
    frame: np.ndarray,
    sample: list[list[float]] | None,
    color: tuple[int, int, int],
    min_visibility: float = 0.35,
    content_rect: tuple[int, int, int, int] | None = None,
) -> np.ndarray:
    if sample is None:
        return frame

    out = frame.copy()
    h, w = out.shape[:2]
    if content_rect is None:
        x0, y0, content_w, content_h = 0, 0, w, h
    else:
        x0, y0, content_w, content_h = content_rect
    content_w = max(1, int(content_w))
    content_h = max(1, int(content_h))

    points: list[tuple[int, int] | None] = []
    vis_flags: list[bool] = []
    for p in sample:
        x = float(p[0]) if len(p) > 0 else 0.0
        y = float(p[1]) if len(p) > 1 else 0.0
        vis = float(p[3]) if len(p) > 3 else 0.0
        in_frame = 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
        visible = in_frame and vis >= min_visibility
        vis_flags.append(visible)
        if not visible:
            points.append(None)
            continue
        px = x0 + int(round(x * (content_w - 1)))
        py = y0 + int(round(y * (content_h - 1)))
        points.append((px, py))

    for a, b in POSE_CONNECTIONS:
        if a >= len(points) or b >= len(points):
            continue
        pa = points[a]
        pb = points[b]
        if pa is None or pb is None:
            continue
        cv2.line(out, pa, pb, color, OVERLAY_LINE_THICKNESS, cv2.LINE_AA)

    for idx, pt in enumerate(points):
        if pt is None:
            continue
        cv2.circle(out, pt, OVERLAY_POINT_RADIUS, color, -1, cv2.LINE_AA)

    return out


def _sample_to_frame_index(sample_index: int, sample_count: int, frame_count: int) -> int:
    if frame_count <= 1 or sample_count <= 1:
        return 0
    ratio = max(0.0, min(1.0, float(sample_index) / float(sample_count - 1)))
    return int(round(ratio * (frame_count - 1)))


def _trimmed_frame_range(reader: _VideoFrameReader, trim_start_sec: float | None, trim_end_sec: float | None) -> tuple[int, int, int]:
    frame_count = max(1, int(reader.frame_count))
    fps = float(reader.fps or 0.0)
    if fps <= 1e-6:
        fps = 30.0

    start_sec = float(trim_start_sec) if trim_start_sec is not None else 0.0
    end_sec = float(trim_end_sec) if trim_end_sec is not None else None

    start_idx = int(max(0, round(start_sec * fps)))
    start_idx = min(start_idx, frame_count - 1)

    if end_sec is None:
        end_idx = frame_count - 1
    else:
        end_idx = int(max(start_idx, round(end_sec * fps)))
        end_idx = min(end_idx, frame_count - 1)

    count = max(1, end_idx - start_idx + 1)
    return start_idx, end_idx, count


def _extract_video_pose_samples_fast(
    video_path: str,
    *,
    trim_start_sec: float | None = None,
    trim_end_sec: float | None = None,
    flip_h: bool = False,
) -> list[list[list[float]]]:
    """Fast extraction for finalize path: try stride=2 first, then fallback to stride=1."""
    last_error: Exception | None = None
    for stride in (2, 1):
        try:
            return extract_video_pose_samples(
                video_path,
                frame_stride=stride,
                trim_start_sec=trim_start_sec,
                trim_end_sec=trim_end_sec,
                flip_h=flip_h,
            )
        except Exception as exc:
            last_error = exc
            message = str(exc)
            if stride == 2 and "Not enough valid pose frames" in message:
                continue
            raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("pose extraction failed")



def smooth_signal(x: np.ndarray, win: int) -> np.ndarray:
    if win <= 1:
        return x
    k = max(1, int(win))
    kernel = np.ones(k, dtype=np.float32) / float(k)
    return np.convolve(x, kernel, mode="same")

def get_mse_signal(
    frames: list[np.ndarray], 
    smooth_window: int = 5,
    crop_h1: float = 0.20,
    crop_h2: float = 1.00,
    crop_w1: float = 0.20,
    crop_w2: float = 0.80
) -> np.ndarray:
    if not frames:
        return np.array([])
        
    h, w = frames[0].shape[:2]
    crop_h1_val, crop_h2_val = int(h * crop_h1), int(h * crop_h2)
    crop_w1_val, crop_w2_val = int(w * crop_w1), int(w * crop_w2)

    gray_frames = []
    for f in frames:
        cropped = f[crop_h1_val:crop_h2_val, crop_w1_val:crop_w2_val]
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (16, 64))
        gray_frames.append(gray.astype(np.float32))

    base_frame = gray_frames[0]
    
    sig = []
    for f in gray_frames:
        mse = np.mean((f - base_frame)**2)
        sig.append(mse)
        
    sig = np.array(sig)
    sig_smooth = smooth_signal(sig, smooth_window)
    
    sig_min = np.min(sig_smooth)
    sig_max = np.max(sig_smooth)
    if sig_max - sig_min > 1e-6:
        sig_smooth = (sig_smooth - sig_min) / (sig_max - sig_min)
    else:
        sig_smooth = np.zeros_like(sig_smooth)
        
    return sig_smooth

def keyframe_align(s_sig: np.ndarray, t_sig: np.ndarray) -> np.ndarray:
    if len(s_sig) == 0 or len(t_sig) == 0:
        return np.array([], dtype=np.int32)
    s_bot = int(np.argmax(s_sig))
    t_bot = int(np.argmax(t_sig))
    
    s_top1, s_top2 = 0, len(s_sig) - 1
    t_top1, t_top2 = 0, len(t_sig) - 1
    
    mapping = np.zeros(len(s_sig), dtype=np.int32)
    
    if s_bot > s_top1:
        down_map = np.linspace(t_top1, t_bot, s_bot - s_top1 + 1)
        mapping[s_top1:s_bot+1] = np.round(down_map).astype(np.int32)
    else:
        mapping[0] = t_bot
        
    if s_top2 > s_bot:
        up_map = np.linspace(t_bot, t_top2, s_top2 - s_bot + 1)
        mapping[s_bot:s_top2+1] = np.round(up_map).astype(np.int32)
    else:
        mapping[-1] = t_bot
        
    return np.clip(mapping, 0, len(t_sig) - 1)

def resize_keep_aspect(frame: np.ndarray, target_h: int) -> np.ndarray:
    h, w = frame.shape[:2]
    scale = target_h / h
    new_w = int(round(w * scale))
    return cv2.resize(frame, (new_w, target_h), interpolation=cv2.INTER_LINEAR)

def draw_label(
    frame: np.ndarray,
    label: str,
    rep: int,
    total_reps: int,
    phase: float,
    flash: int,
    side: str = "left",
) -> np.ndarray:
    canvas = frame.copy()
    h, w = canvas.shape[:2]

    overlay = canvas.copy()
    cv2.rectangle(overlay, (0, 0), (w, 70), (30, 30, 30), -1)
    cv2.addWeighted(overlay, 0.65, canvas, 0.35, 0, canvas)

    cv2.putText(canvas, label, (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)

    rep_text = f"Rep {rep}/{max(1, total_reps)}"
    cv2.putText(canvas, rep_text, (12, 58),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 230, 118), 2)

    bar_w = int(phase * (w - 24))
    cv2.rectangle(canvas, (12, 64), (12 + bar_w, 68), (0, 200, 255), -1)

    if flash > 0 and side == "left":
        alpha = min(flash / 8.0, 1.0)
        flash_overlay = canvas.copy()
        cv2.rectangle(flash_overlay, (w - 140, 8), (w - 8, 42),
                      (0, 180, 0), -1)
        cv2.putText(flash_overlay, "REP +1", (w - 132, 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.addWeighted(flash_overlay, alpha, canvas, 1 - alpha, 0, canvas)

    return canvas

def smooth_signal(x: np.ndarray, win: int) -> np.ndarray:
    if win <= 1:
        return x
    k = max(1, int(win))
    kernel = np.ones(k, dtype=np.float32) / float(k)
    return np.convolve(x, kernel, mode="same")


def get_mse_signal(
    frames: list[np.ndarray], 
    smooth_window: int = 5,
    crop_h1: float = 0.20,
    crop_h2: float = 1.00,
    crop_w1: float = 0.20,
    crop_w2: float = 0.80
) -> np.ndarray:
    if not frames:
        return np.array([])
        
    h, w = frames[0].shape[:2]
    crop_h1_val, crop_h2_val = int(h * crop_h1), int(h * crop_h2)
    crop_w1_val, crop_w2_val = int(w * crop_w1), int(w * crop_w2)

    gray_frames = []
    for f in frames:
        cropped = f[crop_h1_val:crop_h2_val, crop_w1_val:crop_w2_val]
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (16, 64))
        gray_frames.append(gray.astype(np.float32))

    base_frame = gray_frames[0]
    
    sig = []
    for f in gray_frames:
        mse = np.mean((f - base_frame)**2)
        sig.append(mse)
        
    sig = np.array(sig)
    sig_smooth = smooth_signal(sig, smooth_window)
    
    sig_min = np.min(sig_smooth)
    sig_max = np.max(sig_smooth)
    if sig_max - sig_min > 1e-6:
        sig_smooth = (sig_smooth - sig_min) / (sig_max - sig_min)
    else:
        sig_smooth = np.zeros_like(sig_smooth)
        
    return sig_smooth


def keyframe_align(s_sig: np.ndarray, t_sig: np.ndarray) -> np.ndarray:
    s_bot = int(np.argmax(s_sig))
    t_bot = int(np.argmax(t_sig))
    
    s_top1, s_top2 = 0, len(s_sig) - 1
    t_top1, t_top2 = 0, len(t_sig) - 1
    
    mapping = np.zeros(len(s_sig), dtype=np.int32)
    
    if s_bot > s_top1:
        down_map = np.linspace(t_top1, t_bot, s_bot - s_top1 + 1)
        mapping[s_top1:s_bot+1] = np.round(down_map).astype(np.int32)
    else:
        mapping[0] = t_bot
        
    if s_top2 > s_bot:
        up_map = np.linspace(t_bot, t_top2, s_top2 - s_bot + 1)
        mapping[s_bot:s_top2+1] = np.round(up_map).astype(np.int32)
    else:
        mapping[-1] = t_bot
        
    return np.clip(mapping, 0, len(t_sig) - 1)


def _active_span_from_mse_signal(signal: np.ndarray, expected_reps: int = 1) -> tuple[int, int]:
    if signal.size == 0:
        return (0, -1)
    if signal.size == 1:
        return (0, 0)

    lo = float(np.min(signal))
    hi = float(np.max(signal))
    span = hi - lo
    if span < 0.10:
        return (0, int(signal.size - 1))

    threshold = lo + (0.22 * span)
    active = np.where(signal >= threshold)[0]
    if active.size == 0:
        return (0, int(signal.size - 1))

    margin = max(2, int(signal.size * 0.02))
    start_idx = max(0, int(active[0]) - margin)
    end_idx = min(int(signal.size - 1), int(active[-1]) + margin)
    min_required = max(12, int(expected_reps) * 8)
    if (end_idx - start_idx + 1) < min_required:
        return (0, int(signal.size - 1))
    return (start_idx, end_idx)


def _split_even_rep_windows(start_idx: int, end_idx: int, rep_count: int) -> list[tuple[int, int]]:
    if end_idx < start_idx:
        return []
    reps = max(1, int(rep_count))
    total = end_idx - start_idx + 1
    if reps <= 1 or total < reps:
        return [(int(start_idx), int(end_idx))]

    edges = np.linspace(start_idx, end_idx + 1, reps + 1)
    windows: list[tuple[int, int]] = []
    for i in range(reps):
        s = int(round(edges[i]))
        e = int(round(edges[i + 1])) - 1
        if i == reps - 1:
            e = int(end_idx)
        s = max(int(start_idx), min(s, int(end_idx)))
        e = max(s, min(e, int(end_idx)))
        windows.append((s, e))
    return windows


def _find_top_minima_indices(
    signal: np.ndarray,
    start_idx: int,
    end_idx: int,
    expected_reps: int,
) -> list[int]:
    if signal.size < 3 or end_idx - start_idx < 6:
        return []
    arr = np.asarray(signal, dtype=np.float32)
    lo = float(np.min(arr[start_idx : end_idx + 1]))
    hi = float(np.max(arr[start_idx : end_idx + 1]))
    span = hi - lo
    if span < 1e-6:
        return []

    # "Top" posture minima should stay near lower band of the normalized signal.
    top_band = lo + (0.45 * span)
    min_distance = max(8, int((end_idx - start_idx + 1) / max(2, expected_reps * 2)))

    candidates: list[int] = []
    for i in range(max(start_idx + 1, 1), min(end_idx, len(arr) - 2) + 1):
        if arr[i] <= arr[i - 1] and arr[i] <= arr[i + 1] and arr[i] <= top_band:
            candidates.append(i)

    if not candidates:
        return []

    # Keep stronger minima first, then enforce spacing.
    ranked = sorted(candidates, key=lambda idx: float(arr[idx]))
    selected: list[int] = []
    for idx in ranked:
        if all(abs(idx - j) >= min_distance for j in selected):
            selected.append(idx)
    return sorted(selected)


def _rep_windows_from_mse_signal(signal: np.ndarray, expected_reps: int) -> list[tuple[int, int]]:
    reps = max(1, int(expected_reps))
    if signal.size == 0:
        return []

    start_idx, end_idx = _active_span_from_mse_signal(signal, expected_reps=reps)
    if end_idx <= start_idx:
        return [(0, max(0, int(signal.size - 1)))]
    if reps <= 1:
        return [(start_idx, end_idx)]

    minima = _find_top_minima_indices(signal, start_idx, end_idx, reps)
    if not minima:
        return _split_even_rep_windows(start_idx, end_idx, reps)

    # Pick (reps-1) boundaries closest to equally spaced anchors.
    anchors = np.linspace(start_idx, end_idx, reps + 1)[1:-1]
    used: set[int] = set()
    chosen: list[int] = []
    last = start_idx
    for anchor in anchors:
        opts = [m for m in minima if m not in used and m > last and m < end_idx]
        if not opts:
            continue
        best = min(opts, key=lambda m: abs(float(m) - float(anchor)))
        used.add(best)
        chosen.append(best)
        last = best

    if len(chosen) != (reps - 1):
        return _split_even_rep_windows(start_idx, end_idx, reps)

    boundaries = [start_idx] + sorted(chosen) + [end_idx]
    windows: list[tuple[int, int]] = []
    for i in range(reps):
        s = int(boundaries[i])
        e = int(boundaries[i + 1]) - 1
        if i == reps - 1:
            e = int(end_idx)
        s = max(start_idx, min(s, end_idx))
        e = max(s, min(e, end_idx))
        windows.append((s, e))
    return windows


def _render_sync_comparison_video(
    template_video_uri: str,
    student_video_uri: str,
    student_rep_indices: list[int],
    total_reps: int,
    template_samples: list[list[list[float]]],
    student_samples: list[list[list[float]]],
) -> str | None:
    """Render sync like sync_student_teacher.py (MSE + keyframe align), no MediaPipe dependency."""
    import uuid
    import subprocess
    import traceback

    teacher_path = _resolve_video_path(template_video_uri)
    student_path = _resolve_video_path(student_video_uri)

    if not teacher_path.exists() or not student_path.exists():
        print(f"[render_sync] Missing video: teacher={teacher_path.exists()}, student={student_path.exists()}")
        return None

    out_name = f"analysis_sync_{uuid.uuid4()}.mp4"
    out_path = ANALYSIS_DIR / out_name
    temp_path = ANALYSIS_DIR / f"temp_{out_name}"

    try:
        student_frames, student_fps = _read_video_frames(student_path)
        teacher_frames, _ = _read_video_frames(teacher_path)
        if not student_frames or not teacher_frames:
            raise RuntimeError("empty video frames for sync render")

        expected_reps = max(1, int(total_reps or 1))
        student_signal_full = get_mse_signal(student_frames, smooth_window=5)
        teacher_signal_full = get_mse_signal(teacher_frames, smooth_window=5)
        if teacher_signal_full.size == 0:
            raise RuntimeError("teacher mse signal empty")

        rep_windows = _rep_windows_from_mse_signal(student_signal_full, expected_reps=expected_reps)
        if not rep_windows:
            rep_windows = [(0, len(student_frames) - 1)]

        n_teacher = len(teacher_frames)
        teacher_map = np.round(np.linspace(0, max(0, n_teacher - 1), len(student_frames))).astype(np.int32)
        frame_phase = np.zeros(len(student_frames), dtype=np.float32)
        frame_rep = np.zeros(len(student_frames), dtype=np.int32)

        for rep_idx, (start_f, end_f) in enumerate(rep_windows, start=1):
            if end_f <= start_f:
                continue
            query_frames = student_frames[start_f : end_f + 1]
            if not query_frames:
                continue
            student_rep_signal = get_mse_signal(query_frames, smooth_window=5)
            if student_rep_signal.size == 0:
                continue
            rep_map = keyframe_align(student_rep_signal, teacher_signal_full)
            if rep_map.size == 0:
                rep_map = np.round(
                    np.linspace(0, max(0, n_teacher - 1), len(query_frames))
                ).astype(np.int32)

            local_len = min(len(query_frames), int(rep_map.size))
            for local_i in range(local_len):
                g_idx = start_f + local_i
                if g_idx < 0 or g_idx >= len(student_frames):
                    continue
                t_idx = int(rep_map[local_i])
                t_idx = max(0, min(t_idx, n_teacher - 1))
                teacher_map[g_idx] = t_idx
                frame_phase[g_idx] = t_idx / max(1, n_teacher - 1)
                frame_rep[g_idx] = rep_idx

        render_start = max(0, rep_windows[0][0])
        render_end = min(len(student_frames) - 1, rep_windows[-1][1])
        if render_end <= render_start:
            render_start = 0
            render_end = len(student_frames) - 1

        canvas_h = 640
        sample_s = resize_keep_aspect(student_frames[render_start], canvas_h)
        sample_t = resize_keep_aspect(teacher_frames[0], canvas_h)
        sw = max(1, int(sample_s.shape[1]))
        tw = max(1, int(sample_t.shape[1]))
        divider_thickness = 4
        canvas_w = sw + divider_thickness + tw
        fps_raw = float(student_fps) if np.isfinite(float(student_fps)) else 0.0
        if fps_raw <= 0.0:
            fps_raw = 30.0
        # Browser-recorded WebM can expose absurd FPS metadata (e.g. 1000), causing near-0s outputs.
        fps = max(12.0, min(30.0, fps_raw))

        writer = cv2.VideoWriter(
            str(temp_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (canvas_w, canvas_h),
        )
        if not writer.isOpened():
            raise RuntimeError(f"Cannot open VideoWriter: {temp_path}")

        prev_rep = 0
        flash = 0
        try:
            for i in range(render_start, render_end + 1):
                t_idx = int(teacher_map[i]) if i < len(teacher_map) else 0
                t_idx = max(0, min(t_idx, n_teacher - 1))

                cur_rep = int(frame_rep[i]) if i < len(frame_rep) and int(frame_rep[i]) > 0 else 1
                cur_phase = float(frame_phase[i]) if i < len(frame_phase) else 0.0
                if cur_rep > prev_rep:
                    flash = 10
                prev_rep = cur_rep
                display_rep = min(max(1, cur_rep), expected_reps)

                s_panel = resize_keep_aspect(cv2.flip(student_frames[i], 1), canvas_h)
                t_panel = resize_keep_aspect(teacher_frames[t_idx], canvas_h)
                s_panel = cv2.resize(s_panel, (sw, canvas_h))
                t_panel = cv2.resize(t_panel, (tw, canvas_h))

                s_panel = draw_label(s_panel, "STUDENT", display_rep, expected_reps, cur_phase, flash, side="left")
                t_panel = draw_label(t_panel, "TEACHER", display_rep, expected_reps, cur_phase, flash=0, side="right")

                divider = np.full((canvas_h, divider_thickness, 3), 200, dtype=np.uint8)
                canvas = np.hstack([s_panel, divider, t_panel])
                writer.write(canvas)

                if flash > 0:
                    flash -= 1
        finally:
            writer.release()

    except Exception as e:
        print(f"[render_sync] keyframe sync build failed: {e}")
        with open(ANALYSIS_DIR / "dtw_error.txt", "w") as f:
            traceback.print_exc(file=f)
        traceback.print_exc()
        return None

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(temp_path),
                "-vcodec", "libx264", "-pix_fmt", "yuv420p",
                "-preset", "fast", "-crf", "23",
                "-r", str(int(round(fps))),
                str(out_path)
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        if temp_path.exists():
            temp_path.unlink()
    except Exception as e:
        print(f"[render_sync] FFmpeg error: {e}")
        if temp_path.exists():
            temp_path.rename(out_path)

    return f"/uploads/analysis_sync/{out_name}"



def _analyze_segment(
    template: WorkoutTemplate,
    template_profile: dict[str, Any],
    template_features: list[list[float]],
    template_samples: list[list[list[float]]],
    segment: dict[str, Any],
) -> dict[str, Any]:
    segment_started_at = time.perf_counter()
    observed_rep_count = int(segment.get("observed_rep_count") or 0)

    # Temporary fallback path for reps: avoid MediaPipe-dependent post-analysis.
    # Use live observed reps + keyframe sync render (same spirit as sync_student_teacher.py).
    if template.mode == "reps":
        total_reps = max(1, observed_rep_count)
        render_started_at = time.perf_counter()
        comparison_video_uri = _render_sync_comparison_video(
            template_video_uri=template.video_uri,
            student_video_uri=str(segment["video_uri"]),
            student_rep_indices=[],
            total_reps=total_reps,
            template_samples=[],
            student_samples=[],
        )
        render_comparison_ms = int((time.perf_counter() - render_started_at) * 1000)
        total_segment_ms = int((time.perf_counter() - segment_started_at) * 1000)
        comparison_video_generated = bool(comparison_video_uri)
        if not comparison_video_uri:
            comparison_video_uri = str(segment["video_uri"])

        return {
            "template_id": template.template_id,
            "exercise_name": template.name,
            "mode": template.mode,
            "step_index": int(segment["step_index"]),
            "set_index": int(segment["set_index"]),
            "video_uri": str(segment["video_uri"]),
            "duration_seconds": round(float(segment.get("duration_seconds", 0.0)), 2),
            "samples": 0,
            "distance": 0.0,
            "normalized_distance": 0.0,
            "similarity": 0.0,
            "top_issues": [],
            "feedback": [],
            "joint_analyses": [],
            "top_joint_issues": [],
            "pose_connections": POSE_CONNECTIONS,
            "template_pose_samples": [],
            "student_pose_samples": [],
            "pose_frame_count": 0,
            "template_cycles": total_reps,
            "observed_student_reps": observed_rep_count,
            "estimated_student_reps": total_reps,
            "effective_rep_target": total_reps,
            "student_motion_score": 0.0,
            "student_low_motion": False,
            "template_assumed_single_rep": True,
            "template_video_uri": template.video_uri,
            "comparison_video_uri": comparison_video_uri,
            "comparison_video_generated": comparison_video_generated,
            "timing_ms": {
                "extract_student_pose": 0,
                "student_features": 0,
                "dtw": 0,
                "post_process": 0,
                "render_comparison_video": render_comparison_ms,
                "total": total_segment_ms,
            },
            "frame_analyses": [],
            "rep_feedback": [],
        }

    video_path = _resolve_video_path(str(segment["video_uri"]))

    extract_started_at = time.perf_counter()
    student_samples = _extract_video_pose_samples_fast(str(video_path), flip_h=True)
    extract_student_pose_ms = int((time.perf_counter() - extract_started_at) * 1000)

    features_started_at = time.perf_counter()
    student_features = features_from_samples(student_samples)
    student_feature_ms = int((time.perf_counter() - features_started_at) * 1000)
    student_motion = _sample_motion_score(student_samples)
    student_low_motion = student_motion < 0.0025

    # Auto-repair if template features have stale dimensions (e.g., old 22-dim vs new 10-dim)
    if template_features and student_features:
        t_dim = len(template_features[0]) if template_features else 0
        s_dim = len(student_features[0]) if student_features else 0
        if t_dim != s_dim and template_samples:
            template_features = features_from_samples(template_samples)
            if template_profile is not None:
                template_profile["features"] = template_features
    estimated_reps = _estimate_student_reps(student_features, template_profile, template.mode)
    effective_rep_target = _effective_rep_target(observed_rep_count, estimated_reps)

    if template.mode == "reps" and student_low_motion:
        # If recorded segment is visually near-static, avoid forcing template loops
        # from live observed reps because it causes degenerate DTW alignments.
        effective_rep_target = max(1, int(estimated_reps or 1))

    if template.mode == "reps" and template_features:
        # Product rule: template clip always represents exactly one rep.
        repeat_cycles = max(1, int(effective_rep_target))
        template_features, template_samples = _repeat_template_cycles(
            template_features,
            template_samples,
            repeat_cycles,
        )
        template_cycles = repeat_cycles
    else:
        template_cycles = 1

    # For reps: keep fully repeated template cycles (one template rep * N cycles).
    # For hold: no cycle expansion is needed.
    if template.mode == "reps":
        expanded_template_features, expanded_template_samples = template_features, template_samples
    else:
        expanded_template_features, expanded_template_samples = _slice_template_to_rep_target(
            template_features,
            template_samples,
            template_profile,
            template.mode,
            effective_rep_target,
        )

    dtw_started_at = time.perf_counter()
    student_rep_indices = _rep_indices_for_student(student_features, template_profile, template.mode)

    # Run real DTW comparison
    dtw = dtw_distance(
        expanded_template_features,
        student_features,
        window=None,
    )
    dtw_ms = int((time.perf_counter() - dtw_started_at) * 1000)

    post_process_started_at = time.perf_counter()

    # Compute similarity from normalized distance
    if dtw.normalized_distance > 0:
        similarity = max(0.0, min(1.0, 1.0 / (1.0 + dtw.normalized_distance)))
    else:
        similarity = 1.0

    # Analyze per-frame and per-joint issues
    issues = []
    joint_analyses = []
    aligned_template = []
    aligned_student = []
    frame_analyses = []
    rep_feedback = []

    # Build aligned sequences from DTW path for pose overlay
    if dtw.path:
        for t_idx, s_idx in dtw.path:
            if t_idx < len(expanded_template_samples) and s_idx < len(student_samples):
                aligned_template.append(expanded_template_samples[t_idx])
                aligned_student.append(student_samples[s_idx])

    post_process_ms = int((time.perf_counter() - post_process_started_at) * 1000)
    render_started_at = time.perf_counter()

    comparison_video_uri = _render_sync_comparison_video(
        template_video_uri=template.video_uri,
        student_video_uri=str(segment["video_uri"]),
        student_rep_indices=student_rep_indices,
        total_reps=template_cycles,
        template_samples=template_samples,
        student_samples=student_samples,
    )
    render_comparison_ms = int((time.perf_counter() - render_started_at) * 1000)

    total_segment_ms = int((time.perf_counter() - segment_started_at) * 1000)
    comparison_video_generated = bool(comparison_video_uri)
    if not comparison_video_uri:
        comparison_video_uri = str(segment["video_uri"])

    return {
        "template_id": template.template_id,
        "exercise_name": template.name,
        "mode": template.mode,
        "step_index": int(segment["step_index"]),
        "set_index": int(segment["set_index"]),
        "video_uri": str(segment["video_uri"]),
        "duration_seconds": round(float(segment.get("duration_seconds", 0.0)), 2),
        "samples": len(student_features),
        "distance": round(dtw.distance, 4),
        "normalized_distance": round(dtw.normalized_distance, 4),
        "similarity": round(similarity, 4),
        "top_issues": issues[:3],
        "feedback": _issue_feedback(issues),
        "joint_analyses": joint_analyses,
        "top_joint_issues": joint_analyses[:4],
        "pose_connections": POSE_CONNECTIONS,
        "template_pose_samples": [],
        "student_pose_samples": [],
        "pose_frame_count": 0,
        "template_cycles": template_cycles,
        "observed_student_reps": observed_rep_count,
        "estimated_student_reps": estimated_reps,
        "effective_rep_target": effective_rep_target,
        "student_motion_score": round(float(student_motion), 6),
        "student_low_motion": bool(student_low_motion),
        "template_assumed_single_rep": bool(template.mode == "reps"),
        "template_video_uri": template.video_uri,
        "comparison_video_uri": comparison_video_uri,
        "comparison_video_generated": comparison_video_generated,
        "timing_ms": {
            "extract_student_pose": extract_student_pose_ms,
            "student_features": student_feature_ms,
            "dtw": dtw_ms,
            "post_process": post_process_ms,
            "render_comparison_video": render_comparison_ms,
            "total": total_segment_ms,
        },
        "frame_analyses": frame_analyses,
        "rep_feedback": rep_feedback,
    }


@app.post("/v1/library/templates/{template_id}/profile", response_model=TemplateProfileResponse)
def build_template_profile(template_id: str) -> TemplateProfileResponse:
    template = TEMPLATE_LIBRARY.get(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="template not found")

    existing_profile = TEMPLATE_PROFILES.get(template_id) or STORE.get_template_profile(template_id) or {}
    frozen_meta = existing_profile.get("frozen_artifact") if isinstance(existing_profile, dict) else None
    if not isinstance(frozen_meta, dict):
        frozen_meta = {}

    if str(template.video_uri).startswith("/uploads/template_frozen/"):
        source_video_uri = str(frozen_meta.get("source_video_uri") or template.video_uri)
        needs_pose_artifacts = not (
            str(frozen_meta.get("debug_overlay_video_uri", "")).strip()
            and str(frozen_meta.get("pose_timeline_json_uri", "")).strip()
        )
        if needs_pose_artifacts:
            try:
                exported = _export_template_pose_artifacts(
                    template_id=template_id,
                    source_video_uri=source_video_uri,
                    frozen_video_uri=template.video_uri,
                )
                frozen_meta.update(exported)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"cannot export pose artifacts: {exc}") from exc
        frozen_meta.setdefault("frozen_video_uri", template.video_uri)
        frozen_meta.setdefault("source_video_uri", source_video_uri)

    try:
        profile_dict, samples = _build_profile_dict_from_video(
            mode=template.mode,
            video_uri=template.video_uri,
            trim_start_sec=getattr(template, "trim_start_sec", None),
            trim_end_sec=getattr(template, "trim_end_sec", None),
            frozen_meta=(frozen_meta if frozen_meta else None),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"cannot build profile: {exc}") from exc
    TEMPLATE_PROFILES[template_id] = profile_dict
    _persist_template_profiles()
    _persist_template_profile_to_store(template_id, profile_dict)

    return TemplateProfileResponse(
        template_id=template_id,
        ready=True,
        samples=samples,
        profile=profile_dict,
    )


@app.get("/v1/library/templates/{template_id}/profile", response_model=TemplateProfileResponse)
def get_template_profile(template_id: str) -> TemplateProfileResponse:
    profile = TEMPLATE_PROFILES.get(template_id)
    if profile is None:
        profile = STORE.get_template_profile(template_id)
        if isinstance(profile, dict):
            TEMPLATE_PROFILES[template_id] = profile
    if profile is None:
        return TemplateProfileResponse(
            template_id=template_id,
            ready=False,
            samples=0,
            profile={"message": "profile not built"},
        )

    return TemplateProfileResponse(
        template_id=template_id,
        ready=True,
        samples=int(profile.get("samples", 0)),
        profile=profile,
    )


@app.post("/v1/workout/session/start", response_model=WorkoutSessionStartResponse)
def start_workout_session(payload: WorkoutSessionStartRequest) -> WorkoutSessionStartResponse:
    if not TEMPLATE_LIBRARY:
        raise HTTPException(status_code=400, detail="template library is empty")

    steps: list[WorkoutStepConfig] = []
    for s in payload.steps:
        if s.template_id not in TEMPLATE_LIBRARY:
            raise HTTPException(status_code=404, detail=f"template not found: {s.template_id}")
        mode = TEMPLATE_LIBRARY[s.template_id].mode
        if mode == "reps" and not s.reps_per_set:
            raise HTTPException(status_code=400, detail="reps_per_set is required for reps template")
        if mode == "hold" and not s.hold_seconds_per_set:
            raise HTTPException(status_code=400, detail="hold_seconds_per_set is required for hold template")

        steps.append(
            WorkoutStepConfig(
                template_id=s.template_id,
                sets=s.sets,
                reps_per_set=s.reps_per_set,
                hold_seconds_per_set=s.hold_seconds_per_set,
                rest_seconds_between_sets=s.rest_seconds_between_sets,
            )
        )

    adaptive_thresholds_by_template: dict[str, dict[str, float]] = {}
    for step in steps:
        profile = TEMPLATE_PROFILES.get(step.template_id)
        if profile is None:
            loaded = STORE.get_template_profile(step.template_id)
            if isinstance(loaded, dict):
                profile = loaded
                TEMPLATE_PROFILES[step.template_id] = loaded
        adaptive = profile.get("adaptive_thresholds") if isinstance(profile, dict) else None
        if isinstance(adaptive, dict):
            adaptive_thresholds_by_template[step.template_id] = adaptive

    session = WorkoutSession(
        templates=TEMPLATE_LIBRARY,
        plan=WorkoutPlan(steps=steps),
        adaptive_thresholds_by_template=adaptive_thresholds_by_template,
    )
    progress = session.ensure_started()
    session_id = str(uuid.uuid4())
    WORKOUT_SESSIONS[session_id] = session
    speaker = Speaker(enabled=payload.speak_enabled)
    WORKOUT_SPEAKERS[session_id] = speaker
    WORKOUT_EVENT_LOGS[session_id] = []
    WORKOUT_SEGMENTS[session_id] = []
    WORKOUT_EVENT_BUFFER[session_id] = []
    WORKOUT_LAST_STATE_PERSIST[session_id] = {
        "phase": progress.phase,
        "rep_count": progress.rep_count,
        "hold_bucket": int(progress.hold_seconds),
        "done": progress.done,
    }
    STORE.create_workout_session(
        session_id,
        speak_enabled=payload.speak_enabled,
        plan={"steps": [step.model_dump() for step in payload.steps]},
    )
    STORE.update_workout_session_state(session_id, latest_phase=progress.phase, done=progress.done)
    _speak_announcements_throttled(session_id, speaker, progress.announcements)

    return WorkoutSessionStartResponse(
        session_id=session_id,
        phase=progress.phase,
        exercise_name=progress.exercise_name,
        announcements=progress.announcements,
    )


@app.post("/v1/workout/session/frame", response_model=WorkoutProgressResponse)
def workout_frame(payload: WorkoutFrameRequest) -> WorkoutProgressResponse:
    session = WORKOUT_SESSIONS.get(payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="workout session not found")

    readiness_passed = bool(payload.readiness_passed) if payload.readiness_passed is not None else False
    # Only use anchor readiness as a fallback when client does not provide readiness.
    # Do not override an explicit False from client, otherwise session may enter
    # active_set before countdown/pose gate is actually satisfied on frontend.
    if payload.student_frame is not None and payload.readiness_passed is None:
        anchor_ready = _compute_anchor_readiness(session, payload.student_frame)
        if anchor_ready is not None:
            readiness_passed = anchor_ready

    progress = session.frame_update(
        signal=payload.signal,
        timestamp_ms=payload.timestamp_ms,
        readiness_passed=readiness_passed,
    )
    speaker = WORKOUT_SPEAKERS.get(payload.session_id)
    _speak_announcements_throttled(payload.session_id, speaker, progress.announcements)
    response = _progress_response(payload.session_id, progress)
    logs = WORKOUT_EVENT_LOGS.setdefault(payload.session_id, [])
    event = response.model_dump()
    logs.append(event)
    if len(logs) > MAX_IN_MEMORY_EVENTS:
        WORKOUT_EVENT_LOGS[payload.session_id] = logs[-MAX_IN_MEMORY_EVENTS:]

    buffer = WORKOUT_EVENT_BUFFER.setdefault(payload.session_id, [])
    buffer.append(event)

    should_flush_events = (
        len(buffer) >= EVENT_BUFFER_FLUSH_SIZE
        or response.pending_confirmation
        or response.done
        or bool(response.announcements)
    )
    if should_flush_events:
        _flush_event_buffer(payload.session_id)

    if _should_persist_state(payload.session_id, response):
        STORE.update_workout_session_state(payload.session_id, latest_phase=response.phase, done=response.done)
    return response


@app.post("/v1/workout/session/confirm", response_model=WorkoutProgressResponse)
def workout_confirm(payload: WorkoutConfirmRequest) -> WorkoutProgressResponse:
    session = WORKOUT_SESSIONS.get(payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="workout session not found")

    progress = session.confirm()
    speaker = WORKOUT_SPEAKERS.get(payload.session_id)
    _speak_announcements_throttled(payload.session_id, speaker, progress.announcements)
    response = _progress_response(payload.session_id, progress)
    logs = WORKOUT_EVENT_LOGS.setdefault(payload.session_id, [])
    event = response.model_dump()
    logs.append(event)
    _flush_event_buffer(payload.session_id)
    STORE.append_workout_event(payload.session_id, event)
    STORE.update_workout_session_state(payload.session_id, latest_phase=response.phase, done=response.done)
    WORKOUT_LAST_STATE_PERSIST[payload.session_id] = {
        "phase": response.phase,
        "rep_count": response.rep_count,
        "hold_bucket": int(response.hold_seconds),
        "done": response.done,
    }
    return response


@app.post("/v1/workout/session/segment", response_model=WorkoutSegmentResponse)
def workout_segment(payload: WorkoutSegmentCreateRequest) -> WorkoutSegmentResponse:
    session = WORKOUT_SESSIONS.get(payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="workout session not found")

    if payload.step_index >= len(session.plan.steps):
        raise HTTPException(status_code=400, detail="invalid step_index")

    _resolve_video_path(payload.video_uri)

    segment = {
        "step_index": payload.step_index,
        "set_index": payload.set_index,
        "video_uri": payload.video_uri,
        "duration_seconds": payload.duration_seconds,
        "observed_rep_count": payload.observed_rep_count,
    }
    segments = WORKOUT_SEGMENTS.setdefault(payload.session_id, [])
    segments.append(segment)
    STORE.append_segment(payload.session_id, segment)

    return WorkoutSegmentResponse(
        session_id=payload.session_id,
        segment_index=len(segments) - 1,
        step_index=payload.step_index,
        set_index=payload.set_index,
        video_uri=payload.video_uri,
        duration_seconds=payload.duration_seconds,
        observed_rep_count=payload.observed_rep_count,
    )


@app.post("/v1/workout/session/finalize", response_model=WorkoutFinalizeResponse)
def workout_finalize(payload: WorkoutFinalizeRequest) -> WorkoutFinalizeResponse:
    finalize_started_at = time.perf_counter()

    session = WORKOUT_SESSIONS.get(payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="workout session not found")

    _flush_event_buffer(payload.session_id)
    STORE.flush_event_writer(timeout_seconds=3.0)
    logs = WORKOUT_EVENT_LOGS.get(payload.session_id, [])
    segments = WORKOUT_SEGMENTS.get(payload.session_id, [])
    if not logs:
        logs = STORE.list_workout_events(payload.session_id)
    if not segments:
        segments = STORE.list_segments(payload.session_id)
    
    if not segments:
        empty_response = WorkoutFinalizeResponse(
            session_id=payload.session_id,
            done=False,
            total_events=0,
            analysis={
                "message": "Chưa có dữ liệu để phân tích. Hãy thực hiện buổi tập trước.",
            },
        )
        STORE.save_workout_result(
            payload.session_id,
            done=False,
            total_events=0,
            analysis=empty_response.analysis,
        )
        STORE.update_workout_session_state(payload.session_id, latest_phase="idle", done=False, status="active")
        return empty_response

    if logs:
        max_rep = max((int(x.get("rep_count", 0)) for x in logs), default=0)
        max_hold = max((float(x.get("hold_seconds", 0.0)) for x in logs), default=0.0)
        latest = logs[-1]
    else:
        max_rep = max((int(x.get("observed_rep_count", 0)) for x in segments), default=0)
        max_hold = 0.0
        latest = {"phase": "done", "done": True}

    segment_analyses: list[dict[str, Any]] = []
    analysis_errors: list[dict[str, str | int]] = []

    for segment in segments:
        per_segment_started_at = time.perf_counter()
        try:
            step = session.plan.steps[int(segment["step_index"])]
            template = TEMPLATE_LIBRARY.get(step.template_id)
            if template is None:
                raise RuntimeError(f"template not found: {step.template_id}")

            profile_prepare_started_at = time.perf_counter()
            profile = TEMPLATE_PROFILES.get(template.template_id)

            # Auto-rebuild profile if missing or stale feature version
            from motion_core.template_profile import CURRENT_FEATURE_VERSION
            needs_rebuild = (
                profile is None
                or not isinstance(profile.get("features"), list)
                or profile.get("feature_version") != CURRENT_FEATURE_VERSION
            )
            if needs_rebuild:
                template_path = _resolve_video_path(template.video_uri)
                template_samples = _extract_video_pose_samples_fast(
                    str(template_path),
                    trim_start_sec=getattr(template, "trim_start_sec", None),
                    trim_end_sec=getattr(template, "trim_end_sec", None),
                )
                template_features = features_from_samples(template_samples)
                template_profile = build_template_profile_from_features(template_features)
                profile = {
                    "feature_version": template_profile.feature_version,
                    "feature_mean": template_profile.feature_mean,
                    "feature_pc1": template_profile.feature_pc1,
                    "proj_min": template_profile.proj_min,
                    "proj_max": template_profile.proj_max,
                    "features": template_profile.features,
                    "pose_samples": template_samples,
                    "samples": template_profile.samples,
                }
                TEMPLATE_PROFILES[template.template_id] = profile
                _persist_template_profile_to_store(template.template_id, profile)
            else:
                template_features = profile["features"]
                template_samples = profile.get("pose_samples", [])
            if template_samples is None:
                template_path = _resolve_video_path(template.video_uri)
                template_samples = _extract_video_pose_samples_fast(
                    str(template_path),
                    trim_start_sec=getattr(template, "trim_start_sec", None),
                    trim_end_sec=getattr(template, "trim_end_sec", None),
                )
                if profile is not None:
                    profile["pose_samples"] = template_samples

            profile_prepare_ms = int((time.perf_counter() - profile_prepare_started_at) * 1000)
            analyzed = _analyze_segment(template, profile or {}, template_features, template_samples, segment)
            timing = analyzed.get("timing_ms") if isinstance(analyzed, dict) else None
            if isinstance(timing, dict):
                timing["profile_prepare"] = profile_prepare_ms
                timing["total_with_profile_prepare"] = int((time.perf_counter() - per_segment_started_at) * 1000)
            segment_analyses.append(analyzed)
            STORE.upsert_analysis_video(
                session_id=payload.session_id,
                step_index=int(analyzed.get("step_index", 0)),
                set_index=int(analyzed.get("set_index", 0)),
                exercise_name=str(analyzed.get("exercise_name", "")),
                source_video_uri=str(analyzed.get("video_uri", "")),
                comparison_video_uri=str(analyzed.get("comparison_video_uri", "")),
                similarity=float(analyzed.get("similarity", 0.0)),
                normalized_distance=float(analyzed.get("normalized_distance", 0.0)),
            )
        except Exception as exc:
            analysis_errors.append(
                {
                    "step_index": int(segment.get("step_index", -1)),
                    "set_index": int(segment.get("set_index", -1)),
                    "error": str(exc),
                }
            )

    average_similarity = (
        round(sum(float(x["similarity"]) for x in segment_analyses) / len(segment_analyses), 4)
        if segment_analyses
        else 0.0
    )

    segment_timing_list = [x.get("timing_ms", {}) for x in segment_analyses if isinstance(x, dict)]
    total_segment_ms = sum(int(t.get("total", 0) or 0) for t in segment_timing_list if isinstance(t, dict))
    total_render_ms = sum(int(t.get("render_comparison_video", 0) or 0) for t in segment_timing_list if isinstance(t, dict))
    total_extract_ms = sum(int(t.get("extract_student_pose", 0) or 0) for t in segment_timing_list if isinstance(t, dict))
    total_dtw_ms = sum(int(t.get("dtw", 0) or 0) for t in segment_timing_list if isinstance(t, dict))
    total_profile_prepare_ms = sum(int(t.get("profile_prepare", 0) or 0) for t in segment_timing_list if isinstance(t, dict))
    finalize_total_ms = int((time.perf_counter() - finalize_started_at) * 1000)

    analysis = {
        "message": "Đã kết thúc buổi và bắt đầu phân tích sau tập.",
        "final_phase": str(latest.get("phase", "")),
        "max_rep_observed": max_rep,
        "max_hold_seconds_observed": round(max_hold, 2),
        "segment_count": len(segments),
        "analyzed_segments": len(segment_analyses),
        "average_similarity": average_similarity,
        "segments": segment_analyses,
        "errors": analysis_errors,
        "timing_ms": {
            "finalize_total": finalize_total_ms,
            "segments_total": total_segment_ms,
            "segment_avg": int(total_segment_ms / len(segment_analyses)) if segment_analyses else 0,
            "render_total": total_render_ms,
            "extract_pose_total": total_extract_ms,
            "dtw_total": total_dtw_ms,
            "profile_prepare_total": total_profile_prepare_ms,
        },
        "persistence": STORE.queue_stats(),
    }

    response = WorkoutFinalizeResponse(
        session_id=payload.session_id,
        done=bool(latest.get("done", False)),
        total_events=len(logs),
        analysis=analysis,
    )
    STORE.save_workout_result(
        payload.session_id,
        done=response.done,
        total_events=response.total_events,
        analysis=response.analysis,
    )
    STORE.update_workout_session_state(
        payload.session_id,
        latest_phase=str(latest.get("phase", "done")),
        done=response.done,
        status="finalized" if response.done else "active",
    )
    return response


@app.get("/v1/workout/session/{session_id}/result", response_model=WorkoutFinalizeResponse)
def get_workout_result(session_id: str) -> WorkoutFinalizeResponse:
    cached = STORE.get_workout_result(session_id)
    if cached is None:
        raise HTTPException(status_code=404, detail="result not found")
    return WorkoutFinalizeResponse(
        session_id=session_id,
        done=bool(cached.get("done", False)),
        total_events=int(cached.get("total_events", 0)),
        analysis=dict(cached.get("analysis", {})),
    )


@app.delete("/v1/workout/session/{session_id}", response_model=DeleteResponse)
def close_workout_session(session_id: str) -> DeleteResponse:
    _flush_event_buffer(session_id)
    WORKOUT_SESSIONS.pop(session_id, None)
    WORKOUT_SPEAKERS.pop(session_id, None)
    WORKOUT_EVENT_LOGS.pop(session_id, None)
    WORKOUT_SEGMENTS.pop(session_id, None)
    WORKOUT_EVENT_BUFFER.pop(session_id, None)
    WORKOUT_LAST_STATE_PERSIST.pop(session_id, None)
    WORKOUT_SPEECH_STATE.pop(session_id, None)
    return DeleteResponse(ok=True, message="Workout session closed in memory")


@app.get("/v1/library/analysis-videos", response_model=AnalysisVideoListResponse)
def list_analysis_videos() -> AnalysisVideoListResponse:
    items = [
        AnalysisVideoItem(
            id=item.id,
            session_id=item.session_id,
            step_index=item.step_index,
            set_index=item.set_index,
            exercise_name=item.exercise_name,
            source_video_uri=item.source_video_uri,
            comparison_video_uri=item.comparison_video_uri,
            similarity=item.similarity,
            normalized_distance=item.normalized_distance,
            created_at=item.created_at,
        )
        for item in STORE.list_analysis_videos()
    ]
    return AnalysisVideoListResponse(items=items)


@app.delete("/v1/library/analysis-videos/{video_id}", response_model=DeleteResponse)
def delete_analysis_video(video_id: int, delete_file: bool = Query(default=True)) -> DeleteResponse:
    row = STORE.get_analysis_video(video_id)
    if row is None:
        raise HTTPException(status_code=404, detail="analysis video not found")

    file_deleted = False
    if delete_file:
        file_deleted = _remove_uploaded_video_if_safe(row.comparison_video_uri)
    deleted = STORE.delete_analysis_video(video_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="failed to delete analysis video record")

    suffix = " and file removed" if file_deleted else ""
    return DeleteResponse(ok=True, message=f"Analysis video deleted{suffix}")


@app.post("/v1/live/session/start", response_model=LiveSessionStartResponse)
def start_live_session(payload: LiveSessionStartRequest) -> LiveSessionStartResponse:
    specs = [
        ExerciseSpec(
            name=e.name,
            mode=e.mode,
            target_reps=e.target_reps,
            target_seconds=e.target_seconds,
        )
        for e in payload.exercises
    ]
    session = MultiExerciseSession(specs=specs)
    session_id = str(uuid.uuid4())
    LIVE_SESSIONS[session_id] = session

    first_name = specs[0].name if specs else ""
    return LiveSessionStartResponse(session_id=session_id, current_exercise=first_name, done=False)


@app.post("/v1/live/session/frame", response_model=LiveSessionFrameResponse)
def push_live_frame(payload: LiveSessionFrameRequest) -> LiveSessionFrameResponse:
    session = LIVE_SESSIONS.get(payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    progress = session.update(signal=payload.signal, timestamp_ms=payload.timestamp_ms)
    if progress is None:
        return LiveSessionFrameResponse(
            session_id=payload.session_id,
            exercise_name=None,
            mode=None,
            rep_count=0,
            hold_seconds=0.0,
            exercise_completed=False,
            next_exercise=None,
            done=True,
        )

    next_spec = session.current_spec()
    return LiveSessionFrameResponse(
        session_id=payload.session_id,
        exercise_name=progress.name,
        mode=progress.mode,
        rep_count=progress.rep_count,
        hold_seconds=progress.hold_seconds,
        exercise_completed=progress.completed,
        next_exercise=next_spec.name if next_spec else None,
        done=session.done(),
    )
