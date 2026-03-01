"""
ROM matcher - matches scanned files against DAT database
"""

from typing import Callable, Dict, List, Optional, Tuple

from .models import ROMInfo, ScannedFile, DATInfo


class ROMMatcher:
    """
    Matches scanned files against a DAT database.

    Uses hash indexes for O(1) lookups.
    """

    def __init__(self, roms: List[ROMInfo]):
        """
        Initialize matcher with ROM database.

        Args:
            roms: List of ROMInfo from parsed DAT file
        """
        self.roms = roms
        self._build_indexes()

    def _build_indexes(self):
        """Build lookup indexes for fast matching"""
        # Primary index: CRC32 + size (most reliable, most common)
        self.by_crc_size: Dict[Tuple[str, int], ROMInfo] = {}

        # Secondary indexes
        self.by_md5: Dict[str, ROMInfo] = {}
        self.by_sha1: Dict[str, ROMInfo] = {}
        self.by_name: Dict[str, ROMInfo] = {}

        for rom in self.roms:
            # CRC + size index
            if rom.crc32 and rom.size:
                key = (rom.crc32.lower(), rom.size)
                self.by_crc_size[key] = rom

            # MD5 index
            if rom.md5:
                self.by_md5[rom.md5.lower()] = rom

            # SHA1 index
            if rom.sha1:
                self.by_sha1[rom.sha1.lower()] = rom

            # Name index (for reference)
            if rom.name:
                self.by_name[rom.name.lower()] = rom

    def match(self, scanned: ScannedFile) -> Optional[ROMInfo]:
        """
        Try to match a scanned file against the DAT database.

        Matching priority:
        1. CRC32 + size (fastest, most reliable for most DATs)
        2. MD5 (if available in both scan and DAT)
        3. SHA1 (if available in both scan and DAT)

        Args:
            scanned: ScannedFile object with checksums

        Returns:
            Matching ROMInfo or None
        """
        # Try CRC32 + size first (fastest)
        if scanned.crc32:
            key = (scanned.crc32.lower(), scanned.size)
            if key in self.by_crc_size:
                return self.by_crc_size[key]

        # Try MD5
        if scanned.md5:
            md5_lower = scanned.md5.lower()
            if md5_lower in self.by_md5:
                return self.by_md5[md5_lower]

        # Try SHA1
        if scanned.sha1:
            sha1_lower = scanned.sha1.lower()
            if sha1_lower in self.by_sha1:
                return self.by_sha1[sha1_lower]

        return None

    def match_all(
        self,
        scanned_files: List[ScannedFile],
        progress_callback: Optional[Callable[[int, int], None]] = None,
        item_callback: Optional[Callable[[ScannedFile, Optional[ROMInfo], int, int], None]] = None,
    ) -> Tuple[List[ScannedFile], List[ScannedFile]]:
        """
        Match multiple scanned files.

        Args:
            scanned_files: List of scanned files

        Returns:
            Tuple of (identified, unidentified) lists
        """
        identified = []
        unidentified = []

        total = len(scanned_files)
        for idx, scanned in enumerate(scanned_files, start=1):
            match = self.match(scanned)
            scanned.matched_rom = match

            if match:
                identified.append(scanned)
            else:
                unidentified.append(scanned)
            if item_callback:
                item_callback(scanned, match, idx, total)
            if progress_callback:
                progress_callback(idx, total)

        return identified, unidentified

    def get_missing(self, identified: List[ScannedFile]) -> List[ROMInfo]:
        """Return ROMs in the DAT that were NOT found in the identified list."""
        found_keys = set()
        for f in identified:
            if f.matched_rom:
                key = (f.matched_rom.crc32.lower(), f.matched_rom.size)
                found_keys.add(key)

        missing = []
        for rom in self.roms:
            key = (rom.crc32.lower(), rom.size)
            if key not in found_keys:
                missing.append(rom)
        return missing

    def get_completeness(self, identified: List[ScannedFile]) -> Dict:
        """Return completeness statistics."""
        total = len(self.roms)
        found = len([f for f in identified if f.matched_rom and
                     f.matched_rom.crc32 and (f.matched_rom.crc32.lower(), f.matched_rom.size)
                     in self.by_crc_size])
        missing = total - found
        return {
            'total_in_dat': total,
            'found': found,
            'missing': missing,
            'percentage': (found / total * 100) if total > 0 else 0,
        }

    def get_stats(self) -> Dict:
        """Get statistics about the DAT database"""
        regions = {}
        for rom in self.roms:
            region = rom.region or 'Unknown'
            regions[region] = regions.get(region, 0) + 1

        return {
            'total_roms': len(self.roms),
            'by_crc_size': len(self.by_crc_size),
            'by_md5': len(self.by_md5),
            'by_sha1': len(self.by_sha1),
            'regions': regions
        }


