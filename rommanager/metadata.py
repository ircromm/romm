"""Optional curated metadata layer for ROMs."""
from __future__ import annotations

import json
import os
from typing import Dict, Any


class MetadataStore:
    def __init__(self, path: str = ""):
        self.path = path
        self.data: Dict[str, Any] = {}
        if path:
            self.load(path)

    def load(self, path: str):
        self.path = path
        if not path or not os.path.exists(path):
            self.data = {}
            return
        with open(path, 'r', encoding='utf-8') as f:
            self.data = json.load(f)

    def lookup(self, crc32: str = "", game_name: str = "") -> Dict[str, Any]:
        if crc32 and crc32 in self.data.get('by_crc32', {}):
            return self.data['by_crc32'][crc32]
        if game_name and game_name in self.data.get('by_game', {}):
            return self.data['by_game'][game_name]
        return {}
