import 'package:equatable/equatable.dart';

/// Status of a workout session
enum SessionStatus {
  inProgress,
  completed,
  cancelled,
}

/// Result of a single exercise within a session
class ExerciseResult extends Equatable {
  final String id;
  final String exerciseId;
  final String exerciseName;
  final int completedSets;
  final int targetSets;
  final int completedReps;
  final int targetReps;
  final double? holdDuration;      // Actual hold time (for hold mode)
  final double? targetHoldSeconds; // Target hold time
  final double formScore;          // 0-100 form quality score
  final String? processedVideoPath;
  final DateTime completedAt;

  const ExerciseResult({
    required this.id,
    required this.exerciseId,
    required this.exerciseName,
    required this.completedSets,
    required this.targetSets,
    required this.completedReps,
    required this.targetReps,
    this.holdDuration,
    this.targetHoldSeconds,
    required this.formScore,
    this.processedVideoPath,
    required this.completedAt,
  });

  ExerciseResult copyWith({
    String? id,
    String? exerciseId,
    String? exerciseName,
    int? completedSets,
    int? targetSets,
    int? completedReps,
    int? targetReps,
    double? holdDuration,
    double? targetHoldSeconds,
    double? formScore,
    String? processedVideoPath,
    DateTime? completedAt,
  }) {
    return ExerciseResult(
      id: id ?? this.id,
      exerciseId: exerciseId ?? this.exerciseId,
      exerciseName: exerciseName ?? this.exerciseName,
      completedSets: completedSets ?? this.completedSets,
      targetSets: targetSets ?? this.targetSets,
      completedReps: completedReps ?? this.completedReps,
      targetReps: targetReps ?? this.targetReps,
      holdDuration: holdDuration ?? this.holdDuration,
      targetHoldSeconds: targetHoldSeconds ?? this.targetHoldSeconds,
      formScore: formScore ?? this.formScore,
      processedVideoPath: processedVideoPath ?? this.processedVideoPath,
      completedAt: completedAt ?? this.completedAt,
    );
  }

  /// Whether the exercise target was achieved
  bool get isCompleted {
    if (holdDuration != null && targetHoldSeconds != null) {
      return holdDuration! >= targetHoldSeconds!;
    }
    return completedReps >= targetReps && completedSets >= targetSets;
  }

  /// Completion percentage (0-100)
  double get completionPercentage {
    if (targetReps > 0) {
      return (completedReps / targetReps * 100).clamp(0, 100);
    }
    if (targetHoldSeconds != null && targetHoldSeconds! > 0) {
      return ((holdDuration ?? 0) / targetHoldSeconds! * 100).clamp(0, 100);
    }
    return 0;
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'exercise_id': exerciseId,
        'exercise_name': exerciseName,
        'completed_sets': completedSets,
        'target_sets': targetSets,
        'completed_reps': completedReps,
        'target_reps': targetReps,
        'hold_duration': holdDuration,
        'target_hold_seconds': targetHoldSeconds,
        'form_score': formScore,
        'processed_video_path': processedVideoPath,
        'completed_at': completedAt.toIso8601String(),
      };

  factory ExerciseResult.fromJson(Map<String, dynamic> json) {
    return ExerciseResult(
      id: json['id'] as String,
      exerciseId: json['exercise_id'] as String,
      exerciseName: json['exercise_name'] as String,
      completedSets: (json['completed_sets'] as num?)?.toInt() ?? 0,
      targetSets: (json['target_sets'] as num?)?.toInt() ?? 1,
      completedReps: (json['completed_reps'] as num?)?.toInt() ?? 0,
      targetReps: (json['target_reps'] as num?)?.toInt() ?? 10,
      holdDuration: (json['hold_duration'] as num?)?.toDouble(),
      targetHoldSeconds: (json['target_hold_seconds'] as num?)?.toDouble(),
      formScore: (json['form_score'] as num?)?.toDouble() ?? 0,
      processedVideoPath: json['processed_video_path'] as String?,
      completedAt: DateTime.parse(json['completed_at'] as String),
    );
  }

