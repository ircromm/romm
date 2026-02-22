"""PySide6 desktop GUI for R0MM.

This module mirrors the core Flet flows while keeping domain logic in the
existing backend services.
"""

from __future__ import annotations

import os
import sys
import webbrowser
from typing import Any, Dict, List, Optional

from . import i18n as _i18n
from .dat_sources import KNOWN_SOURCES
from .matcher import MultiROMMatcher
from .models import DATInfo, ROMInfo, ScannedFile
from .organizer import Organizer
from .parser import DATParser
from .reporter import MissingROMReporter
from .scanner import FileScanner
from .settings import (
    PROFILE_PRESETS,
    apply_runtime_settings,
    get_effective_profile,
    load_settings,
    save_settings,
)
from .utils import format_size

LANG_EN = getattr(_i18n, "LANG_EN", "en")
LANG_PT_BR = getattr(_i18n, "LANG_PT_BR", "pt-BR")

MOCHA = {
    "text": "#cdd6f4",
    "subtext0": "#a6adc8",
    "subtext1": "#bac2de",
    "surface0": "#313244",
    "surface1": "#45475a",
    "base": "#1e1e2e",
    "crust": "#11111b",
    "blue": "#89b4fa",
    "green": "#a6e3a1",
    "mauve": "#cba6f7",
    "red": "#f38ba8",
    "yellow": "#f9e2af",
}


def _tr(key: str, **kwargs: Any) -> str:
    func = getattr(_i18n, "tr", None)
    if callable(func):
        return func(key, **kwargs)
    return key


def _set_language(lang: str) -> None:
    func = getattr(_i18n, "set_language", None)
    if callable(func):
        func(lang)


class AppStateQt:
    """UI-independent state and orchestration layer for the PySide6 GUI."""

    def __init__(self) -> None:
        self.multi_matcher = MultiROMMatcher()
        self.organizer = Organizer()
        self.reporter = MissingROMReporter()
        self.settings: Dict[str, Any] = load_settings()
        self.identified: List[ScannedFile] = []
        self.unidentified: List[ScannedFile] = []
        self.activity_log: List[str] = []

    def log(self, message: str) -> None:
        self.activity_log.append(message)
        if len(self.activity_log) > 1000:
            self.activity_log = self.activity_log[-1000:]


