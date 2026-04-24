import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_sign_in/google_sign_in.dart';

import '../../data/datasources/local/database.dart';
import '../../data/datasources/local/secure_storage.dart';
import '../../data/repositories/auth_repository_impl.dart';
import '../../domain/entities/user.dart' as domain;
import '../../domain/repositories/auth_repository.dart';
import '../../app/di/injection.dart';

/// Google Sign-In instance provider
final googleSignInProvider = Provider<GoogleSignIn>((ref) {
  return GoogleSignIn(
    scopes: [
      'email',
      'profile',
      // Add Google Drive scope when needed
      // 'https://www.googleapis.com/auth/drive.file',
    ],
  );
});

/// Auth repository provider
final authRepositoryProvider = Provider<AuthRepository>((ref) {
  return AuthRepositoryImpl(
    googleSignIn: ref.watch(googleSignInProvider),
    secureStorage: getIt<SecureStorageService>(),
    database: getIt<AppDatabase>(),
  );
});

/// Auth state - current user
class AuthState {
  final domain.User? user;
  final bool isLoading;
  final String? error;

  const AuthState({
    this.user,
    this.isLoading = false,
    this.error,
  });

  bool get isAuthenticated => user != null;

  AuthState copyWith({
    domain.User? user,
    bool? isLoading,
    String? error,
  }) {
    return AuthState(
      user: user ?? this.user,
      isLoading: isLoading ?? this.isLoading,
      error: error,
    );
  }
}

/// Auth notifier for managing auth state
class AuthNotifier extends StateNotifier<AuthState> {
  final AuthRepository _authRepository;

  AuthNotifier(this._authRepository) : super(const AuthState(isLoading: true)) {
    _checkCurrentUser();
  }

  Future<void> _checkCurrentUser() async {
    final result = await _authRepository.getCurrentUser();
    result.fold(
      (failure) => state = const AuthState(),
      (user) => state = AuthState(user: user),
    );
  }

  Future<void> signInWithGoogle() async {
    state = state.copyWith(isLoading: true, error: null);

    final result = await _authRepository.signInWithGoogle();
    result.fold(
      (failure) => state = AuthState(error: failure.message),
      (user) => state = AuthState(user: user),
    );
  }

  Future<void> signOut() async {
    state = state.copyWith(isLoading: true);

    final result = await _authRepository.signOut();
    result.fold(
      (failure) => state = state.copyWith(isLoading: false, error: failure.message),
      (_) => state = const AuthState(),
    );
  }

  Future<void> deleteAccount() async {
    state = state.copyWith(isLoading: true);

    final result = await _authRepository.deleteAccount();
    result.fold(
      (failure) => state = state.copyWith(isLoading: false, error: failure.message),
      (_) => state = const AuthState(),
    );
  }

  Future<void> updateStorageMode(domain.StorageMode mode) async {
    if (state.user == null) return;

    final result = await _authRepository.updateStorageMode(mode);
    result.fold(
      (failure) => state = state.copyWith(error: failure.message),
      (user) => state = state.copyWith(user: user),
    );
  }

  void clearError() {
    state = state.copyWith(error: null);
  }
}

/// Auth state provider
final authProvider = StateNotifierProvider<AuthNotifier, AuthState>((ref) {
  return AuthNotifier(ref.watch(authRepositoryProvider));
});

/// Current user provider (convenience)
final currentUserProvider = Provider<domain.User?>((ref) {
  return ref.watch(authProvider).user;
});

/// Is authenticated provider (convenience)
final isAuthenticatedProvider = Provider<bool>((ref) {
  return ref.watch(authProvider).isAuthenticated;
});
