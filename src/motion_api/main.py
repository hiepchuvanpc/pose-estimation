from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi import Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from motion_core.dtw import dtw_distance, segment_by_signal_valleys
from motion_core.sync_alignment import build_sync_mapping
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
    DTWBacktestRequest,
    DTWBacktestResponse,
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
    LLMFeedbackRequest,
    LLMFeedbackResponse,
)
from .dtw_analysis_adapter import DTWAnalysisAdapter, build_clean_segment_result
from .speaker import Speaker

app = FastAPI(title="Motion Coach API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
WEB_DIR = Path(__file__).resolve().parents[2] / "web"
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
APP_DIR = Path(__file__).resolve().parents[2]
ANALYSIS_DIR = UPLOAD_DIR / "analysis_sync"
TEMPLATE_FROZEN_DIR = UPLOAD_DIR / "template_frozen"
TEMPLATE_STORE_PATH = DATA_DIR / "templates.json"
UPLOAD_INDEX_PATH = DATA_DIR / "upload_index.json"
TEMPLATE_PROFILE_STORE_PATH = DATA_DIR / "template_profiles.json"
SQLITE_DB_PATH = DATA_DIR / "motion_coach.db"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATE_FROZEN_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="web_static")
app.mount("/data/models", StaticFiles(directory=str(DATA_DIR / "models")), name="data_models")


@app.get("/", include_in_schema=False)
def serve_index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")

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
DTW_ANALYSIS_ADAPTER = DTWAnalysisAdapter()

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


def _load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            # Keep explicit environment variable precedence over .env file.
            os.environ.setdefault(key, value)
    except Exception:
        # Non-fatal: app should still run without .env parsing.
        return


_load_env_file(APP_DIR / ".env")


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


def _ensure_feature_weights(profile: dict[str, Any]) -> list[float]:
    weights = profile.get("feature_weights")
    if isinstance(weights, list) and weights:
        return [float(x) for x in weights]

    features = profile.get("features", [])
    if not isinstance(features, list) or not features:
        return []

    arr = np.asarray(features, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] <= 0:
        return []

    ranges = np.nanmax(arr, axis=0) - np.nanmin(arr, axis=0)
    ranges = np.where(np.isfinite(ranges), ranges, 0.0)
    max_range = float(np.max(ranges)) if ranges.size > 0 else 0.0
    if max_range <= 1e-6:
        weights_arr = np.ones(arr.shape[1], dtype=np.float32)
    else:
        weights_arr = ranges / max_range

    weights_arr = np.clip(weights_arr, 0.15, 1.0)
    profile["feature_ranges"] = ranges.tolist()
    profile["feature_weights"] = weights_arr.tolist()

    if "feature_group_motion" not in profile:
        group_motion: dict[str, float] = {}
        for name, idxs in FEATURE_GROUPS.items():
            total = 0.0
            count = 0
            for idx in idxs:
                if idx < len(ranges):
                    total += float(ranges[idx])
                    count += 1
            if count:
                group_motion[name] = round(total / count, 6)
        if group_motion:
            profile["feature_group_motion"] = group_motion

    mean = [float(x) for x in profile.get("feature_mean", [])]
    pc1 = [float(x) for x in profile.get("feature_pc1", [])]
    n = min(len(mean), len(pc1), arr.shape[1])
    if n > 0:
        mean_arr = np.asarray(mean[:n], dtype=np.float32)
        pc1_arr = np.asarray(pc1[:n], dtype=np.float32)
        weights_n = weights_arr[:n]
        proj = (arr[:, :n] - mean_arr) * weights_n
        proj_vals = proj @ pc1_arr
        if proj_vals.size > 0:
            profile["weighted_proj_min"] = float(np.min(proj_vals))
            profile["weighted_proj_max"] = float(np.max(proj_vals))

    return profile["feature_weights"]


def _compute_feature_group_motion_profile(profile: dict[str, Any]) -> None:
    features = profile.get("features", [])
    if not isinstance(features, list) or len(features) < 3:
        return

    arr = np.asarray(features, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] <= 0:
        return

    deltas = np.abs(np.diff(arr, axis=0))
    group_stats: dict[str, dict[str, float]] = {}
    group_means: list[tuple[str, float]] = []

    for name, idxs in FEATURE_GROUPS.items():
        valid = [i for i in idxs if i < deltas.shape[1]]
        if not valid:
            continue
        per_frame = np.mean(deltas[:, valid], axis=1)
        mean_val = float(np.mean(per_frame))
        p50 = float(np.quantile(per_frame, 0.50))
        p75 = float(np.quantile(per_frame, 0.75))
        group_stats[name] = {
            "mean": round(mean_val, 6),
            "p50": round(p50, 6),
            "p75": round(p75, 6),
        }
        group_means.append((name, mean_val))

    if not group_means:
        return

    max_mean = max(val for _, val in group_means)
    if max_mean <= 1e-6:
        return

    dominant = [name for name, val in group_means if val >= (0.6 * max_mean)]
    if not dominant:
        dominant = [max(group_means, key=lambda item: item[1])[0]]

    dom_p50 = [group_stats[name]["p50"] for name in dominant if name in group_stats]
    if dom_p50:
        median_p50 = float(np.median(np.asarray(dom_p50, dtype=np.float32)))
    else:
        median_p50 = 0.0

    threshold = max(0.015, median_p50 * 0.55)

    profile["feature_group_motion_profile"] = group_stats
    profile["dominant_feature_groups"] = dominant
    profile["dominant_group_threshold"] = round(float(threshold), 6)


def _dominant_group_gate(
    prev_feature: list[float] | None,
    feature: list[float],
    profile: dict[str, Any],
) -> float:
    if prev_feature is None:
        return 1.0
    groups = profile.get("dominant_feature_groups")
    if not isinstance(groups, list) or not groups:
        return 1.0
    threshold = float(profile.get("dominant_group_threshold", 0.0) or 0.0)
    if threshold <= 0.0:
        return 1.0

    deltas: list[float] = []
    for name in groups:
        idxs = FEATURE_GROUPS.get(str(name), [])
        if not idxs:
            continue
        total = 0.0
        count = 0
        for idx in idxs:
            if idx < len(prev_feature) and idx < len(feature):
                total += abs(float(feature[idx]) - float(prev_feature[idx]))
                count += 1
        if count:
            deltas.append(total / count)
    if not deltas:
        return 1.0

    mean_delta = sum(deltas) / max(1, len(deltas))
    gate = mean_delta / max(threshold, 1e-6)
    return _clamp(gate, 0.0, 1.0)


def _phase_signal_from_feature(feature: list[float], profile: dict[str, Any]) -> float:
    mean = [float(x) for x in profile.get("feature_mean", [])]
    pc1 = [float(x) for x in profile.get("feature_pc1", [])]
    if not mean or not pc1:
        return 0.0
    weights = _ensure_feature_weights(profile)
    n = min(len(feature), len(mean), len(pc1))
    centered = [feature[i] - (mean[i] if i < len(mean) else 0.0) for i in range(n)]
    if weights and len(weights) >= n:
        centered = [centered[i] * float(weights[i]) for i in range(n)]
        min_p = float(profile.get("weighted_proj_min", profile.get("proj_min", 0.0)))
        max_p = float(profile.get("weighted_proj_max", profile.get("proj_max", 1.0)))
    else:
        min_p = float(profile.get("proj_min", 0.0))
        max_p = float(profile.get("proj_max", 1.0))
    proj = sum(centered[i] * (pc1[i] if i < len(pc1) else 0.0) for i in range(n))
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


