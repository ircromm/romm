"""PySide6 desktop interface for R0MM (Flutter-parity layout)."""

from __future__ import annotations

from collections import OrderedDict
import sys
from pathlib import Path
import random
import time
import traceback

from PySide6 import QtCore, QtGui, QtWidgets

from .gui_pyside6_state import AppState, LANG_EN, LANG_PT_BR
from .gui_pyside6_views import DashboardView, ImportScanView, LibraryView, ToolsView, DownloadsView
from .gui_pyside6_widgets import COLORS, apply_global_style, subtle_label
from .monitor import get_log_path, monitor_action, setup_runtime_monitor
from . import __version__
from . import i18n as _i18n


def _tr(key: str, **kwargs) -> str:
    func = getattr(_i18n, "tr", None)
    if callable(func):
        return func(key, **kwargs)
    return key


RETRO_QUOTES = [
    "All your base are belong to us.", "A winner is you!", "I am Error.",
    "Conglaturation !!! You have completed a great game.", "I feel asleep!!",
    "Somebody set up us the bomb.", "You were almost a Jill sandwich!",
    "Master of unlocking.", "Finish him!", "Get over here!", "Flawless Victory.",
    "Rise from your grave!", "Welcome to your doom!", "He's on fire!",
    "Boomshakalaka!", "C-C-C-Combo Breaker!", "It's dangerous to go alone! Take this.",
    "Thank you Mario! But our princess is in another castle!",
    "You have died of dysentery.", "What is a man? A miserable little pile of secrets.",
    "Die monster! You don't belong in this world!", "But thou must!",
    "War. War never changes.", "Zug zug.",
    "The president has been kidnapped by ninjas.",
    "It's time to kick ass and chew bubble gum...", "Hail to the king, baby!",
    "Do a barrel roll!", "Snake? Snake? SNAAAAAAAKE!!!", "Hey! Listen!",
    "Itchy. Tasty.", "Insert Coin.", "Winners don't use drugs.",
    "Game Over. Return of Ganon.", "PROTIP: To defeat the Cyberdemon, shoot at it until it dies.",
]

_QT_MESSAGE_HANDLER_INSTALLED = False


def _emit_terminal_line(message: str) -> None:
    stream = getattr(sys, "__stderr__", None) or sys.stderr
    if not message or stream is None:
        return
    try:
        print(message, file=stream)
        stream.flush()
    except Exception:
        pass


def _install_qt_message_bridge() -> None:
    global _QT_MESSAGE_HANDLER_INSTALLED
    if _QT_MESSAGE_HANDLER_INSTALLED:
        return

    level_map = {
        QtCore.QtMsgType.QtDebugMsg: "DEBUG",
        QtCore.QtMsgType.QtInfoMsg: "INFO",
        QtCore.QtMsgType.QtWarningMsg: "WARN",
        QtCore.QtMsgType.QtCriticalMsg: "CRITICAL",
        QtCore.QtMsgType.QtFatalMsg: "FATAL",
    }

    def _handler(mode, context, message):
        try:
            level = level_map.get(mode, "INFO")
            src_file = getattr(context, "file", "") or ""
            src_line = getattr(context, "line", 0) or 0
            where = ""
            if src_file:
                where = f" ({Path(src_file).name}:{src_line})"
            line = f"[Qt {level}] {message}{where}"
            _emit_terminal_line(line)
            if mode in (QtCore.QtMsgType.QtWarningMsg, QtCore.QtMsgType.QtCriticalMsg, QtCore.QtMsgType.QtFatalMsg):
                monitor_action(f"[!] {line}")
            else:
                monitor_action(f"[*] {line}")
        except Exception:
            _emit_terminal_line(f"[Qt] {message}")

    QtCore.qInstallMessageHandler(_handler)
    _QT_MESSAGE_HANDLER_INSTALLED = True


