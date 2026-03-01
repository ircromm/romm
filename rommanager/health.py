"""Collection health checks (integrity/risk)."""
from __future__ import annotations

import os
from collections import defaultdict
from typing import Dict, List

from .models import ScannedFile

KNOWN_EXT = {'.zip', '.7z', '.rar', '.nes', '.sfc', '.smc', '.gb', '.gbc', '.gba', '.bin', '.iso', '.chd', '.md', '.cue'}


def run_health_checks(files: List[ScannedFile], warn_on_unknown_ext: bool = True, warn_on_duplicates: bool = True) -> Dict[str, List[str]]:
    issues: Dict[str, List[str]] = {
        "duplicate_crc": [],
        "unknown_extension": [],
        "missing_file": [],
        "zero_size": [],
    }
    by_crc = defaultdict(list)
    for f in files:
        if not os.path.exists(f.path.split('|')[0]):
            issues["missing_file"].append(f.path)
        if f.size == 0:
            issues["zero_size"].append(f.path)
        if warn_on_unknown_ext:
            ext = os.path.splitext(f.filename)[1].lower()
            if ext and ext not in KNOWN_EXT:
                issues["unknown_extension"].append(f.filename)
        if warn_on_duplicates and f.crc32:
            by_crc[f.crc32].append(f.filename)

    if warn_on_duplicates:
        for crc, names in by_crc.items():
            if len(names) > 1:
                issues["duplicate_crc"].append(f"{crc}: {', '.join(sorted(set(names)))}")

    return {k: v for k, v in issues.items() if v}
