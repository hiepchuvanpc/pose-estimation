import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' as p;
import 'package:uuid/uuid.dart';
import 'package:video_player/video_player.dart';

/// Service để xử lý video: trim, tạo thumbnail, encode
/// Note: FFmpeg Kit đã bị discontinued. Hiện tại sử dụng phương pháp đơn giản hơn.
/// Trong tương lai có thể thay bằng package khác hoặc native code.
class VideoProcessingService {
  static const _uuid = Uuid();

  /// Copy video file (placeholder cho trim - sẽ implement đầy đủ sau)
  /// Hiện tại chỉ copy file vì FFmpeg không available
  /// Returns: đường dẫn file video đã copy
  Future<String?> trimVideo({
    required String inputPath,
    required double startSec,
    required double endSec,
    void Function(double progress)? onProgress,
  }) async {
    try {
      final appDir = await getApplicationDocumentsDirectory();
      final outputDir = Directory(p.join(appDir.path, 'exercises', 'videos'));
      if (!await outputDir.exists()) {
        await outputDir.create(recursive: true);
      }

      final outputFileName = '${_uuid.v4()}.mp4';
      final outputPath = p.join(outputDir.path, outputFileName);

      // TODO: Implement actual trimming when FFmpeg alternative is available
      // For now, just copy the file and store trim points in database
      final inputFile = File(inputPath);
      await inputFile.copy(outputPath);
      
      debugPrint('Video copied (trim points: $startSec - $endSec): $outputPath');
      return outputPath;
    } catch (e) {
      debugPrint('Error copying video: $e');
      return null;
    }
  }

  /// Tạo placeholder thumbnail (không có FFmpeg)
  /// Returns: null - sẽ sử dụng placeholder image trong UI
  Future<String?> generateThumbnail({
    required String videoPath,
    double atSecond = 0.0,
    int width = 256,
    int height = 256,
  }) async {
    // TODO: Implement thumbnail generation
    // Options:
    // 1. Use native platform code via method channel
    // 2. Use video_thumbnail package (but it may have similar dependency issues)
    // 3. Generate on server if connected
    debugPrint('Thumbnail generation not available (FFmpeg discontinued)');
    return null;
  }

  /// Lấy thông tin video sử dụng video_player
  Future<VideoInfo?> getVideoInfo(String videoPath) async {
    VideoPlayerController? controller;
    try {
      controller = VideoPlayerController.file(File(videoPath));
      await controller.initialize();
      
      final duration = controller.value.duration.inMilliseconds / 1000.0;
      final size = controller.value.size;
      
      return VideoInfo(
        path: videoPath,
        durationSeconds: duration,
        width: size.width.toInt(),
        height: size.height.toInt(),
      );
    } catch (e) {
      debugPrint('Error getting video info: $e');
      return null;
    } finally {
      await controller?.dispose();
    }
  }

  /// Xóa file video
  Future<bool> deleteVideo(String videoPath) async {
    try {
      final file = File(videoPath);
      if (await file.exists()) {
        await file.delete();
        return true;
      }
      return false;
    } catch (e) {
      debugPrint('Error deleting video: $e');
      return false;
    }
  }
}

/// Thông tin video
class VideoInfo {
  final String path;
  final double durationSeconds;
  final int width;
  final int height;

  VideoInfo({
    required this.path,
    required this.durationSeconds,
    required this.width,
    required this.height,
  });

  String get formattedDuration {
    final minutes = (durationSeconds ~/ 60).toString().padLeft(2, '0');
    final seconds = (durationSeconds.toInt() % 60).toString().padLeft(2, '0');
    return '$minutes:$seconds';
  }

  @override
  String toString() => 'VideoInfo($path, $formattedDuration, ${width}x$height)';
}
