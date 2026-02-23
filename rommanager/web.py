"""
Web API for R0MM using Flask + embedded React UI
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

from flask import Flask, jsonify, request, render_template_string, send_file
from werkzeug.utils import secure_filename

from .monitor import setup_runtime_monitor, monitor_action
from .settings import load_settings, save_settings, apply_runtime_settings
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
from .auto_downloader import AutoDownloadTaskRegistry
from .session_state import build_snapshot, save_snapshot, load_snapshot, restore_into_matcher, restore_scanned
from . import __version__
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
    'settings': load_settings(),
    'auto_downloads': AutoDownloadTaskRegistry(),
}


def persist_web_session() -> None:
    snapshot = build_snapshot(
        dats=state['multi_matcher'].get_dat_list(),
        identified=state['identified'],
        unidentified=state['unidentified'],
        extras={
            'blindmatch_mode': state.get('blindmatch_mode', False),
            'blindmatch_system': state.get('blindmatch_system', ''),
        },
    )
    save_snapshot(snapshot)


def restore_web_session() -> None:
    snap = load_snapshot()
    if not snap:
        return
    restore_into_matcher(state['multi_matcher'], snap)
    state['identified'], state['unidentified'] = restore_scanned(snap)
    extras = snap.get('extras', {})
    state['blindmatch_mode'] = bool(extras.get('blindmatch_mode', False))
    state['blindmatch_system'] = extras.get('blindmatch_system', '')


restore_web_session()

_client_activity = {
    'seen': False,
    'last_seen': 0.0,
}
_idle_shutdown_started = False


def _mark_client_activity() -> None:
    _client_activity['seen'] = True
    _client_activity['last_seen'] = time.time()


def _idle_shutdown_worker(timeout_seconds: int = 6) -> None:
    while True:
        time.sleep(1.0)
        if not _client_activity['seen']:
            continue
        if (time.time() - _client_activity['last_seen']) > timeout_seconds:
            os._exit(0)


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


@app.before_request
def track_client_activity():
    if request.path.startswith('/api/'):
        _mark_client_activity()


@app.after_request
def autosave_session(response):
    if request.method != 'GET' and response.status_code < 400:
        try:
            persist_web_session()
        except Exception:
            pass
    return response


@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    _mark_client_activity()
    return jsonify({'ok': True})


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


@app.route('/api/new-session', methods=['POST'])
def new_session():
    state['multi_matcher'] = MultiROMMatcher()
    state['identified'] = []
    state['unidentified'] = []
    state['scanning'] = False
    state['scan_progress'] = 0
    state['scan_total'] = 0
    state['blindmatch_mode'] = False
    state['blindmatch_system'] = ''
    persist_web_session()
    return jsonify({'ok': True})


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
        # Background thumbnail fetch for identified ROMs
        _bg_fetch_thumbnails()


def _bg_fetch_thumbnails():
    """Trigger background thumbnail download for all identified ROMs."""
    import threading as _th
    from rommanager.thumbnail_service import ThumbnailService
    from rommanager.shared_config import THUMBNAILS_DIR
    items = []
    for sf in state.get('identified', []):
        rom = getattr(sf, 'matched_rom', None)
        if rom and getattr(rom, 'system_name', None) and getattr(rom, 'game_name', None):
            items.append((rom.system_name, rom.game_name))
    if items:
        def _run():
            ts = ThumbnailService(THUMBNAILS_DIR)
            ts.fetch_batch_sync(items)
        _th.Thread(target=_run, daemon=True).start()


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


@app.route('/api/auto-download/start', methods=['POST'])
def auto_download_start():
    data = request.get_json() or {}
    rom_name = data.get('rom_name', '')
    if not rom_name:
        return jsonify({'error': 'rom_name is required'}), 400

    missing_roms = state['multi_matcher'].get_missing(state['identified'])
    rom = next((r for r in missing_roms if r.name == rom_name), None)
    if rom is None:
        return jsonify({'error': 'ROM not found in missing list'}), 404

    task_id = state['auto_downloads'].start(rom)
    return jsonify({'task_id': task_id})


@app.route('/api/auto-download/status/<task_id>')
def auto_download_status(task_id: str):
    task = state['auto_downloads'].get(task_id)
    if task is None:
        return jsonify({'error': 'task not found'}), 404

    payload = {
        'task_id': task.task_id,
        'status': task.status,
        'progress': task.progress,
        'message': task.message,
        'destination': task.destination,
        'error': task.error,
        'rom_name': task.rom_name,
    }
    return jsonify(payload)


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


# ── Thumbnail API ─────────────────────────────────────────────

@app.route('/api/thumbnail/<path:system>/<path:game_name>')
def api_thumbnail(system, game_name):
    from rommanager.shared_config import THUMBNAILS_DIR
    from rommanager.thumbnail_service import _sanitize_game_name, _system_folder
    folder = _system_folder(system)
    if not folder:
        return '', 404
    safe_name = _sanitize_game_name(game_name)
    path = os.path.join(THUMBNAILS_DIR, folder, f"{safe_name}.png")
    if os.path.isfile(path):
        return send_file(path, mimetype='image/png')
    return '', 404


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
    })


# ── HTML Template ──────────────────────────────────────────────

HTML_TEMPLATE = r'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>R0MM ver 0.30rc</title>
    <script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #1e1e2e;
            --bg-dim: #181825;
            --bg-deep: #11111b;
            --surface0: #313244;
            --surface1: #45475a;
            --surface2: #585b70;
            --text: #cdd6f4;
            --subtext1: #bac2de;
            --subtext0: #a6adc8;
            --overlay2: #9399b2;
            --overlay1: #7f849c;
            --overlay0: #6c7086;
            --primary: #cba6f7;
            --secondary: #89b4fa;
            --success: #a6e3a1;
            --warning: #f9e2af;
            --error: #f38ba8;
            --info: #94e2d5;
            --peach: #fab387;
            --pink: #f5c2e7;
            --sky: #89dceb;
            --lavender: #b4befe;
            --flamingo: #f2cdcd;
            --rosewater: #f5e0dc;
        }
        body { font-family: 'Inter', sans-serif; background-color: var(--bg); color: var(--text); }
        .loader { border: 3px solid var(--surface1); border-top: 3px solid var(--primary); border-radius: 50%; width: 20px; height: 20px; animation: spin 1s linear infinite; display: inline-block; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 100; }
        .modal-content { background: var(--bg-dim); border: 1px solid var(--surface1); border-radius: 12px; max-width: 800px; width: 90%; max-height: 80vh; overflow-y: auto; padding: 24px; }
        @keyframes skeleton-pulse { 0%, 100% { opacity: 0.4; } 50% { opacity: 0.8; } }
        .skeleton { background: var(--surface0); border-radius: 6px; animation: skeleton-pulse 1.5s ease-in-out infinite; }
        .skeleton-row { height: 44px; margin-bottom: 4px; }
        .skeleton-card { width: 180px; height: 260px; border-radius: 12px; }
        .dropzone { border: 2px dashed var(--overlay1); border-radius: 12px; padding: 24px; text-align: center; color: var(--overlay0); transition: all 0.2s ease; cursor: pointer; }
        .dropzone.dragover { border-color: var(--primary); background: rgba(203, 166, 247, 0.05); color: var(--primary); }
        .toast-container { position: fixed; bottom: 20px; right: 20px; z-index: 200; display: flex; flex-direction: column-reverse; gap: 8px; max-width: 380px; }
        .toast { padding: 12px 16px; border-radius: 10px; background: var(--surface0); border-left: 4px solid var(--info); box-shadow: 0 4px 20px rgba(0,0,0,0.4); display: flex; align-items: center; gap: 10px; animation: toast-in 0.3s ease-out; position: relative; overflow: hidden; }
        .toast.success { border-left-color: var(--success); }
        .toast.error { border-left-color: var(--error); }
        .toast.warning { border-left-color: var(--warning); }
        .toast.info { border-left-color: var(--info); }
        .toast .toast-progress { position: absolute; bottom: 0; left: 0; height: 3px; background: var(--overlay1); animation: toast-progress 4s linear forwards; }
        @keyframes toast-in { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
        @keyframes toast-progress { from { width: 100%; } to { width: 0%; } }
        .poster-card { width: 180px; border-radius: 12px; background: var(--surface0); border: 1px solid var(--surface1); overflow: hidden; cursor: pointer; transition: transform 0.2s ease, box-shadow 0.2s ease; }
        .poster-card:hover { transform: scale(1.03); box-shadow: 0 8px 24px rgba(0,0,0,0.4); }
        .poster-card img, .poster-card .poster-placeholder { width: 100%; height: 200px; object-fit: cover; }
        .poster-placeholder { display: flex; align-items: center; justify-content: center; font-size: 48px; font-weight: bold; color: var(--overlay0); }
        .poster-info { padding: 8px 10px; background: var(--bg-dim); }
        .empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 60px 20px; text-align: center; }
        .empty-state svg { width: 80px; height: 80px; color: var(--overlay0); margin-bottom: 16px; opacity: 0.6; }
        .empty-state h3 { font-size: 20px; font-weight: 600; color: var(--text); margin-bottom: 8px; }
        .empty-state p { font-size: 14px; color: var(--subtext0); margin-bottom: 20px; }
        .empty-state button { padding: 10px 24px; background: linear-gradient(135deg, var(--primary), var(--secondary)); border: none; border-radius: 8px; color: var(--bg-deep); font-weight: 600; font-size: 14px; cursor: pointer; transition: opacity 0.2s; }
        .empty-state button:hover { opacity: 0.85; }
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
                            <h3 className="text-lg font-bold" style={{color:'var(--primary)'}}>Browse {mode === 'dir' ? 'Folder' : 'File'}</h3>
                            <button onClick={onClose} className="text-xl" style={{color:'var(--subtext0)'}}>&#x2715;</button>
                        </div>
                        <div className="p-2 rounded mb-2 text-xs font-mono truncate" style={{backgroundColor:'var(--bg)',border:'1px solid var(--surface1)',color:'var(--subtext1)'}}>
                            {path || "Root"}
                        </div>
                        <div className="flex-1 overflow-auto rounded h-80 p-2" style={{backgroundColor:'var(--bg-dim)',border:'1px solid var(--surface1)'}}>
                            {loading ? <div className="text-center p-4" style={{color:'var(--overlay1)'}}>Loading...</div> :
                             items.map((item, i) => (
                                <div key={i} onClick={() => handleItemClick(item)}
                                     className="flex items-center gap-2 p-2 cursor-pointer rounded text-sm" style={{color:'var(--subtext1)'}}>
                                    <span className="text-lg" style={{color:'var(--warning)'}}>{item.type === 'dir' ? '📁' : '📄'}</span>
                                    <span className={item.type === 'dir' ? 'font-bold' : ''} style={item.type === 'dir' ? {color:'var(--text)'} : {}}>{item.name}</span>
                                </div>
                            ))}
                        </div>
                        <div className="mt-4 flex justify-end gap-2">
                            <button onClick={onClose} className="px-4 py-2 rounded-lg text-sm" style={{backgroundColor:'var(--surface1)'}}>Cancel</button>
                            {mode === 'dir' && (
                                <button onClick={() => onSelect(path)} className="px-4 py-2 rounded-lg text-sm font-medium" style={{backgroundColor:'var(--primary)',color:'var(--bg-deep)'}}>
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
            'USA':    { bg: 'rgba(137,180,250,0.15)', fg: 'var(--secondary)' },
            'Europe': { bg: 'rgba(203,166,247,0.15)', fg: 'var(--primary)' },
            'Japan':  { bg: 'rgba(243,139,168,0.15)', fg: 'var(--error)' },
            'World':  { bg: 'rgba(166,227,161,0.15)', fg: 'var(--success)' },
            'Brazil': { bg: 'rgba(249,226,175,0.15)', fg: 'var(--warning)' },
            'Korea':  { bg: 'rgba(250,179,135,0.15)', fg: 'var(--peach)' },
            'China':  { bg: 'rgba(242,205,205,0.15)', fg: 'var(--flamingo)' },
        };
        const defaultRegionCSS = { bg: 'rgba(127,132,156,0.15)', fg: 'var(--overlay1)' };
        function RegionBadge({ region }) {
            const c = REGION_CSS[region] || defaultRegionCSS;
            return <span style={{background: c.bg, color: c.fg, padding: '2px 8px', borderRadius: '4px', fontSize: '12px'}}>{region || 'Unknown'}</span>;
        }

        /* ── Toast Notification System ──────────── */
        const ToastContext = React.createContext(null);
        function ToastProvider({ children }) {
            const [toasts, setToasts] = React.useState([]);
            const nextId = React.useRef(0);
            const addToast = React.useCallback((message, type = 'info') => {
                const id = nextId.current++;
                setToasts(prev => [...prev.slice(-2), { id, message, type }]);
                setTimeout(() => {
                    setToasts(prev => prev.filter(t => t.id !== id));
                }, 4000);
            }, []);
            const removeToast = React.useCallback((id) => {
                setToasts(prev => prev.filter(t => t.id !== id));
            }, []);
            return (
                <ToastContext.Provider value={addToast}>
                    {children}
                    <div className="toast-container">
                        {toasts.map(t => (
                            <div key={t.id} className={`toast ${t.type}`} onClick={() => removeToast(t.id)}>
                                <span style={{flex:1}}>{t.message}</span>
                                <span style={{cursor:'pointer',opacity:0.6}}>&#x2715;</span>
                                <div className="toast-progress"></div>
                            </div>
                        ))}
                    </div>
                </ToastContext.Provider>
            );
        }
        function useToast() { return React.useContext(ToastContext); }

        /* ── Modal ────────────────────────────── */
        function Modal({ title, children, onClose }) {
            return (
                <div className="modal-overlay" onClick={onClose}>
                    <div className="modal-content" onClick={e => e.stopPropagation()}>
                        <div className="flex justify-between items-center mb-4">
                            <h2 className="text-lg font-bold" style={{color:'var(--primary)'}}>{title}</h2>
                            <button onClick={onClose} className="text-xl" style={{color:'var(--subtext0)'}}>&#x2715;</button>
                        </div>
                        {children}
                    </div>
                </div>
            );
        }

        /* ── Poster Card (Grid View) ────────────── */
        function PosterCard({ rom }) {
            const thumbSrc = `/api/thumbnail/${encodeURIComponent(rom.system)}/${encodeURIComponent(rom.game_name)}`;
            const [imgError, setImgError] = React.useState(false);
            const initial = (rom.game_name || '?')[0].toUpperCase();
            const colors = ['#cba6f7','#89b4fa','#a6e3a1','#f9e2af','#f38ba8','#fab387','#94e2d5','#89dceb'];
            const colorIdx = rom.game_name ? rom.game_name.charCodeAt(0) % colors.length : 0;
            return (
                <div className="poster-card">
                    {!imgError ? (
                        <img src={thumbSrc} alt={rom.game_name}
                            onError={() => setImgError(true)}
                            style={{width:'100%',height:'200px',objectFit:'cover'}} />
                    ) : (
                        <div className="poster-placeholder" style={{background: `linear-gradient(135deg, ${colors[colorIdx]}22, ${colors[colorIdx]}44)`}}>
                            {initial}
                        </div>
                    )}
                    <div className="poster-info">
                        <div style={{fontSize:'12px',fontWeight:600,color:'var(--text)',overflow:'hidden',display:'-webkit-box',WebkitLineClamp:2,WebkitBoxOrient:'vertical'}}>{rom.game_name}</div>
                        <div style={{fontSize:'10px',color:'var(--subtext0)',marginTop:'2px'}}>{rom.system}</div>
                        <div style={{marginTop:'4px'}}><RegionBadge region={rom.region} /></div>
                    </div>
                </div>
            );
        }

        /* ── Dropzone ───────────────────────────── */
        function Dropzone({ label, onDrop }) {
            const [dragover, setDragover] = React.useState(false);
            return (
                <div className={`dropzone ${dragover ? 'dragover' : ''}`}
                    onDragOver={e => { e.preventDefault(); setDragover(true); }}
                    onDragLeave={() => setDragover(false)}
                    onDrop={e => {
                        e.preventDefault(); setDragover(false);
                        const paths = [];
                        if (e.dataTransfer.files.length > 0) {
                            for (let f of e.dataTransfer.files) paths.push(f.name);
                        }
                        if (paths.length > 0 && onDrop) onDrop(paths);
                    }}>
                    <div style={{fontSize:'28px',marginBottom:'8px',opacity:0.5}}>&#128230;</div>
                    <div>{label}</div>
                </div>
            );
        }

        /* ── Skeleton Loaders ───────────────────── */
        function SkeletonTable({ rows = 8 }) {
            return (
                <div style={{padding:'4px'}}>
                    {Array.from({length: rows}).map((_, i) => (
                        <div key={i} className="skeleton skeleton-row" style={{animationDelay: `${i * 0.1}s`}}></div>
                    ))}
                </div>
            );
        }
        function SkeletonGrid({ count = 8 }) {
            return (
                <div style={{display:'flex',flexWrap:'wrap',gap:'16px',padding:'8px'}}>
                    {Array.from({length: count}).map((_, i) => (
                        <div key={i} className="skeleton skeleton-card" style={{animationDelay: `${i * 0.08}s`}}></div>
                    ))}
                </div>
            );
        }

        /* ── Empty State ────────────────────────── */
        function EmptyState({ icon, heading, subtext, ctaLabel, onCta }) {
            const icons = {
                gamepad: <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" d="M14.25 6.087c0-.355.186-.676.401-.959.221-.29.349-.634.349-1.003 0-1.036-1.007-1.875-2.25-1.875S10.5 3.09 10.5 4.125c0 .369.128.713.349 1.003.215.283.401.604.401.959v0a.64.64 0 01-.657.643 48.491 48.491 0 01-4.163-.3c-1.108-.128-2.18.225-2.837.914a2.26 2.26 0 00-.418.55L1.293 10.77a1 1 0 00.668 1.47c.637.112 1.287.195 1.942.249 3.726.308 7.468.308 11.194 0a26.1 26.1 0 001.942-.249 1 1 0 00.668-1.47L15.825 7.894a2.26 2.26 0 00-.418-.55c-.657-.689-1.729-1.042-2.837-.914a48.491 48.491 0 01-4.163.3.64.64 0 01-.657-.643v0z" /><path strokeLinecap="round" strokeLinejoin="round" d="M12 12.75c-2.472 0-4.9-.184-7.274-.54a1 1 0 00-1.09.618l-1.454 3.926A2.25 2.25 0 004.293 19.5h15.414a2.25 2.25 0 002.111-2.746l-1.454-3.926a1 1 0 00-1.09-.618A49.261 49.261 0 0112 12.75z" /></svg>,
                folder_search: <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607zM13.5 10.5H10.5m0 0H7.5m3 0V7.5m0 3V13.5" /></svg>,
                search_off: <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" /></svg>,
            };
            return (
                <div className="empty-state">
                    {icons[icon] || icons.search_off}
                    <h3>{heading}</h3>
                    <p>{subtext}</p>
                    {ctaLabel && <button onClick={onCta}>{ctaLabel}</button>}
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
            const [viewMode, setViewMode] = useState('list');
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
            const [autoDownloadTasks, setAutoDownloadTasks] = useState({});

            const toast = useToast();
            const notify = (type, message) => {
                toast(message, type);
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

            useEffect(() => {
                const ping = () => api.post('/api/heartbeat', {});
                ping();
                const iv = setInterval(ping, 2000);
                const onBeforeUnload = () => { navigator.sendBeacon('/api/heartbeat', new Blob([], { type: 'application/json' })); };
                window.addEventListener('beforeunload', onBeforeUnload);
                return () => {
                    clearInterval(iv);
                    window.removeEventListener('beforeunload', onBeforeUnload);
                };
            }, []);
            // set descriptive hover tooltips for button actions
            useEffect(() => {
                const isPt = (navigator.language || '').toLowerCase().startsWith('pt');
                const tipMapEn = {
                    'Browse': 'Open the file browser to select a file or folder path.',
                    'Add': 'Load the DAT file path into the active DAT list.',
                    'Scan': 'Start scanning ROM files in the selected folder.',
                    'Preview': 'Preview destination paths before organizing files.',
                    'Organize': 'Execute organization using selected strategy and action.',
                    'Undo': 'Undo the most recent organization operation.',
                    'Refresh': 'Recompute missing ROMs from current data.',
                    'Search': 'Open external search tools for missing entries.',
                    'Force Identify': 'Move selected unidentified files to identified list.',
                    'Save Current': 'Save current DATs and scan results as a collection.',
                    'Load': 'Load this collection into the current session.',
                    'Remove': 'Remove this item from the current list.',
                    'Collections': 'Open saved collections manager.',
                    'DAT Library': 'Open DAT library manager.',
                    'Cancel': 'Close this dialog without applying changes.',
                    'Execute': 'Run this action now.',
                    'Close': 'Close this dialog.'
                };
                const tipMapPt = {
                    'Browse': 'Abre o navegador de arquivos para selecionar um caminho.',
                    'Add': 'Carrega o caminho do DAT na lista ativa.',
                    'Scan': 'Inicia o escaneamento de ROMs na pasta selecionada.',
                    'Preview': 'Mostra destinos antes de organizar os arquivos.',
                    'Organize': 'Executa a organização com a estratégia e ação escolhidas.',
                    'Undo': 'Desfaz a operação de organização mais recente.',
                    'Refresh': 'Recalcula ROMs faltantes com os dados atuais.',
                    'Search Archive': 'Abre ferramentas de busca no Archive.org.',
                    'Force Identify': 'Move arquivos não identificados para identificados.',
                    'Save Current': 'Salva DATs e resultados atuais como coleção.',
                    'Load': 'Carrega esta coleção na sessão atual.',
                    'Remove': 'Remove este item da lista atual.',
                    'Collections': 'Abre o gerenciador de coleções salvas.',
                    'DAT Library': 'Abre o gerenciador da biblioteca de DAT.',
                    'Cancel': 'Fecha esta janela sem aplicar alterações.',
                    'Execute': 'Executa esta ação agora.',
                    'Close': 'Fecha esta janela.'
                };
                const map = isPt ? tipMapPt : tipMapEn;
                const applyTips = () => {
                    document.querySelectorAll('button').forEach((b) => {
                        const t = (b.innerText || '').trim();
                        if (map[t]) b.title = map[t];
                        else if (!b.title || !b.title.trim()) b.title = t || 'Action';
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

            const newSession = async () => {
                const shouldSave = window.confirm('Deseja salvar a sessão atual antes de iniciar uma nova sessão?');
                if (shouldSave) {
                    const name = prompt('Nome da coleção para salvar:', `autosave-${Date.now()}`);
                    if (name) {
                        const saved = await api.post('/api/collection/save', { name });
                        if (saved.error) return notify('error', saved.error);
                    }
                }
                const res = await api.post('/api/new-session', {});
                if (res.error) notify('error', res.error);
                else {
                    setActiveTab('identified');
                    notify('success', 'Nova sessão iniciada');
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

            const startAutoDownload = async (rom) => {
                const start = await api.post('/api/auto-download/start', { rom_name: rom.rom_name });
                if (start.error || !start.task_id) {
                    notify('error', start.error || 'Could not start auto-download');
                    return;
                }
                setAutoDownloadTasks(prev => ({ ...prev, [rom.rom_name]: { task_id: start.task_id, status: 'queued', progress: 0, message: 'Queued' } }));
            };

            useEffect(() => {
                const pendingEntries = Object.entries(autoDownloadTasks).filter(([, t]) => t.status === 'queued' || t.status === 'running');
                if (!pendingEntries.length) return;

                const iv = setInterval(async () => {
                    const updates = {};
                    for (const [, t] of pendingEntries) {
                        const st = await api.get(`/api/auto-download/status/${t.task_id}`);
                        if (st && !st.error) {
                            updates[st.rom_name] = st;
                            if (st.status === 'done') {
                                notify('success', `${st.rom_name} installed`);
                                refreshMissing();
                            } else if (st.status === 'failed') {
                                notify('error', `${st.rom_name}: download failed`);
                            }
                        }
                    }
                    if (Object.keys(updates).length) {
                        setAutoDownloadTasks(prev => ({ ...prev, ...updates }));
                    }
                }, 1200);

                return () => clearInterval(iv);
            }, [autoDownloadTasks]);

            const progress = status.scan_total > 0 ? (status.scan_progress / status.scan_total * 100) : 0;
            const comp = missing.completeness || {};

            return (
                <div className="min-h-screen p-6" style={{background:'linear-gradient(135deg, var(--bg), var(--bg-dim), var(--bg))',color:'var(--text)'}}>

                    {browserMode && <FileBrowser mode={browserMode} onSelect={browserCallback} onClose={() => setBrowserMode(null)} />}

                    {/* ── Preview Modal ── */}
                    {showPreview && previewData && (
                        <Modal title="Organization Preview" onClose={() => setShowPreview(false)}>
                            <div className="space-y-3 text-sm">
                                <div className="flex gap-6">
                                    <span style={{color:'var(--subtext0)'}}>Strategy: <span style={{color:'var(--text)'}}>{previewData.strategy}</span></span>
                                    <span style={{color:'var(--subtext0)'}}>Files: <span style={{color:'var(--text)'}}>{previewData.total_files}</span></span>
                                    <span style={{color:'var(--subtext0)'}}>Size: <span style={{color:'var(--text)'}}>{previewData.total_size_formatted}</span></span>
                                </div>
                                <div className="max-h-60 overflow-auto rounded p-2" style={{backgroundColor:'var(--bg)'}}>
                                    {previewData.actions.slice(0, 200).map((a, i) => (
                                        <div key={i} className="py-1 text-xs" style={{borderBottom:'1px solid var(--surface0)'}}>
                                            <span style={{color:'var(--overlay1)'}}>{a.action}</span>
                                            <span className="ml-2" style={{color:'var(--primary)'}}>{a.source.split(/[/\\]/).pop()}</span>
                                            <span className="mx-1" style={{color:'var(--surface2)'}}>&#8594;</span>
                                            <span style={{color:'var(--success)'}}>{a.destination}</span>
                                        </div>
                                    ))}
                                    {previewData.actions.length > 200 && <div className="text-xs py-1" style={{color:'var(--overlay1)'}}>... and {previewData.actions.length - 200} more</div>}
                                </div>
                                <div className="flex gap-2 justify-end">
                                    <button onClick={() => setShowPreview(false)} className="px-4 py-2 rounded-lg" style={{backgroundColor:'var(--surface1)'}}>Cancel</button>
                                    <button onClick={doOrganize} className="px-4 py-2 rounded-lg font-medium" style={{backgroundColor:'var(--primary)',color:'var(--bg-deep)'}}>Execute</button>
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
                                        placeholder="Collection name" className="flex-1 px-3 py-2 rounded-lg text-sm focus:outline-none" style={{backgroundColor:'var(--bg)',border:'1px solid var(--surface2)',color:'var(--text)'}} />
                                    <button onClick={saveCollection} className="px-4 py-2 rounded-lg text-sm font-medium" style={{backgroundColor:'var(--primary)',color:'var(--bg-deep)'}}>Save Current</button>
                                </div>
                                {collections.length > 0 && (
                                    <div className="space-y-2">
                                        <h3 className="text-sm font-medium" style={{color:'var(--subtext0)'}}>Saved Collections</h3>
                                        {collections.map((c, i) => (
                                            <div key={i} className="flex items-center justify-between p-3 rounded-lg" style={{backgroundColor:'var(--bg-dim)'}}>
                                                <div>
                                                    <div className="font-medium">{c.name}</div>
                                                    <div className="text-xs" style={{color:'var(--overlay1)'}}>{c.dat_count} DATs, {c.identified_count} identified - {c.updated_at ? new Date(c.updated_at).toLocaleDateString() : ''}</div>
                                                </div>
                                                <button onClick={() => loadCollection(c.filepath)} className="px-3 py-1 rounded text-sm" style={{backgroundColor:'var(--primary)',color:'var(--bg-deep)'}}>Load</button>
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
                                    <button onClick={importToLibrary} className="px-3 py-2 rounded-lg text-sm" style={{backgroundColor:'var(--success)',color:'var(--bg-deep)'}}>Import Current DAT Path</button>
                                    <button onClick={openDatSources} className="px-3 py-2 rounded-lg text-sm" style={{backgroundColor:'var(--secondary)',color:'var(--bg-deep)'}}>DAT Sources</button>
                                </div>
                                {libraryDats.length > 0 ? (
                                    <div className="space-y-2">
                                        {libraryDats.map((d, i) => (
                                            <div key={i} className="flex items-center justify-between p-3 rounded-lg" style={{backgroundColor:'var(--bg-dim)'}}>
                                                <div>
                                                    <div className="font-medium text-sm">{d.system_name || d.name}</div>
                                                    <div className="text-xs" style={{color:'var(--overlay1)'}}>{d.rom_count.toLocaleString()} ROMs - v{d.version || '?'}</div>
                                                </div>
                                                <div className="flex gap-2">
                                                    <button onClick={() => loadFromLibrary(d.id)} className="px-3 py-1 rounded text-xs" style={{backgroundColor:'var(--primary)',color:'var(--bg-deep)'}}>Load</button>
                                                    <button onClick={() => removeFromLibrary(d.id)} className="px-3 py-1 rounded text-xs" style={{backgroundColor:'rgba(243,139,168,0.15)',color:'var(--error)'}}>Remove</button>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                ) : <p className="text-sm" style={{color:'var(--overlay1)'}}>No DATs in library. Import a DAT file or check DAT Sources.</p>}
                            </div>
                        </Modal>
                    )}

                    {/* ── DAT Sources Modal ── */}
                    {showDatSources && (
                        <Modal title="DAT Sources" onClose={() => setShowDatSources(false)}>
                            <div className="space-y-3">
                                {datSources.map((s, i) => (
                                    <div key={i} className="p-3 rounded-lg" style={{backgroundColor:'var(--bg-dim)'}}>
                                        <div className="font-medium text-sm" style={{color:'var(--secondary)'}}>{s.name}</div>
                                        <div className="text-xs mt-1" style={{color:'var(--subtext0)'}}>{s.description}</div>
                                        <a href={s.url} target="_blank" rel="noopener noreferrer"
                                            className="text-xs hover:underline mt-1 inline-block" style={{color:'var(--secondary)'}}>Open Page &#8599;</a>
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
                                        placeholder="Search for ROMs..." className="flex-1 px-3 py-2 rounded-lg text-sm focus:outline-none" style={{backgroundColor:'var(--bg)',border:'1px solid var(--surface2)',color:'var(--text)'}} />
                                    <button onClick={searchArchive} disabled={archiveSearching}
                                        className="px-4 py-2 disabled:opacity-50 rounded-lg text-sm flex items-center gap-2" style={{backgroundColor:'var(--primary)',color:'var(--bg-deep)'}}>
                                        {archiveSearching && <span className="loader" style={{width:14,height:14}}></span>}
                                        Search
                                    </button>
                                </div>
                                <div className="max-h-60 overflow-auto space-y-2">
                                    {archiveResults.map((r, i) => (
                                        <div key={i} className="p-3 rounded-lg" style={{backgroundColor:'var(--bg-dim)'}}>
                                            <div className="font-medium text-sm">{r.title || r.identifier}</div>
                                            <div className="text-xs mt-1" style={{color:'var(--overlay1)'}}>{r.description?.substring(0, 120) || 'No description'}</div>
                                            <a href={`https://archive.org/details/${r.identifier}`} target="_blank" rel="noopener noreferrer"
                                                className="text-xs hover:underline mt-1 inline-block" style={{color:'var(--secondary)'}}>View on Archive.org &#8599;</a>
                                        </div>
                                    ))}
                                    {archiveResults.length === 0 && !archiveSearching && <p className="text-sm text-center py-4" style={{color:'var(--overlay1)'}}>Enter a search term to find ROMs on archive.org</p>}
                                </div>
                            </div>
                        </Modal>
                    )}

                    {/* ── Myrient Browser Modal ── */}
                    {showMyrient && (
                        <div className="modal-overlay" onClick={() => setShowMyrient(false)}>
                            <div className="modal-content" style={{maxWidth:'1000px',maxHeight:'85vh'}} onClick={e => e.stopPropagation()}>
                                <div className="flex justify-between items-center mb-4">
                                    <h2 className="text-lg font-bold" style={{color:'var(--primary)'}}>Myrient ROM Browser</h2>
                                    <button onClick={() => setShowMyrient(false)} className="text-xl" style={{color:'var(--subtext0)'}}>&#x2715;</button>
                                </div>
                                <div className="flex gap-4" style={{height:'60vh'}}>
                                    {/* System list */}
                                    <div className="w-1/3 flex flex-col">
                                        <div className="text-sm font-medium mb-1" style={{color:'var(--subtext0)'}}>Systems</div>
                                        <input type="text" value={myrientSysSearch} onChange={e => setMyrientSysSearch(e.target.value)}
                                            placeholder="Filter systems..." className="px-2 py-1 rounded text-xs mb-2 focus:outline-none" style={{backgroundColor:'var(--bg)',border:'1px solid var(--surface1)',color:'var(--text)'}} />
                                        <div className="flex-1 overflow-auto rounded" style={{backgroundColor:'var(--bg-dim)'}}>
                                            {myrientSystems.filter(s => !myrientSysSearch || s.name.toLowerCase().includes(myrientSysSearch.toLowerCase())).map((s, i) => (
                                                <div key={i} onClick={() => loadMyrientFiles(s.name)}
                                                    className="px-3 py-2 text-xs cursor-pointer" style={{borderBottom:'1px solid var(--surface0)',color: myrientSelectedSys === s.name ? 'var(--secondary)' : 'var(--text)',backgroundColor: myrientSelectedSys === s.name ? 'rgba(203,166,247,0.1)' : 'transparent'}}>
                                                    <span style={{color:'var(--overlay1)'}}>[{s.category}]</span> {s.name}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                    {/* File list */}
                                    <div className="w-2/3 flex flex-col">
                                        <div className="flex gap-2 mb-2">
                                            <input type="text" value={myrientFileSearch} onChange={e => setMyrientFileSearch(e.target.value)}
                                                onKeyDown={e => e.key === 'Enter' && searchMyrientFiles()}
                                                placeholder="Search files..." className="flex-1 px-2 py-1 rounded text-xs focus:outline-none" style={{backgroundColor:'var(--bg)',border:'1px solid var(--surface1)',color:'var(--text)'}} />
                                            <button onClick={searchMyrientFiles} className="px-3 py-1 rounded text-xs" style={{backgroundColor:'var(--surface1)'}}>Search</button>
                                            <span className="text-xs self-center" style={{color:'var(--overlay1)'}}>{myrientFiles.length} files</span>
                                        </div>
                                        <div className="flex-1 overflow-auto rounded" style={{backgroundColor:'var(--bg-dim)'}} id="myrient-files">
                                            {myrientLoading ? <div className="p-4 text-center" style={{color:'var(--overlay1)'}}><span className="loader"></span> Loading...</div> :
                                                myrientFiles.length === 0 ? <div className="p-4 text-center" style={{color:'var(--overlay1)'}}>Select a system to browse files</div> :
                                                myrientFiles.map((f, i) => (
                                                    <div key={i} className="px-3 py-1.5 text-xs cursor-pointer flex justify-between items-center myrient-file-row" style={{borderBottom:'1px solid var(--surface0)'}}
                                                        onClick={e => e.currentTarget.classList.toggle('myrient-selected')}>
                                                        <span className="truncate mr-2">{f.name}</span>
                                                        <span className="whitespace-nowrap" style={{color:'var(--overlay1)'}}>{f.size_text || ''}</span>
                                                    </div>
                                                ))}
                                        </div>
                                        <div className="flex gap-2 mt-2 items-center">
                                            <input type="text" value={dlDest} onChange={e => setDlDest(e.target.value)}
                                                placeholder="Download destination folder..." className="flex-1 px-2 py-1 rounded text-xs focus:outline-none" style={{backgroundColor:'var(--bg)',border:'1px solid var(--surface1)',color:'var(--text)'}} />
                                            <button onClick={()=>openBrowser('dir', setDlDest)} className="px-3 py-1 rounded text-xs" style={{backgroundColor:'var(--secondary)',color:'var(--bg-deep)'}} title="Browse folder">Browse</button>

                                            <button onClick={() => {
                                                const selected = [];
                                                document.querySelectorAll('#myrient-files .myrient-selected').forEach(el => {
                                                    const idx = Array.from(el.parentNode.children).indexOf(el);
                                                    if (myrientFiles[idx]) selected.push({name: myrientFiles[idx].name, url: myrientFiles[idx].url});
                                                });
                                                if (selected.length === 0) { notify('warning', 'Click on files to select them first'); return; }
                                                downloadMyrientFiles(selected, dlDest);
                                            }} className="px-3 py-1 rounded text-xs font-medium whitespace-nowrap" style={{backgroundColor:'var(--success)',color:'var(--bg-deep)'}}>
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
                                    <label className="text-sm" style={{color:'var(--subtext0)'}}>Download to (scan folder):</label>
                                    <div className="flex gap-2 mt-1">
                                        <input type="text" value={dlDest} onChange={e => setDlDest(e.target.value)}
                                            placeholder="C:\path\to\roms" className="w-full px-3 py-2 rounded-lg text-sm focus:outline-none" style={{backgroundColor:'var(--bg)',border:'1px solid var(--surface2)',color:'var(--text)'}} />
                                        <button onClick={()=>openBrowser('dir', setDlDest)} className="px-3 rounded text-sm" style={{backgroundColor:'var(--secondary)',color:'var(--bg-deep)'}} title="Browse folder">Browse</button>
                                    </div>
                                </div>
                                <div>
                                    <label className="text-sm" style={{color:'var(--subtext0)'}}>Delay between downloads (seconds):</label>
                                    <input type="number" min="0" max="60" value={dlDelay} onChange={e => setDlDelay(Math.max(0, Math.min(60, parseInt(e.target.value) || 0)))}
                                        disabled={dlActive}
                                        className="mt-1 ml-2 w-20 px-3 py-2 rounded-lg text-sm focus:outline-none disabled:opacity-50" style={{backgroundColor:'var(--bg)',border:'1px solid var(--surface2)',color:'var(--text)'}} />
                                </div>
                                {dlProgress && (
                                    <div className="space-y-2">
                                        <div className="flex justify-between text-sm">
                                            <span style={{color:'var(--subtext0)'}}>{dlProgress.current_rom || 'Starting...'}</span>
                                            <span style={{color:'var(--primary)'}}>{dlProgress.completed}/{dlProgress.total_count}</span>
                                        </div>
                                        <div className="w-full h-2 rounded-full overflow-hidden" style={{backgroundColor:'var(--surface1)'}}>
                                            <div className="h-full transition-all" style={{background:'linear-gradient(to right, var(--success), var(--primary))',width: `${dlProgress.total_count > 0 ? (dlProgress.completed + dlProgress.failed) / dlProgress.total_count * 100 : 0}%`}}></div>
                                        </div>
                                        {dlProgress.current_total > 0 && (
                                            <div className="w-full h-1.5 rounded-full overflow-hidden" style={{backgroundColor:'var(--surface1)'}}>
                                                <div className="h-full transition-all" style={{backgroundColor:'var(--primary)',width: `${dlProgress.current_bytes / dlProgress.current_total * 100}%`}}></div>
                                            </div>
                                        )}
                                        <div className="text-xs" style={{color:'var(--overlay1)'}}>{dlProgress.completed} OK, {dlProgress.failed} failed{dlProgress.cancelled > 0 ? `, ${dlProgress.cancelled} cancelled` : ''}</div>
                                    </div>
                                )}
                                {dlLog.length > 0 && (
                                    <div className="max-h-32 overflow-auto rounded p-2 text-xs font-mono" style={{backgroundColor:'var(--bg)',color:'var(--subtext0)'}}>
                                        {dlLog.map((l, i) => <div key={i}>{l}</div>)}
                                    </div>
                                )}
                                <div className="flex gap-2 justify-end">
                                    {!dlActive ? (
                                        <>
                                            <button onClick={() => setShowDownloadDialog(false)} className="px-4 py-2 rounded-lg text-sm" style={{backgroundColor:'var(--surface1)'}}>Close</button>
                                            <button onClick={() => startDownloadMissing()} className="px-4 py-2 rounded-lg text-sm font-medium" style={{backgroundColor:'var(--success)',color:'var(--bg-deep)'}}>Action unavailable</button>
                                        </>
                                    ) : (
                                        <>
                                            <button onClick={pauseDl} className="px-4 py-2 rounded-lg text-sm" style={{backgroundColor:'var(--warning)',color:'var(--bg-deep)'}}>Pause</button>
                                            <button onClick={resumeDl} className="px-4 py-2 rounded-lg text-sm" style={{backgroundColor:'var(--secondary)',color:'var(--bg-deep)'}}>Resume</button>
                                            <button onClick={cancelDl} className="px-4 py-2 rounded-lg text-sm" style={{backgroundColor:'var(--error)',color:'var(--bg-deep)'}}>Cancel</button>
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
                                    <h1 className="text-3xl font-bold" style={{background:'linear-gradient(135deg, var(--primary), var(--secondary))',WebkitBackgroundClip:'text',WebkitTextFillColor:'transparent'}}>R0MM</h1>
                                    <p style={{color:'var(--subtext0)'}}>ver 0.30rc &mdash; Multi-DAT, Collections, Missing ROMs</p>
                                </div>
                            </div>
                            <div className="flex gap-2">
                                <button onClick={newSession} className="px-3 py-2 rounded-lg text-sm" style={{backgroundColor:'var(--error)',color:'var(--bg-deep)'}}>Nova sessao</button>
                                <button onClick={openCollections} className="px-3 py-2 rounded-lg text-sm" style={{backgroundColor:'var(--surface1)'}}>Collections</button>
                                <button onClick={openDatLibrary} className="px-3 py-2 rounded-lg text-sm" style={{backgroundColor:'var(--surface1)'}}>DAT Library</button>
                                <button onClick={openMyrientBrowser} className="px-3 py-2 rounded-lg text-sm" style={{backgroundColor:'var(--success)',color:'var(--bg-deep)',opacity:0.5}}>Online Browser (disabled)</button>
                            </div>
                        </div>

                        {/* ── DAT & Scan Cards ── */}
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                            {/* DAT File */}
                            <div className="backdrop-blur rounded-xl p-5" style={{backgroundColor:'var(--surface0)',border:'1px solid var(--surface1)'}}>
                                <h2 className="font-semibold mb-4 flex items-center gap-2">
                                    <span style={{color:'var(--primary)'}}>&#128193;</span> DAT Files
                                </h2>
                                <div className="flex gap-2 mb-3">
                                    <input type="text" value={datPath} onChange={e => setDatPath(e.target.value)}
                                        placeholder="C:\path\to\nointro.dat"
                                        className="flex-1 px-4 py-2 rounded-lg focus:outline-none text-sm" style={{backgroundColor:'var(--bg-dim)',border:'1px solid var(--surface2)',color:'var(--text)'}} />
                                    <button onClick={()=>openBrowser('file', setDatPath)} className="px-3 rounded-l-none rounded-r-lg" style={{backgroundColor:'var(--secondary)',color:'var(--bg-deep)'}} title="Browse folder">Browse</button>
                                    <button onClick={loadDat} className="ml-2 px-4 py-2 rounded-lg font-medium transition text-sm" style={{backgroundColor:'var(--primary)',color:'var(--bg-deep)'}}>Add</button>
                                </div>
                                <Dropzone label="Drop DAT files here" onDrop={paths => { if (paths[0]) setDatPath(paths[0]); }} />
                                {(status.dats_loaded || []).length > 0 && (
                                    <div className="space-y-2 max-h-32 overflow-auto mt-3">
                                        {status.dats_loaded.map((d, i) => (
                                            <div key={i} className="flex items-center justify-between p-2 rounded text-sm" style={{backgroundColor:'var(--bg-dim)'}}>
                                                <div>
                                                    <span className="font-medium" style={{color:'var(--primary)'}}>{d.system_name || d.name}</span>
                                                    <span className="ml-2" style={{color:'var(--overlay1)'}}>({d.rom_count.toLocaleString()} ROMs)</span>
                                                </div>
                                                <button onClick={() => removeDat(d.id)} className="text-xs" style={{color:'var(--error)'}}>&#x2715;</button>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            {/* Scan */}
                            <div className="backdrop-blur rounded-xl p-5" style={{backgroundColor:'var(--surface0)',border:'1px solid var(--surface1)'}}>
                                <h2 className="font-semibold mb-4 flex items-center gap-2">
                                    <span style={{color:'var(--success)'}}>&#128269;</span> Scan ROMs
                                </h2>
                                <div className="flex gap-2 mb-3">
                                    <input type="text" value={romFolder} onChange={e => setRomFolder(e.target.value)}
                                        placeholder="C:\path\to\roms"
                                        className="flex-1 px-4 py-2 rounded-lg focus:outline-none text-sm" style={{backgroundColor:'var(--bg-dim)',border:'1px solid var(--surface2)',color:'var(--text)'}} />
                                    <button onClick={()=>openBrowser('dir', setRomFolder)} className="px-3 rounded-l-none rounded-r-lg" style={{backgroundColor:'var(--success)',color:'var(--bg-deep)'}} title="Browse folder">Browse</button>
                                    <button onClick={startScan} disabled={status.scanning}
                                        className="ml-2 px-4 py-2 disabled:opacity-50 rounded-lg font-medium transition flex items-center gap-2 text-sm" style={{backgroundColor:'var(--success)',color:'var(--bg-deep)'}}>
                                        {status.scanning && <span className="loader"></span>}
                                        Scan
                                    </button>
                                </div>
                                <Dropzone label="Drop ROM folders here" onDrop={paths => { if (paths[0]) setRomFolder(paths[0]); }} />
                                <div className="flex gap-4 mb-3 mt-3 items-center">
                                    <label className="flex items-center gap-2 text-sm cursor-pointer" style={{color:'var(--subtext0)'}}>
                                        <input type="checkbox" checked={scanArchives} onChange={e => setScanArchives(e.target.checked)} className="rounded" />
                                        Scan ZIPs
                                    </label>
                                    <label className="flex items-center gap-2 text-sm cursor-pointer" style={{color:'var(--subtext0)'}}>
                                        <input type="checkbox" checked={recursive} onChange={e => setRecursive(e.target.checked)} className="rounded" />
                                        Recursive
                                    </label>
                                    <input type="text" value={blindmatchSystem} onChange={e => setBlindmatchSystem(e.target.value)}
                                        placeholder="BlindMatch system (optional)" title="BlindMatch system name"
                                        className="px-3 py-1.5 rounded text-sm min-w-[260px]" style={{backgroundColor:'var(--bg-dim)',border:'1px solid var(--surface2)',color:'var(--text)'}} />
                                </div>
                                {status.scanning && (
                                    <div className="space-y-2">
                                        <div className="flex justify-between text-sm">
                                            <span style={{color:'var(--subtext0)'}}>Scanning...</span>
                                            <span style={{color:'var(--primary)'}}>{status.scan_progress?.toLocaleString()} / {status.scan_total?.toLocaleString()}</span>
                                        </div>
                                        <div className="w-full h-2 rounded-full overflow-hidden" style={{backgroundColor:'var(--surface1)'}}>
                                            <div className="h-full transition-all" style={{background:'linear-gradient(to right, var(--primary), var(--secondary))',width: `${progress}%`}}></div>
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* ── Stats Bar ── */}
                        {(status.identified_count > 0 || status.unidentified_count > 0) && (
                            <div className="backdrop-blur rounded-xl p-4" style={{backgroundColor:'var(--surface0)',border:'1px solid var(--surface1)'}}>
                                <div className="flex flex-wrap items-center gap-6 text-sm">
                                    <div><span style={{color:'var(--subtext0)'}}>DATs:</span> <span className="font-bold" style={{color:'var(--primary)'}}>{status.dat_count || 0}</span></div>
                                    <div><span style={{color:'var(--subtext0)'}}>Total Scanned:</span> <span className="font-bold">{((status.identified_count || 0) + (status.unidentified_count || 0)).toLocaleString()}</span></div>
                                    <div className="flex items-center gap-1"><span style={{color:'var(--success)'}}>&#10003;</span><span style={{color:'var(--subtext0)'}}>Identified:</span> <span className="font-bold" style={{color:'var(--success)'}}>{(status.identified_count || 0).toLocaleString()}</span></div>
                                    <div className="flex items-center gap-1"><span style={{color:'var(--warning)'}}>?</span><span style={{color:'var(--subtext0)'}}>Unidentified:</span> <span className="font-bold" style={{color:'var(--warning)'}}>{(status.unidentified_count || 0).toLocaleString()}</span></div>
                                    {comp.total_in_dat > 0 && (
                                        <div className="flex items-center gap-1"><span style={{color:'var(--error)'}}>&#9888;</span><span style={{color:'var(--subtext0)'}}>Missing:</span> <span className="font-bold" style={{color:'var(--error)'}}>{(comp.missing || 0).toLocaleString()}</span><span className="text-xs ml-1" style={{color:'var(--overlay1)'}}>({comp.percentage?.toFixed(1)}% complete)</span></div>
                                    )}
                                </div>
                            </div>
                        )}

                        {/* ── Tabs ── */}
                        <div className="backdrop-blur rounded-xl overflow-hidden" style={{backgroundColor:'var(--surface0)',border:'1px solid var(--surface1)'}}>
                            <div className="flex" style={{borderBottom:'1px solid var(--surface1)'}}>
                                {[
                                    { id: 'identified', label: 'Identified', count: results.identified.length, fg: 'var(--success)', badgeBg: 'rgba(166,227,161,0.15)' },
                                    { id: 'unidentified', label: 'Unidentified', count: results.unidentified.length, fg: 'var(--warning)', badgeBg: 'rgba(249,226,175,0.15)' },
                                    { id: 'missing', label: 'Missing', count: (missing.missing || []).length, fg: 'var(--error)', badgeBg: 'rgba(243,139,168,0.15)' },
                                ].map(tab => (
                                    <button key={tab.id} onClick={() => setActiveTab(tab.id)}
                                        className="flex-1 px-6 py-4 font-medium transition flex items-center justify-center gap-2"
                                        style={{
                                            color: activeTab === tab.id ? tab.fg : 'var(--subtext0)',
                                            backgroundColor: activeTab === tab.id ? 'rgba(69,71,90,0.5)' : 'transparent',
                                            borderBottom: activeTab === tab.id ? `2px solid ${tab.fg}` : '2px solid transparent',
                                        }}>
                                        {tab.label}
                                        <span className="px-2 py-0.5 text-xs rounded" style={{background: tab.badgeBg, color: tab.fg}}>{tab.count.toLocaleString()}</span>
                                    </button>
                                ))}
                            </div>

                            {/* Search + Actions bar */}
                            <div className="p-4 flex flex-wrap gap-4 items-center" style={{borderBottom:'1px solid rgba(69,71,90,0.5)'}}>
                                <div className="flex-1 min-w-[200px]">
                                    <input type="text" placeholder="Search..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
                                        className="w-full px-4 py-2 rounded-lg focus:outline-none text-sm" style={{backgroundColor:'var(--bg-dim)',border:'1px solid var(--surface1)',color:'var(--text)'}} />
                                </div>
                                {activeTab === 'identified' && (
                                    <div className="flex gap-2">
                                        <button onClick={() => setViewMode('list')} className="px-3 py-2 rounded-lg text-sm" style={{backgroundColor: viewMode === 'list' ? 'var(--primary)' : 'var(--surface1)', color: viewMode === 'list' ? 'var(--bg-deep)' : 'var(--text)'}}>List</button>
                                        <button onClick={() => setViewMode('grid')} className="px-3 py-2 rounded-lg text-sm" style={{backgroundColor: viewMode === 'grid' ? 'var(--primary)' : 'var(--surface1)', color: viewMode === 'grid' ? 'var(--bg-deep)' : 'var(--text)'}}>Grid</button>
                                    </div>
                                )}
                                {activeTab === 'unidentified' && (
                                    <button onClick={forceIdentify} disabled={selected.size === 0}
                                        className="px-4 py-2 disabled:opacity-50 rounded-lg font-medium transition text-sm" style={{backgroundColor:'var(--secondary)',color:'var(--bg-deep)'}}>
                                        Force to Identified ({selected.size})
                                    </button>
                                )}
                                {activeTab === 'missing' && (
                                    <div className="flex gap-2">
                                        <button onClick={() => { refreshMissing(); notify('info', 'Missing ROMs refreshed'); }}
                                            className="px-3 py-2 rounded-lg text-sm" style={{backgroundColor:'var(--surface1)'}}>Refresh</button>
                                        <button onClick={() => setShowArchive(true)}
                                            className="px-3 py-2 rounded-lg text-sm" style={{backgroundColor:'var(--secondary)',color:'var(--bg-deep)'}}>Search Archive.org</button>
                                        <button onClick={() => { setDlDest(romFolder || ''); setShowDownloadDialog(true); }}
                                            className="px-3 py-2 rounded-lg text-sm font-medium" style={{backgroundColor:'var(--success)',color:'var(--bg-deep)'}}>Download Missing (removed)</button>
                                    </div>
                                )}
                            </div>

                            {/* Table content */}
                            <div className="max-h-[450px] overflow-auto">
                                {activeTab === 'identified' && status.scanning && (
                                    viewMode === 'grid' ? <SkeletonGrid /> : <SkeletonTable />
                                )}
                                {activeTab === 'identified' && !status.scanning && viewMode === 'grid' && filteredIdentified.length > 0 && (
                                    <div style={{display:'flex',flexWrap:'wrap',gap:'16px',padding:'16px'}}>
                                        {filteredIdentified.map(rom => (
                                            <PosterCard key={rom.id} rom={rom} />
                                        ))}
                                    </div>
                                )}
                                {activeTab === 'identified' && !status.scanning && viewMode === 'list' && filteredIdentified.length > 0 && (
                                    <table className="w-full text-sm">
                                        <thead className="sticky top-0" style={{backgroundColor:'var(--surface0)'}}>
                                            <tr className="text-left" style={{color:'var(--subtext0)'}}>
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
                                        <tbody>
                                            {filteredIdentified.map(rom => (
                                                <tr key={rom.id} style={{borderBottom:'1px solid rgba(69,71,90,0.5)'}}>
                                                    <td className="p-3 max-w-[180px] truncate" style={{color:'var(--subtext1)'}}>{rom.original_file}</td>
                                                    <td className="p-3" style={{color:'var(--secondary)'}}>{rom.rom_name}</td>
                                                    <td className="p-3">{rom.game_name}</td>
                                                    <td className="p-3" style={{color:'var(--subtext0)'}}>{rom.system}</td>
                                                    <td className="p-3"><RegionBadge region={rom.region} /></td>
                                                    <td className="p-3" style={{color:'var(--subtext0)'}}>{rom.size_formatted}</td>
                                                        <td className="p-3">{
                                                            (() => {
                                                                const t = autoDownloadTasks[rom.rom_name];
                                                                if (!t || t.status === 'failed') {
                                                                    return <button onClick={() => startAutoDownload(rom)} className="px-3 py-1 rounded text-xs font-medium" style={{backgroundColor:'var(--secondary)', color:'var(--bg-deep)'}}>Download</button>;
                                                                }
                                                                if (t.status === 'done') {
                                                                    return <span style={{color:'var(--success)', fontSize:'12px'}}>Installed</span>;
                                                                }
                                                                return (
                                                                    <div style={{minWidth:'140px'}}>
                                                                        <div style={{fontSize:'11px', color:'var(--subtext0)'}}>{t.progress || 0}%</div>
                                                                        <div className="w-full h-1.5 rounded-full overflow-hidden" style={{backgroundColor:'var(--surface1)'}}>
                                                                            <div className="h-full" style={{backgroundColor:'var(--secondary)', width:`${t.progress || 0}%`}}></div>
                                                                        </div>
                                                                    </div>
                                                                );
                                                            })()
                                                        }</td>
                                                    <td className="p-3 font-mono text-xs" style={{color:'var(--overlay1)'}}>{rom.crc32}</td>
                                                    <td className="p-3" style={{color:'var(--subtext0)'}}>{rom.status}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                )}

                                {activeTab === 'unidentified' && status.scanning && <SkeletonTable />}
                                {activeTab === 'unidentified' && !status.scanning && filteredUnidentified.length > 0 && (
                                    <table className="w-full text-sm">
                                        <thead className="sticky top-0" style={{backgroundColor:'var(--surface0)'}}>
                                            <tr className="text-left" style={{color:'var(--subtext0)'}}>
                                                <th className="p-3 w-10">
                                                    <input type="checkbox" onChange={e => {
                                                        if (e.target.checked) setSelected(new Set(filteredUnidentified.map(f => f.id)));
                                                        else setSelected(new Set());
                                                    }} className="rounded" />
                                                </th>
                                                <th className="p-3">Filename</th>
                                                <th className="p-3">Path</th>
                                                <th className="p-3">Size</th>
                                                <th className="p-3">CRC32</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {filteredUnidentified.map(file => (
                                                <tr key={file.id} style={{borderBottom:'1px solid rgba(69,71,90,0.5)'}}>
                                                    <td className="p-3">
                                                        <input type="checkbox" checked={selected.has(file.id)}
                                                            onChange={e => {
                                                                const next = new Set(selected);
                                                                e.target.checked ? next.add(file.id) : next.delete(file.id);
                                                                setSelected(next);
                                                            }} className="rounded" />
                                                    </td>
                                                    <td className="p-3 font-mono" style={{color:'var(--warning)'}}>{file.filename}</td>
                                                    <td className="p-3 max-w-[250px] truncate" style={{color:'var(--overlay1)'}}>{file.path}</td>
                                                    <td className="p-3" style={{color:'var(--subtext0)'}}>{file.size_formatted}</td>
                                                    <td className="p-3 font-mono text-xs" style={{color:'var(--overlay1)'}}>{file.crc32}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                )}

                                {activeTab === 'missing' && (
                                    <div>
                                        {/* Completeness stats */}
                                        {comp.total_in_dat > 0 && (
                                            <div className="p-4" style={{backgroundColor:'rgba(17,17,27,0.3)',borderBottom:'1px solid rgba(69,71,90,0.5)'}}>
                                                <div className="flex items-center gap-4 text-sm mb-2">
                                                    <span style={{color:'var(--subtext0)'}}>Completeness:</span>
                                                    <span className="font-bold text-lg">{comp.percentage?.toFixed(1)}%</span>
                                                    <span style={{color:'var(--overlay1)'}}>({comp.found?.toLocaleString()} / {comp.total_in_dat?.toLocaleString()})</span>
                                                </div>
                                                <div className="w-full h-3 rounded-full overflow-hidden" style={{backgroundColor:'var(--surface1)'}}>
                                                    <div className="h-full transition-all" style={{background:'linear-gradient(to right, var(--success), var(--primary))',width: `${comp.percentage || 0}%`}}></div>
                                                </div>
                                            </div>
                                        )}
                                        {filteredMissing.length > 0 && (
                                        <table className="w-full text-sm">
                                            <thead className="sticky top-0" style={{backgroundColor:'var(--surface0)'}}>
                                                <tr className="text-left" style={{color:'var(--subtext0)'}}>
                                                    <th className="p-3">ROM Name</th>
                                                    <th className="p-3">Game</th>
                                                    <th className="p-3">System</th>
                                                    <th className="p-3">Region</th>
                                                    <th className="p-3">Size</th>
                                                    <th className="p-3">Action</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {filteredMissing.map((rom, i) => (
                                                    <tr key={i} style={{borderBottom:'1px solid rgba(69,71,90,0.5)'}}>
                                                        <td className="p-3" style={{color:'var(--error)'}}>{rom.rom_name}</td>
                                                        <td className="p-3">{rom.game_name}</td>
                                                        <td className="p-3" style={{color:'var(--subtext0)'}}>{rom.system}</td>
                                                        <td className="p-3"><RegionBadge region={rom.region} /></td>
                                                        <td className="p-3" style={{color:'var(--subtext0)'}}>{rom.size_formatted}</td>
                                                        <td className="p-3">{
                                                            (() => {
                                                                const t = autoDownloadTasks[rom.rom_name];
                                                                if (!t || t.status === 'failed') {
                                                                    return <button onClick={() => startAutoDownload(rom)} className="px-3 py-1 rounded text-xs font-medium" style={{backgroundColor:'var(--secondary)', color:'var(--bg-deep)'}}>Download</button>;
                                                                }
                                                                if (t.status === 'done') {
                                                                    return <span style={{color:'var(--success)', fontSize:'12px'}}>Installed</span>;
                                                                }
                                                                return (
                                                                    <div style={{minWidth:'140px'}}>
                                                                        <div style={{fontSize:'11px', color:'var(--subtext0)'}}>{t.progress || 0}%</div>
                                                                        <div className="w-full h-1.5 rounded-full overflow-hidden" style={{backgroundColor:'var(--surface1)'}}>
                                                                            <div className="h-full" style={{backgroundColor:'var(--secondary)', width:`${t.progress || 0}%`}}></div>
                                                                        </div>
                                                                    </div>
                                                                );
                                                            })()
                                                        }</td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                        )}
                                    </div>
                                )}

                                {/* Empty states */}
                                {activeTab === 'identified' && !status.scanning && filteredIdentified.length === 0 && (
                                    <EmptyState icon="gamepad" heading="No identified ROMs" subtext="Load a DAT file and scan your ROM folder to identify files." ctaLabel={!status.dat_count ? "Load a DAT first" : null} />
                                )}
                                {activeTab === 'unidentified' && !status.scanning && filteredUnidentified.length === 0 && (
                                    <EmptyState icon="search_off" heading="No unidentified files" subtext={q ? "No results match your search." : "All scanned files were matched, or no scan has been performed yet."} />
                                )}
                                {activeTab === 'missing' && filteredMissing.length === 0 && (
                                    <EmptyState icon="folder_search" heading="No missing ROMs" subtext="Load DATs and scan ROMs to compute missing items." />
                                )}
                            </div>
                        </div>

                        {/* ── Organization ── */}
                        <div className="backdrop-blur rounded-xl p-5" style={{backgroundColor:'var(--surface0)',border:'1px solid var(--surface1)'}}>
                            <h2 className="font-semibold mb-4 flex items-center gap-2">
                                <span style={{color:'var(--warning)'}}>&#9889;</span> Organization
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
                                    <button key={s.id} onClick={() => setStrategy(s.id)} title={`Use strategy: ${s.name}. ${s.desc}.`}
                                        className="p-3 rounded-lg text-left transition"
                                        style={{
                                            backgroundColor: strategy === s.id ? 'rgba(203,166,247,0.1)' : 'rgba(17,17,27,0.3)',
                                            border: strategy === s.id ? '1px solid var(--primary)' : '1px solid var(--surface2)',
                                            color: strategy === s.id ? 'var(--primary)' : 'var(--text)',
                                        }}>
                                        <div className="font-medium text-sm">{s.name}</div>
                                        <div className="text-xs" style={{color:'var(--overlay1)'}}>{s.desc}</div>
                                    </button>
                                ))}
                            </div>
                            <div className="flex flex-wrap gap-4 items-end">
                                <div className="flex-1 min-w-[250px]">
                                    <label className="block text-sm mb-2" style={{color:'var(--subtext0)'}}>Output Folder</label>
                                    <div className="flex gap-2">
                                        <input type="text" value={outputFolder} onChange={e => setOutputFolder(e.target.value)}
                                            placeholder="C:\path\to\output"
                                            className="w-full px-4 py-2 rounded-lg focus:outline-none text-sm" style={{backgroundColor:'var(--bg-dim)',border:'1px solid var(--surface2)',color:'var(--text)'}} />
                                        <button onClick={()=>openBrowser('dir', setOutputFolder)} className="px-3 rounded text-sm" style={{backgroundColor:'var(--secondary)',color:'var(--bg-deep)'}} title="Choose the output folder for organized files">Browse</button>
                                    </div>
                                </div>
                                <div>
                                    <label className="block text-sm mb-2" style={{color:'var(--subtext0)'}}>Action</label>
                                    <div className="flex gap-2">
                                        <button onClick={() => setAction('copy')} title="Copy files to output and keep originals"
                                            className="px-4 py-2 rounded-lg transition text-sm"
                                            style={{
                                                backgroundColor: action === 'copy' ? 'rgba(137,180,250,0.15)' : 'rgba(17,17,27,0.3)',
                                                border: action === 'copy' ? '1px solid var(--secondary)' : '1px solid var(--surface2)',
                                                color: action === 'copy' ? 'var(--secondary)' : 'var(--text)',
                                            }}>Copy</button>
                                        <button onClick={() => setAction('move')} title="Move files to output and remove originals"
                                            className="px-4 py-2 rounded-lg transition text-sm"
                                            style={{
                                                backgroundColor: action === 'move' ? 'rgba(249,226,175,0.15)' : 'rgba(17,17,27,0.3)',
                                                border: action === 'move' ? '1px solid var(--warning)' : '1px solid var(--surface2)',
                                                color: action === 'move' ? 'var(--warning)' : 'var(--text)',
                                            }}>Move</button>
                                    </div>
                                </div>
                                <div className="flex gap-2">
                                    <button onClick={previewOrganize} disabled={results.identified.length === 0} title="Show destination preview before organizing"
                                        className="px-4 py-2 disabled:opacity-50 rounded-lg font-medium transition text-sm" style={{backgroundColor:'var(--surface1)'}}>
                                        Preview
                                    </button>
                                    <button onClick={doOrganize} disabled={results.identified.length === 0} title="Execute organization now"
                                        className="px-6 py-2 disabled:opacity-50 rounded-lg font-medium transition text-sm" style={{background:'linear-gradient(135deg, var(--primary), var(--secondary))',color:'var(--bg-deep)',boxShadow:'0 4px 16px rgba(203,166,247,0.3)'}}>
                                        Organize!
                                    </button>
                                    <button onClick={undoOrganize} title="Undo the most recent organization operation"
                                        className="px-4 py-2 rounded-lg font-medium transition text-sm" style={{backgroundColor:'var(--surface1)'}}>
                                        Undo
                                    </button>
                                </div>
                            </div>
                        </div>

                        <p className="text-center text-sm" style={{color:'var(--overlay1)'}}>
                            R0MM ver 0.30rc &mdash; Supports No-Intro, Redump, TOSEC and any XML-based DAT files
                        </p>
                    </div>
                </div>
            );
        }

        ReactDOM.createRoot(document.getElementById('root')).render(<ToastProvider><App /></ToastProvider>);
    {% endraw %}
    </script>
</body>
</html>
'''


def run_server(host='127.0.0.1', port=5000, debug=False, shutdown_on_idle=False):
    """Run the web server"""
    global _idle_shutdown_started
    apply_runtime_settings(load_settings())
    logger = setup_runtime_monitor()
    monitor_action(f"run_server called: host={host} port={port} debug={debug}", logger=logger)
    print(f"R0MM ver {__version__} - Web Interface")
    print(f"=" * 50)
    print(f"Open in your browser: http://{host}:{port}")
    print(f"Press Ctrl+C to stop")
    print()

    if shutdown_on_idle and not _idle_shutdown_started:
        threading.Thread(target=_idle_shutdown_worker, daemon=True).start()
        _idle_shutdown_started = True

    app.run(host=host, port=port, debug=debug, threaded=True)
