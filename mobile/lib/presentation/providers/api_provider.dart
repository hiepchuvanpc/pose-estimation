import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/services/api_client.dart';

/// Global ApiClient provider
final apiClientProvider = Provider<ApiClient>((ref) {
  return ApiClient();
});

/// Provider for loading API settings on startup
final apiInitProvider = FutureProvider<void>((ref) async {
  final api = ref.read(apiClientProvider);
  await api.loadSettings();
});
