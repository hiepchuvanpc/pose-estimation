import 'dart:async';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_mlkit_pose_detection/google_mlkit_pose_detection.dart';

import '../../core/services/pose_service.dart';
import '../../core/utils/performance_optimizer.dart';
import '../../core/utils/rate_limiters.dart';
import '../../presentation/providers/workout_provider.dart';
import '../../shared/theme/app_colors.dart';
import 'workout_result_screen.dart';

/// Màn hình tập luyện chính với camera và pose overlay
class WorkoutScreen extends ConsumerStatefulWidget {
  final String lessonId;

  const WorkoutScreen({super.key, required this.lessonId});

  @override
  ConsumerState<WorkoutScreen> createState() => _WorkoutScreenState();
}

class _WorkoutScreenState extends ConsumerState<WorkoutScreen> {
  CameraController? _cameraController;
  List<CameraDescription>? _cameras;
  bool _isCameraInitialized = false;
  Timer? _countdownTimer;
  Timer? _holdTimer;
  int _holdSeconds = 0;

  // Pose detection  
  late PoseService _poseService;
  bool _isPoseProcessing = false;
  int _frameCount = 0;
  
  // Performance optimization
  late PerformanceOptimizer _performanceOptimizer;
  late Throttler _poseThrottler;
  int _frameSkipCount = 1;

  @override
  void initState() {
    super.initState();
    _initPerformanceOptimization();
    _initPoseService();
    _initializeWorkout();
    _setLandscapeLock();
  }

  void _initPerformanceOptimization() {
    _performanceOptimizer = PerformanceOptimizer();
    _performanceOptimizer.initialize();
    _frameSkipCount = _performanceOptimizer.getFrameSkipCount();
    
    // Throttle pose detection based on battery/performance
    final frameRate = _performanceOptimizer.getRecommendedFrameRate();
    _poseThrottler = Throttler(
      interval: Duration(milliseconds: 1000 ~/ frameRate),
    );
  }

  void _initPoseService() {
    _poseService = PoseService();
    _poseService.initialize();
  }

  void _setLandscapeLock() {
    // Khoá màn hình ngang cho workout
    SystemChrome.setPreferredOrientations([
      DeviceOrientation.landscapeLeft,
      DeviceOrientation.landscapeRight,
    ]);
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
  }

  void _resetOrientation() {
    SystemChrome.setPreferredOrientations([
      DeviceOrientation.portraitUp,
      DeviceOrientation.portraitDown,
    ]);
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
  }

  Future<void> _initializeWorkout() async {
    // Start workout session
    await ref.read(workoutSessionProvider.notifier).startWorkout(widget.lessonId);
    
    // Initialize camera
    await _initializeCamera();
    
    // Start countdown timer
    _startCountdownTimer();
  }

  Future<void> _initializeCamera() async {
    try {
      _cameras = await availableCameras();
      if (_cameras == null || _cameras!.isEmpty) return;

      // Sử dụng camera trước
      final frontCamera = _cameras!.firstWhere(
        (camera) => camera.lensDirection == CameraLensDirection.front,
        orElse: () => _cameras!.first,
      );

      // Chọn resolution dựa trên battery/performance
      final quality = _performanceOptimizer.getRecommendedQuality();
      final resolution = quality == ProcessingQuality.high
          ? ResolutionPreset.high
          : quality == ProcessingQuality.medium
              ? ResolutionPreset.medium
              : ResolutionPreset.low;

      _cameraController = CameraController(
        frontCamera,
        resolution,
        enableAudio: false,
        imageFormatGroup: ImageFormatGroup.nv21, // Best for ML Kit
      );

      await _cameraController!.initialize();
      
      // Start image stream for pose detection
      _startPoseDetection();
      
      if (mounted) {
        setState(() {
          _isCameraInitialized = true;
        });
      }
    } catch (e) {
      debugPrint('Error initializing camera: $e');
    }
  }

