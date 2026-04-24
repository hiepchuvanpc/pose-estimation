import 'package:flutter/foundation.dart';

/// Validator cho server URLs để prevent SSRF và redirect attacks
class ServerUrlValidator {
  /// Whitelist các domain được phép
  static const _allowedHosts = [
    'api.motioncoach.app',
    'motioncoach.app',
    'localhost',
    '127.0.0.1',
    '10.0.2.2',  // Android emulator
    '192.168.1.100',  // Development server
    '192.168.1.101',
    '192.168.1.102',
  ];
  
  /// Validate URL có hợp lệ và an toàn không
  static bool isValidUrl(String url) {
    try {
      final uri = Uri.parse(url);
      
      // Phải có scheme
      if (uri.scheme.isEmpty) {
        return false;
      }
      
      // Production: Chỉ chấp nhận HTTPS
      if (!kDebugMode && uri.scheme != 'https') {
        return false;
      }
      
      // Debug: Chấp nhận HTTP cho localhost
      if (kDebugMode && uri.scheme != 'http' && uri.scheme != 'https') {
        return false;
      }
      
      // Phải có host
      if (uri.host.isEmpty) {
        return false;
      }
      
      // Check whitelist
      if (!_allowedHosts.contains(uri.host)) {
        return false;
      }
      
      // Không cho phép user credentials trong URL
      if (uri.hasAuthority && uri.userInfo.isNotEmpty) {
        return false;
      }
      
      return true;
    } catch (_) {
      return false;
    }
  }
  
  /// Sanitize URL (remove trailing slash, normalize)
  static String sanitizeUrl(String url) {
    try {
      final uri = Uri.parse(url);
      return uri.toString().replaceAll(RegExp(r'/$'), '');
    } catch (_) {
      return url;
    }
  }
  
  /// Get error message for invalid URL
  static String getErrorMessage(String url) {
    try {
      final uri = Uri.parse(url);
      
      if (!kDebugMode && uri.scheme != 'https') {
        return 'Chỉ chấp nhận HTTPS trong production';
      }
      
      if (!_allowedHosts.contains(uri.host)) {
        return 'Domain không được phép. Chỉ chấp nhận: ${_allowedHosts.join(", ")}';
      }
      
      if (uri.userInfo.isNotEmpty) {
        return 'URL không được chứa thông tin xác thực';
      }
      
      return 'URL không hợp lệ';
    } catch (e) {
      return 'URL không đúng định dạng: ${e.toString()}';
    }
  }
}
