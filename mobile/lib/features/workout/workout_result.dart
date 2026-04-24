import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../presentation/providers/api_provider.dart';
import '../../shared/theme/app_colors.dart';

/// Màn hình kết quả sau khi kết thúc buổi tập.
class WorkoutResultScreen extends ConsumerStatefulWidget {
  final String sessionId;
  final String templateName;

  const WorkoutResultScreen({
    super.key,
    required this.sessionId,
    required this.templateName,
  });

  @override
  ConsumerState<WorkoutResultScreen> createState() => _WorkoutResultScreenState();
}

class _WorkoutResultScreenState extends ConsumerState<WorkoutResultScreen>
    with SingleTickerProviderStateMixin {
  Map<String, dynamic>? _result;
  bool _loading = true;
  String? _error;
  late AnimationController _fadeController;

  @override
  void initState() {
    super.initState();
    _fadeController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    );
    _finalizeWorkout();
  }

  @override
  void dispose() {
    _fadeController.dispose();
    super.dispose();
  }

  Future<void> _finalizeWorkout() async {
    try {
      final api = ref.read(apiClientProvider);
      final result = await api.finalizeWorkout(widget.sessionId);
      if (mounted) {
        setState(() {
          _result = result;
          _loading = false;
        });
        _fadeController.forward();
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = 'Không thể lấy kết quả phân tích.';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(gradient: AppColors.backgroundGradient),
        child: SafeArea(
          child: Column(
            children: [
              // Header
              Padding(
                padding: const EdgeInsets.all(16),
                child: Text('Kết quả buổi tập',
                    style: Theme.of(context).textTheme.headlineMedium),
              ),

              Expanded(child: _buildContent()),

              // Done button
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
                child: SizedBox(
                  width: double.infinity,
                  height: 52,
                  child: ElevatedButton(
                    onPressed: () {
                      Navigator.of(context)
                          .popUntil((route) => route.isFirst);
                    },
                    child: const Text('Về trang chính',
                        style: TextStyle(fontSize: 16)),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildContent() {
    if (_loading) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            CircularProgressIndicator(color: AppColors.primary),
            SizedBox(height: 16),
            Text('Đang phân tích kết quả...',
                style: TextStyle(color: AppColors.textSecondary)),
          ],
        ),
      );
    }

    if (_error != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline,
                size: 56, color: AppColors.warning),
            const SizedBox(height: 12),
            Text(_error!, style: Theme.of(context).textTheme.bodyMedium),
          ],
        ),
      );
    }

    final analysis = _result?['analysis'] as Map<String, dynamic>? ?? {};
    final totalEvents = _result?['total_events'] ?? 0;

    return FadeTransition(
      opacity: _fadeController,
      child: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 20),
        child: Column(
          children: [
            // Summary card
            _buildSummaryCard(totalEvents, analysis),
            const SizedBox(height: 16),

            // Analysis details
            if (analysis.isNotEmpty) _buildAnalysisCard(analysis),
          ],
        ),
      ),
    );
  }

  Widget _buildSummaryCard(int totalEvents, Map<String, dynamic> analysis) {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        gradient: AppColors.cardGradient,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(
          color: AppColors.accent.withValues(alpha: 0.3),
        ),
      ),
      child: Column(
        children: [
          // Trophy icon
          Container(
            width: 72,
            height: 72,
            decoration: BoxDecoration(
              gradient: AppColors.primaryGradient,
              borderRadius: BorderRadius.circular(20),
            ),
            child: const Icon(Icons.emoji_events, color: Colors.white, size: 36),
          ),
          const SizedBox(height: 16),
          Text(
            widget.templateName,
            style: Theme.of(context).textTheme.titleLarge,
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 8),
          Text(
            'Buổi tập hoàn tất',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: AppColors.accent,
                  fontWeight: FontWeight.w600,
                ),
          ),
          const SizedBox(height: 20),

          // Stats row
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceEvenly,
            children: [
              _statItem(
                Icons.timeline,
                '$totalEvents',
                'Sự kiện',
              ),
              _statItem(
                Icons.timer,
                '${(analysis['duration_seconds'] ?? 0).toStringAsFixed(0)}s',
                'Thời gian',
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _statItem(IconData icon, String value, String label) {
    return Column(
      children: [
        Icon(icon, color: AppColors.primaryLight, size: 28),
        const SizedBox(height: 6),
        Text(value,
            style: const TextStyle(
              fontSize: 22,
              fontWeight: FontWeight.w800,
              color: AppColors.textPrimary,
            )),
        Text(label, style: Theme.of(context).textTheme.bodySmall),
      ],
    );
  }

  Widget _buildAnalysisCard(Map<String, dynamic> analysis) {
    final entries = analysis.entries
        .where((e) => e.key != 'duration_seconds')
        .toList();

    if (entries.isEmpty) return const SizedBox();

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: AppColors.surfaceCard,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Chi tiết phân tích',
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 12),
          ...entries.map((e) => Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Expanded(
                      child: Text(e.key,
                          style: Theme.of(context).textTheme.bodyMedium),
                    ),
                    Text('${e.value}',
                        style: const TextStyle(
                          color: AppColors.accent,
                          fontWeight: FontWeight.w600,
                        )),
                  ],
                ),
              )),
        ],
      ),
    );
  }
}
