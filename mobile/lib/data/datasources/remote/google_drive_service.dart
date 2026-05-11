import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:googleapis/drive/v3.dart' as drive;
import 'package:google_sign_in/google_sign_in.dart';
import 'package:http/http.dart' as http;

/// HTTP client that authenticates with Google Sign-In
class GoogleAuthClient extends http.BaseClient {
  final Map<String, String> _headers;
  final http.Client _client = http.Client();

  GoogleAuthClient(this._headers);

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) {
    return _client.send(request..headers.addAll(_headers));
  }
}

/// Service for Google Drive operations
class GoogleDriveService {
  static const String _folderName = 'MotionCoach';
  static const String _exercisesFolderName = 'exercises';
  static const String _sessionsFolderName = 'sessions';
  // Reserved for future use
  // static const String _metadataFileName = 'metadata.json';

  final GoogleSignIn _googleSignIn;
  drive.DriveApi? _driveApi;
  String? _rootFolderId;

  GoogleDriveService(this._googleSignIn);

  /// Initialize Drive API with authentication
  Future<bool> init() async {
    try {
      final account = _googleSignIn.currentUser;
      if (account == null) return false;

      final authHeaders = await account.authHeaders;
      final authClient = GoogleAuthClient(authHeaders);
      _driveApi = drive.DriveApi(authClient);
      
      // Create or get root folder
      _rootFolderId = await _getOrCreateFolder(_folderName);
      return _rootFolderId != null;
    } catch (e) {
      debugPrint('GoogleDriveService init error: $e');
      return false;
    }
  }

  /// Check if authenticated and ready
  bool get isReady => _driveApi != null && _rootFolderId != null;

  /// Get or create a folder by name
  Future<String?> _getOrCreateFolder(String name, {String? parentId}) async {
    if (_driveApi == null) return null;

    try {
      // Search for existing folder
      String query = "name = '$name' and mimeType = 'application/vnd.google-apps.folder' and trashed = false";
      if (parentId != null) {
        query += " and '$parentId' in parents";
      }

      final fileList = await _driveApi!.files.list(
        q: query,
        spaces: 'drive',
      );

      if (fileList.files != null && fileList.files!.isNotEmpty) {
        return fileList.files!.first.id;
      }

      // Create folder
      final folder = drive.File()
        ..name = name
        ..mimeType = 'application/vnd.google-apps.folder';
      
      if (parentId != null) {
        folder.parents = [parentId];
      }

      final createdFolder = await _driveApi!.files.create(folder);
      return createdFolder.id;
    } catch (e) {
      debugPrint('Error creating folder $name: $e');
      return null;
    }
  }

  /// Upload a file to Drive
  Future<String?> uploadFile(
    File localFile,
    String fileName, {
    String? parentFolderId,
    String? mimeType,
  }) async {
    if (_driveApi == null || _rootFolderId == null) return null;

    try {
      final targetParent = parentFolderId ?? _rootFolderId!;
      
      // Check if file already exists
      final existingFileId = await _findFile(fileName, parentId: targetParent);
      
      final driveFile = drive.File()
        ..name = fileName;
      
      if (existingFileId == null) {
        driveFile.parents = [targetParent];
      }

      final media = drive.Media(
        localFile.openRead(),
        await localFile.length(),
      );

      drive.File result;
      if (existingFileId != null) {
        // Update existing file
        result = await _driveApi!.files.update(
          driveFile,
          existingFileId,
          uploadMedia: media,
        );
      } else {
        // Create new file
        result = await _driveApi!.files.create(
          driveFile,
          uploadMedia: media,
        );
      }

      return result.id;
    } catch (e) {
      debugPrint('Error uploading file $fileName: $e');
      return null;
    }
  }

  /// Download a file from Drive
  Future<File?> downloadFile(String fileId, String localPath) async {
    if (_driveApi == null) return null;

    try {
      final media = await _driveApi!.files.get(
        fileId,
        downloadOptions: drive.DownloadOptions.fullMedia,
      ) as drive.Media;

      final file = File(localPath);
      final sink = file.openWrite();
      
      await media.stream.pipe(sink);
      await sink.close();
      
      return file;
    } catch (e) {
      debugPrint('Error downloading file $fileId: $e');
      return null;
    }
  }