  void _startCountdownTimer() {
    _countdownTimer?.cancel();
    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      final state = ref.read(workoutSessionProvider);
      
      if (state.status == WorkoutStatus.preparing) {
        ref.read(workoutSessionProvider.notifier).decrementCountdown();
        
        // Khi countdown hết, bắt đầu tập
        final newState = ref.read(workoutSessionProvider);
        if (newState.status == WorkoutStatus.exercising) {
          // Nếu là bài hold, bắt đầu timer
          if (newState.currentExercise != null && !newState.currentExercise!.isReps) {
            _startHoldTimer();
          }
        }
      } else if (state.status == WorkoutStatus.resting) {
        ref.read(workoutSessionProvider.notifier).decrementRestCountdown();
        
        // Khi rest hết, chuẩn bị countdown
        final newState = ref.read(workoutSessionProvider);
        if (newState.status == WorkoutStatus.preparing) {
          // Countdown sẽ tự động chạy ở vòng lặp tiếp
        }
      } else if (state.status == WorkoutStatus.completed || 
                 state.status == WorkoutStatus.cancelled) {
        timer.cancel();
      }
    });
  }

  void _startHoldTimer() {
    _holdTimer?.cancel();
    _holdSeconds = 0;
    final targetSeconds = ref.read(workoutSessionProvider).currentExercise?.targetHoldSeconds ?? 30;

    _holdTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      setState(() {
        _holdSeconds++;
      });
      
      if (_holdSeconds >= targetSeconds) {
        timer.cancel();
        // Record hold complete với mock form score
        ref.read(workoutSessionProvider.notifier).recordHoldComplete(
          formScore: 85.0, // Mock score - sẽ thay bằng pose detection sau
        );
      }
    });
  }

  void _recordRep() {
    // Record rep với mock form score
    ref.read(workoutSessionProvider.notifier).recordRep(
      formScore: 80.0 + (10 * (0.5 - (DateTime.now().millisecondsSinceEpoch % 100) / 100)), // Mock random score
    );
  }

  /// Start pose detection với throttling
  void _startPoseDetection() {
    if (_cameraController == null || !_cameraController!.value.isInitialized) {
      return;
    }

    _cameraController!.startImageStream((CameraImage image) {
      _frameCount++;
      
      // Skip frames based on performance
      if (_frameCount % _frameSkipCount != 0) return;
      
      // Throttle processing
      _poseThrottler.run(() {
        _processCameraFrame(image);
      });
    });
  }

  /// Stop pose detection
  void _stopPoseDetection() {
    try {
      _cameraController?.stopImageStream();
    } catch (_) {}
  }

  /// Process a single camera frame
  Future<void> _processCameraFrame(CameraImage image) async {
    if (_isPoseProcessing) return;
    _isPoseProcessing = true;

    try {
      final inputImage = _convertCameraImage(image);
      if (inputImage == null) return;

      final poseResult = await _poseService.processFrame(inputImage);
      
      if (poseResult != null && mounted) {
        // Check visibility - only use if pose is clearly visible
        if (poseResult.coreVisibility > 0.6) {
          // TODO: Use pose for rep counting and form analysis
          // This is where SignalEngine would process the pose
        }
      }
    } catch (e) {
      debugPrint('Pose detection error: $e');
    } finally {
      _isPoseProcessing = false;
    }
  }

  /// Convert CameraImage to InputImage for ML Kit
  InputImage? _convertCameraImage(CameraImage image) {
    try {
      final camera = _cameras?.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.front,
        orElse: () => _cameras!.first,
      );
      
      if (camera == null) return null;

      final rotation = InputImageRotationValue.fromRawValue(
        camera.sensorOrientation,
      );
      if (rotation == null) return null;

      final format = InputImageFormatValue.fromRawValue(image.format.raw);
      if (format == null) return null;

      return InputImage.fromBytes(
        bytes: image.planes.first.bytes,
        metadata: InputImageMetadata(
          size: Size(image.width.toDouble(), image.height.toDouble()),
          rotation: rotation,
          format: format,
          bytesPerRow: image.planes.first.bytesPerRow,
        ),
      );
    } catch (e) {
      debugPrint('Error converting camera image: $e');
      return null;
    }
  }

  @override
  void dispose() {
    _stopPoseDetection();
    _countdownTimer?.cancel();
    _holdTimer?.cancel();
    _poseThrottler.dispose();
    _poseService.dispose();
    _cameraController?.dispose();
    _resetOrientation();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(workoutSessionProvider);

    // Navigate to result screen when completed
    if (state.status == WorkoutStatus.completed) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _resetOrientation();
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(
            builder: (_) => WorkoutResultScreen(
              sessionId: state.sessionId!,
              exercises: state.exercises,
            ),
          ),
        );
      });
    }

    return Scaffold(
      body: Stack(
        children: [
          // Camera preview
          _buildCameraPreview(),
          
          // Overlay UI
          _buildOverlay(state),
          
          // Status-specific UI
          if (state.status == WorkoutStatus.preparing)
            _buildCountdownOverlay(state),
          
          if (state.status == WorkoutStatus.resting)
            _buildRestOverlay(state),
        ],
      ),
    );
  }

  Widget _buildCameraPreview() {
    if (!_isCameraInitialized || _cameraController == null) {
      return Container(
        color: Colors.black,
        child: const Center(
          child: CircularProgressIndicator(color: AppColors.primary),
        ),
      );
    }

    return SizedBox.expand(
      child: FittedBox(
        fit: BoxFit.cover,
        child: SizedBox(
          width: _cameraController!.value.previewSize?.height ?? 100,
          height: _cameraController!.value.previewSize?.width ?? 100,
          child: CameraPreview(_cameraController!),
        ),
      ),
    );
  }

  Widget _buildOverlay(WorkoutSessionState state) {
    if (state.status == WorkoutStatus.preparing ||
        state.status == WorkoutStatus.resting) {
      return const SizedBox.shrink();
    }

    final currentEx = state.currentExercise;
    if (currentEx == null) return const SizedBox.shrink();

    return SafeArea(
      child: Container(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Top bar: Exercise info + close button
            Row(
              children: [
                // Close button
                IconButton(
                  onPressed: _showExitConfirmation,
                  icon: const Icon(Icons.close, color: Colors.white, size: 28),
                ),
                const SizedBox(width: 12),
                
                // Exercise name
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        currentEx.exercise.name,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 20,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      Text(
                        'Set ${currentEx.currentSet + 1}/${currentEx.targetSets}',
                        style: TextStyle(
                          color: Colors.white.withValues(alpha: 0.8),
                          fontSize: 14,
                        ),
                      ),
                    ],
                  ),
                ),
                
                // Progress indicator
                _buildProgressIndicator(state),
              ],
            ),
            
            const Spacer(),
            
            // Bottom: Rep counter or Hold timer + controls
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                // Rep/Hold info
                if (currentEx.isReps)
                  _buildRepCounter(currentEx)
                else
                  _buildHoldTimer(currentEx),
                
                // Manual rep button (for reps mode)
                if (currentEx.isReps)
                  _buildRepButton(),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildProgressIndicator(WorkoutSessionState state) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.fitness_center, color: AppColors.primary, size: 20),
          const SizedBox(width: 8),
          Text(
            '${state.currentExerciseIndex + 1}/${state.exercises.length}',
            style: const TextStyle(
              color: Colors.white,
              fontWeight: FontWeight.bold,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildRepCounter(WorkoutExerciseItem exercise) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text(
            'REPS',
            style: TextStyle(
              color: AppColors.textSecondary,
              fontSize: 12,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 4),
          RichText(
            text: TextSpan(
              children: [
                TextSpan(
                  text: '${exercise.currentRep}',
                  style: const TextStyle(
                    color: AppColors.primary,
                    fontSize: 48,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                TextSpan(
                  text: '/${exercise.targetReps}',
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.6),
                    fontSize: 24,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildHoldTimer(WorkoutExerciseItem exercise) {
    final targetSeconds = exercise.targetHoldSeconds;
    final progress = _holdSeconds / targetSeconds;

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text(
            'GIỮ',
            style: TextStyle(
              color: AppColors.textSecondary,
              fontSize: 12,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 8),
          SizedBox(
            width: 100,
            height: 100,
            child: Stack(
              alignment: Alignment.center,
              children: [
                CircularProgressIndicator(
                  value: progress.clamp(0.0, 1.0),
                  strokeWidth: 8,
                  backgroundColor: Colors.white.withValues(alpha: 0.2),
                  valueColor: const AlwaysStoppedAnimation<Color>(AppColors.primary),
                ),
                Text(
                  '${targetSeconds - _holdSeconds}s',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 28,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildRepButton() {
    return GestureDetector(
      onTap: _recordRep,
      child: Container(
        width: 100,
        height: 100,
        decoration: BoxDecoration(
          color: AppColors.primary,
          shape: BoxShape.circle,
          boxShadow: [
            BoxShadow(
              color: AppColors.primary.withValues(alpha: 0.4),
              blurRadius: 20,
              spreadRadius: 5,
            ),
          ],
        ),
        child: const Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.touch_app, color: Colors.white, size: 32),
              SizedBox(height: 4),
              Text(
                'TAP',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 14,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildCountdownOverlay(WorkoutSessionState state) {
    return Container(
      color: Colors.black.withValues(alpha: 0.7),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              state.currentExercise?.exercise.name ?? 'Chuẩn bị',
              style: const TextStyle(
                color: Colors.white,
                fontSize: 24,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 24),
            Container(
              width: 150,
              height: 150,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                border: Border.all(color: AppColors.primary, width: 4),
              ),
              child: Center(
                child: Text(
                  '${state.countdownSeconds}',
                  style: const TextStyle(
                    color: AppColors.primary,
                    fontSize: 72,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ),
            const SizedBox(height: 24),
            Text(
              state.countdownSeconds > 1 ? 'Chuẩn bị tư thế...' : 'Bắt đầu!',
              style: const TextStyle(
                color: AppColors.textSecondary,
                fontSize: 18,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildRestOverlay(WorkoutSessionState state) {
    final currentEx = state.currentExercise;
    final isLastExercise = state.isLastExercise;
    
    return Container(
      color: Colors.black.withValues(alpha: 0.8),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(
              Icons.check_circle,
              color: AppColors.accent,
              size: 64,
            ),
            const SizedBox(height: 16),
            Text(
              isLastExercise && currentEx?.isCompleted == true
                  ? 'Hoàn thành!'
                  : 'Nghỉ ngơi',
              style: const TextStyle(
                color: Colors.white,
                fontSize: 28,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 24),
            Container(
              width: 120,
              height: 120,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: AppColors.cardBackground,
              ),
              child: Center(
                child: Text(
                  '${state.restCountdownSeconds}',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 48,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ),
            const SizedBox(height: 16),
            if (!isLastExercise || currentEx?.isCompleted != true) ...[
              Text(
                'Bài tiếp: ${state.exercises.length > state.currentExerciseIndex + 1 ? state.exercises[state.currentExerciseIndex + 1].exercise.name : currentEx?.exercise.name}',
                style: const TextStyle(
                  color: AppColors.textSecondary,
                  fontSize: 16,
                ),
              ),
              const SizedBox(height: 24),
              ElevatedButton(
                onPressed: () {
                  ref.read(workoutSessionProvider.notifier).skipRest();
                },
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.primary,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 12),
                ),
                child: const Text('Bỏ qua'),
              ),
            ],
          ],
        ),
      ),
    );
  }

  void _showExitConfirmation() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.cardBackground,
        title: const Text(
          'Dừng tập luyện?',
          style: TextStyle(color: Colors.white),
        ),
        content: const Text(
          'Tiến trình sẽ không được lưu.',
          style: TextStyle(color: AppColors.textSecondary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Tiếp tục tập'),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(ctx);
              ref.read(workoutSessionProvider.notifier).cancelWorkout();
              Navigator.of(context).pop();
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
            child: const Text('Dừng'),
          ),
        ],
      ),
    );
  }
}
