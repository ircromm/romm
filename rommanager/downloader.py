"""
Internet Archive downloader - search and download ROMs from archive.org.
"""

import os
import time
from typing import Callable, Dict, List, Optional

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from .models import ROMInfo


class ArchiveOrgDownloader:
    """Search and download files from the Internet Archive."""

    BASE_SEARCH = "https://archive.org/advancedsearch.php"
    BASE_METADATA = "https://archive.org/metadata"
    BASE_DOWNLOAD = "https://archive.org/download"

    # Rate limiting: minimum seconds between requests
    # OPTIMIZATION (Phase 3): Reduced from 1.0 to 0.5 to speed up batch operations
    # while staying within safe API limits.
    MIN_REQUEST_INTERVAL = 0.5

    def __init__(self):
        if not REQUESTS_AVAILABLE:
            raise RuntimeError(
                "The 'requests' library is required for downloads. "
                "Install it with: pip install requests"
            )
        self._last_request_time = 0.0
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'ROMCollectionManager/1.0 (preservation tool)'
        })
        self.timeout = 30

    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.time()

    def search(self, rom_name: str, system_name: str = "",
               max_results: int = 10) -> List[Dict]:
        """
        Search archive.org for items matching a ROM name.

        Returns list of results with: identifier, title, description, date.
        """
        self._rate_limit()

        # Build query: search in title, optionally filter by system/collection
        query_parts = [f'title:("{rom_name}")']
        if system_name:
            query_parts.append(f'("{system_name}")')

        query = " AND ".join(query_parts)

        params = {
            'q': query,
            'fl[]': ['identifier', 'title', 'description', 'date',
                     'item_size', 'collection'],
            'rows': max_results,
            'output': 'json',
        }

        try:
            resp = self.session.get(self.BASE_SEARCH, params=params,
                                   timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            docs = data.get('response', {}).get('docs', [])
            return docs
        except Exception as e:
            return [{'error': str(e)}]

    def search_by_hash(self, crc32: str = "", md5: str = "",
                       sha1: str = "", max_results: int = 5) -> List[Dict]:
        """
        Search archive.org by hash values (when available in metadata).
        Note: Hash searching on IA is limited and may not always work.
        """
        self._rate_limit()

        query_parts = []
        if sha1:
            query_parts.append(f'sha1:"{sha1.lower()}"')
        elif md5:
            query_parts.append(f'md5:"{md5.lower()}"')
        elif crc32:
            query_parts.append(f'crc32:"{crc32.lower()}"')
        else:
            return []

        query = " OR ".join(query_parts)

        params = {
            'q': query,
            'fl[]': ['identifier', 'title', 'description', 'date'],
            'rows': max_results,
            'output': 'json',
        }

        try:
            resp = self.session.get(self.BASE_SEARCH, params=params,
                                   timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data.get('response', {}).get('docs', [])
        except Exception:
            return []

    def get_item_files(self, identifier: str) -> List[Dict]:
        """
        List files inside an Internet Archive item.

        Returns list of dicts with: name, size, format, download_url.
        """
        self._rate_limit()

        url = f"{self.BASE_METADATA}/{identifier}/files"

        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()

            files = []
            result = data.get('result', data) if isinstance(data, dict) else data
            if isinstance(result, list):
                file_list = result
            else:
                file_list = result.get('result', []) if isinstance(result, dict) else []

            for f in file_list:
                name = f.get('name', '')
                size = int(f.get('size', 0)) if f.get('size') else 0
                fmt = f.get('format', '')
                download_url = f"{self.BASE_DOWNLOAD}/{identifier}/{name}"

                files.append({
                    'name': name,
                    'size': size,
                    'format': fmt,
                    'download_url': download_url,
                })

            return files
        except Exception:
            return []

    def download(self, url: str, dest_folder: str,
                 filename: Optional[str] = None,
                 progress_callback: Optional[Callable[[int, int], None]] = None
                 ) -> str:
        """
        Download a file from the Internet Archive.

        Args:
            url: Full download URL
            dest_folder: Destination folder
            filename: Optional filename override
            progress_callback: Optional callback(downloaded_bytes, total_bytes)

        Returns:
            Path to downloaded file.
        """
        self._rate_limit()

        os.makedirs(dest_folder, exist_ok=True)

        if not filename:
            filename = url.split('/')[-1]

        dest_path = os.path.join(dest_folder, filename)

        resp = self.session.get(url, stream=True, timeout=self.timeout)
        resp.raise_for_status()

        total_size = int(resp.headers.get('content-length', 0))
        downloaded = 0
        chunk_size = 256 * 1024  # 256KB chunks — matches Myrient, fewer syscalls

        with open(dest_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_size)

        return dest_path

    def batch_search(self, missing_roms: List[ROMInfo],
                     progress_callback: Optional[Callable[[int, int], None]] = None
                     ) -> Dict[str, List[Dict]]:
        """
        Search for multiple missing ROMs on archive.org.

        Respects rate limiting.

        Args:
            missing_roms: List of ROMInfo objects to search for
            progress_callback: Optional callback(current_index, total)

        Returns:
            Dict mapping rom name -> list of search results.
        """
        results = {}
        total = len(missing_roms)

        for i, rom in enumerate(missing_roms):
            # Use game_name for broader search, fall back to rom name
            search_term = rom.game_name if rom.game_name else rom.name
            # Clean search term (remove parenthetical info)
            import re
            clean_term = re.sub(r'\s*\([^)]*\)', '', search_term).strip()

            if clean_term:
                docs = self.search(clean_term, rom.system_name, max_results=5)
                results[rom.name] = docs

            if progress_callback:
                progress_callback(i + 1, total)

        return results