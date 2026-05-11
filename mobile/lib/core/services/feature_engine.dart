import '../utils/constants.dart';
import '../utils/math_utils.dart';

/// 10-dimensional feature extraction from pose landmarks.
///
/// Mirrors Python motion_core/features.py exactly:
///   - 6 joint angles (rotation-invariant)
///   - 4 normalised limb lengths (scale-invariant via torso normalisation)
class FeatureEngine {
  /// Extract 10-dim feature from 33 MediaPipe landmarks.
  ///
  /// [landmarks] is a list of at least 33 entries, each with (x, y, z).
  /// Returns [angle0..angle5, normLen0..normLen3].
  static List<double> fromLandmarkPositions(List<Vec3> pts) {
    if (pts.length < 29) {
      return List.filled(featureDim, 0.0);
    }

    final features = <double>[];
    final torso = torsoHeight(pts);

    // 6 angles
    for (final triplet in angleTriplets) {
      features.add(angle3pts(pts[triplet[0]], pts[triplet[1]], pts[triplet[2]]));
    }

    // 4 normalised limb lengths
    for (final pair in vectorPairs) {
      features.add(vecLength(pts[pair[0]], pts[pair[1]]) / torso);
    }

    return features;
  }

  /// Extract features from raw MediaPipe Pose Detection result.
  ///
  /// Each landmark has normalised x, y, z coordinates.
  static List<double> fromNormalisedLandmarks(
    List<Map<String, double>> landmarks,
  ) {
    final pts = <Vec3>[];
    for (int i = 0; i < 33; i++) {
      if (i < landmarks.length) {
        final lm = landmarks[i];
        pts.add(Vec3(lm['x'] ?? 0, lm['y'] ?? 0, lm['z'] ?? 0));
      } else {
        pts.add(const Vec3(0, 0, 0));
      }
    }
    return fromLandmarkPositions(pts);
  }

  /// Extract features from google_mlkit_pose_detection PoseLandmark list.
  ///
  /// Uses image-normalised coordinates x, y, z from each landmark.
  static List<double> fromMlKitLandmarks(List<dynamic> landmarks) {
    final pts = List<Vec3>.filled(33, const Vec3(0, 0, 0));
    for (final lm in landmarks) {
      final int index = lm.type.index;
      if (index < 33) {
        pts[index] = Vec3(
          lm.x as double,
          lm.y as double,
          lm.z as double,
        );
      }
    }
    return fromLandmarkPositions(pts);
  }

  /// Extract features from a stored pose sample (list of 33 points).
  /// Each point: [x, y, z, vis, ...optional world coords...]
  static List<double> fromSample(List<List<double>> sample) {
    final pts = <Vec3>[];
    for (int i = 0; i < 33; i++) {
      if (i < sample.length) {
        final p = sample[i];
        // Prefer world coordinates if available (indices 4-6)
        if (p.length >= 7) {
          pts.add(Vec3(p[4], p[5], p[6]));
        } else if (p.length >= 3) {
          pts.add(Vec3(p[0], p[1], p[2]));
        } else {
          pts.add(const Vec3(0, 0, 0));
        }
      } else {
        pts.add(const Vec3(0, 0, 0));
      }
    }
    return fromLandmarkPositions(pts);
  }
}
