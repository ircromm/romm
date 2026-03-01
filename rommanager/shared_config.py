"""
Shared configuration between GUI frontends.
Ensures consistency in column definitions, colors, strategy metadata, and labels.
"""

# Standardized column definitions for identified ROMs table
IDENTIFIED_COLUMNS = [
    {'id': 'original_file', 'label': 'Original File', 'width': 350}, # Expanded from 180 to fit long paths without truncating early
    {'id': 'rom_name', 'label': 'ROM Name', 'width': 220},
    {'id': 'game_name', 'label': 'Game', 'width': 300}, # Expanded from 180
    {'id': 'system', 'label': 'System', 'width': 180},
    {'id': 'region', 'label': 'Region', 'width': 90},
    {'id': 'size', 'label': 'Size', 'width': 90},
    {'id': 'crc32', 'label': 'CRC32', 'width': 100},
    {'id': 'status', 'label': 'Status', 'width': 80},
]

# Standardized column definitions for unidentified files table
UNIDENTIFIED_COLUMNS = [
    {'id': 'filename', 'label': 'Filename', 'width': 350},
    {'id': 'path', 'label': 'Path', 'width': 500},
    {'id': 'size', 'label': 'Size', 'width': 100},
    {'id': 'crc32', 'label': 'CRC32', 'width': 100},
]

# Standardized column definitions for missing ROMs table
MISSING_COLUMNS = [
    {'id': 'rom_name', 'label': 'ROM Name', 'width': 300},
    {'id': 'game_name', 'label': 'Game', 'width': 300},
    {'id': 'system', 'label': 'System', 'width': 200},
    {'id': 'region', 'label': 'Region', 'width': 90},
    {'id': 'size', 'label': 'Size', 'width': 90},
]

# ─── Unified Design Tokens (Cyberpunk Industrial) ───────────────────────────────
THEME = {
    # Backgrounds
    "bg":       "#1E1E1E",   # base (main background)
    "bg_dim":   "#151515",   # mantle (deep panels, sidebars)
    "bg_deep":  "#090909",   # crust (absolute bottom)

    # Surfaces
    "surface0": "#2D2D2D",   # floating panels, cards
    "surface1": "#3C3C3C",   # hover states, borders
    "surface2": "#4A4A4A",   # active states

    # Text hierarchy
    "text":     "#E0E0E0",   # main text
    "subtext1": "#CCCCCC",   # secondary text
    "subtext0": "#A0A0A0",   # muted text
    "overlay2": "#808080",
    "overlay1": "#606060",
    "overlay0": "#4D4D4D",

    # Semantic accents (Cyberpunk)
    "primary":  "#39FF14",   # Neon Green — primary actions, nav highlights
    "secondary":"#FF00FF",   # Magenta — secondary actions, links
    "success":  "#39FF14",   # Neon Green
    "warning":  "#F9E2AF",   # Yellow/Gold
    "error":    "#FF00FF",   # Magenta
    "info":     "#89B4FA",   # Blue

    # Extra accents (for region badges, special UI)
    "peach":    "#FAB387",
    "pink":     "#F5C2E7",
    "sky":      "#89DCEB",
    "lavender": "#B4BEFE",
    "flamingo": "#F2CDCD",
    "rosewater":"#F5E0DC",
    "maroon":   "#EBA0AC",
    "sapphire": "#74C7EC",
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
SESSION_CACHE_DIR = os.path.join(APP_DATA_DIR, 'cache')
EXPORTS_DIR = os.path.join(APP_DATA_DIR, 'exports')
LOGS_DIR = os.path.join(APP_DATA_DIR, 'logs')
DAT_INDEX_FILE = os.path.join(APP_DATA_DIR, 'dat_index.json')
RECENT_FILE = os.path.join(APP_DATA_DIR, 'recent.json')
SETTINGS_FILE = os.path.join(APP_DATA_DIR, 'settings.json')
SESSION_STATE_FILE = os.path.join(APP_DATA_DIR, 'session_state.json')


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
        SESSION_CACHE_DIR,
        EXPORTS_DIR,
        LOGS_DIR,
    ):
        os.makedirs(path, exist_ok=True)
