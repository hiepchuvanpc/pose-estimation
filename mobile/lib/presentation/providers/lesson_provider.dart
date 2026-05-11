import 'package:drift/drift.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../../app/di/injection.dart';
import '../../data/datasources/local/database.dart' as db;

/// State cho danh sách lessons
class LessonListState {
  final List<db.Lesson> lessons;
  final bool isLoading;
  final String? error;

  const LessonListState({
    this.lessons = const [],
    this.isLoading = false,
    this.error,
  });

  LessonListState copyWith({
    List<db.Lesson>? lessons,
    bool? isLoading,
    String? error,
  }) {
    return LessonListState(
      lessons: lessons ?? this.lessons,
      isLoading: isLoading ?? this.isLoading,
      error: error,
    );
  }
}

/// Notifier để quản lý danh sách lessons
class LessonListNotifier extends StateNotifier<LessonListState> {
  final db.AppDatabase _database;
  static const _uuid = Uuid();

  LessonListNotifier(this._database) : super(const LessonListState()) {
    loadLessons();
  }

  Future<void> loadLessons() async {
    state = state.copyWith(isLoading: true, error: null);

    try {
      // TODO: Get actual userId from auth
      final lessons = await _database.getAllLessonsForExport();
      state = state.copyWith(
        lessons: lessons,
        isLoading: false,
      );
    } catch (e) {
      debugPrint('Error loading lessons: $e');
      state = state.copyWith(
        isLoading: false,
        error: 'Không thể tải danh sách giáo án',
      );
    }
  }

  Future<String?> createLesson(String name, {String? description}) async {
    try {
      final now = DateTime.now();
      final id = _uuid.v4();
      
      await _database.insertLesson(
        db.LessonsCompanion.insert(
          id: id,
          userId: 'local_user', // TODO: Get actual user ID from auth
          name: name,
          description: Value(description),
          createdAt: now,
          updatedAt: now,
        ),
      );
      await loadLessons();
      return id;
    } catch (e) {
      debugPrint('Error creating lesson: $e');
      state = state.copyWith(error: 'Không thể tạo giáo án');
      return null;
    }
  }

  Future<void> updateLesson(String id, {String? name, String? description}) async {
    try {
      await _database.updateLesson(
        db.LessonsCompanion(
          id: Value(id),
          name: name != null ? Value(name) : const Value.absent(),
          description: description != null ? Value(description) : const Value.absent(),
          updatedAt: Value(DateTime.now()),
        ),
      );
      await loadLessons();
    } catch (e) {
      debugPrint('Error updating lesson: $e');
      state = state.copyWith(error: 'Không thể cập nhật giáo án');
    }
  }

  Future<void> deleteLesson(String id) async {
    try {
      await _database.deleteLesson(id);
      await loadLessons();
    } catch (e) {
      debugPrint('Error deleting lesson: $e');
      state = state.copyWith(error: 'Không thể xóa giáo án');
    }
  }
}

/// Provider cho lesson list
final lessonListProvider =
    StateNotifierProvider<LessonListNotifier, LessonListState>((ref) {
  final database = getIt<db.AppDatabase>();
  return LessonListNotifier(database);
});

// ============ LESSON DETAIL STATE ============

/// Model cho một item trong lesson (bài tập với cấu hình)
class LessonExerciseItem {
  final db.LessonItem lessonItem;
  final db.Exercise? exercise;

  const LessonExerciseItem({
    required this.lessonItem,
    this.exercise,
  });
}

/// State cho chi tiết một lesson
class LessonDetailState {
  final db.Lesson? lesson;
  final List<LessonExerciseItem> items;
  final bool isLoading;
  final bool isSaving;
  final String? error;

  const LessonDetailState({
    this.lesson,
    this.items = const [],
    this.isLoading = false,
    this.isSaving = false,
    this.error,
  });

  LessonDetailState copyWith({
    db.Lesson? lesson,
    List<LessonExerciseItem>? items,
    bool? isLoading,
    bool? isSaving,
    String? error,
  }) {
    return LessonDetailState(
      lesson: lesson ?? this.lesson,
      items: items ?? this.items,
      isLoading: isLoading ?? this.isLoading,
      isSaving: isSaving ?? this.isSaving,
      error: error,
    );
  }
}

