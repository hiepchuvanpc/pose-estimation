import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../presentation/providers/history_provider.dart';
import '../../shared/theme/app_colors.dart';
import '../../data/datasources/local/database.dart' as db;

/// Màn hình chi tiết phiên tập đã hoàn thành
class HistoryDetailScreen extends ConsumerWidget {
  final String sessionId;

  const HistoryDetailScreen({super.key, required this.sessionId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(historyDetailProvider(sessionId));

    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(gradient: AppColors.backgroundGradient),
        child: SafeArea(
          child: Column(
            children: [
              _buildHeader(context, state),
              Expanded(
                child: state.isLoading
                    ? const Center(
                        child: CircularProgressIndicator(color: AppColors.primary),
                      )
                    : state.error != null
                        ? _buildErrorState(context, state.error!)
                        : _buildContent(context, state),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildHeader(BuildContext context, HistoryDetailState state) {
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
                  state.session?.lessonName ?? 'Chi tiết phiên tập',
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.bold,
                        color: Colors.white,
                      ),
                ),
                if (state.session != null)
                  Text(
                    _formatDateTime(state.session!.startedAt),
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: AppColors.textSecondary,
                        ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildErrorState(BuildContext context, String error) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.error_outline, size: 64, color: Colors.red),
            const SizedBox(height: 16),
            Text(
              error,
              textAlign: TextAlign.center,
              style: const TextStyle(color: Colors.white),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildContent(BuildContext context, HistoryDetailState state) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Score summary card
          _buildScoreSummary(context, state),
          const SizedBox(height: 24),
          
          // Stats row
          _buildStatsRow(context, state),
          const SizedBox(height: 24),
          
          // Exercise results
          Text(
            'Chi tiết bài tập',
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.bold,
                  color: Colors.white,
                ),
          ),
          const SizedBox(height: 12),
          
          ...state.results.map((result) => _buildExerciseResultCard(context, result)),
        ],
      ),
    );
  }

  Widget _buildScoreSummary(BuildContext context, HistoryDetailState state) {
    final avgScore = state.averageScore;
    
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
          // Trophy icon
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: _getScoreColor(avgScore).withValues(alpha: 0.15),
              shape: BoxShape.circle,
            ),
            child: Icon(
              Icons.emoji_events,
              color: _getScoreColor(avgScore),
              size: 48,
            ),
          ),
          const SizedBox(height: 16),
          
          // Score
          RichText(
            text: TextSpan(
              children: [
                TextSpan(
                  text: avgScore.toStringAsFixed(1),
                  style: TextStyle(
                    color: _getScoreColor(avgScore),
                    fontSize: 48,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                TextSpan(
                  text: '%',
                  style: TextStyle(
                    color: _getScoreColor(avgScore),
                    fontSize: 24,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          
          // Stars
          _buildStars(avgScore),
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
      mainAxisAlignment: MainAxisAlignment.center,
      children: List.generate(5, (index) {
        if (index < fullStars) {
          return const Icon(Icons.star, color: Colors.amber, size: 28);
        } else if (index == fullStars && hasHalfStar) {
          return const Icon(Icons.star_half, color: Colors.amber, size: 28);
        } else {
          return Icon(Icons.star_border, color: Colors.amber.withValues(alpha: 0.5), size: 28);
        }
      }),
    );
  }

  Widget _buildStatsRow(BuildContext context, HistoryDetailState state) {
    return Row(
      children: [
        Expanded(
          child: _buildStatCard(
            context,
            icon: Icons.fitness_center,
            iconColor: AppColors.primary,
            value: '${state.results.length}',
            label: 'Bài tập',
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: _buildStatCard(
            context,
            icon: Icons.timer,
            iconColor: Colors.orange,
            value: _formatDuration(state.durationSeconds),
            label: 'Thời gian',
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: _buildStatCard(
            context,
            icon: Icons.repeat,
            iconColor: AppColors.accent,
            value: '${_getTotalReps(state.results)}',
            label: 'Tổng reps',
          ),
        ),
      ],
    );
  }

  Widget _buildStatCard(
    BuildContext context, {
    required IconData icon,
    required Color iconColor,
    required String value,
    required String label,
  }) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.cardBackground,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.cardBorder),
      ),
      child: Column(
        children: [
          Icon(icon, color: iconColor, size: 24),
          const SizedBox(height: 8),
          Text(
            value,
            style: Theme.of(context).textTheme.titleLarge?.copyWith(
                  fontWeight: FontWeight.bold,
                  color: Colors.white,
                ),
          ),
          Text(
            label,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: AppColors.textSecondary,
                ),
          ),
        ],
      ),
    );
  }

  Widget _buildExerciseResultCard(BuildContext context, db.ExerciseResult result) {
    final score = result.formScore;
    
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
              color: _getScoreColor(score).withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Center(
              child: Text(
                '${score.toInt()}%',
                style: TextStyle(
                  color: _getScoreColor(score),
                  fontWeight: FontWeight.bold,
                  fontSize: 14,
                ),
              ),
            ),
          ),
          const SizedBox(width: 12),
          
          // Exercise info
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  result.exerciseName,
                  style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 4),
                Row(
                  children: [
                    Text(
                      'Sets: ${result.completedSets}/${result.targetSets}',
                      style: const TextStyle(
                        color: AppColors.textSecondary,
                        fontSize: 12,
                      ),
                    ),
                    const SizedBox(width: 12),
                    if (result.targetHoldSeconds != null)
                      Text(
                        'Hold: ${result.holdDuration?.toInt() ?? 0}s',
                        style: const TextStyle(
                          color: AppColors.textSecondary,
                          fontSize: 12,
                        ),
                      )
                    else
                      Text(
                        'Reps: ${result.completedReps}/${result.targetReps}',
                        style: const TextStyle(
                          color: AppColors.textSecondary,
                          fontSize: 12,
                        ),
                      ),
                  ],
                ),
              ],
            ),
          ),
          
          // Score indicator
          _buildMiniStars(score),
        ],
      ),
    );
  }

  Widget _buildMiniStars(double score) {
    int fullStars = (score / 20).floor();
    
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: List.generate(fullStars, (index) {
        return const Icon(Icons.star, color: Colors.amber, size: 16);
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

  String _formatDateTime(DateTime dt) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final yesterday = today.subtract(const Duration(days: 1));
    final dtDate = DateTime(dt.year, dt.month, dt.day);

    String dateStr;
    if (dtDate == today) {
      dateStr = 'Hôm nay';
    } else if (dtDate == yesterday) {
      dateStr = 'Hôm qua';
    } else {
      dateStr = '${dt.day}/${dt.month}/${dt.year}';
    }
    
    return '$dateStr, ${dt.hour}:${dt.minute.toString().padLeft(2, '0')}';
  }

  String _formatDuration(int seconds) {
    final minutes = seconds ~/ 60;
    final secs = seconds % 60;
    if (minutes > 0) {
      return '$minutes:${secs.toString().padLeft(2, '0')}';
    }
    return '${secs}s';
  }

  int _getTotalReps(List<db.ExerciseResult> results) {
    return results.fold(0, (sum, r) => sum + r.completedReps);
  }
}
