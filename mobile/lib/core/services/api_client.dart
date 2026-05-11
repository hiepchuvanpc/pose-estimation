import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../models/template.dart';
import '../models/workout.dart';
import '../utils/server_url_validator.dart';

/// REST API client for backend FastAPI communication.
class ApiClient {
  static const String _defaultHost = 'api.motioncoach.app';
  static const int _defaultPort = 8000;
  static const String _prefKey = 'backend_url';

  String _baseUrl = 'http://$_defaultHost:$_defaultPort';
  final http.Client _client = http.Client();

  String get baseUrl => _baseUrl;

  /// Load saved backend URL from preferences.
  Future<void> loadSettings() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString(_prefKey);
    if (saved != null && saved.isNotEmpty) {
      _baseUrl = saved;
    }
  }

  /// Save and set a new backend URL.
  Future<void> setBaseUrl(String url) async {
    // Validate URL
    if (!ServerUrlValidator.isValidUrl(url)) {
      throw Exception(ServerUrlValidator.getErrorMessage(url));
    }
    
    // Sanitize
    _baseUrl = ServerUrlValidator.sanitizeUrl(url);
    
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefKey, _baseUrl);
  }

  /// Test connection to backend.
  Future<bool> testConnection() async {
    try {
      final response = await _client
          .get(Uri.parse('$_baseUrl/health'))
          .timeout(const Duration(seconds: 3));
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  // ===================== Library API =====================

  /// Get all templates from library.
  Future<List<WorkoutTemplate>> getTemplates() async {
    final response = await _get('/v1/library/templates');
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    final items = data['items'] as List;
    return items
        .map((e) => WorkoutTemplate.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// Get template profile for a specific template.
  Future<TemplateProfile?> getTemplateProfile(String templateId) async {
    try {
      final response =
          await _get('/v1/library/templates/$templateId/profile');
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        if (data['ready'] == true && data['profile'] != null) {
          return TemplateProfile.fromJson(
              data['profile'] as Map<String, dynamic>);
        }
      }
    } catch (_) {}
    return null;
  }

  /// Create template profile (triggers backend video processing).
  Future<bool> createTemplateProfile(String templateId) async {
    try {
      final response = await _post(
        '/v1/library/templates/$templateId/profile',
        {},
      );
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  // ===================== Workout API =====================

  /// Start a workout session.
  Future<Map<String, dynamic>?> startWorkoutSession({
    required List<WorkoutStepConfig> steps,
    bool speakEnabled = false,
  }) async {
    try {
      final response = await _post('/v1/workout/session/start', {
        'steps': steps.map((s) => s.toJson()).toList(),
        'speak_enabled': speakEnabled,
      });
      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
    } catch (_) {}
    return null;
  }

  /// Send frame signal to workout session.
  Future<WorkoutProgress?> sendWorkoutFrame({
    required String sessionId,
    required double signal,
    required int timestampMs,
    bool? readinessPassed,
    Map<String, dynamic>? studentFrame,
  }) async {
    try {
      final body = <String, dynamic>{
        'session_id': sessionId,
        'signal': signal,
        'timestamp_ms': timestampMs,
      };
      if (readinessPassed != null) {
        body['readiness_passed'] = readinessPassed;
      }
      if (studentFrame != null) {
        body['student_frame'] = studentFrame;
      }

      final response = await _post('/v1/workout/session/frame', body);
      if (response.statusCode == 200) {
        return WorkoutProgress.fromJson(
            jsonDecode(response.body) as Map<String, dynamic>);
      }
    } catch (_) {}
    return null;
  }

  /// Confirm to proceed to next set/exercise.
  Future<WorkoutProgress?> confirmWorkout(String sessionId) async {
    try {
      final response = await _post('/v1/workout/session/confirm', {
        'session_id': sessionId,
      });
      if (response.statusCode == 200) {
        return WorkoutProgress.fromJson(
            jsonDecode(response.body) as Map<String, dynamic>);
      }
    } catch (_) {}
    return null;
  }

  /// Finalize workout session (trigger DTW analysis).
  Future<Map<String, dynamic>?> finalizeWorkout(String sessionId) async {
    try {
      final response = await _post('/v1/workout/session/finalize', {
        'session_id': sessionId,
      });
      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
    } catch (_) {}
    return null;
  }

  // ===================== HTTP helpers =====================

  Future<http.Response> _get(String path) async {
    return await _client
        .get(
          Uri.parse('$_baseUrl$path'),
          headers: {'Accept': 'application/json'},
        )
        .timeout(const Duration(seconds: 10));
  }

  Future<http.Response> _post(String path, Map<String, dynamic> body) async {
    return await _client
        .post(
          Uri.parse('$_baseUrl$path'),
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
          },
          body: jsonEncode(body),
        )
        .timeout(const Duration(seconds: 30));
  }

  void dispose() {
    _client.close();
  }
}
