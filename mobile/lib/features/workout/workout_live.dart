import 'dart:async';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_mlkit_pose_detection/google_mlkit_pose_detection.dart';

import '../../core/models/template.dart';
import '../../core/services/feature_engine.dart';
import '../../core/services/hold_timer.dart';
import '../../core/services/pose_service.dart';
import '../../core/services/rep_counter.dart';
import '../../core/services/signal_engine.dart';
import '../../core/services/tts_service.dart';
import '../../core/utils/math_utils.dart';
import '../../presentation/providers/api_provider.dart';
import '../../shared/theme/app_colors.dart';
import 'widgets/pose_overlay.dart';
import 'widgets/progress_ring.dart';
import 'workout_result.dart';

/// Màn hình tập luyện realtime: camera + pose detection + tracking.
class WorkoutLiveScreen extends ConsumerStatefulWidget {
  final String sessionId;
  final WorkoutTemplate template;
  final TemplateProfile? profile;

  const WorkoutLiveScreen({
    super.key,
    required this.sessionId,
    required this.template,
    this.profile,
  });

  @override
  ConsumerState<WorkoutLiveScreen> createState() => _WorkoutLiveScreenState();
}

class _WorkoutLiveScreenState extends ConsumerState<WorkoutLiveScreen>
    with WidgetsBindingObserver {
  // Camera
  CameraController? _cameraController;
  bool _isCameraInitialized = false;
  List<CameraDescription> _cameras = [];

  // Pose detection
  final PoseService _poseService = PoseService();
  Map<PoseLandmarkType, PoseLandmark>? _currentLandmarks;
  double _coreVisibility = 0.0;

  // On-device engines
  SignalEngine? _signalEngine;
  RepCounter? _repCounter;
  HoldTimer? _holdTimer;

  // TTS
  final TtsService _ttsService = TtsService();

  // State
  int _repCount = 0;
  double _holdSeconds = 0.0;
  double _currentSignal = 0.0;
  String _phase = 'waiting_readiness';
  List<String> _announcements = [];
  bool _trackingStarted = false;
  bool _pendingConfirmation = false;
  bool _isDone = false;
  int _targetReps = 0;
  double _targetSeconds = 0;
  int _stepIndex = 0;
  int _setIndex = 0;
  String? _exerciseName;

  // Timing
  int _frameTimestampMs = 0;
  int _sessionStartMs = 0;

  // Frame throttle
  bool _processingFrame = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]);
    _sessionStartMs = DateTime.now().millisecondsSinceEpoch;
    _exerciseName = widget.template.name;

    _initEngines();
    _initCamera();
    _ttsService.initialize();
  }

  void _initEngines() {
    _poseService.initialize();

    if (widget.profile != null) {
      _signalEngine = SignalEngine(widget.profile!);

      // Build rep counter with adaptive thresholds from profile
      final adaptive = widget.profile!.adaptiveThresholds;
      final tracking =
          adaptive['tracking'] is Map ? adaptive['tracking'] as Map : {};

      if (widget.template.mode == 'reps') {
        _repCounter = RepCounter(
          highEnter: clamp(
              _getDouble(tracking, 'rep_high_enter',
                  _getDouble(adaptive, 'rep_high_enter', 0.72)),
              0.5,
              0.95),
          lowExit: clamp(
              _getDouble(tracking, 'rep_low_exit',
                  _getDouble(adaptive, 'rep_low_exit', 0.38)),
              0.05,
              0.9),
          minHighFrames: (_getDouble(tracking, 'rep_min_high_frames',
                  _getDouble(adaptive, 'rep_min_high_frames', 1)))
              .toInt(),
        );
      } else {
        _holdTimer = HoldTimer(
          holdThreshold: clamp(
              _getDouble(tracking, 'hold_threshold',
                  _getDouble(adaptive, 'hold_threshold', 0.55)),
              0.2,
              0.95),
          stopThreshold: clamp(
              _getDouble(tracking, 'hold_stop_threshold',
                  _getDouble(adaptive, 'hold_stop_threshold', 0.45)),
              0.05,
              0.9),
        );
      }
    }
  }

  static double _getDouble(Map? map, String key, double fallback) {
    if (map == null) return fallback;
    final v = map[key];
    if (v is num) return v.toDouble();
    return fallback;
  }

  Future<void> _initCamera() async {
    _cameras = await availableCameras();
    if (_cameras.isEmpty) return;

    // Prefer front camera for workout
    final frontCamera = _cameras.firstWhere(
      (c) => c.lensDirection == CameraLensDirection.front,
      orElse: () => _cameras.first,
    );

    _cameraController = CameraController(
      frontCamera,
      ResolutionPreset.medium, // Balance quality vs performance
      enableAudio: false,
      imageFormatGroup: ImageFormatGroup.nv21,
    );

    try {
      await _cameraController!.initialize();
      if (mounted) {
        setState(() => _isCameraInitialized = true);
        _startFrameProcessing();
      }
    } catch (e) {
      debugPrint('Camera init error: $e');
    }
  }

  void _startFrameProcessing() {
    _cameraController?.startImageStream((image) {
      if (!_processingFrame && !_isDone) {
        _processingFrame = true;
        _processFrame(image);
      }
    });
  }

  Future<void> _processFrame(CameraImage image) async {
    try {
      _frameTimestampMs =
          DateTime.now().millisecondsSinceEpoch - _sessionStartMs;

      // Convert CameraImage to InputImage
      final camera = _cameras.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.front,
        orElse: () => _cameras.first,
      );

      final inputImage = _convertCameraImage(image, camera);
      if (inputImage == null) {
        _processingFrame = false;
        return;
      }

      // Run on-device pose detection
      final poseResult = await _poseService.processFrame(inputImage);

      if (poseResult == null || !mounted) {
        _processingFrame = false;
        return;
      }

      // Update pose overlay
      setState(() {
        _currentLandmarks = poseResult.rawLandmarks;
        _coreVisibility = poseResult.coreVisibility;
      });

      // Compute signal on-device
      if (_signalEngine != null && poseResult.coreVisibility > 0.4) {
        final features = FeatureEngine.fromLandmarkPositions(poseResult.landmarks);
        final signalResult = _signalEngine!.computeSignal(features);

        setState(() => _currentSignal = signalResult.signal);

        // On-device tracking
        if (widget.template.mode == 'reps' && _repCounter != null) {
          final newReps = _repCounter!.update(signalResult.signal,
              timestampMs: _frameTimestampMs);
          if (newReps > _repCount) {
            _ttsService.speak('Rep $newReps', priority: 3);
          }
          setState(() {
            _repCount = newReps;
            _trackingStarted = _repCounter!.hasStarted;
          });
        } else if (_holdTimer != null) {
          final newHold =
              _holdTimer!.update(signalResult.signal, _frameTimestampMs);
          setState(() {
            _holdSeconds = newHold;
            _trackingStarted = newHold > 0;
          });
        }

        // Also send to backend for orchestration
        _sendFrameToBackend(signalResult.signal);
      }
    } catch (e) {
      debugPrint('Frame processing error: $e');
    } finally {
      _processingFrame = false;
    }
  }

  InputImage? _convertCameraImage(CameraImage image, CameraDescription camera) {
    try {
      final planes = image.planes;
      if (planes.isEmpty) return null;

      final metadata = InputImageMetadata(
        size: Size(image.width.toDouble(), image.height.toDouble()),
        rotation: _rotationFromSensorOrientation(camera.sensorOrientation),
        format: InputImageFormat.nv21,
        bytesPerRow: planes.first.bytesPerRow,
      );

      return InputImage.fromBytes(
        bytes: planes.first.bytes,
        metadata: metadata,
      );
    } catch (_) {
      return null;
    }
  }

  InputImageRotation _rotationFromSensorOrientation(int sensorOrientation) {
    switch (sensorOrientation) {
      case 0:
        return InputImageRotation.rotation0deg;
      case 90:
        return InputImageRotation.rotation90deg;
      case 180:
        return InputImageRotation.rotation180deg;
      case 270:
        return InputImageRotation.rotation270deg;
      default:
        return InputImageRotation.rotation0deg;
    }
  }

  Future<void> _sendFrameToBackend(double signal) async {
    try {
      final api = ref.read(apiClientProvider);
      final progress = await api.sendWorkoutFrame(
        sessionId: widget.sessionId,
        signal: signal,
        timestampMs: _frameTimestampMs,
        readinessPassed: _coreVisibility > 0.5,
      );

      if (progress != null && mounted) {
        setState(() {
          _phase = progress.phase;
          _pendingConfirmation = progress.pendingConfirmation;
          _isDone = progress.done;
          _stepIndex = progress.stepIndex;
          _setIndex = progress.setIndex;
          _targetReps = progress.targetReps ?? 0;
          _targetSeconds = progress.targetSeconds ?? 0;
          _exerciseName = progress.exerciseName ?? widget.template.name;

          if (progress.announcements.isNotEmpty) {
            _announcements = progress.announcements;
            for (final msg in progress.announcements) {
              _ttsService.speak(msg, priority: 2);
            }
          }
        });

        if (_isDone) {
          _finishWorkout();
        }
      }
    } catch (_) {
      // Network errors are non-fatal — on-device tracking continues
    }
  }

  Future<void> _confirmAction() async {
    final api = ref.read(apiClientProvider);
    final progress = await api.confirmWorkout(widget.sessionId);
    if (progress != null && mounted) {
      // Reset on-device counters for new set/exercise
      _repCounter?.reset();
      _holdTimer?.reset();

      setState(() {
        _repCount = 0;
        _holdSeconds = 0.0;
        _phase = progress.phase;
        _pendingConfirmation = progress.pendingConfirmation;
        _isDone = progress.done;
        _announcements = progress.announcements;
      });

      for (final msg in progress.announcements) {
        _ttsService.speak(msg, priority: 2);
      }
    }
  }

  Future<void> _finishWorkout() async {
    await _cameraController?.stopImageStream();

    if (!mounted) return;
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(
        builder: (_) => WorkoutResultScreen(
          sessionId: widget.sessionId,
          templateName: widget.template.name,
        ),
      ),
    );
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.inactive) {
      _cameraController?.stopImageStream();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _cameraController?.dispose();
    _poseService.dispose();
    _ttsService.dispose();
    SystemChrome.setPreferredOrientations(DeviceOrientation.values);
    super.dispose();
  }

  // ===================== BUILD =====================

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      body: Stack(
        children: [
          // Camera preview
          if (_isCameraInitialized && _cameraController != null)
            Positioned.fill(child: _buildCameraPreview())
          else
            const Center(
                child: CircularProgressIndicator(color: AppColors.primary)),

          // Status bar overlay (top)
          _buildTopOverlay(),

          // Progress overlay (bottom)
          _buildBottomOverlay(),

          // Announcements
          if (_announcements.isNotEmpty) _buildAnnouncementBanner(),

          // Confirmation dialog
          if (_pendingConfirmation) _buildConfirmationOverlay(),
        ],
      ),
    );
  }

  Widget _buildCameraPreview() {
    return Stack(
      fit: StackFit.expand,
      children: [
        CameraPreview(_cameraController!),
        // Pose overlay
        if (_currentLandmarks != null)
          PoseOverlay(
            landmarks: _currentLandmarks,
            imageSize: Size(
              _cameraController!.value.previewSize!.height,
              _cameraController!.value.previewSize!.width,
            ),
            widgetSize: MediaQuery.of(context).size,
            isFrontCamera: true,
            coreVisibility: _coreVisibility,
          ),
      ],
    );
  }

  Widget _buildTopOverlay() {
    return Positioned(
      top: 0,
      left: 0,
      right: 0,
      child: Container(
        padding: EdgeInsets.fromLTRB(
          16,
          MediaQuery.of(context).padding.top + 8,
          16,
          12,
        ),
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [
              Colors.black.withValues(alpha: 0.7),
              Colors.transparent,
            ],
          ),
        ),
        child: Row(
          children: [
            // Back button
            IconButton(
              icon: const Icon(Icons.close, color: Colors.white, size: 26),
              onPressed: () => _showExitDialog(),
            ),
            const SizedBox(width: 8),
            // Exercise name + phase
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    _exerciseName ?? widget.template.name,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  Text(
                    'Set ${_setIndex + 1} • Step ${_stepIndex + 1} • ${_phaseLabel(_phase)}',
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.7),
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
            ),
            // Readiness indicator
            _buildReadinessIndicator(),
          ],
        ),
      ),
    );
  }

  Widget _buildReadinessIndicator() {
    Color color;
    String label;
    if (_coreVisibility > 0.7) {
      color = AppColors.readinessGood;
      label = _trackingStarted ? 'Tracking' : 'Tốt';
    } else if (_coreVisibility > 0.4) {
      color = AppColors.readinessWarn;
      label = 'Ổn';
    } else {
      color = AppColors.readinessBad;
      label = 'Yếu';
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.2),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              color: color,
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: 6),
          Text(
            label,
            style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }

  Widget _buildBottomOverlay() {
    final isReps = widget.template.mode == 'reps';

    return Positioned(
      bottom: 0,
      left: 0,
      right: 0,
      child: Container(
        padding: EdgeInsets.fromLTRB(
          20,
          20,
          20,
          MediaQuery.of(context).padding.bottom + 20,
        ),
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.bottomCenter,
            end: Alignment.topCenter,
            colors: [
              Colors.black.withValues(alpha: 0.85),
              Colors.black.withValues(alpha: 0.3),
              Colors.transparent,
            ],
          ),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Signal bar
            _buildSignalBar(),
            const SizedBox(height: 16),

            // Progress ring
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                ProgressRing(
                  progress: isReps
                      ? (_targetReps > 0 ? _repCount / _targetReps : 0)
                      : (_targetSeconds > 0
                          ? _holdSeconds / _targetSeconds
                          : 0),
                  centerText: isReps
                      ? '$_repCount'
                      : '${_holdSeconds.toInt()}s',
                  subtitleText: isReps
                      ? 'của $_targetReps rep'
                      : 'của ${_targetSeconds.toInt()}s',
                  size: 140,
                ),
              ],
            ),
            const SizedBox(height: 16),

            // End workout button
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: _showEndWorkoutDialog,
                icon: const Icon(Icons.stop, size: 20),
                label: const Text('Kết thúc buổi tập'),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.error,
                  side: BorderSide(
                      color: AppColors.error.withValues(alpha: 0.4)),
                  padding: const EdgeInsets.symmetric(vertical: 12),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSignalBar() {
    return Column(
      children: [
        Row(
          children: [
            Text('Tín hiệu',
                style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.6), fontSize: 11)),
            const Spacer(),
            Text('${(_currentSignal * 100).toInt()}%',
                style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.6), fontSize: 11)),
          ],
        ),
        const SizedBox(height: 4),
        ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: LinearProgressIndicator(
            value: _currentSignal.clamp(0.0, 1.0),
            minHeight: 6,
            backgroundColor: AppColors.surfaceLight,
            valueColor:
                const AlwaysStoppedAnimation(AppColors.accent),
          ),
        ),
      ],
    );
  }

  Widget _buildAnnouncementBanner() {
    return Positioned(
      top: MediaQuery.of(context).padding.top + 70,
      left: 16,
      right: 16,
      child: AnimatedOpacity(
        opacity: _announcements.isNotEmpty ? 1.0 : 0.0,
        duration: const Duration(milliseconds: 300),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          decoration: BoxDecoration(
            color: AppColors.primary.withValues(alpha: 0.9),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Text(
            _announcements.join(' • '),
            style: const TextStyle(
              color: Colors.white,
              fontSize: 14,
              fontWeight: FontWeight.w600,
            ),
            textAlign: TextAlign.center,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
        ),
      ),
    );
  }

  Widget _buildConfirmationOverlay() {
    return Positioned.fill(
      child: Container(
        color: Colors.black54,
        child: Center(
          child: Container(
            margin: const EdgeInsets.symmetric(horizontal: 32),
            padding: const EdgeInsets.all(28),
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(24),
              border: Border.all(
                color: AppColors.primary.withValues(alpha: 0.3),
              ),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.check_circle_outline,
                    size: 56, color: AppColors.accent),
                const SizedBox(height: 16),
                Text(
                  'Đã hoàn thành!',
                  style: Theme.of(context).textTheme.headlineMedium,
                ),
                const SizedBox(height: 8),
                Text(
                  'Bấm tiếp tục khi bạn đã sẵn sàng',
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 24),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    onPressed: _confirmAction,
                    child: const Text('Tiếp tục',
                        style: TextStyle(fontSize: 16)),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  String _phaseLabel(String phase) {
    switch (phase) {
      case 'waiting_readiness':
        return 'Chờ tư thế';
      case 'active_set':
        return 'Đang tập';
      case 'rest_pending_confirmation':
        return 'Nghỉ giữa set';
      case 'exercise_pending_confirmation':
        return 'Chuyển bài';
      case 'done':
        return 'Hoàn tất';
      default:
        return phase;
    }
  }

  void _showExitDialog() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: const Text('Thoát buổi tập?'),
        content: const Text('Tiến trình hiện tại sẽ không được lưu.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Ở lại'),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(ctx);
              Navigator.pop(context);
            },
            child: const Text('Thoát',
                style: TextStyle(color: AppColors.error)),
          ),
        ],
      ),
    );
  }

  void _showEndWorkoutDialog() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: const Text('Kết thúc buổi tập?'),
        content: const Text(
            'Hệ thống sẽ phân tích kết quả tổng hợp sau khi kết thúc.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Tiếp tục tập'),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(ctx);
              _finishWorkout();
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.error,
            ),
            child: const Text('Kết thúc',
                style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
  }
}
