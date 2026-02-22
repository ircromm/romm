"""
Data models for ROM Manager
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class DATInfo:
    """Metadata about a loaded DAT file"""
    id: str
    filepath: str
    name: str
    description: str = ""
    version: str = ""
    system_name: str = ""
    rom_count: int = 0
    loaded_at: str = ""

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'filepath': self.filepath,
            'name': self.name,
            'description': self.description,
            'version': self.version,
            'system_name': self.system_name,
            'rom_count': self.rom_count,
            'loaded_at': self.loaded_at,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> 'DATInfo':
        return cls(
            id=d['id'],
            filepath=d.get('filepath', ''),
            name=d.get('name', ''),
            description=d.get('description', ''),
            version=d.get('version', ''),
            system_name=d.get('system_name', ''),
            rom_count=d.get('rom_count', 0),
            loaded_at=d.get('loaded_at', ''),
        )


@dataclass
class ROMInfo:
    """Information about a ROM from DAT file"""
    name: str
    size: int
    crc32: str
    md5: str = ""
    sha1: str = ""
    description: str = ""
    game_name: str = ""
    region: str = ""
    languages: str = ""
    status: str = ""
    dat_id: str = ""
    system_name: str = ""

    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'size': self.size,
            'crc32': self.crc32,
            'md5': self.md5,
            'sha1': self.sha1,
            'description': self.description,
            'game_name': self.game_name,
            'region': self.region,
            'languages': self.languages,
            'status': self.status,
            'dat_id': self.dat_id,
            'system_name': self.system_name,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> 'ROMInfo':
        return cls(
            name=d['name'],
            size=d.get('size', 0),
            crc32=d.get('crc32', ''),
            md5=d.get('md5', ''),
            sha1=d.get('sha1', ''),
            description=d.get('description', ''),
            game_name=d.get('game_name', ''),
            region=d.get('region', ''),
            languages=d.get('languages', ''),
            status=d.get('status', ''),
            dat_id=d.get('dat_id', ''),
            system_name=d.get('system_name', ''),
        )


@dataclass
class ScannedFile:
    """Information about a scanned file"""
    path: str
    filename: str
    size: int
    crc32: str = ""
    md5: str = ""
    sha1: str = ""
    matched_rom: Optional[ROMInfo] = None
    forced: bool = False

    def to_dict(self) -> Dict:
        return {
            'path': self.path,
            'filename': self.filename,
            'size': self.size,
            'crc32': self.crc32,
            'md5': self.md5,
            'sha1': self.sha1,
            'matched_rom': self.matched_rom.to_dict() if self.matched_rom else None,
            'forced': self.forced,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> 'ScannedFile':
        matched = None
        if d.get('matched_rom'):
            matched = ROMInfo.from_dict(d['matched_rom'])
        return cls(
            path=d['path'],
            filename=d['filename'],
            size=d.get('size', 0),
            crc32=d.get('crc32', ''),
            md5=d.get('md5', ''),
            sha1=d.get('sha1', ''),
            matched_rom=matched,
            forced=d.get('forced', False),
        )


@dataclass
class OrganizationAction:
    """Records an organization action for undo"""
    action_type: str  # 'copy', 'move', or 'extract'
    source: str
    destination: str
    timestamp: str

    def to_dict(self) -> Dict:
        return {
            'action_type': self.action_type,
            'source': self.source,
            'destination': self.destination,
            'timestamp': self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> 'OrganizationAction':
        return cls(
            action_type=d['action_type'],
            source=d['source'],
            destination=d['destination'],
            timestamp=d['timestamp'],
        )


@dataclass
class PlannedAction:
    """A planned (not yet executed) organization action"""
    source: str
    destination: str
    action_type: str  # 'copy', 'move', 'extract'


@dataclass
class OrganizationPlan:
    """Preview of what an organization operation would do"""
    strategy_description: str
    actions: List[PlannedAction] = field(default_factory=list)
    total_files: int = 0
    total_size: int = 0


@dataclass
class Collection:
    """A saved collection/session"""
    name: str
    created_at: str = ""
    updated_at: str = ""
    dat_infos: List[DATInfo] = field(default_factory=list)
    dat_filepaths: List[str] = field(default_factory=list)
    scan_folder: str = ""
    scan_options: Dict[str, bool] = field(default_factory=dict)
    identified: List[Dict] = field(default_factory=list)
    unidentified: List[Dict] = field(default_factory=list)
    settings: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'version': 1,
            'name': self.name,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'dat_infos': [d.to_dict() for d in self.dat_infos],
            'dat_filepaths': self.dat_filepaths,
            'scan_folder': self.scan_folder,
            'scan_options': self.scan_options,
            'identified': self.identified,
            'unidentified': self.unidentified,
            'settings': self.settings,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> 'Collection':
        dat_infos = [DATInfo.from_dict(di) for di in d.get('dat_infos', [])]
        return cls(
            name=d.get('name', 'Unnamed'),
            created_at=d.get('created_at', ''),
            updated_at=d.get('updated_at', ''),
            dat_infos=dat_infos,
            dat_filepaths=d.get('dat_filepaths', []),
            scan_folder=d.get('scan_folder', ''),
            scan_options=d.get('scan_options', {}),
            identified=d.get('identified', []),
            unidentified=d.get('unidentified', []),
            settings=d.get('settings', {}),
        )
