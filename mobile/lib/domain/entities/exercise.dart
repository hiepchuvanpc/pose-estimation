import 'package:equatable/equatable.dart';

/// Exercise mode: counting repetitions or holding position
enum ExerciseMode {
  reps, // Count repetitions (squat, pushup, etc.)
  hold, // Hold position for duration (plank, wall sit, etc.)
}

/// Adaptive thresholds for pose detection
class AdaptiveThresholds extends Equatable {
  final double phaseWeight;
  final double similarityWeight;
  final double highThreshold;
  final double lowThreshold;

  const AdaptiveThresholds({
    this.phaseWeight = 0.7,
    this.similarityWeight = 0.3,
    this.highThreshold = 0.7,
    this.lowThreshold = 0.3,
  });

  factory AdaptiveThresholds.fromJson(Map<String, dynamic> json) {
    return AdaptiveThresholds(
      phaseWeight: (json['phase_weight'] as num?)?.toDouble() ?? 0.7,
      similarityWeight: (json['similarity_weight'] as num?)?.toDouble() ?? 0.3,
      highThreshold: (json['high_threshold'] as num?)?.toDouble() ?? 0.7,
      lowThreshold: (json['low_threshold'] as num?)?.toDouble() ?? 0.3,
    );
  }

  Map<String, dynamic> toJson() => {
        'phase_weight': phaseWeight,
        'similarity_weight': similarityWeight,
        'high_threshold': highThreshold,
        'low_threshold': lowThreshold,
      };

  @override
  List<Object?> get props =>
      [phaseWeight, similarityWeight, highThreshold, lowThreshold];
}

/// Profile data for exercise (PCA features from video analysis)
class ExerciseProfile extends Equatable {
  final List<double> featureMean;
  final List<double> featurePc1;
  final double projMin;
  final double projMax;
  final AdaptiveThresholds thresholds;

  const ExerciseProfile({
    required this.featureMean,
    required this.featurePc1,
    required this.projMin,
    required this.projMax,
    this.thresholds = const AdaptiveThresholds(),
  });

  factory ExerciseProfile.fromJson(Map<String, dynamic> json) {
    final profile = json['profile'] as Map<String, dynamic>? ?? json;
    return ExerciseProfile(
      featureMean: _parseDoubleList(profile['feature_mean']),
      featurePc1: _parseDoubleList(profile['feature_pc1']),
      projMin: (profile['proj_min'] as num?)?.toDouble() ?? 0.0,
      projMax: (profile['proj_max'] as num?)?.toDouble() ?? 1.0,
      thresholds: AdaptiveThresholds.fromJson(
        (profile['adaptive_thresholds'] as Map<String, dynamic>?) ?? {},
      ),
    );
  }

  static List<double> _parseDoubleList(dynamic raw) {
    if (raw is List) {
      return raw.map((e) => (e as num).toDouble()).toList();
    }
    return [];
  }

  Map<String, dynamic> toJson() => {
        'feature_mean': featureMean,
        'feature_pc1': featurePc1,
        'proj_min': projMin,
        'proj_max': projMax,
        'adaptive_thresholds': thresholds.toJson(),
      };

  @override
  List<Object?> get props =>
      [featureMean, featurePc1, projMin, projMax, thresholds];
}

/// Exercise entity representing a single exercise template
class Exercise extends Equatable {
  final String id;
  final String name;
  final ExerciseMode mode;
  final String videoPath;        // Local path or remote URI
  final String? thumbnailPath;
  final double trimStartSec;
  final double trimEndSec;
  final String? notes;
  final ExerciseProfile? profile;
  final DateTime createdAt;
  final DateTime updatedAt;
  final bool isSynced;
  final int syncVersion;

  const Exercise({
    required this.id,
    required this.name,
    required this.mode,
    required this.videoPath,
    this.thumbnailPath,
    this.trimStartSec = 0.0,
    this.trimEndSec = 0.0,
    this.notes,
    this.profile,
    required this.createdAt,
    required this.updatedAt,
    this.isSynced = false,
    this.syncVersion = 0,
  });

  /// Create from backend JSON (WorkoutTemplate format)
  factory Exercise.fromApiJson(Map<String, dynamic> json) {
    return Exercise(
      id: json['template_id'] as String,
      name: json['name'] as String,
      mode: (json['mode'] as String) == 'hold'
          ? ExerciseMode.hold
          : ExerciseMode.reps,
      videoPath: json['video_uri'] as String,
      trimStartSec: (json['trim_start_sec'] as num?)?.toDouble() ?? 0.0,
      trimEndSec: (json['trim_end_sec'] as num?)?.toDouble() ?? 0.0,
      notes: json['notes'] as String?,
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
      isSynced: true,
    );
  }

  /// Create a copy with updated fields
  Exercise copyWith({
    String? id,
    String? name,
    ExerciseMode? mode,
    String? videoPath,
    String? thumbnailPath,
    double? trimStartSec,
    double? trimEndSec,
    String? notes,
    ExerciseProfile? profile,
    DateTime? createdAt,
    DateTime? updatedAt,
    bool? isSynced,
    int? syncVersion,
  }) {
    return Exercise(
      id: id ?? this.id,
      name: name ?? this.name,
      mode: mode ?? this.mode,
      videoPath: videoPath ?? this.videoPath,
      thumbnailPath: thumbnailPath ?? this.thumbnailPath,
      trimStartSec: trimStartSec ?? this.trimStartSec,
      trimEndSec: trimEndSec ?? this.trimEndSec,
      notes: notes ?? this.notes,
      profile: profile ?? this.profile,
      createdAt: createdAt ?? this.createdAt,
      updatedAt: updatedAt ?? this.updatedAt,
      isSynced: isSynced ?? this.isSynced,
      syncVersion: syncVersion ?? this.syncVersion,
    );
  }

  /// Mode display text
  String get modeText => mode == ExerciseMode.reps ? 'Reps' : 'Hold';

  @override
  List<Object?> get props => [
        id,
        name,
        mode,
        videoPath,
        thumbnailPath,
        trimStartSec,
        trimEndSec,
        notes,
        profile,
        createdAt,
        updatedAt,
        isSynced,
        syncVersion,
      ];

  @override
  String toString() => 'Exercise($name, $modeText)';
}
