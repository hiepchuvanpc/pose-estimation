import 'package:equatable/equatable.dart';

/// Storage mode for user data
enum StorageMode {
  local,       // Local device storage only
  googleDrive, // Sync to Google Drive
  server,      // Premium: Motion Coach server
}

/// User entity representing authenticated user
class User extends Equatable {
  final String id;
  final String email;
  final String? displayName;
  final String? photoUrl;
  final StorageMode storageMode;
  final bool isPremium;
  final DateTime createdAt;
  final DateTime lastLoginAt;

  const User({
    required this.id,
    required this.email,
    this.displayName,
    this.photoUrl,
    this.storageMode = StorageMode.local,
    this.isPremium = false,
    required this.createdAt,
    required this.lastLoginAt,
  });

  /// Create a copy with updated fields
  User copyWith({
    String? id,
    String? email,
    String? displayName,
    String? photoUrl,
    StorageMode? storageMode,
    bool? isPremium,
    DateTime? createdAt,
    DateTime? lastLoginAt,
  }) {
    return User(
      id: id ?? this.id,
      email: email ?? this.email,
      displayName: displayName ?? this.displayName,
      photoUrl: photoUrl ?? this.photoUrl,
      storageMode: storageMode ?? this.storageMode,
      isPremium: isPremium ?? this.isPremium,
      createdAt: createdAt ?? this.createdAt,
      lastLoginAt: lastLoginAt ?? this.lastLoginAt,
    );
  }

  @override
  List<Object?> get props => [
        id,
        email,
        displayName,
        photoUrl,
        storageMode,
        isPremium,
        createdAt,
        lastLoginAt,
      ];

  @override
  String toString() => 'User(${displayName ?? email}, mode: $storageMode)';
}