def run_pyside6_gui() -> int:
    """Launch PySide6 GUI if available."""
    try:
        from PySide6.QtCore import Qt, QThread, Signal
        from PySide6.QtGui import QAction, QKeySequence
        from PySide6.QtWidgets import (
            QApplication,
            QCheckBox,
            QComboBox,
            QFileDialog,
            QFormLayout,
            QGridLayout,
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QListWidget,
            QListWidgetItem,
            QMainWindow,
            QMessageBox,
            QPushButton,
            QProgressBar,
            QSplitter,
            QStatusBar,
            QTableWidget,
            QTableWidgetItem,
            QTabWidget,
            QTextEdit,
            QVBoxLayout,
            QWidget,
        )
    except ImportError as exc:
        print("Error: PySide6 is required for this interface")
        print("Install it with: pip install PySide6")
        print(f"Details: {exc}")
        return 1

    class ScanWorker(QThread):
        progress = Signal(int, int)
        finished_scan = Signal(list)
        failed = Signal(str)

        def __init__(self, folder: str, recursive: bool, scan_archives: bool) -> None:
            super().__init__()
            self.folder = folder
            self.recursive = recursive
            self.scan_archives = scan_archives

        def run(self) -> None:
            try:
                files = FileScanner.scan_folder(
                    self.folder,
                    recursive=self.recursive,
                    scan_archives=self.scan_archives,
                    progress_callback=lambda c, t: self.progress.emit(c, t),
                )
                self.finished_scan.emit(files)
            except Exception as exc:
                self.failed.emit(str(exc))

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.state = AppStateQt()
            apply_runtime_settings(self.state.settings)
            self.scan_worker: Optional[ScanWorker] = None
            self.current_folder = ""

            self.setWindowTitle("R0MM - PySide6")
            self.resize(1300, 820)
            self._apply_theme()
            self._build_ui()
            self._bind_shortcuts()
            self._refresh_all()

        def _apply_theme(self) -> None:
            self.setStyleSheet(
                f"""
                QMainWindow, QWidget {{ background-color: {MOCHA['base']}; color: {MOCHA['text']}; }}
                QGroupBox {{ border: 1px solid {MOCHA['surface1']}; border-radius: 8px; margin-top: 8px; padding: 8px; }}
                QPushButton {{ background-color: {MOCHA['surface1']}; color: {MOCHA['text']}; border-radius: 6px; padding: 6px 10px; }}
                QPushButton:disabled {{ color: {MOCHA['subtext0']}; }}
                QTableWidget, QListWidget, QTextEdit, QComboBox {{
                    background-color: {MOCHA['surface0']};
                    border: 1px solid {MOCHA['surface1']};
                    selection-background-color: {MOCHA['blue']};
                    selection-color: {MOCHA['crust']};
                }}
                QTabBar::tab {{ background: {MOCHA['surface0']}; padding: 8px 12px; margin-right: 3px; }}
                QTabBar::tab:selected {{ background: {MOCHA['mauve']}; color: {MOCHA['crust']}; }}
                """
            )

        def _build_ui(self) -> None:
            self.tabs = QTabWidget()
            self.setCentralWidget(self.tabs)
            self.status = QStatusBar()
            self.setStatusBar(self.status)

            self.dashboard_tab = QWidget()
            self.library_tab = QWidget()
            self.import_tab = QWidget()
            self.logs_tab = QWidget()
            self.missing_tab = QWidget()
            self.myrient_tab = QWidget()
            self.settings_tab = QWidget()

            self.tabs.addTab(self.dashboard_tab, "Dashboard")
            self.tabs.addTab(self.library_tab, _tr("flet_library"))
            self.tabs.addTab(self.import_tab, _tr("flet_import_scan"))
            self.tabs.addTab(self.logs_tab, "Tools / Logs")
            self.tabs.addTab(self.missing_tab, _tr("tab_missing"))
            self.tabs.addTab(self.myrient_tab, "Myrient / DAT")
            self.tabs.addTab(self.settings_tab, _tr("settings"))

            self._build_dashboard_tab()
            self._build_library_tab()
            self._build_import_tab()
            self._build_logs_tab()
            self._build_missing_tab()
            self._build_myrient_tab()
            self._build_settings_tab()

        def _bind_shortcuts(self) -> None:
            organize_action = QAction(self)
            organize_action.setShortcut(QKeySequence("Ctrl+O"))
            organize_action.triggered.connect(self._organize_identified)
            self.addAction(organize_action)

            refresh_action = QAction(self)
            refresh_action.setShortcut(QKeySequence("Ctrl+R"))
            refresh_action.triggered.connect(self._scan_folder)
            self.addAction(refresh_action)

            settings_action = QAction(self)
            settings_action.setShortcut(QKeySequence("Ctrl+,"))
            settings_action.triggered.connect(lambda: self.tabs.setCurrentWidget(self.settings_tab))
            self.addAction(settings_action)

        def _build_dashboard_tab(self) -> None:
            layout = QVBoxLayout(self.dashboard_tab)
            metrics = QGroupBox("Overview")
            grid = QGridLayout(metrics)
            self.lbl_dats = QLabel("DATs loaded: 0")
            self.lbl_identified = QLabel("Identified: 0")
            self.lbl_unidentified = QLabel("Unidentified: 0")
            self.lbl_missing = QLabel("Missing: 0")
            for idx, widget in enumerate([self.lbl_dats, self.lbl_identified, self.lbl_unidentified, self.lbl_missing]):
                grid.addWidget(widget, idx // 2, idx % 2)
            layout.addWidget(metrics)
            layout.addStretch(1)

        def _build_library_tab(self) -> None:
            layout = QVBoxLayout(self.library_tab)
            splitter = QSplitter(Qt.Horizontal)

            left = QWidget()
            left_layout = QVBoxLayout(left)
            self.library_lists = QTabWidget()

            self.tbl_identified = QTableWidget(0, 5)
            self.tbl_identified.setHorizontalHeaderLabels(["Arquivo", "Jogo", "Sistema", "Região", "CRC32"])
            self.tbl_identified.itemSelectionChanged.connect(self._show_selected_detail)

            self.tbl_unidentified = QTableWidget(0, 4)
            self.tbl_unidentified.setHorizontalHeaderLabels(["Arquivo", "Caminho", "Tamanho", "CRC32"])
            self.tbl_unidentified.itemSelectionChanged.connect(self._show_selected_detail)

            self.library_lists.addTab(self.tbl_identified, _tr("tab_identified"))
            self.library_lists.addTab(self.tbl_unidentified, _tr("tab_unidentified"))
            left_layout.addWidget(self.library_lists)

            right = QWidget()
            right_layout = QFormLayout(right)
            self.detail_name = QLabel("-")
            self.detail_system = QLabel("-")
            self.detail_region = QLabel("-")
            self.detail_size = QLabel("-")
            self.detail_crc = QLabel("-")
            self.detail_path = QLabel("-")
            right_layout.addRow("Nome", self.detail_name)
            right_layout.addRow("Sistema", self.detail_system)
            right_layout.addRow("Região", self.detail_region)
            right_layout.addRow("Tamanho", self.detail_size)
            right_layout.addRow("CRC32", self.detail_crc)
            right_layout.addRow("Caminho", self.detail_path)

            splitter.addWidget(left)
            splitter.addWidget(right)
            splitter.setSizes([850, 350])
            layout.addWidget(splitter)

            btns = QHBoxLayout()
            self.btn_organize = QPushButton(_tr("btn_organize"))
            self.btn_organize.clicked.connect(self._organize_identified)
            btns.addWidget(self.btn_organize)
            btns.addStretch(1)
            layout.addLayout(btns)

        def _build_import_tab(self) -> None:
            layout = QVBoxLayout(self.import_tab)

            dat_group = QGroupBox(_tr("flet_dat_files"))
            dat_layout = QVBoxLayout(dat_group)
            self.dat_list = QListWidget()
            dat_layout.addWidget(self.dat_list)
            dat_btns = QHBoxLayout()
            add_dat = QPushButton(_tr("flet_add_dat"))
            add_dat.clicked.connect(self._add_dat_files)
            remove_dat = QPushButton(_tr("flet_remove_selected"))
            remove_dat.clicked.connect(self._remove_selected_dat)
            dat_btns.addWidget(add_dat)
            dat_btns.addWidget(remove_dat)
            dat_btns.addStretch(1)
            dat_layout.addLayout(dat_btns)

            scan_group = QGroupBox(_tr("flet_scan_folder"))
            scan_layout = QVBoxLayout(scan_group)
            folder_row = QHBoxLayout()
            self.lbl_folder = QLabel(_tr("flet_no_folder"))
            choose_folder = QPushButton(_tr("flet_browse"))
            choose_folder.clicked.connect(self._choose_folder)
            folder_row.addWidget(self.lbl_folder, 1)
            folder_row.addWidget(choose_folder)
            scan_layout.addLayout(folder_row)

            opt_row = QHBoxLayout()
            self.chk_recursive = QCheckBox(_tr("recursive"))
            self.chk_recursive.setChecked(True)
            self.chk_archives = QCheckBox(_tr("scan_archives"))
            self.chk_archives.setChecked(True)
            opt_row.addWidget(self.chk_recursive)
            opt_row.addWidget(self.chk_archives)
            opt_row.addStretch(1)
            scan_layout.addLayout(opt_row)

            run_row = QHBoxLayout()
            self.btn_scan = QPushButton(_tr("btn_scan"))
            self.btn_scan.clicked.connect(self._scan_folder)
            self.scan_progress = QProgressBar()
            self.scan_progress.setValue(0)
            run_row.addWidget(self.btn_scan)
            run_row.addWidget(self.scan_progress, 1)
            scan_layout.addLayout(run_row)

            layout.addWidget(dat_group)
            layout.addWidget(scan_group)
            layout.addStretch(1)

        def _build_logs_tab(self) -> None:
            layout = QVBoxLayout(self.logs_tab)
            self.log_text = QTextEdit()
            self.log_text.setReadOnly(True)
            layout.addWidget(self.log_text)

        def _build_missing_tab(self) -> None:
            layout = QVBoxLayout(self.missing_tab)
            self.tbl_missing = QTableWidget(0, 5)
            self.tbl_missing.setHorizontalHeaderLabels(["ROM", "Game", "System", "Region", "Size"])
            layout.addWidget(self.tbl_missing)
            row = QHBoxLayout()
            export_btn = QPushButton("Export Missing Report")
            export_btn.clicked.connect(self._export_missing_report)
            row.addWidget(export_btn)
            row.addStretch(1)
            layout.addLayout(row)

        def _build_myrient_tab(self) -> None:
            layout = QVBoxLayout(self.myrient_tab)
            for src in KNOWN_SOURCES:
                box = QGroupBox(src["name"])
                row = QHBoxLayout(box)
                row.addWidget(QLabel(src.get("description", "")), 1)
                open_btn = QPushButton(_tr("open_page"))
                open_btn.clicked.connect(lambda _=False, url=src["url"]: webbrowser.open(url))
                row.addWidget(open_btn)
                layout.addWidget(box)
            layout.addStretch(1)

        def _build_settings_tab(self) -> None:
            layout = QFormLayout(self.settings_tab)
            self.cmb_language = QComboBox()
            self.cmb_language.addItem("English", LANG_EN)
            self.cmb_language.addItem("Português (Brasil)", LANG_PT_BR)
            current_lang = self.state.settings.get("language", LANG_EN)
            idx = self.cmb_language.findData(current_lang)
            if idx >= 0:
                self.cmb_language.setCurrentIndex(idx)

            self.cmb_profile = QComboBox()
            for name in PROFILE_PRESETS.keys():
                self.cmb_profile.addItem(name, name)
            active_profile = self.state.settings.get("active_profile", "retroarch_frontend")
            idx_profile = self.cmb_profile.findData(active_profile)
            if idx_profile >= 0:
                self.cmb_profile.setCurrentIndex(idx_profile)

            save_btn = QPushButton("Save Settings")
            save_btn.clicked.connect(self._save_settings)

            layout.addRow("Language", self.cmb_language)
            layout.addRow("Profile", self.cmb_profile)
            layout.addRow("", save_btn)

        def _push_status(self, message: str) -> None:
            self.status.showMessage(message, 5000)
            self.state.log(message)
            self.log_text.setPlainText("\n".join(self.state.activity_log[-200:]))

        def _add_dat_files(self) -> None:
            files, _ = QFileDialog.getOpenFileNames(
                self,
                _tr("flet_add_dat"),
                "",
                "DAT/XML (*.dat *.xml *.zip *.gz);;All files (*)",
            )
            if not files:
                return

            for path in files:
                try:
                    dat_info, roms = DATParser.parse_with_info(path)
                    self.state.multi_matcher.add_dat(dat_info, roms)
                    self._push_status(f"Loaded DAT: {dat_info.name} ({len(roms)} ROMs)")
                except Exception as exc:
                    QMessageBox.warning(self, "DAT", f"Failed to load {path}\n{exc}")
            self._refresh_all()

        def _remove_selected_dat(self) -> None:
            row = self.dat_list.currentRow()
            if row < 0:
                return
            item = self.dat_list.item(row)
            dat_id = item.data(Qt.UserRole)
            self.state.multi_matcher.remove_dat(dat_id)
            self._push_status(f"Removed DAT: {item.text()}")
            self._refresh_all()

        def _choose_folder(self) -> None:
            folder = QFileDialog.getExistingDirectory(self, _tr("flet_scan_folder"), self.current_folder or os.path.expanduser("~"))
            if not folder:
                return
            self.current_folder = folder
            self.lbl_folder.setText(folder)

        def _scan_folder(self) -> None:
            if not self.current_folder:
                QMessageBox.information(self, "Scan", _tr("flet_no_folder"))
                return
            if not self.state.multi_matcher.get_dat_list():
                QMessageBox.information(self, "Scan", "Load at least one DAT file first.")
                return
            if self.scan_worker and self.scan_worker.isRunning():
                return

            self.scan_progress.setValue(0)
            self.btn_scan.setEnabled(False)
            self._push_status("Scanning files...")

            self.scan_worker = ScanWorker(
                self.current_folder,
                recursive=self.chk_recursive.isChecked(),
                scan_archives=self.chk_archives.isChecked(),
            )
            self.scan_worker.progress.connect(self._on_scan_progress)
            self.scan_worker.finished_scan.connect(self._on_scan_finished)
            self.scan_worker.failed.connect(self._on_scan_failed)
            self.scan_worker.start()

        def _on_scan_progress(self, current: int, total: int) -> None:
            value = int((current / total) * 100) if total else 0
            self.scan_progress.setValue(value)
            self._push_status(f"Scanning {current}/{total}")

        def _on_scan_failed(self, error: str) -> None:
            self.btn_scan.setEnabled(True)
            QMessageBox.critical(self, "Scan failed", error)
            self._push_status(f"Scan failed: {error}")

        def _on_scan_finished(self, scanned_files: List[ScannedFile]) -> None:
            self.btn_scan.setEnabled(True)
            identified, unidentified = self.state.multi_matcher.match_all(scanned_files)
            self.state.identified = identified
            self.state.unidentified = unidentified
            self._push_status(
                f"Scan done. Identified: {len(identified)} | Unidentified: {len(unidentified)}"
            )
            self._refresh_all()

        def _organize_identified(self) -> None:
            if not self.state.identified:
                QMessageBox.information(self, "Organize", "No identified ROMs to organize.")
                return
            output_dir = QFileDialog.getExistingDirectory(self, "Choose output folder")
            if not output_dir:
                return

            profile = get_effective_profile(self.state.settings)
            strategy = profile.get("strategy", "system")
            actions = self.state.organizer.organize(
                self.state.identified,
                output_dir=output_dir,
                strategy=strategy,
                action="copy",
            )
            self._push_status(f"Organized {len(actions)} ROM(s) using strategy '{strategy}'.")
            QMessageBox.information(self, "Organize", f"Done: {len(actions)} file(s).")

        def _export_missing_report(self) -> None:
            if not self.state.multi_matcher.dat_infos:
                QMessageBox.information(self, "Missing", "No DAT loaded.")
                return

            report = self.state.reporter.generate_multi_report(
                self.state.multi_matcher.dat_infos,
                self.state.multi_matcher.all_roms,
                self.state.identified,
            )
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Export missing report",
                "missing_report.json",
                "JSON (*.json);;CSV (*.csv);;Text (*.txt)",
            )
            if not path:
                return
            if path.endswith(".csv"):
                self.state.reporter.export_csv(report, path)
            elif path.endswith(".txt"):
                self.state.reporter.export_txt(report, path)
            else:
                if not path.endswith(".json"):
                    path = f"{path}.json"
                self.state.reporter.export_json(report, path)
            self._push_status(f"Exported report: {path}")

        def _save_settings(self) -> None:
            lang = self.cmb_language.currentData()
            profile = self.cmb_profile.currentData()
            self.state.settings["language"] = lang
            self.state.settings["active_profile"] = profile
            save_settings(self.state.settings)
            apply_runtime_settings(self.state.settings)
            _set_language(lang)
            self._push_status("Settings saved.")

        def _refresh_dat_list(self) -> None:
            self.dat_list.clear()
            for dat_info in self.state.multi_matcher.get_dat_list():
                item = QListWidgetItem(f"{dat_info.name} ({dat_info.rom_count})")
                item.setData(Qt.UserRole, dat_info.id)
                self.dat_list.addItem(item)

        def _refresh_library_tables(self) -> None:
            self.tbl_identified.setRowCount(len(self.state.identified))
            for row, scanned in enumerate(self.state.identified):
                rom = scanned.matched_rom
                self.tbl_identified.setItem(row, 0, QTableWidgetItem(scanned.filename))
                self.tbl_identified.setItem(row, 1, QTableWidgetItem((rom.game_name if rom else scanned.filename)))
                self.tbl_identified.setItem(row, 2, QTableWidgetItem((rom.system_name if rom else "")))
                self.tbl_identified.setItem(row, 3, QTableWidgetItem((rom.region if rom else "")))
                self.tbl_identified.setItem(row, 4, QTableWidgetItem(scanned.crc32.upper()))

            self.tbl_unidentified.setRowCount(len(self.state.unidentified))
            for row, scanned in enumerate(self.state.unidentified):
                self.tbl_unidentified.setItem(row, 0, QTableWidgetItem(scanned.filename))
                self.tbl_unidentified.setItem(row, 1, QTableWidgetItem(scanned.path))
                self.tbl_unidentified.setItem(row, 2, QTableWidgetItem(format_size(scanned.size)))
                self.tbl_unidentified.setItem(row, 3, QTableWidgetItem(scanned.crc32.upper()))

        def _refresh_missing(self) -> None:
            all_missing: List[Dict[str, Any]] = []
            for dat_id, dat_info in self.state.multi_matcher.dat_infos.items():
                roms = self.state.multi_matcher.all_roms.get(dat_id, [])
                dat_identified = [
                    f for f in self.state.identified
                    if f.matched_rom and f.matched_rom.dat_id == dat_id
                ]
                rep = self.state.reporter.generate_report(dat_info, roms, dat_identified)
                for item in rep["missing"]:
                    all_missing.append({"system": rep.get("system_name", ""), **item})

            self.tbl_missing.setRowCount(len(all_missing))
            for row, item in enumerate(all_missing):
                self.tbl_missing.setItem(row, 0, QTableWidgetItem(item.get("name", "")))
                self.tbl_missing.setItem(row, 1, QTableWidgetItem(item.get("game_name", "")))
                self.tbl_missing.setItem(row, 2, QTableWidgetItem(item.get("system", "")))
                self.tbl_missing.setItem(row, 3, QTableWidgetItem(item.get("region", "")))
                self.tbl_missing.setItem(row, 4, QTableWidgetItem(item.get("size_formatted", "")))

        def _refresh_dashboard(self) -> None:
            missing_count = self.tbl_missing.rowCount()
            self.lbl_dats.setText(f"DATs loaded: {len(self.state.multi_matcher.get_dat_list())}")
            self.lbl_identified.setText(f"Identified: {len(self.state.identified)}")
            self.lbl_unidentified.setText(f"Unidentified: {len(self.state.unidentified)}")
            self.lbl_missing.setText(f"Missing: {missing_count}")

        def _refresh_all(self) -> None:
            self._refresh_dat_list()
            self._refresh_library_tables()
            self._refresh_missing()
            self._refresh_dashboard()

        def _show_selected_detail(self) -> None:
            scanned: Optional[ScannedFile] = None
            if self.library_lists.currentWidget() is self.tbl_identified:
                row = self.tbl_identified.currentRow()
                if row >= 0 and row < len(self.state.identified):
                    scanned = self.state.identified[row]
            else:
                row = self.tbl_unidentified.currentRow()
                if row >= 0 and row < len(self.state.unidentified):
                    scanned = self.state.unidentified[row]

            if not scanned:
                self.detail_name.setText("-")
                self.detail_system.setText("-")
                self.detail_region.setText("-")
                self.detail_size.setText("-")
                self.detail_crc.setText("-")
                self.detail_path.setText("-")
                return

            rom: Optional[ROMInfo] = scanned.matched_rom
            self.detail_name.setText(rom.game_name if rom else scanned.filename)
            self.detail_system.setText(rom.system_name if rom else "-")
            self.detail_region.setText(rom.region if rom else "-")
            self.detail_size.setText(format_size(scanned.size))
            self.detail_crc.setText(scanned.crc32.upper())
            self.detail_path.setText(scanned.path)

    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_pyside6_gui())
