import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/data/mock_templates.dart';
import '../../core/models/template.dart';
import '../../presentation/providers/api_provider.dart';
import '../../presentation/providers/exercise_provider.dart';
import '../../shared/theme/app_colors.dart';
import '../workout/workout_setup.dart';
import 'add_exercise_screen.dart';

/// Thư viện bài tập — danh sách templates từ backend.
class LibraryScreen extends ConsumerStatefulWidget {
  const LibraryScreen({super.key});

  @override
  ConsumerState<LibraryScreen> createState() => _LibraryScreenState();
}

class _LibraryScreenState extends ConsumerState<LibraryScreen>
    with SingleTickerProviderStateMixin {
  List<WorkoutTemplate> _templates = [];
  bool _loading = true;
  bool _isOfflineMode = false;
  late AnimationController _fadeController;

  @override
  void initState() {
    super.initState();
    _fadeController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    );
    _loadTemplates();
  }

  @override
  void dispose() {
    _fadeController.dispose();
    super.dispose();
  }

  Future<void> _loadTemplates() async {
    setState(() {
      _loading = true;
      _isOfflineMode = false;
    });

    try {
      final api = ref.read(apiClientProvider);
      final templates = await api.getTemplates();
      if (mounted) {
        setState(() {
          _templates = templates;
          _loading = false;
          _isOfflineMode = false;
        });
        _fadeController.forward(from: 0);
      }
    } catch (e) {
      // Fallback to offline mode with mock data
      if (mounted) {
        setState(() {
          _templates = MockTemplates.demoTemplates;
          _loading = false;
          _isOfflineMode = true;
        });
        _fadeController.forward(from: 0);

        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Row(
              children: [
                Icon(Icons.cloud_off, color: Colors.white),
                SizedBox(width: 12),
                Expanded(
                  child: Text('Chế độ Offline - Dùng bài tập demo'),
                ),
              ],
            ),
            backgroundColor: AppColors.accent,
            duration: Duration(seconds: 3),
          ),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final exerciseState = ref.watch(exerciseListProvider);

    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: AppColors.backgroundGradient,
        ),
        child: SafeArea(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _buildHeader(exerciseState),
              Expanded(child: _buildContent(exerciseState)),
            ],
          ),
        ),
      ),
      floatingActionButton: exerciseState.isSelectionMode
          ? null
          : FloatingActionButton.extended(
              onPressed: _addNewExercise,
              backgroundColor: AppColors.primary,
              icon: const Icon(Icons.add),
              label: const Text('Thêm bài tập'),
            ),
    );
  }

  Future<void> _addNewExercise() async {
    final result = await Navigator.of(context).push<Map<String, dynamic>>(
      MaterialPageRoute(builder: (_) => const AddExerciseScreen()),
    );

    if (result != null) {
      // Add exercise to database
      ref.read(exerciseListProvider.notifier).addExercise(
        name: result['name'] as String,
        mode: result['mode'] as String,
        videoPath: result['videoPath'] as String,
        thumbnailPath: result['thumbnailPath'] as String?,
        trimStart: result['trimStart'] as double? ?? 0,
        trimEnd: result['trimEnd'] as double? ?? 0,
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Đã thêm bài tập: ${result['name']}'),
            backgroundColor: AppColors.success,
          ),
        );
      }
    }
  }

  Widget _buildHeader(ExerciseListState exerciseState) {
    final totalCount = _templates.length + exerciseState.exercises.length;

    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
      child: Row(
        children: [
          // Selection mode: back button
          if (exerciseState.isSelectionMode)
            IconButton(
              onPressed: () => ref.read(exerciseListProvider.notifier).clearSelection(),
              icon: const Icon(Icons.close, color: Colors.white),
            )
          else
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                gradient: AppColors.primaryGradient,
                borderRadius: BorderRadius.circular(12),
              ),
              child: const Icon(Icons.fitness_center, color: Colors.white, size: 24),
            ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      exerciseState.isSelectionMode
                          ? '${exerciseState.selectedIds.length} đã chọn'
                          : 'Kho bài tập',
                      style: Theme.of(context).textTheme.headlineMedium,
                    ),
                    if (_isOfflineMode && !exerciseState.isSelectionMode) ...[
                      const SizedBox(width: 8),
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 4),
                        decoration: BoxDecoration(
                          color: AppColors.accent.withValues(alpha: 0.2),
                          borderRadius: BorderRadius.circular(6),
                          border: Border.all(
                            color: AppColors.accent.withValues(alpha: 0.4),
                          ),
                        ),
                        child: const Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(Icons.cloud_off, size: 12, color: AppColors.accent),
                            SizedBox(width: 4),
                            Text('Offline',
                                style: TextStyle(
                                  fontSize: 10,
                                  fontWeight: FontWeight.w600,
                                  color: AppColors.accent,
                                )),
                          ],
                        ),
                      ),
                    ],
                  ],
                ),
                if (!exerciseState.isSelectionMode)
                  Text('$totalCount bài tập',
                      style: Theme.of(context).textTheme.bodySmall),
              ],
            ),
          ),
          if (exerciseState.isSelectionMode)
            IconButton(
              onPressed: () => _confirmDeleteSelected(exerciseState),
              icon: const Icon(Icons.delete, color: AppColors.error),
            )
          else
            IconButton(
              onPressed: _loadTemplates,
              icon: const Icon(Icons.refresh, color: AppColors.textSecondary),
            ),
        ],
      ),
    );
  }

  void _confirmDeleteSelected(ExerciseListState exerciseState) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: AppColors.cardBackground,
        title: const Text('Xóa bài tập?', style: TextStyle(color: Colors.white)),
        content: Text(
          'Bạn có chắc muốn xóa ${exerciseState.selectedIds.length} bài tập?',
          style: const TextStyle(color: AppColors.textSecondary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Hủy', style: TextStyle(color: AppColors.primary)),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(context);
              ref.read(exerciseListProvider.notifier).deleteSelectedExercises();
            },
            style: ElevatedButton.styleFrom(backgroundColor: AppColors.error),
            child: const Text('Xóa'),
          ),
        ],
      ),
    );
  }

  Widget _buildContent(ExerciseListState exerciseState) {
    if (_loading || exerciseState.isLoading) {
      return const Center(
        child: CircularProgressIndicator(color: AppColors.primary),
      );
    }

    final totalExercises = exerciseState.exercises.length + _templates.length;

    if (totalExercises == 0) {
      return _buildEmptyState();
    }

    return FadeTransition(
      opacity: _fadeController,
      child: RefreshIndicator(
        onRefresh: () async {
          await _loadTemplates();
          ref.read(exerciseListProvider.notifier).loadExercises();
        },
        color: AppColors.primary,
        child: GridView.builder(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 100),
          gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: 2,
            childAspectRatio: 1.0,
            crossAxisSpacing: 12,
            mainAxisSpacing: 12,
          ),
          itemCount: totalExercises,
          itemBuilder: (context, index) {
            // Local exercises first
            if (index < exerciseState.exercises.length) {
              final exercise = exerciseState.exercises[index];
              return _ExerciseGridItem(
                id: exercise.id,
                name: exercise.name,
                mode: exercise.mode,
                thumbnailPath: exercise.thumbnailPath,
                isSelected: exerciseState.selectedIds.contains(exercise.id),
                isSelectionMode: exerciseState.isSelectionMode,
                onTap: () {
                  if (exerciseState.isSelectionMode) {
                    ref.read(exerciseListProvider.notifier).toggleSelection(exercise.id);
                  } else {
                    _openExerciseDetail(exercise);
                  }
                },
                onLongPress: () {
                  ref.read(exerciseListProvider.notifier).toggleSelection(exercise.id);
                },
              );
            }

            // Then templates from server
            final templateIndex = index - exerciseState.exercises.length;
            final template = _templates[templateIndex];
            return _TemplateGridItem(
              template: template,
              onTap: exerciseState.isSelectionMode
                  ? null
                  : () {
                      Navigator.of(context).push(
                        MaterialPageRoute(
                          builder: (_) => WorkoutSetupScreen(template: template),
                        ),
                      );
                    },
            );
          },
        ),
      ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              padding: const EdgeInsets.all(24),
              decoration: BoxDecoration(
                color: AppColors.primary.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(20),
              ),
              child: const Icon(
                Icons.fitness_center,
                size: 64,
                color: AppColors.primary,
              ),
            ),
            const SizedBox(height: 24),
            Text(
              'Chưa có bài tập nào',
              style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.bold,
                    color: Colors.white,
                  ),
            ),
            const SizedBox(height: 8),
            Text(
              'Thêm bài tập từ video mẫu\nđể bắt đầu tập luyện!',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: AppColors.textSecondary,
                  ),
            ),
            const SizedBox(height: 32),
            ElevatedButton.icon(
              onPressed: _addNewExercise,
              icon: const Icon(Icons.add),
              label: const Text('Thêm bài tập đầu tiên'),
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.primary,
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(
                  horizontal: 24,
                  vertical: 12,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _openExerciseDetail(dynamic exercise) {
    // TODO: Navigate to exercise detail/edit screen
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('Bài tập: ${exercise.name}'),
        backgroundColor: AppColors.primary,
      ),
    );
  }
}