class MultiROMMatcher:
    """
    Matches scanned files against multiple DAT databases simultaneously.
    Wraps multiple ROMMatcher instances, one per loaded DAT.
    """

    def __init__(self):
        self.matchers: Dict[str, ROMMatcher] = {}
        self.dat_infos: Dict[str, DATInfo] = {}
        self.all_roms: Dict[str, List[ROMInfo]] = {}
        self._global_by_crc_size: Dict[Tuple[str, int], ROMInfo] = {}
        self._global_by_md5: Dict[str, ROMInfo] = {}
        self._global_by_sha1: Dict[str, ROMInfo] = {}

    def _rebuild_global_indexes(self) -> None:
        self._global_by_crc_size = {}
        self._global_by_md5 = {}
        self._global_by_sha1 = {}
        for dat_id in self.dat_infos.keys():
            roms = self.all_roms.get(dat_id, [])
            for rom in roms:
                if rom.crc32 and rom.size:
                    key = (rom.crc32.lower(), rom.size)
                    if key not in self._global_by_crc_size:
                        self._global_by_crc_size[key] = rom
                if rom.md5:
                    key_md5 = rom.md5.lower()
                    if key_md5 not in self._global_by_md5:
                        self._global_by_md5[key_md5] = rom
                if rom.sha1:
                    key_sha1 = rom.sha1.lower()
                    if key_sha1 not in self._global_by_sha1:
                        self._global_by_sha1[key_sha1] = rom

    def add_dat(self, dat_info: DATInfo, roms: List[ROMInfo]) -> None:
        """Add a DAT to the multi-matcher."""
        for rom in roms:
            rom.dat_id = dat_info.id
            rom.system_name = dat_info.system_name
        self.matchers[dat_info.id] = ROMMatcher(roms)
        self.dat_infos[dat_info.id] = dat_info
        self.all_roms[dat_info.id] = roms
        # Build merged O(1) lookup tables across all DATs.
        # First-loaded match wins for deterministic behavior.
        for rom in roms:
            if rom.crc32 and rom.size:
                key = (rom.crc32.lower(), rom.size)
                if key not in self._global_by_crc_size:
                    self._global_by_crc_size[key] = rom
            if rom.md5:
                key_md5 = rom.md5.lower()
                if key_md5 not in self._global_by_md5:
                    self._global_by_md5[key_md5] = rom
            if rom.sha1:
                key_sha1 = rom.sha1.lower()
                if key_sha1 not in self._global_by_sha1:
                    self._global_by_sha1[key_sha1] = rom

    def remove_dat(self, dat_id: str) -> None:
        """Remove a DAT from the multi-matcher."""
        self.matchers.pop(dat_id, None)
        self.dat_infos.pop(dat_id, None)
        self.all_roms.pop(dat_id, None)
        self._rebuild_global_indexes()

    def get_dat_list(self) -> List[DATInfo]:
        """Return list of loaded DATInfo objects."""
        return list(self.dat_infos.values())

    def match(self, scanned: ScannedFile) -> Optional[ROMInfo]:
        """Try matching against all loaded DATs via merged indexes. First-loaded match wins."""
        if scanned.crc32:
            key = (scanned.crc32.lower(), scanned.size)
            if key in self._global_by_crc_size:
                return self._global_by_crc_size[key]
        if scanned.md5:
            key_md5 = scanned.md5.lower()
            if key_md5 in self._global_by_md5:
                return self._global_by_md5[key_md5]
        if scanned.sha1:
            key_sha1 = scanned.sha1.lower()
            if key_sha1 in self._global_by_sha1:
                return self._global_by_sha1[key_sha1]
        return None

    def match_all(
        self,
        scanned_files: List[ScannedFile],
        progress_callback: Optional[Callable[[int, int], None]] = None,
        item_callback: Optional[Callable[[ScannedFile, Optional[ROMInfo], int, int], None]] = None,
    ) -> Tuple[List[ScannedFile], List[ScannedFile]]:
        """Match files against all loaded DATs."""
        identified = []
        unidentified = []

        total = len(scanned_files)
        for idx, scanned in enumerate(scanned_files, start=1):
            match = self.match(scanned)
            scanned.matched_rom = match

            if match:
                identified.append(scanned)
            else:
                unidentified.append(scanned)
            if item_callback:
                item_callback(scanned, match, idx, total)
            if progress_callback:
                progress_callback(idx, total)

        return identified, unidentified

    def get_missing(self, identified: List[ScannedFile]) -> List[ROMInfo]:
        """Return all ROMs missing across all DATs."""
        all_missing = []
        for dat_id, matcher in self.matchers.items():
            # Filter identified to only those from this DAT
            dat_identified = [f for f in identified
                            if f.matched_rom and f.matched_rom.dat_id == dat_id]
            all_missing.extend(matcher.get_missing(dat_identified))
        return all_missing

    def get_missing_by_dat(self, identified: List[ScannedFile]) -> Dict[str, List[ROMInfo]]:
        """Return missing ROMs grouped by DAT id."""
        result = {}
        for dat_id, matcher in self.matchers.items():
            dat_identified = [f for f in identified
                            if f.matched_rom and f.matched_rom.dat_id == dat_id]
            result[dat_id] = matcher.get_missing(dat_identified)
        return result

    def get_completeness(self, identified: List[ScannedFile]) -> Dict:
        """Return overall completeness statistics."""
        total = sum(len(roms) for roms in self.all_roms.values())
        found = len(identified)
        missing = total - found
        return {
            'total_in_dat': total,
            'found': found,
            'missing': missing,
            'percentage': (found / total * 100) if total > 0 else 0,
        }

    def get_completeness_by_dat(self, identified: List[ScannedFile]) -> Dict[str, Dict]:
        """Return per-DAT completeness statistics."""
        result = {}
        for dat_id, matcher in self.matchers.items():
            dat_info = self.dat_infos[dat_id]
            dat_identified = [f for f in identified
                            if f.matched_rom and f.matched_rom.dat_id == dat_id]
            stats = matcher.get_completeness(dat_identified)
            stats['dat_name'] = dat_info.name
            stats['system_name'] = dat_info.system_name
            result[dat_id] = stats
        return result

    def get_stats(self) -> Dict:
        """Get combined statistics."""
        return {
            'dat_count': len(self.matchers),
            'total_roms': sum(len(roms) for roms in self.all_roms.values()),
            'dats': {
                dat_id: {
                    'name': self.dat_infos[dat_id].name,
                    'roms': len(roms),
                }
                for dat_id, roms in self.all_roms.items()
            }
        }

    @property
    def roms(self) -> List[ROMInfo]:
        """All ROMs across all DATs (for backward compat)."""
        all_roms = []
        for roms in self.all_roms.values():
            all_roms.extend(roms)
        return all_roms
