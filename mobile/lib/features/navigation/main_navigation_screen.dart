import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../shared/theme/app_colors.dart';
import '../history/history_screen.dart';
import '../home/home_screen.dart';
import '../lessons/lessons_screen.dart';
import '../library/library_screen.dart';
import '../settings/settings_screen.dart';

/// Provider để quản lý tab index hiện tại
final currentTabIndexProvider = StateProvider<int>((ref) => 0);

/// Main navigation screen với Bottom Navigation Bar
/// 5 tabs: Trang chính, Kho bài tập, Giáo án, Đã hoàn thành, Cài đặt
class MainNavigationScreen extends ConsumerStatefulWidget {
  const MainNavigationScreen({super.key});

  @override
  ConsumerState<MainNavigationScreen> createState() =>
      _MainNavigationScreenState();
}

class _MainNavigationScreenState extends ConsumerState<MainNavigationScreen> {
  // Cache screens để không rebuild khi switch tabs
  late final List<Widget> _screens;
  
  // Page controller for swiping between tabs (optional)
  late final PageController _pageController;

  @override
  void initState() {
    super.initState();
    _pageController = PageController();
    _screens = const [
      HomeScreen(),
      LibraryScreen(),
      LessonsScreen(),
      HistoryScreen(),
      SettingsScreen(),
    ];
  }

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  void _onTabTapped(int index) {
    ref.read(currentTabIndexProvider.notifier).state = index;
    _pageController.jumpToPage(index);
  }

  @override
  Widget build(BuildContext context) {
    final currentIndex = ref.watch(currentTabIndexProvider);

    return Scaffold(
      body: PageView(
        controller: _pageController,
        physics: const NeverScrollableScrollPhysics(), // Disable swipe
        children: _screens,
      ),
      bottomNavigationBar: _buildBottomNav(currentIndex),
    );
  }

  Widget _buildBottomNav(int currentIndex) {
    return Container(
      decoration: BoxDecoration(
        color: AppColors.cardBackground,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.3),
            blurRadius: 10,
            offset: const Offset(0, -2),
          ),
        ],
      ),
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: [
              _buildNavItem(
                index: 0,
                icon: Icons.home_outlined,
                activeIcon: Icons.home,
                label: 'Trang chính',
                isSelected: currentIndex == 0,
              ),
              _buildNavItem(
                index: 1,
                icon: Icons.fitness_center_outlined,
                activeIcon: Icons.fitness_center,
                label: 'Kho bài tập',
                isSelected: currentIndex == 1,
              ),
              _buildNavItem(
                index: 2,
                icon: Icons.list_alt_outlined,
                activeIcon: Icons.list_alt,
                label: 'Giáo án',
                isSelected: currentIndex == 2,
              ),
              _buildNavItem(
                index: 3,
                icon: Icons.check_circle_outline,
                activeIcon: Icons.check_circle,
                label: 'Đã xong',
                isSelected: currentIndex == 3,
              ),
              _buildNavItem(
                index: 4,
                icon: Icons.settings_outlined,
                activeIcon: Icons.settings,
                label: 'Cài đặt',
                isSelected: currentIndex == 4,
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildNavItem({
    required int index,
    required IconData icon,
    required IconData activeIcon,
    required String label,
    required bool isSelected,
  }) {
    return GestureDetector(
      onTap: () => _onTabTapped(index),
      behavior: HitTestBehavior.opaque,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: isSelected
              ? AppColors.primary.withValues(alpha: 0.15)
              : Colors.transparent,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              isSelected ? activeIcon : icon,
              size: 24,
              color: isSelected ? AppColors.primary : AppColors.textSecondary,
            ),
            const SizedBox(height: 4),
            Text(
              label,
              style: TextStyle(
                fontSize: 10,
                fontWeight: isSelected ? FontWeight.w600 : FontWeight.normal,
                color: isSelected ? AppColors.primary : AppColors.textSecondary,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
