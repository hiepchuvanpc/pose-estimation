import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:video_player/video_player.dart';

import '../../shared/theme/app_colors.dart';
import 'exercise_form_screen.dart';

/// Screen để cắt video với timeline kéo thả
class VideoTrimmerScreen extends ConsumerStatefulWidget {
  final String videoPath;
  final double videoDuration;

  const VideoTrimmerScreen({
    super.key,
    required this.videoPath,
    required this.videoDuration,
  });

  @override
  ConsumerState<VideoTrimmerScreen> createState() => _VideoTrimmerScreenState();
}

class _VideoTrimmerScreenState extends ConsumerState<VideoTrimmerScreen> {
  late VideoPlayerController _controller;
  bool _isInitialized = false;
  bool _isPlaying = false;
  bool _isTrimming = false;

  // Trim range (in seconds)
  late double _startTime;
  late double _endTime;
  double _currentPosition = 0;

  @override
  void initState() {
    super.initState();
    _startTime = 0;
    _endTime = widget.videoDuration;
    _initializeVideo();
  }

  Future<void> _initializeVideo() async {
    _controller = VideoPlayerController.file(File(widget.videoPath));
    
    try {
      await _controller.initialize();
      _controller.addListener(_videoListener);
      
      setState(() {
        _isInitialized = true;
        _endTime = _controller.value.duration.inMilliseconds / 1000.0;
      });
    } catch (e) {
      debugPrint('Error initializing video: $e');
    }
  }

  void _videoListener() {
    if (!mounted) return;
    
    final position = _controller.value.position.inMilliseconds / 1000.0;
    
    setState(() {
      _currentPosition = position;
      _isPlaying = _controller.value.isPlaying;
    });

    // Loop within trim range
    if (position >= _endTime && _isPlaying) {
      _controller.seekTo(Duration(milliseconds: (_startTime * 1000).toInt()));
    }
  }

