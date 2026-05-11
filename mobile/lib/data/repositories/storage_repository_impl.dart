import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:dartz/dartz.dart';
import 'package:flutter/foundation.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../core/errors/failures.dart';
import '../../domain/entities/user.dart';
import '../../domain/repositories/storage_repository.dart';
import '../datasources/local/database.dart' as db;
import '../datasources/local/file_storage_service.dart';
import '../datasources/remote/google_drive_service.dart';
import '../datasources/remote/motion_coach_server_service.dart';

/// Implementation of StorageRepository handling all 3 storage modes
class StorageRepositoryImpl implements StorageRepository {
  final db.AppDatabase _database;
  final FileStorageService _fileStorage;
  final GoogleDriveService _driveService;
  final MotionCoachServerService _serverService;
  final GoogleSignIn _googleSignIn;

  static const String _storageModeKey = 'storage_mode';
  final StreamController<SyncResult> _syncStatusController =
      StreamController<SyncResult>.broadcast();

  StorageRepositoryImpl({
    required db.AppDatabase database,
    required FileStorageService fileStorage,
    required GoogleDriveService driveService,
    required MotionCoachServerService serverService,
    required GoogleSignIn googleSignIn,
  })  : _database = database,
        _fileStorage = fileStorage,
        _driveService = driveService,
        _serverService = serverService,
        _googleSignIn = googleSignIn;

  @override
  Future<StorageMode> getCurrentStorageMode() async {
    final prefs = await SharedPreferences.getInstance();
    final modeString = prefs.getString(_storageModeKey);
    
    switch (modeString) {
      case 'googleDrive':
        return StorageMode.googleDrive;
      case 'server':
        return StorageMode.server;
      default:
        return StorageMode.local;
    }
  }

  @override
  Future<Either<Failure, void>> setStorageMode(StorageMode mode) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final currentMode = await getCurrentStorageMode();
      
      if (currentMode == mode) {
        return const Right(null);
      }

      // Validate mode change
      if (mode == StorageMode.googleDrive) {
        final hasPermissions = await hasDrivePermissions();
        if (!hasPermissions) {
          return const Left(StorageFailure('Chưa cấp quyền Google Drive'));
        }
      } else if (mode == StorageMode.server) {
        if (!_serverService.isAuthenticated) {
          return const Left(StorageFailure('Chưa đăng nhập để dùng Server'));
        }
      }

      // Save new mode
      String modeString;
      switch (mode) {
        case StorageMode.googleDrive:
          modeString = 'googleDrive';
          break;
        case StorageMode.server:
          modeString = 'server';
          break;
        default:
          modeString = 'local';
      }
      await prefs.setString(_storageModeKey, modeString);

      // Trigger migration if needed
      await _migrateData(fromMode: currentMode, toMode: mode);

