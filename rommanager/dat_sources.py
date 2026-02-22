"""
Known DAT download sources and update checking.
"""

import os
import webbrowser
from typing import Callable, Dict, List, Optional

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


# Known public DAT sources
KNOWN_SOURCES = [
    {
        'id': 'datomatic',
        'name': 'DAT-o-MATIC (No-Intro)',
        'url': 'https://datomatic.no-intro.org/',
        'type': 'manual',
        'description': 'Official No-Intro DAT distribution. Requires free account and login.',
        'instructions': 'Visit the site, log in (or create a free account), '
                       'and download daily or individual DAT packs.',
    },
    {
        'id': 'redump',
        'name': 'Redump',
        'url': 'http://redump.org/downloads/',
        'type': 'manual',
        'description': 'Disc-based system DATs (PlayStation, Saturn, Dreamcast, etc.).',
        'instructions': 'Visit the downloads page and download individual system DATs.',
    },
    {
        'id': 'libretro_nointro',
        'name': 'Libretro No-Intro (GitHub)',
        'url': 'https://github.com/libretro/libretro-database/tree/master/dat',
        'type': 'direct',
        'description': 'No-Intro DATs mirrored on GitHub by the Libretro project.',
        'base_url': 'https://raw.githubusercontent.com/libretro/libretro-database/master/dat/',
    },
    {
        'id': 'libretro_redump',
        'name': 'Libretro Redump (GitHub)',
        'url': 'https://github.com/libretro/libretro-database/tree/master/rdb',
        'type': 'manual',
        'description': 'Redump-derived databases from Libretro.',
        'instructions': 'Visit the GitHub repo to browse available databases.',
    },
]


class DATSourceManager:
    """Manages known DAT download sources."""

    def __init__(self):
        self.sources = {s['id']: s for s in KNOWN_SOURCES}

    def get_sources(self) -> List[Dict]:
        """List known DAT sources."""
        return KNOWN_SOURCES[:]

    def open_source_page(self, source_id: str) -> bool:
        """Open the source's download page in the user's browser."""
        source = self.sources.get(source_id)
        if source:
            webbrowser.open(source['url'])
            return True
        return False

    def download_dat(self, url: str, dest_folder: str,
                    filename: Optional[str] = None,
                    progress_callback: Optional[Callable[[int, int], None]] = None
                    ) -> Optional[str]:
        """
        Download a DAT file from a URL.

        Args:
            url: Direct URL to the DAT file
            dest_folder: Destination folder
            filename: Optional filename override
            progress_callback: Optional callback(downloaded, total)

        Returns:
            Path to downloaded file, or None on failure.
        """
        if not REQUESTS_AVAILABLE:
            return None

        try:
            os.makedirs(dest_folder, exist_ok=True)

            resp = requests.get(url, stream=True, timeout=30)
            resp.raise_for_status()

            if not filename:
                # Try to get filename from Content-Disposition header
                cd = resp.headers.get('Content-Disposition', '')
                if 'filename=' in cd:
                    filename = cd.split('filename=')[-1].strip('" ')
                else:
                    filename = url.split('/')[-1]

            dest_path = os.path.join(dest_folder, filename)
            total_size = int(resp.headers.get('content-length', 0))
            downloaded = 0

            with open(dest_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total_size)

            return dest_path
        except Exception:
            return None

    def list_libretro_dats(self) -> List[Dict]:
        """
        List available No-Intro DATs from the Libretro GitHub mirror.
        Returns list of dicts with: name, url, system.
        """
        if not REQUESTS_AVAILABLE:
            return []

        try:
            api_url = "https://api.github.com/repos/libretro/libretro-database/contents/dat"
            resp = requests.get(api_url, timeout=15)
            resp.raise_for_status()
            files = resp.json()

            dats = []
            for f in files:
                if f.get('name', '').endswith('.dat'):
                    name = f['name']
                    system = name.replace('.dat', '')
                    dats.append({
                        'name': name,
                        'system': system,
                        'url': f.get('download_url', ''),
                        'size': f.get('size', 0),
                    })

            return sorted(dats, key=lambda d: d['system'])
        except Exception:
            return []
