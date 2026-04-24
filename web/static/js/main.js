import { ApiClient } from "./services/api-client.js?v=20260412a";
import { BrowserSpeechService } from "./services/browser-speech-service.js?v=20260412a";
import { PoseAnalysisEngine, PROFILE_FEATURE_VERSION } from "./pose/pose-analysis-engine.js?v=20260412a";
import { FilesetResolver, PoseLandmarker } from "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/vision_bundle.mjs";

window.addEventListener("error", (event) => {
  const el = document.getElementById("frameLog");
  if (!el) {
    return;
  }
  el.textContent = `JS runtime error: ${event.message}`;
});

const state = {
  templates: [],
  sessionId: null,
  autoTimer: null,
  autoFrameBusy: false,
  cameraStream: null,
  pose: null,
  vision: null,
  poseTimestampMs: 0,
  currentLandmarks: null,
  lastPoseSuccessAt: 0,
  poseFailureSinceAt: 0,
  templateProfiles: {},
  analysisVideos: [],
  workoutSteps: [],
  latestProgress: null,
  countdownActive: false,
  countdownStartedAt: 0,
  countdownLastSpoken: -1,
  forceStartFrame: false,
  lastNotReadyAnnounceAt: 0,
  lastRepAnnounced: 0,
  lastHoldSecondAnnounced: -1,
  lastPhaseAnnounced: "",
  mediaRecorder: null,
  recordingChunks: [],
  activeSegmentMeta: null,
  pendingSegmentMeta: null,
  completedSegments: [],
  segmentUploadPromise: null,
  cameraLoopRaf: null,
  cameraLoopVideoCbId: null,
  inferenceCanvas: null,
  cameraRecoveryTimer: null,
  noLandmarkFrames: 0,
  cameraFrameInFlight: false,
  poseSendFailures: 0,
  lastRealtimeSimilarity: 0,
  lastRealtimeReadiness: false,
  flipSideDirectionLabels: true,
  readinessStableFrames: 0,
  debugTemplateCurrentTemplateId: null,
  debugTemplateCurrentVideoSrc: "",
  debugTemplateOverlayRaf: null,
  debugTemplateOverlayVideoCbId: null,
  lastFrameLogAt: 0,
  bootstrapRefreshTimer: null,
  bootstrapRefreshBusy: false,
  localPreviewObjectUrl: null,
  closedSegmentSetKeys: {},
  isFinalizing: false,
  analysisProgressTimer: null,
  analysisStartedAt: 0,
  autoFinalizeTriggered: false,
  signalBlockUntilMs: 0,
  lastSignalForSegment: 0,
  segmentStartSignalWindow: [],
  startupAnnouncementUntilMs: 0
};

const byId = (id) => document.getElementById(id);

function resetMissingWorkoutSession() {
  if (!state.sessionId) {
    return;
  }
  state.sessionId = null;
  state.latestProgress = null;
  state.countdownActive = false;
  state.countdownLastSpoken = -1;
  state.forceStartFrame = false;
  state.signalBlockUntilMs = 0;
  state.lastSignalForSegment = 0;
  state.segmentStartSignalWindow = [];
  state.startupAnnouncementUntilMs = 0;
  state.pendingSegmentMeta = null;
  state.activeSegmentMeta = null;
  stopAutoFeed();
  stopCamera();
  updateSessionPill();
  updateConfirmButton(null);
  updateTemplateDebugPanel(null);
}

async function api(path, method = "GET", body = null) {
  return apiClient.request(path, method, body);
}

async function uploadVideo(file) {
  return apiClient.uploadVideo(file);
}

function setLog(id, obj) {
  byId(id).textContent = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
}

function speak(messages, clearQueue = false, callback = null) {
  speechService.speak(messages, clearQueue, callback);
}

function speakOncePerCooldown(text, key, cooldownMs = 2500) {
  const now = Date.now();
  const markKey = `__cooldown_${key}`;
  const last = state[markKey] || 0;
  if (now - last < cooldownMs) {
    return;
  }
  state[markKey] = now;
  speak([text]);
}

function updateSessionPill() {
  byId("sessionPill").textContent = "Phiên: " + (state.sessionId || "chưa có");
}

function segmentKeyFromProgress(progress = null) {
  if (!progress) {
    return "";
  }
  const step = Number(progress.step_index ?? NaN);
  const set = Number(progress.set_index ?? NaN);
  if (!Number.isFinite(step) || !Number.isFinite(set)) {
    return "";
  }
  return `${Math.trunc(step)}:${Math.trunc(set)}`;
}

function segmentKeyFromMeta(meta = null) {
  if (!meta) {
    return "";
  }
  const step = Number(meta.step_index ?? NaN);
  const set = Number(meta.set_index ?? NaN);
  if (!Number.isFinite(step) || !Number.isFinite(set)) {
    return "";
  }
  return `${Math.trunc(step)}:${Math.trunc(set)}`;
}

function clearAnalysisProgressTimer() {
  if (state.analysisProgressTimer) {
    clearInterval(state.analysisProgressTimer);
    state.analysisProgressTimer = null;
  }
}

function renderAnalysisProgress(stageText, elapsedSec = 0) {
  const container = byId("analysisResults");
  if (!container) {
    return;
  }
  container.classList.remove("hidden");
  container.innerHTML = `
    <h2>Phân tích sau tập</h2>
    <p><b>${stageText}</b></p>
    <p>Đang xử lý, đã chờ: <b>${Number(elapsedSec).toFixed(1)}s</b></p>
    <div style="height:8px;background:#20303a;border-radius:8px;overflow:hidden;">
      <div style="height:100%;width:100%;background:linear-gradient(90deg,#1dd1a1,#10ac84);"></div>
    </div>
  `;
}

function setCameraPill(active) {
  byId("cameraPill").textContent = active ? "Camera: đang bật" : "Camera: tắt";
}

function setMatchPill(value) {
  byId("matchPill").textContent = `So khớp: ${value}`;
}

function setOrientationDebug(lines) {
  const el = byId("orientationDebug");
  if (!el) {
    return;
  }
  if (!Array.isArray(lines) || !lines.length) {
    el.textContent = "Orientation debug: --";
    return;
  }
  el.textContent = lines.join("\n");
}

function clearCanvas(canvas) {
  if (!canvas) {
    return;
  }
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return;
  }
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}

function clamp01(value) {
  const num = Number(value ?? 0);
  if (!Number.isFinite(num)) {
    return 0;
  }
  if (num < 0) {
    return 0;
  }
  if (num > 1) {
    return 1;
  }
  return num;
}

function stopDebugTemplateOverlayLoop() {
  const video = byId("debugTemplateVideo");
  if (video && state.debugTemplateOverlayVideoCbId && typeof video.cancelVideoFrameCallback === "function") {
    video.cancelVideoFrameCallback(state.debugTemplateOverlayVideoCbId);
    state.debugTemplateOverlayVideoCbId = null;
  }
  if (state.debugTemplateOverlayRaf) {
    cancelAnimationFrame(state.debugTemplateOverlayRaf);
    state.debugTemplateOverlayRaf = null;
  }
}

function resizeCanvasToDisplaySize(canvas) {
  if (!canvas) {
    return;
  }
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const nextW = Math.max(1, Math.round(rect.width * dpr));
  const nextH = Math.max(1, Math.round(rect.height * dpr));
  if (canvas.width !== nextW || canvas.height !== nextH) {
    canvas.width = nextW;
    canvas.height = nextH;
  }
}

function sampleForTemplateVideo(profile, video, template = null, timeSecOverride = null) {
  if (!profile || !video) {
    return null;
  }
  const samples = Array.isArray(profile.pose_samples) ? profile.pose_samples : [];
  if (samples.length) {
    if (samples.length === 1) {
      return samples[0];
    }

    const useTrimWindow = !isFrozenTemplateVideo(template);
    const trimStart = Number(template && template.trim_start_sec);
    const trimEnd = Number(template && template.trim_end_sec);
    const startSec = useTrimWindow && Number.isFinite(trimStart) ? Math.max(0, trimStart) : 0;
    const durationRaw = Number(video.duration || 0);
    const inferredEnd = durationRaw > startSec ? durationRaw : startSec;
    const endSec = useTrimWindow && Number.isFinite(trimEnd) && trimEnd > startSec ? trimEnd : inferredEnd;
    const effectiveDuration = Math.max(1e-6, endSec - startSec);
    const currentSec = Number(timeSecOverride ?? video.currentTime ?? 0);
    const relSec = Math.max(0, Math.min(effectiveDuration, currentSec - startSec));
    const pos = (relSec / effectiveDuration) * (samples.length - 1);
    const lo = Math.max(0, Math.min(samples.length - 1, Math.floor(pos)));
    const hi = Math.max(0, Math.min(samples.length - 1, Math.ceil(pos)));
    if (lo === hi) {
      return samples[lo];
    }

    const t = Math.max(0, Math.min(1, pos - lo));
    const a = samples[lo];
    const b = samples[hi];
    const count = Math.min(Array.isArray(a) ? a.length : 0, Array.isArray(b) ? b.length : 0);
    const blended = [];
    for (let i = 0; i < count; i += 1) {
      const pa = Array.isArray(a[i]) ? a[i] : [];
      const pb = Array.isArray(b[i]) ? b[i] : [];
      const dim = Math.max(pa.length, pb.length);
      const p = [];
      for (let d = 0; d < dim; d += 1) {
        const va = Number(pa[d] ?? 0);
        const vb = Number(pb[d] ?? 0);
        p.push(va + ((vb - va) * t));
      }
      blended.push(p);
    }
    return blended.length ? blended : samples[lo];
  }
  if (Array.isArray(profile.anchor_pose_samples) && profile.anchor_pose_samples.length) {
    return profile.anchor_pose_samples[0];
  }
  if (Array.isArray(profile.anchor_pose_sample) && profile.anchor_pose_sample.length) {
    return profile.anchor_pose_sample;
  }
  return null;
}

