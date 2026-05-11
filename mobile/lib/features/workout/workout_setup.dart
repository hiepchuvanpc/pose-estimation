import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:video_player/video_player.dart';

import '../../core/models/template.dart';
import '../../core/models/workout.dart';
import '../../presentation/providers/api_provider.dart';
import '../../shared/theme/app_colors.dart';
import 'workout_live.dart';

/// Màn hình thiết lập buổi tập: chọn sets, reps trước khi vào camera.
class WorkoutSetupScreen extends ConsumerStatefulWidget {
  final WorkoutTemplate template;

  const WorkoutSetupScreen({super.key, required this.template});

  @override
  ConsumerState<WorkoutSetupScreen> createState() => _WorkoutSetupScreenState();
}

class _WorkoutSetupScreenState extends ConsumerState<WorkoutSetupScreen> {
  int _sets = 3;
  int _repsPerSet = 10;
  double _holdSeconds = 30;
  int _restSeconds = 30;
  bool _starting = false;

  VideoPlayerController? _videoController;
  bool _videoLoading = true;
  String? _videoError;

  bool get _isReps => widget.template.mode == 'reps';

  @override
  void initState() {
    super.initState();
    _initVideo();
  }

  @override
  void dispose() {
    _videoController?.dispose();
    super.dispose();
  }

