/// 2D keypoint with confidence score.
class Keypoint {
  final double x;
  final double y;
  final double score;

  const Keypoint({required this.x, required this.y, required this.score});

  Map<String, dynamic> toJson() => {'x': x, 'y': y, 'score': score};

  factory Keypoint.fromJson(Map<String, dynamic> json) => Keypoint(
        x: (json['x'] as num).toDouble(),
        y: (json['y'] as num).toDouble(),
        score: (json['score'] as num).toDouble(),
      );
}

/// 3D pose landmark from MediaPipe.
class PoseLandmark3D {
  final double x; // normalised image x [0,1]
  final double y; // normalised image y [0,1]
  final double z; // relative depth
  final double visibility;

  const PoseLandmark3D({
    required this.x,
    required this.y,
    required this.z,
    required this.visibility,
  });
}

/// Frame of named 2D keypoints.
typedef PoseFrame = Map<String, Keypoint>;
