import 'dart:math' as math;

/// Running min/max normalizer for raw signal.
///
/// Port of Python exercise_tracking.py SignalNormalizer.
class SignalNormalizer {
  double _min = 1.0;
  double _max = 0.0;
  int _count = 0;
  final int _warmup;

  SignalNormalizer({int warmup = 10}) : _warmup = warmup;

  double normalize(double raw) {
    final s = raw.clamp(0.0, 1.0);
    _min = math.min(_min, s);
    _max = math.max(_max, s);
    _count++;

    if (_count < _warmup) return s;

    final span = _max - _min;
    if (span < 0.08) return s;

    return ((s - _min) / span).clamp(0.0, 1.0);
  }

  void reset() {
    _min = 1.0;
    _max = 0.0;
    _count = 0;
  }
}

/// Rep counter with hysteresis state machine.
///
/// Port of Python exercise_tracking.py RepCounter.
class RepCounter {
  final double highEnter;
  final double lowExit;
  final int minHighFrames;
  final int minRepDurationMs;

  int repCount = 0;
  final SignalNormalizer normalizer;
  String _state = 'down'; // 'down' or 'up'
  int _highFrames = 0;
  int _lastRepTs = 0;

  RepCounter({
    this.highEnter = 0.72,
    this.lowExit = 0.38,
    this.minHighFrames = 1,
    this.minRepDurationMs = 500,
    SignalNormalizer? normalizer,
  }) : normalizer = normalizer ?? SignalNormalizer();

  /// Update with new signal value. Returns current rep count.
  int update(double signal, {int timestampMs = 0}) {
    final s = normalizer.normalize(signal);

    if (_state == 'down') {
      if (s >= highEnter) {
        _highFrames++;
        if (_highFrames >= minHighFrames) {
          _state = 'up';
          _highFrames = 0;
        }
      } else {
        _highFrames = 0;
      }
    } else {
      if (s <= lowExit) {
        final elapsed = timestampMs - _lastRepTs;
        if (elapsed >= minRepDurationMs || _lastRepTs == 0) {
          repCount++;
          _lastRepTs = timestampMs;
        }
        _state = 'down';
      }
    }

    return repCount;
  }

  /// Whether the counter is in the "up" (high) phase.
  bool get isUp => _state == 'up';

  /// Whether tracking has started (any movement detected).
  bool get hasStarted => repCount > 0 || _highFrames > 0 || _state == 'up';

  void reset() {
    repCount = 0;
    _state = 'down';
    _highFrames = 0;
    _lastRepTs = 0;
    normalizer.reset();
  }
}
