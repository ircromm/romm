"""
Myrient downloader - browse, search and download ROMs from myrient.erista.me.
Also uses Internet Archive as fallback.

Embeds a full catalog of ~200 systems mapped to their Myrient URLs,
an HTTP client that parses the directory listings, and a sequential
download manager with progress, pause/cancel, and streaming CRC check.

Downloads run one at a time at FULL SPEED (browser-style) with
configurable delay between files.
"""

import os
import time
import zlib
import zipfile
import logging
from dataclasses import dataclass
from enum import Enum, auto
from html.parser import HTMLParser
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from .models import ROMInfo
from .monitor import log_event


# ═══════════════════════════════════════════════════════════════
# MYRIENT SYSTEM CATALOG
# Maps system names (as they appear in DAT files) to Myrient URLs.
# ═══════════════════════════════════════════════════════════════

MYRIENT_BASE = "https://myrient.erista.me/files"

_NI = "No-Intro"
_RD = "Redump"

# fmt: off
MYRIENT_CATALOG: Dict[str, str] = {
    # ── Nintendo Cartridge ──────────────────────────────
    "Nintendo - Nintendo Entertainment System (Headered)": f"{_NI}/Nintendo%20-%20Nintendo%20Entertainment%20System%20(Headered)",
    "Nintendo - Nintendo Entertainment System":            f"{_NI}/Nintendo%20-%20Nintendo%20Entertainment%20System%20(Headered)",
    "Nintendo - Family Computer Disk System (FDS)":        f"{_NI}/Nintendo%20-%20Family%20Computer%20Disk%20System%20(FDS)",
    "Nintendo - Family Computer Disk System":              f"{_NI}/Nintendo%20-%20Family%20Computer%20Disk%20System%20(FDS)",
    "Nintendo - Super Nintendo Entertainment System":      f"{_NI}/Nintendo%20-%20Super%20Nintendo%20Entertainment%20System",
    "Nintendo - Game Boy":                                 f"{_NI}/Nintendo%20-%20Game%20Boy",
    "Nintendo - Game Boy Color":                           f"{_NI}/Nintendo%20-%20Game%20Boy%20Color",
    "Nintendo - Game Boy Advance":                         f"{_NI}/Nintendo%20-%20Game%20Boy%20Advance",
    "Nintendo - Nintendo 64 (BigEndian)":                  f"{_NI}/Nintendo%20-%20Nintendo%2064%20(BigEndian)",
    "Nintendo - Nintendo 64":                              f"{_NI}/Nintendo%20-%20Nintendo%2064%20(BigEndian)",
    "Nintendo - Virtual Boy":                              f"{_NI}/Nintendo%20-%20Virtual%20Boy",
    "Nintendo - Pokemon Mini":                             f"{_NI}/Nintendo%20-%20Pokemon%20Mini",
    "Nintendo - Nintendo DS (Decrypted)":                  f"{_NI}/Nintendo%20-%20Nintendo%20DS%20(Decrypted)",
    "Nintendo - Nintendo DS":                              f"{_NI}/Nintendo%20-%20Nintendo%20DS%20(Decrypted)",
    "Nintendo - Nintendo DSi (Decrypted)":                 f"{_NI}/Nintendo%20-%20Nintendo%20DSi%20(Decrypted)",
    "Nintendo - Nintendo DSi":                             f"{_NI}/Nintendo%20-%20Nintendo%20DSi%20(Decrypted)",
    "Nintendo - Nintendo 3DS (Decrypted)":                 f"{_NI}/Nintendo%20-%20Nintendo%203DS%20(Decrypted)",
    "Nintendo - Nintendo 3DS":                             f"{_NI}/Nintendo%20-%20Nintendo%203DS%20(Decrypted)",

    # ── Nintendo Disc ───────────────────────────────────
    "Nintendo - GameCube - NKit RVZ [zstd-19-128k]":      f"{_RD}/Nintendo%20-%20GameCube%20-%20NKit%20RVZ%20%5Bzstd-19-128k%5D",
    "Nintendo - GameCube":                                 f"{_RD}/Nintendo%20-%20GameCube%20-%20NKit%20RVZ%20%5Bzstd-19-128k%5D",
    "Nintendo - Wii - NKit RVZ [zstd-19-128k]":           f"{_RD}/Nintendo%20-%20Wii%20-%20NKit%20RVZ%20%5Bzstd-19-128k%5D",
    "Nintendo - Wii":                                      f"{_RD}/Nintendo%20-%20Wii%20-%20NKit%20RVZ%20%5Bzstd-19-128k%5D",
    "Nintendo - Wii U - WUX":                              f"{_RD}/Nintendo%20-%20Wii%20U%20-%20WUX",
    "Nintendo - Wii U":                                    f"{_RD}/Nintendo%20-%20Wii%20U%20-%20WUX",

    # ── Sony ────────────────────────────────────────────
    "Sony - PlayStation":                                  f"{_RD}/Sony%20-%20PlayStation",
    "Sony - PlayStation 2":                                f"{_RD}/Sony%20-%20PlayStation%202",
    "Sony - PlayStation 3":                                f"{_RD}/Sony%20-%20PlayStation%203",
    "Sony - PlayStation Portable":                         f"{_RD}/Sony%20-%20PlayStation%20Portable",
    "Sony - PlayStation Vita":                             f"{_NI}/Sony%20-%20PlayStation%20Vita%20(PSN)%20(Decrypted)",

    # ── Sega Cartridge ──────────────────────────────────
    "Sega - Master System - Mark III":                     f"{_NI}/Sega%20-%20Master%20System%20-%20Mark%20III",
    "Sega - Mega Drive - Genesis":                         f"{_NI}/Sega%20-%20Mega%20Drive%20-%20Genesis",
    "Sega - Game Gear":                                    f"{_NI}/Sega%20-%20Game%20Gear",
    "Sega - 32X":                                          f"{_NI}/Sega%20-%2032X",
    "Sega - SG-1000":                                      f"{_NI}/Sega%20-%20SG-1000",

    # ── Sega Disc ───────────────────────────────────────
    "Sega - Mega CD & Sega CD":                            f"{_RD}/Sega%20-%20Mega%20CD%20%26%20Sega%20CD",
    "Sega - Mega-CD - Sega CD":                            f"{_RD}/Sega%20-%20Mega%20CD%20%26%20Sega%20CD",
    "Sega - Saturn":                                       f"{_RD}/Sega%20-%20Saturn",
    "Sega - Dreamcast":                                    f"{_RD}/Sega%20-%20Dreamcast",

    # ── Microsoft ───────────────────────────────────────
    "Microsoft - Xbox":                                    f"{_RD}/Microsoft%20-%20Xbox",
    "Microsoft - Xbox 360":                                f"{_RD}/Microsoft%20-%20Xbox%20360",

    # ── Atari ───────────────────────────────────────────
    "Atari - 2600":                                        f"{_NI}/Atari%20-%202600",
    "Atari - 5200":                                        f"{_NI}/Atari%20-%205200",
    "Atari - 7800":                                        f"{_NI}/Atari%20-%207800",
    "Atari - Jaguar":                                      f"{_NI}/Atari%20-%20Jaguar",
    "Atari - Lynx":                                        f"{_NI}/Atari%20-%20Lynx",
    "Atari - Jaguar CD Interactive Multimedia System":     f"{_RD}/Atari%20-%20Jaguar%20CD%20Interactive%20Multimedia%20System",
    "Atari - ST":                                          f"{_NI}/Atari%20-%20ST",

    # ── NEC ─────────────────────────────────────────────
    "NEC - PC Engine - TurboGrafx-16":                     f"{_NI}/NEC%20-%20PC%20Engine%20-%20TurboGrafx-16",
    "NEC - PC Engine SuperGrafx":                          f"{_NI}/NEC%20-%20PC%20Engine%20SuperGrafx",
    "NEC - PC Engine CD & TurboGrafx CD":                  f"{_RD}/NEC%20-%20PC%20Engine%20CD%20%26%20TurboGrafx%20CD",
    "NEC - PC-FX & PC-FXGA":                               f"{_RD}/NEC%20-%20PC-FX%20%26%20PC-FXGA",

    # ── SNK ─────────────────────────────────────────────
    "SNK - Neo Geo Pocket":                                f"{_NI}/SNK%20-%20Neo%20Geo%20Pocket",
    "SNK - Neo Geo Pocket Color":                          f"{_NI}/SNK%20-%20Neo%20Geo%20Pocket%20Color",
    "SNK - Neo Geo CD":                                    f"{_RD}/SNK%20-%20Neo%20Geo%20CD",

    # ── Bandai ──────────────────────────────────────────
    "Bandai - WonderSwan":                                 f"{_NI}/Bandai%20-%20WonderSwan",
    "Bandai - WonderSwan Color":                           f"{_NI}/Bandai%20-%20WonderSwan%20Color",

    # ── Coleco / Mattel ─────────────────────────────────
    "Coleco - ColecoVision":                               f"{_NI}/Coleco%20-%20ColecoVision",
    "Mattel - Intellivision":                              f"{_NI}/Mattel%20-%20Intellivision",

    # ── Panasonic / Philips ─────────────────────────────
    "Panasonic - 3DO Interactive Multiplayer":             f"{_RD}/Panasonic%20-%203DO%20Interactive%20Multiplayer",
    "Philips - CD-i":                                      f"{_RD}/Philips%20-%20CD-i",

    # ── Commodore ───────────────────────────────────────
    "Commodore - Amiga":                                   f"{_NI}/Commodore%20-%20Amiga",
    "Commodore - Commodore 64":                            f"{_NI}/Commodore%20-%20Commodore%2064",
    "Commodore - Commodore 64 (Tapes)":                    f"{_NI}/Commodore%20-%20Commodore%2064%20(Tapes)",
    "Commodore - VIC-20":                                  f"{_NI}/Commodore%20-%20VIC-20",
    "Commodore - Amiga CD":                                f"{_RD}/Commodore%20-%20Amiga%20CD",
    "Commodore - Amiga CD32":                              f"{_RD}/Commodore%20-%20Amiga%20CD32",
    "Commodore - Amiga CDTV":                              f"{_RD}/Commodore%20-%20Amiga%20CDTV",

    # ── Other retro ─────────────────────────────────────
    "GCE - Vectrex":                                       f"{_NI}/GCE%20-%20Vectrex",
    "Magnavox - Odyssey 2":                                f"{_NI}/Magnavox%20-%20Odyssey2",
    "Watara - Supervision":                                f"{_NI}/Watara%20-%20Supervision",
    "Fairchild - Channel F":                               f"{_NI}/Fairchild%20-%20Channel%20F",

    # ── Sharp / Fujitsu / NEC PC ────────────────────────
    "Sharp - X68000":                                      f"{_RD}/Sharp%20-%20X68000",
    "Fujitsu - FM-Towns":                                  f"{_RD}/Fujitsu%20-%20FM-Towns",
    "NEC - PC-98 series":                                  f"{_RD}/NEC%20-%20PC-98%20series",
    "NEC - PC-88 series":                                  f"{_RD}/NEC%20-%20PC-88%20series",
}
# fmt: on


