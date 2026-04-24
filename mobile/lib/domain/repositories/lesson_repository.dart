import 'package:dartz/dartz.dart';

import '../../core/errors/failures.dart';
import '../entities/lesson.dart';

/// Repository interface for lesson (giáo án) operations
abstract class LessonRepository {
  /// Get all lessons
  Future<Either<Failure, List<Lesson>>> getLessons();

  /// Get a single lesson by ID
  Future<Either<Failure, Lesson>> getLessonById(String id);

  /// Create a new lesson
  Future<Either<Failure, Lesson>> createLesson(Lesson lesson);

  /// Update an existing lesson
  Future<Either<Failure, Lesson>> updateLesson(Lesson lesson);

  /// Delete a lesson
  Future<Either<Failure, void>> deleteLesson(String id);

  /// Add exercise to a lesson
  Future<Either<Failure, Lesson>> addExerciseToLesson({
    required String lessonId,
    required LessonItem item,
  });

  /// Remove exercise from a lesson
  Future<Either<Failure, Lesson>> removeExerciseFromLesson({
    required String lessonId,
    required String itemId,
  });

  /// Reorder exercises in a lesson
  Future<Either<Failure, Lesson>> reorderExercises({
    required String lessonId,
    required List<String> itemIds,
  });

  /// Stream of lessons for reactive UI
  Stream<List<Lesson>> watchLessons();
}
