import 'package:flutter/material.dart';
import 'package:google_mlkit_pose_detection/google_mlkit_pose_detection.dart';

import '../../../core/utils/constants.dart';
import '../../../shared/theme/app_colors.dart';

/// Draws pose skeleton overlay on camera preview.
class PoseOverlay extends StatelessWidget {
  final Map<PoseLandmarkType, PoseLandmark>? landmarks;
  final Size imageSize;
  final Size widgetSize;
  final bool isFrontCamera;
  final double coreVisibility;

  const PoseOverlay({
    super.key,
    required this.landmarks,
    required this.imageSize,
    required this.widgetSize,
    this.isFrontCamera = true,
    this.coreVisibility = 0.0,
  });

  @override
  Widget build(BuildContext context) {
    if (landmarks == null || landmarks!.isEmpty) return const SizedBox();

    return CustomPaint(
      size: widgetSize,
      painter: _PoseSkeletonPainter(
        landmarks: landmarks!,
        imageSize: imageSize,
        widgetSize: widgetSize,
        isFrontCamera: isFrontCamera,
        coreVisibility: coreVisibility,
      ),
    );
  }
}

class _PoseSkeletonPainter extends CustomPainter {
  final Map<PoseLandmarkType, PoseLandmark> landmarks;
  final Size imageSize;
  final Size widgetSize;
  final bool isFrontCamera;
  final double coreVisibility;

  _PoseSkeletonPainter({
    required this.landmarks,
    required this.imageSize,
    required this.widgetSize,
    required this.isFrontCamera,
    required this.coreVisibility,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final linePaint = Paint()
      ..color = AppColors.skeletonLine.withValues(alpha: 0.8)
      ..strokeWidth = 3.0
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round;

    final jointPaint = Paint()
      ..style = PaintingStyle.fill;

    // Draw connections
    for (final connection in poseConnections) {
      final startType = PoseLandmarkType.values[connection[0]];
      final endType = PoseLandmarkType.values[connection[1]];

      final startLm = landmarks[startType];
      final endLm = landmarks[endType];

      if (startLm != null && endLm != null) {
        if (startLm.likelihood > 0.3 && endLm.likelihood > 0.3) {
          final start = _transformPoint(startLm);
          final end = _transformPoint(endLm);
          canvas.drawLine(start, end, linePaint);
        }
      }
    }

    // Draw joints
    for (final entry in landmarks.entries) {
      final lm = entry.value;
      if (lm.likelihood > 0.3) {
        final point = _transformPoint(lm);
        final isGoodVisibility = lm.likelihood > 0.6;
        jointPaint.color = isGoodVisibility
            ? AppColors.skeletonJoint
            : AppColors.skeletonJointLow;
        canvas.drawCircle(point, isGoodVisibility ? 6 : 4, jointPaint);

        // Glow effect for good visibility
        if (isGoodVisibility) {
          jointPaint.color = AppColors.skeletonJoint.withValues(alpha: 0.3);
          canvas.drawCircle(point, 10, jointPaint);
        }
      }
    }
  }

  Offset _transformPoint(PoseLandmark lm) {
    final scaleX = widgetSize.width / imageSize.width;
    final scaleY = widgetSize.height / imageSize.height;

    double x = lm.x * scaleX;
    final y = lm.y * scaleY;

    // Mirror for front camera
    if (isFrontCamera) {
      x = widgetSize.width - x;
    }

    return Offset(x, y);
  }

  @override
  bool shouldRepaint(covariant _PoseSkeletonPainter old) => true;
}
