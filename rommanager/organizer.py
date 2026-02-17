"""
ROM organizer - organizes ROMs according to different strategies
"""

import os
import re
import shutil
import zipfile
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, Callable

from .models import ScannedFile, ROMInfo, OrganizationAction, PlannedAction, OrganizationPlan
from .monitor import monitor


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

    REGION_PRIORITY = [
        'USA', 'World', 'Europe', 'Japan', 'Brazil', 'Korea', 'China',
        'Germany', 'France', 'Spain', 'Italy', 'Australia', 'Asia',
        'Netherlands', 'Sweden', 'Russia', 'Unknown'
    ]

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
                x.matched_rom.region if x.matched_rom else 'Unknown'))
            selected.append(best)
        return selected

    def _get_base_name(self, name: str) -> str:
        base = re.sub(r'\s*\([^)]*\)', '', name)
        base = re.sub(r'\s*\[[^\]]*\]', '', base)
        return base.strip()

    def _get_priority(self, region: str) -> int:
        try:
            return self.REGION_PRIORITY.index(region)
        except ValueError:
            return len(self.REGION_PRIORITY)


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


class SystemStrategy(OrganizationStrategy):
    """Organize into per-system subfolders based on DAT provenance."""

    def get_relative_path(self, scanned: ScannedFile) -> str:
        rom = scanned.matched_rom
        system = rom.system_name if rom and rom.system_name else 'Unknown'
        name = rom.name if rom else scanned.filename
        return os.path.join(system, name)


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
    'emulationstation': EmulationStationStrategy,
    'flat': FlatStrategy,
    'system': SystemStrategy,
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
        'emulationstation': 'EmulationStation - Flat structure for ES/RetroPie',
        'flat': 'Flat - Rename to proper names, no subfolders',
    }

    # Region priority for 1G1R (lower = better) - kept for backward compat
    REGION_PRIORITY = OneGameOneROMStrategy.REGION_PRIORITY

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
        monitor.info('organizer', f'Start organize: strategy={strategy}, action={action}, total_input={len(files)}')
        matched_files = [f for f in files if f.matched_rom is not None]
        if not matched_files:
            return []

        os.makedirs(output_dir, exist_ok=True)

        strat = build_strategy(strategy)
        to_process = strat.filter_files(matched_files)

        actions = []
        total = len(to_process)

        for i, scanned in enumerate(to_process):
            rel_path = strat.get_relative_path(scanned)
            dest = os.path.join(output_dir, rel_path)

            try:
                action_record = self._perform_action(scanned.path, dest, action)
                actions.append(action_record)
            except Exception as e:
                monitor.error('organizer', f'Failed {action} for {scanned.path} -> {dest}: {e}')

            if progress_callback:
                progress_callback(i + 1, total)

        self.history.extend(actions)
        monitor.info('organizer', f'Organize finished: {len(actions)} actions completed')
        return actions

    def preview(self, files: List[ScannedFile], output_dir: str,
                strategy: str, action: str = 'copy') -> OrganizationPlan:
        """
        Generate a preview of what organization would do, without executing.

        Returns:
            OrganizationPlan with planned actions.
        """
        monitor.info('organizer', f'Preview organize: strategy={strategy}, action={action}, total_input={len(files)}')
        matched_files = [f for f in files if f.matched_rom is not None]
        if not matched_files:
            return OrganizationPlan(strategy_description=strategy)

        strat = build_strategy(strategy)
        to_process = strat.filter_files(matched_files)

        planned = []
        total_size = 0

        for scanned in to_process:
            rel_path = strat.get_relative_path(scanned)
            dest = os.path.join(output_dir, rel_path)

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
        else:
            shutil.move(source, dest)
            action_type = 'move'

        return OrganizationAction(
            action_type=action_type,
            source=source,
            destination=dest,
            timestamp=timestamp
        )

    def undo_last(self) -> bool:
        """Undo the last batch of actions."""
        if not self.history:
            monitor.warning('organizer', 'Undo requested but no history available')
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
            except Exception as e:
                monitor.error('organizer', f'Failed undo action {action.action_type} {action.destination}: {e}')

        monitor.info('organizer', f'Undo finished: {len(to_undo)} actions reverted')
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
