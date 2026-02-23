import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:lucide_icons/lucide_icons.dart';
import '../theme/mocha_colors.dart';

class DashboardView extends StatelessWidget {
  const DashboardView({super.key});

  @override
  Widget build(BuildContext context) {
    const stats = [
      _StatData(
        label: 'DAT Files',
        value: '128',
        icon: LucideIcons.fileArchive,
        accent: MochaColors.blue,
      ),
      _StatData(
        label: 'Identified',
        value: '14,382',
        icon: LucideIcons.badgeCheck,
        accent: MochaColors.green,
      ),
      _StatData(
        label: 'Unidentified',
        value: '241',
        icon: LucideIcons.alertTriangle,
        accent: MochaColors.peach,
      ),
      _StatData(
        label: 'Total',
        value: '14,623',
        icon: LucideIcons.database,
        accent: MochaColors.mauve,
      ),
    ];

    return SingleChildScrollView(
      padding: const EdgeInsets.all(28),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Welcome to R0MM',
            style: GoogleFonts.outfit(
              fontSize: 38,
              fontWeight: FontWeight.w700,
              color: MochaColors.text,
              letterSpacing: -0.8,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            'Manage your retro-gaming ROM collection with precision.',
            style: GoogleFonts.inter(
              fontSize: 15,
              color: MochaColors.subtext0,
            ),
          ),
          const SizedBox(height: 20),
          ElevatedButton.icon(
            onPressed: () {},
            icon: const Icon(LucideIcons.sparkles, size: 18),
            label: Text(
              'Nova Sessão',
              style: GoogleFonts.inter(fontWeight: FontWeight.w600),
            ),
            style: ElevatedButton.styleFrom(
              backgroundColor: MochaColors.mauve,
              foregroundColor: MochaColors.crust,
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(14),
              ),
            ),
          ),
          const SizedBox(height: 30),
          Wrap(
            spacing: 16,
            runSpacing: 16,
            children: stats
                .map((stat) => SizedBox(
                      width: 300,
                      child: _StatCard(data: stat),
                    ))
                .toList(),
          ),
        ],
      ),
    );
  }
}

class _StatCard extends StatelessWidget {
  const _StatCard({required this.data});

  final _StatData data;

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(18),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 14, sigmaY: 14),
        child: Container(
          padding: const EdgeInsets.all(20),
          decoration: BoxDecoration(
            color: MochaColors.surface0.withOpacity(0.6),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: MochaColors.surface1.withOpacity(0.8)),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withOpacity(0.25),
                blurRadius: 20,
                offset: const Offset(0, 8),
              ),
            ],
          ),
          child: Row(
            children: [
              Container(
                width: 46,
                height: 46,
                decoration: BoxDecoration(
                  color: data.accent.withOpacity(0.18),
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Icon(data.icon, color: data.accent, size: 22),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      data.label,
                      style: GoogleFonts.inter(
                        color: MochaColors.subtext0,
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      data.value,
                      style: GoogleFonts.outfit(
                        color: MochaColors.text,
                        fontSize: 28,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _StatData {
  const _StatData({
    required this.label,
    required this.value,
    required this.icon,
    required this.accent,
  });

  final String label;
  final String value;
  final IconData icon;
  final Color accent;
}
