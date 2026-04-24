import 'package:drift/drift.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../../app/di/injection.dart';
import '../../data/datasources/local/database.dart' as db;

// ============ WORKOUT SESSION STATE ============

/// Enum for workout status
enum WorkoutStatus {
  preparing,    // Chuẩn bị (countdown 3-2-1)
  exercising,   // Đang tập
  resting,      // Nghỉ giữa set/bài
  completed,    // Hoàn thành
  cancelled,    // Đã hủy
}

/// Model cho một item tập trong workout
class WorkoutExerciseItem {
  final db.LessonItem lessonItem;
  final db.Exercise exercise;
  int currentSet;
  int currentRep;
  double? holdDuration;
  double formScore;
  bool isCompleted;

  WorkoutExerciseItem({
    required this.lessonItem,
    required this.exercise,
    this.currentSet = 0,
    this.currentRep = 0,
    this.holdDuration,
    this.formScore = 0.0,
    this.isCompleted = false,
  });

  bool get isReps => exercise.mode == 'reps';
  int get targetSets => lessonItem.sets;
  int get targetReps => lessonItem.reps;
  int get targetHoldSeconds => lessonItem.holdSeconds;
  int get restSeconds => lessonItem.restSeconds;
}

/// State cho workout session
class WorkoutSessionState {
  final db.Lesson? lesson;
  final List<WorkoutExerciseItem> exercises;
  final int currentExerciseIndex;
  final WorkoutStatus status;
  final int countdownSeconds;
  final int restCountdownSeconds;
  final String? sessionId;
  final DateTime? startedAt;
  final bool isLoading;
  final String? error;

  const WorkoutSessionState({
    this.lesson,
    this.exercises = const [],
    this.currentExerciseIndex = 0,
    this.status = WorkoutStatus.preparing,
    this.countdownSeconds = 3,
    this.restCountdownSeconds = 0,
    this.sessionId,
    this.startedAt,
    this.isLoading = false,
    this.error,
  });

  WorkoutExerciseItem? get currentExercise =>
      currentExerciseIndex < exercises.length
          ? exercises[currentExerciseIndex]
          : null;

  bool get isLastExercise => currentExerciseIndex >= exercises.length - 1;
  
  double get overallProgress {
    if (exercises.isEmpty) return 0;
    int completed = exercises.where((e) => e.isCompleted).length;
    return completed / exercises.length;
  }

  WorkoutSessionState copyWith({
    db.Lesson? lesson,
    List<WorkoutExerciseItem>? exercises,
    int? currentExerciseIndex,
    WorkoutStatus? status,
    int? countdownSeconds,
    int? restCountdownSeconds,
    String? sessionId,
    DateTime? startedAt,
    bool? isLoading,
    String? error,
  }) {
    return WorkoutSessionState(
      lesson: lesson ?? this.lesson,
      exercises: exercises ?? this.exercises,
      currentExerciseIndex: currentExerciseIndex ?? this.currentExerciseIndex,
      status: status ?? this.status,
      countdownSeconds: countdownSeconds ?? this.countdownSeconds,
      restCountdownSeconds: restCountdownSeconds ?? this.restCountdownSeconds,
      sessionId: sessionId ?? this.sessionId,
      startedAt: startedAt ?? this.startedAt,
      isLoading: isLoading ?? this.isLoading,
      error: error,
    );
  }
}

/// Notifier để quản lý workout session
class WorkoutSessionNotifier extends StateNotifier<WorkoutSessionState> {
  final db.AppDatabase _database;
  static const _uuid = Uuid();

  WorkoutSessionNotifier(this._database) : super(const WorkoutSessionState());

  /// Bắt đầu workout với giáo án đã chọn
  Future<void> startWorkout(String lessonId) async {
    state = state.copyWith(isLoading: true, error: null);

    try {
      final lesson = await _database.getLessonById(lessonId);
      if (lesson == null) {
        state = state.copyWith(
          isLoading: false,
          error: 'Không tìm thấy giáo án',
        );
        return;
      }

      final lessonItems = await _database.getLessonItems(lessonId);
      if (lessonItems.isEmpty) {
        state = state.copyWith(
          isLoading: false,
          error: 'Giáo án không có bài tập nào',
        );
        return;
      }

      final exercises = <WorkoutExerciseItem>[];
      for (final item in lessonItems) {
        final exercise = await _database.getExerciseById(item.exerciseId);
        if (exercise != null) {
          exercises.add(WorkoutExerciseItem(
            lessonItem: item,
            exercise: exercise,
          ));
        }
      }

      if (exercises.isEmpty) {
        state = state.copyWith(
          isLoading: false,
          error: 'Không tìm thấy bài tập trong giáo án',
        );
        return;
      }

      // Create workout session in database
      final sessionId = _uuid.v4();
      final now = DateTime.now();
      
      await _database.insertSession(
        db.WorkoutSessionsCompanion.insert(
          id: sessionId,
          userId: 'local_user', // TODO: Get actual user ID
          lessonId: lessonId,
          lessonName: lesson.name,
          startedAt: now,
        ),
      );

      state = state.copyWith(
        lesson: lesson,
        exercises: exercises,
        currentExerciseIndex: 0,
        status: WorkoutStatus.preparing,
        countdownSeconds: 3,
        sessionId: sessionId,
        startedAt: now,
        isLoading: false,
      );
    } catch (e) {
      debugPrint('Error starting workout: $e');
      state = state.copyWith(
        isLoading: false,
        error: 'Không thể bắt đầu tập luyện',
      );
    }
  }

