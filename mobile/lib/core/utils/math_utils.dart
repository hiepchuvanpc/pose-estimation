import 'dart:math' as math;

/// 3D point for vector math operations.
class Vec3 {
  final double x, y, z;
  const Vec3(this.x, this.y, this.z);

  Vec3 operator -(Vec3 other) => Vec3(x - other.x, y - other.y, z - other.z);
  Vec3 operator +(Vec3 other) => Vec3(x + other.x, y + other.y, z + other.z);
  Vec3 operator *(double s) => Vec3(x * s, y * s, z * s);

  double get norm => math.sqrt(x * x + y * y + z * z);

  double dot(Vec3 other) => x * other.x + y * other.y + z * other.z;
}

/// Angle at point b formed by segments ba and bc (radians).
/// Mirrors _angle_3pts in Python features.py.
double angle3pts(Vec3 a, Vec3 b, Vec3 c) {
  final ba = a - b;
  final bc = c - b;
  final nba = ba.norm;
  final nbc = bc.norm;
  if (nba < 1e-6 || nbc < 1e-6) return 0.0;
  final cosVal = (ba.dot(bc) / (nba * nbc)).clamp(-1.0, 1.0);
  return math.acos(cosVal);
}

/// Distance between two 3D points.
double vecLength(Vec3 a, Vec3 b) => (b - a).norm;

/// Torso height: distance from mid-shoulder to mid-hip.
/// Used for limb length normalisation.
double torsoHeight(List<Vec3> pts) {
  final midShoulder = (pts[11] + pts[12]) * 0.5;
  final midHip = (pts[23] + pts[24]) * 0.5;
  return math.max(vecLength(midShoulder, midHip), 1e-6);
}

/// Euclidean distance between two feature vectors.
double euclideanDistance(List<double> a, List<double> b) {
  final n = math.min(a.length, b.length);
  if (n == 0) return 0.0;
  double sum = 0.0;
  for (int i = 0; i < n; i++) {
    final d = a[i] - b[i];
    sum += d * d;
  }
  return math.sqrt(sum);
}

/// Clamp value between lo and hi.
double clamp(double value, double lo, double hi) =>
    math.max(lo, math.min(hi, value));

/// Simple moving-average smoothing.
List<double> smoothSignal(List<double> values, {int window = 5}) {
  if (values.length <= window) return List.of(values);
  final out = <double>[];
  for (int i = 0; i < values.length; i++) {
    final lo = math.max(0, i - window ~/ 2);
    final hi = math.min(values.length, i + window ~/ 2 + 1);
    double sum = 0.0;
    for (int j = lo; j < hi; j++) {
      sum += values[j];
    }
    out.add(sum / (hi - lo));
  }
  return out;
}
