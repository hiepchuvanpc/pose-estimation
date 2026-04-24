import 'package:equatable/equatable.dart';

/// A single item in a lesson (one exercise with configuration)
class LessonItem extends Equatable {
  final String id;
  final String exerciseId;
  final int orderIndex;
  final int sets;
  final int reps;           // Target reps (for reps mode)
  final int holdSeconds;    // Target hold duration (for hold mode)
  final int restSeconds;    // Rest between sets

  const LessonItem({
    required this.id,
    required this.exerciseId,
    required this.orderIndex,
    this.sets = 1,
    this.reps = 10,
    this.holdSeconds = 30,
    this.restSeconds = 60,
  });

  LessonItem copyWith({
    String? id,
    String? exerciseId,
    int? orderIndex,
    int? sets,
    int? reps,
    int? holdSeconds,
    int? restSeconds,
  }) {
    return LessonItem(
      id: id ?? this.id,
      exerciseId: exerciseId ?? this.exerciseId,
      orderIndex: orderIndex ?? this.orderIndex,
      sets: sets ?? this.sets,
      reps: reps ?? this.reps,
      holdSeconds: holdSeconds ?? this.holdSeconds,
      restSeconds: restSeconds ?? this.restSeconds,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'exercise_id': exerciseId,
        'order_index': orderIndex,
        'sets': sets,
        'reps': reps,
        'hold_seconds': holdSeconds,
        'rest_seconds': restSeconds,
      };

  factory LessonItem.fromJson(Map<String, dynamic> json) {
    return LessonItem(
      id: json['id'] as String,
      exerciseId: json['exercise_id'] as String,
      orderIndex: (json['order_index'] as num?)?.toInt() ?? 0,
      sets: (json['sets'] as num?)?.toInt() ?? 1,
      reps: (json['reps'] as num?)?.toInt() ?? 10,
      holdSeconds: (json['hold_seconds'] as num?)?.toInt() ?? 30,
      restSeconds: (json['rest_seconds'] as num?)?.toInt() ?? 60,
    );
  }

  @override
  List<Object?> get props =>
      [id, exerciseId, orderIndex, sets, reps, holdSeconds, restSeconds];
}

/// Lesson entity (Giáo án) - a workout plan with multiple exercises
class Lesson extends Equatable {
  final String id;
  final String name;
  final String? description;
  final List<LessonItem> items;
  final DateTime createdAt;
  final DateTime updatedAt;
  final bool isSynced;
  final int syncVersion;

  const Lesson({
    required this.id,
    required this.name,
    this.description,
    this.items = const [],
    required this.createdAt,
    required this.updatedAt,
    this.isSynced = false,
    this.syncVersion = 0,
  });

  Lesson copyWith({
    String? id,
    String? name,
    String? description,
    List<LessonItem>? items,
    DateTime? createdAt,
    DateTime? updatedAt,
    bool? isSynced,
    int? syncVersion,
  }) {
    return Lesson(
      id: id ?? this.id,
      name: name ?? this.name,
      description: description ?? this.description,
      items: items ?? this.items,
      createdAt: createdAt ?? this.createdAt,
      updatedAt: updatedAt ?? this.updatedAt,
      isSynced: isSynced ?? this.isSynced,
      syncVersion: syncVersion ?? this.syncVersion,
    );
  }

  /// Total number of exercises in this lesson
  int get totalExercises => items.length;

  /// Total estimated workout time in minutes
  int get estimatedMinutes {
    int totalSeconds = 0;
    for (final item in items) {
      // Assume each rep takes ~3 seconds
      final exerciseTime = item.sets * (item.reps * 3 + item.holdSeconds);
      final restTime = (item.sets - 1) * item.restSeconds;
      totalSeconds += exerciseTime + restTime;
    }
    return (totalSeconds / 60).ceil();
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'description': description,
        'items': items.map((e) => e.toJson()).toList(),
        'created_at': createdAt.toIso8601String(),
        'updated_at': updatedAt.toIso8601String(),
        'is_synced': isSynced,
        'sync_version': syncVersion,
      };

  factory Lesson.fromJson(Map<String, dynamic> json) {
    return Lesson(
      id: json['id'] as String,
      name: json['name'] as String,
      description: json['description'] as String?,
      items: (json['items'] as List<dynamic>?)
              ?.map((e) => LessonItem.fromJson(e as Map<String, dynamic>))
              .toList() ??
          [],
      createdAt: DateTime.parse(json['created_at'] as String),
      updatedAt: DateTime.parse(json['updated_at'] as String),
      isSynced: json['is_synced'] as bool? ?? false,
      syncVersion: (json['sync_version'] as num?)?.toInt() ?? 0,
    );
  }

  @override
  List<Object?> get props =>
      [id, name, description, items, createdAt, updatedAt, isSynced, syncVersion];

  @override
  String toString() => 'Lesson($name, ${items.length} exercises)';
}
