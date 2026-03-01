"""
DAT file library - manage a local collection of DAT files.
"""

import json
import os
import shutil
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .models import DATInfo
from .parser import DATParser
from .shared_config import DATS_DIR, DAT_INDEX_FILE, APP_DATA_DIR


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
            except Exception:
                pass
        return {}

    def _save_index(self):
        """Save the DAT index to disk."""
        with open(DAT_INDEX_FILE, 'w', encoding='utf-8') as f:
            json.dump(self._index, f, indent=2, ensure_ascii=False)

    @staticmethod
    def _normalize_path(path: str) -> str:
        return os.path.normcase(os.path.normpath(str(path or "")))

    @staticmethod
    def _is_supported_dat_file(path: Path) -> bool:
        return path.suffix.lower() in {".dat", ".xml", ".zip", ".gz"}

    def _stable_id_for_path(self, filepath: str) -> str:
        digest = hashlib.sha1(self._normalize_path(filepath).encode("utf-8", errors="ignore")).hexdigest()[:12]
        return f"fs_{digest}"

    def _find_id_by_path(self, filepath: str) -> Optional[str]:
        needle = self._normalize_path(filepath)
        for dat_id, entry in self._index.items():
            if self._normalize_path(entry.get("filepath", "")) == needle:
                return str(dat_id)
        return None

    def _find_id_by_identity(self, name: str, version: str, rom_count: int) -> Optional[str]:
        target_name = str(name or "").strip().lower()
        target_version = str(version or "").strip().lower()
        try:
            target_count = int(rom_count or 0)
        except Exception:
            target_count = 0
        for dat_id, entry in self._index.items():
            filepath = str(entry.get("filepath", "") or "").strip()
            if not filepath or not Path(filepath).exists():
                continue
            row_name = str(entry.get("name", "") or "").strip().lower()
            row_version = str(entry.get("version", "") or "").strip().lower()
            try:
                row_count = int(entry.get("rom_count", 0) or 0)
            except Exception:
                row_count = 0
            if row_name == target_name and row_version == target_version and row_count == target_count:
                return str(dat_id)
        return None

    def _refresh_index_from_disk(self) -> None:
        """Ensure every DAT-like file inside DATS_DIR (recursive) is indexed."""
        changed = False
        dat_root = Path(DATS_DIR)
        dat_root.mkdir(parents=True, exist_ok=True)

        # Drop entries for files that no longer exist and backfill validity metadata.
        stale_ids: List[str] = []
        for dat_id, entry in list(self._index.items()):
            filepath = str(entry.get("filepath", "") or "").strip()
            if not filepath or not Path(filepath).exists():
                stale_ids.append(str(dat_id))
                continue
            needs_revalidate = (
                "is_valid" not in entry
                or "parse_error" not in entry
                or not bool(entry.get("is_valid", True))
                or bool(str(entry.get("parse_error", "") or "").strip())
            )
            if needs_revalidate:
                try:
                    header, roms = DATParser.parse(filepath)
                    entry["name"] = str(entry.get("name") or header.get("name") or header.get("description") or Path(filepath).stem)
                    entry["description"] = str(entry.get("description") or header.get("description", "") or "")
                    entry["version"] = str(entry.get("version") or header.get("version", "") or "")
                    entry["system_name"] = str(entry.get("system_name") or entry.get("name") or Path(filepath).stem)
                    entry["rom_count"] = len(roms)
                    entry["is_valid"] = True
                    entry["parse_error"] = ""
                except Exception as exc:
                    entry["is_valid"] = False
                    entry["parse_error"] = str(exc)
                changed = True
        for dat_id in stale_ids:
            self._index.pop(dat_id, None)
            changed = True

        # Build a path->id map from current entries.
        by_path: Dict[str, str] = {}
        for dat_id, entry in self._index.items():
            filepath = str(entry.get("filepath", "") or "").strip()
            if not filepath:
                continue
            by_path[self._normalize_path(filepath)] = str(dat_id)

        # Discover DAT files recursively.
        for path in dat_root.rglob("*"):
            if not path.is_file() or not self._is_supported_dat_file(path):
                continue
            full_path = str(path)
            norm = self._normalize_path(full_path)
            if norm in by_path:
                continue

            try:
                header, roms = DATParser.parse(full_path)
                name = str(header.get("name") or header.get("description") or path.stem)
                description = str(header.get("description", "") or "")
                version = str(header.get("version", "") or "")
                parse_error = ""
                is_valid = True
            except Exception as exc:
                # Keep entry visible even when parsing fails.
                name = path.stem
                description = ""
                version = ""
                roms = []
                parse_error = str(exc) or "Invalid DAT structure"
                is_valid = False

            dat_id = self._stable_id_for_path(full_path)
            while dat_id in self._index:
                dat_id = f"{dat_id}_x"
            self._index[dat_id] = {
                "id": dat_id,
                "filepath": full_path,
                "name": name,
                "description": description,
                "version": version,
                "system_name": name,
                "rom_count": len(roms),
                "imported_at": datetime.now().isoformat(),
                "is_valid": is_valid,
                "parse_error": parse_error,
            }
            by_path[norm] = dat_id
            changed = True

        if changed:
            self._save_index()

    def import_dat(self, filepath: str) -> DATInfo:
        """Copy a DAT into the library and index it."""
        dat_info, _ = DATParser.parse_with_info(filepath)
        source_path = Path(filepath).resolve()
        dat_root = Path(DATS_DIR).resolve()

        existing_identity_id = self._find_id_by_identity(
            dat_info.name,
            dat_info.version,
            dat_info.rom_count,
        )
        if existing_identity_id:
            existing = self._index.get(existing_identity_id, {})
            existing_path = str(existing.get("filepath", "") or "").strip()
            if existing_path and Path(existing_path).exists():
                dat_info.id = existing_identity_id
                dat_info.filepath = existing_path
                self._index[dat_info.id] = {
                    'id': dat_info.id,
                    'filepath': existing_path,
                    'name': dat_info.name,
                    'description': dat_info.description,
                    'version': dat_info.version,
                    'system_name': dat_info.system_name,
                    'rom_count': dat_info.rom_count,
                    'imported_at': datetime.now().isoformat(),
                    'is_valid': True,
                    'parse_error': "",
                }
                self._save_index()
                return dat_info

        # If DAT is already under the managed DAT root, keep that path and avoid copy-induced duplicates.
        inside_dat_root = False
        try:
            source_path.relative_to(dat_root)
            inside_dat_root = True
        except Exception:
            inside_dat_root = False

        if inside_dat_root:
            dest_path = str(source_path)
        else:
            # Create system subfolder for external imports
            safe_system = "".join(c if c.isalnum() or c in ' _-.' else '_'
                                 for c in dat_info.system_name).strip()
            dest_dir = os.path.join(DATS_DIR, safe_system)
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, os.path.basename(filepath))
            if os.path.abspath(filepath) != os.path.abspath(dest_path):
                shutil.copy2(filepath, dest_path)

        dat_info.filepath = dest_path
        existing_id = self._find_id_by_path(dest_path)
        if existing_id:
            dat_info.id = existing_id

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
            'is_valid': True,
            'parse_error': "",
        }
        # Remove duplicated entries that point to the same file path.
        norm_dest = self._normalize_path(dest_path)
        duplicates = [
            dat_id
            for dat_id, entry in self._index.items()
            if str(dat_id) != str(dat_info.id)
            and self._normalize_path(entry.get("filepath", "")) == norm_dest
        ]
        for dat_id in duplicates:
            self._index.pop(dat_id, None)
        self._save_index()

        return dat_info

    def list_dats(self) -> List[DATInfo]:
        """List all DATs in the library."""
        self._refresh_index_from_disk()
        result = []
        seen_paths = set()
        for entry in self._index.values():
            filepath = entry.get('filepath', '')
            norm = self._normalize_path(filepath)
            if not os.path.exists(filepath) or norm in seen_paths:
                continue
            seen_paths.add(norm)
            result.append(DATInfo(
                id=entry['id'],
                filepath=filepath,
                name=entry.get('name', ''),
                description=entry.get('description', ''),
                version=entry.get('version', ''),
                system_name=entry.get('system_name', ''),
                rom_count=entry.get('rom_count', 0),
                loaded_at=entry.get('imported_at', ''),
                is_valid=bool(entry.get('is_valid', True)),
                parse_error=str(entry.get('parse_error', '') or ''),
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
                except Exception:
                    pass
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
                is_valid=bool(entry.get('is_valid', True)),
                parse_error=str(entry.get('parse_error', '') or ''),
            )
        return None
