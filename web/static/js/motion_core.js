/**
 * motion_core.js
 * Port of Python backend's real-time motion tracking logic to Javascript.
 * Ensures ZERO latency for phase transitions and video segmentation.
 */

// --- Constants & Indices ---
const LMK = {
    nose: 0, left_eye: 2, right_eye: 5, left_ear: 7, right_ear: 8,
    left_shoulder: 11, right_shoulder: 12,
    left_elbow: 13, right_elbow: 14,
    left_wrist: 15, right_wrist: 16,
    left_hip: 23, right_hip: 24,
    left_knee: 25, right_knee: 26,
    left_ankle: 27, right_ankle: 28
};

const HEAD_KEYS = [0, 2, 5, 7, 8];
const ANKLE_KEYS = [27, 28];
const VIS_THRESH = 0.2;

const ANGLE_TRIPLETS = [
    [11, 13, 15], [12, 14, 16], // elbows
    [23, 25, 27], [24, 26, 28], // knees
    [11, 23, 25], [12, 24, 26]  // hips
];
const VECTOR_PAIRS = [
    [23, 25], [24, 26], // thighs
    [11, 15], [12, 16]  // arms (shoulder to wrist)
];

// --- Math Helpers ---
function distance(p1, p2) {
    if (!p1 || !p2) return 0;
    return Math.hypot(p1.x - p2.x, p1.y - p2.y);
}

function angle3(a, b, c) {
    if (!a || !b || !c) return 0.0;
    const v1 = { x: a.x - b.x, y: a.y - b.y };
    const v2 = { x: c.x - b.x, y: c.y - b.y };
    const dot = v1.x * v2.x + v1.y * v2.y;
    const mag1 = Math.hypot(v1.x, v1.y);
    const mag2 = Math.hypot(v2.x, v2.y);
    if (mag1 < 1e-6 || mag2 < 1e-6) return 0.0;
    let cosTheta = dot / (mag1 * mag2);
    cosTheta = Math.max(-1.0, Math.min(1.0, cosTheta));
    return Math.acos(cosTheta);
}

// --- Readiness ---
function yawProxy(landmarks, eps=1e-6) {
    const ls = landmarks[LMK.left_shoulder];
    const rs = landmarks[LMK.right_shoulder];
    if (!ls || !rs || ls.visibility < VIS_THRESH || rs.visibility < VIS_THRESH) return 0.0;
    
    const l_hip = landmarks[LMK.left_hip];
    const r_hip = landmarks[LMK.right_hip];
    if (!l_hip || !r_hip) return 0.0;
    
    const neck = { x: (ls.x + rs.x)/2, y: (ls.y + rs.y)/2 };
    const hip = { x: (l_hip.x + r_hip.x)/2, y: (l_hip.y + r_hip.y)/2 };
    
    const shoulderWidth = distance(ls, rs);
    const torsoHeight = distance(neck, hip);
    return shoulderWidth / (torsoHeight + eps);
}

function viewSimilarity(studentLms, teacherLms, tauRho = 0.25) {
    const rhoS = yawProxy(studentLms);
    const rhoT = yawProxy(teacherLms);
    return Math.exp(-Math.abs(rhoS - rhoT) / Math.max(tauRho, 1e-6));
}

function inFrame(x, y) {
    return x >= 0 && x <= 1 && y >= 0 && y <= 1;
}

function completenessScore(landmarks) {
    const weights = {
        [LMK.left_shoulder]: 1.0, [LMK.right_shoulder]: 1.0,
        [LMK.left_hip]: 1.0, [LMK.right_hip]: 1.0,
        [LMK.left_knee]: 1.2, [LMK.right_knee]: 1.2,
        [LMK.left_ankle]: 1.2, [LMK.right_ankle]: 1.2,
        [LMK.left_elbow]: 0.8, [LMK.right_elbow]: 0.8,
        [LMK.left_wrist]: 0.8, [LMK.right_wrist]: 0.8
    };
    let wSum = 0.0;
    let tW = 0.0;
    for (const [idx, w] of Object.entries(weights)) {
        tW += w;
        const lm = landmarks[idx];
        if (!lm) continue;
        const s = lm.visibility >= VIS_THRESH ? lm.visibility : 0.0;
        wSum += w * Math.min(Math.max(s, 0.0), 1.0);
    }
    return tW <= 0 ? 0.0 : wSum / tW;
}

