"""PySide6 desktop interface for R0MM with full workflow support."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Any

from .models import Collection
from .parser import DATParser
from .scanner import FileScanner
from .matcher import MultiROMMatcher
from .organizer import Organizer
from .collection import CollectionManager
from .reporter import MissingROMReporter
from .utils import format_size
from .shared_config import STRATEGIES
from .blindmatch import build_blindmatch_rom
from . import i18n as _i18n
from . import __version__


LANG_EN = getattr(_i18n, "LANG_EN", "en")
LANG_PT_BR = getattr(_i18n, "LANG_PT_BR", "pt-BR")


def _tr(key: str, **kwargs: Any) -> str:
    func = getattr(_i18n, "tr", None)
    if callable(func):
        return func(key, **kwargs)
    return key


DARK_QSS = """
QWidget { background: #1e1e2e; color: #cdd6f4; }
QMainWindow { background: #181825; }
QLineEdit, QComboBox, QTableView, QListWidget, QPlainTextEdit {
    background: #313244; border: 1px solid #45475a; border-radius: 8px; padding: 6px;
}
QPushButton { background: #45475a; border-radius: 8px; padding: 8px 12px; }
QPushButton#Primary { background: #89b4fa; color: #11111b; font-weight: 700; }
QTabWidget::pane { border: 1px solid #45475a; top: -1px; }
QHeaderView::section { background: #313244; color: #cdd6f4; border: none; padding: 4px; }
"""


def run_pyside6_gui() -> int:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QAction, QStandardItem, QStandardItemModel
        from PySide6.QtWidgets import (
            QApplication,
            QComboBox,
            QFileDialog,
            QFormLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QListWidget,
            QMainWindow,
            QMessageBox,
            QPlainTextEdit,
            QPushButton,
            QTabWidget,
            QTableView,
            QVBoxLayout,
            QWidget,
            QInputDialog,
        )
    except ImportError as exc:
        print("Error: PySide6 is required for this interface")
        print("Install it with: pip install PySide6")
        print(f"Details: {exc}")
        return 1

    class PySideROMManager(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle(f"R0MM {__version__} (PySide6)")
            self.resize(1320, 860)

            self.matcher = MultiROMMatcher()
            self.organizer = Organizer()
            self.collection_manager = CollectionManager()
            self.reporter = MissingROMReporter()
            self.scanned_files = []
            self.identified = []
            self.unidentified = []

            self._setup_menu()
            self._build_ui()
            self._refresh_all()

        def _setup_menu(self):
            file_menu = self.menuBar().addMenu(_tr("menu_file"))

            save_action = QAction(_tr("menu_save_collection"), self)
            save_action.triggered.connect(self._save_collection)
            file_menu.addAction(save_action)

            load_action = QAction(_tr("menu_open_collection"), self)
            load_action.triggered.connect(self._load_collection)
            file_menu.addAction(load_action)

            file_menu.addSeparator()

            export_txt = QAction(_tr("menu_export_missing_txt"), self)
            export_txt.triggered.connect(lambda: self._export_missing("txt"))
            file_menu.addAction(export_txt)

            export_csv = QAction(_tr("menu_export_missing_csv"), self)
            export_csv.triggered.connect(lambda: self._export_missing("csv"))
            file_menu.addAction(export_csv)

            export_json = QAction(_tr("menu_export_missing_json"), self)
            export_json.triggered.connect(lambda: self._export_missing("json"))
            file_menu.addAction(export_json)

            file_menu.addSeparator()
            file_menu.addAction(_tr("menu_exit"), self.close)

        def _build_ui(self):
            root = QWidget()
            self.setCentralWidget(root)
            base = QVBoxLayout(root)

            self.stats_label = QLabel()
            self.stats_label.setStyleSheet("font-size: 14px; font-weight: 600;")
            base.addWidget(self.stats_label)

            tabs = QTabWidget()
            base.addWidget(tabs, 1)

            scan_tab = QWidget()
            scan_layout = QVBoxLayout(scan_tab)

            top_row = QHBoxLayout()
            self.dat_list = QListWidget()
            self.dat_list.setMinimumWidth(320)
            top_row.addWidget(self.dat_list, 2)

            dat_controls = QVBoxLayout()
            load_dat = QPushButton("Load DAT")
            load_dat.setObjectName("Primary")
            load_dat.clicked.connect(self._load_dat)
            dat_controls.addWidget(load_dat)

            remove_dat = QPushButton("Remove selected DAT")
            remove_dat.clicked.connect(self._remove_selected_dat)
            dat_controls.addWidget(remove_dat)

            scan_folder_btn = QPushButton("Scan ROM folder")
            scan_folder_btn.setObjectName("Primary")
            scan_folder_btn.clicked.connect(self._scan_folder)
            dat_controls.addWidget(scan_folder_btn)

            force_match_btn = QPushButton("BlindMatch (best effort)")
            force_match_btn.clicked.connect(self._blindmatch_selected)
            dat_controls.addWidget(force_match_btn)
            dat_controls.addStretch(1)

            top_row.addLayout(dat_controls, 1)
            scan_layout.addLayout(top_row)

            tabs.addTab(scan_tab, "DATs e Scan")

            results_tab = QWidget()
            results_layout = QVBoxLayout(results_tab)

            self.identified_table = QTableView()
            self.identified_model = QStandardItemModel(0, 8, self)
            self.identified_model.setHorizontalHeaderLabels([
                "Original File", "ROM Name", "Game", "System", "Region", "Size", "CRC32", "Status"
            ])
            self.identified_table.setModel(self.identified_model)
            results_layout.addWidget(QLabel("Identified"))
            results_layout.addWidget(self.identified_table, 1)

            self.unidentified_table = QTableView()
            self.unidentified_model = QStandardItemModel(0, 4, self)
            self.unidentified_model.setHorizontalHeaderLabels(["Filename", "Path", "Size", "CRC32"])
            self.unidentified_table.setModel(self.unidentified_model)
            results_layout.addWidget(QLabel("Unidentified"))
            results_layout.addWidget(self.unidentified_table, 1)

            self.missing_table = QTableView()
            self.missing_model = QStandardItemModel(0, 5, self)
            self.missing_model.setHorizontalHeaderLabels(["ROM Name", "Game", "System", "Region", "Size"])
            self.missing_table.setModel(self.missing_model)
            results_layout.addWidget(QLabel("Missing"))
            results_layout.addWidget(self.missing_table, 1)

            tabs.addTab(results_tab, "Resultados")

            organize_tab = QWidget()
            organize_layout = QVBoxLayout(organize_tab)
            form = QFormLayout()

            self.output_edit = QLineEdit()
            out_btn = QPushButton("Browse")
            out_btn.clicked.connect(self._choose_output_folder)
            out_row = QHBoxLayout()
            out_row.addWidget(self.output_edit, 1)
            out_row.addWidget(out_btn)
            out_wrap = QWidget()
            out_wrap.setLayout(out_row)
            form.addRow("Output folder", out_wrap)

            self.strategy_combo = QComboBox()
            for strategy in STRATEGIES:
                self.strategy_combo.addItem(f"{strategy['name']} ({strategy['desc']})", strategy["id"])
            form.addRow("Strategy", self.strategy_combo)

            self.action_combo = QComboBox()
            self.action_combo.addItem("Copy", "copy")
            self.action_combo.addItem("Move", "move")
            form.addRow("Action", self.action_combo)

            organize_layout.addLayout(form)

            button_row = QHBoxLayout()
            preview_btn = QPushButton("Preview")
            preview_btn.clicked.connect(self._preview_organization)
            organize_btn = QPushButton("Organize")
            organize_btn.setObjectName("Primary")
            organize_btn.clicked.connect(self._run_organization)
            undo_btn = QPushButton("Undo last")
            undo_btn.clicked.connect(self._undo_last)
            button_row.addWidget(preview_btn)
            button_row.addWidget(organize_btn)
            button_row.addWidget(undo_btn)
            button_row.addStretch(1)
            organize_layout.addLayout(button_row)

            self.log_box = QPlainTextEdit()
            self.log_box.setReadOnly(True)
            organize_layout.addWidget(self.log_box, 1)
            tabs.addTab(organize_tab, "Organizar")

        def _log(self, msg: str):
            stamp = datetime.now().strftime("%H:%M:%S")
            self.log_box.appendPlainText(f"[{stamp}] {msg}")

        def _refresh_all(self):
            self._refresh_dat_list()
            self._refresh_results_tables()
            self._refresh_missing_table()
            completeness = self.matcher.get_completeness(self.identified)
            self.stats_label.setText(
                f"DATs: {len(self.matcher.get_dat_list())} | "
                f"Scanned: {len(self.scanned_files)} | "
                f"Identified: {len(self.identified)} | "
                f"Unidentified: {len(self.unidentified)} | "
                f"Completeness: {completeness['percentage']:.1f}%"
            )

        def _refresh_dat_list(self):
            self.dat_list.clear()
            for dat in self.matcher.get_dat_list():
                self.dat_list.addItem(f"{dat.name} ({dat.rom_count} ROMs) [{dat.id}]")

        def _refresh_results_tables(self):
            self.identified_model.setRowCount(0)
            for scanned in self.identified:
                rom = scanned.matched_rom
                if not rom:
                    continue
                self.identified_model.appendRow([
                    QStandardItem(scanned.filename),
                    QStandardItem(rom.name),
                    QStandardItem(rom.game_name),
                    QStandardItem(rom.system_name),
                    QStandardItem(rom.region),
                    QStandardItem(format_size(scanned.size)),
                    QStandardItem(scanned.crc32.upper()),
                    QStandardItem("matched" if not scanned.forced else "blindmatch"),
                ])

            self.unidentified_model.setRowCount(0)
            for scanned in self.unidentified:
                self.unidentified_model.appendRow([
                    QStandardItem(scanned.filename),
                    QStandardItem(scanned.path),
                    QStandardItem(format_size(scanned.size)),
                    QStandardItem(scanned.crc32.upper()),
                ])

        def _refresh_missing_table(self):
            self.missing_model.setRowCount(0)
            for rom in self.matcher.get_missing(self.identified):
                self.missing_model.appendRow([
                    QStandardItem(rom.name),
                    QStandardItem(rom.game_name),
                    QStandardItem(rom.system_name),
                    QStandardItem(rom.region),
                    QStandardItem(format_size(rom.size)),
                ])

        def _load_dat(self):
            filepath, _ = QFileDialog.getOpenFileName(self, "Load DAT", "", "DAT/XML (*.dat *.xml *.zip *.gz)")
            if not filepath:
                return
            try:
                dat_info, roms = DATParser.parse_with_info(filepath)
                self.matcher.add_dat(dat_info, roms)
                self._log(f"Loaded DAT: {dat_info.name} ({len(roms)} ROMs)")
                self._refresh_all()
            except Exception as exc:
                QMessageBox.critical(self, "DAT error", str(exc))

        def _remove_selected_dat(self):
            row = self.dat_list.currentRow()
            if row < 0:
                return
            dats = self.matcher.get_dat_list()
            dat_id = dats[row].id
            self.matcher.remove_dat(dat_id)
            self._log(f"Removed DAT: {dats[row].name}")
            self._refresh_all()

        def _scan_folder(self):
            folder = QFileDialog.getExistingDirectory(self, "Select ROM folder")
            if not folder:
                return
            self.statusBar().showMessage("Scanning...")
            QApplication.processEvents()
            try:
                self.scanned_files = FileScanner.scan_folder(folder, recursive=True, scan_archives=True)
                self.identified, self.unidentified = self.matcher.match_all(self.scanned_files)
                self._log(f"Scan completed: {len(self.scanned_files)} files")
                self._refresh_all()
            except Exception as exc:
                QMessageBox.critical(self, "Scan error", str(exc))
            finally:
                self.statusBar().clearMessage()

        def _blindmatch_selected(self):
            system_name, ok = QInputDialog.getText(self, "BlindMatch", "System name:")
            if not ok:
                return
            system_name = (system_name or "").strip()
            if not system_name:
                QMessageBox.warning(self, "BlindMatch", "Please inform a valid system name.")
                return

            folder = QFileDialog.getExistingDirectory(self, "Select ROM folder for BlindMatch")
            if not folder:
                return

            self.statusBar().showMessage("BlindMatch scanning...")
            QApplication.processEvents()
            try:
                scanned_files = FileScanner.scan_folder(folder, recursive=True, scan_archives=True)
                matched_count = 0
                for scanned in scanned_files:
                    scanned.matched_rom = build_blindmatch_rom(scanned, system_name)
                    scanned.forced = True
                    self.identified.append(scanned)
                    matched_count += 1
                self.scanned_files.extend(scanned_files)
                self._log(f"BlindMatch completed: {matched_count} item(s) for system '{system_name}'")
                self._refresh_all()
            except Exception as exc:
                QMessageBox.critical(self, "BlindMatch error", str(exc))
            finally:
                self.statusBar().clearMessage()

        def _choose_output_folder(self):
            folder = QFileDialog.getExistingDirectory(self, "Output folder")
            if folder:
                self.output_edit.setText(folder)

        def _preview_organization(self):
            output = self.output_edit.text().strip()
            if not output:
                QMessageBox.warning(self, "Organize", "Choose output folder.")
                return
            strategy = self.strategy_combo.currentData()
            action = self.action_combo.currentData()
            plan = self.organizer.preview(self.identified, output, strategy, action)
            self._log(
                f"Preview: {plan.total_files} files, {format_size(plan.total_size)}, strategy={strategy}, action={action}"
            )

        def _run_organization(self):
            output = self.output_edit.text().strip()
            if not output:
                QMessageBox.warning(self, "Organize", "Choose output folder.")
                return
            strategy = self.strategy_combo.currentData()
            action = self.action_combo.currentData()
            actions = self.organizer.organize(self.identified, output, strategy, action)
            self._log(f"Organized {len(actions)} files ({action}, {strategy})")
            QMessageBox.information(self, "Organization", f"Done: {len(actions)} files")

        def _undo_last(self):
            ok = self.organizer.undo_last()
            self._log("Undo completed" if ok else "Nothing to undo")

        def _save_collection(self):
            name, ok = QInputDialog.getText(self, "Save collection", "Collection name:")
            if not ok or not name.strip():
                return
            filepath, _ = QFileDialog.getSaveFileName(
                self, "Save collection", f"{name}.romcol.json", "Collection (*.romcol.json)"
            )
            if not filepath:
                return
            collection = Collection(
                name=name.strip(),
                dat_infos=self.matcher.get_dat_list(),
                dat_filepaths=[d.filepath for d in self.matcher.get_dat_list()],
                identified=[s.to_dict() for s in self.identified],
                unidentified=[s.to_dict() for s in self.unidentified],
            )
            self.collection_manager.save(collection, filepath)
            self._log(f"Collection saved: {filepath}")

        def _load_collection(self):
            filepath, _ = QFileDialog.getOpenFileName(self, "Open collection", "", "Collection (*.romcol.json)")
            if not filepath:
                return
            collection = self.collection_manager.load(filepath)
            self.matcher = MultiROMMatcher()
            for dat_path in collection.dat_filepaths:
                if os.path.exists(dat_path):
                    try:
                        dat, roms = DATParser.parse_with_info(dat_path)
                        self.matcher.add_dat(dat, roms)
                    except Exception:
                        pass
            from .models import ScannedFile
            self.identified = [ScannedFile.from_dict(d) for d in collection.identified]
            self.unidentified = [ScannedFile.from_dict(d) for d in collection.unidentified]
            self.scanned_files = [*self.identified, *self.unidentified]
            self._log(f"Collection loaded: {collection.name}")
            self._refresh_all()

        def _export_missing(self, fmt: str):
            if not self.matcher.dat_infos:
                QMessageBox.warning(self, "Export", "Load a DAT first.")
                return
            report = self.reporter.generate_multi_report(
                self.matcher.dat_infos,
                self.matcher.all_roms,
                self.identified,
            )
            filepath, _ = QFileDialog.getSaveFileName(
                self, "Export missing", f"missing_report.{fmt}", f"*.{fmt}"
            )
            if not filepath:
                return
            if fmt == "txt":
                self.reporter.export_txt(report, filepath)
            elif fmt == "csv":
                self.reporter.export_csv(report, filepath)
            else:
                self.reporter.export_json(report, filepath)
            self._log(f"Missing report exported: {filepath}")

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(DARK_QSS)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps)
    win = PySideROMManager()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_pyside6_gui())
