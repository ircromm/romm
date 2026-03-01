"""Automatic scraper/downloader pipeline with retry and progress callbacks."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional

from .downloader import ArchiveOrgDownloader
from .models import ROMInfo

LOG = logging.getLogger(__name__)


@dataclass
class DownloadTaskState:
    task_id: str
    status: str = "queued"
    progress: int = 0
    message: str = "Queued"
    destination: str = ""
    error: str = ""
    rom_name: str = ""


class AutoScraperDownloader:
    """Finds and downloads ROM files with minimal user input."""

    def __init__(self, output_root: Optional[str] = None, retries: int = 3, timeout_s: int = 30):
        from .shared_config import APP_DATA_DIR

        self.output_root = output_root or os.path.join(APP_DATA_DIR, "auto_downloads")
        self.retries = max(1, retries)
        self.downloader = ArchiveOrgDownloader()
        self.downloader.timeout = timeout_s

    def download_rom(
        self,
        rom: ROMInfo,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> str:
        """Download ROM and place it in inferred final folder."""

        def emit(pct: int, msg: str):
            if progress_callback:
                progress_callback(max(0, min(100, pct)), msg)

        emit(2, "Searching mirror")
        item = self._find_best_item(rom)
        if not item:
            raise RuntimeError("No downloadable source found")

        emit(10, "Fetching file list")
        target_file = self._pick_best_file(item["identifier"], rom)
        if not target_file:
            raise RuntimeError("No matching file found in source item")

        tmp_dir = tempfile.mkdtemp(prefix="romm_auto_")
        try:
            emit(20, "Downloading")

            def raw_progress(done: int, total: int):
                if total <= 0:
                    emit(40, "Downloading")
                else:
                    pct = 20 + int((done / total) * 60)
                    emit(pct, f"Downloading {int((done / total) * 100)}%")

            downloaded = self._retry_download(
                target_file["download_url"],
                tmp_dir,
                target_file["name"],
                raw_progress,
            )

            emit(84, "Preparing file")
            prepared = self._prepare_file(downloaded, rom)

            system_folder = rom.system_name.strip() or "Unknown"
            final_dir = os.path.join(self.output_root, system_folder)
            os.makedirs(final_dir, exist_ok=True)

            final_name = rom.name.strip() or os.path.basename(prepared)
            final_path = os.path.join(final_dir, final_name)
            shutil.move(prepared, final_path)
            emit(100, "Installed")
            return final_path
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _find_best_item(self, rom: ROMInfo) -> Optional[Dict]:
        candidates = []
        if rom.sha1 or rom.md5 or rom.crc32:
            candidates.extend(self.downloader.search_by_hash(rom.crc32, rom.md5, rom.sha1, max_results=5))

        if not candidates:
            search_term = rom.game_name or Path(rom.name).stem
            search_term = search_term.split("(")[0].strip()
            candidates.extend(self.downloader.search(search_term, rom.system_name, max_results=8))

        filtered = [c for c in candidates if "identifier" in c]
        if not filtered:
            return None

        return sorted(filtered, key=lambda c: len((c.get("title") or "")))[0]

    def _pick_best_file(self, identifier: str, rom: ROMInfo) -> Optional[Dict]:
        files = self.downloader.get_item_files(identifier)
        if not files:
            return None

        wanted = rom.name.lower()
        expected_crc = (rom.crc32 or "").lower()

        scored = []
        for f in files:
            name = f.get("name", "").lower()
            score = 0
            if name == wanted:
                score += 100
            if wanted and wanted in name:
                score += 60
            if expected_crc and expected_crc in name:
                score += 25
            if name.endswith((".zip", ".7z")):
                score += 5
            if f.get("size"):
                score += 1
            scored.append((score, f))

        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best_file = scored[0]
        if best_score <= 0:
            return None
        return best_file

    def _retry_download(self, url: str, dest_folder: str, filename: str, progress_cb):
        last_exc = None
        for attempt in range(1, self.retries + 1):
            try:
                return self.downloader.download(url, dest_folder, filename=filename, progress_callback=progress_cb)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                LOG.warning("Download retry %s/%s failed: %s", attempt, self.retries, exc)
                time.sleep(min(2 * attempt, 5))
        raise RuntimeError(f"Download failed after retries: {last_exc}")

    def _prepare_file(self, source_path: str, rom: ROMInfo) -> str:
        if source_path.lower().endswith(".zip"):
            with zipfile.ZipFile(source_path, "r") as zf:
                members = [m for m in zf.namelist() if not m.endswith("/")]
                if not members:
                    raise RuntimeError("Archive has no files")
                preferred = self._pick_member(members, rom)
                target_path = os.path.join(os.path.dirname(source_path), os.path.basename(preferred))
                with zf.open(preferred) as src, open(target_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                return target_path
        return source_path

    @staticmethod
    def _pick_member(members, rom: ROMInfo) -> str:
        wanted = rom.name.lower()
        for m in members:
            if os.path.basename(m).lower() == wanted:
                return m
        return members[0]


class AutoDownloadTaskRegistry:
    """Background task executor for Flask and UI polling."""

    def __init__(self, engine: Optional[AutoScraperDownloader] = None):
        self.engine = engine or AutoScraperDownloader()
        self._tasks: Dict[str, DownloadTaskState] = {}
        self._lock = threading.Lock()

    def start(self, rom: ROMInfo) -> str:
        task_id = uuid.uuid4().hex
        task = DownloadTaskState(task_id=task_id, rom_name=rom.name)
        with self._lock:
            self._tasks[task_id] = task

        thread = threading.Thread(target=self._run_task, args=(task_id, rom), daemon=True)
        thread.start()
        return task_id

    def get(self, task_id: str) -> Optional[DownloadTaskState]:
        with self._lock:
            return self._tasks.get(task_id)

    def _run_task(self, task_id: str, rom: ROMInfo):
        task = self.get(task_id)
        if not task:
            return

        def update(pct: int, msg: str):
            with self._lock:
                task.progress = pct
                task.message = msg
                if pct > 0:
                    task.status = "running"

        try:
            final_path = self.engine.download_rom(rom, progress_callback=update)
            with self._lock:
                task.status = "done"
                task.progress = 100
                task.message = "Installed"
                task.destination = final_path
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Auto-download failed for %s", rom.name)
            with self._lock:
                task.status = "failed"
                task.error = str(exc)
                task.message = "Failed"

