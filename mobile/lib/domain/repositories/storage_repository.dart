import 'package:dartz/dartz.dart';

import '../../core/errors/failures.dart';
import '../entities/user.dart';

/// Sync queue item for offline operations
class SyncQueueItem {
  final String id;
  final String entityType;
  final String entityId;
  final SyncOperation operation;
  final Map<String, dynamic>? data;
  final DateTime createdAt;
  final int retryCount;
  final String? lastError;

  const SyncQueueItem({
    required this.id,
    required this.entityType,
    required this.entityId,
    required this.operation,
    this.data,
    required this.createdAt,
    this.retryCount = 0,
    this.lastError,
  });
}

enum SyncOperation { create, update, delete }

/// Result of a sync operation
class SyncResult {
  final int syncedCount;
  final int failedCount;
  final List<String> errors;
  final bool isOffline;

  const SyncResult({
    this.syncedCount = 0,
    this.failedCount = 0,
    this.errors = const [],
    this.isOffline = false,
  });

  factory SyncResult.offline() => const SyncResult(isOffline: true);
  factory SyncResult.success({required int synced}) =>
      SyncResult(syncedCount: synced);
}

/// Repository interface for storage and sync operations
abstract class StorageRepository {
  /// Get current storage mode
  Future<StorageMode> getCurrentStorageMode();

  /// Set storage mode (triggers migration if needed)
  Future<Either<Failure, void>> setStorageMode(StorageMode mode);

  /// Check if drive permissions are granted
  Future<bool> hasDrivePermissions();

  /// Request drive permissions
  Future<Either<Failure, void>> requestDrivePermissions();

  /// Sync data to cloud (based on current storage mode)
  Future<Either<Failure, SyncResult>> syncToCloud();

  /// Download data from cloud
  Future<Either<Failure, void>> syncFromCloud();

  /// Get pending sync items count
  Future<int> getPendingSyncCount();

  /// Clear all local data
  Future<Either<Failure, void>> clearLocalData();

  /// Export data to file (backup)
  Future<Either<Failure, String>> exportData();

  /// Import data from file
  Future<Either<Failure, void>> importData(String filePath);

  /// Stream of sync status
  Stream<SyncResult> get syncStatus;
}
