"""
Collection persistence - save/load sessions with DATs, scan results, and settings.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

from .models import Collection, DATInfo, ScannedFile
from .shared_config import COLLECTIONS_DIR, RECENT_FILE, APP_DATA_DIR
from .monitor import monitor


class CollectionManager:
    """Manages saving, loading, and listing ROM collections."""

    def __init__(self):
        os.makedirs(COLLECTIONS_DIR, exist_ok=True)
        os.makedirs(APP_DATA_DIR, exist_ok=True)

    def save(self, collection: Collection, filepath: Optional[str] = None) -> str:
        """Save collection to JSON. Returns filepath."""
        if not filepath:
            safe_name = "".join(c if c.isalnum() or c in ' _-' else '_'
                               for c in collection.name).strip()
            filepath = os.path.join(COLLECTIONS_DIR, f"{safe_name}.romcol.json")

        collection.updated_at = datetime.now().isoformat()
        if not collection.created_at:
            collection.created_at = collection.updated_at

        data = collection.to_dict()
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self.add_to_recent(filepath, collection.name)
        monitor.info('collection', f'Collection saved: {filepath}')
        return filepath

    def load(self, filepath: str) -> Collection:
        """Load collection from JSON."""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        collection = Collection.from_dict(data)
        self.add_to_recent(filepath, collection.name)
        monitor.info('collection', f'Collection loaded: {filepath}')
        return collection

    def list_saved(self) -> List[Dict]:
        """List all saved collections with metadata."""
        collections = []
        if not os.path.isdir(COLLECTIONS_DIR):
            return collections

        for filename in os.listdir(COLLECTIONS_DIR):
            if filename.endswith('.romcol.json'):
                filepath = os.path.join(COLLECTIONS_DIR, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    collections.append({
                        'name': data.get('name', filename),
                        'filepath': filepath,
                        'created_at': data.get('created_at', ''),
                        'updated_at': data.get('updated_at', ''),
                        'dat_count': len(data.get('dat_infos', [])),
                        'identified_count': len(data.get('identified', [])),
                        'unidentified_count': len(data.get('unidentified', [])),
                    })
                except Exception as e:
                    monitor.error('collection', f'Failed reading collection metadata {filepath}: {e}')

        collections.sort(key=lambda x: x.get('updated_at', ''), reverse=True)
        return collections

    def delete(self, filepath: str) -> bool:
        """Delete a saved collection."""
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                return True
        except Exception as e:
            monitor.error('collection', f'Failed deleting collection {filepath}: {e}')
        return False

    def get_recent(self, limit: int = 10) -> List[Dict]:
        """Get recently opened collections."""
        if not os.path.exists(RECENT_FILE):
            return []
        try:
            with open(RECENT_FILE, 'r', encoding='utf-8') as f:
                recent = json.load(f)
            # Filter out entries where the file no longer exists
            recent = [r for r in recent if os.path.exists(r.get('filepath', ''))]
            return recent[:limit]
        except Exception as e:
            monitor.error('collection', f'Failed reading recent collections: {e}')
            return []

    def add_to_recent(self, filepath: str, name: str) -> None:
        """Track a recently opened collection."""
        recent = self.get_recent(limit=50)
        # Remove existing entry with same path
        recent = [r for r in recent if r.get('filepath') != filepath]
        # Add new entry at top
        recent.insert(0, {
            'name': name,
            'filepath': filepath,
            'accessed_at': datetime.now().isoformat(),
        })
        # Keep only last 20
        recent = recent[:20]

        os.makedirs(os.path.dirname(RECENT_FILE), exist_ok=True)
        with open(RECENT_FILE, 'w', encoding='utf-8') as f:
            json.dump(recent, f, indent=2, ensure_ascii=False)
