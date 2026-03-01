"""
ROM organizer - organizes ROMs according to different strategies
"""

import os
import re
import shutil
import zipfile
from abc import ABC, abstractmethod
from datetime import datetime
import json
from typing import Dict, List, Optional, Callable, Any

from .models import ScannedFile, ROMInfo, OrganizationAction, PlannedAction, OrganizationPlan
from .shared_config import LOGS_DIR

_SELECTION_POLICY: Dict[str, Any] = {
    "global_priority": [
        "USA", "World", "Europe", "Japan", "Brazil", "Korea", "China",
        "Germany", "France", "Spain", "Italy", "Australia", "Asia",
        "Netherlands", "Sweden", "Russia", "Unknown"
    ],
    "per_system": {},
    "allow_tags": [],
    "exclude_tags": [],
}

_NAMING_TEMPLATE = "{name}"
_KEEP_NAME_TAGS = True
_AUDIT_PATH = os.path.join(LOGS_DIR, "audit.log")
_AUDIT_ENABLED = True


def configure_selection_policy(policy: Dict[str, Any] | None):
    global _SELECTION_POLICY
    if policy:
        _SELECTION_POLICY.update({k: v for k, v in policy.items() if v is not None})


def configure_naming(template: str | None = None, keep_tags: bool | None = None):
    global _NAMING_TEMPLATE, _KEEP_NAME_TAGS
    if template:
        _NAMING_TEMPLATE = template
    if keep_tags is not None:
        _KEEP_NAME_TAGS = bool(keep_tags)


def configure_audit(path: str | None = None, enabled: bool | None = None):
    global _AUDIT_PATH, _AUDIT_ENABLED
    if path:
        _AUDIT_PATH = path
    if enabled is not None:
        _AUDIT_ENABLED = bool(enabled)


def _strip_tags(name: str) -> str:
    name = re.sub(r"\s*\([^)]*\)", "", name)
    name = re.sub(r"\s*\[[^\]]*\]", "", name)
    return re.sub(r"\s{2,}", " ", name).strip()


def render_name_template(scanned: ScannedFile) -> str:
    rom = scanned.matched_rom
    raw_name = rom.name if rom else scanned.filename
    game = (rom.game_name if rom and rom.game_name else os.path.splitext(scanned.filename)[0])
    if not _KEEP_NAME_TAGS:
        game = _strip_tags(game)
    values = {
        "name": raw_name,
        "game": game,
        "region": (rom.region if rom else "Unknown"),
        "system": (rom.system_name if rom else "Unknown"),
        "crc": (rom.crc32 if rom else scanned.crc32),
    }
    try:
        return _NAMING_TEMPLATE.format(**values)
    except Exception:
        return raw_name




# ── Path safety (Windows-safe) ───────────────────────────────────

_WINDOWS_UNSAFE_RE = re.compile(r'[<>:"/\\|?*]')
# Windows reserved device names (case-insensitive) cannot be used as bare filenames
_WINDOWS_RESERVED_NAMES = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}


def _sanitize_component(part: str) -> str:
    """Return a filesystem-safe single path component.

    - Replaces Windows-unsafe characters with '_'
    - Trims trailing dots/spaces (Windows restriction)
    - Guards against reserved device names (CON, PRN, ...)
    """
    part = (part or '').strip()
    if part in {'.', '..'}:
        part = '_' + part.replace('.', '')
    part = _WINDOWS_UNSAFE_RE.sub('_', part)
    # Windows forbids trailing dots/spaces
    part = part.rstrip(' .')
    if not part:
        part = '_'
    upper = part.upper()
    if upper in _WINDOWS_RESERVED_NAMES:
        part = f'_{part}_'
    return part


def _sanitize_rel_path(rel_path: str) -> str:
    """Sanitize a relative path (dirs + filename) without touching output_dir."""
    raw = (rel_path or '').strip().lstrip('/\\')
    if not raw:
        return '_'
    parts = [p for p in re.split(r"[\\/]+", raw) if p]
    if not parts:
        return '_'
    safe_parts = []
    for p in parts[:-1]:
        safe_parts.append(_sanitize_component(p))
    filename = parts[-1]
    base, ext = os.path.splitext(filename)
    safe_base = _sanitize_component(base)
    safe_parts.append(f"{safe_base}{ext}")
    return os.path.join(*safe_parts) if safe_parts else '_'