  /// Giảm countdown
  void decrementCountdown() {
    if (state.countdownSeconds > 1) {
      state = state.copyWith(countdownSeconds: state.countdownSeconds - 1);
    } else {
      // Countdown xong, bắt đầu tập
      state = state.copyWith(
        status: WorkoutStatus.exercising,
        countdownSeconds: 0,
      );
    }
  }

  /// Ghi nhận một rep đã hoàn thành
  void recordRep({double formScore = 100.0}) {
    final currentEx = state.currentExercise;
    if (currentEx == null || !currentEx.isReps) return;

    final exercises = List<WorkoutExerciseItem>.from(state.exercises);
    final item = exercises[state.currentExerciseIndex];
    
    item.currentRep++;
    item.formScore = (item.formScore * (item.currentRep - 1) + formScore) / item.currentRep;

    // Kiểm tra đã xong set chưa
    if (item.currentRep >= item.targetReps) {
      item.currentSet++;
      item.currentRep = 0;

      // Kiểm tra đã xong tất cả sets chưa
      if (item.currentSet >= item.targetSets) {
        item.isCompleted = true;
        _handleExerciseComplete();
        return;
      } else {
        // Nghỉ giữa sets
        state = state.copyWith(
          exercises: exercises,
          status: WorkoutStatus.resting,
          restCountdownSeconds: item.restSeconds,
        );
        return;
      }
    }

    state = state.copyWith(exercises: exercises);
  }

  /// Ghi nhận hold xong
  void recordHoldComplete({double formScore = 100.0}) {
    final currentEx = state.currentExercise;
    if (currentEx == null || currentEx.isReps) return;

    final exercises = List<WorkoutExerciseItem>.from(state.exercises);
    final item = exercises[state.currentExerciseIndex];
    
    item.currentSet++;
    item.holdDuration = item.targetHoldSeconds.toDouble();
    item.formScore = (item.formScore * (item.currentSet - 1) + formScore) / item.currentSet;

    // Kiểm tra đã xong tất cả sets chưa
    if (item.currentSet >= item.targetSets) {
      item.isCompleted = true;
      _handleExerciseComplete();
      return;
    } else {
      // Nghỉ giữa sets
      state = state.copyWith(
        exercises: exercises,
        status: WorkoutStatus.resting,
        restCountdownSeconds: item.restSeconds,
      );
    }
  }

  /// Giảm rest countdown
  void decrementRestCountdown() {
    if (state.restCountdownSeconds > 1) {
      state = state.copyWith(
        restCountdownSeconds: state.restCountdownSeconds - 1,
      );
    } else {
      // Rest xong, tiếp tục tập
      state = state.copyWith(
        status: WorkoutStatus.preparing,
        countdownSeconds: 3,
        restCountdownSeconds: 0,
      );
    }
  }

  /// Skip rest và tiếp tục ngay
  void skipRest() {
    state = state.copyWith(
      status: WorkoutStatus.preparing,
      countdownSeconds: 3,
      restCountdownSeconds: 0,
    );
  }

  /// Xử lý khi hoàn thành một bài tập
  void _handleExerciseComplete() {
    if (state.isLastExercise) {
      // Hoàn thành toàn bộ workout
      _completeWorkout();
    } else {
      // Chuyển sang bài tiếp theo
      state = state.copyWith(
        currentExerciseIndex: state.currentExerciseIndex + 1,
        status: WorkoutStatus.resting,
        restCountdownSeconds: state.currentExercise?.restSeconds ?? 60,
      );
    }
  }

  /// Hoàn thành workout
  Future<void> _completeWorkout() async {
    try {
      if (state.sessionId != null) {
        await _database.updateSession(
          db.WorkoutSessionsCompanion(
            id: Value(state.sessionId!),
            status: const Value('completed'),
            completedAt: Value(DateTime.now()),
          ),
        );

        // Save exercise results
        for (final item in state.exercises) {
          await _database.insertExerciseResult(
            db.ExerciseResultsCompanion.insert(
              id: _uuid.v4(),
              sessionId: state.sessionId!,
              exerciseId: item.exercise.id,
              exerciseName: item.exercise.name,
              completedSets: Value(item.currentSet),
              targetSets: Value(item.targetSets),
              completedReps: Value(item.isReps ? item.currentRep : 0),
              targetReps: Value(item.targetReps),
              holdDuration: Value(item.holdDuration),
              targetHoldSeconds: Value(item.isReps ? null : item.targetHoldSeconds.toDouble()),
              formScore: Value(item.formScore),
              completedAt: DateTime.now(),
            ),
          );
        }
      }
    } catch (e) {
      debugPrint('Error completing workout: $e');
    }

    state = state.copyWith(status: WorkoutStatus.completed);
  }

  /// Hủy workout
  Future<void> cancelWorkout() async {
    try {
      if (state.sessionId != null) {
        await _database.updateSession(
          db.WorkoutSessionsCompanion(
            id: Value(state.sessionId!),
            status: const Value('cancelled'),
            completedAt: Value(DateTime.now()),
          ),
        );
      }
    } catch (e) {
      debugPrint('Error cancelling workout: $e');
    }

    state = state.copyWith(status: WorkoutStatus.cancelled);
  }

  /// Reset state
  void reset() {
    state = const WorkoutSessionState();
  }
}

/// Provider cho workout session
final workoutSessionProvider =
    StateNotifierProvider<WorkoutSessionNotifier, WorkoutSessionState>((ref) {
  final database = getIt<db.AppDatabase>();
  return WorkoutSessionNotifier(database);
});