def _build_llm_feedback_input(
    segment: dict[str, Any],
    *,
    fitness_level: str,
    user_history_summary: str | None,
) -> dict[str, Any]:
    scoring = segment.get("scoring") if isinstance(segment.get("scoring"), dict) else {}
    ref = segment.get("reference_plane") if isinstance(segment.get("reference_plane"), dict) else {}
    joint_analyses = segment.get("joint_analyses") if isinstance(segment.get("joint_analyses"), list) else []
    rep_feedback = segment.get("rep_feedback") if isinstance(segment.get("rep_feedback"), list) else []
    top_joints: list[dict[str, Any]] = []
    for item in joint_analyses[:8]:
        if not isinstance(item, dict):
            continue
        top_joints.append(
            {
                "joint": str(item.get("joint", "")),
                "label": str(item.get("label", "")),
                "angle_delta_deg": float(item.get("angle_delta_deg", 0.0) or 0.0),
                "magnitude_deg": float(item.get("magnitude_deg", 0.0) or 0.0),
                "direction": [str(x) for x in (item.get("direction") or [])],
            }
        )
    phases: dict[str, list[dict[str, Any]]] = {"eccentric": [], "bottom": [], "concentric": []}
    for rep in rep_feedback[:4]:
        details = rep.get("details") if isinstance(rep, dict) else []
        if not isinstance(details, list):
            continue
        for d in details[:4]:
            if not isinstance(d, dict):
                continue
            phase = str(d.get("phase_hint") or "").lower()
            bucket = "concentric"
            if "xuong" in phase:
                bucket = "eccentric"
            elif "day" in phase:
                bucket = "bottom"
            phases[bucket].append(
                {
                    "joint": str(d.get("joint", "")),
                    "label": str(d.get("label", "")),
                    "phase_hint": str(d.get("phase_hint", "")),
                    "angle_delta_deg": float(d.get("angle_delta_deg", 0.0) or 0.0),
                    "magnitude_deg": float(d.get("magnitude_deg", 0.0) or 0.0),
                    "direction": [str(x) for x in (d.get("direction") or [])],
                }
            )
    return {
        "meta": {
            "exercise": str(segment.get("exercise_name", "")),
            "mode": str(segment.get("mode", "reps")),
            "language": "vi-VN",
            "fitness_level": str(fitness_level or "beginner"),
            "user_history_summary": str(user_history_summary or "").strip(),
        },
        "camera": {
            "camera_view_mismatch": bool(ref.get("camera_view_mismatch", False)),
        },
        "score": {
            "overall": float(scoring.get("overall", 0.0) or 0.0),
            "form": float(scoring.get("form_score", 0.0) or 0.0),
            "tempo": float(scoring.get("tempo_score", 0.0) or 0.0),
            "consistency": float(scoring.get("consistency_score", 0.0) or 0.0),
            "vertical_axis": float(scoring.get("vertical_axis_score", 0.0) or 0.0),
        },
        "top_issues": [str(x) for x in (scoring.get("action_items") or []) if str(x).strip()][:5],
        "top_joint_analyses": top_joints,
        "phases": phases,
    }


def _call_gemini_feedback(*, model: str, prompt_payload: dict[str, Any], temperature: float) -> dict[str, Any]:
    api_key = str(os.getenv("GEMINI_API_KEY", "")).strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="missing GEMINI_API_KEY")
    system_prompt = (
        "Bạn là huấn luyện viên kỹ thuật thể hình. Chỉ được dùng dữ liệu JSON được cung cấp. "
        "Không bịa số liệu. Trả về đúng JSON object với keys: summary, positive_reinforcement, "
        "issues_found, issues, quick_fixes, camera_note, next_session_focus. issues_found phải từ 0..3."
    )
    user_prompt = (
        "Dữ liệu phân tích segment:\n"
        f"{json.dumps(prompt_payload, ensure_ascii=False)}\n\n"
        "Nếu camera.camera_view_mismatch=true thì camera_note phải cảnh báo góc máy làm giảm độ chắc chắn "
        "đánh giá trục đứng. Viết tiếng Việt ngắn gọn, không dùng dữ liệu ngoài JSON."
    )
    body = {
        "contents": [{"role": "user", "parts": [{"text": system_prompt}]}, {"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": float(temperature), "responseMimeType": "application/json"},
    }
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    raw = ""
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read().decode("utf-8")
                last_err = None
                break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            last_err = HTTPException(status_code=502, detail=f"gemini http error: {detail[:400]}")
            # Retry on temporary unavailable / overload only.
            if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise last_err from exc
        except Exception as exc:
            last_err = HTTPException(status_code=502, detail=f"gemini call failed: {exc}")
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise last_err from exc
    if not raw:
        if isinstance(last_err, HTTPException):
            raise last_err
        raise HTTPException(status_code=502, detail="gemini call failed: empty response")
    try:
        payload = json.loads(raw)
        text = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")
        parsed = json.loads(text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"invalid gemini response: {exc}") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="invalid gemini response: expected json object")
    return parsed


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


@app.post("/v1/analysis/dtw-backtest", response_model=DTWBacktestResponse)
def dtw_backtest(payload: DTWBacktestRequest) -> DTWBacktestResponse:
    _resolve_video_path(payload.template_video_uri)
    _resolve_video_path(payload.student_video_uri)
    trim_start_sec, trim_end_sec = _validate_trim_window(
        payload.template_trim_start_sec,
        payload.template_trim_end_sec,
    )
    template_trim_start = trim_start_sec if payload.template_trim_start_sec is not None else None
    template_trim_end = trim_end_sec if payload.template_trim_end_sec is not None else None
    template_name = str(payload.template_name or "").strip() or "DTW backtest"
    try:
        profile_dict, _ = _build_profile_dict_from_video(
            mode=payload.mode,
            video_uri=payload.template_video_uri,
            trim_start_sec=template_trim_start,
            trim_end_sec=template_trim_end,
        )
        template_features = profile_dict.get("features", [])
        template_samples = profile_dict.get("pose_samples", [])
        if not isinstance(template_features, list) or not template_features:
            raise RuntimeError("template features empty")
        if not isinstance(template_samples, list):
            template_samples = []

        template = WorkoutTemplate(
            template_id=f"dtw_backtest_{uuid.uuid4()}",
            name=template_name,
            mode=payload.mode,
            video_uri=payload.template_video_uri,
            notes="ad-hoc dtw backtest",
            trim_start_sec=template_trim_start,
            trim_end_sec=template_trim_end,
        )
        segment = {
            "step_index": 0,
            "set_index": 0,
            "video_uri": payload.student_video_uri,
            "duration_seconds": 0.0,
            "observed_rep_count": payload.observed_rep_count,
        }
        analyzed = _analyze_segment(
            template=template,
            template_profile=profile_dict,
            template_features=template_features,
            template_samples=template_samples,
            segment=segment,
            render_visual_sync=bool(payload.include_visual_sync),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"cannot run dtw backtest: {exc}") from exc

    llm_feedback: dict[str, Any] | None = None
    if bool(payload.include_llm_feedback):
        try:
            prompt_payload = _build_llm_feedback_input(
                analyzed,
                fitness_level=payload.fitness_level,
                user_history_summary=payload.user_history_summary,
            )
            llm_feedback = _call_gemini_feedback(
                model=str(payload.llm_model or "gemini-flash-lite-latest"),
                prompt_payload=prompt_payload,
                temperature=float(payload.llm_temperature),
            )
        except HTTPException as exc:
            llm_feedback = {
                "summary": "Khong the tao nhan xet AI luc nay; he thong dang dung nhan xet rule-based.",
                "positive_reinforcement": [],
                "issues_found": 0,
                "issues": [],
                "quick_fixes": [],
                "camera_note": "",
                "next_session_focus": [],
                "llm_error": str(exc.detail),
            }

    return DTWBacktestResponse(
        backtest_id=str(uuid.uuid4()),
        template_video_uri=payload.template_video_uri,
        student_video_uri=payload.student_video_uri,
        result=analyzed,
        llm_feedback=llm_feedback,
    )


