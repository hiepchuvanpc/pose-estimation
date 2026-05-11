import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app/di/injection.dart';
import 'features/auth/splash_screen.dart';
import 'presentation/providers/api_provider.dart';
import 'shared/theme/app_theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Lock orientation to portrait
  await SystemChrome.setPreferredOrientations([
    DeviceOrientation.portraitUp,
    DeviceOrientation.portraitDown,
  ]);

  // Initialize dependencies
  await setupDependencies();

  runApp(
    const ProviderScope(
      child: MotionCoachApp(),
    ),
  );
}

class MotionCoachApp extends ConsumerWidget {
  const MotionCoachApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Initialize API client settings on app startup
    ref.watch(apiInitProvider);

    return MaterialApp(
      title: 'Motion Coach',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.darkTheme,
      home: const SplashScreen(),
    );
  }
}
