"""
Web API for R0MM using Flask + embedded React UI (v2)
Full feature parity with the desktop GUI.
Includes File Browser API.
"""

import os
import json
import threading
import platform
import time
from datetime import datetime
from typing import List

from flask import Flask, jsonify, request, render_template_string
from werkzeug.utils import secure_filename

from .monitor import setup_runtime_monitor, monitor_action
from .models import ROMInfo, ScannedFile, DATInfo, Collection
from .parser import DATParser
from .scanner import FileScanner
from .matcher import MultiROMMatcher
from .organizer import Organizer
from .collection import CollectionManager
from .reporter import MissingROMReporter
from .dat_library import DATLibrary
from .dat_sources import DATSourceManager
from .utils import format_size
from .blindmatch import build_blindmatch_rom
from .shared_config import (
    IDENTIFIED_COLUMNS, UNIDENTIFIED_COLUMNS, MISSING_COLUMNS,
    REGION_COLORS, DEFAULT_REGION_COLOR, STRATEGIES,
)

DOWNLOADER_AVAILABLE = False
MYRIENT_AVAILABLE = False

# Flask app
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max upload

# Global state
state = {
    'multi_matcher': MultiROMMatcher(),
    'identified': [],
    'unidentified': [],
    'organizer': Organizer(),
    'collection_manager': CollectionManager(),
    'reporter': MissingROMReporter(),
    'dat_library': DATLibrary(),
    'dat_source_manager': DATSourceManager(),
    'scanning': False,
    'scan_progress': 0,
    'scan_total': 0,
    'blindmatch_mode': False,
    'blindmatch_system': '',
}


# ── Filesystem API ─────────────────────────────────────────────

@app.route('/api/fs/list', methods=['POST'])
def fs_list():
    """List directories and files for the file browser."""
    data = request.get_json()
    path = data.get('path', '')
    
    # Handle root listing
    if not path:
        if platform.system() == "Windows":
            # List drives on Windows
            drives = []
            import string
            from ctypes import windll
            bitmask = windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1:
                    drives.append({'name': f"{letter}:\\", 'type': 'dir', 'path': f"{letter}:\\"})
                bitmask >>= 1
            return jsonify({'items': drives, 'current_path': ''})
        else:
            path = '/'

    if not os.path.isdir(path):
        return jsonify({'error': 'Invalid path'}), 400

    items = []
    try:
        # Add parent directory entry
        parent = os.path.dirname(path)
        if parent and parent != path:
            items.append({'name': '..', 'type': 'dir', 'path': parent})
            
        with os.scandir(path) as it:
            for entry in it:
                try:
                    etype = 'dir' if entry.is_dir() else 'file'
                    items.append({
                        'name': entry.name,
                        'type': etype,
                        'path': entry.path
                    })
                except PermissionError:
                    continue
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    # Sort: Directories first, then files
    items.sort(key=lambda x: (x['type'] != 'dir', x['name'].lower()))
    
    return jsonify({'items': items, 'current_path': path})


# ── Helpers ────────────────────────────────────────────────────

def _rom_to_dict(f: ScannedFile) -> dict:
    rom = f.matched_rom
    return {
        'id': f.path,
        'original_file': f.filename,
        'rom_name': rom.name if rom else f.filename,
        'game_name': rom.game_name if rom else '',
        'system': rom.system_name if rom else '',
        'region': rom.region if rom else 'Unknown',
        'size': f.size,
        'size_formatted': format_size(f.size),
        'crc32': f.crc32.upper(),
        'status': rom.status if rom else 'unknown',
        'path': f.path,
    }


def _unidentified_to_dict(f: ScannedFile) -> dict:
    return {
        'id': f.path,
        'filename': f.filename,
        'path': f.path,
        'size': f.size,
        'size_formatted': format_size(f.size),
        'crc32': f.crc32.upper(),
    }


def _region_css(region: str) -> dict:
    c = REGION_COLORS.get(region, DEFAULT_REGION_COLOR)
    return {'css_bg': c['css_bg'], 'css_fg': c['css_fg']}


# ── API Routes ─────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/status')
def get_status():
    mm = state['multi_matcher']
    dats = mm.get_dat_list()
    return jsonify({
        'dat_count': len(dats),
        'dats_loaded': [d.to_dict() for d in dats],
        'total_roms_in_dats': sum(len(r) for r in mm.all_roms.values()),
        'identified_count': len(state['identified']),
        'unidentified_count': len(state['unidentified']),
        'scanning': state['scanning'],
        'scan_progress': state['scan_progress'],
        'scan_total': state['scan_total'],
        'blindmatch_mode': state.get('blindmatch_mode', False),
    })


# ── Multi-DAT endpoints ───────────────────────────────────────

