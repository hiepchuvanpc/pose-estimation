import '../models/template.dart';

/// Mock templates for offline demo mode (no server required).
class MockTemplates {
  static final List<WorkoutTemplate> demoTemplates = [
    WorkoutTemplate(
      templateId: 'demo-squat',
      name: 'Squat (Demo)',
      mode: 'reps',
      videoUri: 'https://flutter.github.io/assets-for-api-docs/assets/videos/butterfly.mp4',
      notes: 'Offline demo - Squat cơ bản',
      trimStartSec: 0,
      trimEndSec: 10,
    ),
    WorkoutTemplate(
      templateId: 'demo-pushup',
      name: 'Push-up (Demo)',
      mode: 'reps',
      videoUri: 'https://flutter.github.io/assets-for-api-docs/assets/videos/butterfly.mp4',
      notes: 'Offline demo - Chống đẩy',
      trimStartSec: 0,
      trimEndSec: 10,
    ),
    WorkoutTemplate(
      templateId: 'demo-plank',
      name: 'Plank (Demo)',
      mode: 'hold',
      videoUri: 'https://flutter.github.io/assets-for-api-docs/assets/videos/butterfly.mp4',
      notes: 'Offline demo - Plank giữ thăng bằng',
      trimStartSec: 0,
      trimEndSec: 10,
    ),
    WorkoutTemplate(
      templateId: 'demo-lunge',
      name: 'Lunge (Demo)',
      mode: 'reps',
      videoUri: 'https://flutter.github.io/assets-for-api-docs/assets/videos/butterfly.mp4',
      notes: 'Offline demo - Lunge chân trước',
      trimStartSec: 0,
      trimEndSec: 10,
    ),
    WorkoutTemplate(
      templateId: 'demo-bridge',
      name: 'Bridge (Demo)',
      mode: 'hold',
      videoUri: 'https://flutter.github.io/assets-for-api-docs/assets/videos/butterfly.mp4',
      notes: 'Offline demo - Bridge nâng hông',
      trimStartSec: 0,
      trimEndSec: 10,
    ),
  ];
}
