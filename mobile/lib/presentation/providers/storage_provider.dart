import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_sign_in/google_sign_in.dart';

import '../../data/datasources/local/database.dart';
import '../../data/datasources/local/file_storage_service.dart';
import '../../data/datasources/remote/google_drive_service.dart';
import '../../data/datasources/remote/motion_coach_server_service.dart';
import '../../data/repositories/storage_repository_impl.dart';
import '../../domain/entities/user.dart';
import '../../domain/repositories/storage_repository.dart';

/// Provider for FileStorageService
final fileStorageServiceProvider = Provider<FileStorageService>((ref) {
  final service = FileStorageService();
  // Initialize on first access
  service.init();
  return service;
});

/// Provider for AppDatabase
final databaseProvider = Provider<AppDatabase>((ref) {
  return AppDatabase();
});

/// Provider for GoogleSignIn instance
final googleSignInProvider = Provider<GoogleSignIn>((ref) {
  return GoogleSignIn(
    scopes: [
      'email',
      'profile',
      'https://www.googleapis.com/auth/drive.file',
    ],
  );
});

/// Provider for GoogleDriveService
final googleDriveServiceProvider = Provider<GoogleDriveService>((ref) {
  final googleSignIn = ref.watch(googleSignInProvider);
  return GoogleDriveService(googleSignIn);
});

/// Provider for MotionCoachServerService
final serverServiceProvider = Provider<MotionCoachServerService>((ref) {
  final service = MotionCoachServerService();
  service.init();
  return service;
});

/// Provider for StorageRepository
final storageRepositoryProvider = Provider<StorageRepository>((ref) {
  return StorageRepositoryImpl(
    database: ref.watch(databaseProvider),
    fileStorage: ref.watch(fileStorageServiceProvider),
    driveService: ref.watch(googleDriveServiceProvider),
    serverService: ref.watch(serverServiceProvider),
    googleSignIn: ref.watch(googleSignInProvider),
  );
});

/// Provider for current storage mode
final storageModeProvider = FutureProvider<StorageMode>((ref) async {
  final repository = ref.watch(storageRepositoryProvider);
  return await repository.getCurrentStorageMode();
});

/// Provider for pending sync count
final pendingSyncCountProvider = FutureProvider<int>((ref) async {
  final repository = ref.watch(storageRepositoryProvider);
  return await repository.getPendingSyncCount();
});

/// State notifier for storage operations
class StorageNotifier extends StateNotifier<StorageState> {
  final StorageRepository _repository;

  StorageNotifier(this._repository) : super(const StorageState());

  Future<void> setStorageMode(StorageMode mode) async {
    state = state.copyWith(isChangingMode: true, error: null);
    
    final result = await _repository.setStorageMode(mode);
    
    result.fold(
      (failure) => state = state.copyWith(
        isChangingMode: false,
        error: failure.message,
      ),
      (_) => state = state.copyWith(
        isChangingMode: false,
        currentMode: mode,
      ),
    );
  }

  Future<void> syncToCloud() async {
    state = state.copyWith(isSyncing: true, error: null);
    
    final result = await _repository.syncToCloud();
    
    result.fold(
      (failure) => state = state.copyWith(
        isSyncing: false,
        error: failure.message,
      ),
      (syncResult) => state = state.copyWith(
        isSyncing: false,
        lastSyncResult: syncResult,
      ),
    );
  }

  Future<void> syncFromCloud() async {
    state = state.copyWith(isSyncing: true, error: null);
    
    final result = await _repository.syncFromCloud();
    
    result.fold(
      (failure) => state = state.copyWith(
        isSyncing: false,
        error: failure.message,
      ),
      (_) => state = state.copyWith(isSyncing: false),
    );
  }

  Future<String?> exportData() async {
    state = state.copyWith(isExporting: true, error: null);
    
    final result = await _repository.exportData();
    
    return result.fold(
      (failure) {
        state = state.copyWith(isExporting: false, error: failure.message);
        return null;
      },
      (path) {
        state = state.copyWith(isExporting: false);
        return path;
      },
    );
  }

  Future<bool> importData(String filePath) async {
    state = state.copyWith(isImporting: true, error: null);
    
    final result = await _repository.importData(filePath);
    
    return result.fold(
      (failure) {
        state = state.copyWith(isImporting: false, error: failure.message);
        return false;
      },
      (_) {
        state = state.copyWith(isImporting: false);
        return true;
      },
    );
  }

  Future<void> clearLocalData() async {
    final result = await _repository.clearLocalData();
    result.fold(
      (failure) => state = state.copyWith(error: failure.message),
      (_) {},
    );
  }
}

/// State class for storage operations
class StorageState {
  final StorageMode currentMode;
  final bool isSyncing;
  final bool isChangingMode;
  final bool isExporting;
  final bool isImporting;
  final SyncResult? lastSyncResult;
  final String? error;

  const StorageState({
    this.currentMode = StorageMode.local,
    this.isSyncing = false,
    this.isChangingMode = false,
    this.isExporting = false,
    this.isImporting = false,
    this.lastSyncResult,
    this.error,
  });

  StorageState copyWith({
    StorageMode? currentMode,
    bool? isSyncing,
    bool? isChangingMode,
    bool? isExporting,
    bool? isImporting,
    SyncResult? lastSyncResult,
    String? error,
  }) {
    return StorageState(
      currentMode: currentMode ?? this.currentMode,
      isSyncing: isSyncing ?? this.isSyncing,
      isChangingMode: isChangingMode ?? this.isChangingMode,
      isExporting: isExporting ?? this.isExporting,
      isImporting: isImporting ?? this.isImporting,
      lastSyncResult: lastSyncResult ?? this.lastSyncResult,
      error: error,
    );
  }
}

/// Provider for StorageNotifier
final storageNotifierProvider =
    StateNotifierProvider<StorageNotifier, StorageState>((ref) {
  return StorageNotifier(ref.watch(storageRepositoryProvider));
});

/// Stream provider for sync status updates
final syncStatusStreamProvider = StreamProvider<SyncResult>((ref) {
  final repository = ref.watch(storageRepositoryProvider);
  return repository.syncStatus;
});
