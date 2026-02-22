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


_TAG_BLOCK_RE = re.compile(r"\s*[\(\[][^[\]()\[\]]+[\)\]]")


def clean_game_name(filename: str) -> str:
    """Best-effort cleanup of scene-like tags from filename stem."""
    name = os.path.splitext(filename)[0]
    # remove common (...) and [...] tag blocks repeatedly
    prev = None
    while prev != name:
        prev = name
        name = _TAG_BLOCK_RE.sub("", name).strip()

    # normalize separators/spaces
    name = re.sub(r"[_\.]+", " ", name)
    name = re.sub(r"\s{2,}", " ", name).strip(" -_	")
    return name or os.path.splitext(filename)[0]


def infer_region(filename: str) -> str:
    name = filename.upper()
    for pat, region in _REGION_PATTERNS:
        if re.search(pat, name, flags=re.IGNORECASE):
            return region
    return "Unknown"


def build_blindmatch_rom(scanned: ScannedFile, system_name: str) -> ROMInfo:
    base = clean_game_name(scanned.filename)
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
