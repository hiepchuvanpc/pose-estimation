/// Exercise specification.
class ExerciseSpec {
  final String name;
  final String mode; // 'reps' or 'hold'
  final int? targetReps;
  final double? targetSeconds;

  const ExerciseSpec({
    required this.name,
    required this.mode,
    this.targetReps,
    this.targetSeconds,
  });
}

/// Live exercise progress.
class ExerciseProgress {
  final String name;
  final String mode;
  final int repCount;
  final double holdSeconds;
  final bool completed;

  const ExerciseProgress({
    required this.name,
    required this.mode,
    required this.repCount,
    required this.holdSeconds,
    required this.completed,
  });
}
