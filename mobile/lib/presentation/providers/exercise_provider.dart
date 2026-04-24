import 'dart:io';

import 'package:drift/drift.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../../app/di/injection.dart';
import '../../data/datasources/local/database.dart' as db;

/// State cho danh sách exercises của user
class ExerciseListState {
  final List<db.Exercise> exercises;
  final bool isLoading;
  final String? error;
  final Set<String> selectedIds; // For multi-select delete

  const ExerciseListState({
    this.exercises = const [],
    this.isLoading = false,
    this.error,
    this.selectedIds = const {},
  });

  bool get isSelectionMode => selectedIds.isNotEmpty;

  ExerciseListState copyWith({
    List<db.Exercise>? exercises,
    bool? isLoading,
    String? error,
    Set<String>? selectedIds,
  }) {
    return ExerciseListState(
      exercises: exercises ?? this.exercises,
      isLoading: isLoading ?? this.isLoading,
      error: error,
      selectedIds: selectedIds ?? this.selectedIds,
    );
  }
}

/// Notifier để quản lý danh sách exercises
class ExerciseListNotifier extends StateNotifier<ExerciseListState> {
  final db.AppDatabase _database;
  static const _uuid = Uuid();

  ExerciseListNotifier(this._database) : super(const ExerciseListState()) {
    loadExercises();
  }

  Future<void> loadExercises() async {
    state = state.copyWith(isLoading: true, error: null);

    try {
      final exercises = await _database.getAllExercisesForExport();
      state = state.copyWith(
        exercises: exercises,
        isLoading: false,
      );
    } catch (e) {
      debugPrint('Error loading exercises: $e');
      state = state.copyWith(
        isLoading: false,
        error: 'Không thể tải danh sách bài tập',
      );
    }
  }

  Future<void> addExercise({
    required String name,
    required String mode,
    required String videoPath,
    String? thumbnailPath,
    double trimStart = 0,
    double? trimEnd,
  }) async {
    try {
      final now = DateTime.now();
      await _database.insertExercise(
        db.ExercisesCompanion.insert(
          id: _uuid.v4(),
          userId: 'local_user', // TODO: Get actual user ID from auth
          name: name,
          mode: mode,
          videoPath: videoPath,
          thumbnailPath: Value(thumbnailPath),
          trimStartSec: Value(trimStart),
          trimEndSec: Value(trimEnd),
          createdAt: now,
          updatedAt: now,
        ),
      );
      await loadExercises();
    } catch (e) {
      debugPrint('Error adding exercise: $e');
      state = state.copyWith(error: 'Không thể thêm bài tập');
    }
  }

  Future<void> deleteExercise(String id) async {
    try {
      final exercise = state.exercises.firstWhereOrNull((e) => e.id == id);
      if (exercise == null) return;
      
      // Delete video file
      final videoFile = File(exercise.videoPath);
      if (await videoFile.exists()) {
        await videoFile.delete();
      }

      // Delete thumbnail file
      if (exercise.thumbnailPath != null) {
        final thumbFile = File(exercise.thumbnailPath!);
        if (await thumbFile.exists()) {
          await thumbFile.delete();
        }
      }

      // Delete from database
      await _database.deleteExercise(id);
      await loadExercises();
    } catch (e) {
      debugPrint('Error deleting exercise: $e');
      state = state.copyWith(error: 'Không thể xóa bài tập');
    }
  }

  Future<void> deleteSelectedExercises() async {
    final selectedIds = state.selectedIds.toList();
    
    for (final id in selectedIds) {
      await deleteExercise(id);
    }
    
    clearSelection();
  }

  void toggleSelection(String id) {
    final newSelection = Set<String>.from(state.selectedIds);
    if (newSelection.contains(id)) {
      newSelection.remove(id);
    } else {
      newSelection.add(id);
    }
    state = state.copyWith(selectedIds: newSelection);
  }

  void selectAll() {
    state = state.copyWith(
      selectedIds: state.exercises.map((e) => e.id).toSet(),
    );
  }

  void clearSelection() {
    state = state.copyWith(selectedIds: {});
  }
}

/// Extension for List to add firstWhereOrNull
extension ListExtension<T> on List<T> {
  T? firstWhereOrNull(bool Function(T) test) {
    for (final element in this) {
      if (test(element)) return element;
    }
    return null;
  }
}

/// Provider cho exercise list
final exerciseListProvider =
    StateNotifierProvider<ExerciseListNotifier, ExerciseListState>((ref) {
  final database = getIt<db.AppDatabase>();
  return ExerciseListNotifier(database);
});
