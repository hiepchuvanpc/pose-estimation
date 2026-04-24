from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel, Field


class KeypointModel(BaseModel):
    x: float
    y: float
    score: float = Field(ge=0.0, le=1.0)


class FrameModel(BaseModel):
    keypoints: dict[str, KeypointModel]
    frame_width: int | None = Field(default=None, gt=0)
    frame_height: int | None = Field(default=None, gt=0)


class ReadinessParamsModel(BaseModel):
    alpha: float = 0.4
    beta: float = 0.4
    gamma: float = 0.2
    tau_rho: float = 0.25
    tau_center: float = 0.25
    min_keypoint_score: float = 0.2
    min_readiness: float = 0.7
    min_completeness: float = 0.75


class ReadinessRequest(BaseModel):
    teacher_frame: FrameModel
    student_frame: FrameModel
    params: ReadinessParamsModel = ReadinessParamsModel()


class ReadinessResponse(BaseModel):
    readiness: float
    view_score: float
    completeness_score: float
    framing_score: float
    gate_passed: bool
    feedback: list[str]


class DTWParams(BaseModel):
    """Parameters for DTW alignment with Sakoe-Chiba band constraint."""
    window: int | None = Field(
        default=20,
        ge=0,
        le=100,
        description="Window size for DTW Sakoe-Chiba band constraint. "
                    "If None, no constraint (full matrix). "
                    "Smaller values = faster but more constrained alignment."
    )


class AlignRequest(BaseModel):
    teacher_frames: list[FrameModel]
    student_frames: list[FrameModel]
    dtw_params: DTWParams = DTWParams()


class AlignResponse(BaseModel):
    distance: float
    normalized_distance: float
    path_length: int


class HealthResponse(BaseModel):
    status: str


TrackMode = Literal["reps", "hold"]


class ExerciseSpecModel(BaseModel):
    name: str
    mode: TrackMode
    target_reps: int | None = Field(default=None, ge=1)
    target_seconds: float | None = Field(default=None, ge=0.1)


class LiveSessionStartRequest(BaseModel):
    exercises: list[ExerciseSpecModel] = Field(min_length=1)


class LiveSessionStartResponse(BaseModel):
    session_id: str
    current_exercise: str
    done: bool


class LiveSessionFrameRequest(BaseModel):
    session_id: str
    signal: float = Field(ge=0.0, le=1.0)
    timestamp_ms: int = Field(ge=0)


class LiveSessionFrameResponse(BaseModel):
    session_id: str
    exercise_name: str | None
    mode: TrackMode | None
    rep_count: int
    hold_seconds: float
    exercise_completed: bool
    next_exercise: str | None
    done: bool


class TemplateCreateRequest(BaseModel):
    name: str
    mode: TrackMode
    video_uri: str
    notes: str | None = None
    trim_start_sec: float | None = Field(default=None, ge=0.0)
    trim_end_sec: float | None = Field(default=None, ge=0.0)


class TemplateUpdateRequest(BaseModel):
    name: str | None = None
    mode: TrackMode | None = None
    video_uri: str | None = None
    notes: str | None = None
    trim_start_sec: float | None = Field(default=None, ge=0.0)
    trim_end_sec: float | None = Field(default=None, ge=0.0)


class TemplateItem(BaseModel):
    template_id: str
    name: str
    mode: TrackMode
    video_uri: str
    notes: str | None = None
    trim_start_sec: float | None = None
    trim_end_sec: float | None = None
    debug_overlay_video_uri: str | None = None
    pose_timeline_json_uri: str | None = None


class TemplateListResponse(BaseModel):
    items: list[TemplateItem]


class DeleteResponse(BaseModel):
    ok: bool
    message: str


class VideoUploadResponse(BaseModel):
    video_uri: str
    original_name: str


class TemplateProfileResponse(BaseModel):
    template_id: str
    ready: bool
    samples: int
    profile: dict[str, Any]


class WorkoutStepModel(BaseModel):
    template_id: str
    sets: int = Field(default=1, ge=1)
    reps_per_set: int | None = Field(default=None, ge=1)
    hold_seconds_per_set: float | None = Field(default=None, ge=0.1)
    rest_seconds_between_sets: int = Field(default=0, ge=0)


class WorkoutSessionStartRequest(BaseModel):
    steps: list[WorkoutStepModel] = Field(min_length=1)
    speak_enabled: bool = False


class WorkoutSessionStartResponse(BaseModel):
    session_id: str
    phase: str
    exercise_name: str | None
    announcements: list[str]


class WorkoutFrameRequest(BaseModel):
    session_id: str
    signal: float = Field(ge=0.0, le=1.0)
    timestamp_ms: int = Field(ge=0)
    readiness_passed: bool | None = None
    student_frame: FrameModel | None = None


class WorkoutConfirmRequest(BaseModel):
    session_id: str


class WorkoutProgressResponse(BaseModel):
    session_id: str
    phase: str
    exercise_name: str | None
    mode: str | None
    step_index: int
    set_index: int
    rep_count: int
    hold_seconds: float
    target_reps: int | None
    target_seconds: float | None
    tracking_started: bool
    pending_confirmation: bool
    done: bool
    announcements: list[str]


class WorkoutFinalizeRequest(BaseModel):
    session_id: str


class WorkoutFinalizeResponse(BaseModel):
    session_id: str
    done: bool
    total_events: int
    analysis: dict[str, Any]


class WorkoutSegmentCreateRequest(BaseModel):
    session_id: str
    step_index: int = Field(ge=0)
    set_index: int = Field(ge=0)
    video_uri: str
    duration_seconds: float = Field(ge=0.0)
    observed_rep_count: int | None = Field(default=None, ge=0)


class WorkoutSegmentResponse(BaseModel):
    session_id: str
    segment_index: int
    step_index: int
    set_index: int
    video_uri: str
    duration_seconds: float
    observed_rep_count: int | None


class AnalysisVideoItem(BaseModel):
    id: int
    session_id: str
    step_index: int
    set_index: int
    exercise_name: str
    source_video_uri: str
    comparison_video_uri: str
    similarity: float
    normalized_distance: float
    created_at: str


class AnalysisVideoListResponse(BaseModel):
    items: list[AnalysisVideoItem]