/// Notifier để quản lý chi tiết lesson
class LessonDetailNotifier extends StateNotifier<LessonDetailState> {
  final db.AppDatabase _database;
  final String lessonId;
  static const _uuid = Uuid();

  LessonDetailNotifier(this._database, this.lessonId)
      : super(const LessonDetailState()) {
    loadLesson();
  }

  Future<void> loadLesson() async {
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
      final items = <LessonExerciseItem>[];

      for (final item in lessonItems) {
        final exercise = await _database.getExerciseById(item.exerciseId);
        items.add(LessonExerciseItem(lessonItem: item, exercise: exercise));
      }

      state = state.copyWith(
        lesson: lesson,
        items: items,
        isLoading: false,
      );
    } catch (e) {
      debugPrint('Error loading lesson detail: $e');
      state = state.copyWith(
        isLoading: false,
        error: 'Không thể tải chi tiết giáo án',
      );
    }
  }

  Future<void> addExercise(
    String exerciseId, {
    int sets = 3,
    int reps = 10,
    int holdSeconds = 30,
    int restSeconds = 60,
  }) async {
    try {
      final currentOrder = state.items.length;
      
      await _database.insertLessonItem(
        db.LessonItemsCompanion.insert(
          id: _uuid.v4(),
          lessonId: lessonId,
          exerciseId: exerciseId,
          orderIndex: currentOrder,
          sets: Value(sets),
          reps: Value(reps),
          holdSeconds: Value(holdSeconds),
          restSeconds: Value(restSeconds),
        ),
      );
      
      await loadLesson();
    } catch (e) {
      debugPrint('Error adding exercise to lesson: $e');
      state = state.copyWith(error: 'Không thể thêm bài tập');
    }
  }

  Future<void> updateExerciseConfig(
    String itemId, {
    int? sets,
    int? reps,
    int? holdSeconds,
    int? restSeconds,
  }) async {
    try {
      await _database.updateLessonItem(
        db.LessonItemsCompanion(
          id: Value(itemId),
          sets: sets != null ? Value(sets) : const Value.absent(),
          reps: reps != null ? Value(reps) : const Value.absent(),
          holdSeconds: holdSeconds != null ? Value(holdSeconds) : const Value.absent(),
          restSeconds: restSeconds != null ? Value(restSeconds) : const Value.absent(),
        ),
      );
      await loadLesson();
    } catch (e) {
      debugPrint('Error updating lesson item: $e');
      state = state.copyWith(error: 'Không thể cập nhật bài tập');
    }
  }

  Future<void> removeExercise(String itemId) async {
    try {
      await _database.deleteLessonItem(itemId);
      await loadLesson();
    } catch (e) {
      debugPrint('Error removing exercise from lesson: $e');
      state = state.copyWith(error: 'Không thể xóa bài tập');
    }
  }

  Future<void> reorderExercises(int oldIndex, int newIndex) async {
    try {
      final items = List<LessonExerciseItem>.from(state.items);
      
      if (newIndex > oldIndex) {
        newIndex -= 1;
      }
      
      final item = items.removeAt(oldIndex);
      items.insert(newIndex, item);

      // Update order indices in database
      for (int i = 0; i < items.length; i++) {
        await _database.updateLessonItem(
          db.LessonItemsCompanion(
            id: Value(items[i].lessonItem.id),
            orderIndex: Value(i),
          ),
        );
      }

      state = state.copyWith(items: items);
    } catch (e) {
      debugPrint('Error reordering exercises: $e');
      state = state.copyWith(error: 'Không thể sắp xếp lại bài tập');
    }
  }
}

/// Provider cho lesson detail (family provider với lessonId)
final lessonDetailProvider = StateNotifierProvider.family<
    LessonDetailNotifier, LessonDetailState, String>((ref, lessonId) {
  final database = getIt<db.AppDatabase>();
  return LessonDetailNotifier(database, lessonId);
});
