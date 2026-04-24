import 'dart:async';
import 'dart:io';

import 'package:battery_plus/battery_plus.dart';

/// Battery-aware performance optimizer
class PerformanceOptimizer {
  static final PerformanceOptimizer _instance = PerformanceOptimizer._internal();
  factory PerformanceOptimizer() => _instance;
  PerformanceOptimizer._internal();

  final Battery _battery = Battery();
  BatteryState _batteryState = BatteryState.unknown;
  int _batteryLevel = 100;
  
  StreamSubscription<BatteryState>? _stateSubscription;

  /// Initialize battery monitoring
  Future<void> initialize() async {
    try {
      _batteryLevel = await _battery.batteryLevel;
      _batteryState = await _battery.batteryState;
      
      _stateSubscription = _battery.onBatteryStateChanged.listen((state) {
        _batteryState = state;
        _updateBatteryLevel();
      });
    } catch (e) {
      // Battery not available (e.g., desktop)
      _batteryLevel = 100;
      _batteryState = BatteryState.full;
    }
  }

  Future<void> _updateBatteryLevel() async {
    try {
      _batteryLevel = await _battery.batteryLevel;
    } catch (_) {}
  }

  /// Get recommended processing quality
  ProcessingQuality getRecommendedQuality() {
    final isCharging = _batteryState == BatteryState.charging || 
                       _batteryState == BatteryState.full;
    
    if (isCharging || _batteryLevel > 50) {
      return ProcessingQuality.high;
    } else if (_batteryLevel > 20) {
      return ProcessingQuality.medium;
    } else {
      return ProcessingQuality.low;
    }
  }

  /// Get recommended frame rate for pose detection
  int getRecommendedFrameRate() {
    switch (getRecommendedQuality()) {
      case ProcessingQuality.high:
        return 30;
      case ProcessingQuality.medium:
        return 15;
      case ProcessingQuality.low:
        return 10;
    }
  }

  /// Should allow background sync?
  bool shouldAllowBackgroundSync() {
    return _batteryLevel > 20 || 
           _batteryState == BatteryState.charging ||
           _batteryState == BatteryState.full;
  }

  /// Should allow video processing?
  bool shouldAllowVideoProcessing() {
    return _batteryLevel > 15 || 
           _batteryState == BatteryState.charging;
  }

  /// Get frame skip count for pose detection
  int getFrameSkipCount() {
    switch (getRecommendedQuality()) {
      case ProcessingQuality.high:
        return 1; // Process every frame
      case ProcessingQuality.medium:
        return 2; // Skip every other frame
      case ProcessingQuality.low:
        return 3; // Process every 3rd frame
    }
  }

  /// Current battery level
  int get batteryLevel => _batteryLevel;

  /// Is device charging?
  bool get isCharging => _batteryState == BatteryState.charging ||
                         _batteryState == BatteryState.full;

  void dispose() {
    _stateSubscription?.cancel();
  }
}

enum ProcessingQuality {
  high,   // Full quality, 30 FPS
  medium, // Balanced, 15 FPS
  low,    // Power save, 10 FPS
}

/// Memory manager for video processing
class MemoryManager {
  static const int _maxMemoryMB = 200; // Max memory for video buffers
  
  int _currentUsageMB = 0;
  final List<WeakReference<Object>> _trackedObjects = [];

  /// Check if we can allocate more memory
  bool canAllocate(int sizeBytes) {
    final sizeMB = sizeBytes ~/ (1024 * 1024);
    return (_currentUsageMB + sizeMB) <= _maxMemoryMB;
  }

  /// Track memory allocation
  void track(Object object, int sizeBytes) {
    _trackedObjects.add(WeakReference(object));
    _currentUsageMB += sizeBytes ~/ (1024 * 1024);
  }

  /// Release tracked memory
  void release(int sizeBytes) {
    _currentUsageMB -= sizeBytes ~/ (1024 * 1024);
    if (_currentUsageMB < 0) _currentUsageMB = 0;
  }

  /// Cleanup dead references
  void cleanup() {
    _trackedObjects.removeWhere((ref) => ref.target == null);
  }

  /// Force garbage collection hint
  void requestGC() {
    cleanup();
    // Dart doesn't have explicit GC, but we can suggest it
  }

  int get currentUsageMB => _currentUsageMB;
  int get availableMB => _maxMemoryMB - _currentUsageMB;
}

/// Disk space checker
class DiskSpaceChecker {
  /// Check available disk space in bytes
  static Future<int> getAvailableSpace(String path) async {
    try {
      if (Platform.isAndroid || Platform.isIOS) {
        // Check if directory exists
        final dir = Directory(path);
        if (await dir.exists()) {
          // Note: Dart doesn't provide disk space API directly
          // In production, use platform channel for actual value
          return 500 * 1024 * 1024; // Return 500MB as default
        }
      }
      return 500 * 1024 * 1024;
    } catch (e) {
      return 0;
    }
  }

  /// Check if we have enough space for video recording
  static Future<bool> hasSpaceForRecording({
    int durationSeconds = 300,
    int bitrateKbps = 5000,
  }) async {
    // Estimate: bitrate * duration + 20% overhead
    final estimatedBytes = (bitrateKbps * 1024 / 8 * durationSeconds * 1.2).toInt();
    final available = await getAvailableSpace('/');
    return available > estimatedBytes;
  }

  /// Get human readable size
  static String formatBytes(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    if (bytes < 1024 * 1024 * 1024) {
      return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
    }
    return '${(bytes / (1024 * 1024 * 1024)).toStringAsFixed(1)} GB';
  }
}