def _emit_progress(cb, current: int, total: int, filename: str) -> None:
    if not cb:
        return
    try:
        cb(current, total, filename)
        return
    except TypeError:
        # Backward compatibility for callbacks that accept only (current, total)
        try:
            cb(current, total)
        except TypeError:
            return


def build_destination_path(output_dir: str, strat: 'OrganizationStrategy', scanned: ScannedFile) -> str:
    """Build a sanitized destination path for a scanned file.

    CRITICAL: This is used by both preview() and organize() so preview mirrors execution.
    """
    rel_path = strat.get_relative_path(scanned)
    rel_dir = os.path.dirname(rel_path)

    rendered_name = render_name_template(scanned)
    if os.path.splitext(rendered_name)[1] == "":
        ext = os.path.splitext(os.path.basename(rel_path))[1]
        rendered_name = f"{rendered_name}{ext}" if ext else rendered_name

    rel_path = os.path.join(rel_dir, rendered_name) if rel_dir else rendered_name
    rel_path = _sanitize_rel_path(rel_path)
    return os.path.join(output_dir, rel_path)


# ── Strategy Pattern ──────────────────────────────────────────────

class OrganizationStrategy(ABC):
    """Base class for organization strategies."""

    @abstractmethod
    def get_relative_path(self, scanned: ScannedFile) -> str:
        """Return the relative destination path for a file."""

    def filter_files(self, files: List[ScannedFile]) -> List[ScannedFile]:
        """Filter/select files for this strategy. Default: no filtering."""
        return files


class OneGameOneROMStrategy(OrganizationStrategy):
    """Keep best version per game based on region priority."""


    def get_relative_path(self, scanned: ScannedFile) -> str:
        rom = scanned.matched_rom
        return rom.name if rom else scanned.filename

    def filter_files(self, files: List[ScannedFile]) -> List[ScannedFile]:
        games: Dict[str, List[ScannedFile]] = {}
        for f in files:
            if f.matched_rom:
                base = self._get_base_name(f.matched_rom.game_name)
                if base not in games:
                    games[base] = []
                games[base].append(f)

        selected = []
        for versions in games.values():
            best = min(versions, key=lambda x: self._get_priority(
                x.matched_rom.region if x.matched_rom else 'Unknown',
                x.matched_rom.system_name if x.matched_rom else ""))
            selected.append(best)
        return selected

    def _get_base_name(self, name: str) -> str:
        base = re.sub(r'\s*\([^)]*\)', '', name)
        base = re.sub(r'\s*\[[^\]]*\]', '', base)
        return base.strip()

    def _get_priority(self, region: str, system_name: str = "") -> int:
        per_system = _SELECTION_POLICY.get("per_system", {}) or {}
        region_priority = per_system.get(system_name, _SELECTION_POLICY.get("global_priority", []))
        try:
            return region_priority.index(region)
        except ValueError:
            return len(region_priority)


class RegionStrategy(OrganizationStrategy):
    """Organize into region folders."""

    def get_relative_path(self, scanned: ScannedFile) -> str:
        rom = scanned.matched_rom
        region = rom.region if rom else 'Unknown'
        name = rom.name if rom else scanned.filename
        return os.path.join(region, name)


class AlphabeticalStrategy(OrganizationStrategy):
    """Organize into A-Z folders."""

    def get_relative_path(self, scanned: ScannedFile) -> str:
        rom = scanned.matched_rom
        game_name = rom.game_name if rom and rom.game_name else scanned.filename
        name = rom.name if rom else scanned.filename
        first_char = game_name[0].upper() if game_name else '#'
        if not first_char.isalpha():
            first_char = '#'
        return os.path.join(first_char, name)


class EmulationStationStrategy(OrganizationStrategy):
    """Flat structure compatible with EmulationStation/RetroPie."""

    def get_relative_path(self, scanned: ScannedFile) -> str:
        rom = scanned.matched_rom
        return rom.name if rom else scanned.filename


class FlatStrategy(OrganizationStrategy):
    """Rename files with proper names, no subfolders."""

    def get_relative_path(self, scanned: ScannedFile) -> str:
        rom = scanned.matched_rom
        return rom.name if rom else scanned.filename


