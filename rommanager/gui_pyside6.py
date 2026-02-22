"""PySide6 premium shell skeleton for R0MM.

Frameless window, three-pane layout, contextual metadata drawer and scan wizard.
"""

from __future__ import annotations

import sys
from typing import Any

from . import i18n as _i18n

LANG_EN = getattr(_i18n, "LANG_EN", "en")
LANG_PT_BR = getattr(_i18n, "LANG_PT_BR", "pt-BR")


DARK_QSS = """
QWidget { background: #1e1e2e; color: #cdd6f4; }
#AppShell { background: #181825; border-radius: 12px; }
#TitleBar { background: #11111b; border-top-left-radius: 12px; border-top-right-radius: 12px; }
QLineEdit, QComboBox, QTableView, QListView { background: #313244; border: 1px solid #45475a; border-radius: 8px; padding: 6px; }
QPushButton { background: #45475a; border-radius: 8px; padding: 8px 12px; }
QPushButton#Primary { background: #89b4fa; color: #11111b; font-weight: 700; }
QFrame#PanelCard { background: #313244; border: 1px solid #45475a; border-radius: 12px; }
"""

LIGHT_QSS = """
QWidget { background: #eff1f5; color: #4c4f69; }
#AppShell { background: #e6e9ef; border-radius: 12px; }
#TitleBar { background: #dce0e8; border-top-left-radius: 12px; border-top-right-radius: 12px; }
QLineEdit, QComboBox, QTableView, QListView { background: #ccd0da; border: 1px solid #bcc0cc; border-radius: 8px; padding: 6px; }
QPushButton { background: #bcc0cc; border-radius: 8px; padding: 8px 12px; }
QPushButton#Primary { background: #1e66f5; color: #eff1f5; font-weight: 700; }
QFrame#PanelCard { background: #ccd0da; border: 1px solid #bcc0cc; border-radius: 12px; }
"""


def _tr(key: str, **kwargs: Any) -> str:
    func = getattr(_i18n, "tr", None)
    if callable(func):
        return func(key, **kwargs)
    return key


