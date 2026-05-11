import 'package:flutter/material.dart';
import 'dart:math';

import '../../core/models/template.dart';
import '../../core/storage/template_storage.dart';
import '../../shared/theme/app_colors.dart';

/// Screen to create a new workout template.
class AddTemplateScreen extends StatefulWidget {
  const AddTemplateScreen({super.key});

  @override
  State<AddTemplateScreen> createState() => _AddTemplateScreenState();
}

class _AddTemplateScreenState extends State<AddTemplateScreen> {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _notesController = TextEditingController();
  String _mode = 'reps';
  bool _saving = false;

  @override
  void dispose() {
    _nameController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  Future<void> _saveTemplate() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() => _saving = true);

    // Generate unique ID
    final timestamp = DateTime.now().millisecondsSinceEpoch;
    final random = Random().nextInt(1000);
    final templateId = 'local-$timestamp-$random';

    final template = WorkoutTemplate(
      templateId: templateId,
      name: _nameController.text.trim(),
      mode: _mode,
      videoUri: 'https://flutter.github.io/assets-for-api-docs/assets/videos/butterfly.mp4',
      notes: _notesController.text.trim().isEmpty
          ? null
          : _notesController.text.trim(),
      trimStartSec: 0,
      trimEndSec: 10,
    );

    await TemplateStorage.addTemplate(template);

    if (!mounted) return;

    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Row(
          children: [
            Icon(Icons.check_circle, color: Colors.white),
            SizedBox(width: 12),
            Text('Đã thêm bài tập: ${template.name}'),
          ],
        ),
        backgroundColor: AppColors.success,
      ),
    );

    Navigator.of(context).pop(true); // Return true to refresh library
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(gradient: AppColors.backgroundGradient),
        child: SafeArea(
          child: Column(
            children: [
              // Header
              Padding(
                padding: const EdgeInsets.fromLTRB(8, 16, 20, 24),
                child: Row(
                  children: [
                    IconButton(
                      icon: const Icon(Icons.close, size: 24),
                      onPressed: () => Navigator.pop(context),
                    ),
                    Container(
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(
                        gradient: AppColors.primaryGradient,
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: const Icon(Icons.add, color: Colors.white, size: 24),
                    ),
                    const SizedBox(width: 14),
                    Text('Thêm bài tập mới',
                        style: Theme.of(context).textTheme.headlineMedium),
                  ],
                ),
              ),

              // Form
              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(20),
                  child: Form(
                    key: _formKey,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        _buildSectionTitle('Thông tin cơ bản'),
                        const SizedBox(height: 12),

                        // Name field
                        TextFormField(
                          controller: _nameController,
                          decoration: InputDecoration(
                            labelText: 'Tên bài tập *',
                            hintText: 'VD: Squat, Push-up, Plank...',
                            prefixIcon: Icon(Icons.fitness_center),
                          ),
                          validator: (value) {
                            if (value == null || value.trim().isEmpty) {
                              return 'Vui lòng nhập tên bài tập';
                            }
                            return null;
                          },
                        ),
                        const SizedBox(height: 16),

                        // Mode selection
                        Text('Chế độ tập *',
                            style: Theme.of(context).textTheme.titleSmall),
                        const SizedBox(height: 8),
                        Row(
                          children: [
                            Expanded(
                              child: _buildModeCard(
                                icon: Icons.repeat,
                                label: 'Đếm rep',
                                value: 'reps',
                                isSelected: _mode == 'reps',
                              ),
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: _buildModeCard(
                                icon: Icons.timer,
                                label: 'Giữ tư thế',
                                value: 'hold',
                                isSelected: _mode == 'hold',
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 24),

                        // Notes field
                        _buildSectionTitle('Ghi chú (tùy chọn)'),
                        const SizedBox(height: 12),
                        TextFormField(
                          controller: _notesController,
                          decoration: InputDecoration(
                            labelText: 'Mô tả bài tập',
                            hintText: 'VD: Tập chân, lưng thẳng...',
                            prefixIcon: Icon(Icons.notes),
                          ),
                          maxLines: 3,
                        ),
                        const SizedBox(height: 24),

                        // Video info
                        Container(
                          padding: const EdgeInsets.all(16),
                          decoration: BoxDecoration(
                            color: AppColors.accent.withValues(alpha: 0.1),
                            borderRadius: BorderRadius.circular(12),
                            border: Border.all(
                              color: AppColors.accent.withValues(alpha: 0.3),
                            ),
                          ),
                          child: Row(
                            children: [
                              Icon(Icons.info_outline,
                                  color: AppColors.accent, size: 20),
                              SizedBox(width: 12),
                              Expanded(
                                child: Text(
                                  'Video demo sẽ dùng video mẫu. Trong tương lai sẽ có thể quay video hoặc chọn từ thư viện.',
                                  style: TextStyle(
                                    fontSize: 12,
                                    color: AppColors.textSecondary,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),

              // Save button
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
                child: SizedBox(
                  width: double.infinity,
                  height: 56,
                  child: ElevatedButton(
                    onPressed: _saving ? null : _saveTemplate,
                    style: ElevatedButton.styleFrom(
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(16),
                      ),
                    ),
                    child: _saving
                        ? const SizedBox(
                            width: 24,
                            height: 24,
                            child: CircularProgressIndicator(
                              color: Colors.white,
                              strokeWidth: 2.5,
                            ),
                          )
                        : const Row(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Icon(Icons.save, size: 24),
                              SizedBox(width: 8),
                              Text('Lưu bài tập',
                                  style: TextStyle(
                                      fontSize: 17,
                                      fontWeight: FontWeight.w700)),
                            ],
                          ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
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

  Widget _buildModeCard({
    required IconData icon,
    required String label,
    required String value,
    required bool isSelected,
  }) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: () => setState(() => _mode = value),
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: isSelected
                ? AppColors.primary.withValues(alpha: 0.15)
                : AppColors.surfaceLight,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(
              color: isSelected
                  ? AppColors.primary
                  : AppColors.primary.withValues(alpha: 0.1),
              width: isSelected ? 2 : 1,
            ),
          ),
          child: Column(
            children: [
              Icon(
                icon,
                color: isSelected ? AppColors.primary : AppColors.textSecondary,
                size: 32,
              ),
              const SizedBox(height: 8),
              Text(
                label,
                style: TextStyle(
                  fontSize: 14,
                  fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
                  color: isSelected ? AppColors.primary : AppColors.textSecondary,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