class EverDriveStrategy(OrganizationStrategy):
    """Organize into A-Z chunks to respect folder limits (Max 250 per folder)."""
    
    def __init__(self):
        super().__init__()
        self.max_files = 250
        self._path_map = {}

    def filter_files(self, files: List[ScannedFile]) -> List[ScannedFile]:
        self._path_map.clear()
        
        # Sort files by game name
        def get_sort_key(f: ScannedFile) -> str:
            rom = f.matched_rom
            return (rom.game_name if rom and rom.game_name else f.filename).upper()
            
        sorted_files = sorted(files, key=get_sort_key)
        
        for i in range(0, len(sorted_files), self.max_files):
            chunk = sorted_files[i:i+self.max_files]
            if not chunk:
                continue
                
            first_name = get_sort_key(chunk[0])
            last_name = get_sort_key(chunk[-1])
            first_char = first_name[0] if first_name else '#'
            last_char = last_name[0] if last_name else '#'
            
            if not first_char.isalnum(): first_char = '#'
            if not last_char.isalnum(): last_char = '#'
            
            folder_name = f"{first_char} - {last_char}" if first_char != last_char else first_char
            
            # handle cases where multiple chunks end up with same name (e.g. lots of S games)
            # just append a chunk index
            chunk_idx = (i // self.max_files) + 1
            if len(sorted_files) > self.max_files:
                folder_name = f"{chunk_idx:02d} ({folder_name})"
                
            for f in chunk:
                rom = f.matched_rom
                name = rom.name if rom else f.filename
                self._path_map[f.path] = os.path.join(folder_name, name)
                
        return files

    def get_relative_path(self, scanned: ScannedFile) -> str:
        return self._path_map.get(scanned.path, scanned.filename)

class SystemStrategy(OrganizationStrategy):
    """Organize into per-system subfolders based on DAT provenance."""

    def get_relative_path(self, scanned: ScannedFile) -> str:
        rom = scanned.matched_rom
        system = rom.system_name if rom and rom.system_name else 'Unknown'
        name = rom.name if rom else scanned.filename
        return os.path.join(system, name)




class MuseumStrategy(OrganizationStrategy):
    """Organize by preservation-themed hierarchy."""

    def get_relative_path(self, scanned: ScannedFile) -> str:
        rom = scanned.matched_rom
        system = (rom.system_name if rom and rom.system_name else "Unknown System")
        region = (rom.region if rom and rom.region else "Unknown")
        generation = "Unknown Era"
        s = system.lower()
        if any(k in s for k in ["nes", "master system", "2600"]):
            generation = "3rd Gen"
        elif any(k in s for k in ["snes", "genesis", "mega drive", "pc engine"]):
            generation = "4th Gen"
        elif any(k in s for k in ["n64", "playstation", "saturn"]):
            generation = "5th Gen"
        name = rom.name if rom else scanned.filename
        return os.path.join(generation, system, region, name)

class CompositeStrategy(OrganizationStrategy):
    """Chain multiple strategies. Each contributes a directory level."""

    def __init__(self, strategies: List[OrganizationStrategy]):
        if not strategies:
            raise ValueError("CompositeStrategy needs at least one strategy")
        self.strategies = strategies

    def get_relative_path(self, scanned: ScannedFile) -> str:
        parts = []
        for strategy in self.strategies:
            rel = strategy.get_relative_path(scanned)
            dir_part = os.path.dirname(rel)
            if dir_part:
                parts.append(dir_part)
        # Filename from the last strategy
        filename = os.path.basename(self.strategies[-1].get_relative_path(scanned))
        if parts:
            return os.path.join(*parts, filename)
        return filename

    def filter_files(self, files: List[ScannedFile]) -> List[ScannedFile]:
        result = files
        for strategy in self.strategies:
            result = strategy.filter_files(result)
        return result


# ── Strategy Registry ─────────────────────────────────────────────

STRATEGY_MAP = {
    '1g1r': OneGameOneROMStrategy,
    'region': RegionStrategy,
    'alphabetical': AlphabeticalStrategy,
    'everdrive': EverDriveStrategy,
    'emulationstation': EmulationStationStrategy,
    'flat': FlatStrategy,
    'system': SystemStrategy,
    'museum': MuseumStrategy,
}


def build_strategy(name: str) -> OrganizationStrategy:
    """Build a strategy from a string name. Supports '+' for composites."""
    if '+' in name:
        parts = [p.strip() for p in name.split('+')]
        strategies = []
        for part in parts:
            cls = STRATEGY_MAP.get(part)
            if not cls:
                raise ValueError(f"Unknown strategy: {part}")
            strategies.append(cls())
        return CompositeStrategy(strategies)
    else:
        cls = STRATEGY_MAP.get(name)
        if not cls:
            raise ValueError(f"Unknown strategy: {name}")
        return cls()


# ── Organizer ─────────────────────────────────────────────────────

class Organizer:
    """
    Organizes ROMs according to different strategies.
    """

    # Available strategies (for backward compat and UI listing)
    STRATEGIES = {
        'system': 'By System - Per-system folders (multi-DAT)',
        '1g1r': 'One Game, One ROM - Keep best version per game',
        'region': 'By Region - Organize into region folders',
        'alphabetical': 'Alphabetical - Organize into A-Z folders',
        'everdrive': 'A-Z Split (EverDrive) - Max 250 files per folder',
        'emulationstation': 'EmulationStation - Flat structure for ES/RetroPie',
        'flat': 'Flat - Rename to proper names, no subfolders',
        'museum': 'Museum - Generation/System/Region hierarchy',
    }

    # Region priority for 1G1R (lower = better) - kept for backward compat
    REGION_PRIORITY = _SELECTION_POLICY.get("global_priority", [])

    def __init__(self):
        """Initialize organizer with empty history"""
        self.history: List[OrganizationAction] = []

    def organize(self, files: List[ScannedFile], output_dir: str,
                 strategy: str, action: str = 'copy',
                 progress_callback: Optional[Callable[[int, int], None]] = None
                 ) -> List[OrganizationAction]:
        """
        Organize files according to strategy.

        Args:
            files: List of ScannedFile with matched_rom
            output_dir: Output directory
            strategy: Organization strategy name (supports '+' for composites)
            action: 'copy' or 'move'
            progress_callback: Optional callback(current, total)

        Returns:
            List of performed actions
        """
        matched_files = [f for f in files if f.matched_rom is not None]
        if not matched_files:
            return []

        os.makedirs(output_dir, exist_ok=True)

        strat = build_strategy(strategy)
        to_process = strat.filter_files(matched_files)

        actions = []
        errors: List[Dict[str, str]] = []
        total = len(to_process)

        for i, scanned in enumerate(to_process):
            dest = build_destination_path(output_dir, strat, scanned)
            _emit_progress(progress_callback, i + 1, total, os.path.basename(dest))

            try:
                action_record = self._perform_action(scanned.path, dest, action)
                actions.append(action_record)
            except Exception as exc:
                errors.append({"source": scanned.path, "destination": dest, "error": str(exc)})

            _emit_progress(progress_callback, i + 1, total, os.path.basename(dest))

        if not actions and errors:
            # If we had matches but every file op failed, surface a useful error
            raise RuntimeError(errors[0].get("error") or "organization failed")

        self.history.extend(actions)
        self._generate_m3u_playlists(actions)
        return actions

    def _generate_m3u_playlists(self, actions: List[OrganizationAction]) -> None:
        """Finds multi-disc games inside the output folders and generates M3U files."""
        import re
        import collections

        # Group by output directory
        dirs = collections.defaultdict(list)
        for act in actions:
            dest = act.destination
            if os.path.isfile(dest):
                d = os.path.dirname(dest)
                dirs[d].append(os.path.basename(dest))

        # Regex to detect disc numbers like (Disc 1), (Disc 2), (Disc A), (Disc I)
        disc_re = re.compile(r'(?i)\(Disc\s*([0-9a-z]+)\)')
        
        for d, files in dirs.items():
            # Group by base name without the (Disc X)
            games = collections.defaultdict(list)
            for f in files:
                # ignore already created m3u
                if f.lower().endswith('.m3u'):
                    continue
                match = disc_re.search(f)
                if match:
                    # e.g., "Final Fantasy VII (USA) (Disc 1).chd" -> "Final Fantasy VII (USA)"
                    base = f[:match.start()].strip() + f[match.end():]
                    # remove extension from base
                    base, _ = os.path.splitext(base)
                    base = base.strip()
                    games[base].append(f)

            # Generate M3U
            for base, discs in games.items():
                if len(discs) > 1:
                    discs.sort()
                    m3u_path = os.path.join(d, f"{base}.m3u")
                    try:
                        with open(m3u_path, 'w', encoding='utf-8') as f_out:
                            for disc in discs:
                                f_out.write(f"{disc}\n")
                    except Exception:
                        pass

    def preview(self, files: List[ScannedFile], output_dir: str,
                strategy: str, action: str = 'copy') -> OrganizationPlan:
        """
        Generate a preview of what organization would do, without executing.

        Returns:
            OrganizationPlan with planned actions.
        """
        matched_files = [f for f in files if f.matched_rom is not None]
        if not matched_files:
            return OrganizationPlan(strategy_description=strategy)

        strat = build_strategy(strategy)
        to_process = strat.filter_files(matched_files)

        planned = []
        total_size = 0

        for scanned in to_process:
            dest = build_destination_path(output_dir, strat, scanned)

            act_type = action
            if '|' in scanned.path:
                act_type = 'extract'

            planned.append(PlannedAction(
                source=scanned.path,
                destination=dest,
                action_type=act_type,
            ))
            total_size += scanned.size

        desc = self.STRATEGIES.get(strategy, strategy)
        return OrganizationPlan(
            strategy_description=desc,
            actions=planned,
            total_files=len(planned),
            total_size=total_size,
        )

    def _perform_action(self, source: str, dest: str,
                       action: str) -> OrganizationAction:
        """Perform copy, move, or extract action"""
        dest_dir = os.path.dirname(dest)
        if dest_dir:
            os.makedirs(dest_dir, exist_ok=True)

        timestamp = datetime.now().isoformat()

        if '|' in source:
            archive_path, internal_path = source.split('|', 1)
            with zipfile.ZipFile(archive_path, 'r') as zf:
                with zf.open(internal_path) as src:
                    with open(dest, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
            action_type = 'extract'
        elif action == 'copy':
            shutil.copy2(source, dest)
            action_type = 'copy'
        elif action == 'hardlink':
            os.link(source, dest)
            action_type = 'hardlink'
        elif action == 'symlink':
            os.symlink(source, dest)
            action_type = 'symlink'
        else:
            shutil.move(source, dest)
            action_type = 'move'

        action_obj = OrganizationAction(
            action_type=action_type,
            source=source,
            destination=dest,
            timestamp=timestamp
        )
        if _AUDIT_ENABLED:
            try:
                os.makedirs(os.path.dirname(_AUDIT_PATH), exist_ok=True)
                with open(_AUDIT_PATH, "a", encoding="utf-8") as af:
                    af.write(json.dumps({
                        "timestamp": timestamp,
                        "action": action_type,
                        "source": source,
                        "destination": dest,
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass
        return action_obj

    def undo_last(self) -> bool:
        """Undo the last batch of actions."""
        if not self.history:
            return False

        last_time = self.history[-1].timestamp
        to_undo = []

        while self.history and self.history[-1].timestamp == last_time:
            to_undo.append(self.history.pop())

        for action in to_undo:
            try:
                if action.action_type in ('copy', 'extract'):
                    if os.path.exists(action.destination):
                        os.remove(action.destination)
                        self._remove_empty_dirs(os.path.dirname(action.destination))
                elif action.action_type == 'move':
                    if os.path.exists(action.destination):
                        src_dir = os.path.dirname(action.source)
                        if src_dir:
                            os.makedirs(src_dir, exist_ok=True)
                        shutil.move(action.destination, action.source)
                        self._remove_empty_dirs(os.path.dirname(action.destination))
            except Exception:
                pass

        return True

    def _remove_empty_dirs(self, path: str):
        """Remove empty directories recursively"""
        try:
            while path:
                if os.path.isdir(path) and not os.listdir(path):
                    os.rmdir(path)
                    path = os.path.dirname(path)
                else:
                    break
        except Exception:
            pass

    def get_history_count(self) -> int:
        """Get number of actions in history"""
        return len(self.history)

    def clear_history(self):
        """Clear action history"""
        self.history.clear()
