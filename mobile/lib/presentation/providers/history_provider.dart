import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/di/injection.dart';
import '../../data/datasources/local/database.dart' as db;

// ============ HISTORY LIST STATE ============

/// Model cho một phiên tập với thông tin tổng hợp
class WorkoutHistoryItem {
  final db.WorkoutSession session;
  final List<db.ExerciseResult> results;

  WorkoutHistoryItem({
    required this.session,
    required this.results,
  });

  /// Tính điểm trung bình của phiên tập
  double get averageScore {
    if (results.isEmpty) return 0;
    return results.map((r) => r.formScore).reduce((a, b) => a + b) / results.length;
  }

  /// Tính thời gian tập (giây)
  int get durationSeconds {
    if (session.completedAt == null) return 0;
    return session.completedAt!.difference(session.startedAt).inSeconds;
  }

  /// Số bài tập đã hoàn thành
  int get completedExerciseCount => results.length;
}

/// State cho danh sách lịch sử
class HistoryListState {
  final List<WorkoutHistoryItem> sessions;
  final bool isLoading;
  final String? error;

  const HistoryListState({
    this.sessions = const [],
    this.isLoading = false,
    this.error,
  });

  HistoryListState copyWith({
    List<WorkoutHistoryItem>? sessions,
    bool? isLoading,
    String? error,
  }) {
    return HistoryListState(
      sessions: sessions ?? this.sessions,
      isLoading: isLoading ?? this.isLoading,
      error: error,
    );
  }
}

/// Notifier để quản lý danh sách lịch sử
class HistoryListNotifier extends StateNotifier<HistoryListState> {
  final db.AppDatabase _database;

  HistoryListNotifier(this._database) : super(const HistoryListState()) {
    loadHistory();
  }

  Future<void> loadHistory() async {
    state = state.copyWith(isLoading: true, error: null);

    try {
      // Get all sessions (completed only)
      final allSessions = await _database.getAllSessions('local_user');
      final completedSessions = allSessions
          .where((s) => s.status == 'completed')
          .toList();

      final items = <WorkoutHistoryItem>[];
      for (final session in completedSessions) {
        final results = await _database.getSessionResults(session.id);
        items.add(WorkoutHistoryItem(session: session, results: results));
      }

      // Sort by date descending
      items.sort((a, b) => b.session.startedAt.compareTo(a.session.startedAt));

      state = state.copyWith(
        sessions: items,
        isLoading: false,
      );
    } catch (e) {
      debugPrint('Error loading history: $e');
      state = state.copyWith(
        isLoading: false,
        error: 'Không thể tải lịch sử tập luyện',
      );
    }
  }

  Future<void> deleteSession(String sessionId) async {
    try {
      await _database.deleteSession(sessionId);
      await loadHistory();
    } catch (e) {
      debugPrint('Error deleting session: $e');
      state = state.copyWith(error: 'Không thể xóa phiên tập');
    }
  }
}

/// Provider cho history list
final historyListProvider =
    StateNotifierProvider<HistoryListNotifier, HistoryListState>((ref) {
  final database = getIt<db.AppDatabase>();
  return HistoryListNotifier(database);
});

// ============ HISTORY DETAIL STATE ============

/// State cho chi tiết một phiên tập
class HistoryDetailState {
  final db.WorkoutSession? session;
  final List<db.ExerciseResult> results;
  final bool isLoading;
  final String? error;

  const HistoryDetailState({
    this.session,
    this.results = const [],
    this.isLoading = false,
    this.error,
  });

  double get averageScore {
    if (results.isEmpty) return 0;
    return results.map((r) => r.formScore).reduce((a, b) => a + b) / results.length;
  }

  int get durationSeconds {
    if (session == null || session!.completedAt == null) return 0;
    return session!.completedAt!.difference(session!.startedAt).inSeconds;
  }

  HistoryDetailState copyWith({
    db.WorkoutSession? session,
    List<db.ExerciseResult>? results,
    bool? isLoading,
    String? error,
  }) {
    return HistoryDetailState(
      session: session ?? this.session,
      results: results ?? this.results,
      isLoading: isLoading ?? this.isLoading,
      error: error,
    );
  }
}

/// Notifier để quản lý chi tiết phiên tập
class HistoryDetailNotifier extends StateNotifier<HistoryDetailState> {
  final db.AppDatabase _database;
  final String sessionId;

  HistoryDetailNotifier(this._database, this.sessionId)
      : super(const HistoryDetailState()) {
    loadDetail();
  }

  Future<void> loadDetail() async {
    state = state.copyWith(isLoading: true, error: null);

    try {
      final session = await _database.getSessionById(sessionId);
      if (session == null) {
        state = state.copyWith(
          isLoading: false,
          error: 'Không tìm thấy phiên tập',
        );
        return;
      }

      final results = await _database.getSessionResults(sessionId);

      state = state.copyWith(
        session: session,
        results: results,
        isLoading: false,
      );
    } catch (e) {
      debugPrint('Error loading history detail: $e');
      state = state.copyWith(
        isLoading: false,
        error: 'Không thể tải chi tiết phiên tập',
      );
    }
  }
}

/// Provider cho history detail (family provider với sessionId)
final historyDetailProvider = StateNotifierProvider.family<
    HistoryDetailNotifier, HistoryDetailState, String>((ref, sessionId) {
  final database = getIt<db.AppDatabase>();
  return HistoryDetailNotifier(database, sessionId);
});
