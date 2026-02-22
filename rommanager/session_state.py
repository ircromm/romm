"""Persistent runtime session snapshot shared by all interfaces."""
from __future__ import annotations

import json
import os
from typing import Dict, Any, List

from .models import DATInfo, ScannedFile

SESSION_PATH = os.path.expanduser("~/.rommanager/session.json")


def save_session(dat_infos: List[DATInfo], identified: List[ScannedFile], unidentified: List[ScannedFile], ui: Dict[str, Any] | None = None) -> None:
    data = {
        "dat_infos": [d.to_dict() for d in dat_infos],
        "identified": [f.to_dict() for f in identified],
        "unidentified": [f.to_dict() for f in unidentified],
        "ui": ui or {},
    }
    os.makedirs(os.path.dirname(SESSION_PATH), exist_ok=True)
    with open(SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_session() -> Dict[str, Any]:
    if not os.path.exists(SESSION_PATH):
        return {}
    try:
        with open(SESSION_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def clear_session() -> None:
    if os.path.exists(SESSION_PATH):
        os.remove(SESSION_PATH)


def restore_files(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "dat_infos": [DATInfo.from_dict(d) for d in data.get("dat_infos", [])],
        "identified": [ScannedFile.from_dict(d) for d in data.get("identified", [])],
        "unidentified": [ScannedFile.from_dict(d) for d in data.get("unidentified", [])],
        "ui": data.get("ui", {}),
    }
