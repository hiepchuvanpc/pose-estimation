/// Hardcoded exercise template metadata
/// Calibration data loaded từ assets/templates/*.json
library;

class ExerciseTemplateData {
  static const templates = [
    {
      'id': 'reverse_lunge',
      'name': 'Reverse Lunge to Balance',
      'name_vi': 'Lunge ngược về cân bằng',
      'type': 'reps',
      'difficulty': 'beginner',
      'calibrationAsset': 'assets/templates/reverse_lunge_calibration.json',
      'cameraAngle': 'side',
      'cameraDistance': 2.5,  // meters
      'cameraHeight': 0.9,  // meters
      'keyBodyParts': ['hips', 'knees', 'ankles', 'shoulders'],
      'description': 'Bước chân ra sau, gập đầu gối, rồi đứng lên cân bằng',
      'repConfig': {
        'peakThreshold': 0.82,
        'valleyThreshold': 0.23,
        'minDuration': 1.5,
      },
      'formChecks': [
        {
          'name': 'front_knee_alignment',
          'description': 'Đầu gối trước không vượt quá mũi chân',
          'keypoints': [25, 27, 31],
        },
        {
          'name': 'balance_stability',
          'description': 'Giữ thân cân bằng khi đứng một chân',
          'keypoints': [11, 23, 27],
        },
      ],
    },
    {
      'id': 'plank_knees_down',
      'name': 'Plank with Knees Down',
      'name_vi': 'Plank hạ đầu gối',
      'type': 'hold',
      'difficulty': 'beginner',
      'calibrationAsset': 'assets/templates/plank_knees_down_calibration.json',
      'cameraAngle': 'side',
      'cameraDistance': 2.0,
      'cameraHeight': 0.4,
      'keyBodyParts': ['shoulders', 'elbows', 'hips', 'knees'],
      'description': 'Chống tay, hạ đầu gối xuống đất, giữ thân thẳng',
      'holdConfig': {
        'minScore': 75,
        'checkInterval': 0.5,
      },
      'formChecks': [
        {
          'name': 'shoulder_to_knee_alignment',
          'description': 'Vai-hông-gối thẳng hàng',
          'keypoints': [11, 23, 25],
        },
        {
          'name': 'elbow_90_degrees',
          'description': 'Khuỷu tay gập 90 độ',
          'keypoints': [11, 13, 15],
        },
        {
          'name': 'hip_level',
          'description': 'Hông không cao hoặc thấp quá',
          'keypoints': [23, 24],
        },
      ],
    },
    {
      'id': 'pushup_basic',
      'name': 'Push-up',
      'name_vi': 'Hít đất cơ bản',
      'type': 'reps',
      'difficulty': 'intermediate',
      'calibrationAsset': 'assets/templates/pushup_basic_calibration.json',
      'cameraAngle': 'side',
      'cameraDistance': 2.0,
      'cameraHeight': 0.3,  // ground level
      'keyBodyParts': ['elbows', 'shoulders', 'hips', 'ankles'],
      'description': 'Hạ thân xuống, khuỷu tay gập 90 độ, đẩy lên',
      'repConfig': {
        'peakThreshold': 0.85,
        'valleyThreshold': 0.18,
        'minDuration': 1.0,
      },
      'formChecks': [
        {
          'name': 'elbow_angle',
          'description': 'Khuỷu tay gập ít nhất 90 độ',
          'keypoints': [11, 13, 15],
        },
        {
          'name': 'plank_position',
          'description': 'Thân từ vai đến chân thẳng',
          'keypoints': [11, 23, 27],
        },
        {
          'name': 'chest_to_ground',
          'description': 'Ngực gần chạm đất',
          'keypoints': [11, 12],
        },
      ],
    },
  ];
}