/// Grid item cho exercise từ local database
class _ExerciseGridItem extends StatelessWidget {
  final String id;
  final String name;
  final String mode;
  final String? thumbnailPath;
  final bool isSelected;
  final bool isSelectionMode;
  final VoidCallback onTap;
  final VoidCallback onLongPress;

  const _ExerciseGridItem({
    required this.id,
    required this.name,
    required this.mode,
    this.thumbnailPath,
    required this.isSelected,
    required this.isSelectionMode,
    required this.onTap,
    required this.onLongPress,
  });

  @override
  Widget build(BuildContext context) {
    final isReps = mode == 'reps';

    return GestureDetector(
      onTap: onTap,
      onLongPress: onLongPress,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        decoration: BoxDecoration(
          color: AppColors.cardBackground,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
            color: isSelected ? AppColors.primary : AppColors.cardBorder,
            width: isSelected ? 2 : 1,
          ),
        ),
        child: Stack(
          children: [
            Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // Thumbnail
                Expanded(
                  child: ClipRRect(
                    borderRadius: const BorderRadius.vertical(top: Radius.circular(15)),
                    child: thumbnailPath != null && File(thumbnailPath!).existsSync()
                        ? Image.file(
                            File(thumbnailPath!),
                            fit: BoxFit.cover,
                          )
                        : Container(
                            color: AppColors.surfaceLight,
                            child: Icon(
                              isReps ? Icons.repeat : Icons.timer,
                              size: 40,
                              color: isReps ? AppColors.primary : AppColors.accent,
                            ),
                          ),
                  ),
                ),

                // Info
                Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontWeight: FontWeight.bold,
                          color: Colors.white,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Row(
                        children: [
                          Icon(
                            isReps ? Icons.repeat : Icons.timer,
                            size: 12,
                            color: isReps ? AppColors.primary : AppColors.accent,
                          ),
                          const SizedBox(width: 4),
                          Text(
                            isReps ? 'Reps' : 'Hold',
                            style: TextStyle(
                              fontSize: 11,
                              color: isReps ? AppColors.primary : AppColors.accent,
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ],
            ),

            // Selection checkbox
            if (isSelectionMode)
              Positioned(
                top: 8,
                right: 8,
                child: Container(
                  width: 24,
                  height: 24,
                  decoration: BoxDecoration(
                    color: isSelected ? AppColors.primary : Colors.black54,
                    shape: BoxShape.circle,
                    border: Border.all(color: Colors.white, width: 2),
                  ),
                  child: isSelected
                      ? const Icon(Icons.check, size: 14, color: Colors.white)
                      : null,
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// Grid item cho template từ server
class _TemplateGridItem extends StatelessWidget {
  final WorkoutTemplate template;
  final VoidCallback? onTap;

  const _TemplateGridItem({
    required this.template,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final isReps = template.mode == 'reps';

    return GestureDetector(
      onTap: onTap,
      child: Container(
        decoration: BoxDecoration(
          gradient: AppColors.cardGradient,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
            color: AppColors.primary.withValues(alpha: 0.15),
            width: 1,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Thumbnail placeholder
            Expanded(
              child: Container(
                decoration: BoxDecoration(
                  color: (isReps ? AppColors.primary : AppColors.accent)
                      .withValues(alpha: 0.15),
                  borderRadius: const BorderRadius.vertical(top: Radius.circular(15)),
                ),
                child: Center(
                  child: Icon(
                    isReps ? Icons.repeat : Icons.timer,
                    size: 40,
                    color: isReps ? AppColors.primary : AppColors.accent,
                  ),
                ),
              ),
            ),

            // Info
            Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    template.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontWeight: FontWeight.bold,
                      color: Colors.white,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      Icon(
                        isReps ? Icons.repeat : Icons.timer,
                        size: 12,
                        color: isReps ? AppColors.primary : AppColors.accent,
                      ),
                      const SizedBox(width: 4),
                      Text(
                        isReps ? 'Reps' : 'Hold',
                        style: TextStyle(
                          fontSize: 11,
                          color: isReps ? AppColors.primary : AppColors.accent,
                        ),
                      ),
                      const Spacer(),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(
                          color: AppColors.accent.withValues(alpha: 0.2),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: const Text(
                          'Server',
                          style: TextStyle(
                            fontSize: 9,
                            color: AppColors.accent,
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            ],
          ),
        ),
      );
    }
  }

