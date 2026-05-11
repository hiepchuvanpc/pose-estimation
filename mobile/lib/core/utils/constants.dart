/// Landmark indices matching MediaPipe Pose (33 landmarks).
/// Mirrors motion_core/features.py ANGLE_TRIPLETS_IDX, VECTOR_PAIRS_IDX.
class LandmarkIndex {
  static const int nose = 0;
  static const int leftEye = 2;
  static const int rightEye = 5;
  static const int leftEar = 7;
  static const int rightEar = 8;
  static const int leftShoulder = 11;
  static const int rightShoulder = 12;
  static const int leftElbow = 13;
  static const int rightElbow = 14;
  static const int leftWrist = 15;
  static const int rightWrist = 16;
  static const int leftHip = 23;
  static const int rightHip = 24;
  static const int leftKnee = 25;
  static const int rightKnee = 26;
  static const int leftAnkle = 27;
  static const int rightAnkle = 28;

  /// Named map for readiness (mirrors mediapipe_pose.py LANDMARK_INDEX)
  static const Map<String, int> nameToIndex = {
    'nose': nose,
    'left_eye': leftEye,
    'right_eye': rightEye,
    'left_ear': leftEar,
    'right_ear': rightEar,
    'left_shoulder': leftShoulder,
    'right_shoulder': rightShoulder,
    'left_elbow': leftElbow,
    'right_elbow': rightElbow,
    'left_wrist': leftWrist,
    'right_wrist': rightWrist,
    'left_hip': leftHip,
    'right_hip': rightHip,
    'left_knee': leftKnee,
    'right_knee': rightKnee,
    'left_ankle': leftAnkle,
    'right_ankle': rightAnkle,
  };
}

/// 6 angle triplets – same as Python features.py
const List<List<int>> angleTriplets = [
  [11, 13, 15], // left elbow
  [12, 14, 16], // right elbow
  [23, 25, 27], // left knee
  [24, 26, 28], // right knee
  [11, 23, 25], // left hip
  [12, 24, 26], // right hip
];

/// 4 vector pairs for normalised limb lengths
const List<List<int>> vectorPairs = [
  [23, 25], // left hip-knee
  [24, 26], // right hip-knee
  [11, 15], // left shoulder-wrist
  [12, 16], // right shoulder-wrist
];

/// Feature dimension: 6 angles + 4 lengths = 10
const int featureDim = 10;

/// Default readiness weights
const Map<String, double> defaultReadinessWeights = {
  'left_shoulder': 1.0,
  'right_shoulder': 1.0,
  'left_hip': 1.0,
  'right_hip': 1.0,
  'left_knee': 1.2,
  'right_knee': 1.2,
  'left_ankle': 1.2,
  'right_ankle': 1.2,
  'left_elbow': 0.8,
  'right_elbow': 0.8,
  'left_wrist': 0.8,
  'right_wrist': 0.8,
};

/// Pose skeleton connections for drawing overlay
const List<List<int>> poseConnections = [
  [11, 12], // shoulders
  [11, 13], // left shoulder → elbow
  [13, 15], // left elbow → wrist
  [12, 14], // right shoulder → elbow
  [14, 16], // right elbow → wrist
  [11, 23], // left shoulder → hip
  [12, 24], // right shoulder → hip
  [23, 24], // hips
  [23, 25], // left hip → knee
  [25, 27], // left knee → ankle
  [24, 26], // right hip → knee
  [26, 28], // right knee → ankle
];