function framingScore(landmarks, tauCenter = 0.25) {
    const checkVis = (keys) => keys.some(k => {
        const lm = landmarks[k];
        return lm && lm.visibility >= VIS_THRESH && inFrame(lm.x, lm.y);
    });
    
    if (!checkVis(HEAD_KEYS) || !checkVis(ANKLE_KEYS)) return 0.0;
    
    const visible = landmarks.filter(lm => lm && lm.visibility >= VIS_THRESH && inFrame(lm.x, lm.y));
    if (!visible.length) return 0.0;
    
    const cx = visible.reduce((sum, lm) => sum + lm.x, 0) / visible.length;
    const cy = visible.reduce((sum, lm) => sum + lm.y, 0) / visible.length;
    
    const dx = cx - 0.5;
    const dy = cy - 0.5;
    const centerDist = Math.hypot(dx, dy);
    return Math.exp(-centerDist / Math.max(tauCenter, 1e-6));
}

function getReadiness(studentLms, teacherLms) {
    const sView = viewSimilarity(studentLms, teacherLms);
    const sComp = completenessScore(studentLms);
    const sFrame = framingScore(studentLms);
    const total = 0.4 * sView + 0.4 * sComp + 0.2 * sFrame;
    
    const feedback = [];
    if (sView < 0.7) feedback.push("Điều chỉnh góc quay cơ thể để tương đồng hơn với giáo viên.");
    if (sComp < 0.75) feedback.push("Đảm bảo toàn thân vào khung hình (vai, hông, gối, chân).");
    if (sFrame < 0.7) feedback.push("Đưa cơ thể vào giữa khung hình và không bị cắt đầu/chân.");
    if (feedback.length === 0) feedback.push("Sẵn sàng so khớp động tác.");
    
    return { isReady: feedback.length === 1 && feedback[0].includes("Sẵn sàng"), feedback };
}

// --- Features & Signals ---
function extractFeatures(landmarks) {
    const features = [];
    // Angles
    for (const [a, b, c] of ANGLE_TRIPLETS) {
        features.push(angle3(landmarks[a], landmarks[b], landmarks[c]));
    }
    // Vectors
    for (const [a, b] of VECTOR_PAIRS) {
        const lmA = landmarks[a];
        const lmB = landmarks[b];
        if (!lmA || !lmB) {
            features.push(0, 0, 0);
            continue;
        }
        const vx = lmB.x - lmA.x;
        const vy = lmB.y - lmA.y;
        const len = Math.hypot(vx, vy);
        if (len < 1e-6) {
            features.push(0, 0, 0);
        } else {
            features.push(vx / len, vy / len, len);
        }
    }
    return features;
}

function computeSignalAndSimilarity(feature, profile) {
    const mean = profile.feature_mean || [];
    const pc1 = profile.feature_pc1 || [];
    const refFeatures = profile.features || [];
    
    if (!mean.length || !pc1.length || !refFeatures.length) {
        return { signal: 0.0, similarity: 0.0 };
    }
    
    const centered = feature.map((v, i) => v - (mean[i] || 0.0));
    let proj = 0.0;
    for (let i = 0; i < centered.length; i++) {
        proj += centered[i] * (pc1[i] || 0.0);
    }
    
    const minP = Number(profile.proj_min || 0.0);
    const maxP = Number(profile.proj_max || 1.0);
    const denom = Math.max(1e-6, maxP - minP);
    const phaseSignal = Math.max(0.0, Math.min(1.0, (proj - minP) / denom));
    
    let minDist = Infinity;
    for (const ref of refFeatures) {
        let total = 0.0;
        for (let i = 0; i < feature.length; i++) {
            const diff = feature[i] - (ref[i] || 0.0);
            total += diff * diff;
        }
        minDist = Math.min(minDist, Math.sqrt(total));
    }
    
    const similarity = minDist !== Infinity ? Math.exp(-minDist / 2.8) : 0.0;
    const signal = (0.65 * phaseSignal) + (0.35 * similarity);
    
    return {
        signal: Math.max(0.0, Math.min(1.0, signal)),
        similarity
    };
}

