import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:lucide_icons/lucide_icons.dart';

import 'theme/mocha_colors.dart';
import 'views/dashboard_view.dart';

void main() {
  runApp(const R0mmApp());
}

class R0mmApp extends StatelessWidget {
  const R0mmApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'R0MM',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        scaffoldBackgroundColor: MochaColors.base,
        colorScheme: const ColorScheme.dark(
          primary: MochaColors.mauve,
          surface: MochaColors.base,
          onSurface: MochaColors.text,
        ),
        textTheme: GoogleFonts.interTextTheme().apply(
          bodyColor: MochaColors.text,
          displayColor: MochaColors.text,
        ),
      ),
      home: const MainLayout(),
    );
  }
}

enum AppView {
  dashboard('Dashboard', LucideIcons.layoutDashboard),
  library('Library', LucideIcons.library),
  importScan('Import & Scan', LucideIcons.folderSearch),
  downloads('Downloads', LucideIcons.download),
  toolsLogs('Tools & Logs', LucideIcons.wrench);

  const AppView(this.label, this.icon);

  final String label;
  final IconData icon;
}

class MainLayout extends StatefulWidget {
  const MainLayout({super.key});

  @override
  State<MainLayout> createState() => _MainLayoutState();
}

class _MainLayoutState extends State<MainLayout> {
  AppView _activeView = AppView.dashboard;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Row(
        children: [
          Container(
            width: 250,
            decoration: const BoxDecoration(
              color: MochaColors.mantle,
              border: Border(right: BorderSide(color: MochaColors.surface1)),
            ),
            padding: const EdgeInsets.fromLTRB(18, 24, 18, 20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      width: 36,
                      height: 36,
                      decoration: BoxDecoration(
                        color: MochaColors.mauve.withOpacity(0.2),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: const Icon(
                        LucideIcons.gamepad2,
                        color: MochaColors.mauve,
                        size: 20,
                      ),
                    ),
                    const SizedBox(width: 10),
                    Text(
                      'R0MM',
                      style: GoogleFonts.outfit(
                        color: MochaColors.text,
                        fontWeight: FontWeight.w700,
                        fontSize: 24,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 28),
                ...AppView.values.map(
                  (view) => Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: _NavItem(
                      view: view,
                      active: _activeView == view,
                      onTap: () => setState(() => _activeView = view),
                    ),
                  ),
                ),
                const Spacer(),
                Text(
                  'Backend: http://127.0.0.1:5000/api',
                  style: GoogleFonts.inter(
                    color: MochaColors.subtext0,
                    fontSize: 12,
                  ),
                ),
              ],
            ),
          ),
          Expanded(child: _buildCurrentView()),
        ],
      ),
    );
  }

  Widget _buildCurrentView() {
    switch (_activeView) {
      case AppView.dashboard:
        return const DashboardView();
      case AppView.library:
        return const _LibraryView();
      case AppView.importScan:
        return const _SimplePlaceholder(title: 'Import & Scan');
      case AppView.downloads:
        return const _SimplePlaceholder(title: 'Downloads');
      case AppView.toolsLogs:
        return const _SimplePlaceholder(title: 'Tools & Logs');
    }
  }
}

class _NavItem extends StatefulWidget {
  const _NavItem({
    required this.view,
    required this.active,
    required this.onTap,
  });

  final AppView view;
  final bool active;
  final VoidCallback onTap;

  @override
  State<_NavItem> createState() => _NavItemState();
}

class _NavItemState extends State<_NavItem> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final isHighlighted = widget.active || _hovered;
    return MouseRegion(
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() => _hovered = false),
      child: GestureDetector(
        onTap: widget.onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 180),
          curve: Curves.easeOut,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
          decoration: BoxDecoration(
            color: widget.active
                ? MochaColors.mauve.withOpacity(0.16)
                : isHighlighted
                    ? MochaColors.surface0.withOpacity(0.6)
                    : Colors.transparent,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(
              color: widget.active
                  ? MochaColors.mauve.withOpacity(0.7)
                  : isHighlighted
                      ? MochaColors.surface1.withOpacity(0.9)
                      : Colors.transparent,
            ),
          ),
          child: Row(
            children: [
              Icon(
                widget.view.icon,
                size: 18,
                color: widget.active ? MochaColors.mauve : MochaColors.subtext0,
              ),
              const SizedBox(width: 10),
              Text(
                widget.view.label,
                style: GoogleFonts.inter(
                  color: widget.active ? MochaColors.text : MochaColors.subtext0,
                  fontWeight: widget.active ? FontWeight.w600 : FontWeight.w500,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _LibraryView extends StatefulWidget {
  const _LibraryView();

  @override
  State<_LibraryView> createState() => _LibraryViewState();
}

class _LibraryViewState extends State<_LibraryView> {
  final _searchController = TextEditingController();

  final List<Map<String, String>> _games = List.generate(
    12,
    (index) => {
      'name': 'Game #${index + 1}',
      'region': index.isEven ? 'USA' : 'EUR',
    },
  );

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(28),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            constraints: const BoxConstraints(maxWidth: 460),
            child: TextField(
              controller: _searchController,
              style: GoogleFonts.inter(color: MochaColors.text),
              decoration: InputDecoration(
                hintText: 'Search games, systems or region...',
                hintStyle: GoogleFonts.inter(color: MochaColors.subtext0),
                prefixIcon: const Icon(LucideIcons.search, size: 18),
                filled: true,
                fillColor: MochaColors.surface0.withOpacity(0.55),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(16),
                  borderSide: const BorderSide(color: MochaColors.surface1),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(16),
                  borderSide: const BorderSide(color: MochaColors.surface1),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(16),
                  borderSide: const BorderSide(color: MochaColors.mauve),
                ),
              ),
            ),
          ),
          const SizedBox(height: 18),
          Expanded(
            child: GridView.builder(
              itemCount: _games.length,
              gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                maxCrossAxisExtent: 230,
                mainAxisSpacing: 14,
                crossAxisSpacing: 14,
                childAspectRatio: 1.25,
              ),
              itemBuilder: (context, index) {
                final game = _games[index];
                return Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: MochaColors.surface0.withOpacity(0.5),
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(color: MochaColors.surface1.withOpacity(0.9)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 10,
                          vertical: 6,
                        ),
                        decoration: BoxDecoration(
                          color: MochaColors.blue.withOpacity(0.2),
                          borderRadius: BorderRadius.circular(999),
                        ),
                        child: Text(
                          game['region']!,
                          style: GoogleFonts.inter(
                            color: MochaColors.blue,
                            fontWeight: FontWeight.w700,
                            fontSize: 12,
                          ),
                        ),
                      ),
                      const Spacer(),
                      Text(
                        game['name']!,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: GoogleFonts.outfit(
                          color: MochaColors.text,
                          fontSize: 18,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _SimplePlaceholder extends StatelessWidget {
  const _SimplePlaceholder({required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Text(
        '$title view in progress',
        style: GoogleFonts.outfit(
          color: MochaColors.subtext0,
          fontSize: 24,
          fontWeight: FontWeight.w500,
        ),
      ),
    );
  }
}