function drawSampleOnVideoOverlay(canvas, video, sample, style = OVERLAY_STYLE) {
  if (!canvas || !video || !Array.isArray(sample) || !sample.length) {
    clearCanvas(canvas);
    return;
  }

  resizeCanvasToDisplaySize(canvas);
  const rect = canvas.getBoundingClientRect();
  const cssW = Math.max(1, Number(rect.width || canvas.clientWidth || 1));
  const cssH = Math.max(1, Number(rect.height || canvas.clientHeight || 1));
  const scaleX = canvas.width / cssW;
  const scaleY = canvas.height / cssH;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return;
  }

  const srcW = Math.max(1, Number(video.videoWidth || cssW));
  const srcH = Math.max(1, Number(video.videoHeight || cssH));
  const fit = Math.min(cssW / srcW, cssH / srcH);
  const drawW = srcW * fit;
  const drawH = srcH * fit;
  const offsetX = (cssW - drawW) / 2;
  const offsetY = (cssH - drawH) / 2;

  const project = (point) => ([
    offsetX + (Number(point[0] ?? 0) * drawW),
    offsetY + (Number(point[1] ?? 0) * drawH)
  ]);

  const lineColor = String(style && style.lineColor ? style.lineColor : (style && style.color ? style.color : OVERLAY_STYLE.color));
  const pointColor = String(style && style.pointColor ? style.pointColor : lineColor);
  const lineWidth = Math.max(1, Number(style && style.lineWidth ? style.lineWidth : OVERLAY_STYLE.lineWidth));
  const pointRadius = Math.max(1, Number(style && style.pointRadius ? style.pointRadius : OVERLAY_STYLE.pointRadius));

  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.save();
  ctx.scale(scaleX, scaleY);
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.strokeStyle = lineColor;
  ctx.lineWidth = lineWidth;
  for (const [a, b] of ANALYSIS_CONNECTIONS) {
    const pa = sample[a];
    const pb = sample[b];
    if (!pa || !pb || (pa[3] ?? 0) < 0.25 || (pb[3] ?? 0) < 0.25) {
      continue;
    }
    const [x1, y1] = project(pa);
    const [x2, y2] = project(pb);
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
  }

  ctx.fillStyle = pointColor;
  for (const point of sample) {
    if (!point || (point[3] ?? 0) < 0.25) {
      continue;
    }
    const [x, y] = project(point);
    ctx.beginPath();
    ctx.arc(x, y, pointRadius, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

function syncDebugTemplateStage(video) {
  if (!video) {
    return;
  }
  const stage = video.closest(".video-stage");
  if (!stage) {
    return;
  }
  const width = Math.max(1, Number(video.videoWidth || 0));
  const height = Math.max(1, Number(video.videoHeight || 0));
  if (width > 1 && height > 1) {
    stage.style.aspectRatio = `${width} / ${height}`;
  }
}

function normalizeMediaUri(uri) {
  const raw = String(uri || "").trim();
  if (!raw) {
    return "";
  }
  if (/^https?:\/\//i.test(raw)) {
    return raw;
  }
  return apiClient.buildUrl(raw);
}

function getTemplateArtifactMeta(profile = null) {
  const frozen = profile && profile.frozen_artifact;
  return (frozen && typeof frozen === "object") ? frozen : null;
}

function getTemplateVideoUrl(tpl, profile = null) {
  const artifact = getTemplateArtifactMeta(profile);
  const debugUri = String(artifact && artifact.debug_overlay_video_uri ? artifact.debug_overlay_video_uri : "").trim();
  if (debugUri) {
    return normalizeMediaUri(debugUri);
  }
  const debugUriFromTemplate = String(tpl && tpl.debug_overlay_video_uri ? tpl.debug_overlay_video_uri : "").trim();
  if (debugUriFromTemplate) {
    return normalizeMediaUri(debugUriFromTemplate);
  }
  if (!tpl || !tpl.video_uri) return "";
  return normalizeMediaUri(tpl.video_uri);
}

function getTemplatePoseTimelineJsonUrl(profile = null) {
  const artifact = getTemplateArtifactMeta(profile);
  const timelineUri = String(artifact && artifact.pose_timeline_json_uri ? artifact.pose_timeline_json_uri : "").trim();
  if (!timelineUri) {
    return "";
  }
  return normalizeMediaUri(timelineUri);
}

function useBakedTemplateDebugVideo(profile = null) {
  const artifact = getTemplateArtifactMeta(profile);
  return Boolean(artifact && artifact.debug_overlay_video_uri);
}

function getTemplateTrimRange(tpl, video = null) {
  const useTrimWindow = !isFrozenTemplateVideo(tpl);
  const rawStart = Number(tpl && tpl.trim_start_sec);
  const rawEnd = Number(tpl && tpl.trim_end_sec);
  const hasStart = Number.isFinite(rawStart) && rawStart >= 0;
  const hasEnd = Number.isFinite(rawEnd) && rawEnd > 0;

  const duration = Number(video && video.duration ? video.duration : 0);
  const start = useTrimWindow && hasStart ? Math.max(0, rawStart) : 0;
  let end = useTrimWindow && hasEnd ? rawEnd : (duration > 0 ? duration : start);
  if (!Number.isFinite(end) || end <= start) {
    end = duration > start ? duration : start;
  }
  return { hasTrim: useTrimWindow && (hasStart || hasEnd), start, end };
}

function applyTrimLoopToVideo(video, tpl, options = {}) {
  if (!video) {
    return;
  }

  if (typeof video.__trimCleanup === "function") {
    video.__trimCleanup();
    video.__trimCleanup = null;
  }

  const clampTime = () => {
    const range = getTemplateTrimRange(tpl, video);
    if (!range.hasTrim || !Number.isFinite(video.duration) || video.duration <= 0) {
      return;
    }
    const eps = 0.02;
    if (video.currentTime < (range.start - eps) || video.currentTime > (range.end + eps)) {
      video.currentTime = range.start;
    }
  };

  const onTimeUpdate = () => {
    const range = getTemplateTrimRange(tpl, video);
    if (!range.hasTrim || !Number.isFinite(video.duration) || video.duration <= 0) {
      return;
    }
    if (video.currentTime >= (range.end - 0.01)) {
      video.currentTime = range.start;
      if (!video.paused) {
        video.play().catch(() => { });
      }
    }
  };

  const onSeeking = () => {
    const range = getTemplateTrimRange(tpl, video);
    if (!range.hasTrim || !Number.isFinite(video.duration) || video.duration <= 0) {
      return;
    }
    if (video.currentTime < range.start) {
      video.currentTime = range.start;
    } else if (video.currentTime > range.end) {
      video.currentTime = range.end;
    }
  };

  const onLoadedMetadata = () => {
    clampTime();
    if (options.autoPlayIfReady && video.paused) {
      video.play().catch(() => { });
    }
  };

  video.addEventListener("loadedmetadata", onLoadedMetadata);
  video.addEventListener("timeupdate", onTimeUpdate);
  video.addEventListener("seeking", onSeeking);

  video.__trimCleanup = () => {
    video.removeEventListener("loadedmetadata", onLoadedMetadata);
    video.removeEventListener("timeupdate", onTimeUpdate);
    video.removeEventListener("seeking", onSeeking);
  };

  if (video.readyState >= 1) {
    onLoadedMetadata();
  }
}

function stopBootstrapRefresh() {
  if (state.bootstrapRefreshTimer) {
    clearInterval(state.bootstrapRefreshTimer);
    state.bootstrapRefreshTimer = null;
  }
}

async function refreshDataOnce() {
  await Promise.all([checkHealth(), refreshTemplates(), refreshAnalysisVideos()]);
}

function scheduleBootstrapRefresh() {
  if (state.bootstrapRefreshTimer) {
    return;
  }
  state.bootstrapRefreshTimer = setInterval(async () => {
    if (state.bootstrapRefreshBusy) {
      return;
    }
    state.bootstrapRefreshBusy = true;
    try {
      await refreshDataOnce();
      stopBootstrapRefresh();
      setLog("startLog", "Đã tự đồng bộ lại dữ liệu từ server sau khi khởi động lại.");
    } catch (_) {
      // Keep retrying silently until API is ready.
    } finally {
      state.bootstrapRefreshBusy = false;
    }
  }, 2500);
}

function updateConfirmButton(progress = state.latestProgress) {
  const btn = byId("confirmBtn");
  if (!progress) {
    btn.textContent = "Tiếp tục set/bài kế tiếp";
    return;
  }

  if (progress.phase === "rest_pending_confirmation") {
    btn.textContent = "Tiếp tục vào set tiếp theo";
  } else if (progress.phase === "exercise_pending_confirmation") {
    btn.textContent = "Tiếp tục sang bài tiếp theo";
  } else if (progress.phase === "waiting_readiness") {
    btn.textContent = "Tiếp tục và bật pose";
  } else if (progress.phase === "done") {
    btn.textContent = "Buổi tập đã xong";
  } else {
    btn.textContent = "Tiếp tục set/bài kế tiếp";
  }
}

function pickRecordingMimeType() {
  if (typeof MediaRecorder === "undefined") {
    return "";
  }
  const candidates = [
    "video/webm;codecs=vp9,opus",
    "video/webm;codecs=vp8,opus",
    "video/webm"
  ];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

async function startSegmentRecording(progress) {
  if (!state.cameraStream || state.mediaRecorder || typeof MediaRecorder === "undefined") {
    return;
  }

  const mimeType = pickRecordingMimeType();
  const options = mimeType ? { mimeType } : undefined;
  state.recordingChunks = [];
  const armed = state.pendingSegmentMeta || {};
  state.activeSegmentMeta = {
    startedAt: Date.now(),
    step_index: Number(armed.step_index ?? progress.step_index ?? 0),
    set_index: Number(armed.set_index ?? progress.set_index ?? 0),
    exercise_name: armed.exercise_name || progress.exercise_name || ""
  };
  state.pendingSegmentMeta = null;

  const recorder = new MediaRecorder(state.cameraStream, options);
  recorder.ondataavailable = (event) => {
    if (event.data && event.data.size > 0) {
      state.recordingChunks.push(event.data);
    }
  };
  recorder.start(250);
  state.mediaRecorder = recorder;
  // Short guard so tracking cannot run ahead before recorder is fully ready.
  state.signalBlockUntilMs = Math.max(state.signalBlockUntilMs || 0, Date.now() + 250);
}

async function stopSegmentRecording(progress = state.latestProgress) {
  if (state.segmentUploadPromise) {
    return state.segmentUploadPromise;
  }
  if (!state.mediaRecorder) {
    return null;
  }

  const recorder = state.mediaRecorder;
  const meta = state.activeSegmentMeta || {};
  const segmentKey = segmentKeyFromMeta(meta);
  if (segmentKey) {
    state.closedSegmentSetKeys[segmentKey] = true;
  }
  state.mediaRecorder = null;
  state.activeSegmentMeta = null;

  const stopPromise = recorder.state === "inactive"
    ? Promise.resolve()
    : new Promise((resolve) => {
      recorder.addEventListener("stop", resolve, { once: true });
    });

  if (recorder.state !== "inactive") {
    recorder.stop();
  }
  await stopPromise;

  const chunks = state.recordingChunks.slice();
  state.recordingChunks = [];
  if (!chunks.length) {
    return null;
  }

  const mimeType = chunks[0].type || recorder.mimeType || "video/webm";
  const extension = mimeType.includes("mp4") ? ".mp4" : ".webm";
  const elapsed = Math.max(0, Date.now() - Number(meta.startedAt || Date.now()));
  const blob = new Blob(chunks, { type: mimeType });
  if (!blob.size) {
    return null;
  }

  state.segmentUploadPromise = (async () => {
    const file = new File([blob], `segment-${Date.now()}${extension}`, { type: mimeType });
    const upload = await uploadVideo(file);
    const segment = await api("/v1/workout/session/segment", "POST", {
      session_id: state.sessionId,
      step_index: Number(meta.step_index ?? progress?.step_index ?? 0),
      set_index: Number(meta.set_index ?? progress?.set_index ?? 0),
      video_uri: upload.video_uri,
      duration_seconds: elapsed / 1000,
      observed_rep_count: Number(progress?.rep_count ?? 0)
    });

    const saved = {
      exercise_name: meta.exercise_name || progress?.exercise_name || "",
      upload,
      segment
    };
    state.completedSegments.push(saved);
    setLog("finalizeLog", { recorded_segments: state.completedSegments });
    return saved;
  })();

  try {
    return await state.segmentUploadPromise;
  } finally {
    state.segmentUploadPromise = null;
  }
}

function armSegmentRecording(progress = state.latestProgress) {
  if (!progress || progress.phase !== "active_set") {
    return;
  }
  const segmentKey = segmentKeyFromProgress(progress);
  if (segmentKey && state.closedSegmentSetKeys[segmentKey]) {
    return;
  }
  if (state.mediaRecorder || state.segmentUploadPromise || state.pendingSegmentMeta) {
    return;
  }
  state.pendingSegmentMeta = {
    step_index: Number(progress.step_index ?? 0),
    set_index: Number(progress.set_index ?? 0),
    exercise_name: progress.exercise_name || ""
  };
}

async function maybeStartSegmentRecording(progress = state.latestProgress) {
  if (!progress || progress.phase !== "active_set") {
    return;
  }
  if (!Boolean(progress.tracking_started)) {
    return;
  }
  const segmentKey = segmentKeyFromProgress(progress);
  if (segmentKey && state.closedSegmentSetKeys[segmentKey]) {
    return;
  }
  if (state.mediaRecorder || state.segmentUploadPromise) {
    return;
  }
  if (!state.pendingSegmentMeta) {
    armSegmentRecording(progress);
  }
  await startSegmentRecording(progress);
}

async function syncSessionTransition(previousProgress, nextProgress) {
  const previousPhase = previousProgress && previousProgress.phase ? previousProgress.phase : "";
  const nextPhase = nextProgress && nextProgress.phase ? nextProgress.phase : "";

  updateConfirmButton(nextProgress);

  if (nextPhase === "active_set" && previousPhase !== "active_set") {
    const segmentKey = segmentKeyFromProgress(nextProgress);
    if (segmentKey && state.closedSegmentSetKeys[segmentKey]) {
      delete state.closedSegmentSetKeys[segmentKey];
    }
    armSegmentRecording(nextProgress);
    await maybeStartSegmentRecording(nextProgress);
    state.signalBlockUntilMs = Math.max(state.signalBlockUntilMs || 0, Date.now() + 450);
    state.segmentStartSignalWindow = [];
    state.startupAnnouncementUntilMs = 0;
  }

  if (previousPhase === "active_set" && nextPhase !== "active_set") {
    await stopSegmentRecording(nextProgress);
    state.pendingSegmentMeta = null;
    stopAutoFeed();
  }

  if (nextPhase !== "active_set") {
    state.pendingSegmentMeta = null;
    state.signalBlockUntilMs = 0;
    state.segmentStartSignalWindow = [];
    if (nextPhase !== "waiting_readiness") {
      state.startupAnnouncementUntilMs = 0;
    }
  }

  // Auto-finalize: when all sets/exercises are done, trigger post-workout analysis immediately
  if (nextPhase === "done" && previousPhase !== "done") {
    speak(["Hoàn thành buổi tập. Bắt đầu phân tích."]);
    activateStep(5);
    setTimeout(() => {
      finalizeSession({ autoTriggered: true }).catch((err) => {
        setLog("finalizeLog", "Auto-finalize failed: " + String(err));
      });
    }, 800);
  }
}

const ANALYSIS_CONNECTIONS = (window.POSE_CONNECTIONS || [
  [11, 12], [11, 13], [13, 15], [12, 14], [14, 16],
  [11, 23], [12, 24], [23, 24], [23, 25], [25, 27], [24, 26], [26, 28]
]).map((conn) => Array.isArray(conn) ? conn : [conn.start, conn.end]);

const OVERLAY_STYLE = {
  color: "#136f63",
  lineWidth: 3,
  pointRadius: 4,
};

const DEBUG_TEMPLATE_OVERLAY_STYLE = {
  lineColor: "#ff4f8b",
  pointColor: "#00d5ff",
  lineWidth: 3,
  pointRadius: 4,
};

function isFrozenTemplateVideo(template = null) {
  const uri = String(template && template.video_uri ? template.video_uri : "");
  return uri.startsWith("/uploads/template_frozen/");
}

// Realtime camera flow: prioritize FULL model for better FPS while keeping pose quality.
const POSE_MODEL_CANDIDATES = [
  "/data/models/pose_landmarker_full.task",
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task",
];

function drawNotebookStyleLiveFrame(frameImage, landmarks) {
  const overlay = byId("liveCameraOverlay");
  if (!overlay) {
    return;
  }

  const ctx = overlay.getContext("2d");
  if (!ctx) {
    return;
  }

  ctx.clearRect(0, 0, overlay.width, overlay.height);
  if (frameImage) {
    ctx.drawImage(frameImage, 0, 0, overlay.width, overlay.height);
  }

  if (!Array.isArray(landmarks) || !landmarks.length) {
    return;
  }

  const w = overlay.width;
  const h = overlay.height;

  ctx.fillStyle = "rgb(0,255,0)";
  for (const lm of landmarks) {
    const x = Math.trunc(Number(lm && lm.x) * w);
    const y = Math.trunc(Number(lm && lm.y) * h);
    if (x >= 0 && x < w && y >= 0 && y < h) {
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  ctx.strokeStyle = "rgb(255,200,0)";
  ctx.lineWidth = 2;
  for (const [a, b] of ANALYSIS_CONNECTIONS) {
    if (a >= landmarks.length || b >= landmarks.length) {
      continue;
    }
    const la = landmarks[a];
    const lb = landmarks[b];
    if (!la || !lb) {
      continue;
    }

    const x1 = Math.trunc(Number(la.x) * w);
    const y1 = Math.trunc(Number(la.y) * h);
    const x2 = Math.trunc(Number(lb.x) * w);
    const y2 = Math.trunc(Number(lb.y) * h);
    if (x1 >= 0 && x1 < w && y1 >= 0 && y1 < h && x2 >= 0 && x2 < w && y2 >= 0 && y2 < h) {
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
    }
  }
}

const apiClient = new ApiClient({
  baseUrl: (window.location.protocol === "file:" || !window.location.hostname)
    ? "http://127.0.0.1:8000"
    : "",
  onSessionMissing: () => resetMissingWorkoutSession(),
});

const speechService = new BrowserSpeechService({
  isEnabled: () => Boolean(byId("speakEnabledBrowser")?.checked),
});

const poseEngine = new PoseAnalysisEngine({
  connections: ANALYSIS_CONNECTIONS,
  getFlipSideDirectionLabels: () => state.flipSideDirectionLabels,
});

function projectPointFromBBox(point, bbox, width, height) {
  const minX = Number(bbox.min_x ?? 0);
  const minY = Number(bbox.min_y ?? 0);
  const maxX = Number(bbox.max_x ?? 1);
  const maxY = Number(bbox.max_y ?? 1);
  const scaleX = width / Math.max(1e-6, maxX - minX);
  const scaleY = height / Math.max(1e-6, maxY - minY);
  const scale = Math.min(scaleX, scaleY);
  const offsetX = (width - ((maxX - minX) * scale)) / 2;
  const offsetY = (height - ((maxY - minY) * scale)) / 2;
  return [
    ((point[0] - minX) * scale) + offsetX,
    ((point[1] - minY) * scale) + offsetY
  ];
}

function applyVideoFocus(video, bbox) {
  if (!video || !bbox) {
    return;
  }
  video.style.objectPosition = `${Number(bbox.center_x ?? 0.5) * 100}% ${Number(bbox.center_y ?? 0.5) * 100}%`;
}

function bboxFromSample(sample) {
  return poseEngine.bboxFromSample(sample);
}

function sampleFromLandmarks(landmarks) {
  return poseEngine.sampleFromLandmarks(landmarks);
}

function landmarksFromSample(sample, bbox = null) {
  return poseEngine.landmarksFromSample(sample, bbox);
}

function drawOverlay(canvas, sample, bbox, jointErrors, baseColor) {
  poseEngine.drawOverlay(canvas, sample, bbox, jointErrors, baseColor);
}

function renderFrameDetails(segment, frameInfo, idx) {
  const info = byId(`analysisFrameInfo_${idx}`);
  const detail = byId(`analysisDetail_${idx}`);
  if (info) {
    const repLabel = frameInfo.rep_index ? ` | Rep ${frameInfo.rep_index}` : "";
    const cycleLabel = frameInfo.template_cycle_index
      ? ` | Mẫu vòng ${Number(frameInfo.template_cycle_index)}/${Number(segment.template_cycles || 1)}`
      : "";
    info.textContent = `Frame ${Number(frameInfo.student_frame_index || 0) + 1}${repLabel}${cycleLabel}`;
  }
  if (detail) {
    const top = (frameInfo.joint_errors || []).filter((item) => item.highlight).slice(0, 3);
    detail.textContent = top.length
      ? top.map((item) => `${item.label}: ${Number(item.angle_delta_deg || 0).toFixed(1)}°, ${Array.isArray(item.direction) ? item.direction.join(", ") : ""}`).join(" | ")
      : "Frame này không có sai lệch lớn.";
  }
}

function mountSegmentPlayers(segment, idx) {
  const templateVideo = byId(`templateVideo_${idx}`);
  const studentVideo = byId(`studentVideo_${idx}`);
  const templateCanvas = byId(`templateCanvas_${idx}`);
  const studentCanvas = byId(`studentCanvas_${idx}`);
  const playBtn = byId(`analysisToggle_${idx}`);
  const frameAnalyses = Array.isArray(segment.frame_analyses) ? segment.frame_analyses : [];
  if (!templateVideo || !studentVideo || !templateCanvas || !studentCanvas || !playBtn || !frameAnalyses.length) {
    return;
  }

  let rafId = 0;
  let playing = false;
  let syncing = false;

  const update = () => {
    const progress = studentVideo.duration ? (studentVideo.currentTime / studentVideo.duration) : 0;
    const frameIndex = Math.max(0, Math.min(frameAnalyses.length - 1, Math.floor(progress * frameAnalyses.length)));
    const frameInfo = frameAnalyses[frameIndex];
    const templateSample = segment.template_pose_samples[frameIndex];
    const studentSample = segment.student_pose_samples[frameIndex];

    if (templateVideo.duration && frameInfo && frameInfo.template_cycle_frames) {
      const cycleFrames = Math.max(1, Number(frameInfo.template_cycle_frames || 1));
      const cycleFrameIndex = Math.max(0, Number(frameInfo.template_cycle_frame_index || 0));
      const mapped = (cycleFrameIndex / cycleFrames) * templateVideo.duration;
      if (Math.abs(templateVideo.currentTime - mapped) > 0.05) {
        templateVideo.currentTime = Math.max(0, Math.min(templateVideo.duration, mapped));
      }
    }

    applyVideoFocus(templateVideo, frameInfo.template_bbox);
    applyVideoFocus(studentVideo, frameInfo.student_bbox);
    drawOverlay(templateCanvas, templateSample, frameInfo.template_bbox, [], OVERLAY_STYLE.color);
    drawOverlay(studentCanvas, studentSample, frameInfo.student_bbox, frameInfo.joint_errors, OVERLAY_STYLE.color);
    renderFrameDetails(segment, frameInfo, idx);

    if (playing) {
      rafId = window.requestAnimationFrame(update);
    }
  };

  const syncVideos = (source, target) => {
    if (syncing) {
      return;
    }
    syncing = true;
    const progress = source.duration ? (source.currentTime / source.duration) : 0;
    if (target.duration) {
      target.currentTime = progress * target.duration;
    }
    window.setTimeout(() => {
      syncing = false;
    }, 0);
  };

  const startPlayback = () => {
    window.cancelAnimationFrame(rafId);
    templateVideo.currentTime = 0;
    studentVideo.currentTime = 0;
    templateVideo.play().catch(() => { });
    studentVideo.play().catch(() => { });
    playing = true;
    playBtn.textContent = "Tạm dừng video";
    update();
  };

  const stopPlayback = () => {
    playing = false;
    window.cancelAnimationFrame(rafId);
    templateVideo.pause();
    studentVideo.pause();
    playBtn.textContent = "Phát lại video";
    update();
  };

  playBtn.addEventListener("click", () => {
    if (playing) {
      stopPlayback();
    } else {
      startPlayback();
    }
  });

  studentVideo.addEventListener("ended", stopPlayback);
  templateVideo.addEventListener("ended", stopPlayback);
  studentVideo.addEventListener("timeupdate", update);
  templateVideo.addEventListener("timeupdate", update);
  studentVideo.addEventListener("seeking", () => {
    syncVideos(studentVideo, templateVideo);
    update();
  });
  templateVideo.addEventListener("seeking", () => {
    syncVideos(templateVideo, studentVideo);
    update();
  });
  studentVideo.addEventListener("pause", update);
  templateVideo.addEventListener("pause", update);
  studentVideo.addEventListener("loadedmetadata", update);
  templateVideo.addEventListener("loadedmetadata", update);
  update();
}

function renderAnalysisResults(result) {
  const container = byId("analysisResults");
  const analysis = result && result.analysis ? result.analysis : {};
  const segments = Array.isArray(analysis.segments) ? analysis.segments : [];
  const errors = Array.isArray(analysis.errors) ? analysis.errors : [];
  const errorHtml = errors.length
    ? `
      <div class="analysis-errors" style="margin:10px 0 12px;padding:10px 12px;border:1px solid #b45309;background:#fff7ed;border-radius:10px;">
        <b>Có ${errors.length} segment lỗi khi phân tích:</b>
        <pre style="white-space:pre-wrap;word-break:break-word;margin-top:8px;">${errors.map((err) => `[step ${Number(err.step_index ?? -1) + 1} set ${Number(err.set_index ?? -1) + 1}] ${String(err.error || "")}`).join("\n")}</pre>
      </div>
    `
    : "";
  if (!segments.length) {
    container.classList.remove("hidden");
    container.innerHTML = `
      <h2>Phân tích sau tập</h2>
      <p>${String(analysis.message || "Chưa có segment phân tích được.")}</p>
      ${errorHtml}
    `;
    return;
  }

  container.classList.remove("hidden");
  container.innerHTML = `
    <h2>Phân tích sau tập</h2>
    <p>Độ giống trung bình: <b>${Number(analysis.average_similarity || 0).toFixed(2)}</b> | Segment đã phân tích: <b>${analysis.analyzed_segments || 0}</b></p>
    ${errorHtml}
    <div class="analysis-grid">
      ${segments.map((segment, idx) => `
        <article class="analysis-card">
          <h3>${segment.exercise_name} (Bài ${Number(segment.step_index || 0) + 1} - Set ${Number(segment.set_index || 0) + 1})</h3>
          <p>Similarity: <b>${Number(segment.similarity || 0).toFixed(2)}</b> | Distance: <b>${Number(segment.normalized_distance || 0).toFixed(3)}</b></p>
          ${segment.comparison_video_uri ? `
            <div style="margin:8px 0 10px;">
              <h4 style="margin:0 0 6px;">Video so khớp duy nhất (mẫu và người tập)</h4>
              <video src="${segment.comparison_video_uri}" controls playsinline preload="metadata"></video>
            </div>
          ` : ""}
          <table class="joint-table">
            <thead>
              <tr>
                <th>Khớp</th>
                <th>Lệch độ</th>
                <th>Hướng lệch</th>
              </tr>
            </thead>
            <tbody>
              ${(segment.joint_analyses || []).slice(0, 8).map((joint) => `
                <tr>
                  <td>${joint.label}</td>
                  <td>${Number(joint.angle_delta_deg || 0).toFixed(1)}°</td>
                  <td>${Array.isArray(joint.direction) ? joint.direction.join(", ") : ""}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
          <pre>${(segment.rep_feedback || []).flatMap((item) => item.text || []).join("\n")}</pre>
        </article>
      `).join("")}
    </div>
  `;
}

function activateStep(stepNumber) {
  const buttons = Array.from(document.querySelectorAll(".step-btn"));
  buttons.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.step === String(stepNumber));
  });
  for (let i = 1; i <= 5; i += 1) {
    const panel = byId("step" + i);
    if (panel) panel.classList.toggle("hidden", i !== stepNumber);
  }
}

function lockWorkflowUI(isLocked) {
  // Lock steps 1-3 during active workout (step 4) or analysis (step 5)
  const buttons = Array.from(document.querySelectorAll(".step-btn"));
  buttons.forEach((btn) => {
    const step = Number(btn.dataset.step);
    if (step <= 3) {
      btn.classList.toggle("locked", isLocked);
    }
  });
}

function stepItemHtml() {
  const options = state.templates.map((t) => `<option value="${t.template_id}">${t.name} (${t.mode})</option>`).join("");
  return `
    <div class="step-item">
      <div class="step-item-head">
        <b>Dòng bài tập</b>
        <button class="warn remove-step-btn" type="button">Xóa dòng</button>
      </div>
      <div class="row2">
        <div>
          <label>Bài tập (từ kho)</label>
          <select class="step-template">${options}</select>
        </div>
        <div>
          <label>Số set</label>
          <input class="step-sets" type="number" min="1" value="1">
        </div>
      </div>
      <div class="row2">
        <div class="step-config step-reps-wrap">
          <label>Rep mỗi set (cho reps)</label>
          <input class="step-reps" type="number" min="1" value="10">
        </div>
        <div class="step-config step-hold-wrap">
          <label>Giây giữ mỗi set (cho hold)</label>
          <input class="step-hold" type="number" min="1" value="30">
        </div>
      </div>
    </div>
  `;
}

function readWorkoutSteps() {
  const rows = Array.from(document.querySelectorAll(".step-item"));
  return rows.map((row) => ({
    template_id: row.querySelector(".step-template").value,
    sets: Number(row.querySelector(".step-sets").value),
    reps_per_set: row.querySelector(".step-reps-wrap").classList.contains("hidden")
      ? null
      : Number(row.querySelector(".step-reps").value),
    hold_seconds_per_set: row.querySelector(".step-hold-wrap").classList.contains("hidden")
      ? null
      : Number(row.querySelector(".step-hold").value),
    rest_seconds_between_sets: 0
  }));
}

function renderLibraryCards() {
  const container = byId("libraryCards");
  if (!state.templates.length) {
    container.innerHTML = "<p>Kho bài tập trống. Hãy thêm video ở Bước 1.</p>";
    return;
  }

  container.innerHTML = state.templates.map((t) => `
    <div class="card-item">
      <h4>${t.name}</h4>
      <p>Kiểu: ${t.mode}</p>
      <p style="font-size:12px;word-break:break-all;">${t.video_uri || ""}</p>
      <div class="card-actions">
        <button class="secondary view-video-btn" data-id="${t.template_id}">Xem video</button>
        <button class="secondary edit-template-btn" data-id="${t.template_id}">Sửa</button>
        <button class="warn delete-template-btn" data-id="${t.template_id}">Xóa</button>
      </div>
    </div>
  `).join("");

  Array.from(document.querySelectorAll(".view-video-btn")).forEach((btn) => {
    btn.addEventListener("click", () => {
      const tpl = state.templates.find((x) => x.template_id === btn.dataset.id);
      if (!tpl) {
        return;
      }
      const preview = byId("previewVideo");
      preview.src = getTemplateVideoUrl(tpl);
      applyTrimLoopToVideo(preview, tpl, { autoPlayIfReady: false });
      byId("videoMeta").textContent = `Đang xem: ${tpl.name} (${tpl.mode})`;
    });
  });

  Array.from(document.querySelectorAll(".edit-template-btn")).forEach((btn) => {
    btn.addEventListener("click", async () => {
      const tpl = state.templates.find((x) => x.template_id === btn.dataset.id);
      if (!tpl) {
        return;
      }

      const name = window.prompt("Tên bài tập mới:", tpl.name);
      if (name === null) {
        return;
      }

      const mode = window.prompt("Kiểu bài tập mới (reps/hold):", tpl.mode);
      if (mode === null) {
        return;
      }
      const normalizedMode = String(mode).trim().toLowerCase();
      if (!["reps", "hold"].includes(normalizedMode)) {
        setLog("libraryLog", "Kiểu bài tập chỉ được là reps hoặc hold.");
        return;
      }

      const notes = window.prompt("Ghi chú:", tpl.notes || "") ?? tpl.notes;

      try {
        const updated = await api(`/v1/library/templates/${tpl.template_id}`, "PUT", {
          name,
          mode: normalizedMode,
          notes
        });
        setLog("libraryLog", { message: "Đã cập nhật template", updated });
        await refreshTemplates();
      } catch (err) {
        setLog("libraryLog", String(err));
      }
    });
  });

  Array.from(document.querySelectorAll(".delete-template-btn")).forEach((btn) => {
    btn.addEventListener("click", async () => {
      const tpl = state.templates.find((x) => x.template_id === btn.dataset.id);
      if (!tpl) {
        return;
      }

      const ok = window.confirm(`Xóa bài tập ${tpl.name}?`);
      if (!ok) {
        return;
      }

      try {
        const result = await api(`/v1/library/templates/${tpl.template_id}`, "DELETE");
        setLog("libraryLog", result);
        await refreshTemplates();
      } catch (err) {
        setLog("libraryLog", String(err));
      }
    });
  });
}

function renderAnalysisLibraryCards() {
  const container = byId("analysisLibraryCards");
  if (!container) {
    return;
  }
  if (!state.analysisVideos.length) {
    container.innerHTML = "<p>Chưa có video phân tích nào.</p>";
    return;
  }

  container.innerHTML = state.analysisVideos.map((item) => `
    <div class="card-item">
      <h4>${item.exercise_name} - set ${Number(item.set_index || 0) + 1}</h4>
      <p>Similarity: ${Number(item.similarity || 0).toFixed(2)}</p>
      <p style="font-size:12px;word-break:break-all;">${item.comparison_video_uri || ""}</p>
      <div class="card-actions">
        <button class="secondary view-analysis-video-btn" data-id="${item.id}">Xem video</button>
        <button class="warn delete-analysis-video-btn" data-id="${item.id}">Xóa</button>
      </div>
    </div>
  `).join("");

  Array.from(document.querySelectorAll(".view-analysis-video-btn")).forEach((btn) => {
    btn.addEventListener("click", () => {
      const item = state.analysisVideos.find((x) => Number(x.id) === Number(btn.dataset.id));
      if (!item) {
        return;
      }
      byId("previewVideo").src = item.comparison_video_uri;
      byId("videoMeta").textContent = `Video phân tích: ${item.exercise_name} | set ${Number(item.set_index || 0) + 1}`;
    });
  });

  Array.from(document.querySelectorAll(".delete-analysis-video-btn")).forEach((btn) => {
    btn.addEventListener("click", async () => {
      const item = state.analysisVideos.find((x) => Number(x.id) === Number(btn.dataset.id));
      if (!item) {
        return;
      }
      const ok = window.confirm(`Xóa video phân tích ${item.exercise_name} set ${Number(item.set_index || 0) + 1}?`);
      if (!ok) {
        return;
      }
      try {
        const result = await api(`/v1/library/analysis-videos/${item.id}?delete_file=true`, "DELETE");
        setLog("libraryLog", result);
        await refreshAnalysisVideos();
      } catch (err) {
        setLog("libraryLog", String(err));
      }
    });
  });
}

function renderStepsBox() {
  const box = byId("stepsBox");
  if (!state.templates.length) {
    box.innerHTML = "<p>Chưa có bài tập trong kho. Hãy quay lại Bước 1.</p>";
    return;
  }
  const currentRows = box.querySelectorAll(".step-item").length;
  const targetRows = Math.max(1, currentRows || 1);
  box.innerHTML = "";
  for (let i = 0; i < targetRows; i += 1) {
    box.insertAdjacentHTML("beforeend", stepItemHtml());
  }
  bindStepRowActions();
}

async function checkHealth() {
  try {
    const health = await api("/health");
    byId("healthPill").textContent = "API: " + health.status;
  } catch (_) {
    byId("healthPill").textContent = "API: không kết nối được";
  }
}

async function refreshTemplates() {
  const data = await api("/v1/library/templates");
  state.templates = data.items || [];
  setLog("templateLog", data);
  setLog("libraryLog", data);
  renderLibraryCards();
  renderStepsBox();
}

async function refreshAnalysisVideos() {
  const data = await api("/v1/library/analysis-videos");
  state.analysisVideos = data.items || [];
  renderAnalysisLibraryCards();
}

async function fetchTemplateProfile(templateId) {
  let profileRes = await api(`/v1/library/templates/${templateId}/profile`, "GET");
  const cachedProfile = profileRes && profileRes.ready ? profileRes.profile : null;

  const tpl = (Array.isArray(state.templates) ? state.templates : []).find((item) => item && item.template_id === templateId) || null;
  const profileArtifact = (cachedProfile && cachedProfile.frozen_artifact && typeof cachedProfile.frozen_artifact === "object")
    ? cachedProfile.frozen_artifact
    : null;
  const hasProfileArtifacts = Boolean(
    profileArtifact
    && String(profileArtifact.debug_overlay_video_uri || "").trim()
    && String(profileArtifact.pose_timeline_json_uri || "").trim()
  );
  const hasTemplateArtifacts = Boolean(
    tpl
    && String(tpl.debug_overlay_video_uri || "").trim()
    && String(tpl.pose_timeline_json_uri || "").trim()
  );
  const missingPoseArtifacts = !(hasProfileArtifacts || hasTemplateArtifacts);

  if (!profileRes.ready || !poseEngine.hasCompatibleProfile(cachedProfile) || missingPoseArtifacts) {
    profileRes = await api(`/v1/library/templates/${templateId}/profile`, "POST");
  }
  if (!profileRes.ready || !poseEngine.hasCompatibleProfile(profileRes.profile)) {
    throw new Error(`Profile ${templateId} chưa sẵn sàng hoặc sai feature version ${PROFILE_FEATURE_VERSION}.`);
  }
  return profileRes.profile;
}

async function warmTemplateProfiles() {
  const templates = Array.isArray(state.templates) ? state.templates : [];
  for (const template of templates) {
    if (!template || !template.template_id) {
      continue;
    }
    const existing = state.templateProfiles[template.template_id];
    if (existing && poseEngine.hasCompatibleProfile(existing)) {
      continue;
    }
    try {
      state.templateProfiles[template.template_id] = await fetchTemplateProfile(template.template_id);
    } catch (_) {
      // Warm-up should not block app boot.
    }
  }
}

async function warmStartApp() {
  activateStep(3);
  setLog("startLog", `Đang khởi tạo app (API base: ${apiClient.baseUrl || "same-origin"}): preload Pose, tải template và warm-up profile...`);

  const results = await Promise.allSettled([
    checkHealth(),
    initPose(),
    refreshTemplates(),
    refreshAnalysisVideos()
  ]);

  const refreshResult = results[2];
  if (refreshResult && refreshResult.status === "fulfilled") {
    setLog("startLog", "Đã preload Pose và tải template. Đang warm-up profile nền...");
    warmTemplateProfiles().then(() => {
      setLog("startLog", "App đã warm-up xong các tiến trình phân tích, có thể chuẩn bị bắt đầu.");
    }).catch(() => {
      setLog("startLog", "App preload xong phan chinh; profile se tiep tuc build khi can.");
    });
  } else {
    setLog("startLog", "Đã preload Pose. API/template sẽ tiếp tục thử lại khi bạn thao tác.");
    scheduleBootstrapRefresh();
  }
}

async function uploadAndCreateTemplate() {
  const fileInput = byId("tplFile");
  if (!fileInput.files || !fileInput.files.length) {
    setLog("templateLog", "Hãy chọn file video trước.");
    return;
  }

  const uploadRes = await uploadVideo(fileInput.files[0]);

  const trimStartStr = byId("tplTrimStart").value.trim();
  const trimEndStr = byId("tplTrimEnd").value.trim();

  const payload = {
    name: byId("tplName").value,
    mode: byId("tplMode").value,
    video_uri: uploadRes.video_uri,
    notes: byId("tplNotes").value,
    trim_start_sec: trimStartStr ? parseFloat(trimStartStr) : null,
    trim_end_sec: trimEndStr ? parseFloat(trimEndStr) : null,
  };

  const result = await api("/v1/library/templates", "POST", payload);
  setLog("templateLog", { upload: uploadRes, template: result });
  await refreshTemplates();
  activateStep(2);
}

function addWorkoutStep() {
  if (!state.templates.length) {
    setLog("startLog", "Hãy thêm bài tập vào kho trước.");
    return;
  }
  byId("stepsBox").insertAdjacentHTML("beforeend", stepItemHtml());
  bindStepRowActions();
}

function syncStepItemMode(row) {
  if (!row) {
    return;
  }
  const templateId = row.querySelector(".step-template").value;
  const template = state.templates.find((item) => item.template_id === templateId);
  const isHold = template && template.mode === "hold";
  row.querySelector(".step-reps-wrap").classList.toggle("hidden", Boolean(isHold));
  row.querySelector(".step-hold-wrap").classList.toggle("hidden", !isHold);
}

function bindStepRowActions() {
  Array.from(document.querySelectorAll(".remove-step-btn")).forEach((btn) => {
    if (btn.dataset.bound === "1") {
      return;
    }
    btn.dataset.bound = "1";
    btn.addEventListener("click", () => {
      const row = btn.closest(".step-item");
      if (row) {
        row.remove();
      }
    });
  });

  Array.from(document.querySelectorAll(".step-template")).forEach((select) => {
    if (select.dataset.bound === "1") {
      return;
    }
    select.dataset.bound = "1";
    select.addEventListener("change", () => {
      syncStepItemMode(select.closest(".step-item"));
    });
    syncStepItemMode(select.closest(".step-item"));
  });
}

async function startWorkoutSession() {
  const steps = readWorkoutSteps();
  if (!steps.length) {
    setLog("startLog", "Giáo án đang trống.");
    return;
  }

  activateStep(4);
  lockWorkflowUI(true);
  window.scrollTo({ top: 0, behavior: "smooth" });
  setLog("startLog", "Đang chuẩn bị phiên tập: mở camera và tải profile bài tập...");
  await startCamera();

  // Build or load template profiles for MediaPipe-based matching.
  const uniqueTemplateIds = [...new Set(steps.map((s) => s.template_id))];
  const profileResults = await Promise.all(
    uniqueTemplateIds.map(async (templateId) => ({
      templateId,
      profile: await fetchTemplateProfile(templateId)
    }))
  );
  for (const item of profileResults) {
    state.templateProfiles[item.templateId] = item.profile;
  }

  const payload = {
    speak_enabled: byId("speakEnabledBackend").checked,
    steps
  };
  const result = await api("/v1/workout/session/start", "POST", payload);
  state.sessionId = result.session_id;

  const tmap = {};
  for (const t of state.templates) tmap[t.template_id] = t;
  state.localSession = new window.WorkoutSessionJS(tmap, { steps: steps });

  state.workoutSteps = steps;
  state.latestProgress = result;
  state.countdownActive = false;
  state.forceStartFrame = false;
  state.lastRepAnnounced = 0;
  state.lastHoldSecondAnnounced = -1;
  state.lastPhaseAnnounced = "";
  poseEngine.resetWorkoutState();
  state.completedSegments = [];
  state.recordingChunks = [];
  state.activeSegmentMeta = null;
  state.pendingSegmentMeta = null;
  state.mediaRecorder = null;
  state.signalBlockUntilMs = 0;
  state.lastSignalForSegment = 0;
  state.segmentStartSignalWindow = [];
  state.startupAnnouncementUntilMs = 0;
  state.closedSegmentSetKeys = {};
  state.autoFinalizeTriggered = false;
  state.isFinalizing = false;
  state.analysisStartedAt = 0;
  clearAnalysisProgressTimer();
  byId("analysisResults").classList.add("hidden");
  byId("analysisResults").innerHTML = "";
  updateSessionPill();
  updateConfirmButton(result);
  setLog("startLog", result);
  speak(result.announcements || []);

  startAutoFeed();
  const introMs = Boolean(byId("speakEnabledBrowser")?.checked) ? 5200 : 0;
  if (introMs > 0) {
    state.startupAnnouncementUntilMs = Date.now() + introMs;
  }
  speak(["Camera đã sẵn sàng. Khi đúng tư thế và góc quay phù hợp, hệ thống sẽ đếm 3 2 1 rồi vào set đầu tiên."], false, () => {
    state.startupAnnouncementUntilMs = 0;
  });
}

function _numberVi(n) {
  const map = {
    0: "không",
    1: "một",
    2: "hai",
    3: "ba",
    4: "bốn",
    5: "năm",
    6: "sáu",
    7: "bảy",
    8: "tám",
    9: "chín",
    10: "mười",
  };
  if (Object.prototype.hasOwnProperty.call(map, n)) {
    return map[n];
  }
  return String(n);
}

function processRealtimeAnnouncements(progress) {
  if (!progress) {
    return;
  }

  const inferredMode = progress.target_seconds ? "hold" : "reps";

  if (inferredMode === "reps" && progress.rep_count > state.lastRepAnnounced) {
    for (let i = state.lastRepAnnounced + 1; i <= progress.rep_count; i += 1) {
      speak([_numberVi(i)]);
    }
    state.lastRepAnnounced = progress.rep_count;
  }

  if (inferredMode === "hold") {
    const sec = Math.floor(progress.hold_seconds || 0);
    if (sec > state.lastHoldSecondAnnounced) {
      for (let s = state.lastHoldSecondAnnounced + 1; s <= sec; s += 1) {
        if (s >= 1) {
          speak([`${_numberVi(s)} giây`]);
        }
      }
      state.lastHoldSecondAnnounced = sec;
    }
  }

  if (progress.phase !== state.lastPhaseAnnounced) {
    state.lastPhaseAnnounced = progress.phase;
    if (progress.phase === "rest_pending_confirmation") {
      speak(["Hoàn thành set. Mời bạn quay lại thiết bị để xác nhận."]);
    } else if (progress.phase === "exercise_pending_confirmation") {
      speak(["Hoàn thành bài tập. Mời bạn xác nhận để sang bài tiếp theo."]);
    } else if (progress.phase === "done") {
      speak(["Buổi tập đã hoàn thành."]);
    }
  }

  if (progress.phase === "active_set" && state.mediaRecorder && !state.segmentUploadPromise) {
    const targetReps = Number(progress.target_reps || 0);
    const targetSeconds = Number(progress.target_seconds || 0);
    const reachedRepTarget = targetReps > 0 && Number(progress.rep_count || 0) >= targetReps;
    const reachedHoldTarget = targetSeconds > 0 && Number(progress.hold_seconds || 0) >= targetSeconds;
    if (reachedRepTarget || reachedHoldTarget) {
      const segmentKey = segmentKeyFromProgress(progress);
      if (segmentKey) {
        state.closedSegmentSetKeys[segmentKey] = true;
      }
      stopSegmentRecording(progress).catch((err) => {
        setLog("frameLog", `Không thể dừng segment đúng mốc: ${String(err)}`);
      });
    }
  }

  if (
    progress.phase === "active_set"
    && !state.mediaRecorder
    && !state.segmentUploadPromise
  ) {
    const mode = Number(progress.target_seconds || 0) > 0 ? "hold" : "reps";
    const signal = Number(state.lastSignalForSegment || 0);
    state.segmentStartSignalWindow.push(signal);
    if (state.segmentStartSignalWindow.length > 14) {
      state.segmentStartSignalWindow.shift();
    }
    const window = state.segmentStartSignalWindow;
    const minSignal = window.length ? Math.min(...window) : signal;
    const maxSignal = window.length ? Math.max(...window) : signal;
    const motionRange = Math.max(0, maxSignal - minSignal);
    const canStartRecording = mode === "hold"
      ? Boolean(progress.tracking_started)
      : (Boolean(progress.tracking_started) && motionRange >= 0.18);

    if (canStartRecording) {
      maybeStartSegmentRecording(progress).catch((err) => {
        setLog("frameLog", `Không thể bắt đầu segment khi đã vào chuyển động: ${String(err)}`);
      });
    }
  }
}

function handleAutoStartCountdown(autoReady, startPostureType = "vertical") {
  const enabled = byId("autoStartWhenReady").checked;
  if (!enabled) {
    state.readinessStableFrames = 0;
    state.countdownActive = false;
    state.countdownLastSpoken = -1;
    state.forceStartFrame = false;
    return false;
  }

  const countdownMs = getReadinessProfile(startPostureType).countdownMs;
  const countdownSec = Math.max(1, Math.ceil(countdownMs / 1000));
  const requiredStableFrames = 2;
  const now = Date.now();

  // Avoid auto-start while long startup guidance is still being spoken.
  if (now < Number(state.startupAnnouncementUntilMs || 0)) {
    state.readinessStableFrames = 0;
    return false;
  }

  // Browser speech onend can occasionally be missed; force-start once countdown window has elapsed.
  if (state.countdownActive) {
    const elapsedMs = now - Number(state.countdownStartedAt || 0);
    if (elapsedMs >= (countdownMs + 1200)) {
      state.countdownActive = false;
      state.forceStartFrame = true;
      state.signalBlockUntilMs = now + 350;
      return true;
    }
  }

  if (!autoReady) {
    state.readinessStableFrames = 0;
    
    if (state.countdownActive) {
      // The user moved right before or during the countdown (e.g. reflex anticipation).
      // We do NOT cancel the countdown here, so the speech can finish and start the set.
      return false;
    }

    state.forceStartFrame = false;
    if (now - state.lastNotReadyAnnounceAt > 4000) {
      state.lastNotReadyAnnounceAt = now;
      speak(["Chưa vào tư thế chuẩn."]);
    }
    return false;
  }

  state.readinessStableFrames += 1;
  if (state.readinessStableFrames < requiredStableFrames) {
    return false;
  }

  if (!state.countdownActive) {
    state.countdownActive = true;
    state.countdownStartedAt = now;
    speak([`Sẵn sàng... 3... 2... 1... Bắt đầu`], true, () => {
      if (state.countdownActive) {
        state.countdownActive = false;
        state.forceStartFrame = true;
        state.signalBlockUntilMs = Date.now() + 350;
      }
    });
    return false;
  }

  // Waiting for TTS to finish. If readiness fails, it will be cancelled by the readiness check block above.
  return false;
}

function currentTemplateIdFromProgress() {
  if (!state.workoutSteps.length) {
    return null;
  }
  const idx = state.latestProgress && Number.isInteger(state.latestProgress.step_index)
    ? state.latestProgress.step_index
    : 0;
  const safeIdx = Math.max(0, Math.min(idx, state.workoutSteps.length - 1));
  return state.workoutSteps[safeIdx].template_id;
}

function currentTemplateModeFromProgress() {
  const templateId = currentTemplateIdFromProgress();
  if (!templateId) {
    return null;
  }
  const tpl = state.templates.find((item) => item.template_id === templateId);
  return tpl ? tpl.mode : null;
}

function currentTemplateFromProgress() {
  const templateId = currentTemplateIdFromProgress();
  if (!templateId) {
    return null;
  }
  return state.templates.find((item) => item.template_id === templateId) || null;
}

function renderTemplateDebugOverlay(progress = state.latestProgress, mediaTimeSec = null) {
  const video = byId("debugTemplateVideo");
  const canvas = byId("debugTemplateCanvas");
  if (!video || !canvas || !state.sessionId || !progress) {
    clearCanvas(canvas);
    return;
  }
  const tpl = currentTemplateFromProgress();
  if (!tpl) {
    clearCanvas(canvas);
    return;
  }
  const profile = state.templateProfiles[tpl.template_id] || null;
  if (useBakedTemplateDebugVideo(profile)) {
    clearCanvas(canvas);
    return;
  }
  const sample = sampleForTemplateVideo(profile, video, tpl, mediaTimeSec);
  syncDebugTemplateStage(video);
  drawSampleOnVideoOverlay(canvas, video, sample, DEBUG_TEMPLATE_OVERLAY_STYLE);
}

function startDebugTemplateOverlayLoop() {
  stopDebugTemplateOverlayLoop();
  const tpl = currentTemplateFromProgress();
  const profile = tpl ? (state.templateProfiles[tpl.template_id] || null) : null;
  if (useBakedTemplateDebugVideo(profile)) {
    clearCanvas(byId("debugTemplateCanvas"));
    return;
  }
  const video = byId("debugTemplateVideo");
  if (video && typeof video.requestVideoFrameCallback === "function") {
    const step = (_now, metadata) => {
      if (!video || video.paused || video.ended) {
        state.debugTemplateOverlayVideoCbId = null;
        return;
      }
      const mediaTimeSec = Number(metadata && metadata.mediaTime);
      renderTemplateDebugOverlay(state.latestProgress, Number.isFinite(mediaTimeSec) ? mediaTimeSec : null);
      state.debugTemplateOverlayVideoCbId = video.requestVideoFrameCallback(step);
    };
    state.debugTemplateOverlayVideoCbId = video.requestVideoFrameCallback(step);
    return;
  }

  const step = () => {
    const v = byId("debugTemplateVideo");
    if (!v) {
      state.debugTemplateOverlayRaf = null;
      return;
    }
    renderTemplateDebugOverlay();
    if (v.paused || v.ended) {
      state.debugTemplateOverlayRaf = null;
      return;
    }
    state.debugTemplateOverlayRaf = requestAnimationFrame(step);
  };
  state.debugTemplateOverlayRaf = requestAnimationFrame(step);
}

function initTemplateDebugVideoBindings() {
  const video = byId("debugTemplateVideo");
  if (!video) {
    return;
  }
  const renderNow = () => renderTemplateDebugOverlay();
  video.addEventListener("loadedmetadata", () => {
    syncDebugTemplateStage(video);
    renderNow();
  });
  video.addEventListener("play", () => startDebugTemplateOverlayLoop());
  video.addEventListener("pause", () => {
    stopDebugTemplateOverlayLoop();
    renderNow();
  });
  video.addEventListener("ended", () => {
    stopDebugTemplateOverlayLoop();
    renderNow();
  });
  video.addEventListener("seeking", renderNow);
  video.addEventListener("seeked", renderNow);
  video.addEventListener("timeupdate", renderNow);
  window.addEventListener("resize", renderNow);
}

function updateTemplateDebugPanel(progress = state.latestProgress) {
  const video = byId("debugTemplateVideo");
  const meta = byId("debugTemplateMeta");
  const log = byId("debugTemplateLog");
  const canvas = byId("debugTemplateCanvas");
  if (!video || !meta || !log) {
    return;
  }

  if (!state.sessionId || !progress) {
    stopDebugTemplateOverlayLoop();
    if (typeof video.__trimCleanup === "function") {
      video.__trimCleanup();
      video.__trimCleanup = null;
    }
    video.removeAttribute("src");
    video.load();
    state.debugTemplateCurrentTemplateId = null;
    state.debugTemplateCurrentVideoSrc = "";
    clearCanvas(canvas);
    meta.textContent = "Chưa bắt đầu phiên tập";
    log.textContent = "Template debug: --";
    return;
  }

  const tpl = currentTemplateFromProgress();
  if (!tpl) {
    stopDebugTemplateOverlayLoop();
    state.debugTemplateCurrentVideoSrc = "";
    clearCanvas(canvas);
    meta.textContent = "Không tìm thấy template cho step hiện tại";
    log.textContent = `session: ${state.sessionId}\nstep: ${Number(progress.step_index || 0)}\nphase: ${progress.phase || "--"}`;
    return;
  }

  const profile = state.templateProfiles[tpl.template_id] || null;

  const desiredSrc = getTemplateVideoUrl(tpl, profile);
  const desiredSrcKey = String(desiredSrc || "");
  const templateChanged = state.debugTemplateCurrentTemplateId !== tpl.template_id;
  const sourceChanged = desiredSrcKey !== String(state.debugTemplateCurrentVideoSrc || "");
  if (templateChanged || sourceChanged) {
    stopDebugTemplateOverlayLoop();
    state.debugTemplateCurrentTemplateId = tpl.template_id;
    state.debugTemplateCurrentVideoSrc = desiredSrcKey;
    if (desiredSrc) {
      if (sourceChanged) {
        video.src = desiredSrc;
        video.load();
      }
    } else {
      if (video.getAttribute("src")) {
        video.removeAttribute("src");
        video.load();
      }
    }
    applyTrimLoopToVideo(video, tpl, { autoPlayIfReady: true });
    const trimRange = getTemplateTrimRange(tpl, video);
    video.currentTime = trimRange.start;
    video.play().catch(() => {
      // Browser may block autoplay; controls are still available.
    });
  }

  const adaptive = profile && profile.adaptive_thresholds ? profile.adaptive_thresholds : null;
  const readyCfg = adaptive && adaptive.readiness ? adaptive.readiness : null;
  const trackingCfg = adaptive && adaptive.tracking ? adaptive.tracking : null;
  const poseSampleCount = Array.isArray(profile && profile.pose_samples) ? profile.pose_samples.length : 0;
  const anchorCount = Array.isArray(profile && profile.anchor_pose_samples)
    ? profile.anchor_pose_samples.length
    : (profile && profile.anchor_pose_sample ? 1 : 0);
  const bakedDebugVideo = useBakedTemplateDebugVideo(profile);
  const poseTimelineJsonUrl = getTemplatePoseTimelineJsonUrl(profile);
  const frozenClip = isFrozenTemplateVideo(tpl);
  const trimRange = getTemplateTrimRange(tpl, video);

  if (canvas) {
    renderTemplateDebugOverlay(progress);
  }
  if (bakedDebugVideo) {
    stopDebugTemplateOverlayLoop();
  } else if (!video.paused && !video.ended && !state.debugTemplateOverlayRaf && !state.debugTemplateOverlayVideoCbId) {
    startDebugTemplateOverlayLoop();
  }

  meta.textContent = `Template: ${tpl.name} (${tpl.mode}) | Step ${Number(progress.step_index || 0) + 1} | Phase: ${progress.phase || "--"}`;
  log.textContent = [
    `template_id: ${tpl.template_id}`,
    `video_uri: ${tpl.video_uri || "--"}`,
    `profile_ready: ${profile ? "yes" : "no"}`,
    `feature_samples: ${Number((profile && profile.samples) || 0)}`,
    `pose_samples: ${poseSampleCount}`,
    `anchors: ${anchorCount}`,
    `template_video_type: ${frozenClip ? "frozen" : "source"}`,
    `baked_debug_video: ${bakedDebugVideo ? "yes" : "no"}`,
    `pose_timeline_json: ${poseTimelineJsonUrl || "--"}`,
    `trim_window_active: ${trimRange.hasTrim ? "yes" : "no"}`,
    `overlay_source: ${bakedDebugVideo ? "baked_pose_video" : (poseSampleCount > 0 ? "pose_samples@video_time" : "anchor_pose_sample")}`,
    `readiness_similarity_min: ${readyCfg ? Number(readyCfg.similarity_min ?? 0).toFixed(3) : "--"}`,
    `readiness_anchor_tolerance: ${readyCfg ? Number(readyCfg.anchor_tolerance ?? 0).toFixed(3) : "--"}`,
    `rep_high_enter: ${trackingCfg ? Number(trackingCfg.rep_high_enter ?? 0).toFixed(3) : "--"}`,
    `rep_low_exit: ${trackingCfg ? Number(trackingCfg.rep_low_exit ?? 0).toFixed(3) : "--"}`,
    `hold_threshold: ${trackingCfg ? Number(trackingCfg.hold_threshold ?? 0).toFixed(3) : "--"}`,
    `hold_stop_threshold: ${trackingCfg ? Number(trackingCfg.hold_stop_threshold ?? 0).toFixed(3) : "--"}`,
  ].join("\n");
}

function resetTemplateDebugPanel() {
  updateTemplateDebugPanel(null);
}

function isHorizontalPosture(landmarks) {
  return poseEngine.isHorizontalPosture(landmarks);
}

function normalizeSignalForTemplate(templateId, rawSignal, mode) {
  return poseEngine.normalizeSignalForTemplate(templateId, rawSignal, mode);
}

function featureFromLandmarks(landmarks) {
  return poseEngine.featureFromLandmarks(landmarks);
}

function _visibleRatio(landmarks, indices, threshold = 0.4) {
  return poseEngine.visibleRatio(landmarks, indices, threshold);
}

function poseQualityScore(landmarks) {
  return poseEngine.poseQualityScore(landmarks);
}

function _angleAt(a, b, c) {
  return poseEngine.angleAt(a, b, c);
}

function _kneeExtensionDeg(landmarks) {
  return poseEngine.kneeExtensionDeg(landmarks);
}

function _hipExtensionDeg(landmarks) {
  return poseEngine.hipExtensionDeg(landmarks);
}

function _estimateOrientationFromLandmarks(landmarks) {
  return poseEngine.estimateOrientationFromLandmarks(landmarks);
}

function _estimateOrientationFromSample(sample) {
  return poseEngine.estimateOrientationFromSample(sample);
}

function _modeOf(values, fallback = "unknown") {
  return poseEngine.modeOf(values, fallback);
}

function _modeOfKnown(values, fallback = "unknown", unknownToken = "unknown") {
  return poseEngine.modeOfKnown(values, fallback, unknownToken);
}

function _sliceSamplesForOrientation(profile, mode = "reps") {
  return poseEngine.sliceSamplesForOrientation(profile, mode);
}

function _phaseSignalFromFeature(profile, featureVec) {
  return poseEngine.phaseSignalFromFeature(profile, featureVec);
}

function _sliceSamplesForBasePose(profile, mode = "reps") {
  return poseEngine.sliceSamplesForBasePose(profile, mode);
}

function _detectTemplateBasePose(profile, mode = "reps") {
  return poseEngine.detectTemplateBasePose(profile, mode);
}

function _detectTemplateOrientation(profile, mode = "reps") {
  return poseEngine.detectTemplateOrientation(profile, mode);
}

function _orientationLabel(orientation) {
  return poseEngine.orientationLabel(orientation);
}

function _detectTemplateView(profile, mode = "reps") {
  return poseEngine.detectTemplateView(profile, mode);
}

function _sampleIsHorizontal(sample) {
  return poseEngine.sampleIsHorizontal(sample);
}

function inferStartPostureType(profile, landmarks = null, mode = "reps") {
  return poseEngine.inferStartPostureType(profile, landmarks, mode);
}

function getReadinessProfile(startPostureType) {
  return poseEngine.getReadinessProfile(startPostureType);
}

function _startPhaseFromProfile(profile) {
  return poseEngine.startPhaseFromProfile(profile);
}

function _phaseWrapDistance(a, b) {
  return poseEngine.phaseWrapDistance(a, b);
}

function _updateStartGateHistory(templateId, score) {
  return poseEngine.updateStartGateHistory(templateId, score);
}

function _viewGateDetailForTemplate(landmarks, profile, templateId = null, mode = "reps") {
  return poseEngine.viewGateDetailForTemplate(landmarks, profile, templateId, mode);
}

function _viewReadyForTemplate(landmarks, profile, templateId = null, mode = "reps") {
  return poseEngine.viewReadyForTemplate(landmarks, profile, templateId, mode);
}

function _holdPoseStillValid(landmarks, profile, score, templateId = null, mode = "hold") {
  return poseEngine.holdPoseStillValid(landmarks, profile, score, templateId, mode);
}

function readinessFromLandmarks(landmarks, profile = null, score = null, mode = null, templateId = null) {
  return poseEngine.readinessFromLandmarks(landmarks, profile, score, mode, templateId);
}

const FRAME_KEYPOINT_INDEX = {
  nose: 0,
  left_eye: 2,
  right_eye: 5,
  left_ear: 7,
  right_ear: 8,
  left_shoulder: 11,
  right_shoulder: 12,
  left_elbow: 13,
  right_elbow: 14,
  left_wrist: 15,
  right_wrist: 16,
  left_hip: 23,
  right_hip: 24,
  left_knee: 25,
  right_knee: 26,
  left_ankle: 27,
  right_ankle: 28,
};

function buildFrameModelFromLandmarks(landmarks, frameWidth, frameHeight) {
  if (!Array.isArray(landmarks) || !landmarks.length) {
    return null;
  }

  const width = Math.max(1, Number(frameWidth || 0));
  const height = Math.max(1, Number(frameHeight || 0));
  const keypoints = {};

  for (const [name, idx] of Object.entries(FRAME_KEYPOINT_INDEX)) {
    const lm = landmarks[idx];
    if (!lm) {
      continue;
    }
    keypoints[name] = {
      x: Number(lm.x ?? 0) * width,
      y: Number(lm.y ?? 0) * height,
      score: Math.max(0, Math.min(1, Number(lm.visibility ?? 0))),
    };
  }

  return {
    keypoints,
    frame_width: width,
    frame_height: height,
  };
}

function signalAndMatchFromProfile(featurePack, profile, mode = null) {
  return poseEngine.signalAndMatchFromProfile(featurePack, profile, mode);
}

function taskResultToLandmarks(result) {
  const imagePoses = Array.isArray(result?.landmarks) ? result.landmarks : null;
  if (!imagePoses || !imagePoses.length) {
    return null;
  }

  const image = imagePoses[0];
  const worldPoses = Array.isArray(result?.worldLandmarks) ? result.worldLandmarks : null;
  const world = worldPoses && worldPoses.length ? worldPoses[0] : null;

  return image.map((lm, idx) => {
    const wlm = world && idx < world.length ? world[idx] : null;
    return {
      x: Number(lm?.x ?? 0),
      y: Number(lm?.y ?? 0),
      z: Number(lm?.z ?? 0),
      visibility: Number(lm?.visibility ?? lm?.presence ?? 0),
      wx: Number(wlm?.x),
      wy: Number(wlm?.y),
      wz: Number(wlm?.z),
      worldVisibility: Number(wlm?.visibility ?? wlm?.presence ?? lm?.visibility ?? lm?.presence ?? 0),
    };
  });
}

// ---------------------------------------------------------------------------
// Landmark EMA Smoother – eliminates jitter from raw MediaPipe output
// Uses adaptive alpha: slow joints get heavy smoothing, fast ones stay responsive.
// ---------------------------------------------------------------------------
const landmarkSmoother = {
  prev: null,
  baseAlpha: 0.30,   // base smoothing factor (lower = smoother, 0.2-0.4 recommended)
  velocityCutoff: 0.04, // distance threshold to consider "fast movement"

  reset() {
    this.prev = null;
  },

  smooth(landmarks) {
    if (!landmarks || !landmarks.length) {
      this.prev = null;
      return landmarks;
    }

    if (!this.prev || this.prev.length !== landmarks.length) {
      // First frame or landmark count changed – just store and pass through
      this.prev = landmarks.map(lm => ({ ...lm }));
      return landmarks;
    }

    const smoothed = landmarks.map((lm, i) => {
      const p = this.prev[i];
      if (!p) return lm;

      // Compute velocity (displacement since last frame)
      const dx = lm.x - p.x;
      const dy = lm.y - p.y;
      const dz = lm.z - p.z;
      const velocity = Math.sqrt(dx * dx + dy * dy + dz * dz);

      // Adaptive alpha: fast movement → higher alpha (more responsive)
      // slow/stationary → lower alpha (more smoothing to kill jitter)
      const speedFactor = Math.min(1.0, velocity / this.velocityCutoff);
      const alpha = this.baseAlpha + (0.45 * speedFactor);

      // Low visibility → trust previous more (more smoothing)
      const vis = Math.max(0, Math.min(1, lm.visibility));
      const visAlpha = vis < 0.5 ? alpha * 0.5 : alpha;

      return {
        x: p.x + visAlpha * (lm.x - p.x),
        y: p.y + visAlpha * (lm.y - p.y),
        z: p.z + visAlpha * (lm.z - p.z),
        visibility: lm.visibility,
        wx: (p.wx != null && lm.wx != null) ? p.wx + visAlpha * (lm.wx - p.wx) : lm.wx,
        wy: (p.wy != null && lm.wy != null) ? p.wy + visAlpha * (lm.wy - p.wy) : lm.wy,
        wz: (p.wz != null && lm.wz != null) ? p.wz + visAlpha * (lm.wz - p.wz) : lm.wz,
        worldVisibility: lm.worldVisibility,
      };
    });

    this.prev = smoothed.map(lm => ({ ...lm }));
    return smoothed;
  }
};

async function createPoseLandmarkerWithFallback(vision) {
  let lastError = null;
  for (const modelAssetPath of POSE_MODEL_CANDIDATES) {
    try {
      return await PoseLandmarker.createFromOptions(vision, {
        baseOptions: { modelAssetPath },
        runningMode: "VIDEO",
        numPoses: 1,
        minPoseDetectionConfidence: 0.5,
        minPosePresenceConfidence: 0.5,
        minTrackingConfidence: 0.5,
        outputSegmentationMasks: false,
      });
    } catch (err) {
      lastError = err;
    }
  }
  throw lastError || new Error("Failed to initialize Pose Landmarker model");
}

async function initPose() {
  if (state.pose) {
    return;
  }

  if (!state.vision) {
    state.vision = await FilesetResolver.forVisionTasks(
      "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm"
    );
  }

  state.pose = await createPoseLandmarkerWithFallback(state.vision);
}

async function startCamera() {
  if (state.cameraStream) {
    return;
  }
  try {
    await initPose();
    const stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: "user",
        width: { ideal: 640 },
        height: { ideal: 360 },
        frameRate: { ideal: 30, max: 30 }
      },
      audio: false
    });
    const video = byId("liveCamera");
    const overlay = byId("liveCameraOverlay");
    video.srcObject = stream;
    state.cameraStream = stream;
    state.currentLandmarks = null;
    landmarkSmoother.reset();
    poseEngine.resetRuntime();
    state.poseTimestampMs = 0;
    state.noLandmarkFrames = 0;
    state.cameraFrameInFlight = false;
    state.poseSendFailures = 0;
    state.lastPoseSuccessAt = Date.now();
    state.poseFailureSinceAt = 0;
    setCameraPill(true);

    const videoTrack = stream.getVideoTracks()[0];
    if (videoTrack) {
      videoTrack.addEventListener("ended", () => scheduleCameraRecovery("track ended"));
    }

    await new Promise((resolve) => {
      if (video.readyState >= 1) {
        resolve();
        return;
      }
      video.onloadedmetadata = () => resolve();
    });

    const videoWidth = Math.max(1, Number(video.videoWidth || 640));
    const videoHeight = Math.max(1, Number(video.videoHeight || 480));
    overlay.width = videoWidth;
    overlay.height = videoHeight;

    if (!state.inferenceCanvas) {
      state.inferenceCanvas = document.createElement("canvas");
    }
    state.inferenceCanvas.width = videoWidth;
    state.inferenceCanvas.height = videoHeight;

    // Show only synchronized rendered frames on overlay (Notebook-like display).
    video.style.visibility = "hidden";

    const stage = video.closest(".video-stage");
    if (stage) {
      stage.style.aspectRatio = `${videoWidth} / ${videoHeight}`;
    }

    const loop = async () => {
      if (!state.cameraStream || !state.pose) {
        return;
      }
      if (video.readyState < 2 || state.cameraFrameInFlight) {
        state.cameraLoopRaf = requestAnimationFrame(loop);
        return;
      }
      state.cameraFrameInFlight = true;
      const inferenceCanvas = state.inferenceCanvas;
      const inferenceCtx = inferenceCanvas ? inferenceCanvas.getContext("2d") : null;
      try {
        if (!inferenceCanvas || !inferenceCtx) {
          throw new Error("Inference canvas not ready");
        }

        // Capture a single snapshot used for both inference and rendering to avoid visual drift.
        inferenceCtx.drawImage(video, 0, 0, inferenceCanvas.width, inferenceCanvas.height);
        const nowMs = Math.floor(performance.now());
        state.poseTimestampMs = Math.max(state.poseTimestampMs + 1, nowMs);
        const result = state.pose.detectForVideo(inferenceCanvas, state.poseTimestampMs);
        const rawLandmarks = taskResultToLandmarks(result);
        state.currentLandmarks = landmarkSmoother.smooth(rawLandmarks);

        // Render from the exact processed frame to keep display synchronized like notebook loop.
        drawNotebookStyleLiveFrame(inferenceCanvas, state.currentLandmarks);
        // processLocalFrame handled via sendOneFrame/startAutoFeed
        state.poseSendFailures = 0;
        state.lastPoseSuccessAt = Date.now();
        state.poseFailureSinceAt = 0;
      } catch (_) {
        state.poseSendFailures += 1;
        if (!state.poseFailureSinceAt) {
          state.poseFailureSinceAt = Date.now();
        }

        // Only recover on sustained stalls. Avoid restarting camera in active set/recording.
        const stallMs = Date.now() - state.poseFailureSinceAt;
        if (state.poseSendFailures >= 120 && stallMs >= 4000) {
          const activeSet = Boolean(state.latestProgress && state.latestProgress.phase === "active_set");
          const recording = Boolean(state.mediaRecorder);
          if (!activeSet && !recording) {
            scheduleCameraRecovery(`pose pipeline stalled ${stallMs}ms`);
            state.poseSendFailures = 0;
            state.poseFailureSinceAt = 0;
          } else {
            // Keep trying inference without hard-restarting camera during active workout capture.
            state.poseSendFailures = 80;
          }
        }
      } finally {
        state.cameraFrameInFlight = false;
      }
      state.cameraLoopRaf = requestAnimationFrame(loop);
    };
    state.cameraLoopRaf = requestAnimationFrame(loop);
  } catch (err) {
    setLog("frameLog", "Không mở được camera: " + String(err));
  }
}

function stopCamera() {
  if (!state.cameraStream) {
    return;
  }
  if (state.cameraRecoveryTimer) {
    clearTimeout(state.cameraRecoveryTimer);
    state.cameraRecoveryTimer = null;
  }
  if (state.cameraLoopRaf) {
    cancelAnimationFrame(state.cameraLoopRaf);
    state.cameraLoopRaf = null;
  }
  state.cameraLoopVideoCbId = null;
  state.cameraStream.getTracks().forEach((t) => t.stop());
  state.cameraStream = null;
  state.cameraFrameInFlight = false;
  landmarkSmoother.reset();
  state.poseTimestampMs = 0;
  state.poseSendFailures = 0;
  state.lastPoseSuccessAt = 0;
  state.poseFailureSinceAt = 0;
  const liveVideo = byId("liveCamera");
  liveVideo.srcObject = null;
  liveVideo.style.visibility = "visible";
  state.currentLandmarks = null;
  poseEngine.resetRuntime();
  const overlay = byId("liveCameraOverlay");
  if (overlay) {
    const ctx = overlay.getContext("2d");
    ctx.clearRect(0, 0, overlay.width, overlay.height);
  }
  setCameraPill(false);
  setMatchPill("--");
  setOrientationDebug([]);
}

function scheduleCameraRecovery(reason = "unknown") {
  if (state.cameraRecoveryTimer) {
    return;
  }

  const wasAutoFeed = Boolean(state.autoTimer);
  state.cameraRecoveryTimer = setTimeout(async () => {
    state.cameraRecoveryTimer = null;
    stopAutoFeed();
    stopCamera();
    try {
      await startCamera();
      if (wasAutoFeed) {
        startAutoFeed();
      }
      setLog("frameLog", `Da khoi dong lai camera pose (${reason}).`);
    } catch (err) {
      setLog("frameLog", `Khoi dong lai camera that bai (${reason}): ${String(err)}`);
    }
  }, 400);
}

function computePoseSignal() {
  const landmarks = state.currentLandmarks;
  const templateId = currentTemplateIdFromProgress();
  const templateMode = currentTemplateModeFromProgress();
  const profile = templateId ? state.templateProfiles[templateId] : null;
  const modeKey = templateMode || "reps";
  const templateOrientation = _detectTemplateOrientation(profile, modeKey);
  const basePose = _detectTemplateBasePose(profile, modeKey);
  if (!landmarks || landmarks.length < 29) {
    state.forceStartFrame = false;
    state.countdownActive = false;
    state.countdownLastSpoken = -1;
    state.readinessStableFrames = 0;
    state.noLandmarkFrames += 1;
    byId("signalInput").value = "0.00";
    byId("signalValue").textContent = "0.00";
    setMatchPill("không phát hiện người");
    setOrientationDebug([
      "Orientation debug",
      `template: ${templateId || "--"} | mode: ${templateMode || "--"}`,
      `template base: ${basePose.postureClass || "unknown"}${basePose.lyingType && basePose.lyingType !== "unknown" ? `/${basePose.lyingType}` : ""}`,
      "user: no-landmarks"
    ]);
    poseEngine.setRealtimeMetrics(0, false);
    return {
      signal: 0,
      readiness: false,
      readinessStrict: false
    };
  }
  state.noLandmarkFrames = 0;

  const quality = poseQualityScore(landmarks);
  const postureType = inferStartPostureType(profile, landmarks, modeKey);
  const qualityMin = postureType === "horizontal" ? 0.34 : 0.42;
  const trunkCoverage = _visibleRatio(landmarks, [11, 12, 23, 24], 0.45);
  const lowerCoverage = _visibleRatio(landmarks, [23, 24, 25, 26, 27, 28], 0.45);

  if (trunkCoverage < 0.5 || lowerCoverage < 0.25) {
    state.forceStartFrame = false;
    state.countdownActive = false;
    state.countdownLastSpoken = -1;
    state.readinessStableFrames = 0;
    byId("signalInput").value = "0.00";
    byId("signalValue").textContent = "0.00";
    setMatchPill(`khung hinh thieu landmark (trunk ${trunkCoverage.toFixed(2)}, chan ${lowerCoverage.toFixed(2)})`);
    setOrientationDebug([
      "Orientation debug",
      `template: ${templateId || "--"} | mode: ${templateMode || "--"}`,
      `template base: ${basePose.postureClass || "unknown"}${basePose.lyingType && basePose.lyingType !== "unknown" ? `/${basePose.lyingType}` : ""}`,
      `expected posture: ${postureType}`,
      `coverage fail: trunk=${trunkCoverage.toFixed(2)}, lower=${lowerCoverage.toFixed(2)}`
    ]);
    poseEngine.setRealtimeMetrics(0, false);
    return {
      signal: 0,
      readiness: false,
      readinessStrict: false
    };
  }

  // Enforce strict completeness gating
  if (window.MotionMath && window.MotionMath.completenessScore) {
      const sComp = window.MotionMath.completenessScore(landmarks);
      const sFrame = window.MotionMath.framingScore(landmarks);
      const minComp = profile && profile.readiness_min_completeness != null ? Number(profile.readiness_min_completeness) : 0.72;
      if (sComp < minComp || sFrame < 0.2) {
          if (state.countdownActive) speak([], true);
          state.forceStartFrame = false;
          state.countdownActive = false;
          state.countdownLastSpoken = -1;
          state.readinessStableFrames = 0;
          byId("signalInput").value = "0.00";
          byId("signalValue").textContent = "0.00";
          setMatchPill(`khong du bo phan (${(sComp * 100).toFixed(0)}% < ${(minComp * 100).toFixed(0)}%)`);
          setOrientationDebug([
            "Orientation debug",
            `completeness fail: ${sComp.toFixed(2)} < ${minComp.toFixed(2)}`
          ]);
          poseEngine.setRealtimeMetrics(0, false);
          return {
            signal: 0,
            readiness: false,
            readinessStrict: false
          };
      }
  }

  if (quality < qualityMin) {
    state.forceStartFrame = false;
    state.countdownActive = false;
    state.countdownLastSpoken = -1;
    state.readinessStableFrames = 0;
    byId("signalInput").value = "0.00";
    byId("signalValue").textContent = "0.00";
    setMatchPill(`pose quality thap (${quality.toFixed(2)})`);
    setOrientationDebug([
      "Orientation debug",
      `template: ${templateId || "--"} | mode: ${templateMode || "--"}`,
      `template base: ${basePose.postureClass || "unknown"}${basePose.lyingType && basePose.lyingType !== "unknown" ? `/${basePose.lyingType}` : ""}`,
      `expected posture: ${postureType}`,
      `quality: ${quality.toFixed(2)} < ${qualityMin.toFixed(2)}`
    ]);
    poseEngine.setRealtimeMetrics(0, false);
    return {
      signal: 0,
      readiness: false,
      readinessStrict: false
    };
  }

  const featurePack = featureFromLandmarks(landmarks);
  const score = signalAndMatchFromProfile(featurePack, profile, templateMode);
  const normalizedSignal = normalizeSignalForTemplate(templateId, score.signal, modeKey);
  const startPostureType = inferStartPostureType(profile, landmarks, modeKey);
  const orientation = _estimateOrientationFromLandmarks(landmarks);
  const gateDetail = _viewGateDetailForTemplate(landmarks, profile, templateId, modeKey);
  const framePoseValid = gateDetail.ok;
  const minSimilarityForCount = startPostureType === "horizontal" ? 0.34 : 0.26;
  const similarityValid = Number(score.similarity || 0) >= minSimilarityForCount;
  const holdPoseValid = templateMode === "hold"
    ? _holdPoseStillValid(landmarks, profile, score, templateId, modeKey)
    : (framePoseValid && similarityValid);
  const finalSignal = holdPoseValid ? normalizedSignal : 0;

  byId("signalInput").value = finalSignal.toFixed(2);
  byId("signalValue").textContent = finalSignal.toFixed(2);
  setMatchPill(`${(score.similarity * 100).toFixed(1)}% | ${_orientationLabel(orientation)}`);

  const autoReady = readinessFromLandmarks(landmarks, profile, score, templateMode, templateId);
  const allowManualReady = byId("readinessInput").checked;
  setOrientationDebug([
    "Orientation debug",
    `template: ${templateId || "--"} | mode: ${templateMode || "--"}`,
    `template inferred pose(video): ${_orientationLabel(templateOrientation)}`,
    `template base(video): ${basePose.postureClass || "unknown"}${basePose.lyingType && basePose.lyingType !== "unknown" ? `/${basePose.lyingType}` : ""} | conf: ${Number(basePose.confidence || 0).toFixed(2)}`,
    `expected posture: ${gateDetail.expectedPosture || startPostureType}`,
    `template chestNz: ${Number.isFinite(Number(templateOrientation.chestNormalZ)) ? Number(templateOrientation.chestNormalZ).toFixed(2) : "--"} | floorScore: ${Number(templateOrientation.floorHorizontalScore || 0).toFixed(2)}`,
    `user lying: ${orientation.lyingType || "unknown"} | knee: ${Number.isFinite(Number(orientation.kneeExtensionDeg)) ? Number(orientation.kneeExtensionDeg).toFixed(0) : "--"} do | hip: ${Number.isFinite(Number(orientation.hipExtensionDeg)) ? Number(orientation.hipExtensionDeg).toFixed(0) : "--"} do`,
    `user chestNz: ${Number.isFinite(Number(orientation.chestNormalZ)) ? Number(orientation.chestNormalZ).toFixed(2) : "--"} | floorScore: ${Number(orientation.floorHorizontalScore || 0).toFixed(2)} | chestConf: ${Number(orientation.chestNormalConfidence || 0).toFixed(2)}`,
    `gate: ${String(gateDetail.reason || "unknown")}`,
    `sim: ${(Number(score.similarity || 0) * 100).toFixed(1)}% (min ${(minSimilarityForCount * 100).toFixed(0)}%) | visPenalty: ${(Number(score.visibility_penalty || 0) * 100).toFixed(1)}% | signal: ${finalSignal.toFixed(2)} | poseValid: ${String(framePoseValid)} | ready: ${String(autoReady && allowManualReady)}`
  ]);
  state.lastRealtimeSimilarity = Number(score.similarity || 0);
  state.lastRealtimeReadiness = Boolean(autoReady && allowManualReady);
  poseEngine.setRealtimeMetrics(state.lastRealtimeSimilarity, state.lastRealtimeReadiness);
  const readinessStrict = Boolean(finalSignal > 0 && framePoseValid && similarityValid);
  return {
    signal: finalSignal,
    readiness: autoReady && allowManualReady,
    readinessStrict,
    start_posture_type: startPostureType
  };
}

async function sendOneFrame() {
  if (!state.sessionId) return;
  const landmarks = state.currentLandmarks;
  if (!landmarks || !landmarks.length) return;
  const featureVec = featureFromLandmarks(landmarks);
  const quality = poseQualityScore(landmarks);
  const templateId = currentTemplateIdFromProgress();
  const templateMode = currentTemplateModeFromProgress();
  const profile = templateId ? state.templateProfiles[templateId] : null;
  const score = signalAndMatchFromProfile(featureVec, profile, templateMode);
  let normalizedSignal = normalizeSignalForTemplate(templateId, score.signal, templateMode);
  // Fix: ensure signal is LOW at rest position, HIGH at deep position.
  // PCA direction is arbitrary — if the template's start (rest) phase has high signal,
  // invert so the counter triggers on RETURN to rest, not at the deep part.
  if (profile && templateMode !== "hold") {
    const startPhase = _startPhaseFromProfile(profile);
    if (startPhase != null && startPhase > 0.55) {
      normalizedSignal = 1.0 - normalizedSignal;
    }
  }
  const startPostureType = inferStartPostureType(profile, landmarks);
  const holdPoseValid = templateMode === "hold"
    ? _holdPoseStillValid(landmarks, profile, score)
    : true;
  const finalSignal = holdPoseValid ? normalizedSignal : 0;
  state.lastSignalForSegment = finalSignal;
  byId("signalInput").value = finalSignal.toFixed(2);
  byId("signalValue").textContent = finalSignal.toFixed(2);
  setMatchPill((score.similarity * 100).toFixed(1) + "%");
  let autoReady = readinessFromLandmarks(landmarks, profile, score, templateMode, templateId);
  if (autoReady && window.MotionMath && window.MotionMath.completenessScore) {
      const sComp = window.MotionMath.completenessScore(landmarks);
      const sFrame = window.MotionMath.framingScore(landmarks);
      const minComp = profile && profile.readiness_min_completeness != null ? Number(profile.readiness_min_completeness) : 0.72;
      
      // Strict gating: if legs/body are hidden (e.g. sitting randomly), sComp drops significantly.
      if (sComp < minComp || sFrame < 0.2) {
          autoReady = false;
      }
  }
  const allowManualReady = byId("readinessInput").checked;
  const readiness = autoReady && allowManualReady;

  // Use local session if available, otherwise fall back to API
  if (state.localSession) {
    const previousProgress = state.latestProgress;
    const currentPhase = state.latestProgress && state.latestProgress.phase ? state.latestProgress.phase : "waiting_readiness";
    let readinessForServer = readiness;
    if (currentPhase === "waiting_readiness") {
      let countdownReady = false;
      if (!state.forceStartFrame) {
        countdownReady = handleAutoStartCountdown(readiness, startPostureType || "vertical");
      }
      if (state.forceStartFrame || countdownReady) {
        readinessForServer = true;
        state.forceStartFrame = false;
        state.lastRepAnnounced = 0;
        state.lastHoldSecondAnnounced = -1;
      } else {
        readinessForServer = false;
      }
    }
    const result = state.localSession.frameUpdate(finalSignal, Date.now(), readinessForServer);
    state.latestProgress = result;
    setLog("frameLog", result);
    processRealtimeAnnouncements(result);
    syncSessionTransition(previousProgress, result);
  } else {
    const body = {
      session_id: state.sessionId,
      signal: finalSignal,
      readiness: readiness,
      start_posture_type: startPostureType,
    };
    const res = await fetch("/v1/workout/session/frame", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      const previousProgress = state.latestProgress;
      const result = await res.json();
      state.latestProgress = result;
      setLog("frameLog", result);
      processRealtimeAnnouncements(result);
      syncSessionTransition(previousProgress, result);
    }
  }
}

async function confirmNext() {
  if (!state.sessionId) {
    setLog("frameLog", "Session not started.");
    return;
  }
  if (state.localSession) {
    const previousProgress = state.latestProgress;
    const result = state.localSession.confirm();
    state.latestProgress = result;
    updateConfirmButton(result);
    setLog("frameLog", result);
    speak(result.announcements || []);
    state.countdownActive = false;
    state.countdownLastSpoken = -1;
    state.forceStartFrame = false;
    state.startupAnnouncementUntilMs = 0;
    state.lastRepAnnounced = 0;
    state.lastHoldSecondAnnounced = -1;
    if (!result.done && result.phase === "waiting_readiness") {
      startCamera();
      startAutoFeed();
    }
    syncSessionTransition(previousProgress, result);
  }
}


async function finalizeSession(options = {}) {
  if (!state.sessionId) {
    setLog("finalizeLog", "Bạn chưa bắt đầu phiên luyện tập.");
    return;
  }
  if (state.isFinalizing) {
    return;
  }

  state.isFinalizing = true;
  stopAutoFeed();
  const stages = [
    "Đang chốt segment cuối...",
    "Đang đồng bộ video mẫu và video người tập...",
    "Đang tính điểm và phân tích sai lệch khớp...",
    "Đang tổng hợp báo cáo cuối buổi..."
  ];
  let stageIndex = 0;
  state.analysisStartedAt = Date.now();
  renderAnalysisProgress(stages[stageIndex], 0);
  clearAnalysisProgressTimer();
  state.analysisProgressTimer = setInterval(() => {
    const elapsedSec = Math.max(0, (Date.now() - state.analysisStartedAt) / 1000);
    if (stageIndex < stages.length - 1 && elapsedSec >= (stageIndex + 1) * 4) {
      stageIndex += 1;
    }
    renderAnalysisProgress(stages[stageIndex], elapsedSec);
  }, 400);

  try {
    await stopSegmentRecording(state.latestProgress);
    stopCamera();

    // Update progress bar on step 5
    const progressText = byId("analysisProgressText");
    const progressBar = byId("analysisProgressBar");
    if (progressText) progressText.textContent = "Đang gửi dữ liệu lên server để phân tích...";
    if (progressBar) progressBar.style.width = "15%";

    const result = await api("/v1/workout/session/finalize", "POST", { session_id: state.sessionId });
    setLog("finalizeLog", result);
    clearAnalysisProgressTimer();

    // Update progress to 100%
    if (progressText) progressText.textContent = "Phân tích hoàn tất!";
    if (progressBar) progressBar.style.width = "100%";

    renderAnalysisResults(result);
    await refreshAnalysisVideos();
    updateConfirmButton(state.latestProgress);
    lockWorkflowUI(false);
    if (options.autoTriggered) {
      speak(["Đã hoàn tất buổi tập. Bắt đầu phân tích sau tập."]);
    }
  } catch (err) {
    clearAnalysisProgressTimer();
    setLog("finalizeLog", String(err));
    renderAnalysisProgress("Phân tích thất bại. Vui lòng thử lại.", Math.max(0, (Date.now() - state.analysisStartedAt) / 1000));
  } finally {
    state.isFinalizing = false;
  }
}

function startAutoFeed() {
  stopAutoFeed();
  const tick = async () => {
    if (!state.autoTimer) {
      return;
    }
    if (!state.autoFrameBusy) {
      state.autoFrameBusy = true;
      try {
        await sendOneFrame();
      } catch (err) {
        setLog("frameLog", String(err));
      } finally {
        state.autoFrameBusy = false;
      }
    }
    if (state.autoTimer) {
      state.autoTimer = setTimeout(tick, 350);
    }
  };
  state.autoTimer = setTimeout(tick, 0);
}

function stopAutoFeed() {
  if (state.autoTimer) {
    clearTimeout(state.autoTimer);
    state.autoTimer = null;
  }
  state.autoFrameBusy = false;
}

Array.from(document.querySelectorAll(".step-btn")).forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.classList.contains("locked")) return;
    activateStep(Number(btn.dataset.step));
  });
});

// Cancel workout button
byId("cancelWorkoutBtn").addEventListener("click", async () => {
  if (!confirm("Bạn có chắc muốn hủy buổi tập hiện tại?")) return;
  try {
    if (window.speechService) {
      window.speechService.speak([], true); // Clear queue and stop
    }
    state.countdownActive = false;
    state.forceStartFrame = false;
    state.startupAnnouncementUntilMs = 0;
    stopAutoFeed();
    stopCamera();
    if (state.sessionId) {
      await api(`/v1/workout/session/${state.sessionId}`, "DELETE").catch(() => {});
    }
    state.sessionId = null;
    state.localSession = null;
    state.latestProgress = null;
    state.isFinalizing = false;
    clearAnalysisProgressTimer();
    updateSessionPill();
    lockWorkflowUI(false);
    activateStep(3);
    speak(["Đã hủy buổi tập."]);
    setLog("startLog", "Buổi tập đã bị hủy.");
  } catch (err) {
    setLog("frameLog", "Lỗi khi hủy: " + String(err));
  }
});

// Back to setup button (from step 5)
byId("backToSetupBtn").addEventListener("click", () => {
  lockWorkflowUI(false);
  activateStep(3);
});

function updateTrimSliderFill() {
  const startThumb = byId("tplTrimStart");
  const endThumb = byId("tplTrimEnd");
  const fill = byId("trimSliderFill");
  if (!startThumb || !endThumb || !fill) return;

  const min = parseFloat(startThumb.min || 0);
  const max = parseFloat(startThumb.max || 100);
  const startVal = parseFloat(startThumb.value);
  const endVal = parseFloat(endThumb.value);

  const range = max - min;
  if (range <= 0) return;

  const leftPercent = ((startVal - min) / range) * 100;
  const widthPercent = ((endVal - startVal) / range) * 100;

  fill.style.left = `${leftPercent}%`;
  fill.style.width = `${widthPercent}%`;
}

function handleTrimInput(isStart) {
  const startThumb = byId("tplTrimStart");
  const endThumb = byId("tplTrimEnd");
  const startLabel = byId("trimStartLabel");
  const endLabel = byId("trimEndLabel");
  const video = byId("localPreviewVideo");

  let startVal = parseFloat(startThumb.value);
  let endVal = parseFloat(endThumb.value);

  // Prevent overlap
  if (isStart && startVal > endVal) {
    startVal = endVal;
    startThumb.value = startVal;
  } else if (!isStart && endVal < startVal) {
    endVal = startVal;
    endThumb.value = endVal;
  }

  startLabel.textContent = startVal.toFixed(1);
  endLabel.textContent = endVal.toFixed(1);
  updateTrimSliderFill();

  // Scrub video to the thumb being moved
  if (video && video.readyState >= 1) {
    video.currentTime = isStart ? startVal : endVal;
  }
}

byId("tplFile").addEventListener("change", () => {
  const fileInput = byId("tplFile");
  if (!fileInput.files || !fileInput.files.length) {
    byId("trimUI").classList.add("hidden");
    return;
  }
  const file = fileInput.files[0];
  if (state.localPreviewObjectUrl) {
    URL.revokeObjectURL(state.localPreviewObjectUrl);
    state.localPreviewObjectUrl = null;
  }

  const blobUrl = URL.createObjectURL(file);
  state.localPreviewObjectUrl = blobUrl;
  const video = byId("localPreviewVideo");

  video.src = blobUrl;

  video.onloadedmetadata = () => {
    const duration = video.duration;
    if (duration > 0) {
      const startThumb = byId("tplTrimStart");
      const endThumb = byId("tplTrimEnd");

      startThumb.max = duration;
      endThumb.max = duration;

      startThumb.value = 0;
      endThumb.value = duration;

      byId("trimStartLabel").textContent = "0.0";
      byId("trimEndLabel").textContent = duration.toFixed(1);

      updateTrimSliderFill();
      byId("trimUI").classList.remove("hidden");
    }
  };
});

byId("tplTrimStart").addEventListener("input", () => handleTrimInput(true));
byId("tplTrimEnd").addEventListener("input", () => handleTrimInput(false));

byId("signalInput").addEventListener("input", (e) => {
  byId("signalValue").textContent = Number(e.target.value).toFixed(2);
});

byId("flipSideDirection").addEventListener("change", (e) => {
  state.flipSideDirectionLabels = Boolean(e.target.checked);
  setLog("frameLog", `Dao nhan trai/phai: ${state.flipSideDirectionLabels ? "bat" : "tat"}`);
});

byId("uploadAndCreateTplBtn").addEventListener("click", () => uploadAndCreateTemplate().catch((err) => setLog("templateLog", String(err))));
byId("refreshTplBtn").addEventListener("click", () => refreshTemplates().catch((err) => setLog("templateLog", String(err))));
byId("refreshLibBtn").addEventListener("click", () => refreshTemplates().catch((err) => setLog("libraryLog", String(err))));
byId("refreshAnalysisLibBtn").addEventListener("click", () => refreshAnalysisVideos().catch((err) => setLog("libraryLog", String(err))));
byId("addStepBtn").addEventListener("click", addWorkoutStep);
byId("startWorkoutBtn").addEventListener("click", () => startWorkoutSession().catch((err) => setLog("startLog", String(err))));
byId("startCameraBtn").addEventListener("click", () => startCamera().catch((err) => setLog("frameLog", String(err))));
byId("stopCameraBtn").addEventListener("click", stopCamera);
byId("sendFrameBtn").addEventListener("click", () => sendOneFrame().catch((err) => setLog("frameLog", String(err))));
byId("confirmBtn").addEventListener("click", () => confirmNext().catch((err) => setLog("frameLog", String(err))));
byId("finalizeBtn").addEventListener("click", () => {
  activateStep(5);
  finalizeSession().catch((err) => setLog("finalizeLog", String(err)));
});
byId("autoStartBtn").addEventListener("click", startAutoFeed);
byId("autoStopBtn").addEventListener("click", stopAutoFeed);
byId("debugTemplateFullscreenBtn")?.addEventListener("click", async () => {
  const stage = byId("debugTemplateStage");
  if (!stage) {
    return;
  }
  if (document.fullscreenElement === stage) {
    await document.exitFullscreen().catch(() => { });
    return;
  }
  if (typeof stage.requestFullscreen === "function") {
    await stage.requestFullscreen().catch(() => { });
  }
});

initTemplateDebugVideoBindings();

window.addEventListener("beforeunload", () => {
  stopBootstrapRefresh();
  stopAutoFeed();
  stopCamera();
  stopDebugTemplateOverlayLoop();
  if (state.localPreviewObjectUrl) {
    URL.revokeObjectURL(state.localPreviewObjectUrl);
    state.localPreviewObjectUrl = null;
  }
});

resetTemplateDebugPanel();

warmStartApp().catch((err) => {
  setLog("templateLog", String(err));
  setLog("libraryLog", "Chưa kết nối được API.");
  renderLibraryCards();
  renderStepsBox();
  bindStepRowActions();
  scheduleBootstrapRefresh();
});
