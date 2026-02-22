"""PySide6 desktop interface for R0MM with broad feature parity across app flows."""

from __future__ import annotations

import os
import sys
import webbrowser
from datetime import datetime
from typing import Any, List

from . import i18n as _i18n
from .blindmatch import build_blindmatch_rom
from .collection import CollectionManager
from .dat_library import DATLibrary
from .dat_sources import DATSourceManager
from .health import run_health_checks
from .matcher import MultiROMMatcher
from .metadata import MetadataStore
from .models import Collection, ROMInfo, ScannedFile
from .organizer import Organizer
from .parser import DATParser
from .reporter import MissingROMReporter
from .scanner import FileScanner
from .shared_config import STRATEGIES
from .utils import format_size

LANG_EN = getattr(_i18n, "LANG_EN", "en")
LANG_PT_BR = getattr(_i18n, "LANG_PT_BR", "pt-BR")


def _tr(key: str, **kwargs: Any) -> str:
    func = getattr(_i18n, "tr", None)
    if callable(func):
        return func(key, **kwargs)
    return key


def run_pyside6_gui() -> int:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QApplication,
            QCheckBox,
            QComboBox,
            QFileDialog,
            QFormLayout,
            QGroupBox,
            QHBoxLayout,
            QInputDialog,
            QLabel,
            QLineEdit,
            QListWidget,
            QListWidgetItem,
            QMainWindow,
            QMessageBox,
            QPushButton,
            QSplitter,
            QTableWidget,
            QTableWidgetItem,
            QTextEdit,
            QVBoxLayout,
            QWidget,
        )
    except ImportError as exc:
        print("Error: PySide6 is required for this interface")
        print("Install it with: pip install PySide6")
        print(f"Details: {exc}")
        return 1

    strategy_options = [s["id"] for s in STRATEGIES]

    class ROMManagerPySide6(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("R0MM - PySide6")
            self.resize(1500, 900)

            self.multi_matcher = MultiROMMatcher()
            self.scanned_files: List[ScannedFile] = []
            self.identified: List[ScannedFile] = []
            self.unidentified: List[ScannedFile] = []
            self.organizer = Organizer()
            self.collection_manager = CollectionManager()
            self.reporter = MissingROMReporter()
            self.dat_library = DATLibrary()
            self.dat_sources = DATSourceManager()
            self.metadata_db = ""

            self._build_ui()
            self._refresh_dat_list()
            self._refresh_tables()
            self._refresh_missing_table()
            self._refresh_stats()

        def _build_ui(self):
            root = QWidget()
            self.setCentralWidget(root)
            main = QVBoxLayout(root)

            top = QSplitter(Qt.Horizontal)
            main.addWidget(top, 1)

            left = QWidget()
            left_l = QVBoxLayout(left)
            top.addWidget(left)

            dat_box = QGroupBox("DATs")
            dat_l = QVBoxLayout(dat_box)
            self.dat_list = QListWidget()
            dat_l.addWidget(self.dat_list)
            dat_btns = QHBoxLayout()
            b_add_dat = QPushButton("Adicionar DAT")
            b_add_dat.clicked.connect(self._add_dat)
            b_remove_dat = QPushButton("Remover DAT")
            b_remove_dat.clicked.connect(self._remove_dat)
            b_library = QPushButton("Biblioteca DAT")
            b_library.clicked.connect(self._show_dat_library)
            dat_btns.addWidget(b_add_dat)
            dat_btns.addWidget(b_remove_dat)
            dat_btns.addWidget(b_library)
            dat_l.addLayout(dat_btns)
            left_l.addWidget(dat_box)

            scan_box = QGroupBox("Scanner")
            scan_l = QFormLayout(scan_box)
            self.scan_path = QLineEdit()
            b_scan_path = QPushButton("Selecionar")
            b_scan_path.clicked.connect(self._select_scan_folder)
            scan_row = QHBoxLayout()
            scan_row.addWidget(self.scan_path)
            scan_row.addWidget(b_scan_path)
            scan_l.addRow("Pasta ROMs", scan_row)

            self.scan_archives = QCheckBox("Scan em ZIP")
            self.scan_archives.setChecked(True)
            self.scan_recursive = QCheckBox("Recursivo")
            self.scan_recursive.setChecked(True)
            self.blindmatch = QCheckBox("BlindMatch")
            self.blindmatch_system = QLineEdit()
            self.blindmatch_system.setPlaceholderText("Sistema p/ BlindMatch")
            self.health_check = QCheckBox("Health check")
            self.metadata_path = QLineEdit()
            self.metadata_path.setPlaceholderText("Metadata DB (opcional)")
            b_metadata = QPushButton("Selecionar")
            b_metadata.clicked.connect(self._select_metadata)
            metadata_row = QHBoxLayout()
            metadata_row.addWidget(self.metadata_path)
            metadata_row.addWidget(b_metadata)

            scan_l.addRow(self.scan_archives)
            scan_l.addRow(self.scan_recursive)
            scan_l.addRow(self.blindmatch)
            scan_l.addRow("Sistema", self.blindmatch_system)
            scan_l.addRow(self.health_check)
            scan_l.addRow("Metadata", metadata_row)
            b_scan = QPushButton("Scan + Match")
            b_scan.clicked.connect(self._scan_and_match)
            scan_l.addRow(b_scan)
            left_l.addWidget(scan_box)

            coll_box = QGroupBox("Coleção")
            coll_l = QVBoxLayout(coll_box)
            b_save_col = QPushButton("Salvar coleção")
            b_save_col.clicked.connect(self._save_collection)
            b_load_col = QPushButton("Carregar coleção")
            b_load_col.clicked.connect(self._load_collection)
            b_new = QPushButton("Nova sessão")
            b_new.clicked.connect(self._new_session)
            coll_l.addWidget(b_save_col)
            coll_l.addWidget(b_load_col)
            coll_l.addWidget(b_new)
            left_l.addWidget(coll_box)
            left_l.addStretch(1)

            center = QWidget()
            center_l = QVBoxLayout(center)
            top.addWidget(center)

            self.stats_label = QLabel("Sem dados")
            center_l.addWidget(self.stats_label)

            self.search_input = QLineEdit()
            self.search_input.setPlaceholderText("Pesquisar nome/crc/sistema")
            self.search_input.textChanged.connect(self._refresh_tables)
            center_l.addWidget(self.search_input)

            self.id_table = QTableWidget(0, 6)
            self.id_table.setHorizontalHeaderLabels(["Arquivo", "Sistema", "Jogo", "Região", "CRC32", "Status"])
            center_l.addWidget(QLabel("Identificados"))
            center_l.addWidget(self.id_table, 1)

            un_toolbar = QHBoxLayout()
            b_force = QPushButton("Forçar Identificação")
            b_force.clicked.connect(self._force_identified)
            un_toolbar.addWidget(b_force)
            un_toolbar.addStretch(1)
            center_l.addLayout(un_toolbar)

            self.un_table = QTableWidget(0, 3)
            self.un_table.setHorizontalHeaderLabels(["Arquivo", "Tamanho", "CRC32"])
            self.un_table.setSelectionBehavior(QTableWidget.SelectRows)
            center_l.addWidget(QLabel("Não identificados"))
            center_l.addWidget(self.un_table, 1)

            right = QWidget()
            right_l = QVBoxLayout(right)
            top.addWidget(right)

            missing_toolbar = QHBoxLayout()
            b_missing_refresh = QPushButton("Atualizar missing")
            b_missing_refresh.clicked.connect(self._refresh_missing_table)
            b_search_archive = QPushButton("Buscar no Archive.org")
            b_search_archive.clicked.connect(self._search_archive)
            missing_toolbar.addWidget(b_missing_refresh)
            missing_toolbar.addWidget(b_search_archive)
            missing_toolbar.addStretch(1)
            right_l.addLayout(missing_toolbar)

            self.missing_table = QTableWidget(0, 4)
            self.missing_table.setHorizontalHeaderLabels(["Sistema", "ROM", "Região", "CRC32"])
            self.missing_table.setSelectionBehavior(QTableWidget.SelectRows)
            right_l.addWidget(QLabel("Missing"))
            right_l.addWidget(self.missing_table, 1)

            report_box = QGroupBox("Relatório")
            report_l = QVBoxLayout(report_box)
            b_show_report = QPushButton("Mostrar missing")
            b_show_report.clicked.connect(self._show_missing_report_text)
            b_export_report = QPushButton("Exportar relatório")
            b_export_report.clicked.connect(self._export_report)
            report_l.addWidget(b_show_report)
            report_l.addWidget(b_export_report)
            right_l.addWidget(report_box)

            org_box = QGroupBox("Organizar")
            org_l = QFormLayout(org_box)
            self.output_path = QLineEdit()
            b_output = QPushButton("Selecionar")
            b_output.clicked.connect(self._select_output_folder)
            output_row = QHBoxLayout()
            output_row.addWidget(self.output_path)
            output_row.addWidget(b_output)
            self.strategy = QComboBox()
            self.strategy.addItems(strategy_options)
            self.strategy.setCurrentText("flat")
            self.action = QComboBox()
            self.action.addItems(["copy", "move"])
            b_preview = QPushButton("Preview")
            b_preview.clicked.connect(self._preview)
            b_organize = QPushButton("Organizar")
            b_organize.clicked.connect(self._organize)
            b_undo = QPushButton("Undo")
            b_undo.clicked.connect(self._undo)
            org_l.addRow("Output", output_row)
            org_l.addRow("Strategy", self.strategy)
            org_l.addRow("Action", self.action)
            org_l.addRow(b_preview)
            org_l.addRow(b_organize)
            org_l.addRow(b_undo)
            right_l.addWidget(org_box)

            self.log = QTextEdit()
            self.log.setReadOnly(True)
            main.addWidget(self.log)
            top.setSizes([330, 760, 410])

        def _msg(self, text: str):
            self.log.append(text)

        def _warn(self, title: str, text: str):
            QMessageBox.warning(self, title, text)

        def _info(self, title: str, text: str):
            QMessageBox.information(self, title, text)

        def _select_scan_folder(self):
            path = QFileDialog.getExistingDirectory(self, "Selecionar pasta ROMs")
            if path:
                self.scan_path.setText(path)

        def _select_output_folder(self):
            path = QFileDialog.getExistingDirectory(self, "Selecionar output")
            if path:
                self.output_path.setText(path)

        def _select_metadata(self):
            path, _ = QFileDialog.getOpenFileName(self, "Selecionar metadata DB", "", "JSON (*.json)")
            if path:
                self.metadata_path.setText(path)

        def _add_dat(self):
            files, _ = QFileDialog.getOpenFileNames(self, "Selecionar DAT", "", "DAT/XML (*.dat *.xml);;Todos (*.*)")
            if not files:
                return
            for path in files:
                try:
                    dat_info, roms = DATParser.parse_with_info(path)
                    self.multi_matcher.add_dat(dat_info, roms)
                    self._msg(f"DAT carregado: {dat_info.system_name} ({dat_info.rom_count:,} ROMs)")
                except Exception as exc:
                    self._warn("Erro DAT", f"Falha ao carregar {path}\n{exc}")
            self._refresh_dat_list()
            self._refresh_missing_table()
            self._refresh_stats()

        def _remove_dat(self):
            item = self.dat_list.currentItem()
            if not item:
                return
            dat_id = item.data(Qt.UserRole)
            self.multi_matcher.remove_dat(dat_id)
            self._msg(f"DAT removido: {item.text()}")
            self._refresh_dat_list()
            self._refresh_missing_table()
            self._refresh_stats()

        def _refresh_dat_list(self):
            self.dat_list.clear()
            for dat in self.multi_matcher.get_dat_list():
                item = QListWidgetItem(f"{dat.system_name or dat.name} ({dat.rom_count:,})")
                item.setData(Qt.UserRole, dat.id)
                self.dat_list.addItem(item)

        def _apply_metadata(self):
            metadata_path = self.metadata_path.text().strip()
            if not metadata_path:
                return
            if not os.path.exists(metadata_path):
                self._warn("Metadata", "Arquivo de metadata não encontrado.")
                return
            md = MetadataStore(metadata_path)
            for sc in self.identified:
                if sc.matched_rom:
                    meta = md.lookup(sc.matched_rom.crc32, sc.matched_rom.game_name)
                    if meta:
                        sc.matched_rom.status = f"{sc.matched_rom.status} | curated"

        def _scan_and_match(self):
            roms_path = self.scan_path.text().strip()
            if not roms_path or not os.path.isdir(roms_path):
                self._warn("Scan", "Selecione uma pasta válida de ROMs.")
                return
            if not self.blindmatch.isChecked() and not self.multi_matcher.get_dat_list():
                self._warn("Scan", "Carregue ao menos um DAT ou habilite BlindMatch.")
                return

            self._msg(f"Scanning: {roms_path}")
            self.scanned_files = FileScanner.scan_folder(
                roms_path,
                recursive=self.scan_recursive.isChecked(),
                scan_archives=self.scan_archives.isChecked(),
            )

            if self.health_check.isChecked():
                hc = run_health_checks(self.scanned_files)
                if hc:
                    self._msg("Health check warnings:")
                    for key, vals in hc.items():
                        self._msg(f"  {key}: {len(vals)}")
                else:
                    self._msg("Health check: no issues detected")

            if self.blindmatch.isChecked():
                system_name = self.blindmatch_system.text().strip()
                if not system_name:
                    self._warn("BlindMatch", "Informe o sistema para BlindMatch.")
                    return
                self.identified = []
                for scanned in self.scanned_files:
                    scanned.matched_rom = build_blindmatch_rom(scanned, system_name)
                    self.identified.append(scanned)
                self.unidentified = []
            else:
                self.identified, self.unidentified = self.multi_matcher.match_all(self.scanned_files)

            self._apply_metadata()
            self._msg(f"Scan concluído: {len(self.scanned_files):,} arquivos | {len(self.identified):,} identificados")
            self._refresh_tables()
            self._refresh_missing_table()
            self._refresh_stats()

        def _matches_filter(self, values: List[str]) -> bool:
            query = self.search_input.text().strip().lower()
            if not query:
                return True
            hay = " ".join(str(v or "").lower() for v in values)
            return query in hay

        def _refresh_tables(self):
            self.id_table.setRowCount(0)
            for sc in self.identified:
                rom = sc.matched_rom
                vals = [
                    sc.filename,
                    (rom.system_name if rom else ""),
                    (rom.game_name if rom else ""),
                    (rom.region if rom else ""),
                    sc.crc32,
                    (rom.status if rom else ""),
                ]
                if not self._matches_filter(vals):
                    continue
                row = self.id_table.rowCount()
                self.id_table.insertRow(row)
                for col, val in enumerate(vals):
                    self.id_table.setItem(row, col, QTableWidgetItem(str(val or "")))

            self.un_table.setRowCount(0)
            for sc in self.unidentified:
                vals = [sc.filename, format_size(sc.size), sc.crc32]
                if not self._matches_filter(vals):
                    continue
                row = self.un_table.rowCount()
                self.un_table.insertRow(row)
                for col, val in enumerate(vals):
                    self.un_table.setItem(row, col, QTableWidgetItem(str(val or "")))

        def _refresh_missing_table(self):
            self.missing_table.setRowCount(0)
            missing = self.multi_matcher.get_missing(self.identified)
            for rom in missing:
                vals = [rom.system_name, rom.game_name or rom.name, rom.region, rom.crc32]
                if not self._matches_filter(vals):
                    continue
                row = self.missing_table.rowCount()
                self.missing_table.insertRow(row)
                for col, val in enumerate(vals):
                    self.missing_table.setItem(row, col, QTableWidgetItem(str(val or "")))

        def _refresh_stats(self):
            total = len(self.identified) + len(self.unidentified)
            percent = (len(self.identified) / total * 100) if total else 0
            dat_total = sum(d.rom_count for d in self.multi_matcher.get_dat_list())
            size_total = sum(f.size for f in self.identified)
            self.stats_label.setText(
                f"DATs: {len(self.multi_matcher.get_dat_list())} ({dat_total:,} ROMs) | "
                f"Arquivos: {total:,} | Identificados: {len(self.identified):,} ({percent:.1f}%) | "
                f"Tamanho: {format_size(size_total)}"
            )

        def _force_identified(self):
            rows = sorted({idx.row() for idx in self.un_table.selectionModel().selectedRows()})
            if not rows:
                self._warn("Forçar", "Selecione um ou mais arquivos não identificados.")
                return
            system, ok = QInputDialog.getText(self, "Forçar identificação", "Sistema para BlindMatch:")
            if not ok or not system.strip():
                return

            selected = [self.unidentified[r] for r in rows if r < len(self.unidentified)]
            for sc in selected:
                sc.matched_rom = build_blindmatch_rom(sc, system.strip())
                sc.forced = True
                self.identified.append(sc)
                if sc in self.unidentified:
                    self.unidentified.remove(sc)

            self._msg(f"Forçados para identificados: {len(selected)}")
            self._refresh_tables()
            self._refresh_missing_table()
            self._refresh_stats()

        def _build_report(self):
            infos = self.multi_matcher.get_dat_list()
            if not infos:
                raise ValueError("Nenhum DAT carregado")
            if len(infos) == 1:
                dat_info = infos[0]
                roms = self.multi_matcher.all_roms.get(dat_info.id, [])
                return self.reporter.generate_report(dat_info, roms, self.identified)
            return self.reporter.generate_multi_report(self.multi_matcher.dat_infos, self.multi_matcher.all_roms, self.identified)

        def _show_missing_report_text(self):
            try:
                report = self._build_report()
            except Exception as exc:
                self._warn("Relatório", str(exc))
                return

            if "by_dat" in report:
                text = [
                    "=== Missing ROM Report ===",
                    f"Overall: {report['found_in_all']}/{report['total_in_all_dats']} ({report['overall_percentage']:.1f}%)",
                ]
                for dat_report in report["by_dat"].values():
                    text.append(f"\n--- {dat_report['dat_name']} ---")
                    text.append(f"Found: {dat_report['found']}/{dat_report['total_in_dat']} ({dat_report['percentage']:.1f}%)")
                    text.extend([f"  {m['name']} [{m['region']}]" for m in dat_report['missing'][:20]])
                    if len(dat_report['missing']) > 20:
                        text.append(f"  ... and {len(dat_report['missing']) - 20} more")
            else:
                text = [
                    f"=== Missing ROM Report: {report['dat_name']} ===",
                    f"Found: {report['found']}/{report['total_in_dat']} ({report['percentage']:.1f}%)",
                ]
                text.extend([f"  {m['name']} [{m['region']}]" for m in report["missing"][:50]])
                if len(report["missing"]) > 50:
                    text.append(f"  ... and {len(report['missing']) - 50} more")

            self._info("Relatório", "\n".join(text))

        def _export_report(self):
            try:
                report = self._build_report()
            except Exception as exc:
                self._warn("Relatório", str(exc))
                return

            path, _ = QFileDialog.getSaveFileName(self, "Exportar relatório", "missing_report.txt", "TXT (*.txt);;CSV (*.csv);;JSON (*.json)")
            if not path:
                return
            ext = os.path.splitext(path)[1].lower()
            if ext == ".csv":
                self.reporter.export_csv(report, path)
            elif ext == ".json":
                self.reporter.export_json(report, path)
            else:
                self.reporter.export_txt(report, path)
            self._msg(f"Relatório exportado: {path}")

        def _search_archive(self):
            row = self.missing_table.currentRow()
            if row < 0:
                self._warn("Archive", "Selecione uma ROM missing para buscar.")
                return
            item = self.missing_table.item(row, 3)
            crc = item.text().strip() if item else ""
            if not crc:
                self._warn("Archive", "CRC não disponível para busca.")
                return
            webbrowser.open(f"https://archive.org/advancedsearch.php?q=crc32:{crc}&output=json")
            self._msg(f"Busca aberta no Archive.org para CRC {crc}")

        def _preview(self):
            out = self.output_path.text().strip()
            if not out:
                self._warn("Preview", "Selecione o diretório de output.")
                return
            if not self.identified:
                self._warn("Preview", "Nenhum ROM identificado para preview.")
                return

            plan = self.organizer.preview(self.identified, out, self.strategy.currentText(), self.action.currentText())
            lines = [
                "=== Dry Run Preview ===",
                f"Strategy: {plan.strategy_description}",
                f"Files: {plan.total_files:,}",
                f"Total size: {format_size(plan.total_size)}",
            ]
            for action in plan.actions[:30]:
                lines.append(f"[{action.action_type}] {os.path.basename(action.source)} -> {os.path.relpath(action.destination, out)}")
            if len(plan.actions) > 30:
                lines.append(f"... e mais {len(plan.actions) - 30}")
            self._info("Preview", "\n".join(lines))

        def _organize(self):
            out = self.output_path.text().strip()
            if not out:
                self._warn("Organizar", "Selecione o diretório de output.")
                return
            if not self.identified:
                self._warn("Organizar", "Nenhum ROM identificado para organizar.")
                return

            total_size = sum(f.size for f in self.identified)
            confirm = QMessageBox.question(
                self,
                "Confirmar",
                f"Organizar {len(self.identified):,} ROMs?\n\nStrategy: {self.strategy.currentText()}\n"
                f"Action: {self.action.currentText()}\nTotal size: {format_size(total_size)}\nOutput: {out}",
            )
            if confirm != QMessageBox.Yes:
                return

            actions = self.organizer.organize(self.identified, out, self.strategy.currentText(), self.action.currentText())
            self._msg(f"Organização concluída: {len(actions):,} arquivos")
            self._info("Organizar", f"Concluído. {len(actions):,} arquivos processados.")

        def _undo(self):
            if not self.organizer.get_history_count():
                self._info("Undo", "Nada para desfazer.")
                return
            confirm = QMessageBox.question(self, "Undo", "Desfazer última organização?")
            if confirm == QMessageBox.Yes and self.organizer.undo_last():
                self._msg("Undo concluído")
                self._info("Undo", "Última operação desfeita.")

        def _save_collection(self):
            path, _ = QFileDialog.getSaveFileName(self, "Salvar coleção", "collection.romcol.json", "Coleção (*.romcol.json)")
            if not path:
                return
            base_name = os.path.splitext(os.path.basename(path))[0]
            collection = Collection(
                name=base_name,
                created_at=datetime.now().isoformat(),
                dat_infos=self.multi_matcher.get_dat_list(),
                dat_filepaths=[d.filepath for d in self.multi_matcher.get_dat_list()],
                scan_folder=self.scan_path.text().strip(),
                scan_options={
                    "recursive": self.scan_recursive.isChecked(),
                    "scan_archives": self.scan_archives.isChecked(),
                },
                identified=[f.to_dict() for f in self.identified],
                unidentified=[f.to_dict() for f in self.unidentified],
                settings={
                    "strategy": self.strategy.currentText(),
                    "action": self.action.currentText(),
                    "output": self.output_path.text().strip(),
                    "blindmatch": str(self.blindmatch.isChecked()),
                    "blindmatch_system": self.blindmatch_system.text().strip(),
                    "metadata_db": self.metadata_path.text().strip(),
                },
            )
            saved_path = self.collection_manager.save(collection, filepath=path)
            self._msg(f"Coleção salva: {saved_path}")

        def _load_collection(self):
            path, _ = QFileDialog.getOpenFileName(self, "Carregar coleção", "", "Coleção (*.romcol.json)")
            if not path:
                return
            try:
                collection = self.collection_manager.load(path)
            except Exception as exc:
                self._warn("Coleção", f"Falha ao carregar coleção: {exc}")
                return

            self.multi_matcher = MultiROMMatcher()
            for dat in collection.dat_infos:
                if dat.filepath and os.path.exists(dat.filepath):
                    dat_info, roms = DATParser.parse_with_info(dat.filepath)
                    self.multi_matcher.add_dat(dat_info, roms)

            self.identified = [ScannedFile.from_dict(i) for i in collection.identified]
            self.unidentified = [ScannedFile.from_dict(i) for i in collection.unidentified]
            self.scan_path.setText(collection.scan_folder or "")
            self.output_path.setText(collection.settings.get("output", ""))
            self.strategy.setCurrentText(collection.settings.get("strategy", "flat"))
            self.action.setCurrentText(collection.settings.get("action", "copy"))
            self.scan_recursive.setChecked(collection.scan_options.get("recursive", True))
            self.scan_archives.setChecked(collection.scan_options.get("scan_archives", True))
            self.blindmatch.setChecked(collection.settings.get("blindmatch", "False") == "True")
            self.blindmatch_system.setText(collection.settings.get("blindmatch_system", ""))
            self.metadata_path.setText(collection.settings.get("metadata_db", ""))
            self._refresh_dat_list()
            self._refresh_tables()
            self._refresh_missing_table()
            self._refresh_stats()
            self._msg(f"Coleção carregada: {collection.name}")

        def _show_dat_library(self):
            dats = self.dat_library.list_dats()
            if not dats:
                self._info("Biblioteca DAT", "Biblioteca vazia. Importe um DAT primeiro.")
            path, _ = QFileDialog.getOpenFileName(self, "Importar DAT para biblioteca", "", "DAT/XML (*.dat *.xml *.zip);;Todos (*.*)")
            if path:
                try:
                    info = self.dat_library.import_dat(path)
                    self._msg(f"DAT importado para biblioteca: {info.system_name}")
                except Exception as exc:
                    self._warn("Biblioteca DAT", str(exc))

            dats = self.dat_library.list_dats()
            if dats:
                choices = [f"{d.system_name} | {d.version} | {d.id}" for d in dats]
                chosen, ok = QInputDialog.getItem(self, "Biblioteca DAT", "Carregar DAT da biblioteca:", choices, 0, False)
                if ok and chosen:
                    dat_id = chosen.split("|")[-1].strip()
                    dat_path = self.dat_library.get_dat_path(dat_id)
                    if dat_path and os.path.exists(dat_path):
                        dat_info, roms = DATParser.parse_with_info(dat_path)
                        self.multi_matcher.add_dat(dat_info, roms)
                        self._msg(f"DAT carregado da biblioteca: {dat_info.system_name}")
                        self._refresh_dat_list()
                        self._refresh_stats()

            sources = self.dat_sources.get_sources()
            if sources:
                src_choices = [f"{s['name']} ({s['type']})" for s in sources]
                src, ok = QInputDialog.getItem(self, "Fontes DAT", "Abrir página de fonte DAT (opcional):", ["-"] + src_choices, 0, False)
                if ok and src and src != "-":
                    idx = src_choices.index(src)
                    self.dat_sources.open_source_page(sources[idx]["id"])

        def _new_session(self):
            self.multi_matcher = MultiROMMatcher()
            self.scanned_files = []
            self.identified = []
            self.unidentified = []
            self.scan_path.clear()
            self.output_path.clear()
            self.search_input.clear()
            self.metadata_path.clear()
            self.blindmatch_system.clear()
            self.blindmatch.setChecked(False)
            self._refresh_dat_list()
            self._refresh_tables()
            self._refresh_missing_table()
            self._refresh_stats()
            self._msg("Nova sessão iniciada")

    app = QApplication.instance() or QApplication(sys.argv)
    win = ROMManagerPySide6()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_pyside6_gui())