@app.post("/v1/analysis/llm-feedback", response_model=LLMFeedbackResponse)
def llm_feedback(payload: LLMFeedbackRequest) -> LLMFeedbackResponse:
    if not isinstance(payload.segment, dict) or not payload.segment:
        raise HTTPException(status_code=400, detail="segment is required")
    prompt_payload = _build_llm_feedback_input(
        payload.segment,
        fitness_level=payload.fitness_level,
        user_history_summary=payload.user_history_summary,
    )
    feedback = _call_gemini_feedback(
        model=str(payload.model or "gemini-flash-lite-latest"),
        prompt_payload=prompt_payload,
        temperature=float(payload.temperature),
    )
    return LLMFeedbackResponse(
        ok=True,
        model=str(payload.model or "gemini-flash-lite-latest"),
        feedback=feedback,
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
        if score < 0.1:
            continue
        if score >= 0.26:
            level = "lệch nhiều"
        elif score >= 0.17:
            level = "lệch vừa"
        else:
            level = "lệch nhẹ"

        if "tay" in label:
            feedback.append(f"{label}: {level}. Tập trung giữ trục vai-khuỷu-cổ tay ổn định và đối xứng hai bên.")
        else:
            feedback.append(f"{label}: {level}. Tập trung biên độ đều, giữ hướng khớp ổn định theo quỹ đạo mẫu.")
    if not feedback:
        feedback.append("Động tác gần với video mẫu, chưa thấy sai lệch lớn ở tay/chân.")
    return feedback


def _severity_label(magnitude_deg: float) -> str:
    mag = abs(float(magnitude_deg))
    if mag >= 30.0:
        return "cao"
    if mag >= 18.0:
        return "vừa"
    if mag >= 10.0:
        return "nhẹ"
    return "nhỏ"


def _phase_hint_from_frame(frame: dict[str, Any]) -> str:
    cycle_frames = max(1, int(frame.get("template_cycle_frames") or 1))
    cycle_idx = _clamp(float(frame.get("template_cycle_frame_index") or 0), 0.0, float(cycle_frames - 1))
    ratio = cycle_idx / max(1.0, float(cycle_frames - 1))
    if ratio < 0.2:
        return "đầu rep"
    if ratio < 0.48:
        return "pha xuống"
    if ratio < 0.62:
        return "đáy rep"
    if ratio < 0.88:
        return "pha lên"
    return "cuối rep"


def _joint_pattern_hint(joint_name: str) -> str:
    name = str(joint_name or "")
    if "knee" in name:
        return "Giữ gối cùng hướng mũi chân, tránh đổ gối vào trong."
    if "hip" in name:
        return "Siết core, giữ hông cân và tránh đẩy lệch một bên."
    if "shoulder" in name:
        return "Mở ngực, hạ vai và giữ vai không nhún."
    if "elbow" in name:
        return "Giữ khuỷu ổn định, tránh văng tay ra ngoài."
    return "Giữ khớp ổn định theo trục chuyển động mẫu."


def _direction_correction(label: str, directions: list[str]) -> list[str]:
    actions: list[str] = []
    for direction in directions:
        d = str(direction).strip().lower()
        if d == "lech trai":
            actions.append(f"đưa {label} sang phải")
        elif d == "lech phai":
            actions.append(f"đưa {label} sang trái")
        elif d == "cao hon":
            actions.append(f"hạ {label} xuống")
        elif d == "thap hon":
            actions.append(f"nâng {label} lên")
        elif d == "ra truoc hon":
            actions.append(f"đưa {label} lùi lại một chút")
        elif d == "ra sau hon":
            actions.append(f"đưa {label} ra trước một chút")
    # Keep only the first 2 concrete corrections to avoid noisy guidance.
    uniq: list[str] = []
    seen: set[str] = set()
    for action in actions:
        if action not in seen:
            uniq.append(action)
            seen.add(action)
    return uniq[:2]


def _build_segment_scoring(
    *,
    similarity: float,
    normalized_distance: float,
    joint_analyses: list[dict[str, Any]],
    rep_feedback: list[dict[str, Any]],
    camera_view_mismatch: bool = False,
) -> dict[str, Any]:
    similarity_score = _clamp(float(similarity) * 100.0, 0.0, 100.0)
    distance_penalty = _clamp(float(normalized_distance), 0.0, 4.0)
    tempo_score = _clamp(100.0 - (distance_penalty * 18.0), 0.0, 100.0)

    joint_mags = [
        abs(float(item.get("weighted_magnitude_deg") or item.get("angle_delta_deg") or 0.0))
        for item in joint_analyses
    ]
    form_p70 = _quantile(joint_mags, 0.7, default=0.0)
    form_score = _clamp(100.0 - (form_p70 * 2.1), 0.0, 100.0)

    rep_top_mags: list[float] = []
    action_items: list[str] = []
    for rep in rep_feedback:
        details = rep.get("details") or []
        if details:
            rep_top_mags.append(max(abs(float(d.get("angle_delta_deg") or 0.0)) for d in details))
        for cue in rep.get("coaching_cues") or []:
            cue_text = str(cue).strip()
            if cue_text and cue_text not in action_items:
                action_items.append(cue_text)
            if len(action_items) >= 6:
                break
        if len(action_items) >= 6:
            break

    consistency_std = float(np.std(np.asarray(rep_top_mags, dtype=np.float32))) if rep_top_mags else 0.0
    consistency_score = _clamp(100.0 - (consistency_std * 3.0), 0.0, 100.0)

    vertical_deltas = [abs(float(item.get("vertical_axis_delta_deg") or 0.0)) for item in joint_analyses]
    vertical_axis_delta_deg = _quantile(vertical_deltas, 0.5, default=0.0)
    vertical_axis_score = _clamp(100.0 - (vertical_axis_delta_deg * 2.8), 0.0, 100.0)
    if camera_view_mismatch:
        vertical_axis_score = 70.0

    overall = _clamp(
        (0.30 * similarity_score)
        + (0.28 * form_score)
        + (0.18 * consistency_score)
        + (0.14 * tempo_score)
        + (0.10 * vertical_axis_score),
        0.0,
        100.0,
    )

    grade = "A"
    if overall < 85.0:
        grade = "B"
    if overall < 72.0:
        grade = "C"
    if overall < 58.0:
        grade = "D"

    if camera_view_mismatch:
        axis_hint = (
            "Hai video đang khác góc máy rõ rệt (mẫu góc thấp/chĩa lên, student ngang người), "
            "nên chỉ số trục đứng chỉ dùng tham khảo."
        )
    elif vertical_axis_delta_deg >= 16.0:
        axis_hint = "Trục đứng giữa hai video lệch nhiều; ưu tiên đặt camera ngang hông và giữ thân người thẳng."
    elif vertical_axis_delta_deg >= 9.0:
        axis_hint = "Trục đứng còn lệch nhẹ; nên cân lại góc quay để so khớp ổn định hơn."
    else:
        axis_hint = "Trục đứng giữa hai video khá khớp."

    if camera_view_mismatch or vertical_axis_delta_deg >= 9.0:
        action_items.insert(0, axis_hint)

    return {
        "overall": round(overall, 1),
        "grade": grade,
        "similarity_score": round(similarity_score, 1),
        "form_score": round(form_score, 1),
        "consistency_score": round(consistency_score, 1),
        "tempo_score": round(tempo_score, 1),
        "vertical_axis_score": round(vertical_axis_score, 1),
        "vertical_axis_delta_deg": round(vertical_axis_delta_deg, 2),
        "camera_view_mismatch": bool(camera_view_mismatch),
        "axis_hint": axis_hint,
        "action_items": action_items[:5],
    }


def _sample_point_3d(sample: list[list[float]], idx: int) -> list[float]:
    point = sample[idx]
    if len(point) >= 7:
        return [float(point[4]), float(point[5]), float(point[6])]
    return [float(point[0]), float(point[1]), float(point[2])]


def _vec_sub(a: list[float], b: list[float]) -> list[float]:
    return [float(a[0] - b[0]), float(a[1] - b[1]), float(a[2] - b[2])]


def _vec_dot(a: list[float], b: list[float]) -> float:
    return float(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])


def _vec_norm(v: list[float]) -> float:
    return math.sqrt(_vec_dot(v, v))


def _vec_unit(v: list[float], fallback: list[float]) -> list[float]:
    n = _vec_norm(v)
    if n < 1e-6:
        return [float(fallback[0]), float(fallback[1]), float(fallback[2])]
    return [float(v[0] / n), float(v[1] / n), float(v[2] / n)]


def _vec_cross(a: list[float], b: list[float]) -> list[float]:
    return [
        float((a[1] * b[2]) - (a[2] * b[1])),
        float((a[2] * b[0]) - (a[0] * b[2])),
        float((a[0] * b[1]) - (a[1] * b[0])),
    ]


