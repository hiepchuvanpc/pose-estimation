import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../presentation/providers/exercise_provider.dart';
import '../../presentation/providers/lesson_provider.dart';
import '../../shared/theme/app_colors.dart';
import '../../data/datasources/local/database.dart' as db;

/// Màn hình chi tiết giáo án - quản lý bài tập trong giáo án
class LessonDetailScreen extends ConsumerStatefulWidget {
  final String lessonId;
  final String lessonName;

  const LessonDetailScreen({
    super.key,
    required this.lessonId,
    required this.lessonName,
  });

  @override
  ConsumerState<LessonDetailScreen> createState() => _LessonDetailScreenState();
}

class _LessonDetailScreenState extends ConsumerState<LessonDetailScreen> {
  @override
  Widget build(BuildContext context) {
    final state = ref.watch(lessonDetailProvider(widget.lessonId));

    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(gradient: AppColors.backgroundGradient),
        child: SafeArea(
          child: Column(
            children: [
              _buildHeader(context),
              Expanded(
                child: state.isLoading
                    ? const Center(
                        child: CircularProgressIndicator(color: AppColors.primary),
                      )
                    : state.items.isEmpty
                        ? _buildEmptyState(context)
                        : _buildExerciseList(context, state),
              ),
            ],
          ),
        ),
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _showAddExerciseSheet(context),
        backgroundColor: AppColors.primary,
        icon: const Icon(Icons.add),
        label: const Text('Thêm bài tập'),
      ),
    );
  }

  Widget _buildHeader(BuildContext context) {
    final state = ref.watch(lessonDetailProvider(widget.lessonId));
    
    return Container(
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          IconButton(
            onPressed: () => Navigator.pop(context),
            icon: const Icon(Icons.arrow_back, color: Colors.white),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  widget.lessonName,
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.bold,
                        color: Colors.white,
                      ),
                ),
                Text(
                  '${state.items.length} bài tập',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: AppColors.textSecondary,
                      ),
                ),
              ],
            ),
          ),
          // Edit name button
          IconButton(
            onPressed: () => _editLessonName(context),
            icon: const Icon(Icons.edit, color: AppColors.primary),
          ),
        ],
      ),
    );
  }

  Widget _buildEmptyState(BuildContext context) {
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
              'Thêm bài tập từ kho bài tập\nđể bắt đầu xây dựng giáo án',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: AppColors.textSecondary,
                  ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildExerciseList(BuildContext context, LessonDetailState state) {
    return ReorderableListView.builder(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 100),
      itemCount: state.items.length,
      onReorder: (oldIndex, newIndex) {
        ref
            .read(lessonDetailProvider(widget.lessonId).notifier)
            .reorderExercises(oldIndex, newIndex);
      },
      itemBuilder: (context, index) {
        final item = state.items[index];
        return _buildExerciseCard(context, item, index);
      },
    );
  }

  Widget _buildExerciseCard(
    BuildContext context,
    LessonExerciseItem item,
    int index,
  ) {
    final exercise = item.exercise;
    final lessonItem = item.lessonItem;
    final isReps = exercise?.mode == 'reps';

    return Card(
      key: ValueKey(lessonItem.id),
      margin: const EdgeInsets.only(bottom: 12),
      color: AppColors.cardBackground,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: AppColors.cardBorder),
      ),
      child: InkWell(
        onTap: () => _showEditExerciseSheet(context, item),
        onLongPress: () => _showDeleteConfirm(context, item),
        borderRadius: BorderRadius.circular(16),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              // Drag handle
              ReorderableDragStartListener(
                index: index,
                child: Container(
                  padding: const EdgeInsets.all(8),
                  child: const Icon(
                    Icons.drag_handle,
                    color: AppColors.textSecondary,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              
              // Exercise icon
              Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(
                  color: (isReps ? AppColors.primary : AppColors.accent)
                      .withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(
                  isReps ? Icons.repeat : Icons.timer,
                  color: isReps ? AppColors.primary : AppColors.accent,
                ),
              ),
              const SizedBox(width: 12),
              
              // Info
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      exercise?.name ?? 'Bài tập không xác định',
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                            fontWeight: FontWeight.bold,
                            color: Colors.white,
                          ),
                    ),
                    const SizedBox(height: 4),
                    Row(
                      children: [
                        _buildInfoChip(
                          '${lessonItem.sets} sets',
                          Icons.layers,
                        ),
                        const SizedBox(width: 8),
                        if (isReps)
                          _buildInfoChip(
                            '${lessonItem.reps} reps',
                            Icons.repeat,
                          )
                        else
                          _buildInfoChip(
                            '${lessonItem.holdSeconds}s',
                            Icons.timer,
                          ),
                      ],
                    ),
                  ],
                ),
              ),
              
              // More button
              IconButton(
                onPressed: () => _showEditExerciseSheet(context, item),
                icon: const Icon(
                  Icons.more_vert,
                  color: AppColors.textSecondary,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildInfoChip(String text, IconData icon) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: AppColors.surfaceVariant,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 12, color: AppColors.textSecondary),
          const SizedBox(width: 4),
          Text(
            text,
            style: const TextStyle(
              fontSize: 12,
              color: AppColors.textSecondary,
            ),
          ),
        ],
      ),
    );
  }

  void _showAddExerciseSheet(BuildContext context) {
    final exerciseState = ref.read(exerciseListProvider);
    
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppColors.cardBackground,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.7,
        minChildSize: 0.5,
        maxChildSize: 0.9,
        expand: false,
        builder: (context, scrollController) {
          return Column(
            children: [
              // Handle
              Container(
                margin: const EdgeInsets.only(top: 12),
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: AppColors.textSecondary.withValues(alpha: 0.3),
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(16),
                child: Text(
                  'Chọn bài tập',
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.bold,
                        color: Colors.white,
                      ),
                ),
              ),
              
              Expanded(
                child: exerciseState.exercises.isEmpty
                    ? Center(
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            const Icon(
                              Icons.fitness_center,
                              size: 48,
                              color: AppColors.textSecondary,
                            ),
                            const SizedBox(height: 16),
                            Text(
                              'Chưa có bài tập nào',
                              style: TextStyle(color: AppColors.textSecondary),
                            ),
                            const SizedBox(height: 8),
                            TextButton(
                              onPressed: () {
                                Navigator.pop(context);
                                // TODO: Navigate to library
                              },
                              child: const Text('Thêm bài tập mới'),
                            ),
                          ],
                        ),
                      )
                    : ListView.builder(
                        controller: scrollController,
                        padding: const EdgeInsets.symmetric(horizontal: 16),
                        itemCount: exerciseState.exercises.length,
                        itemBuilder: (context, index) {
                          final exercise = exerciseState.exercises[index];
                          return _buildExerciseSelectItem(context, exercise);
                        },
                      ),
              ),
            ],
          );
        },
      ),
    );
  }

  Widget _buildExerciseSelectItem(BuildContext context, db.Exercise exercise) {
    final isReps = exercise.mode == 'reps';
    
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      color: AppColors.surfaceVariant,
      child: ListTile(
        leading: Container(
          width: 48,
          height: 48,
          decoration: BoxDecoration(
            color: (isReps ? AppColors.primary : AppColors.accent)
                .withValues(alpha: 0.15),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Icon(
            isReps ? Icons.repeat : Icons.timer,
            color: isReps ? AppColors.primary : AppColors.accent,
          ),
        ),
        title: Text(
          exercise.name,
          style: const TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.w500,
          ),
        ),
        subtitle: Text(
          isReps ? 'Reps' : 'Hold',
          style: const TextStyle(color: AppColors.textSecondary),
        ),
        trailing: const Icon(Icons.add_circle, color: AppColors.primary),
        onTap: () {
          Navigator.pop(context);
          _showConfigExerciseSheet(context, exercise);
        },
      ),
    );
  }

  void _showConfigExerciseSheet(BuildContext context, db.Exercise exercise) {
    final isReps = exercise.mode == 'reps';
    int sets = 3;
    int reps = 10;
    int holdSeconds = 30;
    int restSeconds = 60;

    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.cardBackground,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setModalState) {
          return Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Center(
                  child: Container(
                    width: 40,
                    height: 4,
                    decoration: BoxDecoration(
                      color: AppColors.textSecondary.withValues(alpha: 0.3),
                      borderRadius: BorderRadius.circular(2),
                    ),
                  ),
                ),
                const SizedBox(height: 20),
                
                Text(
                  'Cấu hình: ${exercise.name}',
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.bold,
                        color: Colors.white,
                      ),
                ),
                const SizedBox(height: 24),
                
                // Sets
                _buildNumberPicker(
                  label: 'Số sets',
                  value: sets,
                  min: 1,
                  max: 10,
                  onChanged: (v) => setModalState(() => sets = v),
                ),
                const SizedBox(height: 16),
                
                // Reps or Hold
                if (isReps)
                  _buildNumberPicker(
                    label: 'Số reps mỗi set',
                    value: reps,
                    min: 1,
                    max: 50,
                    onChanged: (v) => setModalState(() => reps = v),
                  )
                else
                  _buildNumberPicker(
                    label: 'Giữ (giây)',
                    value: holdSeconds,
                    min: 5,
                    max: 120,
                    step: 5,
                    onChanged: (v) => setModalState(() => holdSeconds = v),
                  ),
                const SizedBox(height: 16),
                
                // Rest
                _buildNumberPicker(
                  label: 'Nghỉ giữa sets (giây)',
                  value: restSeconds,
                  min: 10,
                  max: 180,
                  step: 10,
                  onChanged: (v) => setModalState(() => restSeconds = v),
                ),
                const SizedBox(height: 24),
                
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    onPressed: () {
                      Navigator.pop(ctx);
                      ref
                          .read(lessonDetailProvider(widget.lessonId).notifier)
                          .addExercise(
                            exercise.id,
                            sets: sets,
                            reps: reps,
                            holdSeconds: holdSeconds,
                            restSeconds: restSeconds,
                          );
                    },
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppColors.primary,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                    ),
                    child: const Text('Thêm vào giáo án'),
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildNumberPicker({
    required String label,
    required int value,
    required int min,
    required int max,
    int step = 1,
    required ValueChanged<int> onChanged,
  }) {
    return Row(
      children: [
        Expanded(
          child: Text(
            label,
            style: const TextStyle(color: Colors.white),
          ),
        ),
        IconButton(
          onPressed: value > min
              ? () => onChanged((value - step).clamp(min, max))
              : null,
          icon: Icon(
            Icons.remove_circle,
            color: value > min ? AppColors.primary : AppColors.textSecondary,
          ),
        ),
        Container(
          width: 48,
          alignment: Alignment.center,
          child: Text(
            '$value',
            style: const TextStyle(
              color: Colors.white,
              fontWeight: FontWeight.bold,
              fontSize: 18,
            ),
          ),
        ),
        IconButton(
          onPressed: value < max
              ? () => onChanged((value + step).clamp(min, max))
              : null,
          icon: Icon(
            Icons.add_circle,
            color: value < max ? AppColors.primary : AppColors.textSecondary,
          ),
        ),
      ],
    );
  }

  void _showEditExerciseSheet(BuildContext context, LessonExerciseItem item) {
    final exercise = item.exercise;
    final lessonItem = item.lessonItem;
    final isReps = exercise?.mode == 'reps';
    
    int sets = lessonItem.sets;
    int reps = lessonItem.reps;
    int holdSeconds = lessonItem.holdSeconds;
    int restSeconds = lessonItem.restSeconds;

    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.cardBackground,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setModalState) {
          return Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Center(
                  child: Container(
                    width: 40,
                    height: 4,
                    decoration: BoxDecoration(
                      color: AppColors.textSecondary.withValues(alpha: 0.3),
                      borderRadius: BorderRadius.circular(2),
                    ),
                  ),
                ),
                const SizedBox(height: 20),
                
                Text(
                  'Chỉnh sửa: ${exercise?.name ?? "Bài tập"}',
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.bold,
                        color: Colors.white,
                      ),
                ),
                const SizedBox(height: 24),
                
                _buildNumberPicker(
                  label: 'Số sets',
                  value: sets,
                  min: 1,
                  max: 10,
                  onChanged: (v) => setModalState(() => sets = v),
                ),
                const SizedBox(height: 16),
                
                if (isReps)
                  _buildNumberPicker(
                    label: 'Số reps mỗi set',
                    value: reps,
                    min: 1,
                    max: 50,
                    onChanged: (v) => setModalState(() => reps = v),
                  )
                else
                  _buildNumberPicker(
                    label: 'Giữ (giây)',
                    value: holdSeconds,
                    min: 5,
                    max: 120,
                    step: 5,
                    onChanged: (v) => setModalState(() => holdSeconds = v),
                  ),
                const SizedBox(height: 16),
                
                _buildNumberPicker(
                  label: 'Nghỉ giữa sets (giây)',
                  value: restSeconds,
                  min: 10,
                  max: 180,
                  step: 10,
                  onChanged: (v) => setModalState(() => restSeconds = v),
                ),
                const SizedBox(height: 24),
                
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton(
                        onPressed: () {
                          Navigator.pop(ctx);
                          _showDeleteConfirm(context, item);
                        },
                        style: OutlinedButton.styleFrom(
                          foregroundColor: Colors.red,
                          side: const BorderSide(color: Colors.red),
                          padding: const EdgeInsets.symmetric(vertical: 16),
                        ),
                        child: const Text('Xóa'),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: ElevatedButton(
                        onPressed: () {
                          Navigator.pop(ctx);
                          ref
                              .read(lessonDetailProvider(widget.lessonId).notifier)
                              .updateExerciseConfig(
                                lessonItem.id,
                                sets: sets,
                                reps: reps,
                                holdSeconds: holdSeconds,
                                restSeconds: restSeconds,
                              );
                        },
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppColors.primary,
                          padding: const EdgeInsets.symmetric(vertical: 16),
                        ),
                        child: const Text('Lưu'),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  void _showDeleteConfirm(BuildContext context, LessonExerciseItem item) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: AppColors.cardBackground,
        title: const Text(
          'Xóa bài tập?',
          style: TextStyle(color: Colors.white),
        ),
        content: Text(
          'Xóa "${item.exercise?.name ?? "bài tập"}" khỏi giáo án?',
          style: const TextStyle(color: AppColors.textSecondary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Hủy'),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(context);
              ref
                  .read(lessonDetailProvider(widget.lessonId).notifier)
                  .removeExercise(item.lessonItem.id);
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
            child: const Text('Xóa'),
          ),
        ],
      ),
    );
  }

  void _editLessonName(BuildContext context) {
    final state = ref.read(lessonDetailProvider(widget.lessonId));
    final controller = TextEditingController(text: state.lesson?.name ?? '');

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: AppColors.cardBackground,
        title: const Text(
          'Đổi tên giáo án',
          style: TextStyle(color: Colors.white),
        ),
        content: TextField(
          controller: controller,
          autofocus: true,
          style: const TextStyle(color: Colors.white),
          decoration: InputDecoration(
            hintText: 'Tên giáo án',
            hintStyle: TextStyle(color: AppColors.textSecondary.withValues(alpha: 0.5)),
            filled: true,
            fillColor: AppColors.surfaceVariant,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: BorderSide.none,
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Hủy'),
          ),
          ElevatedButton(
            onPressed: () {
              final newName = controller.text.trim();
              if (newName.isNotEmpty) {
                ref
                    .read(lessonListProvider.notifier)
                    .updateLesson(widget.lessonId, name: newName);
                Navigator.pop(context);
              }
            },
            style: ElevatedButton.styleFrom(backgroundColor: AppColors.primary),
            child: const Text('Lưu'),
          ),
        ],
      ),
    );
  }
}