// --- Trackers ---
class SignalNormalizer {
    constructor() {
        this.min = 1.0;
        this.max = 0.0;
        this.count = 0;
        this.warmup = 5;
    }
    normalize(raw) {
        const s = Math.max(0.0, Math.min(1.0, raw));
        this.min = Math.min(this.min, s);
        this.max = Math.max(this.max, s);
        this.count++;
        if (this.count < this.warmup) {
            return s;
        }
        const span = this.max - this.min;
        if (span < 0.08) {
            return s;
        }
        return Math.max(0.0, Math.min(1.0, (s - this.min) / span));
    }
    reset() {
        this.min = 1.0;
        this.max = 0.0;
        this.count = 0;
    }
}

class RepCounter {
    constructor() {
        this.highEnter = 0.72;
        this.lowExit = 0.38;
        this.minHighFrames = 1;
        this.minRepDurationMs = 100;
        this.repCount = 0;
        this.state = "down";
        this.highFrames = 0;
        this.lastRepTs = 0;
        this._debugInterval = 0;
    }
    update(signal, timestampMs) {
        const s = Math.max(0.0, Math.min(1.0, signal));
        // Debug: log signal every ~10 calls to console
        this._debugInterval++;
        if (this._debugInterval % 10 === 0) {
            console.log(`[RepCounter] signal=${s.toFixed(3)} state=${this.state} reps=${this.repCount}`);
        }
        if (this.state === "down") {
            if (s >= this.highEnter) {
                this.highFrames++;
                if (this.highFrames >= this.minHighFrames) {
                    this.state = "up";
                    this.highFrames = 0;
                    console.log(`[RepCounter] -> UP at signal=${s.toFixed(3)}`);
                }
            } else {
                this.highFrames = 0;
            }
        } else {
            if (s <= this.lowExit) {
                const elapsed = timestampMs - this.lastRepTs;
                if (elapsed >= this.minRepDurationMs || this.lastRepTs === 0) {
                    this.repCount++;
                    this.lastRepTs = timestampMs;
                    console.log(`[RepCounter] REP ${this.repCount}! signal=${s.toFixed(3)}`);
                }
                this.state = "down";
            }
        }
        return this.repCount;
    }
}

class HoldTimer {
    constructor() {
        this.threshold = 0.65;
        this.holdMs = 0;
        this.lastTs = 0;
        this.active = false;
    }
    update(s, timestampMs) {
        if (this.lastTs === 0) {
            this.lastTs = timestampMs;
            this.active = s >= this.threshold;
            return 0;
        }
        const delta = timestampMs - this.lastTs;
        this.lastTs = timestampMs;
        if (s >= this.threshold) {
            this.holdMs += delta;
            this.active = true;
        } else {
            this.active = false;
        }
        return Math.floor(this.holdMs / 1000);
    }
}

