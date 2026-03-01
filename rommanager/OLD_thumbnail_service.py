"""
Libretro Thumbnails integration — async box art downloader with local cache.

Usage:
    from rommanager.thumbnail_service import ThumbnailService
    from rommanager.shared_config import THUMBNAILS_DIR

    ts = ThumbnailService(THUMBNAILS_DIR)
    path = ts.get_thumbnail_path("Nintendo - Game Boy Advance", "Metroid Fusion")
    # Returns cached path or None
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─── System Name Mapping ─────────────────────────────────────────────────────
LIBRETRO_SYSTEM_MAP: Dict[str, str] = {
    # Nintendo
    "Nintendo - Nintendo Entertainment System": "Nintendo_-_Nintendo_Entertainment_System",
    "Nintendo - Super Nintendo Entertainment System": "Nintendo_-_Super_Nintendo_Entertainment_System",
    "Nintendo - Game Boy": "Nintendo_-_Game_Boy",
    "Nintendo - Game Boy Color": "Nintendo_-_Game_Boy_Color",
    "Nintendo - Game Boy Advance": "Nintendo_-_Game_Boy_Advance",
    "Nintendo - Nintendo 64": "Nintendo_-_Nintendo_64",
    "Nintendo - Nintendo DS": "Nintendo_-_Nintendo_DS",
    "Nintendo - Virtual Boy": "Nintendo_-_Virtual_Boy",
    # Sega
    "Sega - Master System - Mark III": "Sega_-_Master_System_-_Mark_III",
    "Sega - Mega Drive - Genesis": "Sega_-_Mega_Drive_-_Genesis",
    "Sega - Game Gear": "Sega_-_Game_Gear",
    "Sega - Saturn": "Sega_-_Saturn",
    "Sega - Dreamcast": "Sega_-_Dreamcast",
    "Sega - 32X": "Sega_-_32X",
    "Sega - Mega-CD - Sega CD": "Sega_-_Mega-CD_-_Sega_CD",
    # Sony
    "Sony - PlayStation": "Sony_-_PlayStation",
    "Sony - PlayStation 2": "Sony_-_PlayStation_2",
    "Sony - PlayStation Portable": "Sony_-_PlayStation_Portable",
    # Atari
    "Atari - 2600": "Atari_-_2600",
    "Atari - 7800": "Atari_-_7800",
    "Atari - Lynx": "Atari_-_Lynx",
    "Atari - Jaguar": "Atari_-_Jaguar",
    # NEC
    "NEC - PC Engine - TurboGrafx-16": "NEC_-_PC_Engine_-_TurboGrafx-16",
    "NEC - PC Engine CD - TurboGrafx-CD": "NEC_-_PC_Engine_CD_-_TurboGrafx-CD",
    # SNK
    "SNK - Neo Geo Pocket": "SNK_-_Neo_Geo_Pocket",
    "SNK - Neo Geo Pocket Color": "SNK_-_Neo_Geo_Pocket_Color",
    # Bandai
    "Bandai - WonderSwan": "Bandai_-_WonderSwan",
    "Bandai - WonderSwan Color": "Bandai_-_WonderSwan_Color",
    # GCE
    "GCE - Vectrex": "GCE_-_Vectrex",
    # Coleco
    "Coleco - ColecoVision": "Coleco_-_ColecoVision",
    # Magnavox
    "Magnavox - Odyssey2": "Magnavox_-_Odyssey2",
    # Mattel
    "Mattel - Intellivision": "Mattel_-_Intellivision",
    # 3DO
    "The 3DO Company - 3DO": "The_3DO_Company_-_3DO",
    # Arcade
    "MAME": "MAME",
    "FBNeo - Arcade Games": "FBNeo_-_Arcade_Games",
}

_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')
_NOT_FOUND_EXPIRY = 7 * 24 * 3600  # 7 days
_BASE_URL = "https://raw.githubusercontent.com/libretro-thumbnails"


def _sanitize_game_name(name: str) -> str:
    """Sanitize game name for use in Libretro Thumbnails URL and file path."""
    sanitized = _UNSAFE_CHARS.sub("_", name)
    sanitized = sanitized.replace("&", "_")
    return sanitized.strip().rstrip(".")


def _system_folder(system: str) -> Optional[str]:
    """Map DAT system name to Libretro folder name. Returns None if unknown."""
    if system in LIBRETRO_SYSTEM_MAP:
        return LIBRETRO_SYSTEM_MAP[system]
    auto = system.replace(" ", "_")
    return auto


class ThumbnailService:
    """Async Libretro Thumbnails downloader with local file cache."""

    def __init__(self, cache_dir: str):
        self._cache_dir = cache_dir
        self._not_found_path = os.path.join(cache_dir, ".not_found.json")
        self._not_found: Dict[str, float] = {}
        self._load_not_found()
        os.makedirs(cache_dir, exist_ok=True)

    def get_thumbnail_path(self, system: str, game_name: str) -> Optional[str]:
        """Return local cached path if thumbnail exists, else None. Non-blocking."""
        folder = _system_folder(system)
        if not folder:
            return None
        safe_name = _sanitize_game_name(game_name)
        path = os.path.join(self._cache_dir, folder, f"{safe_name}.png")
        return path if os.path.isfile(path) else None

    def get_placeholder_data(self, game_name: str, system: str) -> dict:
        """Return data for rendering a placeholder card."""
        initial = game_name[0].upper() if game_name else "?"
        colors = ["#cba6f7", "#89b4fa", "#a6e3a1", "#f9e2af",
                  "#f38ba8", "#fab387", "#94e2d5", "#89dceb"]
        idx = int(hashlib.md5(game_name.encode()).hexdigest()[:2], 16) % len(colors)
        short_system = system.split(" - ")[-1] if " - " in system else system
        return {"initial": initial, "color": colors[idx], "system_short": short_system}

    async def fetch_thumbnail(self, system: str, game_name: str) -> Optional[str]:
        """Download thumbnail if not cached. Returns local path or None."""
        existing = self.get_thumbnail_path(system, game_name)
        if existing:
            return existing

        cache_key = f"{system}|{game_name}"
        if cache_key in self._not_found:
            if time.time() - self._not_found[cache_key] < _NOT_FOUND_EXPIRY:
                return None
            del self._not_found[cache_key]

        folder = _system_folder(system)
        if not folder:
            return None
        safe_name = _sanitize_game_name(game_name)
        url = f"{_BASE_URL}/{folder}/master/Named_Boxarts/{safe_name}.png"

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        dest_dir = os.path.join(self._cache_dir, folder)
                        os.makedirs(dest_dir, exist_ok=True)
                        dest_path = os.path.join(dest_dir, f"{safe_name}.png")
                        data = await resp.read()
                        with open(dest_path, "wb") as f:
                            f.write(data)
                        logger.debug("Thumbnail cached: %s", dest_path)
                        return dest_path
                    else:
                        self._not_found[cache_key] = time.time()
                        self._save_not_found()
                        return None
        except Exception as exc:
            logger.warning("Thumbnail fetch failed for %s/%s: %s", system, game_name, exc)
            return None

    async def fetch_batch(
        self,
        items: List[Tuple[str, str]],
        on_progress: Optional[Callable[[int, int], None]] = None,
        max_concurrent: int = 5,
    ) -> Dict[Tuple[str, str], Optional[str]]:
        """Batch-download thumbnails with limited concurrency."""
        sem = asyncio.Semaphore(max_concurrent)
        results: Dict[Tuple[str, str], Optional[str]] = {}
        completed = 0
        total = len(items)

        async def _fetch_one(system: str, game_name: str):
            nonlocal completed
            async with sem:
                path = await self.fetch_thumbnail(system, game_name)
                results[(system, game_name)] = path
                completed += 1
                if on_progress:
                    on_progress(completed, total)

        tasks = [_fetch_one(sys, gn) for sys, gn in items]
        await asyncio.gather(*tasks, return_exceptions=True)
        return results

    def fetch_batch_sync(
        self,
        items: List[Tuple[str, str]],
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[Tuple[str, str], Optional[str]]:
        """Synchronous wrapper — runs fetch_batch in a background thread."""
        result = {}

        def _run():
            nonlocal result
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    self.fetch_batch(items, on_progress=on_progress)
                )
            finally:
                loop.close()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join()
        return result

    def _load_not_found(self):
        if os.path.isfile(self._not_found_path):
            try:
                with open(self._not_found_path, "r") as f:
                    data = json.load(f)
                now = time.time()
                self._not_found = {
                    k: v for k, v in data.items()
                    if now - v < _NOT_FOUND_EXPIRY
                }
            except Exception:
                self._not_found = {}

    def _save_not_found(self):
        try:
            with open(self._not_found_path, "w") as f:
                json.dump(self._not_found, f)
        except Exception:
            pass
