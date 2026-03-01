from __future__ import annotations

from copy import deepcopy
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6 import QtCore

from .core_service import CoreService
from .monitor import monitor_action
from . import i18n as _i18n


LANG_EN = getattr(_i18n, "LANG_EN", "en")
LANG_PT_BR = getattr(_i18n, "LANG_PT_BR", "pt-BR")


def _tr(key: str, **kwargs: Any) -> str:
    func = getattr(_i18n, "tr", None)
    if callable(func):
        return func(key, **kwargs)
    return key


class ScanWorker(QtCore.QObject):
    progress = QtCore.Signal(int, int)
    finished = QtCore.Signal(dict)
    failed = QtCore.Signal(str)

    def __init__(self, core: CoreService, folder: str, recursive: bool, scan_archives: bool, blindmatch: str):
        super().__init__()
        self._core = core
        self._folder = folder
        self._recursive = recursive
        self._scan_archives = scan_archives
        self._blindmatch = blindmatch

    @QtCore.Slot()
    def run(self) -> None:
        try:
            def _progress(current: int, total: int) -> None:
                self.progress.emit(current, total)

            res = self._core.scan_sync(
                folder=self._folder,
                recursive=self._recursive,
                scan_archives=self._scan_archives,
                blindmatch_system=self._blindmatch,
                progress_callback=_progress,
            )
            self.finished.emit(res)
        except Exception as exc:
            self.failed.emit(str(exc))


class OrganizeWorker(QtCore.QObject):
    progress = QtCore.Signal(int, int, str)
    finished = QtCore.Signal(dict)
    failed = QtCore.Signal(str)

    def __init__(self, core: CoreService, output: str, strategy: str, action: str, is_unidentified: bool = False):
        super().__init__()
        self._core = core
        self._output = output
        self._strategy = strategy
        self._action = action
        self._is_unidentified = is_unidentified

    @QtCore.Slot()
    def run(self) -> None:
        try:
            def _progress(current: int, total: int, filename: str = "") -> None:
                self.progress.emit(current, total, filename)

            if self._is_unidentified:
                res = self._core.organize_unidentified(
                    output=self._output,
                    action=self._action,
                    progress_callback=_progress,
                )
            else:
                res = self._core.organize(
                    output=self._output,
                    strategy=self._strategy,
                    action=self._action,
                    progress_callback=_progress,
                )
            self.finished.emit(res)
        except Exception as exc:
            self.failed.emit(str(exc))


class ToolWorker(QtCore.QObject):
    finished = QtCore.Signal(dict)
    failed = QtCore.Signal(str)
    progress = QtCore.Signal(int, int, str)

    def __init__(self, func, args, progress_callback=None):
        super().__init__()
        self._func = func
        self._args = args
        self._progress_callback = progress_callback

    @QtCore.Slot()
    def run(self) -> None:
        try:
            if self._progress_callback:
                res = self._func(*self._args, progress_callback=self._progress_callback)
            else:
                res = self._func(*self._args)
            self.finished.emit(res)
        except Exception as exc:
            self.failed.emit(str(exc))