def run_pyside6_gui() -> int:
    try:
        from PySide6.QtCore import QEasingCurve, QPoint, Property, QPropertyAnimation, Qt, Signal
        from PySide6.QtGui import QStandardItem, QStandardItemModel
        from PySide6.QtWidgets import (
            QApplication,
            QDialog,
            QFrame,
            QGraphicsOpacityEffect,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QListWidget,
            QListWidgetItem,
            QMainWindow,
            QPushButton,
            QStackedWidget,
            QTableView,
            QVBoxLayout,
            QWidget,
            QWizard,
            QWizardPage,
        )
    except ImportError as exc:
        print("Error: PySide6 is required for this interface")
        print("Install it with: pip install PySide6")
        print(f"Details: {exc}")
        return 1

    class ScanWizard(QWizard):
        def __init__(self, parent: QWidget | None = None):
            super().__init__(parent)
            self.setWindowTitle("Scan Assistant")
            self.setWizardStyle(QWizard.ModernStyle)
            self._add_pages()

        def _add_pages(self):
            p1 = QWizardPage()
            p1.setTitle("1. Seleção de Fonte")
            l1 = QVBoxLayout(p1)
            l1.addWidget(QLabel("Selecione pasta(s) de ROM para iniciar o scan."))
            self.addPage(p1)

            p2 = QWizardPage()
            p2.setTitle("2. Opções de Scan")
            l2 = QVBoxLayout(p2)
            l2.addWidget(QLabel("Defina recursividade, ZIPs e estratégias avançadas."))
            self.addPage(p2)

            p3 = QWizardPage()
            p3.setTitle("3. Revisão e Execução")
            l3 = QVBoxLayout(p3)
            l3.addWidget(QLabel("Revise parâmetros e execute o scan modular."))
            self.addPage(p3)

    class OverlayDialog(QDialog):
        def __init__(self, parent: QWidget, content: QWidget):
            super().__init__(parent)
            self.setModal(True)
            self.setWindowFlag(Qt.FramelessWindowHint, True)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            dim = QFrame()
            dim.setStyleSheet("background: rgba(0,0,0,140);")
            dim_layout = QVBoxLayout(dim)
            dim_layout.setContentsMargins(80, 80, 80, 80)
            dim_layout.addWidget(content)
            outer.addWidget(dim)

    class DetailDrawer(QFrame):
        def __init__(self):
            super().__init__()
            self.setObjectName("PanelCard")
            self._drawer_width = 0
            self.setMinimumWidth(0)
            self.setMaximumWidth(420)
            lay = QVBoxLayout(self)
            lay.addWidget(QLabel("Metadata"))
            lay.addWidget(QLabel("CRC32: -"))
            lay.addWidget(QLabel("MD5: -"))
            lay.addWidget(QLabel("SHA1: -"))
            lay.addStretch(1)
            self.anim = QPropertyAnimation(self, b"drawerWidth")
            self.anim.setDuration(220)
            self.anim.setEasingCurve(QEasingCurve.OutCubic)

        def _get_drawer_width(self):
            return self._drawer_width

        def _set_drawer_width(self, value):
            self._drawer_width = value
            self.setMinimumWidth(value)
            self.setMaximumWidth(value)

        drawerWidth = Property(int, _get_drawer_width, _set_drawer_width)

        def show_drawer(self):
            self.anim.stop()
            self.anim.setStartValue(self._drawer_width)
            self.anim.setEndValue(380)
            self.anim.start()

        def hide_drawer(self):
            self.anim.stop()
            self.anim.setStartValue(self._drawer_width)
            self.anim.setEndValue(0)
            self.anim.start()

    class FramelessMainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("R0MM Premium (PySide6)")
            self.setMinimumSize(1240, 760)
            self.setWindowFlag(Qt.FramelessWindowHint, True)
            self._drag_pos = QPoint()
            self._build_ui()
            self._apply_theme(dark=True)

        def _apply_theme(self, dark: bool):
            self.setStyleSheet(DARK_QSS if dark else LIGHT_QSS)

        def _build_title_bar(self) -> QWidget:
            title = QFrame()
            title.setObjectName("TitleBar")
            lay = QHBoxLayout(title)
            lay.setContentsMargins(12, 10, 12, 10)
            lay.addWidget(QLabel("R0MM"))
            self.search = QLineEdit()
            self.search.setPlaceholderText("Pesquisar ROMs, DATs e hash...")
            lay.addWidget(self.search, 1)
            btn_scan = QPushButton("Iniciar Scan")
            btn_scan.setObjectName("Primary")
            btn_scan.clicked.connect(self._open_scan_wizard)
            lay.addWidget(btn_scan)
            btn_min = QPushButton("—")
            btn_close = QPushButton("✕")
            btn_min.clicked.connect(self.showMinimized)
            btn_close.clicked.connect(self.close)
            lay.addWidget(btn_min)
            lay.addWidget(btn_close)
            return title

        def _build_left_panel(self) -> QWidget:
            panel = QFrame()
            panel.setObjectName("PanelCard")
            lay = QVBoxLayout(panel)
            lay.addWidget(QLabel("Navegação"))
            self.nav = QListWidget()
            for txt in ["Dashboard", "Biblioteca", "Import/Scan", "Resultados", "Configurações"]:
                QListWidgetItem(txt, self.nav)
            self.nav.setCurrentRow(0)
            lay.addWidget(self.nav)
            lay.addWidget(QLabel("Filtros rápidos"))
            lay.addWidget(QPushButton("Somente identificadas"))
            lay.addWidget(QPushButton("Sem match"))
            lay.addStretch(1)
            return panel

        def _build_center_panel(self) -> QWidget:
            panel = QFrame()
            panel.setObjectName("PanelCard")
            lay = QVBoxLayout(panel)
            switcher = QHBoxLayout()
            btn_list = QPushButton("Lista")
            btn_grid = QPushButton("Grelha")
            switcher.addWidget(btn_list)
            switcher.addWidget(btn_grid)
            switcher.addStretch(1)
            lay.addLayout(switcher)

            self.center_stack = QStackedWidget()
            self.table = QTableView()
            model = QStandardItemModel(0, 5, self)
            model.setHorizontalHeaderLabels(["ROM", "Sistema", "Região", "CRC32", "Status"])
            self.table.setModel(model)

            grid_placeholder = QListWidget()
            for i in range(8):
                QListWidgetItem(f"Capa {i+1}", grid_placeholder)

            self.center_stack.addWidget(self.table)
            self.center_stack.addWidget(grid_placeholder)
            lay.addWidget(self.center_stack, 1)

            btn_list.clicked.connect(lambda: self.center_stack.setCurrentIndex(0))
            btn_grid.clicked.connect(lambda: self.center_stack.setCurrentIndex(1))
            self.table.clicked.connect(lambda *_: self.detail_drawer.show_drawer())
            return panel

        def _build_ui(self):
            shell = QWidget()
            shell.setObjectName("AppShell")
            outer = QVBoxLayout(shell)
            outer.setContentsMargins(8, 8, 8, 8)
            outer.setSpacing(8)
            outer.addWidget(self._build_title_bar())

            panes = QHBoxLayout()
            panes.setSpacing(8)
            left = self._build_left_panel()
            center = self._build_center_panel()
            self.detail_drawer = DetailDrawer()
            panes.addWidget(left, 2)
            panes.addWidget(center, 7)
            panes.addWidget(self.detail_drawer, 0)
            outer.addLayout(panes, 1)

            self.setCentralWidget(shell)

        def _open_scan_wizard(self):
            wizard = ScanWizard(self)
            wizard.setMinimumWidth(760)
            dialog = OverlayDialog(self, wizard)
            dialog.resize(self.size())
            dialog.exec()

        def mousePressEvent(self, event):
            if event.button() == Qt.LeftButton:
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()

        def mouseMoveEvent(self, event):
            if event.buttons() & Qt.LeftButton:
                self.move(event.globalPosition().toPoint() - self._drag_pos)
                event.accept()

    app = QApplication.instance() or QApplication(sys.argv)
    win = FramelessMainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_pyside6_gui())
