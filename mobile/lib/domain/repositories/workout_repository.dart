import 'package:dartz/dartz.dart';

import '../../core/errors/failures.dart';
import '../entities/workout_session.dart';

/// Repository interface for workout session operations
abstract class WorkoutRepository {
  /// Start a new workout session
  Future<Either<Failure, WorkoutSession>> startSession({
    required String lessonId,
    required String lessonName,
  });

  /// Get current active session (if any)
  Future<Either<Failure, WorkoutSession?>> getCurrentSession();

  /// Add exercise result to session
  Future<Either<Failure, WorkoutSession>> addExerciseResult({
    required String sessionId,
    required ExerciseResult result,
  });

  /// Complete the session
  Future<Either<Failure, WorkoutSession>> completeSession(String sessionId);

  /// Cancel the session
  Future<Either<Failure, void>> cancelSession(String sessionId);

  /// Get all workout sessions (history)
  Future<Either<Failure, List<WorkoutSession>>> getSessionHistory();

  /// Get sessions for a specific date range
  Future<Either<Failure, List<WorkoutSession>>> getSessionsByDateRange({
    required DateTime startDate,
    required DateTime endDate,
  });

  /// Get a single session by ID
  Future<Either<Failure, WorkoutSession>> getSessionById(String id);

  /// Delete a session
  Future<Either<Failure, void>> deleteSession(String id);

  /// Stream of sessions for reactive UI
  Stream<List<WorkoutSession>> watchSessions();
}
