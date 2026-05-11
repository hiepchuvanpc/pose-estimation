import 'dart:math' as math;

import '../models/template.dart';
import '../utils/math_utils.dart';

/// Computes phase signal and similarity from features using template profile.
///
/// Mirrors the signal computation in Python main.py:
///   signal = phase_weight * phase + similarity_weight * similarity
class SignalEngine {
  final TemplateProfile profile;

  late final double _phaseWeight;
  late final double _similarityWeight;
  late final double _distanceScale;

  SignalEngine(this.profile) {
    final adaptive = profile.adaptiveThresholds;
    final signal =
        adaptive['signal'] is Map ? adaptive['signal'] as Map : {};
    _phaseWeight = _getDouble(signal, 'phase_weight',
        _getDouble(adaptive, 'signal_phase_weight', 0.6));
    _similarityWeight = _getDouble(signal, 'similarity_weight',
        _getDouble(adaptive, 'signal_similarity_weight', 0.4));
    _distanceScale = clamp(
        _getDouble(signal, 'distance_scale',
            _getDouble(adaptive, 'similarity_distance_scale', 2.8)),
        0.5,
        8.0);
  }

  /// Compute phase signal [0..1] by PCA projection.
  double phaseSignal(List<double> feature) {
    if (profile.featureMean.isEmpty || profile.featurePc1.isEmpty) return 0.0;
    final mean = profile.featureMean;
    final pc1 = profile.featurePc1;
    final n = math.min(feature.length, math.min(mean.length, pc1.length));

    double proj = 0.0;
    for (int i = 0; i < n; i++) {
      proj += (feature[i] - mean[i]) * pc1[i];
    }

    final denom = math.max(1e-6, profile.projMax - profile.projMin);
    return clamp((proj - profile.projMin) / denom, 0.0, 1.0);
  }

  /// Feature similarity: exp(-dist / scale).
  double featureSimilarity(List<double> feature) {
    if (profile.featureMean.isEmpty) return 0.0;
    final dist = euclideanDistance(feature, profile.featureMean);
    return math.exp(-dist / _distanceScale);
  }

  /// Combined signal [0..1] blending phase and similarity.
  SignalResult computeSignal(List<double> feature) {
    final phase = phaseSignal(feature);
    final similarity = featureSimilarity(feature);
    final combined = clamp(
      _phaseWeight * phase + _similarityWeight * similarity,
      0.0,
      1.0,
    );
    return SignalResult(
      signal: combined,
      phase: phase,
      similarity: similarity,
    );
  }

  static double _getDouble(Map? map, String key, double fallback) {
    if (map == null) return fallback;
    final v = map[key];
    if (v is num) return v.toDouble();
    return fallback;
  }
}

/// Result of signal computation.
class SignalResult {
  final double signal;
  final double phase;
  final double similarity;

  const SignalResult({
    required this.signal,
    required this.phase,
    required this.similarity,
  });
}