  Future<void> _initVideo() async {
    final api = ref.read(apiClientProvider);
    final videoUrl = '${api.baseUrl}${widget.template.videoUri}';

    try {
      _videoController = VideoPlayerController.networkUrl(Uri.parse(videoUrl));
      await _videoController!.initialize();
      _videoController!.setLooping(true);
      _videoController!.play();

      if (mounted) {
        setState(() {
          _videoLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _videoLoading = false;
          _videoError = 'Không thể load video';
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
              // App bar
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                child: Row(
                  children: [
                    IconButton(
                      icon: const Icon(Icons.arrow_back_ios_new, size: 20),
                      onPressed: () => Navigator.pop(context),
                    ),
                    Expanded(
                      child: Text(
                        widget.template.name,
                        style: Theme.of(context).textTheme.titleLarge,
                        textAlign: TextAlign.center,
                      ),
                    ),
                    const SizedBox(width: 48), // balance
                  ],
                ),
              ),

              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    children: [
                      // Video preview
                      _buildVideoPreview(),
                      const SizedBox(height: 20),

                      // Exercise info card
                      _buildInfoCard(),
                      const SizedBox(height: 24),

                      // Settings
                      _buildSettingRow(
                        icon: Icons.layers,
                        label: 'Số set',
                        value: '$_sets',
                        onMinus: () =>
                            setState(() => _sets = (_sets - 1).clamp(1, 20)),
                        onPlus: () =>
                            setState(() => _sets = (_sets + 1).clamp(1, 20)),
                      ),
                      const SizedBox(height: 12),

                      if (_isReps)
                        _buildSettingRow(
                          icon: Icons.repeat,
                          label: 'Rep / set',
                          value: '$_repsPerSet',
                          onMinus: () => setState(
                              () => _repsPerSet = (_repsPerSet - 1).clamp(1, 100)),
                          onPlus: () => setState(
                              () => _repsPerSet = (_repsPerSet + 1).clamp(1, 100)),
                        )
                      else
                        _buildSettingRow(
                          icon: Icons.timer,
                          label: 'Giây / set',
                          value: '${_holdSeconds.toInt()}s',
                          onMinus: () => setState(() =>
                              _holdSeconds = (_holdSeconds - 5).clamp(5, 300)),
                          onPlus: () => setState(() =>
                              _holdSeconds = (_holdSeconds + 5).clamp(5, 300)),
                        ),
                      const SizedBox(height: 12),

                      _buildSettingRow(
                        icon: Icons.pause_circle_outline,
                        label: 'Nghỉ giữa set',
                        value: '${_restSeconds}s',
                        onMinus: () => setState(
                            () => _restSeconds = (_restSeconds - 5).clamp(0, 120)),
                        onPlus: () => setState(
                            () => _restSeconds = (_restSeconds + 5).clamp(0, 120)),
                      ),
                    ],
                  ),
                ),
              ),

              // Start button
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
                child: SizedBox(
                  width: double.infinity,
                  height: 56,
                  child: ElevatedButton(
                    onPressed: _starting ? null : _startWorkout,
                    style: ElevatedButton.styleFrom(
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(16),
                      ),
                    ),
                    child: _starting
                        ? const SizedBox(
                            width: 24,
                            height: 24,
                            child: CircularProgressIndicator(
                              color: Colors.white,
                              strokeWidth: 2.5,
                            ),
                          )
                        : const Row(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Icon(Icons.play_arrow, size: 28),
                              SizedBox(width: 8),
                              Text('Bắt đầu tập',
                                  style: TextStyle(
                                      fontSize: 17,
                                      fontWeight: FontWeight.w700)),
                            ],
                          ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildVideoPreview() {
    return Container(
      height: 240,
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(
          color: AppColors.primary.withValues(alpha: 0.2),
        ),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(20),
        child: _videoLoading
            ? const Center(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    CircularProgressIndicator(color: AppColors.primary),
                    SizedBox(height: 12),
                    Text('Đang tải video...', style: TextStyle(color: AppColors.textHint)),
                  ],
                ),
              )
            : _videoError != null
                ? Center(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.videocam_off, size: 48, color: AppColors.textHint),
                        SizedBox(height: 8),
                        Text(_videoError!, style: TextStyle(color: AppColors.textHint)),
                        SizedBox(height: 12),
                        TextButton.icon(
                          onPressed: () {
                            setState(() {
                              _videoLoading = true;
                              _videoError = null;
                            });
                            _initVideo();
                          },
                          icon: Icon(Icons.refresh),
                          label: Text('Thử lại'),
                        ),
                      ],
                    ),
                  )
                : Stack(
                    fit: StackFit.expand,
                    children: [
                      FittedBox(
                        fit: BoxFit.cover,
                        child: SizedBox(
                          width: _videoController!.value.size.width,
                          height: _videoController!.value.size.height,
                          child: VideoPlayer(_videoController!),
                        ),
                      ),
                      // Play/Pause overlay
                      Positioned.fill(
                        child: Material(
                          color: Colors.transparent,
                          child: InkWell(
                            onTap: () {
                              setState(() {
                                if (_videoController!.value.isPlaying) {
                                  _videoController!.pause();
                                } else {
                                  _videoController!.play();
                                }
                              });
                            },
                            child: Center(
                              child: AnimatedOpacity(
                                opacity: _videoController!.value.isPlaying ? 0.0 : 0.8,
                                duration: const Duration(milliseconds: 200),
                                child: Container(
                                  padding: const EdgeInsets.all(16),
                                  decoration: BoxDecoration(
                                    color: Colors.black54,
                                    shape: BoxShape.circle,
                                  ),
                                  child: Icon(
                                    _videoController!.value.isPlaying
                                        ? Icons.pause
                                        : Icons.play_arrow,
                                    color: Colors.white,
                                    size: 48,
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
      ),
    );
  }

  Widget _buildInfoCard() {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: AppColors.cardGradient,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(
          color: AppColors.primary.withValues(alpha: 0.2),
        ),
      ),
      child: Row(
        children: [
          Container(
            width: 64,
            height: 64,
            decoration: BoxDecoration(
              gradient: AppColors.primaryGradient,
              borderRadius: BorderRadius.circular(18),
            ),
            child: Icon(
              _isReps ? Icons.repeat : Icons.timer,
              color: Colors.white,
              size: 32,
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(widget.template.name,
                    style: Theme.of(context).textTheme.titleLarge),
                const SizedBox(height: 4),
                Text(
                  _isReps ? 'Chế độ đếm rep' : 'Chế độ giữ tư thế',
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                if (widget.template.notes != null) ...[
                  const SizedBox(height: 4),
                  Text(widget.template.notes!,
                      style: Theme.of(context).textTheme.bodySmall),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSettingRow({
    required IconData icon,
    required String label,
    required String value,
    required VoidCallback onMinus,
    required VoidCallback onPlus,
  }) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: AppColors.surfaceLight,
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(
        children: [
          Icon(icon, color: AppColors.textSecondary, size: 22),
          const SizedBox(width: 12),
          Expanded(
            child: Text(label,
                style: Theme.of(context).textTheme.titleMedium),
          ),
          // Counter
          Container(
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(10),
            ),
            child: Row(
              children: [
                _counterButton(Icons.remove, onMinus),
                SizedBox(
                  width: 48,
                  child: Text(value,
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: AppColors.primary,
                      )),
                ),
                _counterButton(Icons.add, onPlus),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _counterButton(IconData icon, VoidCallback onTap) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(8),
          child: Icon(icon, size: 20, color: AppColors.textSecondary),
        ),
      ),
    );
  }

  Future<void> _startWorkout() async {
    setState(() => _starting = true);

    // Check if offline mode (demo template)
    final isOffline = widget.template.templateId.startsWith('demo-');

    if (isOffline) {
      // Offline mode: Skip backend, go directly to workout
      if (!mounted) return;

      Navigator.of(context).pushReplacement(
        MaterialPageRoute(
          builder: (_) => WorkoutLiveScreen(
            sessionId: 'offline-${DateTime.now().millisecondsSinceEpoch}',
            template: widget.template,
            profile: null, // No profile in offline mode
          ),
        ),
      );
      return;
    }

    // Online mode: Use backend
    final api = ref.read(apiClientProvider);

    // Ensure profile exists
    final profile = await api.getTemplateProfile(widget.template.templateId);
    if (profile == null) {
      // Try creating profile first
      await api.createTemplateProfile(widget.template.templateId);
    }

    // Start session on backend
    final step = WorkoutStepConfig(
      templateId: widget.template.templateId,
      sets: _sets,
      repsPerSet: _isReps ? _repsPerSet : null,
      holdSecondsPerSet: _isReps ? null : _holdSeconds,
      restSecondsBetweenSets: _restSeconds,
    );

    final result = await api.startWorkoutSession(steps: [step]);

    if (!mounted) return;

    if (result == null) {
      setState(() => _starting = false);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Không thể kết nối tới server')),
      );
      return;
    }

    final sessionId = result['session_id'] as String;
    final fetchedProfile =
        await api.getTemplateProfile(widget.template.templateId);

    if (!mounted) return;

    Navigator.of(context).pushReplacement(
      MaterialPageRoute(
        builder: (_) => WorkoutLiveScreen(
          sessionId: sessionId,
          template: widget.template,
          profile: fetchedProfile,
        ),
      ),
    );
  }
}
