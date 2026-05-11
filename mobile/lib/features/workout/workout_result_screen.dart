import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../presentation/providers/workout_provider.dart';
import '../../shared/theme/app_colors.dart';

/// Màn hình kết quả sau khi tập luyện xong
class WorkoutResultScreen extends ConsumerWidget {
  final String sessionId;
  final List<WorkoutExerciseItem> exercises;

  const WorkoutResultScreen({
    super.key,
    required this.sessionId,
    required this.exercises,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Tính điểm trung bình
    final avgScore = exercises.isNotEmpty
        ? exercises.map((e) => e.formScore).reduce((a, b) => a + b) / exercises.length
        : 0.0;

    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(gradient: AppColors.backgroundGradient),
        child: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              children: [
                // Header
                _buildHeader(context),
                const SizedBox(height: 24),
                
                // Score summary
                _buildScoreSummary(context, avgScore),
                const SizedBox(height: 24),
                
                // Exercise results list
                Expanded(
                  child: _buildExerciseList(context),
                ),
                
                // Action buttons
                _buildActionButtons(context, ref),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildHeader(BuildContext context) {
    return Column(
      children: [
        Container(
          padding: const EdgeInsets.all(20),
          decoration: BoxDecoration(
            color: AppColors.accent.withValues(alpha: 0.15),
            shape: BoxShape.circle,
          ),
          child: const Icon(
            Icons.emoji_events,
            color: AppColors.accent,
            size: 48,
          ),
        ),
        const SizedBox(height: 16),
        Text(
          'Hoàn thành tập luyện!',
          style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                fontWeight: FontWeight.bold,
                color: Colors.white,
              ),
        ),
        const SizedBox(height: 8),
        Text(
          '${exercises.length} bài tập',
          style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                color: AppColors.textSecondary,
              ),
        ),
      ],
    );
  }

  Widget _buildScoreSummary(BuildContext context, double avgScore) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: AppColors.cardBackground,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: AppColors.cardBorder),
      ),
      child: Column(
        children: [
          Text(
            'Điểm trung bình',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: AppColors.textSecondary,
                ),
          ),
          const SizedBox(height: 8),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              _buildStars(avgScore),
              const SizedBox(width: 12),
              Text(
                '${avgScore.toStringAsFixed(1)}%',
                style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                      fontWeight: FontWeight.bold,
                      color: _getScoreColor(avgScore),
                    ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            _getScoreMessage(avgScore),
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: AppColors.textSecondary,
                ),
          ),
        ],
      ),
    );
  }

  Widget _buildStars(double score) {
    int fullStars = (score / 20).floor();
    bool hasHalfStar = (score % 20) >= 10;
    
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: List.generate(5, (index) {
        if (index < fullStars) {
          return const Icon(Icons.star, color: Colors.amber, size: 24);
        } else if (index == fullStars && hasHalfStar) {
          return const Icon(Icons.star_half, color: Colors.amber, size: 24);
        } else {
          return Icon(Icons.star_border, color: Colors.amber.withValues(alpha: 0.5), size: 24);
        }
      }),
    );
  }

  Color _getScoreColor(double score) {
    if (score >= 80) return AppColors.accent;
    if (score >= 60) return Colors.amber;
    if (score >= 40) return Colors.orange;
    return Colors.red;
  }

  String _getScoreMessage(double score) {
    if (score >= 90) return 'Xuất sắc! Tư thế chuẩn xác!';
    if (score >= 80) return 'Rất tốt! Tiếp tục phát huy!';
    if (score >= 70) return 'Khá tốt! Cải thiện thêm nhé!';
    if (score >= 60) return 'Ổn! Cần luyện tập thêm.';
    return 'Cố gắng hơn ở lần sau!';
  }

  Widget _buildExerciseList(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Chi tiết bài tập',
          style: Theme.of(context).textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.bold,
                color: Colors.white,
              ),
        ),
        const SizedBox(height: 12),
        Expanded(
          child: ListView.builder(
            itemCount: exercises.length,
            itemBuilder: (context, index) {
              return _buildExerciseResultCard(context, exercises[index]);
            },
          ),
        ),
      ],
    );
  }

  Widget _buildExerciseResultCard(BuildContext context, WorkoutExerciseItem item) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.cardBackground,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.cardBorder),
      ),
      child: Row(
        children: [
          // Exercise icon
          Container(
            width: 48,
            height: 48,
            decoration: BoxDecoration(
              color: AppColors.primary.withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Icon(
              item.isReps ? Icons.repeat : Icons.timer,
              color: AppColors.primary,
            ),
          ),
          const SizedBox(width: 12),
          
          // Exercise info
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  item.exercise.name,
                  style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  item.isReps
                      ? '${item.currentSet} sets × ${item.targetReps} reps'
                      : '${item.currentSet} sets × ${item.targetHoldSeconds}s',
                  style: const TextStyle(
                    color: AppColors.textSecondary,
                    fontSize: 12,
                  ),
                ),
              ],
            ),
          ),
          
          // Score
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    Icons.star,
                    color: _getScoreColor(item.formScore),
                    size: 16,
                  ),
                  const SizedBox(width: 4),
                  Text(
                    '${item.formScore.toStringAsFixed(0)}%',
                    style: TextStyle(
                      color: _getScoreColor(item.formScore),
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ],
              ),
              if (item.isCompleted)
                const Text(
                  '✓ Hoàn thành',
                  style: TextStyle(
                    color: AppColors.accent,
                    fontSize: 10,
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildActionButtons(BuildContext context, WidgetRef ref) {
    return Column(
      children: [
        const SizedBox(height: 16),
        Row(
          children: [
            Expanded(
              child: OutlinedButton(
                onPressed: () {
                  // Reset workout state and go back
                  ref.read(workoutSessionProvider.notifier).reset();
                  Navigator.of(context).pop();
                },
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.textSecondary,
                  side: const BorderSide(color: AppColors.cardBorder),
                  padding: const EdgeInsets.symmetric(vertical: 14),
                ),
                child: const Text('Không lưu'),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: ElevatedButton(
                onPressed: () {
                  // Save is already done in the provider, just reset and go back
                  ref.read(workoutSessionProvider.notifier).reset();
                  Navigator.of(context).pop();
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('Đã lưu kết quả tập luyện!'),
                      backgroundColor: AppColors.accent,
                    ),
                  );
                },
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.primary,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(vertical: 14),
                ),
                child: const Text('Lưu kết quả'),
              ),
            ),
          ],
        ),
      ],
    );
  }
}
