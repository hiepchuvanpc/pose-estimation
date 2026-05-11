import 'dart:io';

import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' as p;

part 'database.g.dart';

// ============ TABLE DEFINITIONS ============

/// Users table
class Users extends Table {
  TextColumn get id => text()();
  TextColumn get email => text().unique()();
  TextColumn get displayName => text().nullable()();
  TextColumn get photoUrl => text().nullable()();
  TextColumn get storageMode => text().withDefault(const Constant('local'))();
  BoolColumn get isPremium => boolean().withDefault(const Constant(false))();
  DateTimeColumn get createdAt => dateTime()();
  DateTimeColumn get lastLoginAt => dateTime()();

  @override
  Set<Column> get primaryKey => {id};
}

/// Exercises table
class Exercises extends Table {
  TextColumn get id => text()();
  TextColumn get userId => text().references(Users, #id)();
  TextColumn get name => text()();
  TextColumn get mode => text()(); // 'reps' or 'hold'
  TextColumn get videoPath => text()();
  TextColumn get thumbnailPath => text().nullable()();
  RealColumn get trimStartSec => real().withDefault(const Constant(0.0))();
  RealColumn get trimEndSec => real().nullable()();
  TextColumn get notes => text().nullable()();
  TextColumn get profileJson => text().nullable()(); // Stored as JSON
  DateTimeColumn get createdAt => dateTime()();
  DateTimeColumn get updatedAt => dateTime()();
  BoolColumn get isSynced => boolean().withDefault(const Constant(false))();
  IntColumn get syncVersion => integer().withDefault(const Constant(0))();

  @override
  Set<Column> get primaryKey => {id};
}

/// Lessons table (Giáo án)
class Lessons extends Table {
  TextColumn get id => text()();
  TextColumn get userId => text().references(Users, #id)();
  TextColumn get name => text()();
  TextColumn get description => text().nullable()();
  DateTimeColumn get createdAt => dateTime()();
  DateTimeColumn get updatedAt => dateTime()();
  BoolColumn get isSynced => boolean().withDefault(const Constant(false))();
  IntColumn get syncVersion => integer().withDefault(const Constant(0))();

  @override
  Set<Column> get primaryKey => {id};
}

/// Lesson items table (exercises in a lesson)
class LessonItems extends Table {
  TextColumn get id => text()();
  TextColumn get lessonId => text().references(Lessons, #id)();
  TextColumn get exerciseId => text().references(Exercises, #id)();
  IntColumn get orderIndex => integer()();
  IntColumn get sets => integer().withDefault(const Constant(1))();
  IntColumn get reps => integer().withDefault(const Constant(10))();
  IntColumn get holdSeconds => integer().withDefault(const Constant(30))();
  IntColumn get restSeconds => integer().withDefault(const Constant(60))();

  @override
  Set<Column> get primaryKey => {id};
}

/// Workout sessions table
class WorkoutSessions extends Table {
  TextColumn get id => text()();
  TextColumn get userId => text().references(Users, #id)();
  TextColumn get lessonId => text().references(Lessons, #id)();
  TextColumn get lessonName => text()();
  TextColumn get status => text().withDefault(const Constant('inProgress'))();
  DateTimeColumn get startedAt => dateTime()();
  DateTimeColumn get completedAt => dateTime().nullable()();
  BoolColumn get isSynced => boolean().withDefault(const Constant(false))();
  IntColumn get syncVersion => integer().withDefault(const Constant(0))();

  @override
  Set<Column> get primaryKey => {id};
}

/// Exercise results table (results within a session)
class ExerciseResults extends Table {
  TextColumn get id => text()();
  TextColumn get sessionId => text().references(WorkoutSessions, #id)();
  TextColumn get exerciseId => text().references(Exercises, #id)();
  TextColumn get exerciseName => text()();
  IntColumn get completedSets => integer().withDefault(const Constant(0))();
  IntColumn get targetSets => integer().withDefault(const Constant(1))();
  IntColumn get completedReps => integer().withDefault(const Constant(0))();
  IntColumn get targetReps => integer().withDefault(const Constant(10))();
  RealColumn get holdDuration => real().nullable()();
  RealColumn get targetHoldSeconds => real().nullable()();
  RealColumn get formScore => real().withDefault(const Constant(0.0))();
  TextColumn get processedVideoPath => text().nullable()();
  DateTimeColumn get completedAt => dateTime()();

  @override
  Set<Column> get primaryKey => {id};
}

/// Sync queue table for offline operations
class SyncQueue extends Table {
  TextColumn get id => text()();
  TextColumn get entityType => text()();
  TextColumn get entityId => text()();
  TextColumn get operation => text()(); // 'create', 'update', 'delete'
  TextColumn get dataJson => text().nullable()();
  DateTimeColumn get createdAt => dateTime()();
  IntColumn get retryCount => integer().withDefault(const Constant(0))();
  TextColumn get lastError => text().nullable()();

  @override
  Set<Column> get primaryKey => {id};
}

// ============ DATABASE CLASS ============

@DriftDatabase(tables: [
  Users,
  Exercises,
  Lessons,
  LessonItems,
  WorkoutSessions,
  ExerciseResults,
  SyncQueue,
])
class AppDatabase extends _$AppDatabase {
  AppDatabase() : super(_openConnection());

  @override
  int get schemaVersion => 1;

  @override
  MigrationStrategy get migration {
    return MigrationStrategy(
      onCreate: (Migrator m) async {
        await m.createAll();
      },
      onUpgrade: (Migrator m, int from, int to) async {
        // Handle future migrations here
      },
    );
  }

  // ============ USER OPERATIONS ============

  Future<User?> getUserById(String id) async {
    return (select(users)..where((t) => t.id.equals(id))).getSingleOrNull();
  }

  Future<User?> getUserByGoogleId(String googleId) async {
    // Google ID is stored as the user's primary ID
    return getUserById(googleId);
  }

  Future<User?> getUserByEmail(String email) async {
    return (select(users)..where((t) => t.email.equals(email))).getSingleOrNull();
  }

  Future<void> upsertUser(UsersCompanion user) async {
    await into(users).insertOnConflictUpdate(user);
  }

  Future<void> updateUserStorageMode(String userId, String mode) async {
    await (update(users)..where((t) => t.id.equals(userId)))
        .write(UsersCompanion(storageMode: Value(mode)));
  }

  Future<void> deleteUser(String id) async {
    await (delete(users)..where((t) => t.id.equals(id))).go();
  }

  // ============ EXERCISE OPERATIONS ============

  Future<List<Exercise>> getAllExercises(String userId) async {
    return (select(exercises)..where((t) => t.userId.equals(userId))).get();
  }

  Stream<List<Exercise>> watchExercises(String userId) {
    return (select(exercises)
          ..where((t) => t.userId.equals(userId))
          ..orderBy([(t) => OrderingTerm.desc(t.createdAt)]))
        .watch();
  }

  Future<Exercise?> getExerciseById(String id) async {
    return (select(exercises)..where((t) => t.id.equals(id))).getSingleOrNull();
  }

  Future<void> insertExercise(ExercisesCompanion exercise) async {
    await into(exercises).insert(exercise);
  }

  Future<void> updateExercise(ExercisesCompanion exercise) async {
    await (update(exercises)..where((t) => t.id.equals(exercise.id.value)))
        .write(exercise);
  }

  Future<void> deleteExercise(String id) async {
    await (delete(exercises)..where((t) => t.id.equals(id))).go();
  }

  Future<List<Exercise>> searchExercises(String userId, String query) async {
    return (select(exercises)
          ..where((t) =>
              t.userId.equals(userId) &
              t.name.lower().contains(query.toLowerCase())))
        .get();
  }

  // ============ LESSON OPERATIONS ============

  Future<List<Lesson>> getAllLessons(String userId) async {
    return (select(lessons)..where((t) => t.userId.equals(userId))).get();
  }

  Stream<List<Lesson>> watchLessons(String userId) {
    return (select(lessons)
          ..where((t) => t.userId.equals(userId))
          ..orderBy([(t) => OrderingTerm.desc(t.updatedAt)]))
        .watch();
  }

  Future<Lesson?> getLessonById(String id) async {
    return (select(lessons)..where((t) => t.id.equals(id))).getSingleOrNull();
  }

  Future<void> insertLesson(LessonsCompanion lesson) async {
    await into(lessons).insert(lesson);
  }

  Future<void> updateLesson(LessonsCompanion lesson) async {
    await (update(lessons)..where((t) => t.id.equals(lesson.id.value)))
        .write(lesson);
  }

  Future<void> deleteLesson(String id) async {
    // Delete lesson items first (cascade)
    await (delete(lessonItems)..where((t) => t.lessonId.equals(id))).go();
    await (delete(lessons)..where((t) => t.id.equals(id))).go();
  }

  // ============ LESSON ITEM OPERATIONS ============

  Future<List<LessonItem>> getLessonItems(String lessonId) async {
    return (select(lessonItems)
          ..where((t) => t.lessonId.equals(lessonId))
          ..orderBy([(t) => OrderingTerm.asc(t.orderIndex)]))
        .get();
  }

  Future<void> insertLessonItem(LessonItemsCompanion item) async {
    await into(lessonItems).insert(item);
  }

  Future<void> updateLessonItem(LessonItemsCompanion item) async {
    await (update(lessonItems)..where((t) => t.id.equals(item.id.value)))
        .write(item);
  }

  Future<void> deleteLessonItem(String id) async {
    await (delete(lessonItems)..where((t) => t.id.equals(id))).go();
  }

  // ============ WORKOUT SESSION OPERATIONS ============

  Future<List<WorkoutSession>> getAllSessions(String userId) async {
    return (select(workoutSessions)
          ..where((t) => t.userId.equals(userId))
          ..orderBy([(t) => OrderingTerm.desc(t.startedAt)]))
        .get();
  }

  Stream<List<WorkoutSession>> watchSessions(String userId) {
    return (select(workoutSessions)
          ..where((t) => t.userId.equals(userId))
          ..orderBy([(t) => OrderingTerm.desc(t.startedAt)]))
        .watch();
  }

  Future<WorkoutSession?> getSessionById(String id) async {
    return (select(workoutSessions)..where((t) => t.id.equals(id)))
        .getSingleOrNull();
  }

  Future<WorkoutSession?> getActiveSession(String userId) async {
    return (select(workoutSessions)
          ..where((t) =>
              t.userId.equals(userId) & t.status.equals('inProgress')))
        .getSingleOrNull();
  }

  Future<void> insertSession(WorkoutSessionsCompanion session) async {
    await into(workoutSessions).insert(session);
  }

  Future<void> updateSession(WorkoutSessionsCompanion session) async {
    await (update(workoutSessions)..where((t) => t.id.equals(session.id.value)))
        .write(session);
  }

  Future<void> deleteSession(String id) async {
    // Delete results first (cascade)
    await (delete(exerciseResults)..where((t) => t.sessionId.equals(id))).go();
    await (delete(workoutSessions)..where((t) => t.id.equals(id))).go();
  }

  // ============ EXERCISE RESULT OPERATIONS ============

  Future<List<ExerciseResult>> getSessionResults(String sessionId) async {
    return (select(exerciseResults)..where((t) => t.sessionId.equals(sessionId)))
        .get();
  }

  Future<void> insertExerciseResult(ExerciseResultsCompanion result) async {
    await into(exerciseResults).insert(result);
  }

  // ============ SYNC QUEUE OPERATIONS ============

  Future<List<SyncQueueData>> getPendingSyncItems() async {
    return (select(syncQueue)..orderBy([(t) => OrderingTerm.asc(t.createdAt)]))
        .get();
  }

  Future<void> addToSyncQueue(SyncQueueCompanion item) async {
    await into(syncQueue).insert(item);
  }

  Future<void> removeSyncQueueItem(String id) async {
    await (delete(syncQueue)..where((t) => t.id.equals(id))).go();
  }

  Future<void> incrementRetryCount(String id, String error) async {
    final item =
        await (select(syncQueue)..where((t) => t.id.equals(id))).getSingle();
    await (update(syncQueue)..where((t) => t.id.equals(id))).write(
      SyncQueueCompanion(
        retryCount: Value(item.retryCount + 1),
        lastError: Value(error),
      ),
    );
  }

  Future<void> deleteSyncItem(String id) async {
    await (delete(syncQueue)..where((t) => t.id.equals(id))).go();
  }

  Future<void> updateSyncItemRetry(String id, int newRetryCount, String error) async {
    await (update(syncQueue)..where((t) => t.id.equals(id))).write(
      SyncQueueCompanion(
        retryCount: Value(newRetryCount),
        lastError: Value(error),
      ),
    );
  }

  Future<int> getPendingSyncCount() async {
    final result = await (selectOnly(syncQueue)..addColumns([syncQueue.id.count()]))
        .getSingle();
    return result.read(syncQueue.id.count()) ?? 0;
  }

  // ============ UTILITY OPERATIONS ============

  Future<void> markAllAsUnsynced(String userId) async {
    await (update(exercises)..where((t) => t.userId.equals(userId)))
        .write(const ExercisesCompanion(isSynced: Value(false)));
    await (update(lessons)..where((t) => t.userId.equals(userId)))
        .write(const LessonsCompanion(isSynced: Value(false)));
    await (update(workoutSessions)..where((t) => t.userId.equals(userId)))
        .write(const WorkoutSessionsCompanion(isSynced: Value(false)));
  }

  Future<void> clearAllUserData(String userId) async {
    // Delete in correct order for foreign key constraints
    final sessions = await getAllSessions(userId);
    for (final session in sessions) {
      await deleteSession(session.id);
    }

    final userLessons = await getLessonsByUserId(userId);
    for (final lesson in userLessons) {
      await deleteLesson(lesson.id);
    }

    await (delete(exercises)..where((t) => t.userId.equals(userId))).go();
    await (delete(users)..where((t) => t.id.equals(userId))).go();
  }

  /// Clear all data from all tables
  Future<void> clearAllData() async {
    await delete(exerciseResults).go();
    await delete(workoutSessions).go();
    await delete(lessonItems).go();
    await delete(lessons).go();
    await delete(exercises).go();
    await delete(syncQueue).go();
    await delete(users).go();
  }

  /// Get all exercises (without userId filter) for export
  Future<List<Exercise>> getAllExercisesForExport() async {
    return select(exercises).get();
  }

  /// Get all lessons (without userId filter) for export
  Future<List<Lesson>> getAllLessonsForExport() async {
    return select(lessons).get();
  }

  /// Get all workout sessions (without userId filter) for export
  Future<List<WorkoutSession>> getAllWorkoutSessions() async {
    return select(workoutSessions).get();
  }

  /// Get workout session by ID
  Future<WorkoutSession?> getWorkoutSessionById(String id) async {
    return getSessionById(id);
  }

  /// Get exercise results for a session
  Future<List<ExerciseResult>> getExerciseResults(String sessionId) async {
    return getSessionResults(sessionId);
  }

  /// Add item to sync queue with SyncOperation enum
  Future<void> addSyncQueueItem({
    required String entityType,
    required String entityId,
    required SyncOperation operation,
    Map<String, dynamic>? data,
  }) async {
    final id = '${entityType}_${entityId}_${DateTime.now().millisecondsSinceEpoch}';
    await into(syncQueue).insert(SyncQueueCompanion.insert(
      id: id,
      entityType: entityType,
      entityId: entityId,
      operation: operation.name,
      createdAt: DateTime.now(),
    ));
  }

  /// Helper to get lessons by user id (internal use)
  Future<List<Lesson>> getLessonsByUserId(String userId) async {
    return (select(lessons)..where((t) => t.userId.equals(userId))).get();
  }
}

/// SyncOperation enum for type safety
enum SyncOperation { create, update, delete }

// ============ DATABASE CONNECTION ============

LazyDatabase _openConnection() {
  return LazyDatabase(() async {
    final dbFolder = await getApplicationDocumentsDirectory();
    final file = File(p.join(dbFolder.path, 'motion_coach.db'));
    return NativeDatabase.createInBackground(file);
  });
}
