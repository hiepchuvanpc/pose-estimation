import 'package:dartz/dartz.dart';

import '../../core/errors/failures.dart';
import '../entities/user.dart';

/// Repository interface for authentication operations
abstract class AuthRepository {
  /// Sign in with Google
  Future<Either<Failure, User>> signInWithGoogle();

  /// Sign out current user
  Future<Either<Failure, void>> signOut();

  /// Get currently authenticated user
  Future<Either<Failure, User>> getCurrentUser();

  /// Check if user is authenticated
  Future<bool> isAuthenticated();

  /// Get access token for API calls
  Future<Either<Failure, String>> getAccessToken();

  /// Refresh the access token
  Future<Either<Failure, String>> refreshToken();

  /// Delete user account (and optionally their data)
  Future<Either<Failure, void>> deleteAccount();

  /// Update user's storage mode preference
  Future<Either<Failure, User>> updateStorageMode(StorageMode mode);
}
