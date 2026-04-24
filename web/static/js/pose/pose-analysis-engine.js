export const PROFILE_FEATURE_VERSION = "v3_angle_length_10d";

const DEFAULT_CONNECTIONS = [
  [11, 12],
  [11, 13],
  [13, 15],
  [12, 14],
  [14, 16],
  [11, 23],
  [12, 24],
  [23, 24],
  [23, 25],
  [25, 27],
  [24, 26],
  [26, 28],
];

export class PoseAnalysisEngine {
  constructor(options = {}) {
    this.connections = Array.isArray(options.connections) && options.connections.length
      ? options.connections.map((conn) => Array.isArray(conn) ? conn : [conn.start, conn.end])
      : DEFAULT_CONNECTIONS;
    this.getFlipSideDirectionLabels = typeof options.getFlipSideDirectionLabels === "function"
      ? options.getFlipSideDirectionLabels
      : () => false;
    this.oneEuroConfig = {
      minCutoff: 1.2,
      beta: 0.032,
      dCutoff: 1.0,
      fastMotionSpeed: 8.0,
      fastMotionAlpha: 0.78,
      ...(options.oneEuroConfig || {}),
    };
    this.occlusionConfig = {
      minVisibility: 0.22,
      maxCarryFrames: 10,
      carryDecay: 0.9,
      ...(options.occlusionConfig || {}),
    };

    this.resetRuntime();
    this.resetWorkoutState();
  }

  resetRuntime() {
    this.oneEuroState = null;
    this.oneEuroLastTs = 0;
    this.carryLandmarks = null;
    this.carryLandmarkFrames = 0;
    this.lastRealtimeSimilarity = 0;
    this.lastRealtimeReadiness = false;
  }

  resetWorkoutState() {
    this.startGateHistory = {};
    this.signalRangeByTemplate = {};
  }

  hasCompatibleProfile(profile) {
    return Boolean(
      profile
      && profile.feature_version === PROFILE_FEATURE_VERSION
      && Array.isArray(profile.features)
      && profile.features.length
    );
  }

  setRealtimeMetrics(similarity, readiness) {
    this.lastRealtimeSimilarity = Number(similarity || 0);
    this.lastRealtimeReadiness = Boolean(readiness);
  }

  getRealtimeMetrics() {
    return {
      similarity: this.lastRealtimeSimilarity,
      readiness: this.lastRealtimeReadiness,
    };
  }

  sampleFromLandmarks(landmarks) {
    return (landmarks || []).map((lm) => ([
      Number(lm.x ?? 0),
      Number(lm.y ?? 0),
      Number(lm.z ?? 0),
      Number(lm.visibility ?? 0),
      Number(lm.wx ?? Number.NaN),
      Number(lm.wy ?? Number.NaN),
      Number(lm.wz ?? Number.NaN),
      Number(lm.worldVisibility ?? Number.NaN),
    ]));
  }

  landmarksFromSample(sample, bbox = null) {
    if (!Array.isArray(sample)) {
      return [];
    }

    if (!bbox) {
      return sample.map((point) => ({
        x: Number(point[0] ?? 0),
        y: Number(point[1] ?? 0),
        z: Number(point[2] ?? 0),
        visibility: Number(point[3] ?? 0),
        wx: Number(point[4] ?? Number.NaN),
        wy: Number(point[5] ?? Number.NaN),
        wz: Number(point[6] ?? Number.NaN),
        worldVisibility: Number(point[7] ?? Number.NaN),
      }));
    }

    const minX = Number(bbox.min_x ?? 0);
    const minY = Number(bbox.min_y ?? 0);
    const maxX = Number(bbox.max_x ?? 1);
    const maxY = Number(bbox.max_y ?? 1);
    const rangeX = Math.max(1e-6, maxX - minX);
    const rangeY = Math.max(1e-6, maxY - minY);

    return sample.map((point) => ({
      x: (Number(point[0] ?? 0) - minX) / rangeX,
      y: (Number(point[1] ?? 0) - minY) / rangeY,
      z: Number(point[2] ?? 0),
      visibility: Number(point[3] ?? 0),
      wx: Number(point[4] ?? Number.NaN),
      wy: Number(point[5] ?? Number.NaN),
      wz: Number(point[6] ?? Number.NaN),
      worldVisibility: Number(point[7] ?? Number.NaN),
    }));
  }

  bboxFromSample(sample) {
    const visible = (sample || []).filter((point) => (point[3] ?? 0) >= 0.25);
    if (!visible.length) {
      return { min_x: 0, min_y: 0, max_x: 1, max_y: 1, center_x: 0.5, center_y: 0.5 };
    }

    let minX = 1;
    let minY = 1;
    let maxX = 0;
    let maxY = 0;
    for (const point of visible) {
      minX = Math.min(minX, point[0]);
      minY = Math.min(minY, point[1]);
      maxX = Math.max(maxX, point[0]);
      maxY = Math.max(maxY, point[1]);
    }

    if ((maxX - minX) < 0.12) {
      const pad = (0.12 - (maxX - minX)) / 2;
      minX -= pad;
      maxX += pad;
    }
    if ((maxY - minY) < 0.16) {
      const pad = (0.16 - (maxY - minY)) / 2;
      minY -= pad;
      maxY += pad;
    }

    minX = Math.max(0, minX - 0.05);
    minY = Math.max(0, minY - 0.05);
    maxX = Math.min(1, maxX + 0.05);
    maxY = Math.min(1, maxY + 0.05);

    return {
      min_x: minX,
      min_y: minY,
      max_x: maxX,
      max_y: maxY,
      center_x: (minX + maxX) / 2,
      center_y: (minY + maxY) / 2,
    };
  }

