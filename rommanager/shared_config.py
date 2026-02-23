"""
Shared configuration between GUI frontends.
Ensures consistency in column definitions, colors, strategy metadata, and labels.
"""

# Standardized column definitions for identified ROMs table
IDENTIFIED_COLUMNS = [
    {'id': 'original_file', 'label': 'Original File', 'width': 180},
    {'id': 'rom_name', 'label': 'ROM Name', 'width': 220},
    {'id': 'game_name', 'label': 'Game', 'width': 180},
    {'id': 'system', 'label': 'System', 'width': 120},
    {'id': 'region', 'label': 'Region', 'width': 80},
    {'id': 'size', 'label': 'Size', 'width': 80},
    {'id': 'crc32', 'label': 'CRC32', 'width': 80},
    {'id': 'status', 'label': 'Status', 'width': 70},
]

# Standardized column definitions for unidentified files table
UNIDENTIFIED_COLUMNS = [
    {'id': 'filename', 'label': 'Filename', 'width': 280},
    {'id': 'path', 'label': 'Path', 'width': 300},
    {'id': 'size', 'label': 'Size', 'width': 90},
    {'id': 'crc32', 'label': 'CRC32', 'width': 90},
]

# Standardized column definitions for missing ROMs table
MISSING_COLUMNS = [
    {'id': 'rom_name', 'label': 'ROM Name', 'width': 250},
    {'id': 'game_name', 'label': 'Game', 'width': 200},
    {'id': 'system', 'label': 'System', 'width': 120},
    {'id': 'region', 'label': 'Region', 'width': 80},
    {'id': 'size', 'label': 'Size', 'width': 80},
]

# ─── Unified Design Tokens (Catppuccin Mocha) ────────────────────────────────
THEME = {
    # Backgrounds
    "bg":       "#1e1e2e",   # base
    "bg_dim":   "#181825",   # mantle
    "bg_deep":  "#11111b",   # crust

    # Surfaces
    "surface0": "#313244",
    "surface1": "#45475a",
    "surface2": "#585b70",

    # Text hierarchy
    "text":     "#cdd6f4",
    "subtext1": "#bac2de",
    "subtext0": "#a6adc8",
    "overlay2": "#9399b2",
    "overlay1": "#7f849c",
    "overlay0": "#6c7086",

    # Semantic accents
    "primary":  "#cba6f7",   # mauve — primary actions, nav highlights
    "secondary":"#89b4fa",   # blue — secondary actions, links
    "success":  "#a6e3a1",   # green
    "warning":  "#f9e2af",   # yellow
    "error":    "#f38ba8",   # red
    "info":     "#94e2d5",   # teal

    # Extra accents (for region badges, special UI)
    "peach":    "#fab387",
    "pink":     "#f5c2e7",
    "sky":      "#89dceb",
    "lavender": "#b4befe",
    "flamingo": "#f2cdcd",
    "rosewater":"#f5e0dc",
    "maroon":   "#eba0ac",
    "sapphire": "#74c7ec",
}

# Region color coding for all frontends — now references THEME tokens
REGION_COLORS = {
    'USA':     {'fg': THEME["secondary"], 'bg': '#1e3a5f', 'css_var': 'secondary'},
    'Europe':  {'fg': THEME["primary"],   'bg': '#3b1f5e', 'css_var': 'primary'},
    'Japan':   {'fg': THEME["error"],     'bg': '#5f1e1e', 'css_var': 'error'},
    'World':   {'fg': THEME["success"],   'bg': '#1e5f2e', 'css_var': 'success'},
    'Brazil':  {'fg': THEME["warning"],   'bg': '#3d5f1e', 'css_var': 'warning'},
    'Korea':   {'fg': THEME["peach"],     'bg': '#5f3b1e', 'css_var': 'peach'},
    'China':   {'fg': THEME["flamingo"],  'bg': '#5f4e1e', 'css_var': 'flamingo'},
}

DEFAULT_REGION_COLOR = {'fg': THEME["overlay1"], 'bg': '#334155', 'css_var': 'overlay1'}

# Organization strategies
STRATEGIES = [
    {'id': 'system',           'name': 'By System',       'desc': 'Per-system folders (multi-DAT)'},
    {'id': '1g1r',             'name': '1 Game 1 ROM',    'desc': 'Best version per game'},
    {'id': 'region',           'name': 'By Region',       'desc': 'Region folders'},
    {'id': 'alphabetical',     'name': 'Alphabetical',    'desc': 'A-Z folders'},
    {'id': 'emulationstation', 'name': 'EmulationStation', 'desc': 'ES/RetroPie compatible'},
    {'id': 'flat',             'name': 'Flat',            'desc': 'Renamed only'},
    {'id': 'museum',           'name': 'Museum',          'desc': 'Generation/System/Region curation'},
]

# App data directory — portable: everything stays inside the project folder
import os
_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_PACKAGE_DIR)          # D:\1 romorg
APP_DATA_DIR = os.path.join(_PROJECT_DIR, 'data')
COLLECTIONS_DIR = os.path.join(APP_DATA_DIR, 'collections')
DATS_DIR = os.path.join(APP_DATA_DIR, 'dats')
IMPORTS_DIR = os.path.join(APP_DATA_DIR, 'imports')
IMPORTED_DATS_DIR = os.path.join(IMPORTS_DIR, 'dats')
IMPORTED_COLLECTIONS_DIR = os.path.join(IMPORTS_DIR, 'collections')
IMPORTED_ROMS_DIR = os.path.join(IMPORTS_DIR, 'roms')
IMPORTED_DOWNLOADS_DIR = os.path.join(IMPORTS_DIR, 'downloads')
SESSION_CACHE_DIR = os.path.join(APP_DATA_DIR, 'cache')
EXPORTS_DIR = os.path.join(APP_DATA_DIR, 'exports')
DAT_INDEX_FILE = os.path.join(APP_DATA_DIR, 'dat_index.json')
RECENT_FILE = os.path.join(APP_DATA_DIR, 'recent.json')


# ─── Empty State Definitions ──────────────────────────────────────────────────
EMPTY_STATES = {
    'no_dats': {
        'icon': 'gamepad',
        'heading': 'empty_no_dats_heading',
        'subtext': 'empty_no_dats_subtext',
        'cta_label': 'empty_no_dats_cta',
        'cta_action': 'navigate_import',
    },
    'no_scan': {
        'icon': 'folder_search',
        'heading': 'empty_no_scan_heading',
        'subtext': 'empty_no_scan_subtext',
        'cta_label': 'empty_no_scan_cta',
        'cta_action': 'navigate_scan',
    },
    'no_results': {
        'icon': 'search_off',
        'heading': 'empty_no_results_heading',
        'subtext': 'empty_no_results_subtext',
        'cta_label': None,
        'cta_action': None,
    },
}

# Thumbnail cache directory
THUMBNAILS_DIR = os.path.join(APP_DATA_DIR, 'cache', 'thumbnails')


def ensure_app_directories() -> None:
    """Create required app-local directories at startup."""
    for path in (
        APP_DATA_DIR,
        COLLECTIONS_DIR,
        DATS_DIR,
        IMPORTS_DIR,
        IMPORTED_DATS_DIR,
        IMPORTED_COLLECTIONS_DIR,
        IMPORTED_ROMS_DIR,
        IMPORTED_DOWNLOADS_DIR,
        SESSION_CACHE_DIR,
        EXPORTS_DIR,
        THUMBNAILS_DIR,
    ):
        os.makedirs(path, exist_ok=True)