class GhostTyper(QtCore.QObject):
    def __init__(self, label: QtWidgets.QLabel):
        super().__init__()
        self.label = label
        self.quotes = RETRO_QUOTES.copy()
        random.shuffle(self.quotes)
        self.current_text = ""
        self.display_text = ""
        self.char_idx = 0
        self.state = "IDLE"
        self.cursor_visible = True

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.cursor_timer = QtCore.QTimer(self)
        self.cursor_timer.timeout.connect(self._blink_cursor)
        self.cursor_timer.start(500)
        self._start_next()

    def _start_next(self) -> None:
        if not self.quotes:
            self.quotes = RETRO_QUOTES.copy()
            random.shuffle(self.quotes)
        self.current_text = self.quotes.pop()
        self.char_idx = 0
        self.display_text = ""
        self.state = "TYPING"
        self.timer.start(50)

    def _tick(self) -> None:
        if self.state == "TYPING":
            if self.char_idx < len(self.current_text):
                self.display_text += self.current_text[self.char_idx]
                self.char_idx += 1
                self._render()
            else:
                self.state = "WAITING"
                self.timer.start(8000)
        elif self.state == "WAITING":
            self.state = "DELETING"
            self.timer.start(25)
        elif self.state == "DELETING":
            if len(self.display_text) > 0:
                self.display_text = self.display_text[:-1]
                self._render()
            else:
                self.state = "IDLE"
                self._render()
                self.timer.start(2000)
        elif self.state == "IDLE":
            self._start_next()

    def _blink_cursor(self) -> None:
        self.cursor_visible = not self.cursor_visible
        self._render()

    def _render(self) -> None:
        cursor = "▏" if self.cursor_visible else " "
        self.label.setText(f">_ {self.display_text}{cursor}")


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.state = AppState()
        self._last_scanning: bool | None = None
        self._scan_speed_fps: float = 0.0
        self._scan_current: int = 0
        self._scan_total: int = 0
        self._scan_phase: str = "idle"
        self._scan_progress_mode: str = "scan"
        self._scan_progress_prev: int | None = None
        self._scan_progress_ts: float | None = None
        self._session_anomalies: int = 0
        self._jd_handoff_active: bool = False
        self._jd_handoff_phase: str = "prepare"
        self._jd_handoff_percent: int = 0
        self._jd_console_percent: int = -1
        self._jd_console_phase: str = ""
        self._hydra_rows: "OrderedDict[str, dict]" = OrderedDict()
        self._restoring_ui_state = False
        self._last_ui_snapshot: dict | None = None
        self.setWindowTitle(f"R0MM {__version__} (PySide6)")
        self.setMinimumSize(1280, 720)
        self._build_ui()
        self._bind()
        if self._prompt_restore_session():
            self._restore_ui_state()
        else:
            monitor_action("[*] ui_state:restore:skipped_by_user")
        if not getattr(self, "_restored_geometry", False):
            self.setWindowState(self.windowState() | QtCore.Qt.WindowState.WindowMaximized)
        self.state.refresh_all()
        self._init_ui_state_autosave()

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        # Sidebar
        sidebar = QtWidgets.QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(240)
        side_layout = QtWidgets.QVBoxLayout(sidebar)
        side_layout.setContentsMargins(8, 8, 8, 8)

        brand = QtWidgets.QLabel(_tr("app_title"))
        brand.setObjectName("Brand")
        side_layout.addWidget(brand)
        side_layout.addSpacing(20)

        self.nav_buttons = []
        self._nav_keys = ["nav_dashboard", "nav_library", "nav_import_scan", "nav_tools", "nav_downloads"]
        for idx, key in enumerate(self._nav_keys):
            btn = QtWidgets.QPushButton(_tr(key))
            btn.setCheckable(True)
            btn.setObjectName("NavItem")
            btn.clicked.connect(lambda _, i=idx: self._set_view(i))
            side_layout.addWidget(btn)
            self.nav_buttons.append(btn)
        self._update_nav_buttons(0)
        side_layout.addStretch(1)

        # Main area
        main = QtWidgets.QWidget()
        main_layout = QtWidgets.QVBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Top bar
        top_bar = QtWidgets.QFrame()
        top_bar.setObjectName("TopBar")
        top_layout = QtWidgets.QHBoxLayout(top_bar)
        top_layout.setContentsMargins(8, 6, 8, 6)
        self.breadcrumbs = QtWidgets.QLabel(_tr("breadcrumbs_dashboard"))
        self.breadcrumbs.setObjectName("Subtle")
        top_layout.addWidget(self.breadcrumbs)
        top_layout.addStretch(1)
        self.search_field = QtWidgets.QLineEdit()
        self.search_field.setPlaceholderText(_tr("search"))
        self.search_field.setFixedWidth(280)
        top_layout.addWidget(self.search_field)
        self.lang_combo = QtWidgets.QComboBox()
        self.lang_combo.addItem("EN", LANG_EN)
        self.lang_combo.addItem("PT-BR", LANG_PT_BR)
        top_layout.addWidget(self.lang_combo)
        main_layout.addWidget(top_bar)

        # Views
        self.stack = QtWidgets.QStackedWidget()
        self.dashboard = DashboardView(self.state)
        self.library = LibraryView(self.state)
        self.import_scan = ImportScanView(self.state)
        self.tools = ToolsView(self.state)
        self.downloads = DownloadsView(self.state)
        self.stack.addWidget(self.dashboard)
        self.stack.addWidget(self.library)
        self.stack.addWidget(self.import_scan)
        self.stack.addWidget(self.tools)
        self.stack.addWidget(self.downloads)
        main_layout.addWidget(self.stack, 1)
        self.state.refresh_dashboard_intel()

        # Nerve Center (fixed bottom)
        self.nerve_center = QtWidgets.QFrame()
        self.nerve_center.setObjectName("NerveCenter")
        self.nerve_center.setFixedHeight(154)
        nerve_layout = QtWidgets.QHBoxLayout(self.nerve_center)
        nerve_layout.setContentsMargins(8, 6, 8, 6)
        nerve_layout.setSpacing(8)
        mono_13 = QtGui.QFont("JetBrains Mono", 13)
        module_frame_style = "QFrame { background-color: #090909; border: 1px solid #2D2D2D; }"
        module_frame_style_labels = (
            "QFrame { background-color: #090909; border: 1px solid #2D2D2D; } "
            "QLabel { border: none; background: transparent; }"
        )

        col1_frame = QtWidgets.QFrame()
        col1_frame.setStyleSheet(module_frame_style_labels)
        col1_frame.setFixedWidth(220)
        col1_layout = QtWidgets.QVBoxLayout(col1_frame)
        col1_layout.setContentsMargins(8, 8, 8, 8)
        col1_layout.setSpacing(4)
        self.disk_label = QtWidgets.QLabel(_tr("monitor_disk"))
        self.disk_label.setObjectName("Subtitle")
        self.disk_bar = QtWidgets.QLabel("[          ] 0%")
        self.disk_bar.setObjectName("H2")
        self.db_label = QtWidgets.QLabel(_tr("monitor_db"))
        self.db_label.setObjectName("Subtitle")
        self.db_bar = QtWidgets.QLabel("[          ] 0%")
        self.db_bar.setObjectName("H2")
        col1_layout.addWidget(self.disk_label)
        col1_layout.addWidget(self.disk_bar)
        col1_layout.addWidget(self.db_label)
        col1_layout.addWidget(self.db_bar)

        col2_frame = QtWidgets.QFrame()
        col2_frame.setStyleSheet(module_frame_style_labels)
        col2_frame.setFixedWidth(300)
        col2_layout = QtWidgets.QVBoxLayout(col2_frame)
        col2_layout.setContentsMargins(8, 8, 8, 8)
        col2_layout.setSpacing(4)
        self.op_status_label = QtWidgets.QLabel(self._format_op_status_text(scanning=False))
        self.op_status_label.setObjectName("H2")
        self.op_status_label.setToolTip(_tr("monitor_op"))
        self.op_scan_label = QtWidgets.QLabel("")
        self.op_scan_label.setObjectName("Subtle")
        self.op_scan_label.setFont(mono_13)
        self.op_scan_label.setVisible(False)
        self.op_scan_bar = QtWidgets.QLabel(self._ascii_bar(0))
        self.op_scan_bar.setObjectName("H2")
        self.op_scan_bar.setFont(mono_13)
        self.op_scan_bar.setVisible(False)
        self.op_handoff_label = QtWidgets.QLabel("")
        self.op_handoff_label.setObjectName("Subtle")
        self.op_handoff_label.setFont(mono_13)
        self.op_handoff_label.setVisible(False)
        self.op_handoff_bar = QtWidgets.QLabel(self._ascii_bar(0))
        self.op_handoff_bar.setObjectName("H2")
        self.op_handoff_bar.setFont(mono_13)
        self.op_handoff_bar.setVisible(False)
        self.hydra_queue_frame = QtWidgets.QFrame()
        self.hydra_queue_frame.setObjectName("HydraQueueFrame")
        self.hydra_queue_frame.setStyleSheet("QFrame { background: transparent; border: none; }")
        self.hydra_queue_layout = QtWidgets.QVBoxLayout(self.hydra_queue_frame)
        self.hydra_queue_layout.setContentsMargins(0, 0, 0, 0)
        self.hydra_queue_layout.setSpacing(0)
        self.hydra_queue_labels: list[QtWidgets.QLabel] = []
        for _ in range(4):
            line = QtWidgets.QLabel("")
            line.setObjectName("Subtle")
            line.setFont(mono_13)
            line.setWordWrap(False)
            line.setMinimumHeight(18)
            line.setStyleSheet("border: none; background: transparent; color: #39FF14;")
            self.hydra_queue_layout.addWidget(line)
            self.hydra_queue_labels.append(line)

        self.btn_abort_op = QtWidgets.QPushButton(_tr("monitor_halt_traffic_button"))
        self.btn_abort_op.setObjectName("Destructive")
        self.btn_abort_op.setVisible(False)

        col2_layout.addWidget(self.op_status_label)
        col2_layout.addWidget(self.op_scan_label)
        col2_layout.addWidget(self.op_scan_bar)
        col2_layout.addWidget(self.op_handoff_label)
        col2_layout.addWidget(self.op_handoff_bar)
        col2_layout.addWidget(self.hydra_queue_frame, 1)
        col2_layout.addWidget(self.btn_abort_op, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        self._render_hydra_queue()

        col3_frame = QtWidgets.QFrame()
        col3_frame.setObjectName("NerveConsoleFrame")
        col3_frame.setStyleSheet(module_frame_style)
        col3_layout = QtWidgets.QVBoxLayout(col3_frame)
        col3_layout.setContentsMargins(8, 8, 8, 8)
        col3_layout.setSpacing(4)

        self.event_stream = QtWidgets.QPlainTextEdit()
        self.event_stream.setObjectName("EventStream")
        self.event_stream.setReadOnly(True)
        self.event_stream.setMaximumBlockCount(1200)
        self.event_stream.setFrameStyle(QtWidgets.QFrame.Shape.NoFrame)
        self.event_stream.setFont(mono_13)
        self.event_stream.setStyleSheet("border: none; background: transparent;")

        self.ghost_label = QtWidgets.QLabel(">_ ")
        self.ghost_label.setObjectName("GhostLine")
        self.ghost_label.setWordWrap(False)
        self.ghost_label.setFont(mono_13)

        col3_layout.addWidget(self.event_stream, 1)
        col3_layout.addWidget(self.ghost_label)

        # Force transparent label backgrounds against the new #090909 module chassis.
        for label in (
            self.disk_label,
            self.disk_bar,
            self.db_label,
            self.db_bar,
            self.op_status_label,
            self.op_scan_label,
            self.op_handoff_label,
            self.ghost_label,
        ):
            label.setStyleSheet("border: none; background: transparent;")
        for label in self.hydra_queue_labels:
            label.setStyleSheet("border: none; background: transparent; color: #39FF14;")

        nerve_layout.addWidget(col1_frame, 0)
        nerve_layout.addWidget(col2_frame, 0)
        nerve_layout.addWidget(col3_frame, 1)
        main_layout.addWidget(self.nerve_center)

        root.addWidget(sidebar)
        root.addWidget(main, 1)
        self._refresh_tooltips()

    def _bind(self) -> None:
        self.search_field.textChanged.connect(self.library.set_search_query)
        self.state.status_changed.connect(self._update_status)
        self.state.scan_progress.connect(self._update_scan_progress)
        self.state.download_progress.connect(self._update_hydra_queue)
        self.state.jdownloader_handoff_progress.connect(self._on_jdownloader_handoff_progress)
        self.state.error_changed.connect(self._show_error)
        self.state.log_message.connect(self._append_console)
        self.lang_combo.currentIndexChanged.connect(self._on_lang_change)
        self.state.locale_changed.connect(self._refresh_labels)
        self.btn_abort_op.clicked.connect(self._halt_traffic)
        self._init_log_monitor()
        self.ghost_typer = GhostTyper(self.ghost_label)
        QtWidgets.QApplication.instance().installEventFilter(self)

    def _on_lang_change(self) -> None:
        lang = self.lang_combo.currentData()
        if lang:
            self.state.set_locale(lang)
            if not self._restoring_ui_state:
                monitor_action(f"[?] ui:language:{lang}")

    def _refresh_labels(self) -> None:
        current_idx = self.stack.currentIndex()
        self._update_nav_buttons(current_idx)
        self.search_field.setPlaceholderText(_tr("search"))
        self.disk_label.setText(_tr("monitor_disk"))
        self.db_label.setText(_tr("monitor_db"))
        self.btn_abort_op.setText(_tr("monitor_halt_traffic_button"))
        if self._jd_handoff_active:
            self._set_handoff_progress_text(
                phase=self._jd_handoff_phase,
                percent=self._jd_handoff_percent,
            )
        breadcrumbs = [
            _tr("breadcrumbs_dashboard"),
            _tr("breadcrumbs_library_identified"),
            _tr("breadcrumbs_import_scan"),
            _tr("breadcrumbs_tools"),
            _tr("breadcrumbs_downloads"),
        ]
        self.breadcrumbs.setText(breadcrumbs[current_idx])
        self._update_speed_label(self._scan_speed_fps)
        self._update_anomalies_label()
        self._update_status(self.state.status)
        self.dashboard.refresh_texts()
        self.library.refresh_texts()
        self.import_scan.refresh_texts()
        self.tools.refresh_texts()
        self._refresh_tooltips()

    def _refresh_tooltips(self) -> None:
        nav_tips = [
            _tr("tip_nav_dashboard"),
            _tr("tip_nav_library"),
            _tr("tip_nav_import_scan"),
            _tr("tip_nav_tools"),
        ]
        for btn, tip in zip(getattr(self, "nav_buttons", []), nav_tips):
            btn.setToolTip(tip)
        self.search_field.setToolTip(_tr("tip_search_filter"))
        self.lang_combo.setToolTip(_tr("tip_language_selector"))
        self.btn_abort_op.setToolTip(_tr("tip_halt_traffic"))
        self.event_stream.setToolTip(_tr("tip_tools_console"))
        self.hydra_queue_frame.setToolTip(_tr("tip_hydra_queue"))
        self.op_status_label.setToolTip(_tr("monitor_op"))
        self.op_scan_label.setToolTip(_tr("monitor_op"))
        self.op_scan_bar.setToolTip(_tr("monitor_op"))
        self.op_handoff_label.setToolTip(_tr("monitor_op"))
        self.op_handoff_bar.setToolTip(_tr("monitor_op"))

    def _init_ui_state_autosave(self) -> None:
        self._ui_state_timer = QtCore.QTimer(self)
        self._ui_state_timer.setInterval(1000)
        self._ui_state_timer.timeout.connect(self._autosave_ui_state_tick)
        self._last_ui_snapshot = self._collect_ui_state()
        self._ui_state_timer.start()

    def _serialize_geometry(self) -> str:
        try:
            return bytes(self.saveGeometry().toBase64()).decode("ascii")
        except Exception:
            return ""

    def _restore_geometry(self, encoded: str) -> None:
        safe = (encoded or "").strip()
        if not safe:
            return
        try:
            data = QtCore.QByteArray.fromBase64(safe.encode("ascii"))
            if not data.isEmpty():
                self.restoreGeometry(data)
                self._restored_geometry = True
        except Exception:
            return

    def _collect_ui_state(self) -> dict:
        payload = {
            "main": {
                "geometry_b64": self._serialize_geometry(),
                "active_view": int(self.stack.currentIndex()),
                "search_text": self.search_field.text(),
                "language": str(self.lang_combo.currentData() or LANG_EN),
                "last_collection_path": str(self.state.last_collection_path or ""),
            },
        }
        for key, view in (
            ("dashboard", self.dashboard),
            ("library", self.library),
            ("import_scan", self.import_scan),
            ("tools", self.tools),
            ("downloads", self.downloads),
        ):
            exporter = getattr(view, "export_ui_state", None)
            if callable(exporter):
                try:
                    view_state = exporter()
                    if isinstance(view_state, dict):
                        payload[key] = view_state
                except Exception as exc:
                    monitor_action(f"[!] ui_state:collect:{key}:error {exc}")
        return payload

    def _restore_ui_state(self) -> None:
        try:
            payload = self.state.get_ui_prefs()
        except Exception:
            payload = {}
        if not isinstance(payload, dict) or not payload:
            return

        self._restoring_ui_state = True
        try:
            main_state = payload.get("main", {})
            if not isinstance(main_state, dict):
                main_state = {}

            lang = str(main_state.get("language", "") or "").strip()
            if lang:
                idx = self.lang_combo.findData(lang)
                if idx >= 0:
                    self.lang_combo.setCurrentIndex(idx)

            self.search_field.setText(str(main_state.get("search_text", "") or ""))
            self._restore_geometry(str(main_state.get("geometry_b64", "") or ""))

            self._set_view(0, emit_log=False)
            last_col = str(main_state.get("last_collection_path", "") or "").strip()
            if last_col and Path(last_col).exists():
                try:
                    self.state.load_collection(last_col)
                except Exception as exc:
                    monitor_action(f"[!] ui_state:restore:load_collection:error {exc}")

            for key, view in (
                ("dashboard", self.dashboard),
                ("library", self.library),
                ("import_scan", self.import_scan),
                ("tools", self.tools),
                ("downloads", self.downloads),
            ):
                applier = getattr(view, "apply_ui_state", None)
                if callable(applier):
                    try:
                        applier(payload.get(key, {}))
                    except Exception as exc:
                        monitor_action(f"[!] ui_state:restore:{key}:error {exc}")
        finally:
            self._restoring_ui_state = False

    def _prompt_restore_session(self) -> bool:
        try:
            platform = str(QtWidgets.QApplication.instance().platformName() or "").lower()
            if "offscreen" in platform:
                return True
        except Exception:
            pass
        res = QtWidgets.QMessageBox.question(
            self,
            _tr("restore_session_title"),
            _tr("restore_session_body"),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.Yes,
        )
        return res == QtWidgets.QMessageBox.StandardButton.Yes

    def _autosave_ui_state_tick(self) -> None:
        if self._restoring_ui_state:
            return
        snapshot = self._collect_ui_state()
        if snapshot == self._last_ui_snapshot:
            return
        self._last_ui_snapshot = snapshot
        try:
            self.state.queue_ui_prefs_save(snapshot)
        except Exception as exc:
            monitor_action(f"[!] ui_state:queue_save:error {exc}")

    def _set_view(self, idx: int, *, emit_log: bool = True) -> None:
        self._update_nav_buttons(idx)
        self.stack.setCurrentIndex(idx)
        breadcrumbs = [
            _tr("breadcrumbs_dashboard"),
            _tr("breadcrumbs_library_identified"),
            _tr("breadcrumbs_import_scan"),
            _tr("breadcrumbs_tools"),
            _tr("breadcrumbs_downloads"),
        ]
        self.breadcrumbs.setText(breadcrumbs[idx])
        if emit_log:
            self.state.log_message.emit(f"[*] ui:navigate:{self._nav_keys[idx]}")

    @QtCore.Slot(list)
    def _open_downloads_for_missing(self, items: list) -> None:
        try:
            self._set_view(4)  # Downloads
            prepare = getattr(self.downloads, "prepare_myrient_missing_candidates", None)
            if callable(prepare):
                prepare(items or [])
        except Exception as exc:
            monitor_action(f"[!] ui:open_downloads_for_missing:error {exc}")

    def _update_nav_buttons(self, active_idx: int) -> None:
        nav_items = [
            ("[#]", "nav_dashboard"),
            ("[=]", "nav_library"),
            ("[+]", "nav_import_scan"),
            ("[*]", "nav_tools"),
            ("[v]", "nav_downloads"),
        ]
        for i, btn in enumerate(self.nav_buttons):
            prefix, key = nav_items[i]
            name = _tr(key)
            if i == active_idx:
                btn.setText(f">_  {name}")
                btn.setChecked(True)
            else:
                btn.setText(f"{prefix}  {name}")
                btn.setChecked(False)

    def _update_status(self, status: dict) -> None:
        identified = status.get("identified_count", 0)
        unidentified = status.get("unidentified_count", 0)
        total = identified + unidentified
        scanning = status.get("scanning", False)
        self._scan_current = int(status.get("scan_progress", 0) or 0)
        self._scan_total = int(status.get("scan_total", 0) or 0)
        self._scan_phase = str(status.get("scan_phase", "idle") or "idle").strip().lower()
        db_pct = (identified / total * 100) if total else 0
        self.disk_bar.setText(self._ascii_bar(min(100, (total / 5000) * 100)))
        self.db_bar.setText(self._ascii_bar(db_pct))
        self._set_scan_progress_indicator(
            bool(scanning),
            current=self._scan_current,
            total=self._scan_total,
            phase=self._scan_phase,
        )
        if not self._jd_handoff_active:
            self.op_status_label.setText(self._format_op_status_text(scanning=scanning, phase=self._scan_phase))
        self.btn_abort_op.setVisible(bool(scanning) or self._hydra_has_active_traffic() or self._jd_handoff_active)
        if not scanning:
            self._reset_scan_telemetry()
        if scanning != self._last_scanning:
            monitor_action(f"[*] status:{'scanning' if scanning else 'idle'}")
            self._last_scanning = scanning

    def _update_scan_progress(self, current: int, total: int) -> None:
        self._scan_current = max(0, int(current or 0))
        self._scan_total = max(0, int(total or 0))
        self._set_scan_progress_indicator(
            True,
            current=self._scan_current,
            total=self._scan_total,
            phase=self._scan_phase,
        )
        mode = "compare" if self._scan_phase == "compare" else "scan"
        if mode != self._scan_progress_mode:
            self._scan_progress_mode = mode
            self._scan_progress_prev = None
            self._scan_progress_ts = None
            self._scan_speed_fps = 0.0
        now = time.monotonic()
        if current <= 1 or self._scan_progress_prev is None or current < self._scan_progress_prev:
            self._scan_progress_prev = current
            self._scan_progress_ts = now
            self._scan_speed_fps = 0.0
            self._update_speed_label(self._scan_speed_fps)
        else:
            prev_ts = self._scan_progress_ts or now
            delta_t = now - prev_ts
            delta_files = current - self._scan_progress_prev
            if delta_t > 0 and delta_files >= 0:
                instant_speed = delta_files / delta_t
                if self._scan_speed_fps <= 0:
                    self._scan_speed_fps = instant_speed
                else:
                    self._scan_speed_fps = (self._scan_speed_fps * 0.7) + (instant_speed * 0.3)
                self._update_speed_label(self._scan_speed_fps)
            self._scan_progress_prev = current
            self._scan_progress_ts = now
        if total and current in (1, total):
            monitor_action(f"[*] scan_progress:{current}/{total}")
        if total and current >= total:
            self._scan_progress_prev = None
            self._scan_progress_ts = None

    def _show_error(self, message: str) -> None:
        if message:
            self._session_anomalies += 1
            self._update_anomalies_label()
            monitor_action(f"[!] {message}")

    def _ascii_bar(self, percent: float, width: int = 10) -> str:
        pct = max(0.0, min(100.0, percent))
        filled = int(round((pct / 100.0) * width))
        bar = "█" * filled + " " * (width - filled)
        return f"[{bar}] {int(pct)}%"

    def _hydra_ascii_bar(self, percent: float, status: str, width: int = 10) -> str:
        safe_status = (status or "").upper().strip()
        pct = 100.0 if safe_status == "DONE" else max(0.0, min(100.0, float(percent or 0.0)))
        if safe_status == "QUEUED":
            pct = 0.0
        filled = int(round((pct / 100.0) * width))
        return "[" + ("#" * filled) + ("." * (width - filled)) + "]"

    def _hydra_status_prefix(self, status: str) -> str:
        return {
            "QUEUED": "[QUE]",
            "DOWNLOADING": "[DWN]",
            "DONE": "[OK ]",
            "ADDED": "[JD ]",
            "HALTED": "[HLT]",
            "ERROR": "[ERR]",
        }.get((status or "").upper().strip(), "[---]")

    def _hydra_has_active_traffic(self) -> bool:
        for row in self._hydra_rows.values():
            if str(row.get("status", "") or "").upper() in {"QUEUED", "DOWNLOADING"}:
                return True
        return False

    def _hydra_elide_filename(self, filename: str, max_chars: int = 22) -> str:
        safe = (filename or "").strip() or "-"
        if len(safe) <= max_chars:
            return safe
        keep_left = max(6, (max_chars // 2) - 2)
        keep_right = max(6, max_chars - keep_left - 3)
        return f"{safe[:keep_left]}...{safe[-keep_right:]}"

    def _hydra_format_line(self, row: dict) -> str:
        name = self._hydra_elide_filename(str(row.get("filename", "") or "-"))
        status = str(row.get("status", "") or "").upper().strip() or "QUEUED"
        percent = max(0.0, min(100.0, float(row.get("percent", 0.0) or 0.0)))
        speed = str(row.get("speed", "") or "").strip()
        prefix = self._hydra_status_prefix(status)
        bar = self._hydra_ascii_bar(percent, status)
        pct_text = "100%" if status == "DONE" else f"{int(round(percent))}%"
        if status == "QUEUED":
            return f"{prefix} {name} {bar} {status}"
        if status == "DOWNLOADING":
            speed_suffix = f" ({speed})" if speed else ""
            return f"{prefix} {name} {bar} {pct_text}{speed_suffix}"
        if status == "DONE":
            return f"{prefix} {name} {bar} 100%"
        if status == "ADDED":
            return f"{prefix} {name} {bar} LINKGRABBER"
        if status == "HALTED":
            return f"{prefix} {name} {bar} HALTED"
        if status == "ERROR":
            return f"{prefix} {name} {bar} ERROR"
        return f"{prefix} {name} {bar} {pct_text}"

    def _render_hydra_queue(self) -> None:
        labels = getattr(self, "hydra_queue_labels", [])
        if not labels:
            return

        rows = list(self._hydra_rows.values())
        visible_rows = rows[-len(labels):] if rows else []
        for idx, label in enumerate(labels):
            if idx < len(visible_rows):
                row = visible_rows[idx]
                label.setText(self._hydra_format_line(row))
                filename = str(row.get("filename", "") or "").strip()
                status = str(row.get("status", "") or "").upper().strip() or "QUEUED"
                percent = max(0.0, min(100.0, float(row.get("percent", 0.0) or 0.0)))
                speed = str(row.get("speed", "") or "").strip()
                details = [status]
                if status not in {"QUEUED", "ADDED"}:
                    details.append(f"{percent:.1f}%")
                if speed:
                    details.append(speed)
                label.setToolTip((filename + "\n" if filename else "") + " | ".join(details))
            else:
                label.setText("")
                label.setToolTip("")

        scanning = bool((getattr(self.state, "status", {}) or {}).get("scanning", False))
        active_traffic = self._hydra_has_active_traffic()
        self.btn_abort_op.setVisible(scanning or active_traffic or self._jd_handoff_active)
        if not scanning:
            if active_traffic:
                self.op_status_label.setText(f"{_tr('details_status')}: {_tr('monitor_downloading')}")
            elif not self._jd_handoff_active:
                self.op_status_label.setText(self._format_op_status_text(scanning=False, phase=self._scan_phase))

    def _jd_handoff_phase_label(self, phase: str) -> str:
        key_map = {
            "prepare": "monitor_handoff_phase_prepare",
            "bootstrap": "monitor_handoff_phase_bootstrap",
            "collect_targets": "monitor_handoff_phase_collect",
            "enqueue": "monitor_handoff_phase_enqueue",
            "repair": "monitor_handoff_phase_repair",
            "retry": "monitor_handoff_phase_retry",
            "done": "monitor_handoff_phase_done",
            "error": "monitor_handoff_phase_error",
            "halted": "monitor_handoff_phase_halted",
        }
        key = key_map.get((phase or "").strip().lower(), "monitor_handoff_phase_prepare")
        return _tr(key)

    def _set_handoff_progress_text(self, *, phase: str, percent: int) -> None:
        phase_text = self._jd_handoff_phase_label(phase)
        self.op_handoff_label.setText(
            _tr("monitor_handoff_progress", phase=phase_text, percent=max(0, min(100, int(percent or 0))))
        )

    def _set_scan_progress_indicator(self, scanning: bool, *, current: int, total: int, phase: str = "scan") -> None:
        if not hasattr(self, "op_scan_label") or not hasattr(self, "op_scan_bar"):
            return
        if not scanning:
            self.op_scan_label.clear()
            self.op_scan_label.setVisible(False)
            self.op_scan_bar.setText(self._ascii_bar(0))
            self.op_scan_bar.setVisible(False)
            return

        safe_current = max(0, int(current or 0))
        safe_total = max(0, int(total or 0))
        safe_phase = str(phase or "scan").strip().lower()
        if safe_total > 0:
            if safe_phase == "compare":
                self.op_scan_label.setText(_tr("scan_compare_progress", current=safe_current, total=safe_total))
            else:
                self.op_scan_label.setText(_tr("scan_progress", current=safe_current, total=safe_total))
            percent = (safe_current / safe_total * 100.0) if safe_total else 0.0
            self.op_scan_bar.setText(self._ascii_bar(percent))
        else:
            if safe_phase == "compare":
                self.op_scan_label.setText(_tr("scan_compare_starting"))
            else:
                self.op_scan_label.setText(_tr("scan_starting"))
            self.op_scan_bar.setText("[..........] ...")
        self.op_scan_label.setVisible(True)
        self.op_scan_bar.setVisible(True)

    @QtCore.Slot(bool, int, str)
    def _on_jdownloader_handoff_progress(self, active: bool, percent: int, phase: str) -> None:
        safe_pct = max(0, min(100, int(percent or 0)))
        safe_phase = (phase or "").strip().lower() or "prepare"
        self._jd_handoff_phase = safe_phase
        self._jd_handoff_percent = safe_pct
        self._jd_handoff_active = bool(active)
        if self._jd_handoff_active:
            self.op_handoff_label.setVisible(True)
            self.op_handoff_bar.setVisible(True)
            self.op_handoff_bar.setText(self._ascii_bar(safe_pct))
            self._set_handoff_progress_text(phase=safe_phase, percent=safe_pct)
            if safe_phase != self._jd_console_phase or safe_pct in {0, 100} or abs(safe_pct - self._jd_console_percent) >= 5:
                self._jd_console_phase = safe_phase
                self._jd_console_percent = safe_pct
                phase_text = self._jd_handoff_phase_label(safe_phase)
                self._append_console(f"[*] JD {phase_text} {safe_pct}%")
                self._append_console(self._ascii_bar(safe_pct))
            self.op_status_label.setText(f"{_tr('details_status')}: {_tr('monitor_handoff_active')}")
            self.btn_abort_op.setVisible(True)
            return

        self._set_handoff_progress_text(phase=safe_phase, percent=safe_pct)
        self.op_handoff_bar.setVisible(False)
        self.op_handoff_label.setVisible(False)
        self._jd_console_phase = ""
        self._jd_console_percent = -1
        status = (getattr(self.state, "status", {}) or {})
        scanning = bool(status.get("scanning", False))
        phase = str(status.get("scan_phase", "idle") or "idle").strip().lower()
        if scanning:
            self.op_status_label.setText(self._format_op_status_text(scanning=True, phase=phase))
        elif self._hydra_has_active_traffic():
            self.op_status_label.setText(f"{_tr('details_status')}: {_tr('monitor_downloading')}")
        else:
            self.op_status_label.setText(self._format_op_status_text(scanning=False, phase=phase))
        self.btn_abort_op.setVisible(scanning or self._hydra_has_active_traffic() or self._jd_handoff_active)

    @QtCore.Slot(str, float, str, str)
    def _update_hydra_queue(self, filename: str, percent: float, speed: str, status: str) -> None:
        safe_name = (filename or "").strip() or "download.bin"
        safe_status = (status or "").upper().strip() or "QUEUED"
        row = self._hydra_rows.get(safe_name, {})
        row.update(
            {
                "filename": safe_name,
                "percent": max(0.0, min(100.0, float(percent or 0.0))),
                "speed": str(speed or "").strip(),
                "status": safe_status,
                "updated_at": time.monotonic(),
            }
        )
        self._hydra_rows[safe_name] = row
        self._hydra_rows.move_to_end(safe_name)

        if len(self._hydra_rows) > 32:
            removable = []
            for key, value in self._hydra_rows.items():
                if str(value.get("status", "") or "").upper() in {"DONE", "ADDED", "HALTED", "ERROR"}:
                    removable.append(key)
                if len(self._hydra_rows) - len(removable) <= 32:
                    break
            for key in removable:
                self._hydra_rows.pop(key, None)

        self._render_hydra_queue()

    @QtCore.Slot()
    def _halt_traffic(self) -> None:
        monitor_action("[!] ui:halt_traffic:requested")
        try:
            self.state.halt_traffic()
        except Exception as exc:
            monitor_action(f"[!] ui:halt_traffic:error {exc}")
        for row in self._hydra_rows.values():
            if str(row.get("status", "") or "").upper() in {"QUEUED", "DOWNLOADING"}:
                row["status"] = "HALTED"
                row["speed"] = ""
        self._render_hydra_queue()

    def _append_console(self, message: str) -> None:
        if not message:
            return
        cursor = self.event_stream.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        fmt = QtGui.QTextCharFormat()
        color = "#39FF14"  # [*] normal navigation/status
        if "[!]" in message:
            color = "#FF0000"  # critical/error
        elif "[?]" in message:
            color = "#FF00FF"  # user interaction/dialog wait
        elif "[*]" in message:
            color = "#39FF14"
        fmt.setForeground(QtGui.QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(message + "\n")
        self.event_stream.setTextCursor(cursor)
        self.event_stream.ensureCursorVisible()

    def _format_op_status_text(self, *, scanning: bool, phase: str = "idle") -> str:
        safe_phase = str(phase or "idle").strip().lower()
        if scanning and safe_phase == "compare":
            state_text = _tr("monitor_comparing")
        elif scanning:
            state_text = _tr("monitor_scanning")
        else:
            state_text = _tr("monitor_idle")
        return f"{_tr('details_status')}: {state_text}"

    def _set_elided_path(self, label: QtWidgets.QLabel, text: str) -> None:
        if label is None:
            return
        safe_text = (text or "").strip() or "-"
        metrics = QtGui.QFontMetrics(label.font())
        elided = metrics.elidedText(
            safe_text,
            QtCore.Qt.TextElideMode.ElideMiddle,
            250,
        )
        label.setText(elided)
        label.setToolTip("" if safe_text == "-" else safe_text)

    def _format_speed_text(self, fps: float) -> str:
        value = max(0.0, fps)
        shown = f"{value:.1f}" if value < 10 else f"{int(round(value))}"
        return _tr("monitor_speed_value", value=shown)

    def _update_speed_label(self, fps: float) -> None:
        if hasattr(self, "op_speed_label"):
            self.op_speed_label.setText(self._format_speed_text(fps))

    def _update_anomalies_label(self) -> None:
        if not hasattr(self, "op_errors_label"):
            return
        label_text = _tr("monitor_anomalies")
        count = max(0, int(self._session_anomalies))
        if count > 0:
            self.op_errors_label.setText(
                f"{label_text}: <span style='color:#FF00FF'>{count}</span>"
            )
        else:
            self.op_errors_label.setText(f"{label_text}: 0")
        self.op_errors_label.setToolTip(f"{label_text}: {count}")

    def _reset_scan_telemetry(self) -> None:
        self._scan_progress_prev = None
        self._scan_progress_ts = None
        self._scan_speed_fps = 0.0
        self._scan_phase = "idle"
        self._scan_progress_mode = "scan"
        self._update_speed_label(0.0)

    def _abort_active_operation(self) -> None:
        monitor_action("[!] ui:abort:requested")
        thread = getattr(self.state, "_scan_thread", None)
        if thread is not None and thread.isRunning():
            try:
                thread.requestInterruption()
            except Exception:
                pass
            thread.quit()
            if not thread.wait(300):
                monitor_action("[!] ui:abort:forced_terminate")
                thread.terminate()
                thread.wait(1000)
        core = getattr(self.state, "core", None)
        if core is not None:
            core.scanning = False
            core.scan_progress = 0
            core.scan_total = 0
            core.scan_phase = "idle"
        self._reset_scan_telemetry()
        self.btn_abort_op.setVisible(False)
        self._append_console("[!] abort:scan")
        self.state.refresh_status()

    def _init_log_monitor(self) -> None:
        self._log_path = Path(get_log_path())
        if self._log_path.exists():
            self._log_pos = self._log_path.stat().st_size
        else:
            self._log_pos = 0
        self._log_watcher = QtCore.QFileSystemWatcher(self)
        self._log_watcher.fileChanged.connect(self._on_log_changed)
        self._log_watcher.directoryChanged.connect(self._on_log_dir_changed)
        if self._log_path.exists():
            self._log_watcher.addPath(str(self._log_path))
        self._log_watcher.addPath(str(self._log_path.parent))
        self._poll_log()

    def _on_log_changed(self, _path: str) -> None:
        if self._log_path.exists() and str(self._log_path) not in self._log_watcher.files():
            self._log_watcher.addPath(str(self._log_path))
        self._poll_log()

    def _on_log_dir_changed(self, _path: str) -> None:
        if self._log_path.exists() and str(self._log_path) not in self._log_watcher.files():
            self._log_watcher.addPath(str(self._log_path))
            self._poll_log()

    def _poll_log(self) -> None:
        if not self._log_path.exists():
            return
        try:
            with self._log_path.open("r", encoding="utf-8", errors="ignore") as handle:
                handle.seek(self._log_pos)
                data = handle.read()
                self._log_pos = handle.tell()
        except Exception:
            return
        if not data:
            return
        for line in data.splitlines():
            self._append_console(line)

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.Type.MouseButtonPress:
            widget = obj if isinstance(obj, QtWidgets.QWidget) else None
            if widget is not None:
                name = widget.objectName() or widget.__class__.__name__
                msg = f"[?] click:{name}"
                monitor_action(msg)
        return super().eventFilter(obj, event)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        try:
            results = getattr(self.state, "results", {}) or {}
            identified = len(results.get("identified", []))
            unidentified = len(results.get("unidentified", []))
            if identified + unidentified > 0:
                msg = _tr("save_collection_prompt")
                box = QtWidgets.QMessageBox(self)
                box.setWindowTitle(_tr("confirm"))
                box.setText(msg)
                save_btn = box.addButton(_tr("save_collection"), QtWidgets.QMessageBox.ButtonRole.AcceptRole)
                discard_btn = box.addButton(_tr("no"), QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
                cancel_btn = box.addButton(_tr("cancel"), QtWidgets.QMessageBox.ButtonRole.RejectRole)
                box.exec()
                clicked = box.clickedButton()
                if clicked == cancel_btn:
                    event.ignore()
                    return
                if clicked == save_btn:
                    default_name = Path(self.state.last_collection_path).stem if self.state.last_collection_path else "collection"
                    name, ok = QtWidgets.QInputDialog.getText(
                        self,
                        _tr("save_collection"),
                        _tr("collection_name"),
                        text=default_name,
                    )
                    if ok and name.strip():
                        self.state.save_collection(name.strip())
        except Exception as exc:
            monitor_action(f"[!] close_prompt:error {exc}")
        try:
            snapshot = self._collect_ui_state()
            self._last_ui_snapshot = snapshot
            self.state.queue_ui_prefs_save(snapshot)
            self.state.flush_ui_prefs()
        except Exception as exc:
            monitor_action(f"[!] ui_state:close_save:error {exc}")
        super().closeEvent(event)


def run_pyside6_gui() -> int:
    try:
        setup_runtime_monitor()
        _install_qt_message_bridge()
        app = QtWidgets.QApplication(sys.argv)
        apply_global_style(app)
        window = MainWindow()
        window.show()
        return app.exec()
    except Exception:
        try:
            monitor_action("[!] pyside6 startup/runtime crash")
        except Exception:
            pass
        _emit_terminal_line("[R0MM] PySide6 crashed during startup/runtime")
        traceback.print_exc(file=getattr(sys, "__stderr__", None) or sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run_pyside6_gui())
