import 'package:flutter/material.dart';

/// App color palette — premium dark theme with vibrant accents.
class AppColors {
  // Background layers
  static const Color background = Color(0xFF0D0D1A);
  static const Color surface = Color(0xFF1A1A2E);
  static const Color surfaceLight = Color(0xFF252542);
  static const Color surfaceCard = Color(0xFF16213E);
  static const Color surfaceVariant = Color(0xFF1E1E36);

  // Card styles
  static const Color cardBackground = Color(0xFF1A1A2E);
  static const Color cardBorder = Color(0xFF2A2A4E);

  // Primary gradient
  static const Color primary = Color(0xFF6C63FF);
  static const Color primaryLight = Color(0xFF8B83FF);
  static const Color primaryDark = Color(0xFF4A42D4);

  // Accent / secondary
  static const Color accent = Color(0xFF00D4AA);
  static const Color accentLight = Color(0xFF33DDBB);

  // Status colors
  static const Color success = Color(0xFF00E676);
  static const Color warning = Color(0xFFFFAB40);
  static const Color error = Color(0xFFFF5252);
  static const Color info = Color(0xFF40C4FF);

  // Text
  static const Color textPrimary = Color(0xFFF5F5F5);
  static const Color textSecondary = Color(0xFFB0B0CC);
  static const Color textHint = Color(0xFF6B6B8D);

  // Readiness states
  static const Color readinessGood = Color(0xFF00E676);
  static const Color readinessWarn = Color(0xFFFFAB40);
  static const Color readinessBad = Color(0xFFFF5252);

  // Skeleton overlay
  static const Color skeletonLine = Color(0xFF00D4AA);
  static const Color skeletonJoint = Color(0xFF6C63FF);
  static const Color skeletonJointLow = Color(0xFFFF5252);

  // Gradients
  static const LinearGradient primaryGradient = LinearGradient(
    colors: [primary, Color(0xFF00D4AA)],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
  );

  static const LinearGradient cardGradient = LinearGradient(
    colors: [surfaceCard, Color(0xFF1A1A3E)],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
  );

  static const LinearGradient backgroundGradient = LinearGradient(
    colors: [background, Color(0xFF0A0A14)],
    begin: Alignment.topCenter,
    end: Alignment.bottomCenter,
  );
}
