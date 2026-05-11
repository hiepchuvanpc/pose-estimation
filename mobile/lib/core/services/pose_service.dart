import 'package:google_mlkit_pose_detection/google_mlkit_pose_detection.dart';

import '../utils/math_utils.dart';

/// On-device MediaPipe Pose Detection service.
///
/// Uses google_mlkit_pose_detection which wraps MediaPipe Pose Landmarker
/// for both Android (OpenCL GPU) and iOS (CoreML).
class PoseService {
  PoseDetector? _detector;
  bool _isBusy = false;

  /// Initialize the pose detector with lite model for best performance.
  void initialize() {
    _detector = PoseDetector(
      options: PoseDetectorOptions(
        model: PoseDetectionModel.base, // lighter, faster inference
        mode: PoseDetectionMode.stream, // optimised for video frames
      ),
    );
  }

  /// Process a camera frame and return pose landmarks.
  ///
  /// Returns null if no pose detected or detector is busy.
  Future<PoseResult?> processFrame(InputImage inputImage) async {
    if (_detector == null || _isBusy) return null;
    _isBusy = true;

    try {
      final poses = await _detector!.processImage(inputImage);
      if (poses.isEmpty) return null;

      // Take first (most prominent) person
      final pose = poses.first;
      final landmarks = pose.landmarks;

      // Build normalised Vec3 list for feature extraction
      final pts = List<Vec3>.filled(33, const Vec3(0, 0, 0));
      final visibilities = List<double>.filled(33, 0.0);

      for (final entry in landmarks.entries) {
        final lm = entry.value;
        final idx = entry.key.index;
        if (idx < 33) {
          pts[idx] = Vec3(lm.x, lm.y, lm.z);
          visibilities[idx] = lm.likelihood;
        }
      }

      return PoseResult(
        landmarks: pts,
        visibilities: visibilities,
        rawLandmarks: landmarks,
      );
    } catch (_) {
      return null;
    } finally {
      _isBusy = false;
    }
  }

  /// Release resources.
  Future<void> dispose() async {
    await _detector?.close();
    _detector = null;
  }
}

/// Processed pose result.
class PoseResult {
  /// 33 landmark positions as Vec3 (pixel coordinates).
  final List<Vec3> landmarks;

  /// Visibility/likelihood for each landmark [0..1].
  final List<double> visibilities;

  /// Raw ML Kit landmarks for drawing overlay.
  final Map<PoseLandmarkType, PoseLandmark> rawLandmarks;

  const PoseResult({
    required this.landmarks,
    required this.visibilities,
    required this.rawLandmarks,
  });

  /// Average visibility of core keypoints (shoulders, hips, knees).
  double get coreVisibility {
    const coreIndices = [11, 12, 23, 24, 25, 26];
    double sum = 0;
    int count = 0;
    for (final idx in coreIndices) {
      if (idx < visibilities.length) {
        sum += visibilities[idx];
        count++;
      }
    }
    return count > 0 ? sum / count : 0;
  }
}
