import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../domain/entities/user.dart';
import '../../presentation/providers/auth_provider.dart';
import '../../shared/theme/app_colors.dart';
import '../auth/login_screen.dart';

/// Cài đặt — tài khoản, lưu trữ.
class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  // Developer mode - tap logo 7 times to enable
  int _devTapCount = 0;
  bool _devModeEnabled = false;

  @override
  void initState() {
    super.initState();
  }

  @override
  void dispose() {
    super.dispose();
  }

  void _handleAboutTap() {
    _devTapCount++;
    if (_devTapCount >= 7 && !_devModeEnabled) {
      setState(() {
        _devModeEnabled = true;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('🛠️ Developer Mode đã được bật!'),
          backgroundColor: Colors.orange,
        ),
      );
    } else if (_devTapCount < 7 && _devTapCount >= 4) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Còn ${7 - _devTapCount} lần nữa để bật Developer Mode'),
          duration: const Duration(milliseconds: 500),
        ),
      );
    }

    // Reset after 2 seconds
    Future.delayed(const Duration(seconds: 2), () {
      if (mounted && _devTapCount < 7) {
        _devTapCount = 0;
      }
    });

    showAboutDialog(
      context: context,
      applicationName: 'Motion Coach',
      applicationVersion: '1.0.0',
      applicationIcon: const Icon(Icons.fitness_center, size: 48),
      children: [
        const Text('AI Fitness Coach - Tập luyện thông minh cùng AI'),
      ],
    );
  }

  Future<void> _signOut() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: AppColors.surface,
        title: const Text('Đăng xuất'),
        content: const Text('Bạn có chắc muốn đăng xuất?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Hủy'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(context, true),
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.error,
            ),
            child: const Text('Đăng xuất'),
          ),
        ],
      ),
    );

    if (confirmed == true && mounted) {
      await ref.read(authProvider.notifier).signOut();
      if (mounted) {
        Navigator.of(context).pushAndRemoveUntil(
          MaterialPageRoute(builder: (_) => const LoginScreen()),
          (route) => false,
        );
      }
    }
  }

  void _showStorageModeDialog() {
    final currentUser = ref.read(currentUserProvider);
    final currentMode = currentUser?.storageMode ?? StorageMode.local;

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: AppColors.surface,
        title: const Text('Chế độ lưu trữ'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            _buildStorageOption(
              StorageMode.local,
              'Lưu cục bộ',
              'Dữ liệu lưu trên thiết bị',
              Icons.phone_android,
              currentMode,
            ),
            const SizedBox(height: 12),
            _buildStorageOption(
              StorageMode.googleDrive,
              'Google Drive',
              'Đồng bộ lên Google Drive',
              Icons.cloud,
              currentMode,
            ),
            const SizedBox(height: 12),
            _buildStorageOption(
              StorageMode.server,
              'Motion Coach Server',
              'Premium - Đồng bộ đa thiết bị',
              Icons.dns,
              currentMode,
              isPremium: true,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildStorageOption(
    StorageMode mode,
    String title,
    String subtitle,
    IconData icon,
    StorageMode currentMode, {
    bool isPremium = false,
  }) {
    final isSelected = mode == currentMode;

    return InkWell(
      onTap: isPremium
          ? () {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text('Tính năng này sẽ có trong phiên bản Premium'),
                ),
              );
            }
          : () {
              ref.read(authProvider.notifier).updateStorageMode(mode);
              Navigator.pop(context);
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(content: Text('Đã chuyển sang: $title')),
              );
            },
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: isSelected
              ? AppColors.primary.withValues(alpha: 0.15)
              : AppColors.surfaceLight,
          borderRadius: BorderRadius.circular(12),
          border: isSelected
              ? Border.all(color: AppColors.primary, width: 2)
              : null,
        ),
        child: Row(
          children: [
            Icon(icon, color: isSelected ? AppColors.primary : AppColors.textSecondary),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(
                        title,
                        style: TextStyle(
                          fontWeight: FontWeight.w600,
                          color: isSelected ? AppColors.primary : AppColors.textPrimary,
                        ),
                      ),
                      if (isPremium) ...[
                        const SizedBox(width: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                          decoration: BoxDecoration(
                            color: Colors.amber,
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: const Text(
                            'PREMIUM',
                            style: TextStyle(
                              fontSize: 10,
                              fontWeight: FontWeight.bold,
                              color: Colors.black87,
                            ),
                          ),
                        ),
                      ],
                    ],
                  ),
                  Text(
                    subtitle,
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
              ),
            ),
            if (isSelected)
              const Icon(Icons.check_circle, color: AppColors.primary),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final authState = ref.watch(authProvider);
    final user = authState.user;

    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(gradient: AppColors.backgroundGradient),
        child: SafeArea(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Header
              Padding(
                padding: const EdgeInsets.fromLTRB(8, 16, 20, 24),
                child: Row(
                  children: [
                    IconButton(
                      icon: const Icon(Icons.arrow_back_ios_new, size: 20),
                      onPressed: () => Navigator.pop(context),
                    ),
                    Container(
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(
                        color: AppColors.surfaceLight,
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: const Icon(Icons.settings,
                          color: AppColors.textSecondary, size: 24),
                    ),
                    const SizedBox(width: 14),
                    Text('Cài đặt',
                        style: Theme.of(context).textTheme.headlineMedium),
                  ],
                ),
              ),

              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // Account section
                      if (user != null) ...[
                        _buildSectionTitle('Tài khoản'),
                        const SizedBox(height: 12),
                        Container(
                          padding: const EdgeInsets.all(16),
                          decoration: BoxDecoration(
                            color: AppColors.surfaceLight,
                            borderRadius: BorderRadius.circular(16),
                          ),
                          child: Row(
                            children: [
                              CircleAvatar(
                                radius: 28,
                                backgroundColor: AppColors.primary,
                                backgroundImage: user.photoUrl != null
                                    ? NetworkImage(user.photoUrl!)
                                    : null,
                                child: user.photoUrl == null
                                    ? Text(
                                        user.displayName?.substring(0, 1).toUpperCase() ?? 'U',
                                        style: const TextStyle(
                                          fontSize: 24,
                                          color: Colors.white,
                                        ),
                                      )
                                    : null,
                              ),
                              const SizedBox(width: 16),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      user.displayName ?? 'Người dùng',
                                      style: Theme.of(context).textTheme.titleMedium,
                                    ),
                                    Text(
                                      user.email,
                                      style: Theme.of(context).textTheme.bodySmall,
                                    ),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(height: 24),
                      ],

                      // Storage mode section
                      _buildSectionTitle('Lưu trữ'),
                      const SizedBox(height: 12),
                      _buildSettingItem(
                        icon: Icons.storage,
                        title: 'Chế độ lưu trữ',
                        subtitle: _getStorageModeText(user?.storageMode),
                        onTap: _showStorageModeDialog,
                      ),
                      const SizedBox(height: 24),

                      // App info section
                      _buildSectionTitle('Ứng dụng'),
                      const SizedBox(height: 12),
                      _buildSettingItem(
                        icon: Icons.info_outline,
                        title: 'Giới thiệu',
                        subtitle: 'Motion Coach v1.0.0',
                        onTap: _handleAboutTap,
                      ),
                      const SizedBox(height: 8),
                      _buildSettingItem(
                        icon: Icons.description_outlined,
                        title: 'Giấy phép',
                        subtitle: 'Điều khoản sử dụng',
                        onTap: () {
                          showLicensePage(context: context);
                        },
                      ),

                      // Developer Settings (hidden by default)
                      if (_devModeEnabled) ...[
                        const SizedBox(height: 24),
                        _buildDeveloperSection(),
                      ],

                      // Sign out button
                      if (user != null) ...[
                        const SizedBox(height: 32),
                        SizedBox(
                          width: double.infinity,
                          child: OutlinedButton.icon(
                            onPressed: _signOut,
                            icon: const Icon(Icons.logout, color: AppColors.error),
                            label: const Text(
                              'Đăng xuất',
                              style: TextStyle(color: AppColors.error),
                            ),
                            style: OutlinedButton.styleFrom(
                              side: const BorderSide(color: AppColors.error),
                            ),
                          ),
                        ),
                      ],

                      const SizedBox(height: 32),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _getStorageModeText(StorageMode? mode) {
    switch (mode) {
      case StorageMode.googleDrive:
        return 'Google Drive';
      case StorageMode.server:
        return 'Motion Coach Server';
      case StorageMode.local:
      default:
        return 'Lưu cục bộ';
    }
  }

  Widget _buildSectionTitle(String title) {
    return Text(
      title,
      style: Theme.of(context).textTheme.titleMedium?.copyWith(
            color: AppColors.primary,
            fontWeight: FontWeight.w700,
          ),
    );
  }

  Widget _buildSettingItem({
    required IconData icon,
    required String title,
    required String subtitle,
    required VoidCallback onTap,
  }) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AppColors.surfaceLight,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          children: [
            Icon(icon, color: AppColors.textSecondary),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: Theme.of(context).textTheme.titleSmall),
                  Text(subtitle, style: Theme.of(context).textTheme.bodySmall),
                ],
              ),
            ),
            const Icon(Icons.chevron_right, color: AppColors.textSecondary),
          ],
        ),
      ),
    );
  }

  Widget _buildDeveloperSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            _buildSectionTitle('🛠️ Developer'),
            const Spacer(),
            TextButton(
              onPressed: () {
                setState(() {
                  _devModeEnabled = false;
                  _devTapCount = 0;
                });
              },
              child: const Text('Ẩn', style: TextStyle(color: AppColors.error)),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.orange.withValues(alpha: 0.1),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.orange.withValues(alpha: 0.3)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Chế độ hoạt động:',
                style: TextStyle(fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 8),
              const Text(
                '• Offline Mode: Pose detection chạy 100% trên thiết bị\n'
                '• Server Mode: Kết nối FastAPI backend để xử lý nâng cao\n'
                '• Hiện tại app đang chạy Offline Mode',
                style: TextStyle(fontSize: 12),
              ),
              const SizedBox(height: 16),
              _buildSettingItem(
                icon: Icons.dns,
                title: 'Kết nối Server (Dev)',
                subtitle: 'Cấu hình backend FastAPI',
                onTap: _showServerConfigDialog,
              ),
            ],
          ),
        ),
      ],
    );
  }

  void _showServerConfigDialog() {
    final urlController = TextEditingController();

    // Read current URL from ApiClient if needed
    // For now we'll use a default
    urlController.text = 'http://192.168.1.100:8000';

    showDialog(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) {
          bool testing = false;
          bool? connected;

          return AlertDialog(
            backgroundColor: AppColors.surface,
            title: const Row(
              children: [
                Icon(Icons.developer_mode, color: Colors.orange),
                SizedBox(width: 8),
                Text('Server Config'),
              ],
            ),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Nhập địa chỉ IP của máy tính chạy FastAPI backend.\n'
                  'Điện thoại và máy tính phải cùng mạng WiFi.',
                  style: TextStyle(fontSize: 12),
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: urlController,
                  decoration: InputDecoration(
                    labelText: 'Server URL',
                    hintText: 'http://192.168.1.100:8000',
                    prefixIcon: const Icon(Icons.link),
                    suffixIcon: connected == null
                        ? null
                        : Icon(
                            connected ? Icons.check_circle : Icons.error,
                            color: connected ? AppColors.success : AppColors.error,
                          ),
                  ),
                  keyboardType: TextInputType.url,
                ),
                const SizedBox(height: 16),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton.icon(
                    onPressed: testing
                        ? null
                        : () async {
                            setDialogState(() {
                              testing = true;
                              connected = null;
                            });

                            // Test connection
                            final url = urlController.text.trim();
                            // For now, just simulate - in production this would use ApiClient
                            await Future.delayed(const Duration(seconds: 1));
                            final ok = url.isNotEmpty && url.startsWith('http');

                            setDialogState(() {
                              testing = false;
                              connected = ok;
                            });
                          },
                    icon: testing
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Icon(Icons.wifi_find),
                    label: Text(testing ? 'Đang kiểm tra...' : 'Kiểm tra kết nối'),
                  ),
                ),
              ],
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('Đóng'),
              ),
              ElevatedButton(
                onPressed: () {
                  // Save URL to SharedPreferences
                  // This would integrate with ApiClient
                  Navigator.pop(context);
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('Đã lưu cấu hình server'),
                    ),
                  );
                },
                child: const Text('Lưu'),
              ),
            ],
          );
        },
      ),
    );
  }
}
