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
from .shared_config import STRATEGIES, THEME, THUMBNAILS_DIR
from .thumbnail_service import ThumbnailService
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


MOCHA = {
    "text":     THEME["text"],
    "subtext0": THEME["subtext0"],
    "subtext1": THEME["subtext1"],
    "surface0": THEME["surface0"],
    "surface1": THEME["surface1"],
    "base":     THEME["bg"],
    "crust":    THEME["bg_deep"],
    "blue":     THEME["secondary"],
    "green":    THEME["success"],
    "mauve":    THEME["primary"],
    "red":      THEME["error"],
    "yellow":   THEME["warning"],
}


def run_pyside6_gui() -> int:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QAction, QPixmap, QStandardItem, QStandardItemModel
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
            QSplitter,
            QStackedWidget,
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
            self._thumb_svc = ThumbnailService(THUMBNAILS_DIR)

            self._apply_theme()
            self._setup_menu()
            self._build_ui()
            self._refresh_all()

        def _apply_theme(self) -> None:
            self.setStyleSheet(
                f"""
                QMainWindow, QWidget {{ background-color: {MOCHA['base']}; color: {MOCHA['text']}; font-family: 'Inter', 'Segoe UI', sans-serif; }}
                QGroupBox {{ border: 1px solid {MOCHA['surface1']}; border-radius: 12px; margin-top: 8px; padding: 8px; }}
                QPushButton {{ background-color: {MOCHA['surface1']}; color: {MOCHA['text']}; border-radius: 8px; padding: 8px 12px; }}
                QPushButton:hover {{ background-color: {MOCHA['mauve']}; color: {MOCHA['crust']}; }}
                QPushButton:disabled {{ color: {MOCHA['subtext0']}; }}
                QTableWidget, QListWidget, QTextEdit, QComboBox {{
                    background-color: {MOCHA['surface0']};
                    border: 1px solid {MOCHA['surface1']};
                    border-radius: 6px;
                    selection-background-color: {MOCHA['blue']};
                    selection-color: {MOCHA['crust']};
                }}
                QTabBar::tab {{ background: {MOCHA['surface0']}; padding: 8px 14px; margin-right: 3px; border-radius: 6px 6px 0 0; }}
                QTabBar::tab:selected {{ background: {MOCHA['mauve']}; color: {MOCHA['crust']}; }}
                QHeaderView::section {{ background-color: {MOCHA['base']}; color: {MOCHA['mauve']}; border: none; padding: 6px; font-weight: bold; }}
                QScrollBar:vertical {{ background: {MOCHA['surface0']}; width: 8px; border-radius: 4px; }}
                QScrollBar::handle:vertical {{ background: {MOCHA['surface1']}; border-radius: 4px; }}
                """
            )

        def _create_empty_state(self, icon_text, heading, subtext, cta_label=None, on_cta=None):
            """Create a centered empty state widget."""
            widget = QWidget(self)
            layout = QVBoxLayout(widget)
            layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.setSpacing(12)

            icon = QLabel(icon_text)
            icon.setStyleSheet(f"font-size: 64px; color: {MOCHA['subtext0']};")
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(icon)

            title = QLabel(heading)
            title.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {MOCHA['text']};")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(title)

            sub = QLabel(subtext)
            sub.setStyleSheet(f"font-size: 13px; color: {MOCHA['subtext0']};")
            sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(sub)

            if cta_label and on_cta:
                btn = QPushButton(cta_label)
                btn.setStyleSheet(f"""
                    background-color: {MOCHA['mauve']};
                    color: {MOCHA['crust']};
                    border-radius: 8px;
                    padding: 10px 24px;
                    font-weight: bold;
                    font-size: 14px;
                """)
                btn.clicked.connect(on_cta)
                layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

            return widget

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

            self.tabs = QTabWidget()
            base.addWidget(self.tabs, 1)

            # ── Tab 0: DATs & Scan ──────────────────────────────────
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

            self.tabs.addTab(scan_tab, "DATs e Scan")

            # ── Tab 1: Library (with empty state + detail panel) ────
            self.library_stack = QStackedWidget()

            # Empty state page
            self.library_empty = self._create_empty_state(
                "\U0001F3AE", "No ROMs Loaded",
                "Load a DAT file and scan your ROM folder to get started",
                "Go to Import", lambda: self.tabs.setCurrentIndex(2)
            )
            self.library_stack.addWidget(self.library_empty)

            # Content page: splitter with tables on left, detail panel on right
            library_content = QSplitter(Qt.Orientation.Horizontal)

            # Left side: tables
            tables_widget = QWidget()
            results_layout = QVBoxLayout(tables_widget)
            results_layout.setContentsMargins(0, 0, 0, 0)

            self.identified_table = QTableView()
            self.identified_model = QStandardItemModel(0, 8, self)
            self.identified_model.setHorizontalHeaderLabels([
                "Original File", "ROM Name", "Game", "System", "Region", "Size", "CRC32", "Status"
            ])
            self.identified_table.setModel(self.identified_model)
            self.identified_table.clicked.connect(self._on_identified_row_clicked)
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

            library_content.addWidget(tables_widget)

            # Right side: detail panel with thumbnail
            detail_panel = QWidget()
            detail_layout = QVBoxLayout(detail_panel)
            detail_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

            self.detail_art = QLabel()
            self.detail_art.setFixedSize(200, 240)
            self.detail_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.detail_art.setStyleSheet(
                f"background-color: {MOCHA['surface0']}; border-radius: 8px;"
            )
            detail_layout.addWidget(self.detail_art, alignment=Qt.AlignmentFlag.AlignCenter)

            self.detail_game_label = QLabel("")
            self.detail_game_label.setStyleSheet(
                f"font-size: 16px; font-weight: bold; color: {MOCHA['text']};"
            )
            self.detail_game_label.setWordWrap(True)
            self.detail_game_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            detail_layout.addWidget(self.detail_game_label)

            self.detail_system_label = QLabel("")
            self.detail_system_label.setStyleSheet(
                f"font-size: 13px; color: {MOCHA['subtext0']};"
            )
            self.detail_system_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            detail_layout.addWidget(self.detail_system_label)

            self.detail_info_label = QLabel("")
            self.detail_info_label.setStyleSheet(
                f"font-size: 12px; color: {MOCHA['subtext1']};"
            )
            self.detail_info_label.setWordWrap(True)
            self.detail_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            detail_layout.addWidget(self.detail_info_label)

            detail_layout.addStretch(1)
            detail_panel.setMinimumWidth(230)

            library_content.addWidget(detail_panel)
            library_content.setStretchFactor(0, 3)
            library_content.setStretchFactor(1, 1)

            self.library_stack.addWidget(library_content)
            self.library_stack.setCurrentIndex(0)  # Show empty by default

            self.tabs.addTab(self.library_stack, "Resultados")

            # ── Tab 2: Organize ─────────────────────────────────────
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
            self.tabs.addTab(organize_tab, "Organizar")

        def _on_identified_row_clicked(self, index):
            """Update the detail panel when a row in the identified table is clicked."""
            row = index.row()
            if row < 0 or row >= len(self.identified):
                return
            scanned = self.identified[row]
            rom = scanned.matched_rom
            if not rom:
                return

            game_name = rom.game_name or ""
            system = rom.system_name or ""

            # Update text labels
            self.detail_game_label.setText(game_name)
            self.detail_system_label.setText(system)
            self.detail_info_label.setText(
                f"Region: {rom.region}\n"
                f"Size: {format_size(scanned.size)}\n"
                f"CRC32: {scanned.crc32.upper()}"
            )

            # Update thumbnail
            thumb_path = self._thumb_svc.get_thumbnail_path(system, game_name)
            if thumb_path:
                pixmap = QPixmap(thumb_path).scaled(
                    200, 240,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.detail_art.setPixmap(pixmap)
                self.detail_art.setStyleSheet(
                    f"background-color: {MOCHA['surface0']}; border-radius: 8px;"
                )
            else:
                initial = game_name[0].upper() if game_name else "?"
                self.detail_art.clear()
                self.detail_art.setText(initial)
                self.detail_art.setStyleSheet(
                    f"background-color: {MOCHA['surface0']}; border-radius: 8px; "
                    f"font-size: 48px; font-weight: bold; color: {MOCHA['subtext0']};"
                )

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

            # Toggle library empty state vs content
            has_data = len(self.identified) > 0 or len(self.unidentified) > 0
            self.library_stack.setCurrentIndex(1 if has_data else 0)

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
    win = PySideROMManager()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_pyside6_gui())
