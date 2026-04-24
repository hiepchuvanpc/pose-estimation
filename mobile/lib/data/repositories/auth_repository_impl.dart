import 'package:dartz/dartz.dart';
import 'package:drift/drift.dart';
import 'package:google_sign_in/google_sign_in.dart';

import '../../core/errors/failures.dart';
import '../../domain/entities/user.dart' as domain;
import '../../domain/repositories/auth_repository.dart';
import '../datasources/local/database.dart';
import '../datasources/local/secure_storage.dart';

/// Implementation of AuthRepository using Google Sign-In
class AuthRepositoryImpl implements AuthRepository {
  final GoogleSignIn _googleSignIn;
  final SecureStorageService _secureStorage;
  final AppDatabase _database;

  domain.User? _currentUser;

  AuthRepositoryImpl({
    required GoogleSignIn googleSignIn,
    required SecureStorageService secureStorage,
    required AppDatabase database,
  })  : _googleSignIn = googleSignIn,
        _secureStorage = secureStorage,
        _database = database;

  @override
  Future<Either<Failure, domain.User>> signInWithGoogle() async {
    try {
      final googleUser = await _googleSignIn.signIn();
      
      if (googleUser == null) {
        return const Left(AuthCancelled());
      }

      final googleAuth = await googleUser.authentication;
      
      // Store tokens securely
      await _secureStorage.saveGoogleTokens(
        accessToken: googleAuth.accessToken,
        idToken: googleAuth.idToken,
      );

      // Create or update user in database
      final user = domain.User(
        id: googleUser.id,
        email: googleUser.email,
        displayName: googleUser.displayName,
        photoUrl: googleUser.photoUrl,
        storageMode: domain.StorageMode.local, // Default to local
        createdAt: DateTime.now(),
        lastLoginAt: DateTime.now(),
      );

      await _saveUserToDatabase(user);
      _currentUser = user;

      return Right(user);
    } on Exception catch (e) {
      return Left(AuthFailure('Đăng nhập thất bại: ${e.toString()}'));
    }
  }

  @override
  Future<Either<Failure, void>> signOut() async {
    try {
      await _googleSignIn.signOut();
      await _secureStorage.deleteAll();
      _currentUser = null;
      return const Right(null);
    } on Exception catch (e) {
      return Left(AuthFailure('Đăng xuất thất bại: ${e.toString()}'));
    }
  }

  @override
  Future<Either<Failure, domain.User>> getCurrentUser() async {
    try {
      // Check if already cached
      if (_currentUser != null) {
        return Right(_currentUser!);
      }

      // Check if signed in with Google
      final googleUser = await _googleSignIn.signInSilently();
      if (googleUser == null) {
        return const Left(AuthNotAuthenticated());
      }

      // Load user from database
      final dbUser = await _database.getUserByGoogleId(googleUser.id);
      if (dbUser == null) {
        return const Left(AuthNotAuthenticated());
      }

      _currentUser = domain.User(
        id: dbUser.id,
        email: dbUser.email,
        displayName: dbUser.displayName,
        photoUrl: dbUser.photoUrl,
        storageMode: _parseStorageMode(dbUser.storageMode),
        createdAt: dbUser.createdAt,
        lastLoginAt: dbUser.lastLoginAt,
      );

      return Right(_currentUser!);
    } on Exception catch (e) {
      return Left(AuthFailure('Không thể lấy thông tin user: ${e.toString()}'));
    }
  }

  @override
  Future<bool> isAuthenticated() async {
    final result = await getCurrentUser();
    return result.isRight();
  }

  @override
  Future<Either<Failure, String>> getAccessToken() async {
    try {
      final token = await _secureStorage.getGoogleAccessToken();
      if (token == null) {
        return const Left(AuthNotAuthenticated());
      }
      return Right(token);
    } on Exception catch (e) {
      return Left(AuthFailure('Không thể lấy access token: ${e.toString()}'));
    }
  }

  @override
  Future<Either<Failure, String>> refreshToken() async {
    try {
      final googleUser = await _googleSignIn.signInSilently();
      if (googleUser == null) {
        return const Left(AuthTokenExpired());
      }

      final googleAuth = await googleUser.authentication;
      
      if (googleAuth.accessToken != null) {
        await _secureStorage.saveGoogleTokens(accessToken: googleAuth.accessToken);
        return Right(googleAuth.accessToken!);
      }

      return const Left(AuthTokenExpired());
    } on Exception catch (e) {
      return Left(AuthFailure('Không thể refresh token: ${e.toString()}'));
    }
  }

  @override
  Future<Either<Failure, void>> deleteAccount() async {
    try {
      // Get current user ID before signing out
      final googleUser = _googleSignIn.currentUser;
      if (googleUser != null) {
        // Delete from database
        await _database.deleteUser(googleUser.id);
      }

      // Disconnect from Google (revokes access)
      await _googleSignIn.disconnect();
      await _secureStorage.deleteAll();
      _currentUser = null;

      return const Right(null);
    } on Exception catch (e) {
      return Left(AuthFailure('Không thể xóa tài khoản: ${e.toString()}'));
    }
  }

  @override
  Future<Either<Failure, domain.User>> updateStorageMode(domain.StorageMode mode) async {
    try {
      if (_currentUser == null) {
        return const Left(AuthNotAuthenticated());
      }

      final updatedUser = _currentUser!.copyWith(storageMode: mode);
      await _saveUserToDatabase(updatedUser);
      _currentUser = updatedUser;

      return Right(updatedUser);
    } on Exception catch (e) {
      return Left(AuthFailure('Không thể cập nhật chế độ lưu trữ: ${e.toString()}'));
    }
  }

  // Helper methods
  Future<void> _saveUserToDatabase(domain.User user) async {
    final companion = UsersCompanion.insert(
      id: user.id,
      email: user.email,
      displayName: Value(user.displayName),
      photoUrl: Value(user.photoUrl),
      storageMode: Value(user.storageMode.name),
      createdAt: user.createdAt,
      lastLoginAt: user.lastLoginAt,
    );

    await _database.upsertUser(companion);
  }

  domain.StorageMode _parseStorageMode(String mode) {
    switch (mode) {
      case 'googleDrive':
        return domain.StorageMode.googleDrive;
      case 'server':
        return domain.StorageMode.server;
      default:
        return domain.StorageMode.local;
    }
  }
}
