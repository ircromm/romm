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

# Region color coding for both GUIs
# Desktop uses 'fg' for Treeview tag_configure foreground
# Web uses 'css_bg' and 'css_fg' for Tailwind-style classes
REGION_COLORS = {
    'USA':     {'fg': '#60a5fa', 'bg': '#1e3a5f', 'css_bg': 'bg-blue-900/50',   'css_fg': 'text-blue-400'},
    'Europe':  {'fg': '#a78bfa', 'bg': '#3b1f5e', 'css_bg': 'bg-purple-900/50', 'css_fg': 'text-purple-400'},
    'Japan':   {'fg': '#f87171', 'bg': '#5f1e1e', 'css_bg': 'bg-red-900/50',    'css_fg': 'text-red-400'},
    'World':   {'fg': '#4ade80', 'bg': '#1e5f2e', 'css_bg': 'bg-green-900/50',  'css_fg': 'text-green-400'},
    'Brazil':  {'fg': '#a3e635', 'bg': '#3d5f1e', 'css_bg': 'bg-lime-900/50',   'css_fg': 'text-lime-400'},
    'Korea':   {'fg': '#fb923c', 'bg': '#5f3b1e', 'css_bg': 'bg-orange-900/50', 'css_fg': 'text-orange-400'},
    'China':   {'fg': '#fbbf24', 'bg': '#5f4e1e', 'css_bg': 'bg-yellow-900/50', 'css_fg': 'text-yellow-400'},
}

DEFAULT_REGION_COLOR = {'fg': '#94a3b8', 'bg': '#334155', 'css_bg': 'bg-slate-700', 'css_fg': 'text-slate-400'}

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
    ):
        os.makedirs(path, exist_ok=True)
