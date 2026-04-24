import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// Service for communicating with Motion Coach Server (Premium feature)
class MotionCoachServerService {
  static const String _baseUrlKey = 'motion_coach_server_url';
  static const String _defaultUrl = 'https://api.motioncoach.app';
  
  String _baseUrl;
  String? _authToken;
  final http.Client _client;

  MotionCoachServerService({http.Client? client})
      : _baseUrl = _defaultUrl,
        _client = client ?? http.Client();

  /// Initialize service with saved URL
  Future<void> init() async {
    final prefs = await SharedPreferences.getInstance();
    _baseUrl = prefs.getString(_baseUrlKey) ?? _defaultUrl;
  }

  /// Set authentication token (from Google Sign-In)
  void setAuthToken(String token) {
    _authToken = token;
  }

  /// Clear authentication
  void clearAuth() {
    _authToken = null;
  }

  /// Check if authenticated
  bool get isAuthenticated => _authToken != null;

  /// Get authorization headers
  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (_authToken != null) 'Authorization': 'Bearer $_authToken',
      };

  /// Test connection to server
  Future<bool> testConnection() async {
    try {
      final response = await _client
          .get(Uri.parse('$_baseUrl/health'))
          .timeout(const Duration(seconds: 10));
      return response.statusCode == 200;
    } catch (e) {
      return false;
    }
  }

  /// Upload exercise data
  Future<bool> uploadExercise({
    required String id,
    required String name,
    required String type,
    required File videoFile,
    File? thumbnailFile,
    Map<String, dynamic>? metadata,
  }) async {
    if (!isAuthenticated) return false;

    try {
      final uri = Uri.parse('$_baseUrl/v1/exercises');
      final request = http.MultipartRequest('POST', uri);
      
      request.headers.addAll(_headers);
      request.fields['id'] = id;
      request.fields['name'] = name;
      request.fields['type'] = type;
      
      if (metadata != null) {
        request.fields['metadata'] = jsonEncode(metadata);
      }

      request.files.add(await http.MultipartFile.fromPath(
        'video',
        videoFile.path,
      ));

      if (thumbnailFile != null) {
        request.files.add(await http.MultipartFile.fromPath(
          'thumbnail',
          thumbnailFile.path,
        ));
      }

      final response = await request.send();
      return response.statusCode == 200 || response.statusCode == 201;
    } catch (e) {
      debugPrint('Error uploading exercise: $e');
      return false;
    }
  }

  /// Download exercise data
  Future<Map<String, dynamic>?> downloadExercise(String exerciseId) async {
    if (!isAuthenticated) return null;

    try {
      final response = await _client.get(
        Uri.parse('$_baseUrl/v1/exercises/$exerciseId'),
        headers: _headers,
      );

      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
      return null;
    } catch (e) {
      debugPrint('Error downloading exercise: $e');
      return null;
    }
  }

  /// List all exercises for user
  Future<List<Map<String, dynamic>>> listExercises() async {
    if (!isAuthenticated) return [];

    try {
      final response = await _client.get(
        Uri.parse('$_baseUrl/v1/exercises'),
        headers: _headers,
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        return (data['exercises'] as List?)?.cast<Map<String, dynamic>>() ?? [];
      }
      return [];
    } catch (e) {
      debugPrint('Error listing exercises: $e');
      return [];
    }
  }

  /// Delete exercise from server
  Future<bool> deleteExercise(String exerciseId) async {
    if (!isAuthenticated) return false;

    try {
      final response = await _client.delete(
        Uri.parse('$_baseUrl/v1/exercises/$exerciseId'),
        headers: _headers,
      );
      return response.statusCode == 200 || response.statusCode == 204;
    } catch (e) {
      debugPrint('Error deleting exercise: $e');
      return false;
    }
  }

  /// Upload workout session
  Future<bool> uploadWorkoutSession({
    required String sessionId,
    required String lessonId,
    required Map<String, dynamic> results,
    File? processedVideo,
  }) async {
    if (!isAuthenticated) return false;

    try {
      final uri = Uri.parse('$_baseUrl/v1/sessions');
      final request = http.MultipartRequest('POST', uri);
      
      request.headers.addAll(_headers);
      request.fields['session_id'] = sessionId;
      request.fields['lesson_id'] = lessonId;
      request.fields['results'] = jsonEncode(results);

      if (processedVideo != null) {
        request.files.add(await http.MultipartFile.fromPath(
          'video',
          processedVideo.path,
        ));
      }

      final response = await request.send();
      return response.statusCode == 200 || response.statusCode == 201;
    } catch (e) {
      debugPrint('Error uploading session: $e');
      return false;
    }
  }

  /// Get workout history
  Future<List<Map<String, dynamic>>> getWorkoutHistory({
    int limit = 50,
    int offset = 0,
  }) async {
    if (!isAuthenticated) return [];

    try {
      final response = await _client.get(
        Uri.parse('$_baseUrl/v1/sessions?limit=$limit&offset=$offset'),
        headers: _headers,
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        return (data['sessions'] as List?)?.cast<Map<String, dynamic>>() ?? [];
      }
      return [];
    } catch (e) {
      debugPrint('Error getting workout history: $e');
      return [];
    }
  }

  /// Sync all data to server
  Future<Map<String, dynamic>> syncAll({
    required List<Map<String, dynamic>> exercises,
    required List<Map<String, dynamic>> lessons,
    required List<Map<String, dynamic>> sessions,
  }) async {
    if (!isAuthenticated) {
      return {'success': false, 'error': 'Not authenticated'};
    }

    try {
      final response = await _client.post(
        Uri.parse('$_baseUrl/v1/sync'),
        headers: _headers,
        body: jsonEncode({
          'exercises': exercises,
          'lessons': lessons,
          'sessions': sessions,
        }),
      );

      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
      return {'success': false, 'error': 'Server error: ${response.statusCode}'};
    } catch (e) {
      return {'success': false, 'error': e.toString()};
    }
  }

  /// Get user's cloud storage usage
  Future<Map<String, int>?> getStorageUsage() async {
    if (!isAuthenticated) return null;

    try {
      final response = await _client.get(
        Uri.parse('$_baseUrl/v1/user/storage'),
        headers: _headers,
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        return {
          'used': data['used_bytes'] as int? ?? 0,
          'limit': data['limit_bytes'] as int? ?? 0,
        };
      }
      return null;
    } catch (e) {
      debugPrint('Error getting storage usage: $e');
      return null;
    }
  }

  /// Delete user account and all data
  Future<bool> deleteAccount() async {
    if (!isAuthenticated) return false;

    try {
      final response = await _client.delete(
        Uri.parse('$_baseUrl/v1/user'),
        headers: _headers,
      );
      return response.statusCode == 200 || response.statusCode == 204;
    } catch (e) {
      debugPrint('Error deleting account: $e');
      return false;
    }
  }
}