  /// Find a file by name
  Future<String?> _findFile(String name, {String? parentId}) async {
    if (_driveApi == null) return null;

    try {
      String query = "name = '$name' and trashed = false";
      if (parentId != null) {
        query += " and '$parentId' in parents";
      }

      final fileList = await _driveApi!.files.list(
        q: query,
        spaces: 'drive',
      );

      if (fileList.files != null && fileList.files!.isNotEmpty) {
        return fileList.files!.first.id;
      }
      return null;
    } catch (e) {
      debugPrint('Error finding file $name: $e');
      return null;
    }
  }

  /// Delete a file from Drive
  Future<bool> deleteFile(String fileId) async {
    if (_driveApi == null) return false;

    try {
      await _driveApi!.files.delete(fileId);
      return true;
    } catch (e) {
      debugPrint('Error deleting file $fileId: $e');
      return false;
    }
  }

  /// Upload JSON metadata
  Future<String?> uploadMetadata(Map<String, dynamic> data, String fileName) async {
    if (_driveApi == null || _rootFolderId == null) return null;

    try {
      final jsonString = jsonEncode(data);
      final bytes = utf8.encode(jsonString);
      
      final existingFileId = await _findFile(fileName, parentId: _rootFolderId);
      
      final driveFile = drive.File()
        ..name = fileName
        ..mimeType = 'application/json';
      
      if (existingFileId == null) {
        driveFile.parents = [_rootFolderId!];
      }

      final media = drive.Media(
        Stream.value(bytes),
        bytes.length,
      );

      drive.File result;
      if (existingFileId != null) {
        result = await _driveApi!.files.update(
          driveFile,
          existingFileId,
          uploadMedia: media,
        );
      } else {
        result = await _driveApi!.files.create(
          driveFile,
          uploadMedia: media,
        );
      }

      return result.id;
    } catch (e) {
      debugPrint('Error uploading metadata: $e');
      return null;
    }
  }

  /// Download and parse JSON metadata
  Future<Map<String, dynamic>?> downloadMetadata(String fileName) async {
    if (_driveApi == null || _rootFolderId == null) return null;

    try {
      final fileId = await _findFile(fileName, parentId: _rootFolderId);
      if (fileId == null) return null;

      final media = await _driveApi!.files.get(
        fileId,
        downloadOptions: drive.DownloadOptions.fullMedia,
      ) as drive.Media;

      final bytes = <int>[];
      await for (final chunk in media.stream) {
        bytes.addAll(chunk);
      }

      final jsonString = utf8.decode(bytes);
      return jsonDecode(jsonString) as Map<String, dynamic>;
    } catch (e) {
      debugPrint('Error downloading metadata: $e');
      return null;
    }
  }

  /// Get exercises folder ID
  Future<String?> getExercisesFolderId() async {
    if (_rootFolderId == null) return null;
    return await _getOrCreateFolder(_exercisesFolderName, parentId: _rootFolderId);
  }

  /// Get sessions folder ID
  Future<String?> getSessionsFolderId() async {
    if (_rootFolderId == null) return null;
    return await _getOrCreateFolder(_sessionsFolderName, parentId: _rootFolderId);
  }

  /// List all files in MotionCoach folder
  Future<List<drive.File>> listAllFiles() async {
    if (_driveApi == null || _rootFolderId == null) return [];

    try {
      final fileList = await _driveApi!.files.list(
        q: "'$_rootFolderId' in parents and trashed = false",
        spaces: 'drive',
      );

      return fileList.files ?? [];
    } catch (e) {
      debugPrint('Error listing files: $e');
      return [];
    }
  }

  /// Get storage quota info
  Future<Map<String, int>?> getStorageQuota() async {
    if (_driveApi == null) return null;

    try {
      final about = await _driveApi!.about.get($fields: 'storageQuota');
      final quota = about.storageQuota;
      
      if (quota != null) {
        return {
          'limit': int.tryParse(quota.limit ?? '0') ?? 0,
          'usage': int.tryParse(quota.usage ?? '0') ?? 0,
          'usageInDrive': int.tryParse(quota.usageInDrive ?? '0') ?? 0,
        };
      }
      return null;
    } catch (e) {
      debugPrint('Error getting storage quota: $e');
      return null;
    }
  }
}