// --- Session Orchestrator ---
window.WorkoutSessionJS = class WorkoutSessionJS {
    constructor(templates, plan) {
        this.templates = templates; // dict mapping id -> template info
        this.plan = plan; // { steps: [{template_id, sets, reps_per_set, hold_seconds_per_set}, ...] }
        this.stepIndex = 0;
        this.setIndex = 0;
        this.phase = "waiting_readiness"; // waiting_readiness, active_set, rest_pending_confirmation, done
        this.repCount = 0;
        this.holdSeconds = 0;
        
        this.tracker = null;
        this.trackingStarted = false;
        this.pendingConfirmation = false;
        
        this._setupTracker();
    }
    
    _setupTracker() {
        const step = this.plan.steps[this.stepIndex];
        if (!step) return;
        const tpl = this.templates[step.template_id];
        if (tpl.mode === "reps") {
            this.tracker = new RepCounter();
        } else {
            this.tracker = new HoldTimer();
        }
        this.repCount = 0;
        this.holdSeconds = 0;
        this.trackingStarted = false;
    }
    
    _getCurrentConfig() {
        const step = this.plan.steps[this.stepIndex];
        if (!step) return null;
        const tpl = this.templates[step.template_id];
        if (!tpl) return null;
        return { step, tpl };
    }
    
    frameUpdate(signal, timestampMs, readinessPassed) {
        if (this.phase === "done") {
            return this._buildState([]);
        }
        
        const config = this._getCurrentConfig();
        if (!config) {
            this.phase = "done";
            return this._buildState(["Hoàn thành buổi tập."]);
        }
        const { step, tpl } = config;
        const maxSets = step.sets || 1;
        const targetReps = step.reps_per_set || 0;
        const targetHold = step.hold_seconds_per_set || 0;
        
        const announcements = [];
        
        if (this.phase === "waiting_readiness") {
            if (readinessPassed) {
                this.phase = "active_set";
                this.trackingStarted = false;
                announcements.push(`Bắt đầu set ${this.setIndex + 1}.`);
            }
        }
        
        if (this.phase === "active_set") {
            if (tpl.mode === "reps") {
                const preRep = this.repCount;
                this.repCount = this.tracker.update(signal, timestampMs);
                this.trackingStarted = Boolean(
                    this.repCount > 0
                    || this.tracker.highFrames > 0
                    || this.tracker.state === "up"
                );
                if (this.repCount > preRep) {
                    announcements.push(String(this.repCount));
                }
                if (targetReps > 0 && this.repCount >= targetReps) {
                    this._completeSet(announcements, maxSets);
                }
            } else {
                const preHold = this.holdSeconds;
                this.holdSeconds = this.tracker.update(signal, timestampMs);
                this.trackingStarted = Boolean(
                    this.holdSeconds > 0
                    || this.tracker.active
                );
                if (this.holdSeconds > preHold && this.holdSeconds % 5 === 0) {
                    announcements.push(`${this.holdSeconds} giây`);
                }
                if (targetHold > 0 && this.holdSeconds >= targetHold) {
                    this._completeSet(announcements, maxSets);
                }
            }
        }
        
        return this._buildState(announcements);
    }
    
    _completeSet(announcements, maxSets) {
        announcements.push("Hoàn thành set.");
        this.setIndex++;
        if (this.setIndex >= maxSets) {
            this.stepIndex++;
            this.setIndex = 0;
            if (this.stepIndex >= this.plan.steps.length) {
                this.phase = "done";
                this.pendingConfirmation = false;
                announcements.push("Hoàn thành buổi tập. Chúc mừng!");
            } else {
                this.phase = "exercise_pending_confirmation";
                this.pendingConfirmation = true;
            }
        } else {
            this.phase = "rest_pending_confirmation";
            this.pendingConfirmation = true;
        }
        this.trackingStarted = false;
    }
    
    confirm() {
        if (!this.pendingConfirmation) return this._buildState([]);
        if (this.phase === "rest_pending_confirmation" || this.phase === "exercise_pending_confirmation") {
            this.phase = "waiting_readiness";
            this.pendingConfirmation = false;
            this._setupTracker();
            return this._buildState(["Chuẩn bị."]);
        }
        return this._buildState([]);
    }
    
    _buildState(announcements) {
        const config = this._getCurrentConfig();
        const step = config ? config.step : {};
        const tpl = config ? config.tpl : {};
        return {
            phase: this.phase,
            step_index: this.stepIndex,
            set_index: this.setIndex,
            exercise_name: tpl.name || "",
            rep_count: this.repCount,
            hold_seconds: this.holdSeconds,
            tracking_started: this.trackingStarted,
            pending_confirmation: this.pendingConfirmation,
            announcements: announcements
        };
    }
};

window.MotionMath = {
    getReadiness,
    extractFeatures,
    computeSignalAndSimilarity,
    completenessScore,
    framingScore
};
