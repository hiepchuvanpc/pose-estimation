import 'dart:io';

import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' as p;

/// Service for managing local file storage (videos, thumbnails, etc.)
class FileStorageService {
  static const String _videosDir = 'videos';
  static const String _thumbnailsDir = 'thumbnails';
  static const String _processedDir = 'processed';
  static const String _exportDir = 'exports';

  Directory? _appDir;

  /// Initialize and create necessary directories
  Future<void> init() async {
    _appDir = await getApplicationDocumentsDirectory();
    await _ensureDirectoriesExist();
  }

  Future<void> _ensureDirectoriesExist() async {
    if (_appDir == null) return;
    
    final dirs = [_videosDir, _thumbnailsDir, _processedDir, _exportDir];
    for (final dir in dirs) {
      final directory = Directory(p.join(_appDir!.path, 'MotionCoach', dir));
      if (!await directory.exists()) {
        await directory.create(recursive: true);
      }
    }
  }

  /// Get the app's base storage directory
  Future<Directory> get baseDirectory async {
    _appDir ??= await getApplicationDocumentsDirectory();
    return Directory(p.join(_appDir!.path, 'MotionCoach'));
  }

  /// Get videos directory
  Future<Directory> get videosDirectory async {
    final base = await baseDirectory;
    return Directory(p.join(base.path, _videosDir));
  }

  /// Get thumbnails directory
  Future<Directory> get thumbnailsDirectory async {
    final base = await baseDirectory;
    return Directory(p.join(base.path, _thumbnailsDir));
  }

  /// Get processed videos directory
  Future<Directory> get processedDirectory async {
    final base = await baseDirectory;
    return Directory(p.join(base.path, _processedDir));
  }

  /// Get exports directory
  Future<Directory> get exportsDirectory async {
    final base = await baseDirectory;
    return Directory(p.join(base.path, _exportDir));
  }

  /// Save a video file and return its local path
  Future<String> saveVideo(File sourceFile, String exerciseId) async {
    final dir = await videosDirectory;
    final ext = p.extension(sourceFile.path);
    final destPath = p.join(dir.path, '$exerciseId$ext');
    
    await sourceFile.copy(destPath);
    return destPath;
  }

  /// Save a trimmed video segment
  Future<String> saveTrimmedVideo(
    File sourceFile,
    String exerciseId, {
    required double startTime,
    required double endTime,
  }) async {
    final dir = await videosDirectory;
    final ext = p.extension(sourceFile.path);
    final destPath = p.join(dir.path, '${exerciseId}_trimmed$ext');
    
    // For now, just copy the file
    // In production, use ffmpeg_kit to trim video
    await sourceFile.copy(destPath);
    return destPath;
  }

  /// Save a thumbnail image
  Future<String> saveThumbnail(File thumbnailFile, String exerciseId) async {
    final dir = await thumbnailsDirectory;
    final destPath = p.join(dir.path, '$exerciseId.jpg');
    
    await thumbnailFile.copy(destPath);
    return destPath;
  }

  /// Save processed workout video
  Future<String> saveProcessedVideo(File videoFile, String sessionId) async {
    final dir = await processedDirectory;
    final ext = p.extension(videoFile.path);
    final destPath = p.join(dir.path, '${sessionId}_processed$ext');
    
    await videoFile.copy(destPath);
    return destPath;
  }

  /// Get video file for an exercise
  Future<File?> getExerciseVideo(String exerciseId) async {
    final dir = await videosDirectory;
    final files = await dir.list().toList();
    
    for (final entity in files) {
      if (entity is File && p.basenameWithoutExtension(entity.path) == exerciseId) {
        return entity;
      }
    }
    return null;
  }

  /// Get thumbnail file for an exercise
  Future<File?> getExerciseThumbnail(String exerciseId) async {
    final dir = await thumbnailsDirectory;
    final thumbPath = p.join(dir.path, '$exerciseId.jpg');
    final file = File(thumbPath);
    
    if (await file.exists()) {
      return file;
    }
    return null;
  }

  /// Delete exercise files (video + thumbnail)
  Future<void> deleteExerciseFiles(String exerciseId) async {
    final video = await getExerciseVideo(exerciseId);
    final thumb = await getExerciseThumbnail(exerciseId);
    
    if (video != null && await video.exists()) {
      await video.delete();
    }
    if (thumb != null && await thumb.exists()) {
      await thumb.delete();
    }
  }

  /// Delete processed video for a session
  Future<void> deleteProcessedVideo(String sessionId) async {
    final dir = await processedDirectory;
    final files = await dir.list().toList();
    
    for (final entity in files) {
      if (entity is File && entity.path.contains(sessionId)) {
        await entity.delete();
      }
    }
  }

  /// Get storage usage in bytes
  Future<int> getStorageUsage() async {
    final base = await baseDirectory;
    if (!await base.exists()) return 0;
    
    int totalSize = 0;
    await for (final entity in base.list(recursive: true)) {
      if (entity is File) {
        totalSize += await entity.length();
      }
    }
    return totalSize;
  }

  /// Clear all stored files
  Future<void> clearAllFiles() async {
    final base = await baseDirectory;
    if (await base.exists()) {
      await base.delete(recursive: true);
    }
    await _ensureDirectoriesExist();
  }

  /// List all video files
  Future<List<File>> listAllVideos() async {
    final dir = await videosDirectory;
    if (!await dir.exists()) return [];
    
    final files = <File>[];
    await for (final entity in dir.list()) {
      if (entity is File) {
        files.add(entity);
      }
    }
    return files;
  }

  /// Export all data to a zip file (for backup)
  Future<String?> exportToZip() async {
    // Implementation would use archive package
    // For now, return null (not implemented)
    return null;
  }

  /// Import data from a zip file
  Future<bool> importFromZip(String zipPath) async {
    // Implementation would use archive package
    // For now, return false (not implemented)
    return false;
  }
}
