import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../services/video/video_processing_service.dart';
import '../../shared/theme/app_colors.dart';
import 'video_trimmer_screen.dart';

/// Screen để chọn video từ gallery và bắt đầu quá trình tạo bài tập
class AddExerciseScreen extends ConsumerStatefulWidget {
  const AddExerciseScreen({super.key});

  @override
  ConsumerState<AddExerciseScreen> createState() => _AddExerciseScreenState();
}

class _AddExerciseScreenState extends ConsumerState<AddExerciseScreen> {
  final ImagePicker _picker = ImagePicker();
  bool _isLoading = false;
  String? _errorMessage;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(gradient: AppColors.backgroundGradient),
        child: SafeArea(
          child: Column(
            children: [
              _buildHeader(),
              Expanded(
                child: _isLoading
                    ? _buildLoadingState()
                    : _buildContent(),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildHeader() {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          IconButton(
            onPressed: () => Navigator.pop(context),
            icon: const Icon(Icons.close, color: Colors.white),
          ),
          const SizedBox(width: 8),
          Text(
            'Thêm bài tập mới',
            style: Theme.of(context).textTheme.titleLarge?.copyWith(
                  fontWeight: FontWeight.bold,
                  color: Colors.white,
                ),
          ),
        ],
      ),
    );
  }

  Widget _buildLoadingState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const CircularProgressIndicator(color: AppColors.primary),
          const SizedBox(height: 24),
          Text(
            'Đang xử lý video...',
            style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                  color: AppColors.textSecondary,
                ),
          ),
        ],
      ),
    );
  }

  Widget _buildContent() {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          // Error message
          if (_errorMessage != null) ...[
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: AppColors.error.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: AppColors.error.withValues(alpha: 0.3)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.error_outline, color: AppColors.error),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      _errorMessage!,
                      style: const TextStyle(color: AppColors.error),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 32),
          ],

          // Illustration
          Container(
            padding: const EdgeInsets.all(32),
            decoration: BoxDecoration(
              color: AppColors.primary.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(24),
            ),
            child: const Icon(
              Icons.video_library,
              size: 80,
              color: AppColors.primary,
            ),
          ),
          const SizedBox(height: 32),

          Text(
            'Chọn video mẫu',
            style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.bold,
                  color: Colors.white,
                ),
          ),
          const SizedBox(height: 12),
          Text(
            'Chọn video bài tập từ thư viện.\nBạn sẽ có thể cắt đoạn video phù hợp.',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: AppColors.textSecondary,
                ),
          ),
          const SizedBox(height: 40),

          // Pick from gallery button
          SizedBox(
            width: double.infinity,
            height: 56,
            child: ElevatedButton.icon(
              onPressed: _pickVideoFromGallery,
              icon: const Icon(Icons.photo_library),
              label: const Text('Chọn từ thư viện'),
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.primary,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(16),
                ),
              ),
            ),
          ),
          const SizedBox(height: 16),

          // Record video button
          SizedBox(
            width: double.infinity,
            height: 56,
            child: OutlinedButton.icon(
              onPressed: _recordVideo,
              icon: const Icon(Icons.videocam),
              label: const Text('Quay video mới'),
              style: OutlinedButton.styleFrom(
                foregroundColor: AppColors.primary,
                side: const BorderSide(color: AppColors.primary),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(16),
                ),
              ),
            ),
          ),

          const SizedBox(height: 40),

          // Tips
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: AppColors.surfaceLight,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(Icons.lightbulb_outline,
                        color: AppColors.accent, size: 20),
                    const SizedBox(width: 8),
                    Text(
                      'Gợi ý',
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                            fontWeight: FontWeight.bold,
                            color: AppColors.accent,
                          ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Text(
                  '• Video nên quay rõ toàn thân\n'
                  '• Nền đơn giản, ánh sáng tốt\n'
                  '• Thực hiện đúng form chuẩn',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: AppColors.textSecondary,
                        height: 1.5,
                      ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _pickVideoFromGallery() async {
    setState(() {
      _errorMessage = null;
    });

    try {
      final XFile? video = await _picker.pickVideo(
        source: ImageSource.gallery,
        maxDuration: const Duration(minutes: 5),
      );

      if (video == null) {
        return; // User cancelled
      }

      await _processSelectedVideo(video.path);
    } catch (e) {
      setState(() {
        _errorMessage = 'Không thể chọn video: $e';
      });
    }
  }

  Future<void> _recordVideo() async {
    setState(() {
      _errorMessage = null;
    });

    try {
      final XFile? video = await _picker.pickVideo(
        source: ImageSource.camera,
        maxDuration: const Duration(minutes: 5),
      );

      if (video == null) {
        return; // User cancelled
      }

      await _processSelectedVideo(video.path);
    } catch (e) {
      setState(() {
        _errorMessage = 'Không thể quay video: $e';
      });
    }
  }

  Future<void> _processSelectedVideo(String videoPath) async {
    setState(() {
      _isLoading = true;
    });

    try {
      // Get video info
      final videoService = VideoProcessingService();
      final videoInfo = await videoService.getVideoInfo(videoPath);

      if (videoInfo == null) {
        setState(() {
          _isLoading = false;
          _errorMessage = 'Không thể đọc thông tin video';
        });
        return;
      }

      if (!mounted) return;

      setState(() {
        _isLoading = false;
      });

      // Navigate to trimmer screen
      final result = await Navigator.of(context).push<Map<String, dynamic>>(
        MaterialPageRoute(
          builder: (_) => VideoTrimmerScreen(
            videoPath: videoPath,
            videoDuration: videoInfo.durationSeconds,
          ),
        ),
      );

      if (result != null && mounted) {
        // Return result to caller
        Navigator.of(context).pop(result);
      }
    } catch (e) {
      setState(() {
        _isLoading = false;
        _errorMessage = 'Lỗi xử lý video: $e';
      });
    }
  }
}