  @override
  List<Object?> get props => [
        id,
        exerciseId,
        exerciseName,
        completedSets,
        targetSets,
        completedReps,
        targetReps,
        holdDuration,
        targetHoldSeconds,
        formScore,
        processedVideoPath,
        completedAt,
      ];
}

/// Workout session entity - a complete workout execution record
class WorkoutSession extends Equatable {
  final String id;
  final String lessonId;
  final String lessonName;
  final SessionStatus status;
  final List<ExerciseResult> results;
  final DateTime startedAt;
  final DateTime? completedAt;
  final bool isSynced;
  final int syncVersion;

  const WorkoutSession({
    required this.id,
    required this.lessonId,
    required this.lessonName,
    required this.status,
    this.results = const [],
    required this.startedAt,
    this.completedAt,
    this.isSynced = false,
    this.syncVersion = 0,
  });

  WorkoutSession copyWith({
    String? id,
    String? lessonId,
    String? lessonName,
    SessionStatus? status,
    List<ExerciseResult>? results,
    DateTime? startedAt,
    DateTime? completedAt,
    bool? isSynced,
    int? syncVersion,
  }) {
    return WorkoutSession(
      id: id ?? this.id,
      lessonId: lessonId ?? this.lessonId,
      lessonName: lessonName ?? this.lessonName,
      status: status ?? this.status,
      results: results ?? this.results,
      startedAt: startedAt ?? this.startedAt,
      completedAt: completedAt ?? this.completedAt,
      isSynced: isSynced ?? this.isSynced,
      syncVersion: syncVersion ?? this.syncVersion,
    );
  }

  /// Total workout duration in minutes
  int get durationMinutes {
    final end = completedAt ?? DateTime.now();
    return end.difference(startedAt).inMinutes;
  }

  /// Average form score across all exercises
  double get averageFormScore {
    if (results.isEmpty) return 0;
    final total = results.fold<double>(0, (sum, r) => sum + r.formScore);
    return total / results.length;
  }

  /// Total exercises completed
  int get completedExercises => results.where((r) => r.isCompleted).length;

  /// Total exercises in session
  int get totalExercises => results.length;

  /// Overall completion percentage
  double get completionPercentage {
    if (results.isEmpty) return 0;
    return (completedExercises / totalExercises * 100);
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'lesson_id': lessonId,
        'lesson_name': lessonName,
        'status': status.name,
        'results': results.map((e) => e.toJson()).toList(),
        'started_at': startedAt.toIso8601String(),
        'completed_at': completedAt?.toIso8601String(),
        'is_synced': isSynced,
        'sync_version': syncVersion,
      };

  factory WorkoutSession.fromJson(Map<String, dynamic> json) {
    return WorkoutSession(
      id: json['id'] as String,
      lessonId: json['lesson_id'] as String,
      lessonName: json['lesson_name'] as String,
      status: SessionStatus.values.firstWhere(
        (s) => s.name == json['status'],
        orElse: () => SessionStatus.inProgress,
      ),
      results: (json['results'] as List<dynamic>?)
              ?.map((e) => ExerciseResult.fromJson(e as Map<String, dynamic>))
              .toList() ??
          [],
      startedAt: DateTime.parse(json['started_at'] as String),
      completedAt: json['completed_at'] != null
          ? DateTime.parse(json['completed_at'] as String)
          : null,
      isSynced: json['is_synced'] as bool? ?? false,
      syncVersion: (json['sync_version'] as num?)?.toInt() ?? 0,
    );
  }

  @override
  List<Object?> get props => [
        id,
        lessonId,
        lessonName,
        status,
        results,
        startedAt,
        completedAt,
        isSynced,
        syncVersion,
      ];

  @override
  String toString() =>
      'WorkoutSession($lessonName, ${status.name}, ${results.length} exercises)';
}
