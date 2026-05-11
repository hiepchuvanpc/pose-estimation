import 'package:get_it/get_it.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../data/datasources/local/database.dart';
import '../../data/datasources/local/secure_storage.dart';
import '../../data/repositories/template_repository.dart';
import '../../core/services/api_client.dart';

final getIt = GetIt.instance;

/// Initialize all dependencies
Future<void> setupDependencies() async {
  // ============ EXTERNAL DEPENDENCIES ============

  final sharedPrefs = await SharedPreferences.getInstance();
  getIt.registerSingleton<SharedPreferences>(sharedPrefs);

  // ============ LOCAL DATA SOURCES ============

  getIt.registerLazySingleton<AppDatabase>(() => AppDatabase());
  getIt.registerLazySingleton<SecureStorageService>(() => SecureStorageService());

  // ============ REMOTE DATA SOURCES ============

  getIt.registerLazySingleton<ApiClient>(() => ApiClient());

  // ============ REPOSITORIES ============

  getIt.registerLazySingleton<TemplateRepository>(() => TemplateRepository());

  // Will be registered when implementations are created
  // getIt.registerLazySingleton<AuthRepository>(() => AuthRepositoryImpl(...));
  // getIt.registerLazySingleton<ExerciseRepository>(() => ExerciseRepositoryImpl(...));
  // getIt.registerLazySingleton<LessonRepository>(() => LessonRepositoryImpl(...));
  // getIt.registerLazySingleton<WorkoutRepository>(() => WorkoutRepositoryImpl(...));
  // getIt.registerLazySingleton<StorageRepository>(() => StorageRepositoryImpl(...));

  // ============ SERVICES ============

  // Services will be registered as needed
}

/// Reset all dependencies (useful for testing or logout)
Future<void> resetDependencies() async {
  await getIt.reset();
  await setupDependencies();
}

/// Check if dependencies are initialized
bool get dependenciesInitialized => getIt.isRegistered<AppDatabase>();