def _body_reference_frame(sample: list[list[float]]) -> dict[str, list[float]] | None:
    try:
        l_sh = _sample_point_3d(sample, int(LANDMARK_INDEX["left_shoulder"]))
        r_sh = _sample_point_3d(sample, int(LANDMARK_INDEX["right_shoulder"]))
        l_hip = _sample_point_3d(sample, int(LANDMARK_INDEX["left_hip"]))
        r_hip = _sample_point_3d(sample, int(LANDMARK_INDEX["right_hip"]))
    except Exception:
        return None

    mid_sh = [(l_sh[0] + r_sh[0]) * 0.5, (l_sh[1] + r_sh[1]) * 0.5, (l_sh[2] + r_sh[2]) * 0.5]
    mid_hip = [(l_hip[0] + r_hip[0]) * 0.5, (l_hip[1] + r_hip[1]) * 0.5, (l_hip[2] + r_hip[2]) * 0.5]
    up = _vec_unit(_vec_sub(mid_sh, mid_hip), [0.0, -1.0, 0.0])
    lateral_hint = [
        (r_sh[0] - l_sh[0]) + (r_hip[0] - l_hip[0]),
        (r_sh[1] - l_sh[1]) + (r_hip[1] - l_hip[1]),
        (r_sh[2] - l_sh[2]) + (r_hip[2] - l_hip[2]),
    ]
    right = _vec_unit(lateral_hint, [1.0, 0.0, 0.0])
    forward = _vec_unit(_vec_cross(up, right), [0.0, 0.0, 1.0])
    right = _vec_unit(_vec_cross(forward, up), right)
    return {"origin": mid_hip, "right": right, "up": up, "forward": forward}


def _project_to_body_frame(point: list[float], frame: dict[str, list[float]]) -> list[float]:
    rel = _vec_sub(point, frame["origin"])
    return [
        _vec_dot(rel, frame["right"]),
        _vec_dot(rel, frame["up"]),
        _vec_dot(rel, frame["forward"]),
    ]


def _joint_delta_in_reference(
    template_sample: list[list[float]],
    student_sample: list[list[float]],
    point_index: int,
) -> tuple[float, float, float]:
    t_point = _sample_point_3d(template_sample, point_index)
    s_point = _sample_point_3d(student_sample, point_index)
    t_frame = _body_reference_frame(template_sample)
    s_frame = _body_reference_frame(student_sample)
    if t_frame is not None and s_frame is not None:
        t_local = _project_to_body_frame(t_point, t_frame)
        s_local = _project_to_body_frame(s_point, s_frame)
        return (
            float(s_local[0] - t_local[0]),
            float(s_local[1] - t_local[1]),
            float(s_local[2] - t_local[2]),
        )
    return (
        float(s_point[0] - t_point[0]),
        float(s_point[1] - t_point[1]),
        float(s_point[2] - t_point[2]),
    )


def _vertical_axis_delta_deg(template_sample: list[list[float]], student_sample: list[list[float]]) -> float:
    t_frame = _body_reference_frame(template_sample)
    s_frame = _body_reference_frame(student_sample)
    if t_frame is None or s_frame is None:
        return 0.0

    # Use screen-plane torso tilt (x/y) as primary signal for post-analysis.
    # This is more stable than full 3D up-vector angle, which can be noisy on z.
    t_up = t_frame["up"]
    s_up = s_frame["up"]
    t_n2 = math.sqrt((t_up[0] * t_up[0]) + (t_up[1] * t_up[1]))
    s_n2 = math.sqrt((s_up[0] * s_up[0]) + (s_up[1] * s_up[1]))
    if t_n2 < 1e-6 or s_n2 < 1e-6:
        return 0.0

    t_tilt = math.degrees(math.atan2(t_up[0] / t_n2, -(t_up[1] / t_n2)))
    s_tilt = math.degrees(math.atan2(s_up[0] / s_n2, -(s_up[1] / s_n2)))
    delta = abs(s_tilt - t_tilt)
    if delta > 180.0:
        delta = 360.0 - delta
    return float(delta)


def _body_tilt_deg_2d(sample: list[list[float]]) -> float | None:
    frame = _body_reference_frame(sample)
    if frame is None:
        return None
    up = frame["up"]
    n2 = math.sqrt((up[0] * up[0]) + (up[1] * up[1]))
    if n2 < 1e-6:
        return None
    return float(math.degrees(math.atan2(up[0] / n2, -(up[1] / n2))))


def _camera_view_mismatch_from_path(
    template_samples: list[list[list[float]]],
    student_samples: list[list[list[float]]],
    path: list[tuple[int, int]],
) -> bool:
    if not path:
        return False
    tilt_diffs: list[float] = []
    for ti, si in path:
        if ti < 0 or si < 0 or ti >= len(template_samples) or si >= len(student_samples):
            continue
        t_tilt = _body_tilt_deg_2d(template_samples[ti])
        s_tilt = _body_tilt_deg_2d(student_samples[si])
        if t_tilt is None or s_tilt is None:
            continue
        d = abs(float(s_tilt - t_tilt))
        if d > 180.0:
            d = 360.0 - d
        tilt_diffs.append(float(d))
    if len(tilt_diffs) < 12:
        return False
    arr = np.asarray(tilt_diffs, dtype=np.float32)
    return bool(float(np.median(arr)) >= 18.0 and float(np.std(arr)) <= 7.0)


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
    if dx <= -0.045:
        directions.append("lech trai")
    elif dx >= 0.045:
        directions.append("lech phai")
    if dy <= -0.045:
        directions.append("cao hon")
    elif dy >= 0.045:
        directions.append("thap hon")
    if dz <= -0.09:
        directions.append("ra truoc hon")
    elif dz >= 0.09:
        directions.append("ra sau hon")
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


def _compute_teacher_joint_motion_profile(template_samples: list[list[list[float]]]) -> dict[str, dict[str, float | bool]]:
    profile: dict[str, dict[str, float | bool]] = {}
    if len(template_samples) < 3:
        return profile
    raw_motion: dict[str, float] = {}
    for spec in JOINT_ANALYSIS_SPECS:
        name = str(spec["name"])
        a, b, c = spec["points"]
        angles: list[float] = []
        for sample in template_samples:
            try:
                angles.append(float(_angle_3d(sample, a, b, c)))
            except Exception:
                continue
        if len(angles) < 3:
            raw_motion[name] = 0.0
            continue
        q10 = _quantile(angles, 0.10, default=min(angles))
        q90 = _quantile(angles, 0.90, default=max(angles))
        raw_motion[name] = max(0.0, float(q90 - q10))
    max_motion = max(raw_motion.values()) if raw_motion else 0.0
    for name, motion in raw_motion.items():
        norm = float(motion / max_motion) if max_motion > 1e-6 else 0.0
        # keep a floor so secondary joints still contribute a little
        weight = _clamp((0.25 + (0.75 * norm)), 0.25, 1.0)
        active = bool(motion >= 12.0 or norm >= 0.42)
        profile[name] = {
            "motion_deg": round(float(motion), 2),
            "weight": round(float(weight), 4),
            "active": active,
        }
    return profile


def _stabilize_frame_map(frame_map: np.ndarray, max_step: int | None = None) -> np.ndarray:
    """Reduce visible flicker by smoothing abrupt frame-index jumps."""
    if frame_map.size <= 2:
        return frame_map
    arr = np.asarray(frame_map, dtype=np.int32).copy()
    if max_step is None:
        raw_d = np.abs(np.diff(arr).astype(np.float32))
        if raw_d.size <= 0:
            max_step = 2
        else:
            q90 = float(np.quantile(raw_d, 0.90))
            max_step = int(max(2.0, min(24.0, (q90 * 1.8) + 1.0)))
    max_step = max(1, int(max_step))

    # 3-point median filter to remove 1-frame spikes.
    med = arr.copy()
    for i in range(1, len(arr) - 1):
        med[i] = int(np.median(arr[i - 1 : i + 2]))

    # Clamp per-frame jump magnitude to keep playback visually stable.
    out = med.copy()
    prev = int(out[0])
    for i in range(1, len(out)):
        cur = int(out[i])
        delta = cur - prev
        if delta > max_step:
            cur = prev + max_step
        elif delta < -max_step:
            cur = prev - max_step
        out[i] = cur
        prev = cur
    return out


