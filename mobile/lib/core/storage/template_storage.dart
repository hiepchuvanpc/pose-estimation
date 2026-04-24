import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/template.dart';

/// Local storage for user-created workout templates.
class TemplateStorage {
  static const String _key = 'user_templates';

  /// Save templates to local storage.
  static Future<void> saveTemplates(List<WorkoutTemplate> templates) async {
    final prefs = await SharedPreferences.getInstance();
    final jsonList = templates.map((t) => t.toJson()).toList();
    await prefs.setString(_key, jsonEncode(jsonList));
  }

  /// Load templates from local storage.
  static Future<List<WorkoutTemplate>> loadTemplates() async {
    final prefs = await SharedPreferences.getInstance();
    final jsonStr = prefs.getString(_key);
    if (jsonStr == null) return [];
    
    final jsonList = jsonDecode(jsonStr) as List;
    return jsonList
        .map((json) => WorkoutTemplate.fromJson(json as Map<String, dynamic>))
        .toList();
  }

  /// Add a new template.
  static Future<void> addTemplate(WorkoutTemplate template) async {
    final templates = await loadTemplates();
    templates.add(template);
    await saveTemplates(templates);
  }

  /// Update existing template.
  static Future<void> updateTemplate(String templateId, WorkoutTemplate updated) async {
    final templates = await loadTemplates();
    final index = templates.indexWhere((t) => t.templateId == templateId);
    if (index != -1) {
      templates[index] = updated;
      await saveTemplates(templates);
    }
  }

  /// Delete template.
  static Future<void> deleteTemplate(String templateId) async {
    final templates = await loadTemplates();
    templates.removeWhere((t) => t.templateId == templateId);
    await saveTemplates(templates);
  }
}
