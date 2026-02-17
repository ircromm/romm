"""
DAT file library - manage a local collection of DAT files.
"""

import json
import os
import shutil
from datetime import datetime
from typing import Dict, List, Optional

from .models import DATInfo
from .parser import DATParser
from .shared_config import DATS_DIR, DAT_INDEX_FILE, APP_DATA_DIR
from .monitor import monitor


class DATLibrary:
    """Manages a local library of DAT files."""

    def __init__(self):
        os.makedirs(DATS_DIR, exist_ok=True)
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        self._index = self._load_index()

    def _load_index(self) -> Dict[str, Dict]:
        """Load the DAT index from disk."""
        if os.path.exists(DAT_INDEX_FILE):
            try:
                with open(DAT_INDEX_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                monitor.error('dat_library', f'Failed loading DAT index {DAT_INDEX_FILE}: {e}')
        return {}

    def _save_index(self):
        """Save the DAT index to disk."""
        with open(DAT_INDEX_FILE, 'w', encoding='utf-8') as f:
            json.dump(self._index, f, indent=2, ensure_ascii=False)

    def import_dat(self, filepath: str) -> DATInfo:
        """Copy a DAT into the library and index it."""
        dat_info, _ = DATParser.parse_with_info(filepath)

        # Create system subfolder
        safe_system = "".join(c if c.isalnum() or c in ' _-.' else '_'
                             for c in dat_info.system_name).strip()
        dest_dir = os.path.join(DATS_DIR, safe_system)
        os.makedirs(dest_dir, exist_ok=True)

        dest_path = os.path.join(dest_dir, os.path.basename(filepath))
        if os.path.abspath(filepath) != os.path.abspath(dest_path):
            shutil.copy2(filepath, dest_path)

        dat_info.filepath = dest_path

        # Index it
        self._index[dat_info.id] = {
            'id': dat_info.id,
            'filepath': dest_path,
            'name': dat_info.name,
            'description': dat_info.description,
            'version': dat_info.version,
            'system_name': dat_info.system_name,
            'rom_count': dat_info.rom_count,
            'imported_at': datetime.now().isoformat(),
        }
        self._save_index()
        monitor.info('dat_library', f'Imported DAT into library: {dest_path}')

        return dat_info

    def list_dats(self) -> List[DATInfo]:
        """List all DATs in the library."""
        result = []
        for entry in self._index.values():
            if os.path.exists(entry.get('filepath', '')):
                result.append(DATInfo(
                    id=entry['id'],
                    filepath=entry['filepath'],
                    name=entry.get('name', ''),
                    description=entry.get('description', ''),
                    version=entry.get('version', ''),
                    system_name=entry.get('system_name', ''),
                    rom_count=entry.get('rom_count', 0),
                    loaded_at=entry.get('imported_at', ''),
                ))
        return sorted(result, key=lambda d: d.system_name)

    def remove_dat(self, dat_id: str) -> bool:
        """Remove a DAT from the library."""
        entry = self._index.pop(dat_id, None)
        if entry:
            filepath = entry.get('filepath', '')
            if filepath and os.path.exists(filepath):
                try:
                    os.remove(filepath)
                    # Remove empty parent dir
                    parent = os.path.dirname(filepath)
                    if parent and os.path.isdir(parent) and not os.listdir(parent):
                        os.rmdir(parent)
                except Exception as e:
                    monitor.error('dat_library', f'Failed removing DAT file {filepath}: {e}')
            self._save_index()
            return True
        return False

    def get_dat_path(self, dat_id: str) -> Optional[str]:
        """Get the library path for a DAT."""
        entry = self._index.get(dat_id)
        if entry:
            path = entry.get('filepath', '')
            if os.path.exists(path):
                return path
        return None

    def get_dat_info(self, dat_id: str) -> Optional[DATInfo]:
        """Get DATInfo for a library DAT."""
        entry = self._index.get(dat_id)
        if entry:
            return DATInfo(
                id=entry['id'],
                filepath=entry.get('filepath', ''),
                name=entry.get('name', ''),
                description=entry.get('description', ''),
                version=entry.get('version', ''),
                system_name=entry.get('system_name', ''),
                rom_count=entry.get('rom_count', 0),
                loaded_at=entry.get('imported_at', ''),
            )
        return None