def _joint_analysis(template_samples: list[list[list[float]]], student_samples: list[list[list[float]]], path: list[tuple[int, int]]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    if not path:
        return outputs

    vertical_deltas: list[float] = []
    teacher_joint_profile = _compute_teacher_joint_motion_profile(template_samples)
    for spec in JOINT_ANALYSIS_SPECS:
        a, b, c = spec["points"]
        joint_name = str(spec["name"])
        meta = teacher_joint_profile.get(joint_name, {})
        joint_weight = float(meta.get("weight", 1.0) or 1.0)
        joint_motion_deg = float(meta.get("motion_deg", 0.0) or 0.0)
        joint_active = bool(meta.get("active", True))
        angle_deltas: list[float] = []
        dx_values: list[float] = []
        dy_values: list[float] = []
        dz_values: list[float] = []
        for ti, si in path:
            template_sample = template_samples[ti]
            student_sample = student_samples[si]
            angle_deltas.append(_angle_3d(student_sample, a, b, c) - _angle_3d(template_sample, a, b, c))
            dx, dy, dz = _joint_delta_in_reference(template_sample, student_sample, b)
            dx_values.append(dx)
            dy_values.append(dy)
            dz_values.append(dz)
            vertical_deltas.append(_vertical_axis_delta_deg(template_sample, student_sample))

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
                "weighted_magnitude_deg": round(abs(angle_delta) * joint_weight, 2),
                "teacher_motion_deg": round(joint_motion_deg, 2),
                "teacher_joint_active": joint_active,
                "joint_weight": round(joint_weight, 4),
                "direction": _direction_labels(dx, dy, dz),
                "position_delta": {
                    "x": round(dx, 4),
                    "y": round(dy, 4),
                    "z": round(dz, 4),
                },
                "reference_frame": "body_vertical",
            }
        )

    if outputs:
        vertical_mean = sum(vertical_deltas) / max(1, len(vertical_deltas))
        for item in outputs:
            item["vertical_axis_delta_deg"] = round(float(vertical_mean), 2)

    outputs.sort(key=lambda item: float(item.get("weighted_magnitude_deg", item["magnitude_deg"])), reverse=True)
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

    weights = _ensure_feature_weights(profile)
    n = min(len(feature), len(mean), len(pc1))
    centered = [feature[i] - (mean[i] if i < len(mean) else 0.0) for i in range(n)]
    if weights and len(weights) >= n:
        centered = [centered[i] * float(weights[i]) for i in range(n)]
        min_p = float(profile.get("weighted_proj_min", profile.get("proj_min", 0.0)))
        max_p = float(profile.get("weighted_proj_max", profile.get("proj_max", 1.0)))
    else:
        min_p = float(profile.get("proj_min", 0.0))
        max_p = float(profile.get("proj_max", 1.0))
    proj = sum(centered[i] * (pc1[i] if i < len(pc1) else 0.0) for i in range(n))
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
    prev_feature: list[float] | None = None
    current_rep = 1
    indices: list[int | None] = []
    for i, feature in enumerate(student_features):
        signal_raw, _ = _signal_and_similarity(feature, profile)
        gate = _dominant_group_gate(prev_feature, feature, profile)
        signal = normalizer.normalize(signal_raw * gate)
        before = rep_counter.rep_count
        rep_counter.update(signal, timestamp_ms=i * 100)
        after = rep_counter.rep_count
        indices.append(current_rep)
        if after > before:
            current_rep = after + 1
        prev_feature = feature
    return indices


def _estimate_student_reps(student_features: list[list[float]], profile: dict[str, Any], mode: str) -> int:
    if mode != "reps":
        return 1
    rep_counter = RepCounter(config=_profile_rep_counter_config(profile))
    normalizer = SignalNormalizer()
    prev_feature: list[float] | None = None
    for i, feature in enumerate(student_features):
        signal_raw, _ = _signal_and_similarity(feature, profile)
        gate = _dominant_group_gate(prev_feature, feature, profile)
        signal = normalizer.normalize(signal_raw * gate)
        rep_counter.update(signal, timestamp_ms=i * 100)
        prev_feature = feature
    estimated = max(1, int(rep_counter.rep_count))

    # Fallback: derive rep count from valleys when counter is too conservative.
    if estimated <= 1 and student_features:
        signals: list[float] = []
        normalizer2 = SignalNormalizer()
        prev_feature = None
        for feature in student_features:
            raw, _ = _signal_and_similarity(feature, profile)
            gate = _dominant_group_gate(prev_feature, feature, profile)
            signals.append(normalizer2.normalize(raw * gate))
            prev_feature = feature
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


def _phase_signal_series(features: list[list[float]], profile: dict[str, Any], mode: str) -> list[float]:
    if not features:
        return []
    normalizer = SignalNormalizer()
    raw_signals: list[float] = []
    for feature in features:
        signal_raw, _ = _signal_and_similarity(feature, profile)
        raw_signals.append(normalizer.normalize(signal_raw))

    # Match frontend live logic: keep rest/start at low signal, deep posture at high signal.
    if mode != "hold" and raw_signals and raw_signals[0] > 0.55:
        return [1.0 - s for s in raw_signals]
    return raw_signals


def _feature_step_distance(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n <= 0:
        return 0.0
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(n)))


def _compress_rep_indices(rep_features: list[list[float]], rep_signals: list[float]) -> list[int]:
    n = len(rep_features)
    if n <= 4:
        return list(range(n))

    keep: set[int] = {0, n - 1}
    if rep_signals:
        keep.add(int(np.argmax(np.asarray(rep_signals, dtype=np.float32))))
        keep.add(int(np.argmin(np.asarray(rep_signals, dtype=np.float32))))

    for i in range(1, n - 1):
        curr = rep_signals[i] if i < len(rep_signals) else 0.0
        prev = rep_signals[i - 1] if (i - 1) < len(rep_signals) else curr
        nxt = rep_signals[i + 1] if (i + 1) < len(rep_signals) else curr
        if (curr >= prev and curr >= nxt) or (curr <= prev and curr <= nxt):
            keep.add(i)

    diffs = [_feature_step_distance(rep_features[i], rep_features[i - 1]) for i in range(1, n)]
    if diffs:
        diff_arr = np.asarray(diffs, dtype=np.float32)
        low_motion_thr = max(1e-5, float(np.quantile(diff_arr, 0.35)) * 0.45)
        for i, d in enumerate(diffs, start=1):
            if d >= low_motion_thr:
                keep.add(i - 1)
                keep.add(i)

    sorted_keep = sorted(keep)
    densified: list[int] = [sorted_keep[0]]
    max_gap = 6
    for idx in sorted_keep[1:]:
        prev = densified[-1]
        if (idx - prev) > max_gap:
            step = max_gap
            for j in range(prev + step, idx, step):
                densified.append(j)
        densified.append(idx)
    return densified