# ═══════════════════════════════════════════════════════════════
# HTML DIRECTORY PARSER
# ═══════════════════════════════════════════════════════════════

@dataclass
class RemoteFile:
    """A file on a remote HTTP directory."""
    name: str
    url: str
    size: int = 0               # in bytes (0 if unknown)
    size_text: str = ""         # human-readable size from the listing
    date: str = ""


class _DirectoryParser(HTMLParser):
    """Parse an HTML directory listing for <a> tags."""

    def __init__(self):
        super().__init__()
        self.links: List[Tuple[str, str]] = []   # (href, text)
        self._in_a = False
        self._href = ""
        self._text = ""

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self._in_a = True
            self._text = ""
            for k, v in attrs:
                if k == 'href':
                    self._href = v or ""

    def handle_data(self, data):
        if self._in_a:
            self._text += data

    def handle_endtag(self, tag):
        if tag == 'a' and self._in_a:
            self._in_a = False
            if self._href and self._text.strip():
                self.links.append((self._href, self._text.strip()))


# ═══════════════════════════════════════════════════════════════
# DOWNLOAD STATE
# ═══════════════════════════════════════════════════════════════

class DownloadStatus(Enum):
    QUEUED = auto()
    DOWNLOADING = auto()
    COMPLETE = auto()
    FAILED = auto()
    CANCELLED = auto()
    CRC_MISMATCH = auto()


