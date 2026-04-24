/// Hold timer for isometric exercises.
///
/// Port of Python exercise_tracking.py HoldTimer.
class HoldTimer {
  final double holdThreshold;
  final double stopThreshold;

  double holdSeconds = 0.0;
  bool active = false;
  int? _lastTimestampMs;

  HoldTimer({
    this.holdThreshold = 0.55,
    this.stopThreshold = 0.45,
  });

  /// Update with new signal value. Returns current hold seconds.
  double update(double signal, int timestampMs) {
    final s = signal.clamp(0.0, 1.0);
    final ts = timestampMs < 0 ? 0 : timestampMs;

    if (_lastTimestampMs == null) {
      _lastTimestampMs = ts;
      active = s >= holdThreshold;
      return holdSeconds;
    }

    final dtMs = (ts - _lastTimestampMs!).clamp(0, 60000); // max 60s gap
    _lastTimestampMs = ts;

    if (active) {
      if (s < stopThreshold) {
        active = false;
      } else {
        holdSeconds += dtMs / 1000.0;
      }
    } else if (s >= holdThreshold) {
      active = true;
    }

    return holdSeconds;
  }

  void reset() {
    holdSeconds = 0.0;
    active = false;
    _lastTimestampMs = null;
  }
}
