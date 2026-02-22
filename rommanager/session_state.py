"""Persistent session state helpers shared by GUI interfaces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .models import DATInfo, ScannedFile
from .parser import DATParser

SESSION_STATE_PATH = Path.home() / ".rommanager" / "session_state.json"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def build_snapshot(*, dats: List[DATInfo], identified: List[ScannedFile], unidentified: List[ScannedFile], extras: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "version": 1,
        "dats": [d.to_dict() for d in dats],
        "identified": [s.to_dict() for s in identified],
        "unidentified": [s.to_dict() for s in unidentified],
        "extras": extras or {},
    }


def save_snapshot(snapshot: Dict[str, Any], path: Path = SESSION_STATE_PATH) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


def load_snapshot(path: Path = SESSION_STATE_PATH) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def clear_snapshot(path: Path = SESSION_STATE_PATH) -> None:
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


def restore_into_matcher(multi_matcher, snapshot: Dict[str, Any]) -> None:
    parser = DATParser()
    for dat_raw in snapshot.get("dats", []):
        dat_info = DATInfo.from_dict(dat_raw)
        if not dat_info.filepath:
            continue
        try:
            loaded_info, roms = parser.parse(dat_info.filepath)
            # preserve id from prior state when possible
            loaded_info.id = dat_info.id or loaded_info.id
            multi_matcher.add_dat(loaded_info, roms)
        except Exception:
            continue


def restore_scanned(snapshot: Dict[str, Any]) -> tuple[List[ScannedFile], List[ScannedFile]]:
    identified = [ScannedFile.from_dict(s) for s in snapshot.get("identified", [])]
    unidentified = [ScannedFile.from_dict(s) for s in snapshot.get("unidentified", [])]
    return identified, unidentified