@app.route('/api/load-dat', methods=['POST'])
def load_dat():
    data = request.get_json()
    filepath = data.get('path')

    if not filepath or not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 400

    try:
        dat_info, roms = DATParser.parse_with_info(filepath)
        state['multi_matcher'].add_dat(dat_info, roms)
        # Re-match existing scanned files if any
        _rematch_all()
        return jsonify({
            'success': True,
            'dat': dat_info.to_dict(),
            'rom_count': len(roms),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/remove-dat', methods=['POST'])
def remove_dat():
    data = request.get_json()
    dat_id = data.get('dat_id')
    if not dat_id:
        return jsonify({'error': 'dat_id required'}), 400
    state['multi_matcher'].remove_dat(dat_id)
    _rematch_all()
    return jsonify({'success': True})


@app.route('/api/list-dats')
def list_dats():
    dats = state['multi_matcher'].get_dat_list()
    return jsonify({'dats': [d.to_dict() for d in dats]})


def _rematch_all():
    """Re-match all previously scanned files against current DATs."""
    all_files = state['identified'] + state['unidentified']
    if not all_files:
        return
    for f in all_files:
        f.matched_rom = None
    identified, unidentified = state['multi_matcher'].match_all(all_files)
    state['identified'] = identified
    state['unidentified'] = unidentified


# ── Scan ───────────────────────────────────────────────────────

@app.route('/api/scan', methods=['POST'])
def start_scan():
    data = request.get_json()
    folder = data.get('folder')
    scan_archives = data.get('scan_archives', True)
    recursive = data.get('recursive', True)
    blindmatch_system = (data.get('blindmatch_system') or '').strip()

    if not folder or not os.path.isdir(folder):
        return jsonify({'error': 'Invalid folder'}), 400

    if not state['multi_matcher'].matchers:
        return jsonify({'error': 'Load a DAT file first'}), 400

    if state['scanning']:
        return jsonify({'error': 'Scan already in progress'}), 400

    state['blindmatch_mode'] = bool(blindmatch_system)
    state['blindmatch_system'] = blindmatch_system

    thread = threading.Thread(
        target=_scan_thread,
        args=(folder, scan_archives, recursive, blindmatch_system)
    )
    thread.daemon = True
    thread.start()

    return jsonify({'success': True, 'message': 'Scan started'})


def _scan_thread(folder, scan_archives, recursive, blindmatch_system=""):
    state['scanning'] = True
    state['identified'] = []
    state['unidentified'] = []
    state['scan_progress'] = 0

    try:
        files = FileScanner.collect_files(folder, recursive, scan_archives)
        state['scan_total'] = len(files)

        for i, filepath in enumerate(files):
            try:
                ext = os.path.splitext(filepath)[1].lower()
                if ext == '.zip' and scan_archives:
                    for scanned in FileScanner.scan_archive_contents(filepath):
                        _process_scanned(scanned, blindmatch_system)
                else:
                    scanned = FileScanner.scan_file(filepath)
                    _process_scanned(scanned, blindmatch_system)
            except Exception:
                pass
            state['scan_progress'] = i + 1
    finally:
        state['scanning'] = False


def _process_scanned(scanned, blindmatch_system=""):
    if blindmatch_system:
        match = build_blindmatch_rom(scanned, blindmatch_system)
    else:
        match = state['multi_matcher'].match(scanned)
    scanned.matched_rom = match
    if match:
        state['identified'].append(scanned)
    else:
        state['unidentified'].append(scanned)


# ── Results ────────────────────────────────────────────────────

@app.route('/api/results')
def get_results():
    return jsonify({
        'identified': [_rom_to_dict(f) for f in state['identified']],
        'unidentified': [_unidentified_to_dict(f) for f in state['unidentified']],
    })


@app.route('/api/missing')
def get_missing():
    mm = state['multi_matcher']
    if not mm.matchers:
        return jsonify({'missing': [], 'completeness': {}})

    missing_roms = mm.get_missing(state['identified'])
    completeness = mm.get_completeness(state['identified'])
    completeness_by_dat = mm.get_completeness_by_dat(state['identified'])

    missing_list = []
    for rom in missing_roms:
        rc = _region_css(rom.region)
        missing_list.append({
            'rom_name': rom.name,
            'game_name': rom.game_name,
            'system': rom.system_name,
            'region': rom.region,
            'size': rom.size,
            'size_formatted': format_size(rom.size),
            'crc32': rom.crc32.upper(),
            'css_bg': rc['css_bg'],
            'css_fg': rc['css_fg'],
        })

    return jsonify({
        'missing': missing_list,
        'completeness': completeness,
        'completeness_by_dat': completeness_by_dat,
    })


# ── Force Identify ─────────────────────────────────────────────

@app.route('/api/force-identify', methods=['POST'])
def force_identify():
    data = request.get_json()
    paths = data.get('paths', [])

    moved = 0
    for path in paths:
        for f in state['unidentified'][:]:
            if f.path == path:
                f.forced = True
                f.matched_rom = ROMInfo(
                    name=f.filename,
                    size=f.size,
                    crc32=f.crc32,
                    game_name=os.path.splitext(f.filename)[0],
                    region='Unknown'
                )
                state['identified'].append(f)
                state['unidentified'].remove(f)
                moved += 1
                break

    return jsonify({'success': True, 'moved': moved})


# ── Organization ───────────────────────────────────────────────

@app.route('/api/strategies')
def get_strategies():
    return jsonify(STRATEGIES)


@app.route('/api/preview', methods=['POST'])
def preview_organize():
    data = request.get_json()
    output = data.get('output')
    strategy = data.get('strategy', 'flat')
    action = data.get('action', 'copy')

    if not output:
        return jsonify({'error': 'Output folder required'}), 400
    if not state['identified']:
        return jsonify({'error': 'No identified ROMs'}), 400

    try:
        plan = state['organizer'].preview(state['identified'], output, strategy, action)
        actions = [{'source': a.source, 'destination': a.destination, 'action': a.action_type}
                   for a in plan.actions]
        return jsonify({
            'strategy': plan.strategy_description,
            'total_files': plan.total_files,
            'total_size': plan.total_size,
            'total_size_formatted': format_size(plan.total_size),
            'actions': actions,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/organize', methods=['POST'])
def organize():
    data = request.get_json()
    output = data.get('output')
    strategy = data.get('strategy', 'flat')
    action = data.get('action', 'copy')

    if not output:
        return jsonify({'error': 'Output folder required'}), 400
    if not state['identified']:
        return jsonify({'error': 'No identified ROMs'}), 400

    try:
        actions = state['organizer'].organize(
            state['identified'], output, strategy, action
        )
        return jsonify({'success': True, 'organized': len(actions)})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/undo', methods=['POST'])
def undo():
    if state['organizer'].undo_last():
        return jsonify({'success': True})
    return jsonify({'error': 'Nothing to undo'}), 400


# ── Collections ────────────────────────────────────────────────

@app.route('/api/collection/save', methods=['POST'])
def save_collection():
    data = request.get_json()
    name = data.get('name', 'Untitled')

    mm = state['multi_matcher']
    collection = Collection(
        name=name,
        dat_infos=mm.get_dat_list(),
        dat_filepaths=[d.filepath for d in mm.get_dat_list()],
        identified=[f.to_dict() for f in state['identified']],
        unidentified=[f.to_dict() for f in state['unidentified']],
    )

    cm = state['collection_manager']
    filepath = cm.save(collection)
    return jsonify({'success': True, 'filepath': filepath})


@app.route('/api/collection/load', methods=['POST'])
def load_collection():
    data = request.get_json()
    filepath = data.get('filepath')

    if not filepath or not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 400

    try:
        cm = state['collection_manager']
        col = cm.load(filepath)

        # Restore multi-matcher from saved DAT paths
        mm = MultiROMMatcher()
        for dat_info in col.dat_infos:
            if os.path.exists(dat_info.filepath):
                try:
                    di, roms = DATParser.parse_with_info(dat_info.filepath)
                    mm.add_dat(di, roms)
                except Exception:
                    pass
        state['multi_matcher'] = mm

        # Restore scanned files
        state['identified'] = [ScannedFile.from_dict(d) for d in col.identified]
        state['unidentified'] = [ScannedFile.from_dict(d) for d in col.unidentified]

        return jsonify({
            'success': True,
            'name': col.name,
            'dat_count': len(col.dat_infos),
            'identified_count': len(state['identified']),
            'unidentified_count': len(state['unidentified']),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/collection/list')
def list_collections():
    cm = state['collection_manager']
    return jsonify({'collections': cm.list_saved()})


@app.route('/api/collection/recent')
def recent_collections():
    cm = state['collection_manager']
    return jsonify({'recent': cm.get_recent()})


# ── DAT Library ────────────────────────────────────────────────

@app.route('/api/dat-library/list')
def dat_library_list():
    lib = state['dat_library']
    dats = lib.list_dats()
    return jsonify({'dats': [d.to_dict() for d in dats]})


@app.route('/api/dat-library/import', methods=['POST'])
def dat_library_import():
    data = request.get_json()
    filepath = data.get('filepath')

    if not filepath or not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 400

    try:
        lib = state['dat_library']
        info = lib.import_dat(filepath)
        return jsonify({'success': True, 'dat': info.to_dict()})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/dat-library/load', methods=['POST'])
def dat_library_load():
    """Load a DAT from the library into the active multi-matcher."""
    data = request.get_json()
    dat_id = data.get('dat_id')

    lib = state['dat_library']
    path = lib.get_dat_path(dat_id)
    if not path:
        return jsonify({'error': 'DAT not found in library'}), 400

    try:
        dat_info, roms = DATParser.parse_with_info(path)
        state['multi_matcher'].add_dat(dat_info, roms)
        _rematch_all()
        return jsonify({'success': True, 'dat': dat_info.to_dict(), 'rom_count': len(roms)})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/dat-library/remove', methods=['POST'])
def dat_library_remove():
    data = request.get_json()
    dat_id = data.get('dat_id')
    lib = state['dat_library']
    if lib.remove_dat(dat_id):
        return jsonify({'success': True})
    return jsonify({'error': 'DAT not found'}), 400


# ── DAT Sources ────────────────────────────────────────────────

@app.route('/api/dat-sources')
def dat_sources():
    mgr = state['dat_source_manager']
    return jsonify({'sources': mgr.get_sources()})


@app.route('/api/dat-sources/libretro-list')
def dat_sources_libretro():
    mgr = state['dat_source_manager']
    return jsonify({'dats': mgr.list_libretro_dats()})



# ── Direct download endpoints removed ──────────────────────────

@app.route('/api/archive-search', methods=['POST'])
def archive_search():
    return jsonify({'error': 'Direct download/search features were removed from the app'}), 410


@app.route('/api/archive-item-files', methods=['POST'])
def archive_item_files():
    return jsonify({'error': 'Direct download/search features were removed from the app'}), 410


@app.route('/api/myrient/systems')
def myrient_systems():
    return jsonify({'error': 'Direct download features were removed from the app'}), 410


@app.route('/api/myrient/files', methods=['POST'])
def myrient_files():
    return jsonify({'error': 'Direct download features were removed from the app'}), 410


@app.route('/api/myrient/download-missing', methods=['POST'])
def myrient_download_missing():
    return jsonify({'error': 'Direct download features were removed from the app'}), 410


@app.route('/api/myrient/download-files', methods=['POST'])
def myrient_download_files():
    return jsonify({'error': 'Direct download features were removed from the app'}), 410


@app.route('/api/myrient/progress')
def myrient_progress():
    return jsonify({'active': False, 'progress': None, 'log': []})


@app.route('/api/myrient/cancel', methods=['POST'])
def myrient_cancel():
    return jsonify({'error': 'Direct download features were removed from the app'}), 410


@app.route('/api/myrient/pause', methods=['POST'])
def myrient_pause():
    return jsonify({'error': 'Direct download features were removed from the app'}), 410


@app.route('/api/myrient/resume', methods=['POST'])
def myrient_resume():
    return jsonify({'error': 'Direct download features were removed from the app'}), 410


# ── Export Reports ─────────────────────────────────────────────

@app.route('/api/export-report', methods=['POST'])
def export_report():
    data = request.get_json()
    fmt = data.get('format', 'json')
    filepath = data.get('filepath')

    if not filepath:
        return jsonify({'error': 'filepath required'}), 400

    mm = state['multi_matcher']
    reporter = state['reporter']

    report = reporter.generate_multi_report(
        mm.dat_infos, mm.all_roms, state['identified']
    )

    try:
        if fmt == 'txt':
            reporter.export_txt(report, filepath)
        elif fmt == 'csv':
            reporter.export_csv(report, filepath)
        else:
            reporter.export_json(report, filepath)
        return jsonify({'success': True, 'filepath': filepath})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# ── Config endpoint ────────────────────────────────────────────

@app.route('/api/config')
def get_config():
    return jsonify({
        'columns': {
            'identified': IDENTIFIED_COLUMNS,
            'unidentified': UNIDENTIFIED_COLUMNS,
            'missing': MISSING_COLUMNS,
        },
        'region_colors': REGION_COLORS,
        'default_region_color': DEFAULT_REGION_COLOR,
        'strategies': STRATEGIES,
        'downloader_available': DOWNLOADER_AVAILABLE,
        'myrient_available': MYRIENT_AVAILABLE,
    })


# ── HTML Template ──────────────────────────────────────────────

HTML_TEMPLATE = r'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>R0MM v2</title>
    <script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Inter', sans-serif; }
        .loader { border: 3px solid #334155; border-top: 3px solid #22d3ee; border-radius: 50%; width: 20px; height: 20px; animation: spin 1s linear infinite; display: inline-block; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 100; }
        .modal-content { background: #1e293b; border: 1px solid #475569; border-radius: 12px; max-width: 800px; width: 90%; max-height: 80vh; overflow-y: auto; padding: 24px; }
    </style>
</head>
<body>
    <div id="root"></div>
    <script type="text/babel">
    {% raw %}
        const { useState, useEffect, useCallback, useRef } = React;

        const api = {
            async get(url) { const r = await fetch(url); return r.json(); },
            async post(url, data) {
                const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
                return r.json();
            }
        };

        // --- File Browser Component ---
        function FileBrowser({ mode, onSelect, onClose }) {
            const [path, setPath] = useState('');
            const [items, setItems] = useState([]);
            const [loading, setLoading] = useState(false);

            const loadPath = async (p) => {
                setLoading(true);
                try {
                    const res = await api.post('/api/fs/list', { path: p });
                    if(res.error) alert(res.error);
                    else {
                        setItems(res.items);
                        setPath(res.current_path);
                    }
                } catch(e) { console.error(e); }
                setLoading(false);
            };

            useEffect(() => { loadPath(''); }, []);

            const handleItemClick = (item) => {
                if (item.type === 'dir') {
                    loadPath(item.path);
                } else {
                    if (mode === 'file') onSelect(item.path);
                }
            };

            return (
                <div className="modal-overlay" onClick={onClose}>
                    <div className="modal-content" style={{maxWidth:'600px'}} onClick={e => e.stopPropagation()}>
                        <div className="flex justify-between items-center mb-4">
                            <h3 className="text-lg font-bold text-cyan-400">Browse {mode === 'dir' ? 'Folder' : 'File'}</h3>
                            <button onClick={onClose} className="text-slate-400 hover:text-white text-xl">&#x2715;</button>
                        </div>
                        <div className="p-2 bg-slate-900 border border-slate-700 rounded mb-2 text-xs font-mono truncate text-slate-300">
                            {path || "Root"}
                        </div>
                        <div className="flex-1 overflow-auto bg-slate-900/50 border border-slate-700 rounded h-80 p-2">
                            {loading ? <div className="text-center p-4 text-slate-500">Loading...</div> : 
                             items.map((item, i) => (
                                <div key={i} onClick={() => handleItemClick(item)}
                                     className="flex items-center gap-2 p-2 hover:bg-slate-700 cursor-pointer rounded text-sm text-slate-300">
                                    <span className="text-yellow-500 text-lg">{item.type === 'dir' ? '📁' : '📄'}</span>
                                    <span className={item.type === 'dir' ? 'font-bold text-white' : ''}>{item.name}</span>
                                </div>
                            ))}
                        </div>
                        <div className="mt-4 flex justify-end gap-2">
                            <button onClick={onClose} className="px-4 py-2 bg-slate-700 rounded-lg text-sm">Cancel</button>
                            {mode === 'dir' && (
                                <button onClick={() => onSelect(path)} className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm font-medium">
                                    Select This Folder
                                </button>
                            )}
                        </div>
                    </div>
                </div>
            );
        }

        /* ── Region badge ─────────────────────── */
        const REGION_CSS = {
            'USA':    { bg: 'bg-blue-900/50',   fg: 'text-blue-400' },
            'Europe': { bg: 'bg-purple-900/50', fg: 'text-purple-400' },
            'Japan':  { bg: 'bg-red-900/50',    fg: 'text-red-400' },
            'World':  { bg: 'bg-green-900/50',  fg: 'text-green-400' },
            'Brazil': { bg: 'bg-lime-900/50',   fg: 'text-lime-400' },
            'Korea':  { bg: 'bg-orange-900/50', fg: 'text-orange-400' },
            'China':  { bg: 'bg-yellow-900/50', fg: 'text-yellow-400' },
        };
        const defaultRegionCSS = { bg: 'bg-slate-700', fg: 'text-slate-400' };
        function RegionBadge({ region }) {
            const c = REGION_CSS[region] || defaultRegionCSS;
            return <span className={`px-2 py-0.5 rounded text-xs ${c.bg} ${c.fg}`}>{region || 'Unknown'}</span>;
        }

        /* ── Notification ─────────────────────── */
        function Notification({ notification, onClose }) {
            if (!notification) return null;
            const colors = {
                success: 'bg-emerald-900/90 border-emerald-600',
                error:   'bg-red-900/90 border-red-600',
                warning: 'bg-amber-900/90 border-amber-600',
                info:    'bg-sky-900/90 border-sky-600',
            };
            return (
                <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-xl flex items-center gap-3 border ${colors[notification.type] || colors.info}`}>
                    <span>{notification.message}</span>
                    <button onClick={onClose} className="ml-2 hover:opacity-70">&#x2715;</button>
                </div>
            );
        }

        /* ── Modal ────────────────────────────── */
        function Modal({ title, children, onClose }) {
            return (
                <div className="modal-overlay" onClick={onClose}>
                    <div className="modal-content" onClick={e => e.stopPropagation()}>
                        <div className="flex justify-between items-center mb-4">
                            <h2 className="text-lg font-bold text-cyan-400">{title}</h2>
                            <button onClick={onClose} className="text-slate-400 hover:text-white text-xl">&#x2715;</button>
                        </div>
                        {children}
                    </div>
                </div>
            );
        }

        /* ── Main App ─────────────────────────── */
        function App() {
            const [status, setStatus] = useState({});
            const [results, setResults] = useState({ identified: [], unidentified: [] });
            const [missing, setMissing] = useState({ missing: [], completeness: {}, completeness_by_dat: {} });
            const [datPath, setDatPath] = useState('');
            const [romFolder, setRomFolder] = useState('');
            const [outputFolder, setOutputFolder] = useState('');
            const [strategy, setStrategy] = useState('1g1r');
            const [action, setAction] = useState('copy');
            const [scanArchives, setScanArchives] = useState(true);
            const [recursive, setRecursive] = useState(true);
            const [blindmatchSystem, setBlindmatchSystem] = useState('');
            const [activeTab, setActiveTab] = useState('identified');
            const [selected, setSelected] = useState(new Set());
            const [notification, setNotification] = useState(null);
            const [searchQuery, setSearchQuery] = useState('');
            const searchTimer = useRef(null);
            const [debouncedQuery, setDebouncedQuery] = useState('');

            // Browser
            const [browserMode, setBrowserMode] = useState(null); // 'file' or 'dir'
            const [browserCallback, setBrowserCallback] = useState(null);

            // Modals
            const [showPreview, setShowPreview] = useState(false);
            const [previewData, setPreviewData] = useState(null);
            const [showDatLibrary, setShowDatLibrary] = useState(false);
            const [libraryDats, setLibraryDats] = useState([]);
            const [showCollections, setShowCollections] = useState(false);
            const [collections, setCollections] = useState([]);
            const [collectionName, setCollectionName] = useState('');
            const [showArchive, setShowArchive] = useState(false);
            const [archiveQuery, setArchiveQuery] = useState('');
            const [archiveResults, setArchiveResults] = useState([]);
            const [archiveSearching, setArchiveSearching] = useState(false);
            const [showDatSources, setShowDatSources] = useState(false);
            const [datSources, setDatSources] = useState([]);
            // Myrient
            const [showMyrient, setShowMyrient] = useState(false);
            const [myrientSystems, setMyrientSystems] = useState([]);
            const [myrientFiles, setMyrientFiles] = useState([]);
            const [myrientLoading, setMyrientLoading] = useState(false);
            const [myrientSysSearch, setMyrientSysSearch] = useState('');
            const [myrientFileSearch, setMyrientFileSearch] = useState('');
            const [myrientSelectedSys, setMyrientSelectedSys] = useState('');
            const [showDownloadDialog, setShowDownloadDialog] = useState(false);
            const [dlDest, setDlDest] = useState('');
            const [dlProgress, setDlProgress] = useState(null);
            const [dlActive, setDlActive] = useState(false);
            const [dlLog, setDlLog] = useState([]);
            const [dlDelay, setDlDelay] = useState(5);
            const dlPollRef = useRef(null);

            const notify = (type, message) => {
                setNotification({ type, message });
                setTimeout(() => setNotification(null), 4000);
            };

            const openBrowser = (mode, setter) => {
                setBrowserMode(mode);
                setBrowserCallback(() => (path) => {
                    setter(path);
                    setBrowserMode(null);
                });
            };

            // Debounced search
            useEffect(() => {
                if (searchTimer.current) clearTimeout(searchTimer.current);
                searchTimer.current = setTimeout(() => setDebouncedQuery(searchQuery), 300);
                return () => { if (searchTimer.current) clearTimeout(searchTimer.current); };
            }, [searchQuery]);

            const refreshStatus = useCallback(async () => {
                const data = await api.get('/api/status');
                setStatus(data);
                if (data.scanning) setTimeout(refreshStatus, 500);
            }, []);

            const refreshResults = useCallback(async () => {
                const data = await api.get('/api/results');
                setResults(data);
            }, []);

            const refreshMissing = useCallback(async () => {
                const data = await api.get('/api/missing');
                setMissing(data);
            }, []);

            useEffect(() => {
                refreshStatus();
                const iv = setInterval(refreshStatus, 2000);
                return () => clearInterval(iv);
            }, []);
            // set button titles for hover tooltips
            useEffect(() => {
                const applyTips = () => {
                    document.querySelectorAll('button').forEach((b) => {
                        if (!b.title || !b.title.trim()) {
                            const t = (b.innerText || '').trim();
                            if (t) b.title = t;
                        }
                    });
                };
                applyTips();
                const iv = setInterval(applyTips, 2000);
                return () => clearInterval(iv);
            }, []);

            useEffect(() => {
                if (!status.scanning && (status.identified_count > 0 || status.unidentified_count > 0)) {
                    refreshResults();
                    refreshMissing();
                }
            }, [status.scanning, status.identified_count, status.unidentified_count]);

            /* ── DAT actions ──────── */
            const loadDat = async () => {
                if (!datPath) return notify('warning', 'Enter DAT file path');
                const res = await api.post('/api/load-dat', { path: datPath });
                if (res.error) { notify('error', res.error); }
                else { notify('success', `Loaded ${res.rom_count.toLocaleString()} ROMs from ${res.dat.system_name || res.dat.name}`); refreshStatus(); }
            };

            const removeDat = async (datId) => {
                await api.post('/api/remove-dat', { dat_id: datId });
                notify('success', 'DAT removed');
                refreshStatus();
                refreshResults();
                refreshMissing();
            };

            /* ── Scan ──────── */
            const startScan = async () => {
                if (!romFolder) return notify('warning', 'Enter ROM folder path');
                const res = await api.post('/api/scan', { folder: romFolder, scan_archives: scanArchives, recursive, blindmatch_system: blindmatchSystem });
                if (res.error) notify('error', res.error);
                else { notify('success', 'Scan started'); refreshStatus(); }
            };

            /* ── Force identify ──── */
            const forceIdentify = async () => {
                if (selected.size === 0) return notify('warning', 'Select files first');
                const res = await api.post('/api/force-identify', { paths: Array.from(selected) });
                if (res.error) notify('error', res.error);
                else { notify('success', `Moved ${res.moved} files`); setSelected(new Set()); refreshResults(); refreshMissing(); refreshStatus(); }
            };

            /* ── Preview ──────── */
            const previewOrganize = async () => {
                if (!outputFolder) return notify('warning', 'Enter output folder');
                const res = await api.post('/api/preview', { output: outputFolder, strategy, action });
                if (res.error) notify('error', res.error);
                else { setPreviewData(res); setShowPreview(true); }
            };

            /* ── Organize ──────── */
            const doOrganize = async () => {
                const res = await api.post('/api/organize', { output: outputFolder, strategy, action });
                if (res.error) notify('error', res.error);
                else { notify('success', `Organized ${res.organized} ROMs!`); setShowPreview(false); }
            };

            const undoOrganize = async () => {
                const res = await api.post('/api/undo', {});
                if (res.error) notify('error', res.error);
                else notify('success', 'Undo complete');
            };

            /* ── Collections ──────── */
            const saveCollection = async () => {
                if (!collectionName) return notify('warning', 'Enter collection name');
                const res = await api.post('/api/collection/save', { name: collectionName });
                if (res.error) notify('error', res.error);
                else { notify('success', 'Collection saved'); setShowCollections(false); }
            };

            const loadCollection = async (filepath) => {
                const res = await api.post('/api/collection/load', { filepath });
                if (res.error) notify('error', res.error);
                else {
                    notify('success', `Loaded "${res.name}" - ${res.identified_count} identified`);
                    setShowCollections(false);
                    refreshStatus(); refreshResults(); refreshMissing();
                }
            };

            const openCollections = async () => {
                const res = await api.get('/api/collection/list');
                setCollections(res.collections || []);
                setShowCollections(true);
            };

            /* ── DAT Library ──────── */
            const openDatLibrary = async () => {
                const res = await api.get('/api/dat-library/list');
                setLibraryDats(res.dats || []);
                setShowDatLibrary(true);
            };

            const importToLibrary = async () => {
                if (!datPath) return notify('warning', 'Enter DAT path first');
                const res = await api.post('/api/dat-library/import', { filepath: datPath });
                if (res.error) notify('error', res.error);
                else {
                    notify('success', `Imported "${res.dat.system_name}" to library`);
                    const lr = await api.get('/api/dat-library/list');
                    setLibraryDats(lr.dats || []);
                }
            };

            const loadFromLibrary = async (datId) => {
                const res = await api.post('/api/dat-library/load', { dat_id: datId });
                if (res.error) notify('error', res.error);
                else { notify('success', `Loaded ${res.rom_count.toLocaleString()} ROMs`); refreshStatus(); refreshResults(); refreshMissing(); }
            };

            const removeFromLibrary = async (datId) => {
                const res = await api.post('/api/dat-library/remove', { dat_id: datId });
                if (res.error) notify('error', res.error);
                else {
                    notify('success', 'Removed from library');
                    const lr = await api.get('/api/dat-library/list');
                    setLibraryDats(lr.dats || []);
                }
            };

            /* ── DAT Sources ──────── */
            const openDatSources = async () => {
                const res = await api.get('/api/dat-sources');
                setDatSources(res.sources || []);
                setShowDatSources(true);
            };

            /* ── Archive.org ──────── */
            const searchArchive = async () => {
                if (!archiveQuery) return;
                setArchiveSearching(true);
                const res = await api.post('/api/archive-search', { rom_name: archiveQuery });
                setArchiveResults(res.results || []);
                setArchiveSearching(false);
            };

            /* ── Myrient Browser ──────── */
            const openMyrientBrowser = async () => {
                notify('warning', 'Direct download was removed from the app');
            };

            const loadMyrientFiles = async (sysName) => {
                setMyrientSelectedSys(sysName);
                setMyrientLoading(true);
                const res = await api.post('/api/myrient/files', { system_name: sysName, query: myrientFileSearch });
                setMyrientFiles(res.files || []);
                setMyrientLoading(false);
            };

            const searchMyrientFiles = async () => {
                if (!myrientSelectedSys) return;
                setMyrientLoading(true);
                const res = await api.post('/api/myrient/files', { system_name: myrientSelectedSys, query: myrientFileSearch });
                setMyrientFiles(res.files || []);
                setMyrientLoading(false);
            };

            const downloadMyrientFiles = async (files, dest) => {
                setShowDownloadDialog(true);
                const res = await api.post('/api/myrient/download-files', { dest_folder: dest, files, download_delay: dlDelay });
                if (res.error) { notify('error', res.error); return; }
                notify('success', `Queued ${files.length} files for download`);
                startDlPoll();
            };

            /* ── Download Missing ──────── */
            const startDownloadMissing = async (selectedNames = []) => {
                const dest = dlDest || '';
                if (!dest) { notify('warning', 'Enter download destination folder'); return; }
                
                const res = await api.post('/api/myrient/download-missing', {
                    dest_folder: dest,
                    selected_names: selectedNames,
                    download_delay: dlDelay,
                });
                if (res.error) { notify('error', res.error); return; }
                notify('success', `Resolving ${res.queuing} ROMs...`);
                setDlActive(true);
                startDlPoll();
            };

            const startDlPoll = () => {
                setDlActive(true);
                if (dlPollRef.current) clearInterval(dlPollRef.current);
                dlPollRef.current = setInterval(async () => {
                    const res = await api.get('/api/myrient/progress');
                    setDlProgress(res.progress);
                    setDlLog(res.log || []);
                    setDlActive(res.active);
                    if (!res.active) { clearInterval(dlPollRef.current); dlPollRef.current = null; }
                }, 500);
            };

            const cancelDl = async () => { notify('warning', 'Direct download was removed from the app'); };
            const pauseDl = async () => { notify('warning', 'Direct download was removed from the app'); };
            const resumeDl = async () => { notify('warning', 'Direct download was removed from the app'); };

            /* ── Filtering ──────── */
            const q = debouncedQuery.toLowerCase();
            const filteredIdentified = results.identified.filter(r =>
                !q || r.game_name.toLowerCase().includes(q) || r.rom_name.toLowerCase().includes(q) || r.system.toLowerCase().includes(q)
            );
            const filteredUnidentified = results.unidentified.filter(r =>
                !q || r.filename.toLowerCase().includes(q) || r.path.toLowerCase().includes(q)
            );
            const filteredMissing = (missing.missing || []).filter(r =>
                !q || r.game_name.toLowerCase().includes(q) || r.rom_name.toLowerCase().includes(q) || r.system.toLowerCase().includes(q)
            );

            const progress = status.scan_total > 0 ? (status.scan_progress / status.scan_total * 100) : 0;
            const comp = missing.completeness || {};

            return (
                <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 text-white p-6">
                    <Notification notification={notification} onClose={() => setNotification(null)} />
                    {browserMode && <FileBrowser mode={browserMode} onSelect={browserCallback} onClose={() => setBrowserMode(null)} />}

                    {/* ── Preview Modal ── */}
                    {showPreview && previewData && (
                        <Modal title="Organization Preview" onClose={() => setShowPreview(false)}>
                            <div className="space-y-3 text-sm">
                                <div className="flex gap-6">
                                    <span className="text-slate-400">Strategy: <span className="text-white">{previewData.strategy}</span></span>
                                    <span className="text-slate-400">Files: <span className="text-white">{previewData.total_files}</span></span>
                                    <span className="text-slate-400">Size: <span className="text-white">{previewData.total_size_formatted}</span></span>
                                </div>
                                <div className="max-h-60 overflow-auto bg-slate-900 rounded p-2">
                                    {previewData.actions.slice(0, 200).map((a, i) => (
                                        <div key={i} className="py-1 border-b border-slate-800 text-xs">
                                            <span className="text-slate-500">{a.action}</span>
                                            <span className="text-cyan-400 ml-2">{a.source.split(/[/\\]/).pop()}</span>
                                            <span className="text-slate-600 mx-1">&#8594;</span>
                                            <span className="text-emerald-400">{a.destination}</span>
                                        </div>
                                    ))}
                                    {previewData.actions.length > 200 && <div className="text-slate-500 text-xs py-1">... and {previewData.actions.length - 200} more</div>}
                                </div>
                                <div className="flex gap-2 justify-end">
                                    <button onClick={() => setShowPreview(false)} className="px-4 py-2 bg-slate-700 rounded-lg">Cancel</button>
                                    <button onClick={doOrganize} className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 rounded-lg font-medium">Execute</button>
                                </div>
                            </div>
                        </Modal>
                    )}

                    {/* ── Collections Modal ── */}
                    {showCollections && (
                        <Modal title="Collections" onClose={() => setShowCollections(false)}>
                            <div className="space-y-4">
                                <div className="flex gap-2">
                                    <input type="text" value={collectionName} onChange={e => setCollectionName(e.target.value)}
                                        placeholder="Collection name" className="flex-1 px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-sm focus:outline-none focus:border-cyan-500" />
                                    <button onClick={saveCollection} className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 rounded-lg text-sm font-medium">Save Current</button>
                                </div>
                                {collections.length > 0 && (
                                    <div className="space-y-2">
                                        <h3 className="text-sm font-medium text-slate-400">Saved Collections</h3>
                                        {collections.map((c, i) => (
                                            <div key={i} className="flex items-center justify-between p-3 bg-slate-900/50 rounded-lg">
                                                <div>
                                                    <div className="font-medium">{c.name}</div>
                                                    <div className="text-xs text-slate-500">{c.dat_count} DATs, {c.identified_count} identified - {c.updated_at ? new Date(c.updated_at).toLocaleDateString() : ''}</div>
                                                </div>
                                                <button onClick={() => loadCollection(c.filepath)} className="px-3 py-1 bg-blue-600 hover:bg-blue-500 rounded text-sm">Load</button>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </Modal>
                    )}

                    {/* ── DAT Library Modal ── */}
                    {showDatLibrary && (
                        <Modal title="DAT Library" onClose={() => setShowDatLibrary(false)}>
                            <div className="space-y-4">
                                <div className="flex gap-2">
                                    <button onClick={importToLibrary} className="px-3 py-2 bg-emerald-600 hover:bg-emerald-500 rounded-lg text-sm">Import Current DAT Path</button>
                                    <button onClick={openDatSources} className="px-3 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm">DAT Sources</button>
                                </div>
                                {libraryDats.length > 0 ? (
                                    <div className="space-y-2">
                                        {libraryDats.map((d, i) => (
                                            <div key={i} className="flex items-center justify-between p-3 bg-slate-900/50 rounded-lg">
                                                <div>
                                                    <div className="font-medium text-sm">{d.system_name || d.name}</div>
                                                    <div className="text-xs text-slate-500">{d.rom_count.toLocaleString()} ROMs - v{d.version || '?'}</div>
                                                </div>
                                                <div className="flex gap-2">
                                                    <button onClick={() => loadFromLibrary(d.id)} className="px-3 py-1 bg-cyan-600 hover:bg-cyan-500 rounded text-xs">Load</button>
                                                    <button onClick={() => removeFromLibrary(d.id)} className="px-3 py-1 bg-red-900/50 hover:bg-red-800/50 text-red-400 rounded text-xs">Remove</button>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                ) : <p className="text-slate-500 text-sm">No DATs in library. Import a DAT file or check DAT Sources.</p>}
                            </div>
                        </Modal>
                    )}

                    {/* ── DAT Sources Modal ── */}
                    {showDatSources && (
                        <Modal title="DAT Sources" onClose={() => setShowDatSources(false)}>
                            <div className="space-y-3">
                                {datSources.map((s, i) => (
                                    <div key={i} className="p-3 bg-slate-900/50 rounded-lg">
                                        <div className="font-medium text-sm text-cyan-300">{s.name}</div>
                                        <div className="text-xs text-slate-400 mt-1">{s.description}</div>
                                        <a href={s.url} target="_blank" rel="noopener noreferrer"
                                            className="text-xs text-blue-400 hover:underline mt-1 inline-block">Open Page &#8599;</a>
                                    </div>
                                ))}
                            </div>
                        </Modal>
                    )}

                    {/* ── Archive.org Modal ── */}
                    {showArchive && (
                        <Modal title="Search Archive.org" onClose={() => setShowArchive(false)}>
                            <div className="space-y-3">
                                <div className="flex gap-2">
                                    <input type="text" value={archiveQuery} onChange={e => setArchiveQuery(e.target.value)}
                                        onKeyDown={e => e.key === 'Enter' && searchArchive()}
                                        placeholder="Search for ROMs..." className="flex-1 px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-sm focus:outline-none focus:border-cyan-500" />
                                    <button onClick={searchArchive} disabled={archiveSearching}
                                        className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 rounded-lg text-sm flex items-center gap-2">
                                        {archiveSearching && <span className="loader" style={{width:14,height:14}}></span>}
                                        Search
                                    </button>
                                </div>
                                <div className="max-h-60 overflow-auto space-y-2">
                                    {archiveResults.map((r, i) => (
                                        <div key={i} className="p-3 bg-slate-900/50 rounded-lg">
                                            <div className="font-medium text-sm">{r.title || r.identifier}</div>
                                            <div className="text-xs text-slate-500 mt-1">{r.description?.substring(0, 120) || 'No description'}</div>
                                            <a href={`https://archive.org/details/${r.identifier}`} target="_blank" rel="noopener noreferrer"
                                                className="text-xs text-blue-400 hover:underline mt-1 inline-block">View on Archive.org &#8599;</a>
                                        </div>
                                    ))}
                                    {archiveResults.length === 0 && !archiveSearching && <p className="text-slate-500 text-sm text-center py-4">Enter a search term to find ROMs on archive.org</p>}
                                </div>
                            </div>
                        </Modal>
                    )}

                    {/* ── Myrient Browser Modal ── */}
                    {showMyrient && (
                        <div className="modal-overlay" onClick={() => setShowMyrient(false)}>
                            <div className="modal-content" style={{maxWidth:'1000px',maxHeight:'85vh'}} onClick={e => e.stopPropagation()}>
                                <div className="flex justify-between items-center mb-4">
                                    <h2 className="text-lg font-bold text-cyan-400">Myrient ROM Browser</h2>
                                    <button onClick={() => setShowMyrient(false)} className="text-slate-400 hover:text-white text-xl">&#x2715;</button>
                                </div>
                                <div className="flex gap-4" style={{height:'60vh'}}>
                                    {/* System list */}
                                    <div className="w-1/3 flex flex-col">
                                        <div className="text-sm font-medium text-slate-400 mb-1">Systems</div>
                                        <input type="text" value={myrientSysSearch} onChange={e => setMyrientSysSearch(e.target.value)}
                                            placeholder="Filter systems..." className="px-2 py-1 bg-slate-900 border border-slate-700 rounded text-xs mb-2 focus:outline-none focus:border-cyan-500" />
                                        <div className="flex-1 overflow-auto bg-slate-900/50 rounded">
                                            {myrientSystems.filter(s => !myrientSysSearch || s.name.toLowerCase().includes(myrientSysSearch.toLowerCase())).map((s, i) => (
                                                <div key={i} onClick={() => loadMyrientFiles(s.name)}
                                                    className={`px-3 py-2 text-xs cursor-pointer border-b border-slate-800 hover:bg-slate-700/50 ${myrientSelectedSys === s.name ? 'bg-cyan-900/30 text-cyan-300' : ''}`}>
                                                    <span className="text-slate-500">[{s.category}]</span> {s.name}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                    {/* File list */}
                                    <div className="w-2/3 flex flex-col">
                                        <div className="flex gap-2 mb-2">
                                            <input type="text" value={myrientFileSearch} onChange={e => setMyrientFileSearch(e.target.value)}
                                                onKeyDown={e => e.key === 'Enter' && searchMyrientFiles()}
                                                placeholder="Search files..." className="flex-1 px-2 py-1 bg-slate-900 border border-slate-700 rounded text-xs focus:outline-none focus:border-cyan-500" />
                                            <button onClick={searchMyrientFiles} className="px-3 py-1 bg-slate-700 hover:bg-slate-600 rounded text-xs">Search</button>
                                            <span className="text-xs text-slate-500 self-center">{myrientFiles.length} files</span>
                                        </div>
                                        <div className="flex-1 overflow-auto bg-slate-900/50 rounded" id="myrient-files">
                                            {myrientLoading ? <div className="p-4 text-center text-slate-500"><span className="loader"></span> Loading...</div> :
                                                myrientFiles.length === 0 ? <div className="p-4 text-center text-slate-500">Select a system to browse files</div> :
                                                myrientFiles.map((f, i) => (
                                                    <div key={i} className="px-3 py-1.5 text-xs cursor-pointer border-b border-slate-800 hover:bg-slate-700/50 flex justify-between items-center myrient-file-row"
                                                        onClick={e => e.currentTarget.classList.toggle('bg-cyan-900/30')}>
                                                        <span className="truncate mr-2">{f.name}</span>
                                                        <span className="text-slate-500 whitespace-nowrap">{f.size_text || ''}</span>
                                                    </div>
                                                ))}
                                        </div>
                                        <div className="flex gap-2 mt-2 items-center">
                                            <input type="text" value={dlDest} onChange={e => setDlDest(e.target.value)}
                                                placeholder="Download destination folder..." className="flex-1 px-2 py-1 bg-slate-900 border border-slate-700 rounded text-xs focus:outline-none focus:border-cyan-500" />
                                            <button onClick={()=>openBrowser('dir', setDlDest)} className="px-3 py-1 bg-blue-600 hover:bg-blue-500 rounded text-xs" title="Browse folder">Browse</button>

                                            <button onClick={() => {
                                                const selected = [];
                                                document.querySelectorAll('#myrient-files .bg-cyan-900\\/30').forEach(el => {
                                                    const idx = Array.from(el.parentNode.children).indexOf(el);
                                                    if (myrientFiles[idx]) selected.push({name: myrientFiles[idx].name, url: myrientFiles[idx].url});
                                                });
                                                if (selected.length === 0) { notify('warning', 'Click on files to select them first'); return; }
                                                downloadMyrientFiles(selected, dlDest);
                                            }} className="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 rounded text-xs font-medium whitespace-nowrap">
                                                Download Selected
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* ── Download Progress Modal ── */}
                    {showDownloadDialog && (
                        <Modal title="Download Missing ROMs" onClose={() => { if (!dlActive) setShowDownloadDialog(false); }}>
                            <div className="space-y-4">
                                <div>
                                    <label className="text-sm text-slate-400">Download to (scan folder):</label>
                                    <div className="flex gap-2 mt-1">
                                        <input type="text" value={dlDest} onChange={e => setDlDest(e.target.value)}
                                            placeholder="C:\path\to\roms" className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-sm focus:outline-none focus:border-cyan-500" />
                                        <button onClick={()=>openBrowser('dir', setDlDest)} className="px-3 bg-blue-600 hover:bg-blue-500 rounded text-sm" title="Browse folder">Browse</button>
                                    </div>
                                </div>
                                <div>
                                    <label className="text-sm text-slate-400">Delay between downloads (seconds):</label>
                                    <input type="number" min="0" max="60" value={dlDelay} onChange={e => setDlDelay(Math.max(0, Math.min(60, parseInt(e.target.value) || 0)))}
                                        disabled={dlActive}
                                        className="mt-1 ml-2 w-20 px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-sm focus:outline-none focus:border-cyan-500 disabled:opacity-50" />
                                </div>
                                {dlProgress && (
                                    <div className="space-y-2">
                                        <div className="flex justify-between text-sm">
                                            <span className="text-slate-400">{dlProgress.current_rom || 'Starting...'}</span>
                                            <span className="text-cyan-400">{dlProgress.completed}/{dlProgress.total_count}</span>
                                        </div>
                                        <div className="w-full h-2 bg-slate-700 rounded-full overflow-hidden">
                                            <div className="h-full bg-gradient-to-r from-emerald-500 to-cyan-500 transition-all"
                                                style={{width: `${dlProgress.total_count > 0 ? (dlProgress.completed + dlProgress.failed) / dlProgress.total_count * 100 : 0}%`}}></div>
                                        </div>
                                        {dlProgress.current_total > 0 && (
                                            <div className="w-full h-1.5 bg-slate-700 rounded-full overflow-hidden">
                                                <div className="h-full bg-cyan-600 transition-all"
                                                    style={{width: `${dlProgress.current_bytes / dlProgress.current_total * 100}%`}}></div>
                                            </div>
                                        )}
                                        <div className="text-xs text-slate-500">{dlProgress.completed} OK, {dlProgress.failed} failed{dlProgress.cancelled > 0 ? `, ${dlProgress.cancelled} cancelled` : ''}</div>
                                    </div>
                                )}
                                {dlLog.length > 0 && (
                                    <div className="max-h-32 overflow-auto bg-slate-900 rounded p-2 text-xs font-mono text-slate-400">
                                        {dlLog.map((l, i) => <div key={i}>{l}</div>)}
                                    </div>
                                )}
                                <div className="flex gap-2 justify-end">
                                    {!dlActive ? (
                                        <>
                                            <button onClick={() => setShowDownloadDialog(false)} className="px-4 py-2 bg-slate-700 rounded-lg text-sm">Close</button>
                                            <button onClick={() => startDownloadMissing()} className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 rounded-lg text-sm font-medium">Download All Missing (removed)</button>
                                        </>
                                    ) : (
                                        <>
                                            <button onClick={pauseDl} className="px-4 py-2 bg-amber-600 hover:bg-amber-500 rounded-lg text-sm">Pause</button>
                                            <button onClick={resumeDl} className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm">Resume</button>
                                            <button onClick={cancelDl} className="px-4 py-2 bg-red-600 hover:bg-red-500 rounded-lg text-sm">Cancel</button>
                                        </>
                                    )}
                                </div>
                            </div>
                        </Modal>
                    )}

                    <div className="max-w-7xl mx-auto space-y-6">
                        {/* ── Header ── */}
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-4">
                                <div className="text-4xl">&#127918;</div>
                                <div>
                                    <h1 className="text-3xl font-bold bg-gradient-to-r from-cyan-400 to-blue-500 bg-clip-text text-transparent">R0MM</h1>
                                    <p className="text-slate-400">v2 &mdash; Multi-DAT, Collections, Missing ROMs</p>
                                </div>
                            </div>
                            <div className="flex gap-2">
                                <button onClick={openCollections} className="px-3 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm">Collections</button>
                                <button onClick={openDatLibrary} className="px-3 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm">DAT Library</button>
                                <button onClick={openMyrientBrowser} className="px-3 py-2 bg-emerald-700 hover:bg-emerald-600 rounded-lg text-sm">Myrient Browser (removed)</button>
                            </div>
                        </div>

                        {/* ── DAT & Scan Cards ── */}
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                            {/* DAT File */}
                            <div className="bg-slate-800/50 backdrop-blur border border-slate-700 rounded-xl p-5">
                                <h2 className="font-semibold mb-4 flex items-center gap-2">
                                    <span className="text-cyan-400">&#128193;</span> DAT Files
                                </h2>
                                <div className="flex gap-2 mb-3">
                                    <input type="text" value={datPath} onChange={e => setDatPath(e.target.value)}
                                        placeholder="C:\path\to\nointro.dat"
                                        className="flex-1 px-4 py-2 bg-slate-900/50 border border-slate-600 rounded-lg focus:outline-none focus:border-cyan-500 text-sm" />
                                    <button onClick={()=>openBrowser('file', setDatPath)} className="px-3 bg-blue-600 hover:bg-blue-500 rounded-l-none rounded-r-lg" title="Browse folder">Browse</button>
                                    <button onClick={loadDat} className="ml-2 px-4 py-2 bg-cyan-600 hover:bg-cyan-500 rounded-lg font-medium transition text-sm">Add</button>
                                </div>
                                {(status.dats_loaded || []).length > 0 && (
                                    <div className="space-y-2 max-h-32 overflow-auto">
                                        {status.dats_loaded.map((d, i) => (
                                            <div key={i} className="flex items-center justify-between p-2 bg-slate-900/50 rounded text-sm">
                                                <div>
                                                    <span className="text-cyan-400 font-medium">{d.system_name || d.name}</span>
                                                    <span className="text-slate-500 ml-2">({d.rom_count.toLocaleString()} ROMs)</span>
                                                </div>
                                                <button onClick={() => removeDat(d.id)} className="text-red-400 hover:text-red-300 text-xs">&#x2715;</button>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            {/* Scan */}
                            <div className="bg-slate-800/50 backdrop-blur border border-slate-700 rounded-xl p-5">
                                <h2 className="font-semibold mb-4 flex items-center gap-2">
                                    <span className="text-emerald-400">&#128269;</span> Scan ROMs
                                </h2>
                                <div className="flex gap-2 mb-3">
                                    <input type="text" value={romFolder} onChange={e => setRomFolder(e.target.value)}
                                        placeholder="C:\path\to\roms"
                                        className="flex-1 px-4 py-2 bg-slate-900/50 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 text-sm" />
                                    <button onClick={()=>openBrowser('dir', setRomFolder)} className="px-3 bg-emerald-600 hover:bg-emerald-500 rounded-l-none rounded-r-lg" title="Browse folder">Browse</button>
                                    <button onClick={startScan} disabled={status.scanning}
                                        className="ml-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded-lg font-medium transition flex items-center gap-2 text-sm">
                                        {status.scanning && <span className="loader"></span>}
                                        Scan
                                    </button>
                                </div>
                                <div className="flex gap-4 mb-3 items-center">
                                    <label className="flex items-center gap-2 text-sm text-slate-400 cursor-pointer">
                                        <input type="checkbox" checked={scanArchives} onChange={e => setScanArchives(e.target.checked)} className="rounded bg-slate-700 border-slate-600" />
                                        Scan ZIPs
                                    </label>
                                    <label className="flex items-center gap-2 text-sm text-slate-400 cursor-pointer">
                                        <input type="checkbox" checked={recursive} onChange={e => setRecursive(e.target.checked)} className="rounded bg-slate-700 border-slate-600" />
                                        Recursive
                                    </label>
                                    <input type="text" value={blindmatchSystem} onChange={e => setBlindmatchSystem(e.target.value)}
                                        placeholder="BlindMatch system (optional)" title="BlindMatch system name"
                                        className="px-3 py-1.5 bg-slate-900/50 border border-slate-600 rounded text-sm min-w-[260px]" />
                                </div>
                                {status.scanning && (
                                    <div className="space-y-2">
                                        <div className="flex justify-between text-sm">
                                            <span className="text-slate-400">Scanning...</span>
                                            <span className="text-cyan-400">{status.scan_progress?.toLocaleString()} / {status.scan_total?.toLocaleString()}</span>
                                        </div>
                                        <div className="w-full h-2 bg-slate-700 rounded-full overflow-hidden">
                                            <div className="h-full bg-gradient-to-r from-cyan-500 to-blue-500 transition-all" style={{width: `${progress}%`}}></div>
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* ── Stats Bar ── */}
                        {(status.identified_count > 0 || status.unidentified_count > 0) && (
                            <div className="bg-slate-800/50 backdrop-blur border border-slate-700 rounded-xl p-4">
                                <div className="flex flex-wrap items-center gap-6 text-sm">
                                    <div><span className="text-slate-400">DATs:</span> <span className="font-bold text-cyan-400">{status.dat_count || 0}</span></div>
                                    <div><span className="text-slate-400">Total Scanned:</span> <span className="font-bold">{((status.identified_count || 0) + (status.unidentified_count || 0)).toLocaleString()}</span></div>
                                    <div className="flex items-center gap-1"><span className="text-emerald-400">&#10003;</span><span className="text-slate-400">Identified:</span> <span className="font-bold text-emerald-400">{(status.identified_count || 0).toLocaleString()}</span></div>
                                    <div className="flex items-center gap-1"><span className="text-amber-400">?</span><span className="text-slate-400">Unidentified:</span> <span className="font-bold text-amber-400">{(status.unidentified_count || 0).toLocaleString()}</span></div>
                                    {comp.total_in_dat > 0 && (
                                        <div className="flex items-center gap-1"><span className="text-red-400">&#9888;</span><span className="text-slate-400">Missing:</span> <span className="font-bold text-red-400">{(comp.missing || 0).toLocaleString()}</span><span className="text-slate-500 text-xs ml-1">({comp.percentage?.toFixed(1)}% complete)</span></div>
                                    )}
                                </div>
                            </div>
                        )}

                        {/* ── Tabs ── */}
                        <div className="bg-slate-800/50 backdrop-blur border border-slate-700 rounded-xl overflow-hidden">
                            <div className="flex border-b border-slate-700">
                                {[
                                    { id: 'identified', label: 'Identified', count: results.identified.length, color: 'cyan', badgeBg: 'bg-emerald-900/50', badgeFg: 'text-emerald-400' },
                                    { id: 'unidentified', label: 'Unidentified', count: results.unidentified.length, color: 'amber', badgeBg: 'bg-amber-900/50', badgeFg: 'text-amber-400' },
                                    { id: 'missing', label: 'Missing', count: (missing.missing || []).length, color: 'red', badgeBg: 'bg-red-900/50', badgeFg: 'text-red-400' },
                                ].map(tab => (
                                    <button key={tab.id} onClick={() => setActiveTab(tab.id)}
                                        className={`flex-1 px-6 py-4 font-medium transition flex items-center justify-center gap-2 ${
                                            activeTab === tab.id ? `bg-slate-700/50 text-${tab.color}-400 border-b-2 border-${tab.color}-400` : 'text-slate-400 hover:bg-slate-700/30'
                                        }`}>
                                        {tab.label}
                                        <span className={`px-2 py-0.5 ${tab.badgeBg} ${tab.badgeFg} text-xs rounded`}>{tab.count.toLocaleString()}</span>
                                    </button>
                                ))}
                            </div>

                            {/* Search + Actions bar */}
                            <div className="p-4 border-b border-slate-700/50 flex flex-wrap gap-4 items-center">
                                <div className="flex-1 min-w-[200px]">
                                    <input type="text" placeholder="Search..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
                                        className="w-full px-4 py-2 bg-slate-900/50 border border-slate-700 rounded-lg focus:outline-none focus:border-cyan-500 text-sm" />
                                </div>
                                {activeTab === 'unidentified' && (
                                    <button onClick={forceIdentify} disabled={selected.size === 0}
                                        className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg font-medium transition text-sm">
                                        Force to Identified ({selected.size})
                                    </button>
                                )}
                                {activeTab === 'missing' && (
                                    <div className="flex gap-2">
                                        <button onClick={() => { refreshMissing(); notify('info', 'Missing ROMs refreshed'); }}
                                            className="px-3 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm">Refresh</button>
                                        <button onClick={() => setShowArchive(true)}
                                            className="px-3 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm">Search Archive.org</button>
                                        <button onClick={() => { setDlDest(romFolder || ''); setShowDownloadDialog(true); }}
                                            className="px-3 py-2 bg-emerald-600 hover:bg-emerald-500 rounded-lg text-sm font-medium">Download Missing (removed)</button>
                                    </div>
                                )}
                            </div>

                            {/* Table content */}
                            <div className="max-h-[450px] overflow-auto">
                                {activeTab === 'identified' && (
                                    <table className="w-full text-sm">
                                        <thead className="bg-slate-800/80 sticky top-0">
                                            <tr className="text-left text-slate-400">
                                                <th className="p-3">Original File</th>
                                                <th className="p-3">ROM Name</th>
                                                <th className="p-3">Game</th>
                                                <th className="p-3">System</th>
                                                <th className="p-3">Region</th>
                                                <th className="p-3">Size</th>
                                                <th className="p-3">CRC32</th>
                                                <th className="p-3">Status</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-slate-700/50">
                                            {filteredIdentified.map(rom => (
                                                <tr key={rom.id} className="hover:bg-slate-800/30">
                                                    <td className="p-3 text-slate-300 max-w-[180px] truncate">{rom.original_file}</td>
                                                    <td className="p-3 text-cyan-300">{rom.rom_name}</td>
                                                    <td className="p-3">{rom.game_name}</td>
                                                    <td className="p-3 text-slate-400">{rom.system}</td>
                                                    <td className="p-3"><RegionBadge region={rom.region} /></td>
                                                    <td className="p-3 text-slate-400">{rom.size_formatted}</td>
                                                    <td className="p-3 font-mono text-xs text-slate-500">{rom.crc32}</td>
                                                    <td className="p-3 text-slate-400">{rom.status}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                )}

                                {activeTab === 'unidentified' && (
                                    <table className="w-full text-sm">
                                        <thead className="bg-slate-800/80 sticky top-0">
                                            <tr className="text-left text-slate-400">
                                                <th className="p-3 w-10">
                                                    <input type="checkbox" onChange={e => {
                                                        if (e.target.checked) setSelected(new Set(filteredUnidentified.map(f => f.id)));
                                                        else setSelected(new Set());
                                                    }} className="rounded bg-slate-700" />
                                                </th>
                                                <th className="p-3">Filename</th>
                                                <th className="p-3">Path</th>
                                                <th className="p-3">Size</th>
                                                <th className="p-3">CRC32</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-slate-700/50">
                                            {filteredUnidentified.map(file => (
                                                <tr key={file.id} className="hover:bg-slate-800/30">
                                                    <td className="p-3">
                                                        <input type="checkbox" checked={selected.has(file.id)}
                                                            onChange={e => {
                                                                const next = new Set(selected);
                                                                e.target.checked ? next.add(file.id) : next.delete(file.id);
                                                                setSelected(next);
                                                            }} className="rounded bg-slate-700" />
                                                    </td>
                                                    <td className="p-3 text-amber-300 font-mono">{file.filename}</td>
                                                    <td className="p-3 text-slate-500 max-w-[250px] truncate">{file.path}</td>
                                                    <td className="p-3 text-slate-400">{file.size_formatted}</td>
                                                    <td className="p-3 font-mono text-xs text-slate-500">{file.crc32}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                )}

                                {activeTab === 'missing' && (
                                    <div>
                                        {/* Completeness stats */}
                                        {comp.total_in_dat > 0 && (
                                            <div className="p-4 bg-slate-900/30 border-b border-slate-700/50">
                                                <div className="flex items-center gap-4 text-sm mb-2">
                                                    <span className="text-slate-400">Completeness:</span>
                                                    <span className="font-bold text-lg">{comp.percentage?.toFixed(1)}%</span>
                                                    <span className="text-slate-500">({comp.found?.toLocaleString()} / {comp.total_in_dat?.toLocaleString()})</span>
                                                </div>
                                                <div className="w-full h-3 bg-slate-700 rounded-full overflow-hidden">
                                                    <div className="h-full bg-gradient-to-r from-emerald-500 to-cyan-500 transition-all" style={{width: `${comp.percentage || 0}%`}}></div>
                                                </div>
                                            </div>
                                        )}
                                        <table className="w-full text-sm">
                                            <thead className="bg-slate-800/80 sticky top-0">
                                                <tr className="text-left text-slate-400">
                                                    <th className="p-3">ROM Name</th>
                                                    <th className="p-3">Game</th>
                                                    <th className="p-3">System</th>
                                                    <th className="p-3">Region</th>
                                                    <th className="p-3">Size</th>
                                                </tr>
                                            </thead>
                                            <tbody className="divide-y divide-slate-700/50">
                                                {filteredMissing.map((rom, i) => (
                                                    <tr key={i} className="hover:bg-slate-800/30">
                                                        <td className="p-3 text-red-300">{rom.rom_name}</td>
                                                        <td className="p-3">{rom.game_name}</td>
                                                        <td className="p-3 text-slate-400">{rom.system}</td>
                                                        <td className="p-3"><RegionBadge region={rom.region} /></td>
                                                        <td className="p-3 text-slate-400">{rom.size_formatted}</td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                )}

                                {/* Empty state */}
                                {((activeTab === 'identified' && filteredIdentified.length === 0) ||
                                  (activeTab === 'unidentified' && filteredUnidentified.length === 0) ||
                                  (activeTab === 'missing' && filteredMissing.length === 0)) && (
                                    <div className="p-12 text-center text-slate-500">
                                        <div className="text-4xl mb-2">&#128196;</div>
                                        <p>No files to display</p>
                                        <p className="text-sm">{activeTab === 'missing' ? 'Load DATs and scan ROMs to see missing items' : 'Load a DAT and scan your ROMs'}</p>
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* ── Organization ── */}
                        <div className="bg-slate-800/50 backdrop-blur border border-slate-700 rounded-xl p-5">
                            <h2 className="font-semibold mb-4 flex items-center gap-2">
                                <span className="text-amber-400">&#9889;</span> Organization
                            </h2>
                            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2 mb-4">
                                {[
                                    { id: 'system', name: 'By System', desc: 'Per-system folders' },
                                    { id: '1g1r', name: '1 Game 1 ROM', desc: 'Best version/game' },
                                    { id: 'region', name: 'By Region', desc: 'Region folders' },
                                    { id: 'alphabetical', name: 'Alphabetical', desc: 'A-Z folders' },
                                    { id: 'emulationstation', name: 'EmulationStation', desc: 'ES/RetroPie' },
                                    { id: 'flat', name: 'Flat', desc: 'Renamed only' },
                                ].map(s => (
                                    <button key={s.id} onClick={() => setStrategy(s.id)}
                                        className={`p-3 rounded-lg border text-left transition ${
                                            strategy === s.id ? 'bg-cyan-900/30 border-cyan-500 text-cyan-300' : 'bg-slate-900/30 border-slate-600 hover:border-slate-500'
                                        }`}>
                                        <div className="font-medium text-sm">{s.name}</div>
                                        <div className="text-xs text-slate-500">{s.desc}</div>
                                    </button>
                                ))}
                            </div>
                            <div className="flex flex-wrap gap-4 items-end">
                                <div className="flex-1 min-w-[250px]">
                                    <label className="block text-sm text-slate-400 mb-2">Output Folder</label>
                                    <div className="flex gap-2">
                                        <input type="text" value={outputFolder} onChange={e => setOutputFolder(e.target.value)}
                                            placeholder="C:\path\to\output"
                                            className="w-full px-4 py-2 bg-slate-900/50 border border-slate-600 rounded-lg focus:outline-none focus:border-cyan-500 text-sm" />
                                        <button onClick={()=>openBrowser('dir', setOutputFolder)} className="px-3 bg-blue-600 hover:bg-blue-500 rounded text-sm" title="Browse folder">Browse</button>
                                    </div>
                                </div>
                                <div>
                                    <label className="block text-sm text-slate-400 mb-2">Action</label>
                                    <div className="flex gap-2">
                                        <button onClick={() => setAction('copy')}
                                            className={`px-4 py-2 rounded-lg border transition text-sm ${
                                                action === 'copy' ? 'bg-blue-900/30 border-blue-500 text-blue-300' : 'bg-slate-900/30 border-slate-600'
                                            }`}>Copy</button>
                                        <button onClick={() => setAction('move')}
                                            className={`px-4 py-2 rounded-lg border transition text-sm ${
                                                action === 'move' ? 'bg-amber-900/30 border-amber-500 text-amber-300' : 'bg-slate-900/30 border-slate-600'
                                            }`}>Move</button>
                                    </div>
                                </div>
                                <div className="flex gap-2">
                                    <button onClick={previewOrganize} disabled={results.identified.length === 0}
                                        className="px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded-lg font-medium transition text-sm">
                                        Preview
                                    </button>
                                    <button onClick={doOrganize} disabled={results.identified.length === 0}
                                        className="px-6 py-2 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 disabled:opacity-50 rounded-lg font-medium transition shadow-lg shadow-cyan-900/30 text-sm">
                                        Organize!
                                    </button>
                                    <button onClick={undoOrganize}
                                        className="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg font-medium transition text-sm">
                                        Undo
                                    </button>
                                </div>
                            </div>
                        </div>

                        <p className="text-center text-slate-500 text-sm">
                            R0MM v2 &mdash; Supports No-Intro, Redump, TOSEC and any XML-based DAT files
                        </p>
                    </div>
                </div>
            );
        }

        ReactDOM.createRoot(document.getElementById('root')).render(<App />);
    {% endraw %}
    </script>
</body>
</html>
'''


def run_server(host='127.0.0.1', port=5000, debug=False):
    """Run the web server"""
    logger = setup_runtime_monitor()
    monitor_action(f"run_server called: host={host} port={port} debug={debug}", logger=logger)
    print(f"R0MM v2 - Web Interface")
    print(f"=" * 50)
    print(f"Open in your browser: http://{host}:{port}")
    print(f"Press Ctrl+C to stop")
    print()
    app.run(host=host, port=port, debug=debug, threaded=True)