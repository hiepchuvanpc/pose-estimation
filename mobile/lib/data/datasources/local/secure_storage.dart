import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Secure storage for sensitive data (tokens, credentials)
class SecureStorageService {
  final FlutterSecureStorage _storage;

  SecureStorageService() : _storage = const FlutterSecureStorage(
    aOptions: AndroidOptions(
      encryptedSharedPreferences: true,
    ),
    iOptions: IOSOptions(
      accessibility: KeychainAccessibility.first_unlock_this_device,
    ),
  );

  // ============ STORAGE KEYS ============

  static const String _keyGoogleIdToken = 'google_id_token';
  static const String _keyGoogleAccessToken = 'google_access_token';
  static const String _keyGoogleRefreshToken = 'google_refresh_token';
  static const String _keyTokenExpiry = 'token_expiry';
  static const String _keyCurrentUserId = 'current_user_id';

  // ============ TOKEN OPERATIONS ============

  Future<void> saveGoogleTokens({
    String? idToken,
    String? accessToken,
    String? refreshToken,
    DateTime? expiry,
  }) async {
    if (idToken != null) {
      await _storage.write(key: _keyGoogleIdToken, value: idToken);
    }
    if (accessToken != null) {
      await _storage.write(key: _keyGoogleAccessToken, value: accessToken);
    }
    if (refreshToken != null) {
      await _storage.write(key: _keyGoogleRefreshToken, value: refreshToken);
    }
    if (expiry != null) {
      await _storage.write(key: _keyTokenExpiry, value: expiry.toIso8601String());
    }
  }

  Future<String?> getGoogleIdToken() async {
    return _storage.read(key: _keyGoogleIdToken);
  }

  Future<String?> getGoogleAccessToken() async {
    return _storage.read(key: _keyGoogleAccessToken);
  }

  Future<String?> getGoogleRefreshToken() async {
    return _storage.read(key: _keyGoogleRefreshToken);
  }

  Future<DateTime?> getTokenExpiry() async {
    final expiryStr = await _storage.read(key: _keyTokenExpiry);
    if (expiryStr != null) {
      return DateTime.tryParse(expiryStr);
    }
    return null;
  }

  Future<bool> isTokenExpired() async {
    final expiry = await getTokenExpiry();
    if (expiry == null) return true;
    // Consider expired if within 5 minutes of expiry
    return DateTime.now().isAfter(expiry.subtract(const Duration(minutes: 5)));
  }

  Future<void> clearTokens() async {
    await _storage.delete(key: _keyGoogleIdToken);
    await _storage.delete(key: _keyGoogleAccessToken);
    await _storage.delete(key: _keyGoogleRefreshToken);
    await _storage.delete(key: _keyTokenExpiry);
  }

  // ============ USER OPERATIONS ============

  Future<void> setCurrentUserId(String userId) async {
    await _storage.write(key: _keyCurrentUserId, value: userId);
  }

  Future<String?> getCurrentUserId() async {
    return _storage.read(key: _keyCurrentUserId);
  }

  Future<void> clearCurrentUser() async {
    await _storage.delete(key: _keyCurrentUserId);
  }

  // ============ GENERIC OPERATIONS ============

  Future<void> write(String key, String value) async {
    await _storage.write(key: key, value: value);
  }

  Future<String?> read(String key) async {
    return _storage.read(key: key);
  }

  Future<void> deleteKey(String key) async {
    await _storage.delete(key: key);
  }

  Future<void> deleteAll() async {
    await _storage.deleteAll();
  }

  Future<bool> containsKey(String key) async {
    return _storage.containsKey(key: key);
  }
}