  @override
  void dispose() {
    _controller.removeListener(_videoListener);
    _controller.dispose();
    super.dispose();
  }

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
                child: _isInitialized
                    ? _buildContent()
                    : const Center(
                        child: CircularProgressIndicator(color: AppColors.primary),
                      ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildHeader() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
      child: Row(
        children: [
          IconButton(
            onPressed: _isTrimming ? null : () => Navigator.pop(context),
            icon: const Icon(Icons.close, color: Colors.white),
          ),
          Expanded(
            child: Text(
              'Cắt video',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.bold,
                    color: Colors.white,
                  ),
            ),
          ),
          IconButton(
            onPressed: _isTrimming ? null : _confirmTrim,
            icon: Icon(
              Icons.check,
              color: _isTrimming ? AppColors.textSecondary : AppColors.success,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildContent() {
    return Column(
      children: [
        // Video preview
        Expanded(
          flex: 3,
          child: _buildVideoPreview(),
        ),

        // Trim info
        _buildTrimInfo(),

        // Timeline
        _buildTimeline(),

        // Playback controls
        _buildPlaybackControls(),

        // Trim button
        _buildTrimButton(),
      ],
    );
  }

  Widget _buildVideoPreview() {
    return Container(
      margin: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.black,
        borderRadius: BorderRadius.circular(16),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(16),
        child: Stack(
          alignment: Alignment.center,
          children: [
            AspectRatio(
              aspectRatio: _controller.value.aspectRatio,
              child: VideoPlayer(_controller),
            ),
            
            // Play/Pause overlay
            if (!_isPlaying)
              GestureDetector(
                onTap: _togglePlay,
                child: Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: Colors.black.withValues(alpha: 0.5),
                    shape: BoxShape.circle,
                  ),
                  child: const Icon(
                    Icons.play_arrow,
                    size: 48,
                    color: Colors.white,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildTrimInfo() {
    final trimDuration = _endTime - _startTime;
    
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          _buildTimeChip(
            label: 'Bắt đầu',
            time: _startTime,
            color: AppColors.success,
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            decoration: BoxDecoration(
              color: AppColors.primary.withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(20),
            ),
            child: Text(
              'Độ dài: ${_formatTime(trimDuration)}',
              style: const TextStyle(
                color: AppColors.primary,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
          _buildTimeChip(
            label: 'Kết thúc',
            time: _endTime,
            color: AppColors.error,
          ),
        ],
      ),
    );
  }

  Widget _buildTimeChip({
    required String label,
    required double time,
    required Color color,
  }) {
    return Column(
      children: [
        Text(
          label,
          style: TextStyle(
            fontSize: 10,
            color: color.withValues(alpha: 0.7),
          ),
        ),
        const SizedBox(height: 4),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.15),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: color.withValues(alpha: 0.3)),
          ),
          child: Text(
            _formatTime(time),
            style: TextStyle(
              color: color,
              fontWeight: FontWeight.bold,
              fontFamily: 'monospace',
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildTimeline() {
    return Container(
      margin: const EdgeInsets.all(16),
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final totalWidth = constraints.maxWidth;
          final duration = widget.videoDuration;
          
          // Calculate positions
          final startX = ((_startTime / duration) * totalWidth).clamp(0.0, totalWidth);
          final endX = ((_endTime / duration) * totalWidth).clamp(0.0, totalWidth);
          final currentX = ((_currentPosition / duration) * totalWidth).clamp(0.0, totalWidth);

          return Column(
            children: [
              // Current time display
              Text(
                _formatTime(_currentPosition),
                style: const TextStyle(
                  color: AppColors.textSecondary,
                  fontFamily: 'monospace',
                ),
              ),
              const SizedBox(height: 8),
              
              // Timeline
              SizedBox(
                height: 60,
                child: Stack(
                  children: [
                    // Background track
                    Positioned(
                      left: 0,
                      right: 0,
                      top: 20,
                      child: Container(
                        height: 20,
                        decoration: BoxDecoration(
                          color: AppColors.surfaceLight,
                          borderRadius: BorderRadius.circular(4),
                        ),
                      ),
                    ),

                    // Selected range
                    Positioned(
                      left: startX,
                      width: (endX - startX).clamp(0.0, totalWidth),
                      top: 20,
                      child: Container(
                        height: 20,
                        decoration: BoxDecoration(
                          color: AppColors.primary.withValues(alpha: 0.5),
                          borderRadius: BorderRadius.circular(4),
                        ),
                      ),
                    ),

                    // Current position indicator
                    Positioned(
                      left: currentX - 1,
                      top: 10,
                      child: Container(
                        width: 2,
                        height: 40,
                        color: Colors.white,
                      ),
                    ),

                    // Start handle
                    Positioned(
                      left: startX - 12,
                      top: 12,
                      child: GestureDetector(
                        onHorizontalDragUpdate: (details) {
                          _onStartHandleDrag(details, totalWidth, duration);
                        },
                        onHorizontalDragEnd: (_) {
                          _seekToStart();
                        },
                        child: _buildHandle(AppColors.success),
                      ),
                    ),

                    // End handle
                    Positioned(
                      left: endX - 12,
                      top: 12,
                      child: GestureDetector(
                        onHorizontalDragUpdate: (details) {
                          _onEndHandleDrag(details, totalWidth, duration);
                        },
                        onHorizontalDragEnd: (_) {},
                        child: _buildHandle(AppColors.error),
                      ),
                    ),
                  ],
                ),
              ),
              
              // Time markers
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    '0:00',
                    style: TextStyle(
                      fontSize: 10,
                      color: AppColors.textSecondary.withValues(alpha: 0.7),
                    ),
                  ),
                  Text(
                    _formatTime(duration),
                    style: TextStyle(
                      fontSize: 10,
                      color: AppColors.textSecondary.withValues(alpha: 0.7),
                    ),
                  ),
                ],
              ),
            ],
          );
        },
      ),
    );
  }

  Widget _buildHandle(Color color) {
    return Container(
      width: 24,
      height: 36,
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(6),
        boxShadow: [
          BoxShadow(
            color: color.withValues(alpha: 0.4),
            blurRadius: 8,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: const Icon(
        Icons.drag_handle,
        color: Colors.white,
        size: 16,
      ),
    );
  }

  Widget _buildPlaybackControls() {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        IconButton(
          onPressed: _seekToStart,
          icon: const Icon(Icons.skip_previous, color: Colors.white),
        ),
        const SizedBox(width: 16),
        IconButton(
          onPressed: _seekBackward,
          icon: const Icon(Icons.replay_10, color: Colors.white),
        ),
        const SizedBox(width: 16),
        Container(
          decoration: BoxDecoration(
            color: AppColors.primary,
            shape: BoxShape.circle,
          ),
          child: IconButton(
            onPressed: _togglePlay,
            icon: Icon(
              _isPlaying ? Icons.pause : Icons.play_arrow,
              color: Colors.white,
              size: 32,
            ),
          ),
        ),
        const SizedBox(width: 16),
        IconButton(
          onPressed: _seekForward,
          icon: const Icon(Icons.forward_10, color: Colors.white),
        ),
        const SizedBox(width: 16),
        IconButton(
          onPressed: _seekToEnd,
          icon: const Icon(Icons.skip_next, color: Colors.white),
        ),
      ],
    );
  }

  Widget _buildTrimButton() {
    final trimDuration = _endTime - _startTime;
    final isValidDuration = trimDuration >= 1.0; // Minimum 1 second

    return Padding(
      padding: const EdgeInsets.all(20),
      child: SizedBox(
        width: double.infinity,
        height: 56,
        child: ElevatedButton(
          onPressed: _isTrimming || !isValidDuration ? null : _confirmTrim,
          style: ElevatedButton.styleFrom(
            backgroundColor: AppColors.primary,
            foregroundColor: Colors.white,
            disabledBackgroundColor: AppColors.surfaceLight,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(16),
            ),
          ),
          child: _isTrimming
              ? const Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                        color: Colors.white,
                        strokeWidth: 2,
                      ),
                    ),
                    SizedBox(width: 12),
                    Text('Đang cắt video...'),
                  ],
                )
              : Text(
                  isValidDuration
                      ? 'Tiếp tục với đoạn ${_formatTime(trimDuration)}'
                      : 'Chọn ít nhất 1 giây',
                ),
        ),
      ),
    );
  }

  void _onStartHandleDrag(DragUpdateDetails details, double totalWidth, double duration) {
    final delta = details.delta.dx;
    final timeDelta = (delta / totalWidth) * duration;
    
    setState(() {
      _startTime = (_startTime + timeDelta).clamp(0.0, _endTime - 0.5);
    });
  }

  void _onEndHandleDrag(DragUpdateDetails details, double totalWidth, double duration) {
    final delta = details.delta.dx;
    final timeDelta = (delta / totalWidth) * duration;
    
    setState(() {
      _endTime = (_endTime + timeDelta).clamp(_startTime + 0.5, duration);
    });
  }

  void _togglePlay() {
    if (_isPlaying) {
      _controller.pause();
    } else {
      // If at or past end, start from beginning of trim
      if (_currentPosition >= _endTime || _currentPosition < _startTime) {
        _controller.seekTo(Duration(milliseconds: (_startTime * 1000).toInt()));
      }
      _controller.play();
    }
  }

  void _seekToStart() {
    _controller.seekTo(Duration(milliseconds: (_startTime * 1000).toInt()));
  }

  void _seekToEnd() {
    _controller.seekTo(Duration(milliseconds: ((_endTime - 0.1) * 1000).toInt()));
  }

  void _seekBackward() {
    final newPos = (_currentPosition - 0.5).clamp(_startTime, _endTime);
    _controller.seekTo(Duration(milliseconds: (newPos * 1000).toInt()));
  }

  void _seekForward() {
    final newPos = (_currentPosition + 0.5).clamp(_startTime, _endTime);
    _controller.seekTo(Duration(milliseconds: (newPos * 1000).toInt()));
  }

  Future<void> _confirmTrim() async {
    setState(() {
      _isTrimming = true;
    });

    try {
      // Navigate to exercise form with trim data
      final result = await Navigator.of(context).push<Map<String, dynamic>>(
        MaterialPageRoute(
          builder: (_) => ExerciseFormScreen(
            videoPath: widget.videoPath,
            startTime: _startTime,
            endTime: _endTime,
          ),
        ),
      );

      if (!mounted) return;

      setState(() {
        _isTrimming = false;
      });

      if (result != null) {
        // Pass result back
        Navigator.of(context).pop(result);
      }
    } catch (e) {
      setState(() {
        _isTrimming = false;
      });
      
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Lỗi: $e'),
          backgroundColor: AppColors.error,
        ),
      );
    }
  }

  String _formatTime(double seconds) {
    final mins = (seconds ~/ 60).toString().padLeft(2, '0');
    final secs = (seconds % 60).toStringAsFixed(1).padLeft(4, '0');
    return '$mins:$secs';
  }
}
