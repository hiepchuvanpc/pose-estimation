import 'package:dartz/dartz.dart';

import '../../core/errors/failures.dart';
import '../entities/exercise.dart';

/// Repository interface for exercise operations
abstract class ExerciseRepository {
  /// Get all exercises (from local DB + optionally server)
  Future<Either<Failure, List<Exercise>>> getExercises();

  /// Get a single exercise by ID
  Future<Either<Failure, Exercise>> getExerciseById(String id);

  /// Create a new exercise
  Future<Either<Failure, Exercise>> createExercise(Exercise exercise);

  /// Update an existing exercise
  Future<Either<Failure, Exercise>> updateExercise(Exercise exercise);

  /// Delete an exercise
  Future<Either<Failure, void>> deleteExercise(String id);

  /// Delete multiple exercises
  Future<Either<Failure, void>> deleteExercises(List<String> ids);

  /// Get exercise profile (PCA features) - may require server call
  Future<Either<Failure, ExerciseProfile>> getExerciseProfile(String id);

  /// Search exercises by name
  Future<Either<Failure, List<Exercise>>> searchExercises(String query);

  /// Fetch exercises from server (if available)
  Future<Either<Failure, List<Exercise>>> fetchFromServer();

  /// Stream of exercises for reactive UI
  Stream<List<Exercise>> watchExercises();
}