  drawOverlay(canvas, sample, bbox, jointErrors, baseColor) {
    if (!canvas || !sample || !sample.length) {
      return;
    }

    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Keep one consistent projection model across views: draw directly in frame-normalized coordinates.
    const normalized = this.landmarksFromSample(sample, null);
    const visible = normalized.filter((point) => (point.visibility ?? 0) >= 0.25);
    const highlightMap = new Map((jointErrors || []).map((item) => [item.point_index, item]));
    const highlightPoints = Array.from(highlightMap.keys());
    const highlightConnections = this.connections.filter(([a, b]) => highlightMap.has(a) || highlightMap.has(b));

    if (typeof window.drawConnectors === "function" && typeof window.drawLandmarks === "function") {
      window.drawConnectors(ctx, normalized, this.connections, {
        color: baseColor,
        lineWidth: 3,
      });
      window.drawLandmarks(ctx, visible, {
        color: baseColor,
        lineWidth: 1,
        radius: 4,
      });
      if (highlightConnections.length) {
        window.drawConnectors(ctx, normalized, highlightConnections, {
          color: "#d62828",
          lineWidth: 4,
        });
      }
      if (highlightPoints.length) {
        window.drawLandmarks(ctx, highlightPoints.map((idx) => normalized[idx]).filter(Boolean), {
          color: "#d62828",
          lineWidth: 2,
          radius: 6,
        });
      }
      return;
    }

    const width = canvas.width;
    const height = canvas.height;

    ctx.lineWidth = 3;
    for (const [a, b] of this.connections) {
      const pa = sample[a];
      const pb = sample[b];
      if (!pa || !pb || (pa[3] ?? 0) < 0.25 || (pb[3] ?? 0) < 0.25) {
        continue;
      }
      ctx.strokeStyle = highlightMap.has(a) || highlightMap.has(b) ? "#d62828" : baseColor;
      ctx.beginPath();
      ctx.moveTo(pa[0] * width, pa[1] * height);
      ctx.lineTo(pb[0] * width, pb[1] * height);
      ctx.stroke();
    }

    for (let idx = 0; idx < sample.length; idx += 1) {
      const point = sample[idx];
      if (!point || (point[3] ?? 0) < 0.25) {
        continue;
      }
      const isHighlight = highlightMap.has(idx);
      ctx.fillStyle = isHighlight ? "#d62828" : baseColor;
      ctx.beginPath();
      ctx.arc(point[0] * width, point[1] * height, isHighlight ? 6 : 4, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  drawClassicLiveOverlay(ctx, landmarks, similarity = 0, readiness = false) {
    if (!ctx || !landmarks || !landmarks.length) {
      return;
    }

    const width = ctx.canvas.width;
    const height = ctx.canvas.height;
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    for (const [a, b] of this.connections) {
      const pa = landmarks[a];
      const pb = landmarks[b];
      if (!pa || !pb) {
        continue;
      }
      const visA = Number(pa.visibility ?? 0);
      const visB = Number(pb.visibility ?? 0);
      if (visA < 0.18 || visB < 0.18) {
        continue;
      }
      const alpha = Math.max(0.18, Math.min(0.92, (visA + visB) / 2));
      ctx.strokeStyle = `rgba(16, 93, 108, ${alpha})`;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(pa.x * width, pa.y * height);
      ctx.lineTo(pb.x * width, pb.y * height);
      ctx.stroke();
    }

    landmarks.forEach((landmark) => {
      const vis = Number(landmark.visibility ?? 0);
      if (vis < 0.16) {
        return;
      }
      const radius = 3 + (vis * 3.5);
      ctx.fillStyle = `rgba(20, 125, 140, ${Math.max(0.22, vis)})`;
      ctx.beginPath();
      ctx.arc(landmark.x * width, landmark.y * height, radius, 0, Math.PI * 2);
      ctx.fill();
    });

    const pillColor = readiness ? "rgba(15, 105, 76, 0.9)" : "rgba(145, 87, 16, 0.92)";
    ctx.fillStyle = pillColor;
    ctx.fillRect(16, 16, 210, 70);
    ctx.fillStyle = "#ffffff";
    ctx.font = "600 18px Segoe UI";
    ctx.fillText(`Similarity ${(similarity * 100).toFixed(1)}%`, 28, 42);
    ctx.font = "500 14px Segoe UI";
    ctx.fillText(readiness ? "Pose ready" : "Dang can chinh pose", 28, 64);

    const orientation = this.estimateOrientationFromLandmarks(landmarks);
    ctx.fillStyle = "rgba(14, 21, 35, 0.86)";
    ctx.fillRect(16, Math.max(96, height - 76), 260, 54);
    ctx.fillStyle = "#f4fbff";
    ctx.font = "500 12px Segoe UI";
    ctx.fillText(this.orientationLabel(orientation), 26, Math.max(128, height - 46));
    ctx.restore();
  }

  isHorizontalPosture(landmarks) {
    if (!Array.isArray(landmarks) || landmarks.length < 29) {
      return false;
    }

    const ls = landmarks[11];
    const rs = landmarks[12];
    const lh = landmarks[23];
    const rh = landmarks[24];
    const la = landmarks[27];
    const ra = landmarks[28];
    if (!ls || !rs || !lh || !rh || !la || !ra) {
      return false;
    }

    const shoulderMid = { x: (ls.x + rs.x) / 2, y: (ls.y + rs.y) / 2 };
    const hipMid = { x: (lh.x + rh.x) / 2, y: (lh.y + rh.y) / 2 };
    const ankleMid = { x: (la.x + ra.x) / 2, y: (la.y + ra.y) / 2 };

    const torsoDx = Math.abs(shoulderMid.x - hipMid.x);
    const torsoDy = Math.abs(shoulderMid.y - hipMid.y);
    const bodyDx = Math.abs(shoulderMid.x - ankleMid.x);
    const bodyDy = Math.abs(shoulderMid.y - ankleMid.y);

    return torsoDx > (torsoDy * 1.12) && bodyDx > (bodyDy * 1.05);
  }

  normalizeSignalForTemplate(templateId, rawSignal, mode) {
    const signal = Math.max(0, Math.min(1, Number(rawSignal ?? 0)));
    if (!templateId) {
      return signal;
    }

    const key = `${templateId}:${mode || "reps"}`;
    const current = this.signalRangeByTemplate[key] || { min: signal, max: signal };
    current.min = Math.min(current.min, signal);
    current.max = Math.max(current.max, signal);
    this.signalRangeByTemplate[key] = current;

    const span = current.max - current.min;
    if (span < 0.08) {
      return signal;
    }
    return Math.max(0, Math.min(1, (signal - current.min) / Math.max(1e-6, span)));
  }

  featureFromLandmarks(landmarks) {
    // 10-dim feature: 6 angles + 4 torso-normalised lengths
    // Must match server-side features.py layout exactly.
    const angleTriplets = [
      [11, 13, 15],   // left elbow
      [12, 14, 16],   // right elbow
      [23, 25, 27],   // left knee
      [24, 26, 28],   // right knee
      [11, 23, 25],   // left hip
      [12, 24, 26],   // right hip
    ];
    const vectorPairs = [
      [23, 25],   // left hip-knee
      [24, 26],   // right hip-knee
      [11, 15],   // left shoulder-wrist
      [12, 16],   // right shoulder-wrist
    ];

    const vis = landmarks.map((lm) => Number((lm && lm.visibility) ?? 0));
    const features = [];
    const weights = [];

    // 6 angles (rotation-invariant)
    for (const [a, b, c] of angleTriplets) {
      features.push(this._angle3(
        this._point3FromLandmark(landmarks[a]),
        this._point3FromLandmark(landmarks[b]),
        this._point3FromLandmark(landmarks[c]),
      ));
      weights.push(Math.max(0.05, Math.min(vis[a] ?? 0, vis[b] ?? 0, vis[c] ?? 0)));
    }

    // Compute torso height for length normalisation
    const midShoulder = this._midpoint3(
      this._point3FromLandmark(landmarks[11]),
      this._point3FromLandmark(landmarks[12]),
    );
    const midHip = this._midpoint3(
      this._point3FromLandmark(landmarks[23]),
      this._point3FromLandmark(landmarks[24]),
    );
    let torsoHeight = 1e-6;
    if (midShoulder && midHip) {
      torsoHeight = Math.max(1e-6, Math.hypot(
        midShoulder[0] - midHip[0],
        midShoulder[1] - midHip[1],
        midShoulder[2] - midHip[2],
      ));
    }

    // 4 normalised lengths (scale-invariant)
    for (const [a, b] of vectorPairs) {
      const pa = this._point3FromLandmark(landmarks[a]);
      const pb = this._point3FromLandmark(landmarks[b]);
      const w = Math.max(0.05, Math.min(vis[a] ?? 0, vis[b] ?? 0));
      if (!pa || !pb) {
        features.push(0);
        weights.push(w);
        continue;
      }
      const len = Math.hypot(pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]);
      features.push(len / torsoHeight);
      weights.push(w);
    }

    const allCore = [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28];
    const trunk = this.visibleRatio(landmarks, [11, 12, 23, 24], 0.45);
    const lowerBody = this.visibleRatio(landmarks, [23, 24, 25, 26, 27, 28], 0.45);
    const overall = this.visibleRatio(landmarks, allCore, 0.35);

    return {
      values: features,
      weights,
      coverage: {
        trunk,
        lowerBody,
        overall,
      },
    };
  }

  visibleRatio(landmarks, indices, threshold = 0.4) {
    if (!Array.isArray(indices) || !indices.length) {
      return 0;
    }
    let good = 0;
    for (const idx of indices) {
      const lm = landmarks[idx];
      if (!lm) {
        continue;
      }
      const x = Number(lm.x ?? -1);
      const y = Number(lm.y ?? -1);
      const inFrame = x >= 0 && x <= 1 && y >= 0 && y <= 1;
      if (inFrame && Number(lm.visibility ?? 0) >= threshold) {
        good += 1;
      }
    }
    return good / indices.length;
  }

  oneEuroAlpha(dt, cutoff) {
    const tau = 1 / (2 * Math.PI * Math.max(1e-4, cutoff));
    return 1 / (1 + (tau / Math.max(1e-4, dt)));
  }

  smoothPoseLandmarks(current, worldCurrent = null) {
    if (!Array.isArray(current) || !current.length) {
      const carryCfg = this.occlusionConfig || { maxCarryFrames: 8, carryDecay: 0.9 };
      if (Array.isArray(this.carryLandmarks) && this.carryLandmarkFrames < Number(carryCfg.maxCarryFrames || 8)) {
        this.carryLandmarkFrames += 1;
        const decay = Math.max(0.7, Math.min(0.98, Number(carryCfg.carryDecay || 0.9)));
        return this.carryLandmarks.map((lm) => ({
          ...lm,
          visibility: Math.max(0, Number(lm.visibility ?? 0) * decay),
        }));
      }
      this.resetRuntime();
      return null;
    }

    this.carryLandmarkFrames = 0;

    const now = performance.now();
    const prevTs = Number(this.oneEuroLastTs || 0);
    const dt = prevTs > 0 ? Math.max(1 / 120, (now - prevTs) / 1000) : (1 / 30);
    this.oneEuroLastTs = now;

    const cfg = this.oneEuroConfig;
    const occ = this.occlusionConfig;
    const prevFilter = Array.isArray(this.oneEuroState) ? this.oneEuroState : null;

    if (!prevFilter || prevFilter.length !== current.length) {
      const seeded = current.map((lm, idx) => this._seedLandmarkState(lm, Array.isArray(worldCurrent) ? worldCurrent[idx] : null));
      this.oneEuroState = seeded.map((lm) => ({ ...lm }));
      this.carryLandmarks = seeded.map((lm) => ({ ...lm }));
      return seeded;
    }

    const aD = this.oneEuroAlpha(dt, cfg.dCutoff);
    const blended = current.map((lm, idx) => {
      const p = prevFilter[idx] || prevFilter[0];
      const world = Array.isArray(worldCurrent) ? worldCurrent[idx] : null;

      const x = Number(lm.x ?? 0);
      const y = Number(lm.y ?? 0);
      const z = Number(lm.z ?? 0);
      const dxRaw = (x - p.x) / dt;
      const dyRaw = (y - p.y) / dt;
      const dzRaw = (z - p.z) / dt;

      const dxHat = (aD * dxRaw) + ((1 - aD) * p.dx);
      const dyHat = (aD * dyRaw) + ((1 - aD) * p.dy);
      const dzHat = (aD * dzRaw) + ((1 - aD) * p.dz);

      const speed = Math.sqrt((dxHat * dxHat) + (dyHat * dyHat) + (dzHat * dzHat));
      const cutoff = cfg.minCutoff + (cfg.beta * speed);
      const a = this.oneEuroAlpha(dt, cutoff);

      const vis = Math.max(0, Math.min(1, Number(lm.visibility ?? 0)));
      const visWeight = vis >= occ.minVisibility ? vis : 0;
      let aVis = Math.max(0.03, Math.min(0.95, (a * Math.max(0.1, visWeight)) + 0.02));
      if (speed >= Number(cfg.fastMotionSpeed || 8.0)) {
        aVis = Math.max(aVis, Math.min(0.95, Number(cfg.fastMotionAlpha || 0.78)));
      }

      const xPred = p.x + (p.dx * dt);
      const yPred = p.y + (p.dy * dt);
      const zPred = p.z + (p.dz * dt);

      const xInput = visWeight > 0 ? x : xPred;
      const yInput = visWeight > 0 ? y : yPred;
      const zInput = visWeight > 0 ? z : zPred;

      return {
        x: (aVis * xInput) + ((1 - aVis) * p.x),
        y: (aVis * yInput) + ((1 - aVis) * p.y),
        z: (aVis * zInput) + ((1 - aVis) * p.z),
        dx: dxHat,
        dy: dyHat,
        dz: dzHat,
        visibility: vis,
        wx: this._worldComponent(world, "x", p.wx),
        wy: this._worldComponent(world, "y", p.wy),
        wz: this._worldComponent(world, "z", p.wz),
        worldVisibility: this._worldVisibility(world, vis),
      };
    });

    this.oneEuroState = blended.map((lm) => ({ ...lm }));
    this.carryLandmarks = blended.map((lm) => ({ ...lm }));
    return blended;
  }

  poseQualityScore(landmarks) {
    const trunk = this.visibleRatio(landmarks, [11, 12, 23, 24], 0.45);
    const limbs = this.visibleRatio(landmarks, [13, 14, 15, 16, 25, 26, 27, 28], 0.3);
    return (0.6 * trunk) + (0.4 * limbs);
  }

  angleAt(a, b, c) {
    if (!a || !b || !c) {
      return 0;
    }
    const ba = [a.x - b.x, a.y - b.y];
    const bc = [c.x - b.x, c.y - b.y];
    const nba = Math.hypot(ba[0], ba[1]);
    const nbc = Math.hypot(bc[0], bc[1]);
    if (nba < 1e-6 || nbc < 1e-6) {
      return 0;
    }
    const cosVal = Math.max(-1, Math.min(1, ((ba[0] * bc[0]) + (ba[1] * bc[1])) / (nba * nbc)));
    return Math.acos(cosVal);
  }

  kneeExtensionDeg(landmarks) {
    if (!Array.isArray(landmarks) || landmarks.length < 29) {
      return { left: null, right: null, mean: null, min: null, valid: false };
    }

    const left = this.angleAt(landmarks[23], landmarks[25], landmarks[27]) * (180 / Math.PI);
    const right = this.angleAt(landmarks[24], landmarks[26], landmarks[28]) * (180 / Math.PI);
    if (!Number.isFinite(left) || !Number.isFinite(right) || left <= 0 || right <= 0) {
      return { left, right, mean: null, min: null, valid: false };
    }

    const mean = (left + right) / 2;
    const min = Math.min(left, right);
    return { left, right, mean, min, valid: true };
  }

  hipExtensionDeg(landmarks) {
    if (!Array.isArray(landmarks) || landmarks.length < 29) {
      return { left: null, right: null, mean: null, min: null, valid: false };
    }

    const left = this.angleAt(landmarks[11], landmarks[23], landmarks[25]) * (180 / Math.PI);
    const right = this.angleAt(landmarks[12], landmarks[24], landmarks[26]) * (180 / Math.PI);
    if (!Number.isFinite(left) || !Number.isFinite(right) || left <= 0 || right <= 0) {
      return { left, right, mean: null, min: null, valid: false };
    }

    const mean = (left + right) / 2;
    const min = Math.min(left, right);
    return { left, right, mean, min, valid: true };
  }

  estimateOrientationFromLandmarks(landmarks) {
    if (!Array.isArray(landmarks) || landmarks.length < 29) {
      return this._emptyOrientation();
    }

    const ls = landmarks[11];
    const rs = landmarks[12];
    const lh = landmarks[23];
    const rh = landmarks[24];
    const lk = landmarks[25];
    const rk = landmarks[26];
    const la = landmarks[27];
    const ra = landmarks[28];
    const nose = landmarks[0];

    if (!ls || !rs || !lh || !rh) {
      return this._emptyOrientation();
    }

    const faceVisibility = this.visibleRatio(landmarks, [0, 1, 2, 3, 4, 5, 6, 7], 0.25);
    const leftVisibility = this.visibleRatio(landmarks, [11, 13, 15, 23, 25, 27], 0.3);
    const rightVisibility = this.visibleRatio(landmarks, [12, 14, 16, 24, 26, 28], 0.3);
    const shoulderTrunkVisibility = this.visibleRatio(landmarks, [11, 12, 23, 24], 0.35);

    const shoulderMid = { x: (ls.x + rs.x) / 2, y: (ls.y + rs.y) / 2 };
    const hipMid = { x: (lh.x + rh.x) / 2, y: (lh.y + rh.y) / 2 };
    const shoulderWidth = Math.hypot(rs.x - ls.x, rs.y - ls.y);
    const torsoLen = Math.max(1e-6, Math.hypot(shoulderMid.x - hipMid.x, shoulderMid.y - hipMid.y));
    const yawProxy = shoulderWidth / torsoLen;
    const shoulderDepthDelta = Number(rs.z ?? 0) - Number(ls.z ?? 0);

    const rawYaw = Math.max(0, Math.min(1, (0.62 - yawProxy) / 0.62));
    const yawDegUnsigned = rawYaw * 90;
    const noseOffset = nose ? (nose.x - shoulderMid.x) : 0;
    const sideBias = leftVisibility - rightVisibility;
    const signedDirection = Math.abs(sideBias) > 0.06 ? (sideBias > 0 ? 1 : -1) : (noseOffset > 0 ? -1 : 1);
    const yawDeg = yawDegUnsigned * signedDirection;

    const tiltDeg = Math.atan2((rs.y - ls.y), (rs.x - ls.x)) * (180 / Math.PI);
    const floorCue = this._horizontalFloorCue(landmarks);
    const horizontal = this.isHorizontalPosture(landmarks) || floorCue.isHorizontal;
    const chestNormal = this._chestPlaneNormal(landmarks);
    const kneeExt = this.kneeExtensionDeg(landmarks);
    const hipExt = this.hipExtensionDeg(landmarks);

    let viewClass = "front";
    const strongSide = yawProxy < 0.31;
    const likelySide = yawProxy < 0.35 && Math.abs(shoulderDepthDelta) > 0.035 && faceVisibility < 0.58;
    if (strongSide || likelySide) {
      viewClass = "side";
    }
    if (faceVisibility < 0.16 && yawProxy >= 0.45) {
      viewClass = "back";
    }

    let sideDirection = "unknown";
    if (viewClass === "side") {
      if (Math.abs(shoulderDepthDelta) >= 0.03) {
        sideDirection = shoulderDepthDelta < 0 ? "right" : "left";
      } else if (leftVisibility > rightVisibility + 0.07) {
        sideDirection = "left";
      } else if (rightVisibility > leftVisibility + 0.07) {
        sideDirection = "right";
      } else {
        sideDirection = yawDeg >= 0 ? "left" : "right";
      }

      if (this.getFlipSideDirectionLabels() && sideDirection !== "unknown") {
        sideDirection = sideDirection === "left" ? "right" : "left";
      }
    }

    let postureClass = "standing";
    if (horizontal) {
      postureClass = "lying";
    } else {
      const kneeLeft = this.angleAt(lh, lk, la);
      const kneeRight = this.angleAt(rh, rk, ra);
      const kneeBend = Math.min(kneeLeft, kneeRight);
      postureClass = (kneeBend < 2.45) && (hipMid.y > 0.52) ? "sitting" : "standing";
    }

    let lyingType = "unknown";
    let supineScore = 0;
    let proneScore = 0;
    if (postureClass === "lying") {
      // Keep only coarse posture class and diagnostics; disable fine-grained
      // supine/prone subtype classification to avoid unstable labels.
      lyingType = "horizontal";
      supineScore = 0;
      proneScore = 0;
    }

    return {
      viewClass,
      sideDirection,
      postureClass,
      lyingType,
      supineScore,
      proneScore,
      kneeExtensionDeg: kneeExt.valid ? kneeExt.min : null,
      hipExtensionDeg: hipExt.valid ? hipExt.min : null,
      yawDeg,
      tiltDeg,
      yawProxy,
      faceVisibility,
      leftVisibility,
      rightVisibility,
      chestNormalX: chestNormal.valid ? Number(chestNormal.nx) : null,
      chestNormalY: chestNormal.valid ? Number(chestNormal.ny) : null,
      chestNormalZ: chestNormal.valid ? Number(chestNormal.nz) : null,
      chestNormalConfidence: chestNormal.valid ? Number(chestNormal.confidence) : 0,
      floorHorizontalScore: Number(floorCue.score || 0),
    };
  }

  estimateOrientationFromSample(sample) {
    if (!Array.isArray(sample)) {
      return this._emptyOrientation();
    }

    return this.estimateOrientationFromLandmarks(sample.map((point) => ({
      x: Number(point[0] ?? 0),
      y: Number(point[1] ?? 0),
      z: Number(point[2] ?? 0),
      visibility: Number(point[3] ?? 0),
      wx: Number(point[4] ?? Number.NaN),
      wy: Number(point[5] ?? Number.NaN),
      wz: Number(point[6] ?? Number.NaN),
      worldVisibility: Number(point[7] ?? Number.NaN),
    })));
  }

  modeOf(values, fallback = "unknown") {
    const counter = new Map();
    for (const value of values || []) {
      if (!value) {
        continue;
      }
      counter.set(value, (counter.get(value) || 0) + 1);
    }
    if (!counter.size) {
      return fallback;
    }
    let bestValue = fallback;
    let bestCount = -1;
    for (const [value, count] of counter.entries()) {
      if (count > bestCount) {
        bestValue = value;
        bestCount = count;
      }
    }
    return bestValue;
  }

  modeOfKnown(values, fallback = "unknown", unknownToken = "unknown") {
    const known = (values || []).filter((value) => value && value !== unknownToken);
    if (!known.length) {
      return fallback;
    }
    return this.modeOf(known, fallback);
  }

  sliceSamplesForOrientation(profile, mode = "reps") {
    const samples = Array.isArray(profile && profile.pose_samples) ? profile.pose_samples : [];
    if (!samples.length) {
      return [];
    }
    if (mode === "hold") {
      const headCount = Math.max(6, Math.min(24, Math.floor(samples.length * 0.45)));
      return samples.slice(0, headCount);
    }

    const phaseFeatures = Array.isArray(profile && profile.features) ? profile.features : [];
    const startPhase = this.startPhaseFromProfile(profile);
    if (startPhase == null || !phaseFeatures.length) {
      return samples.slice(0, Math.max(8, Math.min(24, Math.floor(samples.length * 0.2))));
    }

    const paired = samples.map((sample, idx) => ({
      sample,
      dist: this.phaseWrapDistance(this.phaseSignalFromFeature(profile, phaseFeatures[idx] || []), startPhase),
    }));
    paired.sort((a, b) => a.dist - b.dist);
    return paired.slice(0, Math.min(18, paired.length)).map((item) => item.sample);
  }

  phaseSignalFromFeature(profile, featureVec) {
    if (!profile || !Array.isArray(featureVec) || !featureVec.length) {
      return 0;
    }

    const mean = profile.feature_mean || [];
    const pc1 = profile.feature_pc1 || [];
    let proj = 0;
    for (let i = 0; i < featureVec.length; i += 1) {
      proj += (Number(featureVec[i] ?? 0) - Number(mean[i] ?? 0)) * Number(pc1[i] ?? 0);
    }
    const minP = Number(profile.proj_min ?? 0);
    const maxP = Number(profile.proj_max ?? 1);
    const denom = Math.max(1e-6, maxP - minP);
    return Math.max(0, Math.min(1, (proj - minP) / denom));
  }

  sliceSamplesForBasePose(profile, mode = "reps") {
    const samples = this.sliceSamplesForOrientation(profile, mode);
    if (mode === "hold" || !samples.length) {
      return samples;
    }
    const headCount = Math.max(4, Math.min(18, Math.floor(samples.length * 0.3)));
    return samples.slice(0, headCount);
  }

  detectTemplateBasePose(profile, mode = "reps") {
    const samples = this.sliceSamplesForBasePose(profile, mode);
    if (!samples.length) {
      return {
        postureClass: "unknown",
        lyingType: "unknown",
        proneScore: 0,
        supineScore: 0,
        confidence: 0,
      };
    }

    const probeCount = Math.min(11, samples.length);
    const probes = [];
    for (let i = 0; i < probeCount; i += 1) {
      const idx = probeCount <= 1 ? 0 : Math.round((i * (samples.length - 1)) / (probeCount - 1));
      probes.push(this.estimateOrientationFromSample(samples[idx]));
    }

    const postureClass = this.modeOfKnown(probes.map((o) => o.postureClass), "unknown");
    const postureVotes = probes.filter((o) => o.postureClass === postureClass).length;
    const postureConfidence = postureVotes / Math.max(1, probes.length);

    const lyingType = postureClass === "lying" ? "horizontal" : "unknown";
    const proneScore = 0;
    const supineScore = 0;
    const lyingProbes = probes.filter((o) => o.postureClass === "lying");
    const lyingVotes = lyingProbes.length;
    const lyingConfidence = lyingType === "unknown" ? 0 : (lyingVotes / Math.max(1, probes.length));

    return {
      postureClass,
      lyingType,
      proneScore,
      supineScore,
      confidence: postureClass === "lying" ? lyingConfidence : postureConfidence,
    };
  }

  detectTemplateOrientation(profile, mode = "reps") {
    const samples = this.sliceSamplesForOrientation(profile, mode);
    if (!samples.length) {
      return {
        viewClass: "unknown",
        sideDirection: "unknown",
        postureClass: "unknown",
        lyingType: "unknown",
        yawDeg: 0,
        proneScore: 0,
        supineScore: 0,
        lyingVoteCount: 0,
      };
    }

    const probeCount = Math.min(17, samples.length);
    const probes = [];
    for (let i = 0; i < probeCount; i += 1) {
      const idx = probeCount <= 1 ? 0 : Math.round((i * (samples.length - 1)) / (probeCount - 1));
      probes.push(this.estimateOrientationFromSample(samples[idx]));
    }

    const yawMean = probes.reduce((acc, o) => acc + Number(o.yawDeg || 0), 0) / Math.max(1, probes.length);
    const lyingProbes = probes.filter((o) => o.postureClass === "lying");
    const supineScore = 0;
    const proneScore = 0;
    const postureClass = this.modeOfKnown(probes.map((o) => o.postureClass), "unknown");
    const lyingType = postureClass === "lying" ? "horizontal" : "unknown";

    return {
      viewClass: this.modeOfKnown(probes.map((o) => o.viewClass), "unknown"),
      sideDirection: this.modeOfKnown(probes.map((o) => o.sideDirection), "unknown"),
      postureClass,
      lyingType,
      yawDeg: yawMean,
      proneScore,
      supineScore,
      lyingVoteCount: lyingProbes.length,
    };
  }

  orientationLabel(orientation) {
    if (!orientation) {
      return "huong: unknown";
    }
    const view = orientation.viewClass || "unknown";
    const side = orientation.sideDirection && orientation.sideDirection !== "unknown" ? `-${orientation.sideDirection}` : "";
    const posture = orientation.postureClass || "unknown";
    const lying = orientation.lyingType && orientation.lyingType !== "unknown" ? `, ${orientation.lyingType}` : "";
    const knee = Number.isFinite(Number(orientation.kneeExtensionDeg)) ? Number(orientation.kneeExtensionDeg).toFixed(0) : "--";
    const hip = Number.isFinite(Number(orientation.hipExtensionDeg)) ? Number(orientation.hipExtensionDeg).toFixed(0) : "--";
    const chestNz = Number.isFinite(Number(orientation.chestNormalZ)) ? Number(orientation.chestNormalZ).toFixed(2) : "--";
    return `huong: ${view}${side}, tu the: ${posture}${lying}, yaw~${Math.round(Math.abs(Number(orientation.yawDeg || 0)))} deg, goi~${knee} deg, hong~${hip} deg, chestNz~${chestNz}`;
  }

  detectTemplateView(profile, mode = "reps") {
    const orientation = this.detectTemplateOrientation(profile, mode);
    if (orientation.viewClass === "side") {
      return orientation.sideDirection === "right" ? "right_side" : "left_side";
    }
    if (orientation.viewClass === "back") {
      return "back";
    }
    if (orientation.viewClass === "front") {
      return "front";
    }
    return "unknown";
  }

  sampleIsHorizontal(sample) {
    if (!Array.isArray(sample) || sample.length < 29) {
      return false;
    }
    const ls = sample[11];
    const rs = sample[12];
    const lh = sample[23];
    const rh = sample[24];
    const la = sample[27];
    const ra = sample[28];
    if (!ls || !rs || !lh || !rh || !la || !ra) {
      return false;
    }

    const shoulderMid = { x: (ls[0] + rs[0]) / 2, y: (ls[1] + rs[1]) / 2 };
    const hipMid = { x: (lh[0] + rh[0]) / 2, y: (lh[1] + rh[1]) / 2 };
    const ankleMid = { x: (la[0] + ra[0]) / 2, y: (la[1] + ra[1]) / 2 };

    const torsoDx = Math.abs(shoulderMid.x - hipMid.x);
    const torsoDy = Math.abs(shoulderMid.y - hipMid.y);
    const bodyDx = Math.abs(shoulderMid.x - ankleMid.x);
    const bodyDy = Math.abs(shoulderMid.y - ankleMid.y);

    return torsoDx > (torsoDy * 1.12) && bodyDx > (bodyDy * 1.05);
  }

  inferStartPostureType(profile, landmarks = null, mode = "reps") {
    const orientation = this.detectTemplateOrientation(profile, mode);
    if (orientation.postureClass === "lying") {
      return "horizontal";
    }
    if (orientation.postureClass === "standing" || orientation.postureClass === "sitting") {
      return "vertical";
    }

    const samples = this.sliceSamplesForOrientation(profile, mode);
    if (samples.length) {
      const probeCount = Math.min(5, samples.length);
      let horizontalHits = 0;
      for (let i = 0; i < probeCount; i += 1) {
        if (this.sampleIsHorizontal(samples[i])) {
          horizontalHits += 1;
        }
      }
      if (horizontalHits >= Math.ceil(probeCount * 0.6)) {
        return "horizontal";
      }
      return "vertical";
    }

    if (landmarks && this.isHorizontalPosture(landmarks)) {
      return "horizontal";
    }
    return "vertical";
  }

  getReadinessProfile(startPostureType, profile = null) {
    const adaptive = profile && profile.adaptive_thresholds && profile.adaptive_thresholds.readiness
      ? profile.adaptive_thresholds.readiness
      : null;
    if (adaptive) {
      return {
        similarityMin: Math.max(0.28, Number(adaptive.similarity_min ?? 0.5) - 0.1),
        meanMin: Math.max(0.28, Number(adaptive.mean_min ?? 0.5) - 0.1),
        spreadMax: Math.min(0.42, Number(adaptive.spread_max ?? 0.22) + 0.08),
        anchorTolerance: Math.min(0.48, Number(adaptive.anchor_tolerance ?? 0.24) + 0.1),
        countdownMs: 4500,
      };
    }

    if (startPostureType === "horizontal") {
      return {
        similarityMin: 0.3,
        meanMin: 0.3,
        spreadMax: 0.34,
        anchorTolerance: 0.45,
        countdownMs: 4500,
      };
    }
    return {
      similarityMin: 0.38,
      meanMin: 0.36,
      spreadMax: 0.28,
      anchorTolerance: 0.32,
      countdownMs: 4500,
    };
  }

  startPhaseFromProfile(profile) {
    if (!profile || !Array.isArray(profile.features) || !profile.features.length) {
      return null;
    }
    const first = profile.features[0] || [];
    const mean = profile.feature_mean || [];
    const pc1 = profile.feature_pc1 || [];
    let proj = 0;
    for (let i = 0; i < first.length; i += 1) {
      const centered = Number(first[i] ?? 0) - Number(mean[i] ?? 0);
      proj += centered * Number(pc1[i] ?? 0);
    }
    const minP = Number(profile.proj_min ?? 0);
    const maxP = Number(profile.proj_max ?? 1);
    const denom = Math.max(1e-6, maxP - minP);
    return Math.max(0, Math.min(1, (proj - minP) / denom));
  }

  phaseWrapDistance(a, b) {
    const d = Math.abs(Number(a) - Number(b));
    return Math.min(d, 1 - d);
  }

  updateStartGateHistory(templateId, score) {
    if (!templateId) {
      return { mean: 0, spread: 1, count: 0 };
    }
    const arr = Array.isArray(this.startGateHistory[templateId]) ? this.startGateHistory[templateId] : [];
    arr.push(Number(score.similarity ?? 0));
    if (arr.length > 8) {
      arr.shift();
    }
    this.startGateHistory[templateId] = arr;
    const mean = arr.reduce((acc, value) => acc + value, 0) / Math.max(1, arr.length);
    const minVal = arr.length ? Math.min(...arr) : 0;
    const maxVal = arr.length ? Math.max(...arr) : 1;
    return { mean, spread: maxVal - minVal, count: arr.length };
  }

  viewGateDetailForTemplate(landmarks, profile, templateId = null, mode = "reps") {
    const fail = (reason, extra = {}) => ({ ok: false, reason, ...extra });
    const pass = (reason, extra = {}) => ({ ok: true, reason, ...extra });
    const userOrientation = this.estimateOrientationFromLandmarks(landmarks);
    const templateOrientation = this.detectTemplateOrientation(profile, mode);
    const basePose = this.detectTemplateBasePose(profile, mode);
    const frontRatio = this.visibleRatio(landmarks, [11, 12, 23, 24, 25, 26, 27, 28], 0.4);
    const leftRatio = this.visibleRatio(landmarks, [11, 13, 15, 23, 25, 27], 0.35);
    const rightRatio = this.visibleRatio(landmarks, [12, 14, 16, 24, 26, 28], 0.35);
    const trunkRatio = this.visibleRatio(landmarks, [11, 12, 23, 24], 0.35);
    const expectedPosture = basePose.postureClass === "lying"
      ? "horizontal"
      : (basePose.postureClass === "standing" || basePose.postureClass === "sitting")
        ? "vertical"
        : this.inferStartPostureType(profile, landmarks, mode);
    const common = {
      templateOrientation,
      userOrientation,
      basePose,
      expectedPosture,
      frontRatio,
      leftRatio,
      rightRatio,
      trunkRatio,
    };

    if (trunkRatio < 0.35) {
      return fail("trunk_visibility_low", common);
    }

    if (expectedPosture === "horizontal") {
      if (userOrientation.postureClass !== "lying") {
        return fail("expected_horizontal_but_not_lying", common);
      }

      // Horizontal-only gate: no supine/prone/side subtype decision.
      return pass("horizontal_posture_pass", common);
    }

    if (userOrientation.postureClass === "lying") {
      return fail("expected_vertical_but_lying", common);
    }

    const viewHint = this.detectTemplateView(profile, mode);
    if (viewHint === "left_side") {
      const ok = (userOrientation.viewClass === "side" && userOrientation.sideDirection === "left") || (leftRatio >= 0.55 && frontRatio >= 0.3);
      return ok ? pass("left_side_pass", { ...common, viewHint }) : fail("left_side_fail", { ...common, viewHint });
    }
    if (viewHint === "right_side") {
      const ok = (userOrientation.viewClass === "side" && userOrientation.sideDirection === "right") || (rightRatio >= 0.55 && frontRatio >= 0.3);
      return ok ? pass("right_side_pass", { ...common, viewHint }) : fail("right_side_fail", { ...common, viewHint });
    }
    if (viewHint === "back") {
      const ok = userOrientation.viewClass === "back" || userOrientation.faceVisibility < 0.2;
      return ok ? pass("back_view_pass", { ...common, viewHint }) : fail("back_view_fail", { ...common, viewHint });
    }
    if (viewHint === "front") {
      const ok = userOrientation.viewClass === "front" || frontRatio >= 0.62;
      return ok ? pass("front_view_pass", { ...common, viewHint }) : fail("front_view_fail", { ...common, viewHint });
    }

    return Math.max(frontRatio, leftRatio, rightRatio) >= 0.6
      ? pass("view_fallback_pass", { ...common, viewHint })
      : fail("view_fallback_fail", { ...common, viewHint });
  }

  viewReadyForTemplate(landmarks, profile, templateId = null, mode = "reps") {
    return this.viewGateDetailForTemplate(landmarks, profile, templateId, mode).ok;
  }

  holdPoseStillValid(landmarks, profile, score, templateId = null, mode = "hold") {
    if (!landmarks || !profile) {
      return false;
    }
    if (!this.viewReadyForTemplate(landmarks, profile, templateId, mode)) {
      return false;
    }

    const expectedPosture = this.inferStartPostureType(profile, landmarks, mode);
    const horizontalNow = this.isHorizontalPosture(landmarks);
    const similarity = Number(score && score.similarity || 0);

    if (expectedPosture === "horizontal") {
      return horizontalNow && similarity >= 0.22;
    }
    return !horizontalNow && similarity >= 0.28;
  }

  readinessFromLandmarks(landmarks, profile = null, score = null, mode = null, templateId = null) {
    const templateMode = mode || "reps";
    const strictViewReady = this.viewReadyForTemplate(landmarks, profile, templateId, templateMode);
    if (!strictViewReady) {
      const sim = Number(score && score.similarity || 0);
      const trunk = this.visibleRatio(landmarks, [11, 12, 23, 24], 0.35);
      const lower = this.visibleRatio(landmarks, [23, 24, 25, 26, 27, 28], 0.3);
      // Soft fallback: allow start when body is visible enough and similarity is acceptable,
      // even if orientation classifier is noisy in realtime.
      if (!(sim >= 0.32 && trunk >= 0.55 && lower >= 0.42)) {
        return false;
      }
    }

    if (!score || !profile) {
      return true;
    }

    const history = this.updateStartGateHistory(templateId, score);
    const similarity = Number(score.similarity ?? 0);
    const phaseSignal = Number(score.phase_signal ?? 0);
    const startPostureType = this.inferStartPostureType(profile, landmarks, templateMode);
    const cfg = this.getReadinessProfile(startPostureType, profile);

    if (templateMode === "hold") {
      const holdSimilarityMin = Math.max(0.32, cfg.similarityMin - 0.12);
      const holdMeanMin = Math.max(0.3, cfg.meanMin - 0.12);
      const holdSpreadMax = cfg.spreadMax + 0.06;
      return similarity >= holdSimilarityMin && history.mean >= holdMeanMin && history.spread <= holdSpreadMax;
    }

    const startPhase = this.startPhaseFromProfile(profile);
    const anchorOk = startPhase == null
      ? similarity >= cfg.similarityMin
      : this.phaseWrapDistance(phaseSignal, startPhase) <= cfg.anchorTolerance;
    const stableEnough = history.count >= 3 ? history.spread <= cfg.spreadMax : true;
    return similarity >= cfg.similarityMin && history.mean >= cfg.meanMin && anchorOk && stableEnough;
  }

  signalAndMatchFromProfile(featurePack, profile, mode = null) {
    if (!profile || !profile.feature_mean || !profile.feature_pc1 || !profile.features) {
      return { signal: 0, similarity: 0, phase_signal: 0, visibility_penalty: 0 };
    }

    const feature = Array.isArray(featurePack && featurePack.values) ? featurePack.values : [];
    const weights = Array.isArray(featurePack && featurePack.weights) ? featurePack.weights : [];
    const coverage = (featurePack && featurePack.coverage) || {};
    if (!feature.length) {
      return { signal: 0, similarity: 0, phase_signal: 0, visibility_penalty: 0 };
    }

    const mean = profile.feature_mean;
    const pc1 = profile.feature_pc1;
    const centered = feature.map((value, idx) => value - (mean[idx] ?? 0));
    let proj = 0;
    for (let i = 0; i < centered.length; i += 1) {
      proj += centered[i] * (pc1[i] ?? 0);
    }

    const minP = Number(profile.proj_min ?? 0);
    const maxP = Number(profile.proj_max ?? 1);
    const denom = Math.max(1e-6, maxP - minP);
    const phaseSignal = Math.max(0, Math.min(1, (proj - minP) / denom));

    let minDist = Number.POSITIVE_INFINITY;
    const refFeatures = profile.features;
    for (let i = 0; i < refFeatures.length; i += 1) {
      const ref = refFeatures[i];
      let sum = 0;
      let wSum = 0;
      for (let j = 0; j < feature.length; j += 1) {
        const w = Math.max(0.05, Number(weights[j] ?? 1));
        const d = feature[j] - (ref[j] ?? 0);
        sum += w * d * d;
        wSum += w;
      }
      const dist = Math.sqrt(sum / Math.max(1e-6, wSum));
      if (dist < minDist) {
        minDist = dist;
      }
    }

    const adaptive = profile && profile.adaptive_thresholds ? profile.adaptive_thresholds : null;
    const signalAdaptive = adaptive && adaptive.signal ? adaptive.signal : null;
    const distanceScale = Math.max(0.5, Number((signalAdaptive && signalAdaptive.distance_scale) ?? profile.similarity_distance_scale ?? 2.8));
    const rawSimilarity = Math.exp(-minDist / distanceScale);
    const trunkCov = Math.max(0, Math.min(1, Number(coverage.trunk ?? 0)));
    const lowerCov = Math.max(0, Math.min(1, Number(coverage.lowerBody ?? 0)));
    const overallCov = Math.max(0, Math.min(1, Number(coverage.overall ?? 0)));
    const visibilityPenalty = Math.max(0, Math.min(1, (0.45 * trunkCov) + (0.35 * lowerCov) + (0.2 * overallCov)));
    const similarity = rawSimilarity * visibilityPenalty;

    // Signal for rep counting: phase-only (no similarity blending)
    // This ensures full [0,1] swing regardless of camera angle or body proportions.
    // Similarity is returned separately for readiness/feedback use.
    const signal = mode === "hold" ? similarity : phaseSignal;

    return {
      signal: Math.max(0, Math.min(1, signal)),
      similarity,
      phase_signal: phaseSignal,
      visibility_penalty: visibilityPenalty,
    };
  }

  _seedLandmarkState(lm, world) {
    return {
      x: Number(lm.x ?? 0),
      y: Number(lm.y ?? 0),
      z: Number(lm.z ?? 0),
      dx: 0,
      dy: 0,
      dz: 0,
      visibility: Number(lm.visibility ?? 0),
      wx: this._worldComponent(world, "x", Number.NaN),
      wy: this._worldComponent(world, "y", Number.NaN),
      wz: this._worldComponent(world, "z", Number.NaN),
      worldVisibility: this._worldVisibility(world, Number(lm.visibility ?? 0)),
    };
  }

  _worldComponent(world, axis, fallback) {
    if (!world || !Number.isFinite(Number(world[axis]))) {
      return fallback;
    }
    return Number(world[axis]);
  }

  _worldVisibility(world, fallback) {
    if (!world) {
      return fallback;
    }
    const raw = Number(world.visibility ?? world.presence);
    return Number.isFinite(raw) ? raw : fallback;
  }

  _point3FromLandmark(lm) {
    if (!lm) {
      return null;
    }
    const wx = Number(lm.wx ?? Number.NaN);
    const wy = Number(lm.wy ?? Number.NaN);
    const wz = Number(lm.wz ?? Number.NaN);
    if (Number.isFinite(wx) && Number.isFinite(wy) && Number.isFinite(wz)) {
      return [wx, wy, wz];
    }
    const x = Number(lm.x ?? Number.NaN);
    const y = Number(lm.y ?? Number.NaN);
    const z = Number(lm.z ?? Number.NaN);
    return Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(z) ? [x, y, z] : null;
  }

  _midpoint3(a, b) {
    if (!a || !b) {
      return null;
    }
    return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2];
  }

  _chestPlaneNormal(landmarks) {
    const ls = this._point3FromLandmark(landmarks && landmarks[11]);
    const rs = this._point3FromLandmark(landmarks && landmarks[12]);
    const lh = this._point3FromLandmark(landmarks && landmarks[23]);
    const rh = this._point3FromLandmark(landmarks && landmarks[24]);
    const nose = this._point3FromLandmark(landmarks && landmarks[0]);
    if (!ls || !rs || !lh || !rh) {
      return { valid: false, nx: 0, ny: 0, nz: 0, confidence: 0 };
    }

    const hipMid = [
      (lh[0] + rh[0]) / 2,
      (lh[1] + rh[1]) / 2,
      (lh[2] + rh[2]) / 2,
    ];

    const u = [rs[0] - ls[0], rs[1] - ls[1], rs[2] - ls[2]];
    const v = [hipMid[0] - ls[0], hipMid[1] - ls[1], hipMid[2] - ls[2]];
    const n = [
      (u[1] * v[2]) - (u[2] * v[1]),
      (u[2] * v[0]) - (u[0] * v[2]),
      (u[0] * v[1]) - (u[1] * v[0]),
    ];
    const norm = Math.hypot(n[0], n[1], n[2]);
    if (norm < 1e-6) {
      return { valid: false, nx: 0, ny: 0, nz: 0, confidence: 0 };
    }

    let nx = n[0] / norm;
    let ny = n[1] / norm;
    let nz = n[2] / norm;

    const shoulderMid = [
      (ls[0] + rs[0]) / 2,
      (ls[1] + rs[1]) / 2,
      (ls[2] + rs[2]) / 2,
    ];
    if (nose) {
      const noseVec = [nose[0] - shoulderMid[0], nose[1] - shoulderMid[1], nose[2] - shoulderMid[2]];
      const noseNorm = Math.hypot(noseVec[0], noseVec[1], noseVec[2]);
      if (noseNorm > 1e-6) {
        const dot = (nx * noseVec[0]) + (ny * noseVec[1]) + (nz * noseVec[2]);
        if (dot < 0) {
          nx = -nx;
          ny = -ny;
          nz = -nz;
        }
      }
    }
    const confidence = Math.max(0, Math.min(1, Math.abs(nz) + (0.5 * Math.abs(nx))));
    return { valid: true, nx, ny, nz, confidence };
  }

  _horizontalFloorCue(landmarks) {
    const ls = this._point3FromLandmark(landmarks && landmarks[11]);
    const rs = this._point3FromLandmark(landmarks && landmarks[12]);
    const lh = this._point3FromLandmark(landmarks && landmarks[23]);
    const rh = this._point3FromLandmark(landmarks && landmarks[24]);
    const la = this._point3FromLandmark(landmarks && landmarks[27]);
    const ra = this._point3FromLandmark(landmarks && landmarks[28]);
    if (!ls || !rs || !lh || !rh || !la || !ra) {
      return { isHorizontal: false, score: 0 };
    }

    const shoulderMid = [(ls[0] + rs[0]) / 2, (ls[1] + rs[1]) / 2, (ls[2] + rs[2]) / 2];
    const hipMid = [(lh[0] + rh[0]) / 2, (lh[1] + rh[1]) / 2, (lh[2] + rh[2]) / 2];
    const ankleMid = [(la[0] + ra[0]) / 2, (la[1] + ra[1]) / 2, (la[2] + ra[2]) / 2];

    const span = Math.max(
      1e-6,
      Math.hypot(shoulderMid[0] - hipMid[0], shoulderMid[1] - hipMid[1], shoulderMid[2] - hipMid[2]),
      Math.hypot(shoulderMid[0] - ankleMid[0], shoulderMid[1] - ankleMid[1], shoulderMid[2] - ankleMid[2]),
    );
    const dyShHip = Math.abs(shoulderMid[1] - hipMid[1]);
    const dyShAnk = Math.abs(shoulderMid[1] - ankleMid[1]);
    const ratio1 = dyShHip / span;
    const ratio2 = dyShAnk / span;
    const score = Math.max(0, Math.min(1, 1 - ((ratio1 * 1.2) + ratio2)));
    return {
      isHorizontal: ratio1 <= 0.36 && ratio2 <= 0.5,
      score,
    };
  }

  _angle3(a, b, c) {
    if (!a || !b || !c) {
      return 0;
    }
    const ba = [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
    const bc = [c[0] - b[0], c[1] - b[1], c[2] - b[2]];
    const nba = Math.hypot(ba[0], ba[1], ba[2]);
    const nbc = Math.hypot(bc[0], bc[1], bc[2]);
    if (nba < 1e-6 || nbc < 1e-6) {
      return 0;
    }
    const cosVal = Math.max(-1, Math.min(1, ((ba[0] * bc[0]) + (ba[1] * bc[1]) + (ba[2] * bc[2])) / (nba * nbc)));
    return Math.acos(cosVal);
  }

  _supportCue(landmarks) {
    const ls = landmarks[11];
    const rs = landmarks[12];
    const le = landmarks[13];
    const re = landmarks[14];
    const lw = landmarks[15];
    const rw = landmarks[16];
    const lh = landmarks[23];
    const rh = landmarks[24];
    if (!ls || !rs || !le || !re || !lw || !rw || !lh || !rh) {
      return { hasSupport: false, forearmPlank: false, straightArmSupport: false, score: 0 };
    }

    const shoulderMid = { x: (ls.x + rs.x) / 2, y: (ls.y + rs.y) / 2 };
    const hipMid = { x: (lh.x + rh.x) / 2, y: (lh.y + rh.y) / 2 };
    const scale = Math.max(1e-6, Math.hypot(rs.x - ls.x, rs.y - ls.y), Math.hypot(shoulderMid.x - hipMid.x, shoulderMid.y - hipMid.y));

    const elbowAngleL = this.angleAt(ls, le, lw) * (180 / Math.PI);
    const elbowAngleR = this.angleAt(rs, re, rw) * (180 / Math.PI);
    const elbowAngleMin = Math.min(elbowAngleL || 180, elbowAngleR || 180);

    const elbowShoulderL = Math.hypot(le.x - ls.x, le.y - ls.y) / scale;
    const elbowShoulderR = Math.hypot(re.x - rs.x, re.y - rs.y) / scale;
    const wristShoulderL = Math.hypot(lw.x - ls.x, lw.y - ls.y) / scale;
    const wristShoulderR = Math.hypot(rw.x - rs.x, rw.y - rs.y) / scale;

    const elbowsNearShoulders = ((elbowShoulderL + elbowShoulderR) / 2) <= 0.55;
    const wristsNearShoulders = ((wristShoulderL + wristShoulderR) / 2) <= 0.8;
    const elbowsBelowShoulders = le.y >= (ls.y - 0.08) && le.y <= (ls.y + 0.24) && re.y >= (rs.y - 0.08) && re.y <= (rs.y + 0.24);
    const wristsAheadOrBelow = (lw.y >= le.y - 0.06) && (rw.y >= re.y - 0.06);
    const forearmPlank = elbowAngleMin >= 60 && elbowAngleMin <= 145 && elbowsNearShoulders && elbowsBelowShoulders && wristsAheadOrBelow;
    const straightArmSupport = elbowAngleMin >= 150 && wristsNearShoulders;
    const bodyLine = this._bodyLineScore(landmarks);

    let score = 0;
    if (forearmPlank) {
      score += 1.45;
    }
    if (straightArmSupport) {
      score += 1.0;
    }
    if ((forearmPlank || straightArmSupport) && bodyLine >= 0.72) {
      score += 0.35;
    }

    return {
      hasSupport: forearmPlank || straightArmSupport,
      forearmPlank,
      straightArmSupport,
      score,
    };
  }

  _bodyLineScore(landmarks) {
    const kneeExt = this.kneeExtensionDeg(landmarks);
    const hipExt = this.hipExtensionDeg(landmarks);
    if (!kneeExt.valid || !hipExt.valid) {
      return 0;
    }
    const kneeScore = Math.max(0, Math.min(1, Number(kneeExt.min || 0) / 170));
    const hipScore = Math.max(0, Math.min(1, Number(hipExt.min || 0) / 170));
    return (0.55 * hipScore) + (0.45 * kneeScore);
  }

  _emptyOrientation() {
    return {
      viewClass: "unknown",
      sideDirection: "unknown",
      postureClass: "unknown",
      lyingType: "unknown",
      supineScore: 0,
      proneScore: 0,
      kneeExtensionDeg: null,
      hipExtensionDeg: null,
      yawDeg: 0,
      tiltDeg: 0,
      yawProxy: 0,
      faceVisibility: 0,
      leftVisibility: 0,
      rightVisibility: 0,
      chestNormalX: null,
      chestNormalY: null,
      chestNormalZ: null,
      chestNormalConfidence: 0,
      floorHorizontalScore: 0,
    };
  }
}