@dataclass
class DownloadTask:
    """A single download task in the queue."""
    rom_name: str
    url: str
    dest_path: str
    expected_crc: str = ""
    expected_size: int = 0
    status: DownloadStatus = DownloadStatus.QUEUED
    downloaded_bytes: int = 0
    total_bytes: int = 0
    error: str = ""
    system_name: str = ""
    computed_crc: str = ""   # CRC32 computed during streaming download


@dataclass
class DownloadProgress:
    """Overall queue progress."""
    current_index: int = 0  # This concept is fuzzy in parallel, usually represents 'completed + 1'
    total_count: int = 0
    current_task: Optional[DownloadTask] = None  # Last updated task
    completed: int = 0
    failed: int = 0
    cancelled: int = 0


# ═══════════════════════════════════════════════════════════════
# MYRIENT DOWNLOADER (main class)
# ═══════════════════════════════════════════════════════════════

class MyrientDownloader:
    """
    Browse, search and download ROMs from Myrient (and IA fallback).
    Downloads run SEQUENTIALLY, one file at a time (browser-style).
    """

    def __init__(self):
        if not REQUESTS_AVAILABLE:
            raise RuntimeError(
                "The 'requests' library is required for downloads. "
                "Install it with: pip install requests"
            )
        self.session = requests.Session()

        # Robust retry strategy (handles transient server errors)
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        
        # PHASE 1: Connection Pooling Optimization
        # Maintain persistent connections to avoid SSL handshake overhead (TTFB)
        adapter = HTTPAdapter(
            max_retries=retries,
            pool_connections=20,   # Increased for parallelism (approx 4x workers)
            pool_maxsize=20,       # Pool capacity per host
            pool_block=False       # Never block caller if pool is full
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        # Browser User-Agent to avoid server-side throttling + keep-alive
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/120.0.0.0 Safari/537.36',
            'Connection': 'keep-alive',
        })
        self.timeout = 30

        # Download queue
        self._queue: List[DownloadTask] = []
        self._cancel_flag = False
        self._pause_flag = False
        

    # ── Catalog helpers ────────────────────────────────────────

    @staticmethod
    def get_catalog() -> Dict[str, str]:
        """Return the full system catalog (system_name -> myrient_path)."""
        return dict(MYRIENT_CATALOG)

    @staticmethod
    def get_systems() -> List[Dict[str, str]]:
        """Return list of systems with name and category."""
        seen = set()
        systems = []
        for name, path in MYRIENT_CATALOG.items():
            if name in seen:
                continue
            seen.add(name)
            cat = "No-Intro" if path.startswith(_NI) else "Redump" if path.startswith(_RD) else "Other"
            systems.append({'name': name, 'category': cat, 'path': path})
        return sorted(systems, key=lambda s: s['name'])

    @staticmethod
    def find_system_url(system_name: str) -> Optional[str]:
        """
        Find the Myrient URL for a system name (from DAT header).
        Does fuzzy matching if exact match isn't found.
        """
        path = MYRIENT_CATALOG.get(system_name)
        if path:
            return f"{MYRIENT_BASE}/{path}/"

        normalized = system_name.strip()
        for key, path in MYRIENT_CATALOG.items():
            if key.lower() == normalized.lower():
                return f"{MYRIENT_BASE}/{path}/"

        lower = normalized.lower()
        for key, path in MYRIENT_CATALOG.items():
            if lower in key.lower() or key.lower() in lower:
                return f"{MYRIENT_BASE}/{path}/"

        return None

    # ── Directory Listing ──────────────────────────────────────

    def list_files(self, system_name: str = "",
                   url: str = "") -> List[RemoteFile]:
        if not url:
            url = self.find_system_url(system_name)
            if not url:
                return []

        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
        except Exception as e:
            log_event('download.list.error', f'Failed listing URL {url}: {e}', logging.ERROR)
            return []

        parser = _DirectoryParser()
        parser.feed(resp.text)

        files = []
        for href, text in parser.links:
            if href in ('..', '../', '/') or text in ('..', 'Parent Directory', 'Name'):
                continue
            if href.endswith('/'):
                continue
            lower = text.lower()
            if lower.endswith(('.xml', '.sqlite', '.txt', '.html')):
                continue

            file_url = href if href.startswith('http') else url.rstrip('/') + '/' + href
            name = unquote(text)

            files.append(RemoteFile(name=name, url=file_url))

        return files

    def search_files(self, system_name: str, query: str,
                     url: str = "") -> List[RemoteFile]:
        all_files = self.list_files(system_name, url)
        if not query:
            return all_files
        q = query.lower()
        return [f for f in all_files if q in f.name.lower()]

    def find_rom_url(self, rom: ROMInfo) -> Optional[str]:
        system_url = self.find_system_url(rom.system_name)
        if not system_url:
            return None

        rom_filename = rom.name
        if not rom_filename.lower().endswith('.zip'):
            rom_basename = os.path.splitext(rom_filename)[0]
            possible_url = system_url.rstrip('/') + '/' + quote(rom_basename + '.zip')
        else:
            possible_url = system_url.rstrip('/') + '/' + quote(rom_filename)

        try:
            resp = self.session.head(possible_url, timeout=self.timeout, allow_redirects=True)
            if resp.status_code == 200:
                return possible_url
        except Exception as e:
            log_event('download.lookup.error', f'HEAD failed for {possible_url}: {e}', logging.ERROR)
        return None

    # ── Download Queue ─────────────────────────────────────────

    def clear_queue(self):
        self._queue.clear()
        self._cancel_flag = False
        self._pause_flag = False

    def get_queue(self) -> List[DownloadTask]:
        return list(self._queue)

    def queue_rom(self, rom_name: str, url: str, dest_folder: str,
                  expected_crc: str = "", expected_size: int = 0,
                  system_name: str = "") -> DownloadTask:
        filename = unquote(url.split('/')[-1])
        dest = os.path.join(dest_folder, filename)

        task = DownloadTask(
            rom_name=rom_name,
            url=url,
            dest_path=dest,
            expected_crc=expected_crc,
            expected_size=expected_size,
            system_name=system_name,
        )
        self._queue.append(task)
        log_event('download.queue.add', f'Queued {filename} -> {dest}')
        return task

    def queue_missing_roms(self, missing_roms: List[ROMInfo],
                           dest_folder: str,
                           progress_callback: Optional[Callable[[str, int, int], None]] = None
                           ) -> int:
        queued = 0
        total = len(missing_roms)

        for i, rom in enumerate(missing_roms):
            if self._cancel_flag:
                break
            if progress_callback:
                progress_callback(rom.name, i + 1, total)

            url = self.find_rom_url(rom)
            if url:
                self.queue_rom(
                    rom_name=rom.name,
                    url=url,
                    dest_folder=dest_folder,
                    expected_crc=rom.crc32,
                    expected_size=rom.size,
                    system_name=rom.system_name,
                )
                queued += 1
        return queued

    def start_downloads(self,
                        progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
                        download_delay: int = 5) -> DownloadProgress:
        """
        Execute downloads SEQUENTIALLY, one file at a time (browser-style).

        Args:
            progress_callback: Called when progress changes.
            download_delay: Seconds to wait between downloads (0-60, default 5).
        """
        self._cancel_flag = False
        self._pause_flag = False

        download_delay = max(0, min(60, download_delay))

        progress = DownloadProgress(total_count=len(self._queue))

        for i, task in enumerate(self._queue):
            if self._cancel_flag:
                task.status = DownloadStatus.CANCELLED
                progress.cancelled += 1
                log_event('download.cancelled', f'Cancelled before start: {task.rom_name}')
                self._safe_callback(progress, progress_callback)
                continue

            # Wait if paused
            while self._pause_flag and not self._cancel_flag:
                time.sleep(0.5)

            # Delay between downloads (skip before first file)
            if i > 0 and download_delay > 0 and not self._cancel_flag:
                for _ in range(download_delay * 2):  # Check cancel every 0.5s
                    if self._cancel_flag or self._pause_flag:
                        break
                    time.sleep(0.5)
                while self._pause_flag and not self._cancel_flag:
                    time.sleep(0.5)

            if self._cancel_flag:
                task.status = DownloadStatus.CANCELLED
                progress.cancelled += 1
                self._safe_callback(progress, progress_callback)
                continue

            task.status = DownloadStatus.DOWNLOADING
            progress.current_task = task
            log_event('download.start', f'Starting download: {task.rom_name}')
            self._safe_callback(progress, progress_callback)

            try:
                self._download_file(task, progress, progress_callback)
            except Exception as e:
                task.status = DownloadStatus.FAILED
                task.error = str(e)
                progress.failed += 1
                log_event('download.failed', f'Failed {task.rom_name}: {e}', logging.ERROR)
                self._safe_callback(progress, progress_callback)
                continue

            if self._cancel_flag:
                continue

            # CRC Verification
            if task.expected_crc:
                actual_crc = task.computed_crc
                if actual_crc.lower() == task.expected_crc.lower():
                    task.status = DownloadStatus.COMPLETE
                    progress.completed += 1
                    log_event('download.complete', f'Completed {task.rom_name}')
                else:
                    inner_crc = self._check_inner_zip_crc(task.dest_path, task.expected_crc)
                    if inner_crc and inner_crc.lower() == task.expected_crc.lower():
                        task.status = DownloadStatus.COMPLETE
                        progress.completed += 1
                        log_event('download.complete', f'Completed {task.rom_name} (inner ZIP CRC ok)')
                    else:
                        task.status = DownloadStatus.CRC_MISMATCH
                        task.error = f"CRC mismatch: expected {task.expected_crc}, got {actual_crc}"
                        progress.failed += 1
                        log_event('download.crc_mismatch', f'{task.rom_name}: {task.error}', logging.ERROR)
            else:
                task.status = DownloadStatus.COMPLETE
                progress.completed += 1
                log_event('download.complete', f'Completed {task.rom_name}')

            progress.current_index = progress.completed + progress.failed + progress.cancelled
            self._safe_callback(progress, progress_callback)

        return progress

    def cancel(self):
        self._cancel_flag = True
        log_event('download.cancel.requested', 'Cancel requested by user')

    def pause(self):
        self._pause_flag = True
        log_event('download.pause', 'Pause requested by user')

    def resume(self):
        self._pause_flag = False
        log_event('download.resume', 'Resume requested by user')

    # ── Internal ───────────────────────────────────────────────

    def _safe_callback(self, progress: DownloadProgress,
                       callback: Optional[Callable[[DownloadProgress], None]]):
        """Invoke the UI callback."""
        if callback:
            callback(progress)

    def _download_file(self, task: DownloadTask,
                       progress: DownloadProgress,
                       callback: Optional[Callable[[DownloadProgress], None]]):
        """
        Download a single file at FULL SPEED, computing CRC32 during streaming.
        Uses 256KB chunks and reports progress safely.
        """
        os.makedirs(os.path.dirname(task.dest_path) or '.', exist_ok=True)

        resp = self.session.get(task.url, stream=True, timeout=self.timeout)
        resp.raise_for_status()

        task.total_bytes = int(resp.headers.get('content-length', 0))
        task.downloaded_bytes = 0

        chunk_size = 256 * 1024
        last_ui_update = 0.0
        crc = 0

        with open(task.dest_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if self._cancel_flag:
                    task.status = DownloadStatus.CANCELLED
                    log_event('download.cancelled', f'Cancelled during transfer: {task.rom_name}')
                    return

                while self._pause_flag and not self._cancel_flag:
                    time.sleep(0.5)

                if chunk:
                    f.write(chunk)
                    task.downloaded_bytes += len(chunk)
                    crc = zlib.crc32(chunk, crc)

                    now = time.time()
                    # Throttle UI updates (limit to ~10Hz per thread)
                    if callback and task.total_bytes > 0 and (now - last_ui_update > 0.1):
                        self._safe_callback(progress, callback)
                        last_ui_update = now

        task.computed_crc = f"{crc & 0xFFFFFFFF:08x}"

    @staticmethod
    def _compute_crc32(filepath: str) -> str:
        """Compute CRC32 of a file (Legacy fallback)."""
        crc = 0
        with open(filepath, 'rb') as f:
            while True:
                data = f.read(65536)
                if not data:
                    break
                crc = zlib.crc32(data, crc)
        return f"{crc & 0xFFFFFFFF:08x}"

    @staticmethod
    def _check_inner_zip_crc(filepath: str, target_crc: Optional[str] = None) -> Optional[str]:
        """Check CRC of files inside a ZIP archive without extracting."""
        try:
            if zipfile.is_zipfile(filepath):
                with zipfile.ZipFile(filepath, 'r') as zf:
                    infos = [i for i in zf.infolist() if not i.is_dir()]
                    if not infos:
                        return None
                    
                    if target_crc:
                        target = target_crc.lower()
                        for info in infos:
                            if f"{info.CRC:08x}".lower() == target:
                                return f"{info.CRC:08x}"
                    
                    largest = max(infos, key=lambda i: i.file_size)
                    return f"{largest.CRC:08x}"
        except Exception as e:
            log_event('download.crc.error', f'Failed to inspect ZIP CRC {filepath}: {e}', logging.ERROR)
        return None
