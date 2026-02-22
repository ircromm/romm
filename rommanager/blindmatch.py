"""Best-effort blind matching without DAT files."""

from __future__ import annotations

import os
import re
from .models import ROMInfo, ScannedFile

_REGION_PATTERNS = [
    (r"\((U|USA|US)\)", "USA"),
    (r"\b(USA|US)\b", "USA"),
    (r"\((E|EUR|EUROPE)\)", "Europe"),
    (r"\b(EUR|EUROPE|EU)\b", "Europe"),
    (r"\((J|JPN|JAPAN)\)", "Japan"),
    (r"\b(JPN|JAPAN|JP)\b", "Japan"),
    (r"\((BR|BRAZIL)\)", "Brazil"),
    (r"\b(BR|BRAZIL)\b", "Brazil"),
    (r"\((K|KOR|KOREA)\)", "Korea"),
    (r"\b(KOR|KOREA|KR)\b", "Korea"),
    (r"\((W|WORLD)\)", "World"),
    (r"\b(WORLD)\b", "World"),
]


def infer_region(filename: str) -> str:
    name = filename.upper()
    for pat, region in _REGION_PATTERNS:
        if re.search(pat, name, flags=re.IGNORECASE):
            return region
    return "Unknown"


def build_blindmatch_rom(scanned: ScannedFile, system_name: str) -> ROMInfo:
    base = os.path.splitext(scanned.filename)[0]
    region = infer_region(scanned.filename)
    return ROMInfo(
        name=scanned.filename,
        game_name=base,
        size=scanned.size,
        crc32=scanned.crc32,
        region=region,
        system_name=system_name.strip() if system_name else "Unknown System",
        status="BlindMatch",
    )
