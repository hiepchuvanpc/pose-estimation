import 'dart:async';

/// Debouncer để tránh spam calls
class Debouncer {
  final Duration delay;
  Timer? _timer;

  Debouncer({this.delay = const Duration(milliseconds: 300)});

  /// Run action sau delay
  void run(void Function() action) {
    _timer?.cancel();
    _timer = Timer(delay, action);
  }

  /// Cancel pending action
  void cancel() {
    _timer?.cancel();
    _timer = null;
  }

  /// Dispose
  void dispose() {
    cancel();
  }
}

/// Throttler để giới hạn tần suất calls
class Throttler {
  final Duration interval;
  DateTime? _lastRun;
  Timer? _pendingTimer;

  Throttler({this.interval = const Duration(milliseconds: 100)});

  /// Run action với throttling
  void run(void Function() action) {
    final now = DateTime.now();
    
    if (_lastRun == null || now.difference(_lastRun!) >= interval) {
      _lastRun = now;
      action();
    } else {
      // Schedule for end of interval
      _pendingTimer?.cancel();
      final remaining = interval - now.difference(_lastRun!);
      _pendingTimer = Timer(remaining, () {
        _lastRun = DateTime.now();
        action();
      });
    }
  }

  /// Cancel pending action
  void cancel() {
    _pendingTimer?.cancel();
    _pendingTimer = null;
  }

  void dispose() {
    cancel();
  }
}

/// Rate limiter với max calls per time window
class RateLimiter {
  final int maxCalls;
  final Duration window;
  final List<DateTime> _calls = [];

  RateLimiter({
    this.maxCalls = 10,
    this.window = const Duration(seconds: 1),
  });

  /// Check if call is allowed
  bool tryCall() {
    final now = DateTime.now();
    final windowStart = now.subtract(window);
    
    // Remove old calls outside window
    _calls.removeWhere((call) => call.isBefore(windowStart));
    
    if (_calls.length >= maxCalls) {
      return false;
    }
    
    _calls.add(now);
    return true;
  }

  /// Time until next call allowed (null if allowed now)
  Duration? timeUntilNextCall() {
    if (_calls.length < maxCalls) return null;
    
    final now = DateTime.now();
    final windowStart = now.subtract(window);
    final oldestInWindow = _calls.firstWhere(
      (call) => call.isAfter(windowStart),
      orElse: () => now,
    );
    
    return oldestInWindow.add(window).difference(now);
  }
}
