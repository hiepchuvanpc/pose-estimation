import 'package:equatable/equatable.dart';

/// Base failure class for error handling
abstract class Failure extends Equatable {
  final String message;
  final String? code;

  const Failure({
    required this.message,
    this.code,
  });

  @override
  List<Object?> get props => [message, code];
}

// ============ Auth Failures ============

class AuthFailure extends Failure {
  const AuthFailure(String message) : super(message: message);
}

class AuthCancelled extends AuthFailure {
  const AuthCancelled() : super('Đăng nhập đã bị hủy');
}

class AuthTokenExpired extends AuthFailure {
  const AuthTokenExpired() : super('Phiên đăng nhập đã hết hạn');
}

class AuthNotAuthenticated extends AuthFailure {
  const AuthNotAuthenticated() : super('Chưa đăng nhập');
}

// ============ Storage Failures ============

class StorageFailure extends Failure {
  const StorageFailure(String message) : super(message: message);
}

class StoragePermissionDenied extends StorageFailure {
  const StoragePermissionDenied() : super('Không có quyền truy cập bộ nhớ');
}

class StorageQuotaExceeded extends StorageFailure {
  const StorageQuotaExceeded() : super('Đã hết dung lượng lưu trữ');
}

class DriveQuotaExceeded extends StorageFailure {
  const DriveQuotaExceeded() : super('Dung lượng Google Drive đã đầy');
}

// ============ Sync Failures ============

class SyncFailure extends Failure {
  const SyncFailure(String message) : super(message: message);
}

class SyncNetworkError extends SyncFailure {
  const SyncNetworkError() : super('Mất kết nối khi đồng bộ');
}

class SyncConflict extends SyncFailure {
  const SyncConflict() : super('Xung đột dữ liệu khi đồng bộ');
}

// ============ Network Failures ============

class NetworkFailure extends Failure {
  const NetworkFailure(String message) : super(message: message);
}

class NoInternetConnection extends NetworkFailure {
  const NoInternetConnection() : super('Không có kết nối Internet');
}

class ServerError extends NetworkFailure {
  const ServerError([String? message]) : super(message ?? 'Lỗi máy chủ');
}

class TimeoutError extends NetworkFailure {
  const TimeoutError() : super('Kết nối quá thời gian');
}

// ============ Database Failures ============

class DatabaseFailure extends Failure {
  const DatabaseFailure(String message) : super(message: message);
}

class EntityNotFound extends DatabaseFailure {
  const EntityNotFound(String entity) : super('Không tìm thấy $entity');
}

class DuplicateEntity extends DatabaseFailure {
  const DuplicateEntity(String entity) : super('$entity đã tồn tại');
}

// ============ Permission Failures ============

class PermissionFailure extends Failure {
  const PermissionFailure(String message) : super(message: message);
}

class CameraPermissionDenied extends PermissionFailure {
  const CameraPermissionDenied() : super('Không có quyền truy cập camera');
}

class PremiumRequired extends PermissionFailure {
  const PremiumRequired() : super('Tính năng này yêu cầu gói Premium');
}

// ============ Video Processing Failures ============

class VideoFailure extends Failure {
  const VideoFailure(String message) : super(message: message);
}

class VideoNotFound extends VideoFailure {
  const VideoNotFound() : super('Không tìm thấy video');
}

class VideoProcessingError extends VideoFailure {
  const VideoProcessingError([String? message])
      : super(message ?? 'Lỗi xử lý video');
}

class VideoTooLong extends VideoFailure {
  final int maxSeconds;
  const VideoTooLong(this.maxSeconds)
      : super('Video quá dài (tối đa $maxSeconds giây)');
}