def _safe_dtw(template_seq: list[list[float]], student_seq: list[list[float]]):
    length_gap = abs(len(template_seq) - len(student_seq))
    window = max(length_gap + 2, max(6, max(len(template_seq), len(student_seq)) // 4))
    res = dtw_distance(template_seq, student_seq, window=window)
    if not np.isfinite(res.normalized_distance):
        res = dtw_distance(template_seq, student_seq, window=None)
    return res


def _peak_anchored_dtw_path(
    template_seq: list[list[float]],
    student_seq: list[list[float]],
    template_peak_idx: int,
    student_peak_idx: int,
) -> tuple[float, float, list[tuple[int, int]]]:
    t_len = len(template_seq)
    s_len = len(student_seq)
    if t_len <= 0 or s_len <= 0:
        return 0.0, 0.0, []

    t_peak = max(0, min(int(template_peak_idx), t_len - 1))
    s_peak = max(0, min(int(student_peak_idx), s_len - 1))
    if t_peak <= 0 or t_peak >= (t_len - 1) or s_peak <= 0 or s_peak >= (s_len - 1):
        res = _safe_dtw(template_seq, student_seq)
        return float(res.distance), float(res.normalized_distance), list(res.path)

    left_res = _safe_dtw(template_seq[: t_peak + 1], student_seq[: s_peak + 1])
    right_res = _safe_dtw(template_seq[t_peak:], student_seq[s_peak:])
    if not np.isfinite(left_res.normalized_distance) or not np.isfinite(right_res.normalized_distance):
        res = _safe_dtw(template_seq, student_seq)
        return float(res.distance), float(res.normalized_distance), list(res.path)

    left_path = list(left_res.path)
    right_path = [(t_peak + t_idx, s_peak + s_idx) for t_idx, s_idx in right_res.path]
    if left_path and right_path and left_path[-1] == right_path[0]:
        merged_path = left_path + right_path[1:]
    else:
        merged_path = left_path + right_path

    if not merged_path:
        res = _safe_dtw(template_seq, student_seq)
        return float(res.distance), float(res.normalized_distance), list(res.path)

    distance = float(left_res.distance) + float(right_res.distance)
    normalized = distance / max(1, len(merged_path))
    return distance, normalized, merged_path


def _student_rep_indices_from_windows(length: int, windows: list[tuple[int, int]]) -> list[int | None]:
    if length <= 0:
        return []
    # Frames outside detected rep windows are pre/post-roll, keep them unassigned.
    out: list[int | None] = [0 for _ in range(length)]
    if not windows:
        return out
    for rep_idx, (start, end) in enumerate(windows, start=1):
        s = max(0, min(int(start), length - 1))
        e = max(s, min(int(end), length - 1))
        for i in range(s, e + 1):
            out[i] = rep_idx
    return out


def _normalize_rep_windows_count(
    windows: list[tuple[int, int]],
    expected_reps: int,
    length: int,
) -> list[tuple[int, int]]:
    if length <= 0:
        return []
    expected = max(1, int(expected_reps or 1))
    cleaned = [
        (
            max(0, min(int(s), length - 1)),
            max(0, min(int(e), length - 1)),
        )
        for s, e in windows
    ]
    cleaned = [(s, e if e >= s else s) for s, e in cleaned]
    if not cleaned:
        return [(0, length - 1)]
    cleaned.sort(key=lambda item: item[0])

    if len(cleaned) > expected:
        kept = cleaned[: expected - 1]
        tail_start = cleaned[expected - 1][0]
        tail_end = max(e for _, e in cleaned[expected - 1 :])
        cleaned = kept + [(tail_start, tail_end)]
    elif len(cleaned) < expected:
        while len(cleaned) < expected:
            longest_idx = int(np.argmax([max(0, e - s) for s, e in cleaned]))
            s, e = cleaned[longest_idx]
            if (e - s) < 8:
                break
            mid = int(round((s + e) * 0.5))
            left = (s, max(s, mid - 1))
            right = (min(e, mid), e)
            cleaned = cleaned[:longest_idx] + [left, right] + cleaned[longest_idx + 1 :]
            cleaned.sort(key=lambda item: item[0])

    return cleaned[:expected] if len(cleaned) >= expected else cleaned


def _build_reps_alignment(
    *,
    template_profile: dict[str, Any],
    template_features: list[list[float]],
    template_samples: list[list[list[float]]],
    student_features: list[list[float]],
    effective_rep_target: int,
) -> dict[str, Any]:
    single_rep_features = template_profile.get("single_rep_features")
    single_rep_samples = template_profile.get("single_rep_samples")
    if not isinstance(single_rep_features, list) or not single_rep_features:
        single_rep_features = template_features
    if not isinstance(single_rep_samples, list) or len(single_rep_samples) != len(single_rep_features):
        single_rep_samples = template_samples[: len(single_rep_features)] if template_samples else []
    if not single_rep_features:
        return {
            "expanded_template_features": template_features,
            "expanded_template_samples": template_samples,
            "template_cycles": 1,
            "student_rep_indices": _student_rep_indices_from_windows(len(student_features), []),
            "distance": 0.0,
            "normalized_distance": 0.0,
            "path": [],
            "rep_windows": [],
        }

    template_signals = _phase_signal_series(single_rep_features, template_profile, "reps")
    student_signals = _phase_signal_series(student_features, template_profile, "reps")

    expected = max(1, int(effective_rep_target or 1))
    min_rep_frames = max(6, int(len(single_rep_features) * 0.45))
    candidate_windows: list[list[tuple[int, int]]] = []
    if expected > 1:
        candidate_windows.append(
            _rep_windows_from_mse_signal(np.asarray(student_signals, dtype=np.float32), expected_reps=expected)
        )
    candidate_windows.append(segment_by_signal_valleys(student_signals, min_rep_frames=min_rep_frames))
    candidate_windows.append([(0, max(0, len(student_features) - 1))])

    template_peak_idx = int(np.argmax(np.asarray(template_signals, dtype=np.float32))) if template_signals else max(0, len(single_rep_features) // 2)

    def _align_with_windows(rep_windows_input: list[tuple[int, int]]) -> dict[str, Any]:
        rep_windows = _normalize_rep_windows_count(rep_windows_input, expected, len(student_features))
        expanded_template_features: list[list[float]] = []
        expanded_template_samples: list[list[list[float]]] = []
        global_path: list[tuple[int, int]] = []
        total_distance = 0.0

        for rep_idx, (start, end) in enumerate(rep_windows):
            rep_features_raw = student_features[start : end + 1]
            rep_signals_raw = student_signals[start : end + 1]
            if not rep_features_raw:
                continue

            keep_local_idx = _compress_rep_indices(rep_features_raw, rep_signals_raw)
            rep_features = [rep_features_raw[i] for i in keep_local_idx]
            if not rep_features:
                continue

            student_peak_raw = int(np.argmax(np.asarray(rep_signals_raw, dtype=np.float32))) if rep_signals_raw else max(0, len(rep_features_raw) // 2)
            student_peak_idx = min(range(len(keep_local_idx)), key=lambda i: abs(keep_local_idx[i] - student_peak_raw))

            rep_distance, _, rep_path = _peak_anchored_dtw_path(
                single_rep_features,
                rep_features,
                template_peak_idx=template_peak_idx,
                student_peak_idx=student_peak_idx,
            )

            template_offset = rep_idx * len(single_rep_features)
            for t_local, s_local in rep_path:
                if s_local < 0 or s_local >= len(keep_local_idx):
                    continue
                s_global = start + keep_local_idx[s_local]
                t_global = template_offset + int(t_local)
                if 0 <= s_global < len(student_features):
                    global_path.append((t_global, s_global))

            total_distance += float(rep_distance)
            expanded_template_features.extend(single_rep_features)
            if single_rep_samples:
                expanded_template_samples.extend(single_rep_samples)

        if not expanded_template_features:
            expanded_template_features = template_features
            expanded_template_samples = template_samples

        normalized = float(total_distance / max(1, len(global_path)))
        return {
            "expanded_template_features": expanded_template_features,
            "expanded_template_samples": expanded_template_samples,
            "template_cycles": max(1, len(rep_windows)),
            "student_rep_indices": _student_rep_indices_from_windows(len(student_features), rep_windows),
            "distance": float(total_distance),
            "normalized_distance": normalized,
            "path": global_path,
            "rep_windows": rep_windows,
        }

    best: dict[str, Any] | None = None
    seen_signatures: set[tuple[tuple[int, int], ...]] = set()
    for windows in candidate_windows:
        normalized_windows = _normalize_rep_windows_count(windows, expected, len(student_features))
        sig = tuple((int(s), int(e)) for s, e in normalized_windows)
        if sig in seen_signatures:
            continue
        seen_signatures.add(sig)
        result = _align_with_windows(normalized_windows)
        score = float(result.get("normalized_distance", float("inf")))
        path_len = len(result.get("path", []))
        if path_len <= 0 or not np.isfinite(score):
            continue
        if best is None or score < float(best["normalized_distance"]):
            best = result

    if best is None:
        best = _align_with_windows([(0, max(0, len(student_features) - 1))])
        if not np.isfinite(float(best.get("normalized_distance", float("inf")))):
            best["normalized_distance"] = 0.0

    return {
        "expanded_template_features": best["expanded_template_features"],
        "expanded_template_samples": best["expanded_template_samples"],
        "template_cycles": int(best["template_cycles"]),
        "student_rep_indices": best["student_rep_indices"],
        "distance": float(best["distance"]),
        "normalized_distance": float(best["normalized_distance"]),
        "path": best["path"],
        "rep_windows": best["rep_windows"],
    }


def _frame_joint_errors(template_sample: list[list[float]], student_sample: list[list[float]]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    vertical_delta = _vertical_axis_delta_deg(template_sample, student_sample)
    for spec in JOINT_ANALYSIS_SPECS:
        a, b, c = spec["points"]
        angle_delta = _angle_3d(student_sample, a, b, c) - _angle_3d(template_sample, a, b, c)
        dx, dy, dz = _joint_delta_in_reference(template_sample, student_sample, b)
        outputs.append(
            {
                "joint": spec["name"],
                "label": spec["label"],
                "point_index": b,
                "angle_delta_deg": round(angle_delta, 2),
                "magnitude_deg": round(abs(angle_delta), 2),
                "direction": _direction_labels(dx, dy, dz),
                "highlight": abs(angle_delta) >= 12.0,
                "vertical_axis_delta_deg": round(float(vertical_delta), 2),
                "reference_frame": "body_vertical",
            }
        )

    outputs.sort(key=lambda item: float(item["magnitude_deg"]), reverse=True)
    return outputs


def _rep_feedback_entries(
    exercise_name: str,
    set_index: int,
    mode: str,
    frame_analyses: list[dict[str, Any]],
    active_joints: set[str] | None = None,
) -> list[dict[str, Any]]:
    use_active_filter = bool(active_joints)
    if mode != "reps":
        worst = sorted(
            (
                (joint, frame)
                for frame in frame_analyses
                for joint in frame["joint_errors"]
                if (not use_active_filter) or (str(joint.get("joint", "")) in active_joints)
                if float(joint["magnitude_deg"]) >= 10.0
            ),
            key=lambda item: float(item[0]["magnitude_deg"]),
            reverse=True,
        )[:6]
        details = [joint for joint, _ in worst]
        cues: list[str] = []
        texts: list[str] = []
        for joint, frame in worst:
            phase = _phase_hint_from_frame(frame)
            severity = _severity_label(float(joint["magnitude_deg"]))
            actions = _direction_correction(str(joint["label"]), list(joint["direction"]))
            core_hint = _joint_pattern_hint(str(joint["joint"]))
            action_text = "; ".join(actions) if actions else "giữ đúng trục khớp theo video mẫu"
            cue = f"{joint['label']} ({phase}): {action_text}. {core_hint}"
            if cue not in cues:
                cues.append(cue)
            texts.append(
                f"{exercise_name} set {set_index + 1}: {joint['label']} lệch {joint['angle_delta_deg']}° ({severity}, {phase}). "
                f"Sửa: {action_text}. {core_hint}"
            )
        if not texts:
            texts = [f"{exercise_name} set {set_index + 1}: động tác ổn định, chưa thấy sai lệch lớn."]
        return [
            {
                "exercise_name": exercise_name,
                "set_index": set_index,
                "rep_index": None,
                "details": details,
                "coaching_cues": cues[:4],
                "text": texts[:6],
            }
        ]

    per_rep: dict[int, dict[str, dict[str, Any]]] = {}
    for frame in frame_analyses:
        rep_index = frame.get("rep_index")
        if rep_index is None:
            continue
        phase_hint = _phase_hint_from_frame(frame)
        bucket = per_rep.setdefault(int(rep_index), {})
        for joint in frame["joint_errors"]:
            if use_active_filter and str(joint.get("joint", "")) not in active_joints:
                continue
            existing = bucket.get(str(joint["joint"]))
            if existing is None or float(joint["magnitude_deg"]) > float(existing["magnitude_deg"]):
                updated = dict(joint)
                updated["phase_hint"] = phase_hint
                bucket[str(joint["joint"])] = updated

    entries: list[dict[str, Any]] = []
    for rep_index in sorted(per_rep):
        top = sorted(per_rep[rep_index].values(), key=lambda item: float(item["magnitude_deg"]), reverse=True)[:6]
        text: list[str] = []
        coaching_cues: list[str] = []
        for item in top:
            mag = float(item["magnitude_deg"])
            if mag < 10.0:
                continue
            phase = str(item.get("phase_hint") or "giữa rep")
            severity = _severity_label(mag)
            actions = _direction_correction(str(item["label"]), list(item["direction"]))
            core_hint = _joint_pattern_hint(str(item["joint"]))
            action_text = "; ".join(actions) if actions else "giữ đúng trục khớp theo video mẫu"
            text.append(
                f"{exercise_name} set {set_index + 1} rep {rep_index} ({phase}): {item['label']} lệch {item['angle_delta_deg']}° ({severity}). "
                f"Sửa: {action_text}. {core_hint}"
            )
            cue = f"Rep {rep_index} - {item['label']} ({phase}): {action_text}. {core_hint}"
            if cue not in coaching_cues:
                coaching_cues.append(cue)
        if not text:
            text = [f"{exercise_name} set {set_index + 1} rep {rep_index}: động tác ổn định, chưa thấy sai lệch lớn."]
        entries.append(
            {
                "exercise_name": exercise_name,
                "set_index": set_index,
                "rep_index": rep_index,
                "details": top,
                "coaching_cues": coaching_cues[:3],
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
    _ensure_feature_weights(profile_seed)
    _compute_feature_group_motion_profile(profile_seed)

    rep_cycle_info = detect_rep_cycles(
        features=profile.features,
        samples=pose_samples,
        mode=mode,
    )

    anchor_bank = _build_anchor_pose_bank(pose_samples)
    if pose_samples:
        anchor_bank = [pose_samples[0]]
    adaptive_thresholds = _build_adaptive_thresholds(profile_seed, mode)
    signal_cfg = adaptive_thresholds.get("signal", {}) if isinstance(adaptive_thresholds, dict) else {}

    profile_dict = {
        **profile_seed,
        "anchor_pose_sample": (pose_samples[0] if pose_samples else None),
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
        profile_dict, samples = _build_profile_dict_from_video(
            mode=mode,
            video_uri=frozen_video_uri,
            trim_start_sec=None,
            trim_end_sec=None,
            frozen_meta=frozen_meta,
        )
    except Exception:
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
    _ = template_id
    return None, None


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
        try:
            _resolve_video_path(t.video_uri)
        except Exception:
            continue
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

# (duplicate smooth_signal/get_mse_signal/keyframe_align removed – kept first copy above)


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
    template_profile: dict[str, Any] | None = None,
) -> str | None:
    """Render sync using pose-based PCA phase signal with multi-anchor alignment.

    Improvements over the old MSE pixel approach:
      - Uses PCA phase signal (from template profile) instead of pixel MSE
      - Anchors sync at both peaks (deepest rep point) AND valleys (rest position)
      - Detects rest segments and freezes teacher during student rest
      - Falls back to MSE-based alignment if pose features are unavailable
    """
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
        n_teacher = len(teacher_frames)
        n_student = len(student_frames)
        # --- Pose-based sync (preferred) ---
        use_pose_sync = (
            template_profile is not None
            and template_samples
            and student_samples
            and len(template_samples) >= 3
            and len(student_samples) >= 3
        )

        if use_pose_sync:
            student_feats = features_from_samples(student_samples)
            teacher_feats = features_from_samples(template_samples)
            sync_result = build_sync_mapping(
                student_features=student_feats,
                teacher_features=teacher_feats,
                profile=template_profile,
                expected_reps=expected_reps,
                student_rep_indices=student_rep_indices,
            )
            # Map from sample-space to frame-space
            sample_teacher_map = sync_result["teacher_map"]
            sample_frame_rep = sync_result["frame_rep"]
            sample_frame_phase = sync_result["frame_phase"]
            rest_segments = sync_result.get("rest_segments", [])

            # Interpolate sample-space mapping to frame-space
            s_sample_count = len(student_samples)
            t_sample_count = len(template_samples)
            teacher_map = np.zeros(n_student, dtype=np.int32)
            frame_phase = np.zeros(n_student, dtype=np.float32)
            frame_rep = np.zeros(n_student, dtype=np.int32)

            for i in range(n_student):
                sample_idx = int(round(i * max(0, s_sample_count - 1) / max(1, n_student - 1)))
                sample_idx = max(0, min(sample_idx, s_sample_count - 1))
                t_sample_idx = int(sample_teacher_map[sample_idx])
                t_frame = int(round(t_sample_idx * max(0, n_teacher - 1) / max(1, t_sample_count - 1)))
                teacher_map[i] = max(0, min(t_frame, n_teacher - 1))
                frame_phase[i] = float(sample_frame_phase[sample_idx])
                frame_rep[i] = int(sample_frame_rep[sample_idx])
            teacher_map = _stabilize_frame_map(teacher_map, max_step=2)

            # Determine render range from rep windows
            rep_windows = sync_result.get("rep_windows", [(0, s_sample_count - 1)])
            if rep_windows:
                first_sample = rep_windows[0][0]
                last_sample = rep_windows[-1][1]
                render_start = max(0, int(round(first_sample * (n_student - 1) / max(1, s_sample_count - 1))))
                render_end = min(n_student - 1, int(round(last_sample * (n_student - 1) / max(1, s_sample_count - 1))))
            else:
                render_start, render_end = 0, n_student - 1

            print(f"[render_sync] Pose-based sync: {len(student_feats)} student feats, "
                  f"{len(teacher_feats)} teacher feats, {len(rest_segments)} rest segments, "
                  f"{len(rep_windows)} rep windows")
        else:
            # --- MSE fallback ---
            print("[render_sync] Falling back to MSE-based sync (no pose features)")
            student_signal_full = get_mse_signal(student_frames, smooth_window=5)
            teacher_signal_full = get_mse_signal(teacher_frames, smooth_window=5)
            if teacher_signal_full.size == 0:
                raise RuntimeError("teacher mse signal empty")

            mse_rep_windows = _rep_windows_from_mse_signal(student_signal_full, expected_reps=expected_reps)
            if not mse_rep_windows:
                mse_rep_windows = [(0, n_student - 1)]

            teacher_map = np.round(np.linspace(0, max(0, n_teacher - 1), n_student)).astype(np.int32)
            frame_phase = np.zeros(n_student, dtype=np.float32)
            frame_rep = np.zeros(n_student, dtype=np.int32)

            for rep_idx, (start_f, end_f) in enumerate(mse_rep_windows, start=1):
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
                    if 0 <= g_idx < n_student:
                        t_idx = max(0, min(int(rep_map[local_i]), n_teacher - 1))
                        teacher_map[g_idx] = t_idx
                        frame_phase[g_idx] = t_idx / max(1, n_teacher - 1)
                        frame_rep[g_idx] = rep_idx
            teacher_map = _stabilize_frame_map(teacher_map, max_step=2)

            render_start = max(0, mse_rep_windows[0][0])
            render_end = min(n_student - 1, mse_rep_windows[-1][1])

        if render_end <= render_start:
            render_start = 0
            render_end = n_student - 1

        canvas_h = 640
        sample_s = resize_keep_aspect(student_frames[render_start], canvas_h)
        sample_t = resize_keep_aspect(teacher_frames[0], canvas_h)
        sw = max(1, int(sample_s.shape[1]))
        tw = max(1, int(sample_t.shape[1]))
        # Keep 50/50 split: both panels share the same fixed width.
        panel_w = max(sw, tw)
        divider_thickness = 4
        canvas_w = (panel_w * 2) + divider_thickness
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

                s_panel = _resize_pad(student_frames[i], panel_w, canvas_h)
                t_panel = _resize_pad(teacher_frames[t_idx], panel_w, canvas_h)

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
        print(f"[render_sync] sync build failed: {e}")
        with open(ANALYSIS_DIR / "dtw_error.txt", "w") as f:
            traceback.print_exc(file=f)
        traceback.print_exc()
        return None

    try:
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-i", str(temp_path),
                "-vcodec", "libx264", "-pix_fmt", "yuv420p",
                "-preset", "fast", "-crf", "23",
                "-movflags", "+faststart",
                "-an",
                "-r", str(int(round(fps))),
                str(out_path)
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        if temp_path.exists():
            temp_path.unlink()
        # Guard: only return comparison URI when output video is actually readable.
        cap = cv2.VideoCapture(str(out_path))
        ok, _ = cap.read()
        cap.release()
        if not ok:
            out_path.unlink(missing_ok=True)
            return None
    except Exception as e:
        print(f"[render_sync] FFmpeg error: {e}")
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)
        return None

    return f"/uploads/analysis_sync/{out_name}"


def _render_backtest_sync_video_dtw(
    *,
    template_video_uri: str,
    student_video_uri: str,
    expected_reps: int | None = None,
    teacher_samples: list[list[list[float]]] | None = None,
    student_samples: list[list[list[float]]] | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    teacher_path = _resolve_video_path(template_video_uri)
    student_path = _resolve_video_path(student_video_uri)
    if not teacher_path.exists() or not student_path.exists():
        return None, {"error": "missing template/student video"}

    out_name = f"analysis_sync_backtest_{uuid.uuid4()}.mp4"
    out_path = ANALYSIS_DIR / out_name
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    started_at = time.perf_counter()

    try:
        from dtw_standalone.main_pipeline import run_backtest
        # We ignore pre-extracted samples and let the standalone pipeline do its full job
        _, stats = run_backtest(str(teacher_path), str(student_path), str(out_path))
        
        cap = cv2.VideoCapture(str(out_path))
        ok, _ = cap.read()
        cap.release()
        if not ok:
            out_path.unlink(missing_ok=True)
            return None, {"error": "rendered video unreadable"}

        out_stats = dict(stats) if isinstance(stats, dict) else {}
        out_stats["render_ms"] = int((time.perf_counter() - started_at) * 1000)
        return f"/uploads/analysis_sync/{out_name}", out_stats
    except Exception as exc:
        out_path.unlink(missing_ok=True)
        return None, {
            "error": str(exc),
            "render_ms": int((time.perf_counter() - started_at) * 1000),
        }



def _analyze_segment(
    template: WorkoutTemplate,
    template_profile: dict[str, Any],
    template_features: list[list[float]],
    template_samples: list[list[list[float]]],
    segment: dict[str, Any],
    render_visual_sync: bool = True,
) -> dict[str, Any]:
    segment_started_at = time.perf_counter()
    video_path = _resolve_video_path(str(segment["video_uri"]))

    student_samples = _extract_video_pose_samples_fast(str(video_path), flip_h=False)
    student_features = features_from_samples(student_samples)
    if not isinstance(student_features, list):
        student_features = []

    summary = DTW_ANALYSIS_ADAPTER.run(
        template_features=template_features,
        student_features=student_features,
        expected_reps=(int(segment.get("observed_rep_count") or 0) or None),
    )

    result = build_clean_segment_result(
        template_id=template.template_id,
        exercise_name=template.name,
        mode=template.mode,
        segment=segment,
        summary=summary,
    )
    result["template_video_uri"] = template.video_uri
    result["samples"] = int(len(student_features))
    comparison_video_uri: str | None = None
    sync_video_stats: dict[str, Any] | None = None
    render_started_at = time.perf_counter()
    if render_visual_sync:
        rep_target = 1
        if template.mode == "reps":
            rep_target = int(segment.get("observed_rep_count") or summary.estimated_reps or 1)
        comparison_video_uri, sync_video_stats = _render_backtest_sync_video_dtw(
            template_video_uri=template.video_uri,
            student_video_uri=str(segment["video_uri"]),
            expected_reps=rep_target if rep_target > 0 else None,
            teacher_samples=template_samples,
            student_samples=student_samples,
        )
    render_comparison_ms = int((time.perf_counter() - render_started_at) * 1000)

    comparison_video_generated = bool(comparison_video_uri)
    comparison_video_source = "sync_video_dtw" if comparison_video_generated else (
        "disabled" if not render_visual_sync else "source_video_fallback"
    )
    if not comparison_video_uri:
        comparison_video_uri = str(segment["video_uri"])

    result["comparison_video_uri"] = comparison_video_uri
    result["comparison_video_generated"] = comparison_video_generated
    result["comparison_video_source"] = comparison_video_source
    result["sync_video_stats"] = sync_video_stats or {}
    result["timing_ms"]["render_comparison_video"] = render_comparison_ms
    result["timing_ms"]["total"] = int((time.perf_counter() - segment_started_at) * 1000)

    return result


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

            if template.mode == "reps" and not segment.get("observed_rep_count"):
                reps_per_set = getattr(step, "reps_per_set", None)
                if reps_per_set is not None:
                    segment["observed_rep_count"] = int(reps_per_set)

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