class AppState(QtCore.QObject):
    status_changed = QtCore.Signal(dict)
    results_changed = QtCore.Signal(dict)
    missing_changed = QtCore.Signal(dict)
    collections_changed = QtCore.Signal(list)
    recent_collections_changed = QtCore.Signal(list)
    dat_library_changed = QtCore.Signal(list)
    dat_sources_changed = QtCore.Signal(list)
    dat_downloader_catalog_done = QtCore.Signal(dict)
    dat_downloader_download_done = QtCore.Signal(dict)
    error_changed = QtCore.Signal(str)
    locale_changed = QtCore.Signal(str)
    scan_progress = QtCore.Signal(int, int)
    organize_progress = QtCore.Signal(int, int, str)
    organize_finished = QtCore.Signal(dict)
    organize_failed = QtCore.Signal(str)
    download_progress = QtCore.Signal(str, float, str, str)  # filename, percent, speed, status
    jdownloader_handoff_progress = QtCore.Signal(bool, int, str)  # active, percent, phase
    jdownloader_queue_finished = QtCore.Signal(dict)
    myrient_directory_listed = QtCore.Signal(dict)
    myrient_links_resolved = QtCore.Signal(dict)
    download_missing_requested = QtCore.Signal(list)
    log_message = QtCore.Signal(str)
    tool_failed = QtCore.Signal(str)
    tool_progress = QtCore.Signal(str, int, int, str)
    dat_diff_done = QtCore.Signal(dict)
    dat_merge_done = QtCore.Signal(dict)
    batch_convert_done = QtCore.Signal(dict)
    torrentzip_done = QtCore.Signal(dict)
    deep_clean_done = QtCore.Signal(dict)
    find_duplicates_done = QtCore.Signal(dict)
    dashboard_data_ready = QtCore.Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.core = CoreService()
        self.ui_prefs: Dict[str, Any] = {}
        self.status: Dict[str, Any] = {}
        self.results: Dict[str, Any] = {"identified": [], "unidentified": []}
        self.missing: Dict[str, Any] = {"missing": [], "completeness": {}, "completeness_by_dat": {}}
        self.collections: List[Dict[str, Any]] = []
        self.recent_collections: List[Dict[str, Any]] = []
        self.dat_library: List[Dict[str, Any]] = []
        self.dat_sources: List[Dict[str, Any]] = []
        self.dashboard_intel: Dict[str, Any] = {}
        self._scan_thread: Optional[QtCore.QThread] = None
        self._scan_worker: Optional[ScanWorker] = None
        self._organize_thread: Optional[QtCore.QThread] = None
        self._organize_worker: Optional[OrganizeWorker] = None
        self._tool_thread: Optional[QtCore.QThread] = None
        self._dashboard_thread: Optional[QtCore.QThread] = None
        self._dashboard_worker: Optional[ToolWorker] = None
        self._myrient_thread: Optional[QtCore.QThread] = None
        self._myrient_worker: Optional[ToolWorker] = None
        self._dat_thread: Optional[QtCore.QThread] = None
        self._dat_worker: Optional[ToolWorker] = None
        self._jd_queue_thread: Optional[QtCore.QThread] = None
        self._jd_queue_worker: Optional[ToolWorker] = None
        self._myrient_task_queue: List[Dict[str, Any]] = []
        self._dat_task_queue: List[Dict[str, Any]] = []
        self._jd_monitor_lock = threading.Lock()
        self._jd_monitor_items: Dict[str, Dict[str, Any]] = {}
        self._jd_hint_thread: Optional[threading.Thread] = None
        self._jd_monitor_timer = QtCore.QTimer(self)
        self._jd_monitor_timer.setInterval(1000)
        self._jd_monitor_timer.timeout.connect(self._poll_jdownloader_progress)
        self._ui_prefs_dirty = False
        self._ui_prefs_save_timer = QtCore.QTimer(self)
        self._ui_prefs_save_timer.setSingleShot(True)
        self._ui_prefs_save_timer.setInterval(700)
        self._ui_prefs_save_timer.timeout.connect(self._flush_ui_prefs)
        self.last_collection_path: str = ""
        self._scan_live_last_emit_ts: float = 0.0
        self._scan_live_last_emit_count: int = 0
        self._scan_ui_last_emit_ts: float = 0.0
        self._scan_ui_last_emit_count: int = 0
        self._scan_ui_last_phase: str = "idle"
        self.dat_downloader_catalog_done.connect(self._on_dat_downloader_catalog_done)
        self.dat_downloader_download_done.connect(self._on_dat_downloader_download_done)

        try:
            saved_lang = str(self.core.settings.get("language", LANG_EN) or LANG_EN)
            set_lang = getattr(_i18n, "set_language", None)
            if callable(set_lang):
                set_lang(saved_lang)
        except Exception:
            pass
        try:
            self.ui_prefs = self.core.get_pyside6_ui_state()
        except Exception:
            self.ui_prefs = {}

    def t(self, key: str, **kwargs: Any) -> str:
        return _tr(key, **kwargs)

    def set_locale(self, lang: str) -> None:
        func = getattr(_i18n, "set_language", None)
        if callable(func):
            func(lang)
        try:
            self.core.settings["language"] = str(lang or LANG_EN)
            self._ui_prefs_dirty = True
            self._ui_prefs_save_timer.start()
        except Exception:
            pass
        self.locale_changed.emit(lang)

    def get_ui_prefs(self) -> Dict[str, Any]:
        return deepcopy(self.ui_prefs)

    def queue_ui_prefs_save(self, payload: Dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        if payload == self.ui_prefs and not self._ui_prefs_dirty:
            return
        self.ui_prefs = deepcopy(payload)
        self._ui_prefs_dirty = True
        self._ui_prefs_save_timer.start()

    def flush_ui_prefs(self) -> None:
        self._flush_ui_prefs()

    def _flush_ui_prefs(self) -> None:
        if not self._ui_prefs_dirty:
            return
        try:
            self.core.save_pyside6_ui_state(self.ui_prefs)
            self._ui_prefs_dirty = False
        except Exception as exc:
            self.log_message.emit(f"[!] ui_state:save:error {exc}")

    def refresh_all(self) -> None:
        self.refresh_status()
        self.refresh_results()
        self.refresh_missing()
        self.refresh_dashboard_intel()

    def refresh_status(self) -> None:
        self.status = self.core.get_status()
        self.status_changed.emit(self.status)

    def refresh_results(self) -> None:
        self.results = self.core.get_results()
        self.results_changed.emit(self.results)

    def refresh_missing(self) -> None:
        self.missing = self.core.get_missing()
        self.missing_changed.emit(self.missing)

    def new_session(self) -> None:
        self.core.new_session()
        self.core.persist_session()
        self.refresh_all()

    def load_dat(self, filepath: str) -> dict:
        res = self.core.load_dat(filepath)
        if res.get("error"):
            self.error_changed.emit(res["error"])
            return res
        self.core.persist_session()
        self.refresh_all()
        return res

    def remove_dat(self, dat_id: str) -> dict:
        res = self.core.remove_dat(dat_id)
        if res.get("error"):
            self.error_changed.emit(res["error"])
            return res
        self.core.persist_session()
        self.refresh_all()
        return res

    def force_identify(self, paths: List[str]) -> dict:
        res = self.core.force_identify(paths)
        if res.get("error"):
            self.error_changed.emit(res["error"])
            return res
        self.core.persist_session()
        self.refresh_all()
        return res

    def add_unidentified_to_local_dat(self, entries: List[Dict[str, Any]]) -> dict:
        res = self.core.add_unidentified_to_local_dat(entries)
        if res.get("error"):
            self.error_changed.emit(res["error"])
            return res
        self.core.persist_session()
        self.dat_library_list()
        self.refresh_all()
        return res

    def add_to_edit_dat(self, entries: List[Dict[str, Any]], target_dat_id: str) -> dict:
        res = self.core.add_to_edit_dat(entries, target_dat_id)
        if res.get("error"):
            self.error_changed.emit(res["error"])
            return res
        self.core.persist_session()
        self.dat_library_list()
        self.refresh_all()
        return res

    def suggest_local_dat_metadata(self, scan_id: str, limit: int = 8) -> dict:
        return self.core.suggest_local_dat_metadata(scan_id, limit=limit)

    def fetch_online_metadata_hints(self, query: str, system: str = "", limit: int = 6) -> dict:
        return self.core.fetch_online_metadata_hints(query, system=system, limit=limit)

    def start_scan(self, folder: str, recursive: bool, scan_archives: bool, blindmatch: str) -> None:
        if self._scan_thread and self._scan_thread.isRunning():
            return
        monitor_action(f"[!] scan:start folder={folder}")
        # Emit immediate scan-running status so Nerve Center shows activity before first file callback.
        self.core.scanning = True
        self.core.scan_progress = 0
        self.core.scan_total = 0
        self.core.scan_phase = "scan"
        self.results = {"identified": [], "unidentified": []}
        self.results_changed.emit(self.results)
        self._scan_live_last_emit_ts = 0.0
        self._scan_live_last_emit_count = 0
        self._scan_ui_last_emit_ts = 0.0
        self._scan_ui_last_emit_count = 0
        self._scan_ui_last_phase = "scan"
        self.status = self.core.get_status()
        self.status_changed.emit(self.status)
        self.scan_progress.emit(0, 0)
        self._scan_thread = QtCore.QThread()
        worker = ScanWorker(self.core, folder, recursive, scan_archives, blindmatch)
        self._scan_worker = worker
        worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(worker.run)
        worker.progress.connect(self._on_scan_progress)
        worker.finished.connect(self._on_scan_finished)
        worker.failed.connect(self._on_scan_failed)
        worker.finished.connect(self._scan_thread.quit)
        worker.failed.connect(self._scan_thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.start()

    def _on_scan_progress(self, current: int, total: int) -> None:
        self.core.scan_progress = current
        self.core.scan_total = total
        status = self.core.get_status()
        phase = str(status.get("scan_phase", "") or "").strip().lower()
        safe_current = max(0, int(current or 0))
        safe_total = max(0, int(total or 0))
        now = time.monotonic()

        if phase != self._scan_ui_last_phase:
            self._scan_ui_last_phase = phase
            self._scan_ui_last_emit_count = 0
            self._scan_ui_last_emit_ts = 0.0

        if phase == "compare":
            ui_step_threshold = 120 if safe_total <= 5000 else 500
            ui_time_threshold = 0.80 if safe_total <= 5000 else 1.50
        else:
            ui_step_threshold = 50 if safe_total <= 5000 else 200
            ui_time_threshold = 0.25 if safe_total <= 5000 else 0.60

        should_emit_ui = False
        if safe_current in (0, 1):
            should_emit_ui = True
        if safe_total and safe_current >= safe_total:
            should_emit_ui = True
        if (safe_current - self._scan_ui_last_emit_count) >= ui_step_threshold:
            should_emit_ui = True
        if (now - self._scan_ui_last_emit_ts) >= ui_time_threshold:
            should_emit_ui = True

        if should_emit_ui:
            self.status = status
            self.status_changed.emit(status)
            self.scan_progress.emit(current, total)
            self._scan_ui_last_emit_ts = now
            self._scan_ui_last_emit_count = safe_current

        if phase == "compare":
            results_step_threshold = 100 if safe_total <= 5000 else 500
            results_time_threshold = 1.20 if safe_total <= 5000 else 2.20
            should_emit = False
            if safe_current in (0, 1):
                should_emit = True
            if safe_total and safe_current >= safe_total:
                should_emit = True
            if (safe_current - self._scan_live_last_emit_count) >= results_step_threshold:
                should_emit = True
            if (now - self._scan_live_last_emit_ts) >= results_time_threshold:
                should_emit = True
            if should_emit:
                self.results = self.core.get_results()
                self.results_changed.emit(self.results)
                self._scan_live_last_emit_ts = now
                self._scan_live_last_emit_count = safe_current

    def _on_scan_finished(self, res: dict) -> None:
        self._scan_worker = None
        self.core.scanning = False
        self.core.scan_phase = "idle"
        if res.get("error"):
            self.error_changed.emit(res["error"])
            monitor_action(f"[!] scan:error {res['error']}")
        else:
            monitor_action("[!] scan:finished")
        self.core.persist_session()
        self._scan_live_last_emit_ts = 0.0
        self._scan_live_last_emit_count = 0
        self._scan_ui_last_emit_ts = 0.0
        self._scan_ui_last_emit_count = 0
        self._scan_ui_last_phase = "idle"
        self.refresh_all()

    def _on_scan_failed(self, message: str) -> None:
        self._scan_worker = None
        self.core.scanning = False
        self.core.scan_phase = "idle"
        self.error_changed.emit(message)
        monitor_action(f"[!] scan:failed {message}")
        self._scan_live_last_emit_ts = 0.0
        self._scan_live_last_emit_count = 0
        self._scan_ui_last_emit_ts = 0.0
        self._scan_ui_last_emit_count = 0
        self._scan_ui_last_phase = "idle"
        self.refresh_status()

    def _clear_organize_refs(self, thread: Optional[QtCore.QThread] = None) -> None:
        """Clear organize worker/thread refs when an organize job ends."""
        self._organize_worker = None
        if thread is None or self._organize_thread is thread:
            self._organize_thread = None

    def preview_organize(self, output: str, strategy: str, action: str) -> dict:
        res = self.core.preview_organize(output, strategy, action)
        if res.get("error"):
            self.error_changed.emit(res["error"])
        return res

    def organize(self, output: str, strategy: str, action: str) -> None:
        if self._organize_thread and self._organize_thread.isRunning():
            return
        self._organize_thread = QtCore.QThread()
        thread = self._organize_thread
        worker = OrganizeWorker(self.core, output, strategy, action)
        self._organize_worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.organize_progress.emit)
        worker.finished.connect(self._on_organize_finished)
        worker.failed.connect(self._on_organize_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(lambda: self._clear_organize_refs(thread))
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def organize_unidentified(self, output: str, action: str) -> None:
        if self._organize_thread and self._organize_thread.isRunning():
            return
        self._organize_thread = QtCore.QThread()
        thread = self._organize_thread
        worker = OrganizeWorker(self.core, output, "flat", action, is_unidentified=True)
        self._organize_worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.organize_progress.emit)
        worker.finished.connect(self._on_organize_finished)
        worker.failed.connect(self._on_organize_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(lambda: self._clear_organize_refs(thread))
        thread.finished.connect(thread.deleteLater)
        thread.start()



    def _on_organize_finished(self, res: dict) -> None:
        self._organize_worker = None
        if res.get("error"):
            self.error_changed.emit(res["error"])
        self.core.persist_session()
        self.refresh_all()
        self.organize_finished.emit(res)

    def _on_organize_failed(self, message: str) -> None:
        self._organize_worker = None
        self.error_changed.emit(message)
        self.organize_failed.emit(message)

    def undo(self) -> dict:
        res = self.core.undo()
        if res.get("error"):
            self.error_changed.emit(res["error"])
        return res

    def save_collection(self, name: str) -> dict:
        res = self.core.save_collection(name)
        if res.get("error"):
            self.error_changed.emit(res["error"])
        self.list_collections()
        if res.get("success") and res.get("filepath"):
            self.last_collection_path = str(res.get("filepath"))
        return res

    def load_collection(self, filepath: str) -> dict:
        res = self.core.load_collection(filepath)
        if res.get("error"):
            self.error_changed.emit(res["error"])
        self.core.persist_session()
        # Force immediate UI refresh so tables repopulate after load.
        self.status = self.core.get_status()
        self.status_changed.emit(self.status)
        self.results = self.core.get_results()
        self.results_changed.emit(self.results)
        self.missing = self.core.get_missing()
        self.missing_changed.emit(self.missing)
        self.refresh_dashboard_intel()
        if res.get("success"):
            self.last_collection_path = str(filepath)
        return res

    def list_collections(self) -> None:
        res = self.core.list_collections()
        self.collections = res.get("collections", [])
        self.collections_changed.emit(self.collections)

    def list_recent_collections(self) -> None:
        res = self.core.list_recent_collections()
        self.recent_collections = res.get("recent", [])
        self.recent_collections_changed.emit(self.recent_collections)

    # Backward-compatible refresh aliases (used by ToolsView buttons)
    def refresh_collections(self) -> None:
        self.list_collections()

    def refresh_recent_collections(self) -> None:
        self.list_recent_collections()

    def dat_library_list(self) -> None:
        res = self.core.dat_library_list()
        self.dat_library = res.get("dats", [])
        self.dat_library_changed.emit(self.dat_library)

    def refresh_dat_library(self) -> None:
        self.dat_library_list()

    def dat_library_import(self, filepath: str) -> dict:
        res = self.core.dat_library_import(filepath)
        if res.get("error"):
            self.error_changed.emit(res["error"])
        self.dat_library_list()
        return res

    def dat_library_load(self, dat_id: str) -> dict:
        res = self.core.dat_library_load(dat_id)
        if res.get("error"):
            self.error_changed.emit(res["error"])
        self.core.persist_session()
        self.refresh_all()
        return res

    def dat_library_remove(self, dat_id: str) -> dict:
        res = self.core.dat_library_remove(dat_id)
        if res.get("error"):
            self.error_changed.emit(res["error"])
            self.dat_library_list()
            return res
        self.core.persist_session()
        self.dat_library_list()
        self.refresh_all()
        return res

    def dat_sources_list(self) -> None:
        self.refresh_dat_downloader_catalog()

    def refresh_dat_downloader_catalog(self, family: str = "") -> bool:
        safe_family = str(family or "").strip().lower()
        # Keep latest refresh request only.
        self._dat_task_queue = [t for t in self._dat_task_queue if t.get("name") != "dat_downloader_catalog"]
        self._enqueue_dat_task(
            name="dat_downloader_catalog",
            func=self.core.dat_downloader_catalog,
            args=(safe_family, 5000, True),
            done_signal=self.dat_downloader_catalog_done,
            on_failed_payload=lambda msg: {"error": msg, "items": [], "family_filter": safe_family},
        )
        return True

    def queue_dat_download(
        self,
        url: str,
        *,
        family: str = "",
        output_dir: str = "",
        auto_import: bool = True,
    ) -> bool:
        safe_url = str(url or "").strip()
        if not safe_url:
            self.log_message.emit(f"[!] {self.t('dat_downloader_url_required')}")
            return False
        self._enqueue_dat_task(
            name="dat_downloader_download",
            func=self.core.dat_downloader_download,
            args=(
                safe_url,
                str(family or "").strip(),
                str(output_dir or "").strip(),
                bool(auto_import),
                True,
            ),
            done_signal=self.dat_downloader_download_done,
            on_failed_payload=lambda msg: {"error": msg, "url": safe_url},
        )
        return True

    def queue_dat_download_by_query(
        self,
        query: str,
        *,
        family: str = "",
        output_dir: str = "",
        auto_import: bool = True,
    ) -> bool:
        safe_query = str(query or "").strip()
        if not safe_query:
            self.log_message.emit(f"[!] {self.t('dat_downloader_query_required')}")
            return False
        # Keep latest quick-query request only.
        self._dat_task_queue = [
            t for t in self._dat_task_queue if t.get("name") != "dat_downloader_find_and_download"
        ]
        self._enqueue_dat_task(
            name="dat_downloader_find_and_download",
            func=self.core.dat_downloader_find_and_download,
            args=(safe_query, str(family or "").strip(), str(output_dir or "").strip(), bool(auto_import)),
            done_signal=self.dat_downloader_download_done,
            on_failed_payload=lambda msg: {"error": msg, "query": safe_query},
        )
        return True

    def _enqueue_dat_task(
        self,
        *,
        name: str,
        func,
        args: tuple,
        done_signal: QtCore.SignalInstance,
        on_failed_payload,
    ) -> None:
        self._dat_task_queue.append(
            {
                "name": name,
                "func": func,
                "args": args,
                "done_signal": done_signal,
                "on_failed_payload": on_failed_payload,
            }
        )
        self._drain_dat_task_queue()

    def _drain_dat_task_queue(self) -> None:
        if self._dat_thread is not None:
            try:
                if self._dat_thread.isRunning():
                    return
            except RuntimeError:
                self._dat_thread = None
                self._dat_worker = None
        if not self._dat_task_queue:
            return

        task = self._dat_task_queue.pop(0)
        self._dat_thread = QtCore.QThread()
        worker = ToolWorker(task["func"], task["args"])
        self._dat_worker = worker
        worker.moveToThread(self._dat_thread)
        self._dat_thread.started.connect(worker.run)
        worker.finished.connect(self._dat_thread.quit)
        worker.failed.connect(self._dat_thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)

        def _on_finished(res: dict) -> None:
            payload = res if isinstance(res, dict) else {"error": str(res)}
            task["done_signal"].emit(payload)

        def _on_failed(message: str) -> None:
            self.log_message.emit(f"[!] {message}")
            try:
                payload = task["on_failed_payload"](message)
            except Exception:
                payload = {"error": message}
            task["done_signal"].emit(payload)

        worker.finished.connect(_on_finished)
        worker.failed.connect(_on_failed)

        self._dat_thread.finished.connect(self._dat_thread.deleteLater)
        self._dat_thread.finished.connect(lambda: setattr(self, "_dat_thread", None))
        self._dat_thread.finished.connect(lambda: setattr(self, "_dat_worker", None))
        self._dat_thread.finished.connect(self._drain_dat_task_queue)
        self._dat_thread.start()

    def _on_dat_downloader_catalog_done(self, payload: dict) -> None:
        data = payload if isinstance(payload, dict) else {}
        self.dat_sources = [row for row in list(data.get("items", []) or []) if isinstance(row, dict)]
        self.dat_sources_changed.emit(self.dat_sources)

    def _on_dat_downloader_download_done(self, payload: dict) -> None:
        data = payload if isinstance(payload, dict) else {}
        if data.get("error"):
            self.error_changed.emit(str(data.get("error")))
            return
        if data.get("imported"):
            self.dat_library_list()
        if data.get("loaded"):
            self.refresh_all()

    def refresh_dashboard_intel(self) -> None:
        if self._dashboard_thread:
            try:
                if self._dashboard_thread.isRunning():
                    return
            except RuntimeError:
                self._dashboard_thread = None

        self._dashboard_thread = QtCore.QThread()

        def _collect() -> dict:
            return {
                "dat_syndicate": self.core.fetch_dat_syndicate(),
                "bounty_board": self.core.get_bounty_board(),
                "storage_telemetry": self.core.get_storage_telemetry(),
                "retro_news": {},
            }

        worker = ToolWorker(_collect, ())
        self._dashboard_worker = worker
        worker.moveToThread(self._dashboard_thread)
        self._dashboard_thread.started.connect(worker.run)
        worker.finished.connect(self._dashboard_thread.quit)
        worker.failed.connect(self._dashboard_thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        self._dashboard_thread.finished.connect(self._dashboard_thread.deleteLater)
        self._dashboard_thread.finished.connect(lambda: setattr(self, "_dashboard_thread", None))
        self._dashboard_thread.finished.connect(lambda: setattr(self, "_dashboard_worker", None))

        def _on_done(payload: dict) -> None:
            self.dashboard_intel = payload or {}
            self.dashboard_data_ready.emit(self.dashboard_intel)
            self.log_message.emit("[*] dashboard:intel:ready")

        def _on_failed(message: str) -> None:
            self.error_changed.emit(message)
            self.log_message.emit(f"[!] dashboard:intel:error {message}")

        worker.finished.connect(_on_done)
        worker.failed.connect(_on_failed)
        self.log_message.emit("[*] dashboard:intel:refresh:start")
        self._dashboard_thread.start()

    def queue_myrient_downloads(self, targets: List[Dict[str, Any]]) -> dict:
        def _progress(filename: str, percent: float, speed: str, status: str) -> None:
            self.download_progress.emit(filename, float(percent or 0.0), str(speed or ""), str(status or ""))

        res = self.core.myrient_queue_downloads(targets or [], progress_callback=_progress)
        if res.get("error"):
            self.error_changed.emit(res["error"])
            self.log_message.emit(f"[!] myrient:queue:error {res['error']}")
            return res
        queued = int(res.get("queued", 0) or 0)
        errs = res.get("errors", []) or []
        self.log_message.emit(f"[*] myrient:queue:queued={queued} errors={len(errs)}")
        for item in errs[:4]:
            self.log_message.emit(f"[!] myrient:queue:item_error {item.get('error', 'unknown')}")
        return res

    def _register_jdownloader_monitor_targets(self, accepted_items: List[Dict[str, Any]]) -> None:
        now = time.monotonic()
        with self._jd_monitor_lock:
            for item in accepted_items:
                if not isinstance(item, dict):
                    continue
                dest_path = str(item.get("dest_path", "") or "").strip()
                if not dest_path:
                    continue
                key = str(Path(dest_path))
                filename = str(item.get("filename", "") or Path(dest_path).name or "download.bin")
                self._jd_monitor_items[key] = {
                    "key": key,
                    "filename": filename.strip() or "download.bin",
                    "dest_path": dest_path,
                    "url": str(item.get("url", "") or "").strip(),
                    "size_hint": int(item.get("size_hint", 0) or 0),
                    "last_size": 0,
                    "last_ts": now,
                    "last_growth_ts": now,
                    "status": "ADDED",
                    "added_ts": now,
                    "done_ts": 0.0,
                    "stable_ticks": 0,
                    "last_emit_pct": -1.0,
                    "last_emit_speed": "",
                    "last_emit_status": "",
                }
        if not self._jd_monitor_timer.isActive():
            self._jd_monitor_timer.start()
        self._ensure_jdownloader_size_hints_async()

    def _ensure_jdownloader_size_hints_async(self) -> None:
        th = self._jd_hint_thread
        if th is not None and th.is_alive():
            return
        self._jd_hint_thread = threading.Thread(
            target=self._fill_jdownloader_size_hints_worker,
            name="R0MM-JD-SizeHints",
            daemon=True,
        )
        self._jd_hint_thread.start()

    def _fill_jdownloader_size_hints_worker(self) -> None:
        while True:
            with self._jd_monitor_lock:
                pending = [
                    (key, str(item.get("url", "") or ""))
                    for key, item in self._jd_monitor_items.items()
                    if int(item.get("size_hint", 0) or 0) <= 0 and str(item.get("url", "") or "").strip()
                ]
            if not pending:
                return
            progressed = False
            for key, url in pending[:24]:
                try:
                    size_hint = int(self.core.jdownloader_probe_content_length(url, timeout_s=2.5) or 0)
                except Exception:
                    size_hint = 0
                if size_hint > 0:
                    progressed = True
                    with self._jd_monitor_lock:
                        item = self._jd_monitor_items.get(key)
                        if item is not None:
                            item["size_hint"] = int(size_hint)
                time.sleep(0.02)
            if not progressed:
                return

    def _emit_jdownloader_progress_if_changed(
        self,
        item: Dict[str, Any],
        *,
        percent: float,
        speed_text: str,
        status: str,
    ) -> None:
        pct = max(0.0, min(100.0, float(percent or 0.0)))
        safe_speed = str(speed_text or "").strip()
        safe_status = str(status or "").upper().strip() or "QUEUED"
        last_status = str(item.get("last_emit_status", "") or "")
        last_pct = float(item.get("last_emit_pct", -1.0) or -1.0)
        last_speed = str(item.get("last_emit_speed", "") or "")
        changed = (
            safe_status != last_status
            or abs(pct - last_pct) >= 1.0
            or (safe_status == "DOWNLOADING" and safe_speed != last_speed)
            or safe_status in {"DONE", "ERROR"}
        )
        if not changed:
            return
        item["last_emit_status"] = safe_status
        item["last_emit_pct"] = pct
        item["last_emit_speed"] = safe_speed
        self.download_progress.emit(str(item.get("filename", "download.bin")), pct, safe_speed, safe_status)

    def _poll_jdownloader_progress(self) -> None:
        now = time.monotonic()
        with self._jd_monitor_lock:
            snapshot = list(self._jd_monitor_items.items())
        if not snapshot:
            self._jd_monitor_timer.stop()
            return

        remove_keys: List[str] = []
        for key, item in snapshot:
            dest_path = Path(str(item.get("dest_path", "") or ""))
            if not dest_path:
                continue
            part_path = Path(str(dest_path) + ".part")

            final_exists = False
            part_exists = False
            final_size = 0
            part_size = 0
            try:
                final_exists = dest_path.exists()
                if final_exists:
                    final_size = int(dest_path.stat().st_size or 0)
            except Exception:
                final_exists = False
                final_size = 0
            try:
                part_exists = part_path.exists()
                if part_exists:
                    part_size = int(part_path.stat().st_size or 0)
            except Exception:
                part_exists = False
                part_size = 0

            active_size = part_size if part_exists else final_size
            prev_size = int(item.get("last_size", 0) or 0)
            prev_ts = float(item.get("last_ts", now) or now)
            delta_t = max(0.001, now - prev_ts)
            delta_b = active_size - prev_size
            if delta_b > 0:
                item["last_growth_ts"] = now
                item["stable_ticks"] = 0
            else:
                item["stable_ticks"] = int(item.get("stable_ticks", 0) or 0) + 1
            item["last_size"] = active_size
            item["last_ts"] = now

            size_hint = int(item.get("size_hint", 0) or 0)
            status = str(item.get("status", "ADDED") or "ADDED").upper()
            percent = 0.0

            if part_exists:
                status = "DOWNLOADING" if active_size > 0 or delta_b > 0 else "QUEUED"
            elif final_exists:
                if size_hint > 0:
                    if final_size >= max(1, size_hint - 1) and not part_exists:
                        status = "DONE"
                    else:
                        status = "DOWNLOADING"
                else:
                    if delta_b > 0:
                        status = "DOWNLOADING"
                    elif int(item.get("stable_ticks", 0) or 0) >= 3:
                        status = "DONE"
                    else:
                        status = "DOWNLOADING" if final_size > 0 else "QUEUED"
            else:
                if status in {"DONE", "ERROR"}:
                    pass
                elif status in {"DOWNLOADING", "QUEUED", "ADDED"}:
                    status = "QUEUED"

            if status == "DONE":
                percent = 100.0
                if float(item.get("done_ts", 0.0) or 0.0) <= 0:
                    item["done_ts"] = now
            elif size_hint > 0 and active_size > 0:
                percent = min(99.9, (float(active_size) / float(size_hint)) * 100.0)
            else:
                percent = 0.0

            speed_text = ""
            if status == "DOWNLOADING" and delta_b > 0:
                speed_bps = float(delta_b) / float(delta_t)
                speed_text = f"{(speed_bps / (1024.0 * 1024.0)):.2f} MB/s"

            item["status"] = status
            self._emit_jdownloader_progress_if_changed(
                item,
                percent=percent,
                speed_text=speed_text,
                status=status,
            )

            done_ts = float(item.get("done_ts", 0.0) or 0.0)
            if status in {"DONE", "ERROR"} and done_ts > 0 and (now - done_ts) > 90.0:
                remove_keys.append(key)
            elif status in {"QUEUED", "ADDED"} and (now - float(item.get("added_ts", now) or now)) > 3600.0:
                remove_keys.append(key)

            with self._jd_monitor_lock:
                if key in self._jd_monitor_items:
                    self._jd_monitor_items[key] = item

        if remove_keys:
            with self._jd_monitor_lock:
                for key in remove_keys:
                    self._jd_monitor_items.pop(key, None)
        with self._jd_monitor_lock:
            if not self._jd_monitor_items and self._jd_monitor_timer.isActive():
                self._jd_monitor_timer.stop()

    def queue_jdownloader_downloads(
        self,
        targets: List[Dict[str, Any]],
        *,
        autostart: bool = True,
        jd_options: Optional[Dict[str, Any]] = None,
    ) -> dict:
        self._emit_jdownloader_handoff_progress(True, 2, "prepare")
        res = self.core.jdownloader_queue_downloads(
            targets or [],
            autostart=autostart,
            jd_options=jd_options or {},
            phase_callback=lambda phase, pct: self._emit_jdownloader_handoff_progress(True, pct, phase),
        )
        if isinstance(res, dict) and res.get("error"):
            self._emit_jdownloader_handoff_progress(False, 100, "error")
        else:
            self._emit_jdownloader_handoff_progress(False, 100, "done")
        return self._handle_jdownloader_queue_result(res, autostart=autostart)

    def queue_jdownloader_downloads_async(
        self,
        targets: List[Dict[str, Any]],
        *,
        autostart: bool = True,
        jd_options: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if self._jd_queue_thread is not None:
            try:
                if self._jd_queue_thread.isRunning():
                    self.log_message.emit(f"[!] {self.t('busy_operation')}")
                    return False
            except RuntimeError:
                self._jd_queue_thread = None
                self._jd_queue_worker = None

        safe_targets = [t for t in list(targets or []) if isinstance(t, dict)]
        if not safe_targets:
            self.log_message.emit("[!] jdownloader:queue:error targets required")
            self.jdownloader_queue_finished.emit({"error": "targets required"})
            return False

        safe_opts = dict(jd_options) if isinstance(jd_options, dict) else {}
        self._emit_jdownloader_handoff_progress(True, 2, "prepare")
        self._jd_queue_thread = QtCore.QThread()

        def _queue_work() -> dict:
            return self.core.jdownloader_queue_downloads(
                safe_targets,
                autostart=autostart,
                jd_options=safe_opts,
                phase_callback=lambda phase, pct: self._emit_jdownloader_handoff_progress(True, pct, phase),
            )

        worker = ToolWorker(_queue_work, ())
        self._jd_queue_worker = worker
        worker.moveToThread(self._jd_queue_thread)
        self._jd_queue_thread.started.connect(worker.run)
        worker.finished.connect(self._jd_queue_thread.quit)
        worker.failed.connect(self._jd_queue_thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        self._jd_queue_thread.finished.connect(self._jd_queue_thread.deleteLater)
        self._jd_queue_thread.finished.connect(lambda: setattr(self, "_jd_queue_thread", None))
        self._jd_queue_thread.finished.connect(lambda: setattr(self, "_jd_queue_worker", None))

        def _on_done(res: dict) -> None:
            payload = self._handle_jdownloader_queue_result(res, autostart=autostart)
            if payload.get("error"):
                self._emit_jdownloader_handoff_progress(False, 100, "error")
            else:
                self._emit_jdownloader_handoff_progress(False, 100, "done")
            self.jdownloader_queue_finished.emit(payload)

        def _on_failed(message: str) -> None:
            payload = self._handle_jdownloader_queue_result({"error": message}, autostart=autostart)
            self._emit_jdownloader_handoff_progress(False, 100, "error")
            self.jdownloader_queue_finished.emit(payload)

        worker.finished.connect(_on_done)
        worker.failed.connect(_on_failed)
        self._jd_queue_thread.start()
        return True

    def _emit_jdownloader_handoff_progress(self, active: bool, percent: int, phase: str) -> None:
        try:
            pct = max(0, min(100, int(percent or 0)))
        except Exception:
            pct = 0
        self.jdownloader_handoff_progress.emit(bool(active), pct, str(phase or "").strip())

    def _handle_jdownloader_queue_result(self, res: dict, *, autostart: bool) -> dict:
        if not isinstance(res, dict):
            res = {"error": str(res)}
        if res.get("error"):
            self.error_changed.emit(res["error"])
            self.log_message.emit(f"[!] jdownloader:queue:error {res['error']}")
            hint = str(res.get("hint", "") or "").strip()
            if hint:
                self.log_message.emit(f"[?] jdownloader:hint {hint}")
            return res

        queued = int(res.get("queued", 0) or 0)
        errs = list(res.get("errors", []) or [])
        endpoint = str(res.get("endpoint", "") or "")
        runtime = dict(res.get("runtime", {}) or {})
        runtime_mode = str(runtime.get("boot_mode", "") or "").strip()
        if runtime:
            try:
                runtime_timeout = int(float(runtime.get("boot_timeout_s", 0) or 0))
            except Exception:
                runtime_timeout = 0
        else:
            runtime_timeout = 0
        runtime_tune = bool(runtime.get("tune_enabled", False)) if runtime else False
        runtime_profile = str(runtime.get("tune_profile", "") or "").strip()
        runtime_bin_override = 1 if bool(runtime.get("binary_override", False)) else 0
        repair = dict(res.get("repair", {}) or {})
        self.log_message.emit(
            (
                f"[*] jdownloader:queue:queued={queued} errors={len(errs)} autostart={1 if autostart else 0} "
                f"mode={runtime_mode or 'gui'} timeout={runtime_timeout or 30}s "
                f"tune={1 if runtime_tune else 0}/{runtime_profile or 'balanced'} "
                f"bin_override={runtime_bin_override}"
            )
        )
        if endpoint:
            self.log_message.emit(f"[*] jdownloader:endpoint:{endpoint}")
        if repair.get("changed"):
            changed_count = len((repair.get("changes") or {}).keys())
            self.log_message.emit(f"[*] jdownloader:repair:changed keys={changed_count}")
        if repair.get("restarted"):
            killed = ",".join([str(x) for x in list(repair.get("restart_info", {}).get("killed_pids", []) or [])])
            self.log_message.emit(f"[*] jdownloader:repair:restarted pids={killed or '-'}")
        if repair.get("ready"):
            self.log_message.emit("[*] jdownloader:repair:ready")
        if repair.get("restart_required"):
            self.log_message.emit("[?] jdownloader:repair:restart_required")
        tune = res.get("tune", {}) or {}
        if isinstance(tune, dict) and tune.get("applied") and tune.get("changed"):
            profile = str(tune.get("profile", "balanced") or "balanced")
            changed_count = len((tune.get("changes") or {}).keys())
            self.log_message.emit(
                f"[*] jdownloader:tune:applied profile={profile} changed={changed_count}"
            )
            self.log_message.emit("[?] jdownloader:tune:restart_jdownloader_recommended")

        accepted_items = [a for a in list(res.get("accepted", []) or []) if isinstance(a, dict)]
        for accepted in accepted_items:
            filename = str(accepted.get("filename", "") or "").strip() or "download.bin"
            self.download_progress.emit(filename, 0.0, "JDownloader", "ADDED")
        if accepted_items:
            self._register_jdownloader_monitor_targets(accepted_items)

        for item in errs[:8]:
            raw_name = str(item.get("dest_path", "") or item.get("url", "") or "download.bin")
            name = Path(raw_name).name or raw_name
            self.download_progress.emit(name, 0.0, str(item.get("error", "unknown")), "ERROR")
            self.log_message.emit(f"[!] jdownloader:queue:item_error {item.get('error', 'unknown')}")
        return res

    def repair_jdownloader_api(self, jd_options: Optional[Dict[str, Any]] = None) -> dict:
        options = dict(jd_options) if isinstance(jd_options, dict) else {}
        endpoint = str(options.get("endpoint", "") or "").strip()
        binary_path = str(options.get("binary_path", "") or "").strip()
        try:
            boot_timeout_s = float(options.get("boot_timeout_s", 18) or 18)
        except Exception:
            boot_timeout_s = 18.0

        res = self.core.jdownloader_repair_local_api(
            endpoint=endpoint,
            binary_path=binary_path,
            requested_mode="gui",
            boot_timeout_s=boot_timeout_s,
            enable_deprecated_api=True,
            force_restart_on_change=True,
        )
        if res.get("error"):
            self.log_message.emit(f"[!] jdownloader:repair:error {res.get('error')}")
            return res

        changed = 1 if res.get("changed") else 0
        ready = 1 if res.get("ready") else 0
        restarted = 1 if res.get("restarted") else 0
        self.log_message.emit(f"[*] jdownloader:repair:done changed={changed} ready={ready}")
        if restarted:
            self.log_message.emit("[*] jdownloader:repair:restarted")
        if res.get("restart_required"):
            self.log_message.emit("[?] jdownloader:repair:restart_required")
        return res

    def request_missing_download_links(self, items: List[Dict[str, Any]]) -> None:
        payload = [i for i in (items or []) if isinstance(i, dict)]
        self.log_message.emit(f"[*] myrient:missing:request count={len(payload)}")
        self.download_missing_requested.emit(payload)

    def _enqueue_myrient_task(
        self,
        *,
        name: str,
        func,
        args: tuple,
        done_signal: QtCore.SignalInstance,
        on_failed_payload,
    ) -> None:
        self._myrient_task_queue.append(
            {
                "name": name,
                "func": func,
                "args": args,
                "done_signal": done_signal,
                "on_failed_payload": on_failed_payload,
            }
        )
        self._drain_myrient_task_queue()

    def _drain_myrient_task_queue(self) -> None:
        if self._myrient_thread is not None:
            try:
                if self._myrient_thread.isRunning():
                    return
            except RuntimeError:
                self._myrient_thread = None
                self._myrient_worker = None
        if not self._myrient_task_queue:
            return

        task = self._myrient_task_queue.pop(0)
        self._myrient_thread = QtCore.QThread()
        worker = ToolWorker(task["func"], task["args"])
        self._myrient_worker = worker
        worker.moveToThread(self._myrient_thread)
        self._myrient_thread.started.connect(worker.run)
        worker.finished.connect(self._myrient_thread.quit)
        worker.failed.connect(self._myrient_thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)

        def _on_finished(res: dict) -> None:
            payload = res if isinstance(res, dict) else {"error": str(res)}
            task["done_signal"].emit(payload)

        def _on_failed(message: str) -> None:
            self.log_message.emit(f"[!] {message}")
            try:
                payload = task["on_failed_payload"](message)
            except Exception:
                payload = {"error": message}
            task["done_signal"].emit(payload)

        worker.finished.connect(_on_finished)
        worker.failed.connect(_on_failed)

        self._myrient_thread.finished.connect(self._myrient_thread.deleteLater)
        self._myrient_thread.finished.connect(lambda: setattr(self, "_myrient_thread", None))
        self._myrient_thread.finished.connect(lambda: setattr(self, "_myrient_worker", None))
        self._myrient_thread.finished.connect(self._drain_myrient_task_queue)
        self._myrient_thread.start()

    def list_myrient_directory(self, base_url: str) -> None:
        if not base_url:
            self.log_message.emit("[!] myrient:list:missing_base_url")
            return
        self.log_message.emit(f"[*] myrient:list:start {base_url}")
        self._enqueue_myrient_task(
            name="myrient_list_directory",
            func=self.core.myrient_list_directory,
            args=(base_url,),
            done_signal=self.myrient_directory_listed,
            on_failed_payload=lambda msg: {"error": msg, "base_url": base_url},
        )

    def resolve_myrient_links_from_missing(self, base_url: str, missing_items: List[Dict[str, Any]]) -> None:
        if not base_url or not missing_items:
            self.log_message.emit("[!] myrient:resolve:missing_params")
            return
        self.log_message.emit(f"[*] myrient:resolve:start count={len(missing_items)}")
        self._enqueue_myrient_task(
            name="myrient_resolve_links_from_missing",
            func=self.core.myrient_resolve_links_from_missing,
            args=(base_url, missing_items),
            done_signal=self.myrient_links_resolved,
            on_failed_payload=lambda msg: {
                "error": msg,
                "base_url": base_url,
                "matches": [],
                "unmatched": [],
                "ambiguous": [],
            },
        )

    def halt_traffic(self) -> dict:
        try:
            res = self.core.halt_traffic()
        except Exception as exc:
            message = str(exc)
            self.error_changed.emit(message)
            self.log_message.emit(f"[!] myrient:halt:error {message}")
            return {"error": message}
        self.log_message.emit(
            f"[!] myrient:halt cancelled={int(res.get('cancelled', 0) or 0)} active={int(res.get('active_signalled', 0) or 0)}"
        )
        self._emit_jdownloader_handoff_progress(False, 100, "halted")
        return res

    def _run_tool(self, name: str, func, args: tuple, done_signal: QtCore.SignalInstance, use_progress: bool) -> None:
        if self._tool_thread and self._tool_thread.isRunning():
            self.log_message.emit(f"[!] {self.t('busy_operation')}")
            return
        self._tool_thread = QtCore.QThread()

        def _progress(current: int, total: int, filename: str = "") -> None:
            self.tool_progress.emit(name, current, total, filename)

        worker = ToolWorker(func, args, progress_callback=_progress if use_progress else None)
        worker.moveToThread(self._tool_thread)
        self._tool_thread.started.connect(worker.run)
        worker.finished.connect(self._tool_thread.quit)
        worker.failed.connect(self._tool_thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        self._tool_thread.finished.connect(self._tool_thread.deleteLater)

        def _on_finished(res: dict) -> None:
            if res.get("error"):
                self.tool_failed.emit(res["error"])
                self.log_message.emit(f"[!] {res['error']}")
            done_signal.emit(res)

        worker.finished.connect(_on_finished)
        worker.failed.connect(lambda msg: self.tool_failed.emit(msg))
        worker.failed.connect(lambda msg: self.log_message.emit(f"[!] {msg}"))
        self._tool_thread.start()

    # Tools API (async wrappers)
    def compare_dats(self, dat_path_a: Optional[str] = None, dat_path_b: Optional[str] = None) -> None:
        if not dat_path_a or not dat_path_b:
            self.log_message.emit("[!] dat_path_a and dat_path_b are required.")
            return
        self._run_tool("compare_dats", self.core.compare_dats, (dat_path_a, dat_path_b), self.dat_diff_done, False)

    def merge_dats(self, dat_paths: Optional[List[str]] = None, output_path: Optional[str] = None, strategy: str = "strict") -> None:
        if not dat_paths or not output_path:
            self.log_message.emit("[!] dat_paths and output_path are required.")
            return
        self._run_tool("merge_dats", self.core.merge_dats, (dat_paths, output_path, strategy), self.dat_merge_done, False)

    def batch_convert(self, source_dir: Optional[str] = None, output_dir: Optional[str] = None, target_format: Optional[str] = None) -> None:
        if not source_dir or not output_dir or not target_format:
            self.log_message.emit("[!] source_dir, output_dir and target_format are required.")
            return
        self._run_tool(
            "batch_convert",
            self.core.batch_convert,
            (source_dir, output_dir, target_format),
            self.batch_convert_done,
            True,
        )

    def apply_torrentzip(self, target_dir: Optional[str] = None) -> None:
        if not target_dir:
            self.log_message.emit("[!] target_dir is required.")
            return
        self._run_tool("apply_torrentzip", self.core.apply_torrentzip, (target_dir,), self.torrentzip_done, True)

    def deep_clean(self, target_dir: Optional[str] = None, dat_id: Optional[str] = None, dry_run: bool = True) -> None:
        if not target_dir:
            self.log_message.emit("[!] target_dir is required.")
            return
        self._run_tool("deep_clean", self.core.deep_clean, (target_dir, dat_id, dry_run), self.deep_clean_done, True)

    def find_duplicates(self, target_dir: Optional[str] = None) -> None:
        if not target_dir:
            self.log_message.emit("[!] target_dir is required.")
            return
        self._run_tool("find_duplicates", self.core.find_duplicates, (target_dir,), self.find_duplicates_done, True)

    # Backward-compatible UI methods (to be wired with UI inputs later)
    def convert_roms(self, format_type: str) -> None:
        self.log_message.emit("[!] source_dir and output_dir are required for batch convert.")

    def clean_junk_files(self) -> None:
        self.log_message.emit("[!] target_dir is required for deep clean.")