      return const Right(null);
    } catch (e) {
      return Left(StorageFailure('Không thể đổi chế độ lưu trữ: $e'));
    }
  }

  @override
  Future<bool> hasDrivePermissions() async {
    try {
      final account = _googleSignIn.currentUser;
      if (account == null) return false;
      
      // Check if we have Drive scope
      final scopes = _googleSignIn.scopes;
      return scopes.contains('https://www.googleapis.com/auth/drive.file') ||
             scopes.contains('https://www.googleapis.com/auth/drive.appdata');
    } catch (e) {
      return false;
    }
  }

  @override
  Future<Either<Failure, void>> requestDrivePermissions() async {
    try {
      // Request additional scope for Drive
      final account = await _googleSignIn.signIn();
      if (account == null) {
        return const Left(StorageFailure('Người dùng từ chối cấp quyền'));
      }
      
      // Initialize Drive service
      final initialized = await _driveService.init();
      if (!initialized) {
        return const Left(StorageFailure('Không thể kết nối Google Drive'));
      }
      
      return const Right(null);
    } catch (e) {
      return Left(StorageFailure('Lỗi khi yêu cầu quyền Drive: $e'));
    }
  }

  @override
  Future<Either<Failure, SyncResult>> syncToCloud() async {
    final mode = await getCurrentStorageMode();
    
    if (mode == StorageMode.local) {
      return const Right(SyncResult(syncedCount: 0));
    }

    _syncStatusController.add(const SyncResult()); // Start sync

    try {
      if (mode == StorageMode.googleDrive) {
        return await _syncToDrive();
      } else if (mode == StorageMode.server) {
        return await _syncToServer();
      }
      return const Right(SyncResult(syncedCount: 0));
    } catch (e) {
      final result = SyncResult(failedCount: 1, errors: [e.toString()]);
      _syncStatusController.add(result);
      return Left(SyncFailure('Lỗi đồng bộ: $e'));
    }
  }

  Future<Either<Failure, SyncResult>> _syncToDrive() async {
    if (!_driveService.isReady) {
      final initialized = await _driveService.init();
      if (!initialized) {
        return const Left(StorageFailure('Không thể kết nối Google Drive'));
      }
    }

    int syncedCount = 0;
    final errors = <String>[];

    try {
      // Get all pending sync items
      final pendingItems = await _database.getPendingSyncItems();

      for (final item in pendingItems) {
        try {
          switch (item.entityType) {
            case 'exercise':
              await _syncExerciseToDrive(item.entityId);
              break;
            case 'lesson':
              await _syncLessonToDrive(item.entityId);
              break;
            case 'session':
              await _syncSessionToDrive(item.entityId);
              break;
          }
          
          // Mark as synced
          await _database.deleteSyncItem(item.id);
          syncedCount++;
        } catch (e) {
          errors.add('${item.entityType}/${item.entityId}: $e');
          await _database.updateSyncItemRetry(
            item.id,
            item.retryCount + 1,
            e.toString(),
          );
        }
      }

      final result = SyncResult(
        syncedCount: syncedCount,
        failedCount: errors.length,
        errors: errors,
      );
      _syncStatusController.add(result);
      return Right(result);
    } catch (e) {
      return Left(SyncFailure('Lỗi đồng bộ Drive: $e'));
    }
  }

  Future<void> _syncExerciseToDrive(String exerciseId) async {
    // Get exercise from database
    final exercise = await _database.getExerciseById(exerciseId);
    if (exercise == null) return;

    // Upload video if exists
    final videoFile = await _fileStorage.getExerciseVideo(exerciseId);
    if (videoFile != null) {
      final exercisesFolderId = await _driveService.getExercisesFolderId();
      await _driveService.uploadFile(
        videoFile,
        '$exerciseId.mp4',
        parentFolderId: exercisesFolderId,
      );
    }

    // Upload metadata
    await _driveService.uploadMetadata(
      {
        'id': exercise.id,
        'name': exercise.name,
        'mode': exercise.mode,
        'videoPath': exercise.videoPath,
        'createdAt': exercise.createdAt.toIso8601String(),
      },
      'exercise_$exerciseId.json',
    );
  }

  Future<void> _syncLessonToDrive(String lessonId) async {
    final lesson = await _database.getLessonById(lessonId);
    if (lesson == null) return;

    final items = await _database.getLessonItems(lessonId);
    
    await _driveService.uploadMetadata(
      {
        'id': lesson.id,
        'name': lesson.name,
        'createdAt': lesson.createdAt.toIso8601String(),
        'items': items.map((item) => {
          'exerciseId': item.exerciseId,
          'orderIndex': item.orderIndex,
          'sets': item.sets,
          'reps': item.reps,
          'holdSeconds': item.holdSeconds,
        }).toList(),
      },
      'lesson_$lessonId.json',
    );
  }

  Future<void> _syncSessionToDrive(String sessionId) async {
    final session = await _database.getWorkoutSessionById(sessionId);
    if (session == null) return;

    final results = await _database.getExerciseResults(sessionId);
    
    // Upload processed video if exists
    final processedDir = await _fileStorage.processedDirectory;
    final processedVideo = File('${processedDir.path}/${sessionId}_processed.mp4');
    if (await processedVideo.exists()) {
      final sessionsFolderId = await _driveService.getSessionsFolderId();
      await _driveService.uploadFile(
        processedVideo,
        '${sessionId}_processed.mp4',
        parentFolderId: sessionsFolderId,
      );
    }

    await _driveService.uploadMetadata(
      {
        'id': session.id,
        'lessonId': session.lessonId,
        'startedAt': session.startedAt.toIso8601String(),
        'completedAt': session.completedAt?.toIso8601String(),
        'status': session.status,
        'results': results.map((r) => {
          'exerciseId': r.exerciseId,
          'formScore': r.formScore,
          'completedReps': r.completedReps,
          'holdDuration': r.holdDuration,
        }).toList(),
      },
      'session_$sessionId.json',
    );
  }

  Future<Either<Failure, SyncResult>> _syncToServer() async {
    if (!_serverService.isAuthenticated) {
      return const Left(StorageFailure('Chưa đăng nhập server'));
    }

    int syncedCount = 0;
    final errors = <String>[];

    try {
      final pendingItems = await _database.getPendingSyncItems();

      for (final item in pendingItems) {
        try {
          bool success = false;
          
          switch (item.entityType) {
            case 'exercise':
              final exercise = await _database.getExerciseById(item.entityId);
              if (exercise != null) {
                final videoFile = await _fileStorage.getExerciseVideo(item.entityId);
                success = await _serverService.uploadExercise(
                  id: exercise.id,
                  name: exercise.name,
                  type: exercise.mode,
                  videoFile: videoFile ?? File(exercise.videoPath),
                );
              }
              break;
            case 'session':
              final session = await _database.getWorkoutSessionById(item.entityId);
              if (session != null) {
                final results = await _database.getExerciseResults(item.entityId);
                success = await _serverService.uploadWorkoutSession(
                  sessionId: session.id,
                  lessonId: session.lessonId,
                  results: {
                    'status': session.status,
                    'results': results.map((r) => r.toJson()).toList(),
                  },
                );
              }
              break;
          }

          if (success) {
            await _database.deleteSyncItem(item.id);
            syncedCount++;
          } else {
            errors.add('${item.entityType}/${item.entityId}: Upload failed');
          }
        } catch (e) {
          errors.add('${item.entityType}/${item.entityId}: $e');
        }
      }

      final result = SyncResult(
        syncedCount: syncedCount,
        failedCount: errors.length,
        errors: errors,
      );
      _syncStatusController.add(result);
      return Right(result);
    } catch (e) {
      return Left(SyncFailure('Lỗi đồng bộ server: $e'));
    }
  }

  @override
  Future<Either<Failure, void>> syncFromCloud() async {
    final mode = await getCurrentStorageMode();
    
    if (mode == StorageMode.local) {
      return const Right(null);
    }

    try {
      if (mode == StorageMode.googleDrive) {
        return await _downloadFromDrive();
      } else if (mode == StorageMode.server) {
        return await _downloadFromServer();
      }
      return const Right(null);
    } catch (e) {
      return Left(SyncFailure('Lỗi tải dữ liệu: $e'));
    }
  }

  Future<Either<Failure, void>> _downloadFromDrive() async {
    if (!_driveService.isReady) {
      return const Left(StorageFailure('Google Drive chưa sẵn sàng'));
    }

    try {
      // Download all metadata files and recreate local data
      final files = await _driveService.listAllFiles();
      
      for (final file in files) {
        if (file.name?.startsWith('exercise_') == true) {
          final metadata = await _driveService.downloadMetadata(file.name!);
          if (metadata != null) {
            // Insert/update exercise in local DB
            // Implementation depends on your database schema
          }
        } else if (file.name?.startsWith('lesson_') == true) {
          final metadata = await _driveService.downloadMetadata(file.name!);
          if (metadata != null) {
            // Insert/update lesson in local DB
          }
        }
      }

      return const Right(null);
    } catch (e) {
      return Left(SyncFailure('Lỗi tải từ Drive: $e'));
    }
  }

  Future<Either<Failure, void>> _downloadFromServer() async {
    if (!_serverService.isAuthenticated) {
      return const Left(StorageFailure('Chưa đăng nhập server'));
    }

    try {
      // Download exercises
      final exercises = await _serverService.listExercises();
      for (final exerciseData in exercises) {
        // TODO: Insert/update exercise in local DB
        // Placeholder - will implement when server API is ready
        debugPrint('Server exercise: ${exerciseData['id']}');
      }

      // Download workout history
      final sessions = await _serverService.getWorkoutHistory();
      for (final sessionData in sessions) {
        // TODO: Insert/update session in local DB
        // Placeholder - will implement when server API is ready
        debugPrint('Server session: ${sessionData['id']}');
      }

      return const Right(null);
    } catch (e) {
      return Left(SyncFailure('Lỗi tải từ server: $e'));
    }
  }

  @override
  Future<int> getPendingSyncCount() async {
    return await _database.getPendingSyncCount();
  }

  @override
  Future<Either<Failure, void>> clearLocalData() async {
    try {
      // Clear database
      await _database.clearAllData();
      
      // Clear files
      await _fileStorage.clearAllFiles();
      
      return const Right(null);
    } catch (e) {
      return Left(StorageFailure('Lỗi xóa dữ liệu: $e'));
    }
  }

  @override
  Future<Either<Failure, String>> exportData() async {
    try {
      // Export all data to a JSON file
      final exportDir = await _fileStorage.exportsDirectory;
      final timestamp = DateTime.now().millisecondsSinceEpoch;
      final exportPath = '${exportDir.path}/backup_$timestamp.json';

      // Get all data from database
      final exercises = await _database.getAllExercisesForExport();
      final lessons = await _database.getAllLessonsForExport();
      final sessions = await _database.getAllWorkoutSessions();

      final exportData = {
        'version': 1,
        'exportedAt': DateTime.now().toIso8601String(),
        'exercises': exercises.map((e) => {
          'id': e.id,
          'name': e.name,
          'mode': e.mode,
          'videoPath': e.videoPath,
          'thumbnailPath': e.thumbnailPath,
          'createdAt': e.createdAt.toIso8601String(),
        }).toList(),
        'lessons': lessons.map((l) => {
          'id': l.id,
          'name': l.name,
          'createdAt': l.createdAt.toIso8601String(),
        }).toList(),
        'sessions': sessions.map((s) => {
          'id': s.id,
          'lessonId': s.lessonId,
          'startedAt': s.startedAt.toIso8601String(),
          'completedAt': s.completedAt?.toIso8601String(),
        }).toList(),
      };

      final file = File(exportPath);
      await file.writeAsString(jsonEncode(exportData));

      return Right(exportPath);
    } catch (e) {
      return Left(StorageFailure('Lỗi xuất dữ liệu: $e'));
    }
  }

  @override
  Future<Either<Failure, void>> importData(String filePath) async {
    try {
      final file = File(filePath);
      if (!await file.exists()) {
        return const Left(StorageFailure('File không tồn tại'));
      }

      final jsonString = await file.readAsString();
      final data = jsonDecode(jsonString) as Map<String, dynamic>;

      // Validate version
      final version = data['version'] as int?;
      if (version == null || version > 1) {
        return const Left(StorageFailure('Phiên bản backup không tương thích'));
      }

      // Import exercises
      final exercises = data['exercises'] as List?;
      if (exercises != null) {
        for (final exerciseData in exercises) {
          // TODO: Insert exercise into database
          debugPrint('Importing exercise: ${exerciseData['id']}');
        }
      }

      // Import lessons
      final lessons = data['lessons'] as List?;
      if (lessons != null) {
        for (final lessonData in lessons) {
          // TODO: Insert lesson into database
          debugPrint('Importing lesson: ${lessonData['id']}');
        }
      }

      return const Right(null);
    } catch (e) {
      return Left(StorageFailure('Lỗi nhập dữ liệu: $e'));
    }
  }

  @override
  Stream<SyncResult> get syncStatus => _syncStatusController.stream;

  /// Migrate data when changing storage mode
  Future<void> _migrateData({
    required StorageMode fromMode,
    required StorageMode toMode,
  }) async {
    // If moving to cloud, upload all local data
    if (fromMode == StorageMode.local && 
        (toMode == StorageMode.googleDrive || toMode == StorageMode.server)) {
      // Queue all existing data for sync
      final exercises = await _database.getAllExercisesForExport();
      for (final exercise in exercises) {
        await _database.addSyncQueueItem(
          entityType: 'exercise',
          entityId: exercise.id,
          operation: db.SyncOperation.create,
        );
      }

      final lessons = await _database.getAllLessonsForExport();
      for (final lesson in lessons) {
        await _database.addSyncQueueItem(
          entityType: 'lesson',
          entityId: lesson.id,
          operation: db.SyncOperation.create,
        );
      }

      // Trigger sync
      await syncToCloud();
    }

    // If moving from cloud to local, download all data
    if ((fromMode == StorageMode.googleDrive || fromMode == StorageMode.server) &&
        toMode == StorageMode.local) {
      await syncFromCloud();
    }
  }

  void dispose() {
    _syncStatusController.close();
  }
}

/// Extension to add toJson to exercise results
extension ExerciseResultJson on db.ExerciseResult {
  Map<String, dynamic> toJson() => {
        'exerciseId': exerciseId,
        'formScore': formScore,
        'completedReps': completedReps,
        'holdDuration': holdDuration,
      };
}
