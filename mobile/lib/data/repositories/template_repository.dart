import 'dart:convert';
import 'package:flutter/services.dart';

import '../../core/models/template.dart';
import '../../domain/entities/exercise.dart';

/// Repository để load template calibration data từ assets
class TemplateRepository {
  final Map<String, TemplateProfile> _cache = {};
  
  /// Load template profile từ assets
  Future<TemplateProfile> loadProfile(String templateId) async {
    // Check cache
    if (_cache.containsKey(templateId)) {
      return _cache[templateId]!;
    }
    
    // Load từ assets
    final jsonString = await rootBundle.loadString(
      'assets/templates/${templateId}_calibration.json',
    );
    
    final data = jsonDecode(jsonString);
    
    // Parse PCA data
    final pcaData = data['pca'] as Map<String, dynamic>;
    
    final profile = TemplateProfile(
      featureMean: List<double>.from(pcaData['mean']),
      featurePc1: List<double>.from(pcaData['pc1']),
      projMin: pcaData['proj_min'].toDouble(),
      projMax: pcaData['proj_max'].toDouble(),
      adaptiveThresholds: {
        'signal': data['thresholds'] as Map<String, dynamic>,
      },
      features: [],  // Not needed for template
      samples: 0,    // Not needed for template
    );
    
    // Cache
    _cache[templateId] = profile;
    
    return profile;
  }
  
  /// Get available template IDs
  List<String> getAvailableTemplateIds() {
    return [
      'reverse_lunge',
      'plank_knees_down',
      'pushup_basic',
    ];
  }
  
  /// Get exercise metadata for template
  Exercise getExerciseMetadata(String templateId) {
    // Map template IDs to Exercise entities
    final metadata = _exerciseMetadata[templateId];
    if (metadata == null) {
      throw Exception('Template not found: $templateId');
    }
    
    final now = DateTime.now();
    return Exercise(
      id: templateId,
      name: metadata['name'] as String,
      mode: metadata['mode'] as ExerciseMode,
      videoPath: metadata['videoPath'] as String? ?? '',
      thumbnailPath: metadata['thumbnailPath'] as String?,
      createdAt: now,
      updatedAt: now,
    );
  }
  
  static final _exerciseMetadata = {
    'reverse_lunge': {
      'name': 'Reverse Lunge to Balance',
      'name_vi': 'Lunge ngược về cân bằng',
      'mode': ExerciseMode.reps,
      'difficulty': 'beginner',
      'thumbnailPath': null,  // TODO: Add thumbnails
      'videoPath': null,  // Template videos are in backend, not bundled
    },
    'plank_knees_down': {
      'name': 'Plank with Knees Down',
      'name_vi': 'Plank hạ đầu gối',
      'mode': ExerciseMode.hold,
      'difficulty': 'beginner',
      'thumbnailPath': null,
      'videoPath': null,
    },
    'pushup_basic': {
      'name': 'Push-up',
      'name_vi': 'Hít đất cơ bản',
      'mode': ExerciseMode.reps,
      'difficulty': 'intermediate',
      'thumbnailPath': null,
      'videoPath': null,
    },
  };
}
