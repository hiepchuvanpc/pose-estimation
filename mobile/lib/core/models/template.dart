/// Exercise template from backend library.
class WorkoutTemplate {
  final String templateId;
  final String name;
  final String mode; // 'reps' or 'hold'
  final String videoUri;
  final String? notes;
  final double? trimStartSec;
  final double? trimEndSec;

  const WorkoutTemplate({
    required this.templateId,
    required this.name,
    required this.mode,
    required this.videoUri,
    this.notes,
    this.trimStartSec,
    this.trimEndSec,
  });

  factory WorkoutTemplate.fromJson(Map<String, dynamic> json) =>
      WorkoutTemplate(
        templateId: json['template_id'] as String,
        name: json['name'] as String,
        mode: json['mode'] as String,
        videoUri: json['video_uri'] as String,
        notes: json['notes'] as String?,
        trimStartSec: (json['trim_start_sec'] as num?)?.toDouble(),
        trimEndSec: (json['trim_end_sec'] as num?)?.toDouble(),
      );

  Map<String, dynamic> toJson() => {
        'template_id': templateId,
        'name': name,
        'mode': mode,
        'video_uri': videoUri,
        'notes': notes,
        'trim_start_sec': trimStartSec,
        'trim_end_sec': trimEndSec,
      };
}

/// Template profile from backend (PCA mean, pc1, etc).
class TemplateProfile {
  final List<double> featureMean;
  final List<double> featurePc1;
  final double projMin;
  final double projMax;
  final List<List<double>> features;
  final int samples;
  final Map<String, dynamic> adaptiveThresholds;
  final List<List<List<double>>> anchorPoseSamples;

  const TemplateProfile({
    required this.featureMean,
    required this.featurePc1,
    required this.projMin,
    required this.projMax,
    required this.features,
    required this.samples,
    this.adaptiveThresholds = const {},
    this.anchorPoseSamples = const [],
  });

  factory TemplateProfile.fromJson(Map<String, dynamic> json) {
    final profile = json['profile'] as Map<String, dynamic>? ?? json;
    return TemplateProfile(
      featureMean: _parseDoubleList(profile['feature_mean']),
      featurePc1: _parseDoubleList(profile['feature_pc1']),
      projMin: (profile['proj_min'] as num?)?.toDouble() ?? 0.0,
      projMax: (profile['proj_max'] as num?)?.toDouble() ?? 1.0,
      features: _parse2DList(profile['features']),
      samples: (profile['samples'] as num?)?.toInt() ?? 0,
      adaptiveThresholds:
          (profile['adaptive_thresholds'] as Map<String, dynamic>?) ?? {},
      anchorPoseSamples: _parse3DList(profile['anchor_pose_samples']),
    );
  }

  static List<double> _parseDoubleList(dynamic raw) {
    if (raw is List) {
      return raw.map((e) => (e as num).toDouble()).toList();
    }
    return [];
  }

  static List<List<double>> _parse2DList(dynamic raw) {
    if (raw is List) {
      return raw
          .map((row) =>
              (row as List).map((e) => (e as num).toDouble()).toList())
          .toList();
    }
    return [];
  }

  static List<List<List<double>>> _parse3DList(dynamic raw) {
    if (raw is List) {
      return raw
          .map((sample) => (sample as List)
              .map((point) =>
                  (point as List).map((e) => (e as num).toDouble()).toList())
              .toList())
          .toList();
    }
    return [];
  }
}
