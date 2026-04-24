/// Workout session response from backend.
class WorkoutProgress {
  final String sessionId;
  final String phase;
  final String? exerciseName;
  final String? mode;
  final int stepIndex;
  final int setIndex;
  final int repCount;
  final double holdSeconds;
  final int? targetReps;
  final double? targetSeconds;
  final bool trackingStarted;
  final bool pendingConfirmation;
  final bool done;
  final List<String> announcements;

  const WorkoutProgress({
    required this.sessionId,
    required this.phase,
    this.exerciseName,
    this.mode,
    required this.stepIndex,
    required this.setIndex,
    required this.repCount,
    required this.holdSeconds,
    this.targetReps,
    this.targetSeconds,
    required this.trackingStarted,
    required this.pendingConfirmation,
    required this.done,
    required this.announcements,
  });

  factory WorkoutProgress.fromJson(Map<String, dynamic> json) =>
      WorkoutProgress(
        sessionId: json['session_id'] as String,
        phase: json['phase'] as String,
        exerciseName: json['exercise_name'] as String?,
        mode: json['mode'] as String?,
        stepIndex: (json['step_index'] as num).toInt(),
        setIndex: (json['set_index'] as num).toInt(),
        repCount: (json['rep_count'] as num).toInt(),
        holdSeconds: (json['hold_seconds'] as num).toDouble(),
        targetReps: (json['target_reps'] as num?)?.toInt(),
        targetSeconds: (json['target_seconds'] as num?)?.toDouble(),
        trackingStarted: json['tracking_started'] as bool,
        pendingConfirmation: json['pending_confirmation'] as bool,
        done: json['done'] as bool,
        announcements: (json['announcements'] as List<dynamic>)
            .map((e) => e as String)
            .toList(),
      );
}

/// Workout step config (sent to start a session).
class WorkoutStepConfig {
  final String templateId;
  final int sets;
  final int? repsPerSet;
  final double? holdSecondsPerSet;
  final int restSecondsBetweenSets;

  const WorkoutStepConfig({
    required this.templateId,
    this.sets = 1,
    this.repsPerSet,
    this.holdSecondsPerSet,
    this.restSecondsBetweenSets = 0,
  });

  Map<String, dynamic> toJson() => {
        'template_id': templateId,
        'sets': sets,
        'reps_per_set': repsPerSet,
        'hold_seconds_per_set': holdSecondsPerSet,
        'rest_seconds_between_sets': restSecondsBetweenSets,
      };
}
