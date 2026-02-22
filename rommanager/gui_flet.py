"""
R0MM - Flet-based Desktop GUI
Catppuccin Mocha color scheme with Progressive Disclosure design.
Compatible with Flet 0.80+.
"""

import os
import shutil
import sys
import threading
import time
import webbrowser
from typing import List, Optional, Dict, Any

import flet as ft

from .models import DATInfo, ROMInfo, ScannedFile, Collection
from .parser import DATParser
from .scanner import FileScanner
from .matcher import MultiROMMatcher
from .organizer import Organizer
from .collection import CollectionManager
from .reporter import MissingROMReporter
from .utils import format_size
from . import i18n as _i18n
from .settings import (
    load_settings, save_settings, apply_runtime_settings,
    PROFILE_PRESETS, DEFAULT_SETTINGS,
)
from .health import run_health_checks
from .dat_sources import DATSourceManager, KNOWN_SOURCES
from .session_state import build_snapshot, save_snapshot, load_snapshot, restore_into_matcher, restore_scanned, clear_snapshot
from .shared_config import (
    STRATEGIES,
    APP_DATA_DIR,
    IMPORTED_DATS_DIR,
    IMPORTED_COLLECTIONS_DIR,
    IMPORTED_ROMS_DIR,
    ensure_app_directories,
)
from .blindmatch import build_blindmatch_rom
from .monitor import setup_runtime_monitor, monitor_action
LANG_EN = getattr(_i18n, "LANG_EN", "en")
LANG_PT_BR = getattr(_i18n, "LANG_PT_BR", "pt-BR")


def _tr(key, **kwargs):
    func = getattr(_i18n, "tr", None)
    if callable(func):
        return func(key, **kwargs)
    return key


def _set_language(lang):
    func = getattr(_i18n, "set_language", None)
    if callable(func):
        func(lang)


def _safe_get_language():
    func = getattr(_i18n, "get_language", None)
    if callable(func):
        return func()
    return LANG_EN


def _ensure_app_structure() -> None:
    ensure_app_directories()
    os.makedirs(os.path.join(APP_DATA_DIR, "sessions"), exist_ok=True)


def _copy_into_app_storage(source_path: str, destination_dir: str) -> str:
    """Copy imported file to app-local storage and return copied path."""
    _ensure_app_structure()
    base = os.path.basename(source_path)
    stem, ext = os.path.splitext(base)
    safe_stem = "".join(c if c.isalnum() or c in "-_ ." else "_" for c in stem).strip() or "imported"
    candidate = os.path.join(destination_dir, f"{safe_stem}{ext.lower()}")
    suffix = 1
    while os.path.exists(candidate):
        candidate = os.path.join(destination_dir, f"{safe_stem}-{suffix}{ext.lower()}")
        suffix += 1
    shutil.copy2(source_path, candidate)
    return candidate


def _copy_dat_to_local_cache(source_path: str) -> str:
    return _copy_into_app_storage(source_path, IMPORTED_DATS_DIR)


def _copy_collection_to_local_cache(source_path: str) -> str:
    return _copy_into_app_storage(source_path, IMPORTED_COLLECTIONS_DIR)


def _copy_rom_to_local_cache(source_path: str) -> str:
    return _copy_into_app_storage(source_path, IMPORTED_ROMS_DIR)



SESSION_EXPORTS_DIR = os.path.join(APP_DATA_DIR, "sessions")
MIN_FLET_VERSION = "0.80.0"


def _clear_app_cache() -> None:
    clear_snapshot()
    cache_dirs = [
        os.path.join(APP_DATA_DIR, "cache"),
    ]
    for cache_dir in cache_dirs:
        if not os.path.isdir(cache_dir):
            continue
        for name in os.listdir(cache_dir):
            path = os.path.join(cache_dir, name)
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    os.remove(path)
            except Exception:
                pass


def _version_tuple(version_str: str) -> tuple:
    clean = (version_str or "").split("+")[0].split("-")[0]
    parts = []
    for item in clean.split("."):
        if item.isdigit():
            parts.append(int(item))
        else:
            digits = "".join(c for c in item if c.isdigit())
            parts.append(int(digits) if digits else 0)
    return tuple(parts)


# ─── Catppuccin Mocha Palette ──────────────────────────────────────────────────
MOCHA = {
    "rosewater": "#f5e0dc",
    "flamingo":  "#f2cdcd",
    "pink":      "#f5c2e7",
    "mauve":     "#cba6f7",
    "red":       "#f38ba8",
    "maroon":    "#eba0ac",
    "peach":     "#fab387",
    "yellow":    "#f9e2af",
    "green":     "#a6e3a1",
    "teal":      "#94e2d5",
    "sky":       "#89dceb",
    "sapphire":  "#74c7ec",
    "blue":      "#89b4fa",
    "lavender":  "#b4befe",
    "text":      "#cdd6f4",
    "subtext1":  "#bac2de",
    "subtext0":  "#a6adc8",
    "overlay2":  "#9399b2",
    "overlay1":  "#7f849c",
    "overlay0":  "#6c7086",
    "surface2":  "#585b70",
    "surface1":  "#45475a",
    "surface0":  "#313244",
    "base":      "#1e1e2e",
    "mantle":    "#181825",
    "crust":     "#11111b",
}

REGION_BADGE_COLORS = {
    "USA":    MOCHA["blue"],
    "Europe": MOCHA["mauve"],
    "Japan":  MOCHA["red"],
    "World":  MOCHA["green"],
    "Brazil": MOCHA["yellow"],
    "Korea":  MOCHA["peach"],
    "China":  MOCHA["flamingo"],
}
DEFAULT_BADGE_COLOR = MOCHA["overlay1"]

SPACE_8 = 8
SPACE_16 = 16
SPACE_24 = 24
SPACE_32 = 32
RADIUS_SM = 8
RADIUS_LG = 12
ICON_BUTTON_SIZE = 20
VIEW_TITLE_SIZE = 24


# ─── Helpers ────────────────────────────────────────────────────────────────────
def _card_container(content, **kwargs):
    """Styled card container used throughout the UI."""
    defaults = dict(
        bgcolor=MOCHA["surface0"],
        border_radius=RADIUS_LG,
        padding=ft.Padding.all(SPACE_16),
        border=ft.Border.all(1, MOCHA["surface1"]),
    )
    defaults.update(kwargs)
    return ft.Container(content=content, **defaults)


# ─── Application State ─────────────────────────────────────────────────────────
class AppState:
    """Central application state shared across all views."""

    def __init__(self):
        _ensure_app_structure()
        self.logger = setup_runtime_monitor()
        self.activity_log: List[tuple[str, str]] = []
        self.activity_subscribers: List[Any] = []
        self.multi_matcher = MultiROMMatcher()
        self.organizer = Organizer()
        self.collection_manager = CollectionManager()
        self.reporter = MissingROMReporter()
        self.dat_source_manager = DATSourceManager()
        self.identified: List[ScannedFile] = []
        self.unidentified: List[ScannedFile] = []
        self.scanning = False
        self.scan_progress = 0
        self.scan_total = 0
        self.blindmatch_mode = False
        self.blindmatch_system = ""
        self.settings: Dict[str, Any] = load_settings()

    def persist_session(self):
        snapshot = build_snapshot(
            dats=self.multi_matcher.get_dat_list(),
            identified=self.identified,
            unidentified=self.unidentified,
            extras={
                "blindmatch_mode": self.blindmatch_mode,
                "blindmatch_system": self.blindmatch_system,
            },
        )
        save_snapshot(snapshot)

    def restore_session(self):
        snap = load_snapshot()
        if not snap:
            return
        restore_into_matcher(self.multi_matcher, snap)
        self.identified, self.unidentified = restore_scanned(snap)
        extras = snap.get("extras", {})
        self.blindmatch_mode = bool(extras.get("blindmatch_mode", False))
        self.blindmatch_system = extras.get("blindmatch_system", "")

    def reset_session(self):
        self.multi_matcher = MultiROMMatcher()
        self.identified = []
        self.unidentified = []
        self.scan_progress = 0
        self.scan_total = 0
        self.blindmatch_mode = False
        self.blindmatch_system = ""
        self.persist_session()

    def subscribe_activity_log(self, callback) -> None:
        if callback not in self.activity_subscribers:
            self.activity_subscribers.append(callback)

    def emit_activity(self, action: str, message: str, color: str = MOCHA["text"]) -> None:
        monitor_action(action, logger=self.logger)
        entry = (message, color)
        self.activity_log.append(entry)
        if len(self.activity_log) > 1000:
            self.activity_log = self.activity_log[-1000:]
        for callback in list(self.activity_subscribers):
            try:
                callback(message, color)
            except Exception:
                pass


# ─── Snackbar ───────────────────────────────────────────────────────────────────
def _legacy_open_overlay(pg: ft.Page, control: ft.Control):
    """Fallback para versões antigas do Flet sem page.open()."""
    control.open = True
    if isinstance(control, ft.AlertDialog):
        pg.dialog = control
    elif isinstance(control, ft.SnackBar):
        pg.snack_bar = control
    pg.update()


def _legacy_close_overlay(pg: ft.Page, control: ft.Control):
    """Fallback para versões antigas do Flet sem page.close()."""
    control.open = False
    if isinstance(control, ft.AlertDialog) and getattr(pg, "dialog", None) is control:
        pg.dialog = None
    pg.update()


def _safe_open_overlay(pg: ft.Page, control: ft.Control):
    """Abre overlays com compatibilidade entre APIs nova/legada do Flet."""
    open_fn = getattr(pg, "open", None)
    if callable(open_fn):
        open_fn(control)
        return
    _legacy_open_overlay(pg, control)


def _safe_close_overlay(pg: ft.Page, control: ft.Control):
    """Fecha overlays com compatibilidade entre APIs nova/legada do Flet."""
    close_fn = getattr(pg, "close", None)
    if callable(close_fn):
        close_fn(control)
        return
    _legacy_close_overlay(pg, control)


def _show_snack(pg: ft.Page, text: str, color: str = MOCHA["text"], duration: int = 3000):
    sb = ft.SnackBar(
        content=ft.Text(text, color=color),
        bgcolor=MOCHA["surface0"],
        duration=duration,
    )
    show_dialog_fn = getattr(pg, "show_dialog", None)
    if callable(show_dialog_fn):
        show_dialog_fn(sb)
        return
    _safe_open_overlay(pg, sb)


def region_badge(region: str) -> ft.Container:
    color = REGION_BADGE_COLORS.get(region, DEFAULT_BADGE_COLOR)
    return ft.Container(
        content=ft.Text(
            region if region else "??",
            size=9,
            weight=ft.FontWeight.BOLD,
            color=MOCHA["crust"],
        ),
        bgcolor=color,
        border_radius=4,
        padding=ft.Padding.symmetric(horizontal=6, vertical=2),
    )


# ─── Game Card for Library GridView ─────────────────────────────────────────────
def game_card(scanned: ScannedFile, on_click) -> ft.Container:
    rom = scanned.matched_rom
    game_name = rom.game_name if rom else scanned.filename
    region = rom.region if rom else ""
    system = rom.system_name if rom else ""
    first_letter = game_name[0].upper() if game_name else "?"

    return ft.Container(
        content=ft.Stack(
            controls=[
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Container(
                                content=ft.Text(
                                    first_letter, size=36,
                                    weight=ft.FontWeight.BOLD,
                                    color=MOCHA["overlay0"],
                                ),
                                bgcolor=MOCHA["surface0"],
                                border_radius=ft.border_radius.only(top_left=8, top_right=8),
                                alignment=ft.Alignment(0, 0),
                                expand=True,
                            ),
                            ft.Container(
                                content=ft.Column(
                                    controls=[
                                        ft.Text(game_name, size=11, weight=ft.FontWeight.W_600, color=MOCHA["text"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                                        ft.Text(system or "", size=9, color=MOCHA["subtext0"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                    ],
                                    spacing=2,
                                ),
                                padding=ft.Padding.all(8),
                                bgcolor=MOCHA["mantle"],
                                border_radius=ft.border_radius.only(bottom_left=8, bottom_right=8),
                            ),
                        ],
                        spacing=0,
                    ),
                    border_radius=RADIUS_SM,
                    border=ft.Border.all(1, MOCHA["surface1"]),
                    clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                ),
                ft.Container(content=region_badge(region), top=6, right=6),
            ],
        ),
        on_click=lambda e: on_click(scanned),
        animate=ft.Animation(200, ft.AnimationCurve.EASE_IN_OUT),
        ink=True,
    )


# ─── Detail Panel ───────────────────────────────────────────────────────────────
class DetailPanel(ft.Container):
    def __init__(self, pg: ft.Page):
        super().__init__()
        self._pg = pg
        self._scanned: Optional[ScannedFile] = None
        self._clipboard = ft.Clipboard()
        self._pg.services.append(self._clipboard)

        self.title_text = ft.Text("", size=20, weight=ft.FontWeight.BOLD, color=MOCHA["text"])
        self.system_text = ft.Text("", size=13, color=MOCHA["subtext0"])
        self.region_container = ft.Row(controls=[], spacing=SPACE_8)
        self.meta_column = ft.Column(controls=[], spacing=SPACE_8, scroll=ft.ScrollMode.AUTO)
        self.action_row = ft.Row(controls=[], spacing=SPACE_8)
        self.close_btn = ft.IconButton(icon=ft.Icons.CLOSE, icon_color=MOCHA["overlay1"], icon_size=ICON_BUTTON_SIZE, on_click=self._close)

        self.width = 400
        self.min_width = 384
        self.bgcolor = MOCHA["mantle"]
        self.border = ft.Border.only(left=ft.BorderSide(1, MOCHA["surface1"]))
        self.padding = ft.Padding.all(SPACE_24)
        self.visible = False
        self.animate_opacity = ft.Animation(250, ft.AnimationCurve.EASE_OUT)
        self.opacity = 0

        self.content = ft.Column(
            controls=[
                ft.Row(
                    controls=[ft.Column(controls=[self.title_text, self.system_text], spacing=4, expand=True), self.close_btn],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                self.region_container,
                ft.Divider(height=1, color=MOCHA["surface1"]),
                self.meta_column,
                ft.Divider(height=1, color=MOCHA["surface1"]),
                self.action_row,
            ],
            spacing=SPACE_16, expand=True,
        )

    def show(self, scanned: ScannedFile):
        self._scanned = scanned
        rom = scanned.matched_rom
        self.title_text.value = rom.game_name if rom else scanned.filename
        self.system_text.value = rom.system_name if rom else ""
        self.region_container.controls.clear()
        if rom and rom.region:
            self.region_container.controls.append(region_badge(rom.region))

        self.meta_column.controls.clear()
        meta_items = [("File", scanned.filename), ("Path", scanned.path), ("Size", format_size(scanned.size)), ("CRC32", scanned.crc32.upper())]
        if rom:
            meta_items.extend([("ROM Name", rom.name), ("MD5", rom.md5.upper() if rom.md5 else "N/A"), ("SHA1", rom.sha1.upper() if rom.sha1 else "N/A"), ("Status", rom.status or "Verified"), ("Languages", rom.languages or "N/A")])
        for label, value in meta_items:
            self.meta_column.controls.append(ft.Column(controls=[
                ft.Text(label, size=10, color=MOCHA["overlay1"], weight=ft.FontWeight.BOLD),
                ft.Text(value, size=12, color=MOCHA["text"], selectable=True, max_lines=3, overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=2))

        self.action_row.controls = [
            ft.Button(_tr("flet_open_folder"), icon=ft.Icons.FOLDER_OPEN, icon_size=ICON_BUTTON_SIZE, bgcolor=MOCHA["surface0"], color=MOCHA["text"], on_click=self._open_folder),
            ft.Button(_tr("flet_copy_crc"), icon=ft.Icons.CONTENT_COPY, icon_size=ICON_BUTTON_SIZE, bgcolor=MOCHA["surface0"], color=MOCHA["text"], on_click=self._copy_crc),
        ]
        self.visible = True
        self.opacity = 1
        self.update()

    def _close(self, e):
        self.opacity = 0
        self.update()
        self.visible = False
        self.update()

    def _open_folder(self, e):
        if self._scanned:
            folder = os.path.dirname(self._scanned.path)
            if os.path.isdir(folder):
                if sys.platform == "win32":
                    os.startfile(folder)
                else:
                    os.system(f'xdg-open "{folder}"')

    async def _copy_crc(self, e):
        if self._scanned:
            await self._clipboard.set(self._scanned.crc32.upper())
            _show_snack(self._pg, _tr("flet_crc_copied"))


# ─── Empty State Widget ─────────────────────────────────────────────────────────
def empty_state(message: str, sub: str, button_label: str, on_button) -> ft.Container:
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Icon(ft.Icons.SPORTS_ESPORTS_OUTLINED, size=80, color=MOCHA["overlay0"]),
                ft.Text(message, size=22, weight=ft.FontWeight.BOLD, color=MOCHA["text"], text_align=ft.TextAlign.CENTER),
                ft.Text(sub, size=14, color=MOCHA["subtext0"], text_align=ft.TextAlign.CENTER),
                ft.Container(height=16),
                ft.Button(button_label, icon=ft.Icons.ADD, bgcolor=MOCHA["mauve"], color=MOCHA["crust"], style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)), on_click=on_button),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=8,
        ),
        expand=True,
        alignment=ft.Alignment(0, 0),
    )


# ─── Dashboard View ─────────────────────────────────────────────────────────────
class DashboardView(ft.Column):
    def __init__(self, state: AppState, pg: ft.Page, navigate_cb, new_session_cb):
        super().__init__(expand=True, spacing=20, scroll=ft.ScrollMode.AUTO)
        self.state = state
        self._pg = pg
        self.navigate_cb = navigate_cb
        self.new_session_cb = new_session_cb
        self.padding = ft.Padding.all(30)

    def build_content(self):
        self.controls.clear()
        dats = self.state.multi_matcher.get_dat_list()
        id_count = len(self.state.identified)
        un_count = len(self.state.unidentified)
        total = id_count + un_count

        self.controls.append(ft.Row(controls=[
            ft.Icon(ft.Icons.DASHBOARD_OUTLINED, size=28, color=MOCHA["mauve"]),
            ft.Text(_tr("flet_nav_dashboard"), size=26, weight=ft.FontWeight.BOLD, color=MOCHA["text"]),
            ft.Container(expand=True),
            ft.Button("Nova sessão", icon=ft.Icons.RESTART_ALT, icon_size=ICON_BUTTON_SIZE, bgcolor=MOCHA["red"], color=MOCHA["crust"], on_click=lambda e: self.new_session_cb()),
        ], spacing=12))

        stats = [
            (_tr("flet_dat_files"), str(len(dats)), ft.Icons.DESCRIPTION_OUTLINED, MOCHA["blue"]),
            (_tr("tab_identified"), str(id_count), ft.Icons.CHECK_CIRCLE_OUTLINE, MOCHA["green"]),
            (_tr("tab_unidentified"), str(un_count), ft.Icons.HELP_OUTLINE, MOCHA["peach"]),
            (_tr("flet_total"), str(total), ft.Icons.STORAGE_OUTLINED, MOCHA["lavender"]),
        ]
        stat_cards = []
        for label, value, icon, color in stats:
            stat_cards.append(ft.Container(
                content=ft.Row(controls=[
                    ft.Icon(icon, size=32, color=color),
                    ft.Column(controls=[
                        ft.Text(value, size=28, weight=ft.FontWeight.BOLD, color=MOCHA["text"]),
                        ft.Text(label, size=12, color=MOCHA["subtext0"]),
                    ], spacing=2),
                ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=MOCHA["surface0"], border_radius=RADIUS_LG,
                padding=ft.Padding.all(20), expand=True,
                border=ft.Border.all(1, MOCHA["surface1"]),
            ))
        self.controls.append(ft.Row(controls=stat_cards, spacing=16))

        # Health check summary
        if self.state.identified or self.state.unidentified:
            all_files = self.state.identified + self.state.unidentified
            issues = run_health_checks(all_files)
            if issues:
                issue_items = []
                for kind, items in issues.items():
                    label = kind.replace("_", " ").title()
                    issue_items.append(ft.Row(controls=[
                        ft.Icon(ft.Icons.WARNING_AMBER_OUTLINED, size=16, color=MOCHA["yellow"]),
                        ft.Text(f"{label}: {len(items)}", size=12, color=MOCHA["yellow"]),
                    ], spacing=6))
                self.controls.append(
                    _card_container(ft.Column(controls=[
                        ft.Text("Health Check", size=16, weight=ft.FontWeight.W_600, color=MOCHA["text"]),
                        *issue_items,
                    ], spacing=6))
                )

        if dats:
            self.controls.append(ft.Text(_tr("flet_collection_completeness"), size=VIEW_TITLE_SIZE, weight=ft.FontWeight.W_600, color=MOCHA["text"]))
            completeness = self.state.multi_matcher.get_completeness_by_dat(self.state.identified)
            for dat_id, comp in completeness.items():
                dat_info = self.state.multi_matcher.dat_infos.get(dat_id)
                if not dat_info:
                    continue
                pct = comp.get("percentage", 0)
                found = comp.get("found", 0)
                total_in_dat = comp.get("total_in_dat", 0)
                bar_color = MOCHA["green"] if pct > 75 else MOCHA["yellow"] if pct > 40 else MOCHA["red"]
                self.controls.append(_card_container(ft.Column(controls=[
                    ft.Row(controls=[
                        ft.Text(dat_info.system_name or dat_info.name, size=13, weight=ft.FontWeight.W_600, color=MOCHA["text"], expand=True),
                        ft.Text(f"{found}/{total_in_dat} ({pct:.1f}%)", size=12, color=MOCHA["subtext0"]),
                    ]),
                    ft.ProgressBar(value=pct / 100, bgcolor=MOCHA["surface1"], color=bar_color, bar_height=6, border_radius=3),
                ], spacing=SPACE_8), border_radius=RADIUS_LG))
        else:
            self.controls.append(_card_container(
                ft.Column(controls=[
                    ft.Icon(ft.Icons.INFO_OUTLINE, size=40, color=MOCHA["overlay0"]),
                    ft.Text("No DAT files loaded yet", size=16, color=MOCHA["subtext0"]),
                    ft.Button("Go to Import & Scan", icon=ft.Icons.UPLOAD_FILE, icon_size=ICON_BUTTON_SIZE, bgcolor=MOCHA["mauve"], color=MOCHA["crust"], on_click=lambda e: self.navigate_cb(2)),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                alignment=ft.Alignment(0, 0), padding=ft.Padding.all(40),
            ))


# ─── Library View ────────────────────────────────────────────────────────────────
class LibraryView(ft.Row):
    def __init__(self, state: AppState, pg: ft.Page, navigate_cb):
        super().__init__(expand=True, spacing=0)
        self.state = state
        self._pg = pg
        self.navigate_cb = navigate_cb
        self.search_field = ft.TextField(
            hint_text=_tr("flet_search_games"), prefix_icon=ft.Icons.SEARCH,
            border_radius=RADIUS_SM, bgcolor=MOCHA["surface0"], color=MOCHA["text"],
            hint_style=ft.TextStyle(color=MOCHA["overlay0"]),
            border_color=MOCHA["surface1"], focused_border_color=MOCHA["mauve"],
            height=40, text_size=13, on_change=self._on_search, expand=True,
        )
        self.grid = ft.GridView(
            expand=True, runs_count=5, max_extent=200, child_aspect_ratio=0.78,
            spacing=SPACE_16, run_spacing=SPACE_16, padding=ft.Padding.all(SPACE_24),
        )
        self.detail_panel = DetailPanel(pg)
        self._search_text = ""

    def build_content(self):
        items = self.state.identified
        if not items:
            main_area = ft.Column(controls=[self._build_toolbar(), empty_state(
                _tr("flet_library_empty_title"), _tr("flet_library_empty_desc"),
                _tr("flet_import_scan"), lambda e: self.navigate_cb(2),
            )], expand=True, spacing=0)
        else:
            self._populate_grid(items)
            main_area = ft.Column(controls=[self._build_toolbar(), self.grid], expand=True, spacing=0)
        self.controls = [main_area, self.detail_panel]

    def _build_toolbar(self):
        id_count = len(self.state.identified)
        un_count = len(self.state.unidentified)
        total = id_count + un_count
        pct = (id_count / total * 100) if total else 0
        return ft.Container(
            content=ft.Row(controls=[
                self.search_field, ft.Container(width=SPACE_16),
                ft.Text(f"{id_count} {_tr('flet_identified')}  |  {un_count} {_tr('flet_unidentified')}  |  {pct:.0f}%", size=12, color=MOCHA["subtext0"]),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(horizontal=SPACE_24, vertical=SPACE_16),
            bgcolor=MOCHA["mantle"],
            border=ft.Border.only(bottom=ft.BorderSide(1, MOCHA["surface1"])),
        )

    def _populate_grid(self, items: List[ScannedFile]):
        self.grid.controls.clear()
        search = self._search_text.lower()
        for sc in items:
            rom = sc.matched_rom
            name = rom.game_name if rom else sc.filename
            system = rom.system_name if rom else ""
            region = rom.region if rom else ""
            if search and search not in name.lower() and search not in system.lower() and search not in region.lower():
                continue
            self.grid.controls.append(game_card(sc, self._on_card_click))

    def _on_card_click(self, scanned: ScannedFile):
        self.detail_panel.show(scanned)

    def _on_search(self, e):
        self._search_text = e.control.value
        self._populate_grid(self.state.identified)
        self.grid.update()


# ─── Import & Scan View ─────────────────────────────────────────────────────────
class ImportScanView(ft.Column):
    def __init__(self, state: AppState, pg: ft.Page, on_scan_complete):
        super().__init__(expand=True, spacing=0, scroll=ft.ScrollMode.AUTO)
        self.state = state
        self._pg = pg
        self.on_scan_complete = on_scan_complete

        self.dat_picker = ft.FilePicker()
        self._pg.services.append(self.dat_picker)
        self.folder_picker = ft.FilePicker()
        self._pg.services.append(self.folder_picker)

        self.dat_list = ft.ListView(spacing=4, height=180, padding=ft.Padding.all(8))
        self.folder_path_text = ft.Text(_tr("flet_no_folder"), size=13, color=MOCHA["subtext0"], expand=True)
        self.recursive_switch = ft.Switch(label=_tr("recursive"), value=True, active_color=MOCHA["mauve"], label_text_style=ft.TextStyle(color=MOCHA["text"], size=12))
        self.archives_switch = ft.Switch(label=_tr("scan_archives"), value=True, active_color=MOCHA["mauve"], label_text_style=ft.TextStyle(color=MOCHA["text"], size=12))

        self.scan_btn = ft.Button(
            _tr("btn_scan"), icon=ft.Icons.RADAR,
            bgcolor=MOCHA["green"], color=MOCHA["crust"],
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=self._start_scan, disabled=True,
        )
        self.progress_text = ft.Text("", size=12, color=MOCHA["subtext0"])
        self.scan_progress_bar = ft.ProgressBar(width=420, value=0, color=MOCHA["green"], bgcolor=MOCHA["surface1"])
        self.blindmatch_switch = ft.Switch(label="BlindMatch", value=False, tooltip="BlindMatch")
        self.blindmatch_system_field = ft.TextField(label=_tr("system"), width=220, tooltip=_tr("tip_blindmatch_system"))
        self._selected_folder = ""

    def build_content(self):
        self.controls.clear()
        self.padding = ft.Padding.all(30)
        self._refresh_dat_list()

        # DAT Sources section
        source_items = []
        for src in KNOWN_SOURCES:
            source_items.append(ft.Container(
                content=ft.Row(controls=[
                    ft.Icon(ft.Icons.LANGUAGE, size=18, color=MOCHA["blue"]),
                    ft.Column(controls=[
                        ft.Text(src["name"], size=13, weight=ft.FontWeight.W_600, color=MOCHA["text"]),
                        ft.Text(src["description"], size=10, color=MOCHA["subtext0"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=1, expand=True),
                    ft.Button(
                        _tr("open_page"), icon=ft.Icons.OPEN_IN_NEW,
                        bgcolor=MOCHA["surface1"], color=MOCHA["text"],
                        on_click=lambda e, url=src["url"]: webbrowser.open(url),
                    ),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=MOCHA["mantle"], border_radius=RADIUS_SM,
                padding=ft.Padding.symmetric(horizontal=8, vertical=6),
            ))

        self.controls.extend([
            ft.Row(controls=[
                ft.Icon(ft.Icons.UPLOAD_FILE, size=28, color=MOCHA["mauve"]),
                ft.Text(_tr("flet_import_scan"), size=26, weight=ft.FontWeight.BOLD, color=MOCHA["text"]),
            ], spacing=12),
            ft.Container(height=10),

            # DAT Files
            ft.Text(_tr("flet_dat_files"), size=16, weight=ft.FontWeight.W_600, color=MOCHA["text"]),
            ft.Text(_tr("flet_dat_help"), size=12, color=MOCHA["subtext0"]),
            ft.Container(height=6),
            _card_container(ft.Column(controls=[
                self.dat_list,
                ft.Row(controls=[
                    ft.Button(_tr("flet_add_dat"), icon=ft.Icons.ADD, bgcolor=MOCHA["blue"], color=MOCHA["crust"], on_click=self._on_add_dat_click, tooltip=_tr("tip_add_dat")),
                    ft.Button(_tr("flet_remove_selected"), icon=ft.Icons.DELETE_OUTLINE, bgcolor=MOCHA["surface1"], color=MOCHA["text"], on_click=self._remove_selected_dat, tooltip=_tr("tip_remove_dat")),
                ], spacing=8),
            ], spacing=10)),

            ft.Container(height=20),

            # DAT Sources
            ft.Text(_tr("dat_sources"), size=16, weight=ft.FontWeight.W_600, color=MOCHA["text"]),
            ft.Text("Official DAT provider links.", size=12, color=MOCHA["subtext0"]),
            ft.Container(height=6),
            _card_container(ft.Column(controls=source_items, spacing=6)),

            ft.Container(height=20),

            # Scan Folder
            ft.Text(_tr("flet_scan_folder"), size=16, weight=ft.FontWeight.W_600, color=MOCHA["text"]),
            ft.Text(_tr("flet_scan_help"), size=12, color=MOCHA["subtext0"]),
            ft.Container(height=6),
            _card_container(ft.Column(controls=[
                ft.Row(controls=[
                    ft.Icon(ft.Icons.FOLDER_OUTLINED, color=MOCHA["overlay1"]),
                    self.folder_path_text,
                    ft.Button(_tr("flet_browse"), icon=ft.Icons.FOLDER_OPEN, bgcolor=MOCHA["surface1"], color=MOCHA["text"], on_click=self._on_browse_folder_click, tooltip=_tr("tip_select_rom_folder")),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Row(controls=[self.recursive_switch, self.archives_switch, self.blindmatch_switch, self.blindmatch_system_field], spacing=16),
                ft.Divider(height=1, color=MOCHA["surface1"]),
                ft.Row(controls=[self.scan_btn, self.progress_text], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                self.scan_progress_bar,
            ], spacing=10)),
        ])

    def _refresh_dat_list(self):
        self.dat_list.controls.clear()
        dats = self.state.multi_matcher.get_dat_list()
        if not dats:
            self.dat_list.controls.append(ft.Text("No DAT files loaded", size=12, color=MOCHA["overlay0"], italic=True))
            return
        for dat in dats:
            self.dat_list.controls.append(ft.Container(
                content=ft.Row(controls=[
                    ft.Checkbox(value=False, data=dat.id, active_color=MOCHA["mauve"]),
                    ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, size=18, color=MOCHA["blue"]),
                    ft.Column(controls=[
                        ft.Text(dat.system_name or dat.name, size=13, weight=ft.FontWeight.W_600, color=MOCHA["text"]),
                        ft.Text(f"{dat.rom_count} ROMs  |  v{dat.version}" if dat.version else f"{dat.rom_count} ROMs", size=11, color=MOCHA["subtext0"]),
                    ], spacing=1, expand=True),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=MOCHA["mantle"], border_radius=RADIUS_SM,
                padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            ))
        self._update_scan_btn_state()

    async def _on_add_dat_click(self, e):
        files = await self.dat_picker.pick_files(
            dialog_title=_tr("select_dat_file"),
            allowed_extensions=["dat", "xml", "gz", "zip"],
            allow_multiple=True,
        )
        if not files:
            self.state.emit_activity("ui:import:dat:cancel", "DAT import canceled.", MOCHA["overlay0"])
            return
        errors = []
        for f in files:
            try:
                local_dat_path = _copy_dat_to_local_cache(f.path)
                dat_info, roms = DATParser.parse_with_info(local_dat_path)
                self.state.multi_matcher.add_dat(dat_info, roms)
            except Exception as ex:
                errors.append(f"{f.name}: {ex}")
        self._refresh_dat_list()
        self.build_content()
        self.update()
        self.state.persist_session()
        if errors:
            msg = f"Errors: {'; '.join(errors)}"
            self.state.emit_activity("ui:import:dat:error", msg, MOCHA["red"])
            _show_snack(self._pg, msg, MOCHA["red"], 5000)
        else:
            msg = f"Loaded {len(files)} DAT file(s)"
            self.state.emit_activity("ui:import:dat:loaded", msg, MOCHA["green"])
            _show_snack(self._pg, msg, MOCHA["green"])

    def _remove_selected_dat(self, e):
        to_remove = []
        for ctrl in self.dat_list.controls:
            if isinstance(ctrl, ft.Container) and ctrl.content:
                row = ctrl.content
                if isinstance(row, ft.Row) and row.controls:
                    cb = row.controls[0]
                    if isinstance(cb, ft.Checkbox) and cb.value:
                        to_remove.append(cb.data)
        for dat_id in to_remove:
            self.state.multi_matcher.remove_dat(dat_id)
        if to_remove:
            self._refresh_dat_list()
            self.build_content()
            self.update()
            self.state.persist_session()

    async def _on_browse_folder_click(self, e):
        path = await self.folder_picker.get_directory_path(dialog_title=_tr("select_rom_folder"))
        if path:
            self._selected_folder = path
            self.folder_path_text.value = path
            self.state.emit_activity("ui:scan:folder:selected", f"Scan folder selected: {path}", MOCHA["blue"])
            self._update_scan_btn_state()
            self.folder_path_text.update()
            self.scan_btn.update()

    def _update_scan_btn_state(self):
        has_dats = len(self.state.multi_matcher.get_dat_list()) > 0
        if self.blindmatch_switch.value:
            has_dats = True
        has_folder = bool(self._selected_folder)
        self.scan_btn.disabled = not (has_dats and has_folder) or self.state.scanning

    def _start_scan(self, e):
        if self.state.scanning:
            return
        folder = self._selected_folder
        if not folder or not os.path.isdir(folder):
            return
        self.state.scanning = True
        self.state.emit_activity("ui:scan:start", f"Starting scan: {folder}", MOCHA["blue"])
        self.state.blindmatch_mode = bool(self.blindmatch_switch.value)
        self.state.blindmatch_system = (self.blindmatch_system_field.value or "").strip()
        self.scan_btn.disabled = True
        self.scan_btn.text = "Scanning..."
        self.scan_progress_bar.value = None
        self.progress_text.value = "Starting scan..."
        self.scan_btn.update()
        self.scan_progress_bar.update()
        self.progress_text.update()
        recursive = self.recursive_switch.value
        scan_archives = self.archives_switch.value
        thread = threading.Thread(target=self._scan_worker, args=(folder, recursive, scan_archives), daemon=True)
        thread.start()

    def _scan_worker(self, folder: str, recursive: bool, scan_archives: bool):
        try:
            files = FileScanner.collect_files(folder, recursive=recursive, scan_archives=scan_archives)
            total = len(files)
            self.state.scan_total = total
            self.state.scan_progress = 0
            self.scan_progress_bar.value = 0 if total > 0 else 1
            try:
                self.scan_progress_bar.update()
            except Exception:
                pass
            scanned_all: List[ScannedFile] = []
            for i, fpath in enumerate(files):
                try:
                    local_source = _copy_rom_to_local_cache(fpath)
                    if local_source.lower().endswith('.zip') and scan_archives:
                        results = FileScanner.scan_archive_contents(local_source)
                    else:
                        results = [FileScanner.scan_file(local_source)]
                    scanned_all.extend(results)
                except Exception:
                    pass
                self.state.scan_progress = i + 1
                if (i + 1) % 50 == 0 or (i + 1) == total:
                    self.progress_text.value = f"Scanned {i + 1}/{total} files..."
                    self.scan_progress_bar.value = (i + 1) / total if total else 1
                    try:
                        self.progress_text.update()
                        self.scan_progress_bar.update()
                    except Exception:
                        pass
            identified, unidentified = self.state.multi_matcher.match_all(scanned_all)
            self.state.identified = identified
            self.state.unidentified = unidentified
            self.state.persist_session()
            self.state.emit_activity("ui:scan:complete", f"Scan complete: {len(identified)} identified, {len(unidentified)} unidentified", MOCHA["green"])
        except Exception as ex:
            self.state.emit_activity("ui:scan:error", f"Scan error: {ex}", MOCHA["red"])
            _show_snack(self._pg, f"Scan error: {ex}", MOCHA["red"], 5000)
        finally:
            self.state.scanning = False
            self.scan_btn.disabled = False
            self.scan_btn.text = _tr("btn_scan")
            id_count = len(self.state.identified)
            un_count = len(self.state.unidentified)
            self.progress_text.value = f"Done! {id_count} identified, {un_count} unidentified"
            self.scan_progress_bar.value = 1
            try:
                self.scan_btn.update()
                self.progress_text.update()
                self.scan_progress_bar.update()
            except Exception:
                pass
            _show_snack(self._pg, f"Scan complete: {id_count} identified, {un_count} unidentified", MOCHA["green"], 4000)
            if self.on_scan_complete:
                self.on_scan_complete()


# ─── Tools & Organize View ──────────────────────────────────────────────────────
class ToolsLogsView(ft.Column):
    def __init__(self, state: AppState, pg: ft.Page):
        super().__init__(expand=True, spacing=0, scroll=ft.ScrollMode.AUTO)
        self.state = state
        self._pg = pg

        self.output_picker = ft.FilePicker()
        self._pg.services.append(self.output_picker)
        self.collection_picker = ft.FilePicker()
        self._pg.services.append(self.collection_picker)

        self.save_name_field = ft.TextField(
            hint_text=_tr("flet_collection_name"), border_radius=RADIUS_SM,
            bgcolor=MOCHA["surface0"], color=MOCHA["text"],
            hint_style=ft.TextStyle(color=MOCHA["overlay0"]),
            border_color=MOCHA["surface1"], focused_border_color=MOCHA["mauve"],
            height=40, text_size=13, expand=True,
        )

        all_strategies = [ft.dropdown.Option(key=s["id"], text=s["name"]) for s in STRATEGIES]
        # Add composite strategies
        all_strategies.extend([
            ft.dropdown.Option(key="system+1g1r", text="System + 1G1R"),
            ft.dropdown.Option(key="system+region", text="System + Region"),
            ft.dropdown.Option(key="system+alphabetical", text="System + Alphabetical"),
        ])

        self.strategy_dropdown = ft.Dropdown(
            label=_tr("strategy"), tooltip=_tr("tip_choose_strategy"),
            options=all_strategies, value="flat",
            border_radius=RADIUS_SM, bgcolor=MOCHA["surface0"], color=MOCHA["text"],
            label_style=ft.TextStyle(color=MOCHA["subtext0"]),
            border_color=MOCHA["surface1"], focused_border_color=MOCHA["mauve"],
            width=240, text_size=13,
        )
        self.action_dropdown = ft.Dropdown(
            label=_tr("action"), tooltip=_tr("tip_choose_action"),
            options=[ft.dropdown.Option(key="copy", text=_tr("copy_action")), ft.dropdown.Option(key="move", text=_tr("move_action"))],
            value="copy", border_radius=RADIUS_SM, bgcolor=MOCHA["surface0"], color=MOCHA["text"],
            label_style=ft.TextStyle(color=MOCHA["subtext0"]),
            border_color=MOCHA["surface1"], focused_border_color=MOCHA["mauve"],
            width=140, text_size=13,
        )
        self.output_path_text = ft.Text(_tr("flet_no_output"), size=13, color=MOCHA["subtext0"], expand=True)
        self._output_folder = ""
        self.log_view = ft.ListView(spacing=2, height=200, padding=ft.Padding.all(8), auto_scroll=True)
        self.state.subscribe_activity_log(self._append_log_entry)

    def build_content(self):
        self.controls.clear()
        self.padding = ft.Padding.all(30)
        if not self.log_view.controls:
            for msg, color in self.state.activity_log[-300:]:
                self.log_view.controls.append(ft.Text(msg, size=11, color=color, selectable=True, font_family="Consolas,monospace"))
        self.controls.extend([
            ft.Row(controls=[
                ft.Icon(ft.Icons.BUILD_OUTLINED, size=28, color=MOCHA["mauve"]),
                ft.Text(_tr("flet_tools_logs"), size=26, weight=ft.FontWeight.BOLD, color=MOCHA["text"]),
            ], spacing=12),
            ft.Container(height=10),

            # Organize
            ft.Text(_tr("flet_organize_roms"), size=16, weight=ft.FontWeight.W_600, color=MOCHA["text"]),
            ft.Text(_tr("flet_organize_help"), size=12, color=MOCHA["subtext0"]),
            ft.Container(height=6),
            _card_container(ft.Column(controls=[
                ft.Row(controls=[self.strategy_dropdown, self.action_dropdown], spacing=12),
                ft.Row(controls=[
                    ft.Icon(ft.Icons.FOLDER_OUTLINED, color=MOCHA["overlay1"]),
                    self.output_path_text,
                    ft.Button(_tr("flet_browse"), icon=ft.Icons.FOLDER_OPEN, bgcolor=MOCHA["surface1"], color=MOCHA["text"], on_click=self._on_browse_output_click, tooltip=_tr("tip_select_output_folder")),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Divider(height=1, color=MOCHA["surface1"]),
                ft.Row(controls=[
                    ft.Button(_tr("flet_preview"), icon=ft.Icons.PREVIEW, bgcolor=MOCHA["surface1"], color=MOCHA["text"], on_click=self._preview_organize, tooltip=_tr("tip_preview_organization")),
                    ft.Button(_tr("flet_organize"), icon=ft.Icons.AUTO_FIX_HIGH, bgcolor=MOCHA["green"], color=MOCHA["crust"], on_click=self._execute_organize, tooltip=_tr("tip_organize_now")),
                    ft.Button(_tr("flet_undo_last"), icon=ft.Icons.UNDO, bgcolor=MOCHA["peach"], color=MOCHA["crust"], on_click=self._undo_organize, tooltip=_tr("tip_undo_last")),
                ], spacing=8),
            ], spacing=10)),

            ft.Container(height=20),

            # Collections
            ft.Text(_tr("flet_collections"), size=16, weight=ft.FontWeight.W_600, color=MOCHA["text"]),
            ft.Text(_tr("flet_collections_help"), size=12, color=MOCHA["subtext0"]),
            ft.Container(height=6),
            _card_container(ft.Column(controls=[
                ft.Row(controls=[
                    self.save_name_field,
                    ft.Button(_tr("flet_save"), icon=ft.Icons.SAVE, bgcolor=MOCHA["blue"], color=MOCHA["crust"], on_click=self._save_collection, tooltip=_tr("tip_save_collection")),
                    ft.Button(_tr("flet_load"), icon=ft.Icons.FOLDER_OPEN, bgcolor=MOCHA["surface1"], color=MOCHA["text"], on_click=self._on_load_collection_click, tooltip=_tr("tip_open_collection")),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ], spacing=10)),

            ft.Container(height=20),

            # Activity Log
            ft.Text(_tr("flet_activity_log"), size=16, weight=ft.FontWeight.W_600, color=MOCHA["text"]),
            ft.Container(height=6),
            _card_container(self.log_view, bgcolor=MOCHA["crust"], padding=ft.Padding.all(4)),
        ])

    def _append_log_entry(self, msg: str, color: str = MOCHA["text"]):
        self.log_view.controls.append(ft.Text(msg, size=11, color=color, selectable=True, font_family="Consolas,monospace"))
        try:
            self.log_view.update()
        except Exception:
            pass

    def _log(self, msg: str, color: str = MOCHA["text"], action: str = "ui:tools:log"):
        self.state.emit_activity(action, msg, color)

    async def _on_browse_output_click(self, e):
        path = await self.output_picker.get_directory_path(dialog_title=_tr("select_output_folder"))
        if path:
            self._output_folder = path
            self.output_path_text.value = path
            self.output_path_text.update()

    def _preview_organize(self, e):
        if not self.state.identified:
            self._log(_tr("flet_no_identified_to_organize"), MOCHA["peach"])
            return
        if not self._output_folder:
            self._log("Please select an output folder first.", MOCHA["peach"])
            return
        strategy = self.strategy_dropdown.value or "flat"
        action = self.action_dropdown.value or "copy"
        try:
            plan = self.state.organizer.preview(self.state.identified, self._output_folder, strategy, action)
            self._log(f"Preview: {plan.total_files} files, {format_size(plan.total_size)}", MOCHA["blue"])
            for pa in plan.actions[:20]:
                self._log(f"  {pa.action_type}: {os.path.basename(pa.source)} -> {pa.destination}", MOCHA["subtext0"])
            if len(plan.actions) > 20:
                self._log(f"  ... and {len(plan.actions) - 20} more", MOCHA["overlay0"])
        except Exception as ex:
            self._log(f"Preview error: {ex}", MOCHA["red"])

    def _execute_organize(self, e):
        if not self.state.identified:
            self._log(_tr("flet_no_identified_to_organize"), MOCHA["peach"])
            return
        if not self._output_folder:
            self._log("Please select an output folder first.", MOCHA["peach"])
            return
        strategy = self.strategy_dropdown.value or "flat"
        action = self.action_dropdown.value or "copy"
        def progress(current, total, filename=""):
            self._log(f"  [{current}/{total}] {filename}", MOCHA["subtext0"])
        try:
            actions = self.state.organizer.organize(self.state.identified, self._output_folder, strategy, action, progress_callback=progress)
            self._log(f"Organization complete: {len(actions)} files processed.", MOCHA["green"])
        except Exception as ex:
            self._log(f"Organize error: {ex}", MOCHA["red"])

    def _undo_organize(self, e):
        try:
            success = self.state.organizer.undo_last()
            if success:
                self._log("Undo successful.", MOCHA["green"])
            else:
                self._log("Nothing to undo.", MOCHA["overlay0"])
        except Exception as ex:
            self._log(f"Undo error: {ex}", MOCHA["red"])

    def _save_collection(self, e):
        name = self.save_name_field.value
        if not name:
            self._log("Please enter a collection name.", MOCHA["peach"])
            return
        from datetime import datetime
        now = datetime.now().isoformat()
        coll = Collection(
            name=name, created_at=now, updated_at=now,
            dat_infos=self.state.multi_matcher.get_dat_list(),
            dat_filepaths=[d.filepath for d in self.state.multi_matcher.get_dat_list()],
            identified=[sc.to_dict() for sc in self.state.identified],
            unidentified=[sc.to_dict() for sc in self.state.unidentified],
        )
        try:
            path = self.state.collection_manager.save(coll)
            self.state.persist_session()
            self._log(f"Collection saved: {path}", MOCHA["green"])
            _show_snack(self._pg, f"Collection '{name}' saved!", MOCHA["green"])
        except Exception as ex:
            self._log(f"Save error: {ex}", MOCHA["red"])

    async def _on_load_collection_click(self, e):
        files = await self.collection_picker.pick_files(dialog_title=_tr("menu_open_collection"), allowed_extensions=["json"])
        if not files:
            return
        filepath = files[0].path
        try:
            local_collection_path = _copy_collection_to_local_cache(filepath)
            coll = self.state.collection_manager.load(local_collection_path)
            self.state.multi_matcher = MultiROMMatcher()
            for di in coll.dat_infos:
                try:
                    dat_path = di.filepath
                    if dat_path and os.path.isfile(dat_path):
                        dat_path = _copy_dat_to_local_cache(dat_path)
                    _, roms = DATParser.parse_with_info(dat_path)
                    di.filepath = dat_path
                    self.state.multi_matcher.add_dat(di, roms)
                except Exception:
                    pass
            self.state.identified = [ScannedFile.from_dict(d) for d in coll.identified]
            self.state.unidentified = [ScannedFile.from_dict(d) for d in coll.unidentified]
            self.state.persist_session()
            self._log(f"Collection loaded: {coll.name}", MOCHA["green"])
            _show_snack(self._pg, f"Collection '{coll.name}' loaded!", MOCHA["green"])
        except Exception as ex:
            self._log(f"Load error: {ex}", MOCHA["red"])


# ─── Missing ROM Reports View ───────────────────────────────────────────────────
class MissingReportsView(ft.Column):
    def __init__(self, state: AppState, pg: ft.Page):
        super().__init__(expand=True, spacing=0, scroll=ft.ScrollMode.AUTO)
        self.state = state
        self._pg = pg
        self.export_picker = ft.FilePicker()
        self._pg.services.append(self.export_picker)
        self.report_list = ft.ListView(spacing=4, expand=True, padding=ft.Padding.all(8))
        self._current_report = None

    def build_content(self):
        self.controls.clear()
        self.padding = ft.Padding.all(30)

        self.controls.extend([
            ft.Row(controls=[
                ft.Icon(ft.Icons.ASSIGNMENT_OUTLINED, size=28, color=MOCHA["mauve"]),
                ft.Text(_tr("tab_missing"), size=26, weight=ft.FontWeight.BOLD, color=MOCHA["text"]),
            ], spacing=12),
            ft.Container(height=10),
        ])

        dats = self.state.multi_matcher.get_dat_list()
        if not dats or not self.state.identified:
            self.controls.append(_card_container(
                ft.Column(controls=[
                    ft.Icon(ft.Icons.INFO_OUTLINE, size=40, color=MOCHA["overlay0"]),
                    ft.Text(_tr("completeness_hint"), size=14, color=MOCHA["subtext0"]),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                alignment=ft.Alignment(0, 0), padding=ft.Padding.all(40),
            ))
            return

        # Generate multi-report
        report = self.state.reporter.generate_multi_report(
            self.state.multi_matcher.dat_infos,
            self.state.multi_matcher.all_roms,
            self.state.identified,
        )
        self._current_report = report

        # Overall summary
        self.controls.append(_card_container(ft.Column(controls=[
            ft.Row(controls=[
                ft.Text("Overall", size=16, weight=ft.FontWeight.W_600, color=MOCHA["text"], expand=True),
                ft.Text(f"{report['found_in_all']}/{report['total_in_all_dats']} ({report['overall_percentage']:.1f}%)", size=14, color=MOCHA["green"] if report['overall_percentage'] > 75 else MOCHA["yellow"]),
            ]),
            ft.Text(f"Missing: {report['missing_in_all']} ROMs across {report['total_dats']} DAT(s)", size=12, color=MOCHA["subtext0"]),
            ft.ProgressBar(value=report['overall_percentage'] / 100, bgcolor=MOCHA["surface1"], color=MOCHA["green"] if report['overall_percentage'] > 75 else MOCHA["yellow"], bar_height=8, border_radius=4),
        ], spacing=8)))

        # Export buttons
        self.controls.extend([
            ft.Container(height=10),
            ft.Row(controls=[
                ft.Button("Export TXT", icon=ft.Icons.DESCRIPTION, bgcolor=MOCHA["blue"], color=MOCHA["crust"], on_click=lambda e: self._export_report("txt")),
                ft.Button("Export CSV", icon=ft.Icons.TABLE_CHART, bgcolor=MOCHA["teal"], color=MOCHA["crust"], on_click=lambda e: self._export_report("csv")),
                ft.Button("Export JSON", icon=ft.Icons.DATA_OBJECT, bgcolor=MOCHA["peach"], color=MOCHA["crust"], on_click=lambda e: self._export_report("json")),
            ], spacing=8),
            ft.Container(height=16),
        ])

        # Per-DAT breakdown
        for dat_id, dat_report in report.get('by_dat', {}).items():
            pct = dat_report['percentage']
            bar_color = MOCHA["green"] if pct > 75 else MOCHA["yellow"] if pct > 40 else MOCHA["red"]

            # Region breakdown
            region_chips = []
            for region, count in sorted(dat_report.get('missing_by_region', {}).items()):
                region_chips.append(ft.Container(
                    content=ft.Text(f"{region}: {count}", size=10, color=MOCHA["text"]),
                    bgcolor=MOCHA["surface1"], border_radius=4,
                    padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                ))

            missing_items_col = ft.Column(controls=[], spacing=2, visible=False)
            for m in dat_report['missing'][:50]:
                missing_items_col.controls.append(ft.Text(
                    f"  {m['name']} [{m['region']}] ({m['size_formatted']})",
                    size=10, color=MOCHA["subtext0"], selectable=True,
                ))
            if len(dat_report['missing']) > 50:
                missing_items_col.controls.append(ft.Text(f"  ... and {len(dat_report['missing']) - 50} more", size=10, color=MOCHA["overlay0"]))

            def toggle_missing(e, col=missing_items_col):
                col.visible = not col.visible
                col.update()

            self.controls.append(_card_container(ft.Column(controls=[
                ft.Row(controls=[
                    ft.Text(dat_report['system_name'] or dat_report['dat_name'], size=14, weight=ft.FontWeight.W_600, color=MOCHA["text"], expand=True),
                    ft.Text(f"{dat_report['found']}/{dat_report['total_in_dat']} ({pct:.1f}%)", size=12, color=MOCHA["subtext0"]),
                ]),
                ft.ProgressBar(value=pct / 100, bgcolor=MOCHA["surface1"], color=bar_color, bar_height=5, border_radius=3),
                ft.Text(f"Missing: {dat_report['missing_count']}", size=11, color=MOCHA["subtext0"]),
                ft.Row(controls=region_chips, spacing=4, wrap=True) if region_chips else ft.Container(),
                ft.TextButton(f"Show missing ({dat_report['missing_count']})", on_click=toggle_missing, style=ft.ButtonStyle(color=MOCHA["blue"])),
                missing_items_col,
            ], spacing=6)))

    async def _export_report(self, fmt: str):
        if not self._current_report:
            _show_snack(self._pg, "No report to export.", MOCHA["peach"])
            return

        ext_map = {"txt": ["txt"], "csv": ["csv"], "json": ["json"]}
        path = await self.export_picker.save_file(
            dialog_title=f"Export Missing ROMs ({fmt.upper()})",
            allowed_extensions=ext_map.get(fmt, ["txt"]),
            file_name=f"missing_roms.{fmt}",
        )
        if not path:
            return

        try:
            if fmt == "txt":
                self.state.reporter.export_txt(self._current_report, path)
            elif fmt == "csv":
                self.state.reporter.export_csv(self._current_report, path)
            elif fmt == "json":
                self.state.reporter.export_json(self._current_report, path)
            _show_snack(self._pg, f"Report exported: {path}", MOCHA["green"])
        except Exception as ex:
            _show_snack(self._pg, f"Export error: {ex}", MOCHA["red"])


# ─── Myrient Browser View ───────────────────────────────────────────────────────
class MyrientView(ft.Column):
    def __init__(self, state: AppState, pg: ft.Page):
        super().__init__(expand=True, spacing=0, scroll=ft.ScrollMode.AUTO)
        self.state = state
        self._pg = pg
        self._downloader = None
        self._selected_system = ""

        self.download_picker = ft.FilePicker()
        self._pg.services.append(self.download_picker)

        self.search_field = ft.TextField(
            hint_text="Search files...", prefix_icon=ft.Icons.SEARCH,
            border_radius=RADIUS_SM, bgcolor=MOCHA["surface0"], color=MOCHA["text"],
            hint_style=ft.TextStyle(color=MOCHA["overlay0"]),
            border_color=MOCHA["surface1"], focused_border_color=MOCHA["mauve"],
            height=40, text_size=13, on_submit=self._on_search, expand=True,
        )
        self.file_list = ft.ListView(spacing=4, expand=True, height=400, padding=ft.Padding.all(8))
        self.status_text = ft.Text("", size=12, color=MOCHA["subtext0"])
        self._download_folder = ""

    def _ensure_downloader(self):
        if self._downloader is None:
            try:
                from .myrient_downloader import MyrientDownloader
                self._downloader = MyrientDownloader()
            except Exception:
                self._downloader = None
        return self._downloader

    def build_content(self):
        self.controls.clear()
        self.padding = ft.Padding.all(30)

        dl = self._ensure_downloader()

        self.controls.extend([
            ft.Row(controls=[
                ft.Text("Myrient Browser", size=26, weight=ft.FontWeight.BOLD, color=MOCHA["text"]),
            ], spacing=12),
            ft.Container(height=10),
        ])

        if dl is None:
            self.controls.append(_card_container(ft.Column(controls=[
                ft.Icon(ft.Icons.WARNING_AMBER_OUTLINED, size=40, color=MOCHA["peach"]),
                ft.Text("'requests' library is required for Myrient.", size=14, color=MOCHA["subtext0"]),
                ft.Text("Install with: pip install requests", size=12, color=MOCHA["overlay0"]),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10), padding=ft.Padding.all(40)))
            return

        # System selector
        from .myrient_downloader import MyrientDownloader
        systems = MyrientDownloader.get_systems()
        system_options = [ft.dropdown.Option(key=s['name'], text=f"{s['name']} [{s['category']}]") for s in systems]

        system_dropdown = ft.Dropdown(
            label="System", options=system_options,
            value=self._selected_system or None,
            border_radius=RADIUS_SM, bgcolor=MOCHA["surface0"], color=MOCHA["text"],
            label_style=ft.TextStyle(color=MOCHA["subtext0"]),
            border_color=MOCHA["surface1"], focused_border_color=MOCHA["mauve"],
            expand=True, text_size=12,
            on_select=self._on_system_select,
        )

        self.controls.extend([
            ft.Text("Browse ROM files on Myrient.erista.me", size=12, color=MOCHA["subtext0"]),
            ft.Container(height=6),
            _card_container(ft.Column(controls=[
                ft.Row(controls=[system_dropdown], spacing=12),
                ft.Row(controls=[
                    self.search_field,
                    ft.Button("Search", icon=ft.Icons.SEARCH, bgcolor=MOCHA["blue"], color=MOCHA["crust"], on_click=self._on_search),
                ], spacing=8),
                ft.Row(controls=[
                    ft.Icon(ft.Icons.FOLDER_OUTLINED, color=MOCHA["overlay1"]),
                    ft.Text(self._download_folder or "No download folder selected", size=12, color=MOCHA["subtext0"], expand=True),
                    ft.Button("Browse", icon=ft.Icons.FOLDER_OPEN, bgcolor=MOCHA["surface1"], color=MOCHA["text"], on_click=self._on_browse_download_folder),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                self.status_text,
            ], spacing=10)),

            ft.Container(height=10),
            _card_container(self.file_list, bgcolor=MOCHA["crust"], padding=ft.Padding.all(4)),
        ])

    def _on_system_select(self, e):
        self._selected_system = e.control.value
        self.state.emit_activity("ui:myrient:system_select", f"Myrient system selected: {self._selected_system}", MOCHA["blue"])
        self.file_list.controls.clear()
        self.status_text.value = f"Loading files for {self._selected_system}..."
        try:
            self.status_text.update()
            self.file_list.update()
        except Exception:
            pass
        thread = threading.Thread(target=self._load_files, args=(self._selected_system, ""), daemon=True)
        thread.start()

    def _on_search(self, e):
        if not self._selected_system:
            self.state.emit_activity("ui:myrient:search:block", "Myrient search blocked: no system selected.", MOCHA["peach"])
            _show_snack(self._pg, "Select a system first.", MOCHA["peach"])
            return
        query = self.search_field.value or ""
        self.state.emit_activity("ui:myrient:search", f"Myrient search: '{query}' in {self._selected_system}", MOCHA["blue"])
        self.file_list.controls.clear()
        self.status_text.value = f"Searching '{query}' in {self._selected_system}..."
        try:
            self.status_text.update()
            self.file_list.update()
        except Exception:
            pass
        thread = threading.Thread(target=self._load_files, args=(self._selected_system, query), daemon=True)
        thread.start()

    def _load_files(self, system: str, query: str):
        dl = self._ensure_downloader()
        if not dl:
            return
        try:
            if query:
                files = dl.search_files(system, query)
            else:
                files = dl.list_files(system)
            self.file_list.controls.clear()
            if not files:
                self.file_list.controls.append(ft.Text("No files found.", size=12, color=MOCHA["overlay0"], italic=True))
            else:
                for rf in files[:200]:
                    self.file_list.controls.append(ft.Container(
                        content=ft.Row(controls=[
                            ft.Icon(ft.Icons.INSERT_DRIVE_FILE_OUTLINED, size=16, color=MOCHA["blue"]),
                            ft.Text(rf.name, size=11, color=MOCHA["text"], expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, selectable=True),
                            ft.IconButton(icon=ft.Icons.DOWNLOAD, icon_size=16, icon_color=MOCHA["green"], tooltip="Download", on_click=lambda e, url=rf.url, name=rf.name: self._download_file(url, name)),
                        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        bgcolor=MOCHA["mantle"], border_radius=6,
                        padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                    ))
                if len(files) > 200:
                    self.file_list.controls.append(ft.Text(f"Showing 200 of {len(files)} files. Use search to narrow results.", size=10, color=MOCHA["overlay0"]))

            self.status_text.value = f"{len(files)} file(s) found"
            try:
                self.file_list.update()
                self.status_text.update()
            except Exception:
                pass
        except Exception as ex:
            self.status_text.value = f"Error: {ex}"
            try:
                self.status_text.update()
            except Exception:
                pass

    async def _on_browse_download_folder(self, e):
        path = await self.download_picker.get_directory_path(dialog_title="Select Download Folder")
        if path:
            self._download_folder = path
            self.state.emit_activity("ui:myrient:download_folder", f"Download folder selected: {path}", MOCHA["blue"])
            self.build_content()
            self.update()

    def _download_file(self, url: str, name: str):
        if not self._download_folder:
            self.state.emit_activity("ui:myrient:download:block", "Download blocked: no folder selected.", MOCHA["peach"])
            _show_snack(self._pg, "Select a download folder first.", MOCHA["peach"])
            return
        self.status_text.value = f"Downloading {name}..."
        self.state.emit_activity("ui:myrient:download:start", f"Downloading {name}", MOCHA["blue"])
        try:
            self.status_text.update()
        except Exception:
            pass

        def worker():
            dl = self._ensure_downloader()
            if not dl:
                return
            dl.queue_rom(rom_name=name, url=url, dest_folder=self._download_folder, system_name=self._selected_system)
            progress = dl.start_downloads()
            if progress.completed > 0:
                self.status_text.value = f"Downloaded: {name}"
                downloaded_path = os.path.join(self._download_folder, name)
                if os.path.isfile(downloaded_path):
                    _copy_download_to_local_cache(downloaded_path)
                self.state.emit_activity("ui:myrient:download:success", f"Downloaded: {name}", MOCHA["green"])
                _show_snack(self._pg, f"Downloaded: {name}", MOCHA["green"])
            else:
                self.status_text.value = f"Failed: {name}"
                self.state.emit_activity("ui:myrient:download:failed", f"Download failed: {name}", MOCHA["red"])
                _show_snack(self._pg, f"Download failed: {name}", MOCHA["red"])
            try:
                self.status_text.update()
            except Exception:
                pass

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()


# ─── Settings View ──────────────────────────────────────────────────────────────
class SettingsView(ft.Column):
    def __init__(self, state: AppState, pg: ft.Page):
        super().__init__(expand=True, spacing=0, scroll=ft.ScrollMode.AUTO)
        self.state = state
        self._pg = pg

    def build_content(self):
        self.controls.clear()
        self.padding = ft.Padding.all(30)
        settings = self.state.settings

        self.controls.extend([
            ft.Row(controls=[
                ft.Icon(ft.Icons.SETTINGS_OUTLINED, size=28, color=MOCHA["mauve"]),
                ft.Text(_tr("menu_settings"), size=26, weight=ft.FontWeight.BOLD, color=MOCHA["text"]),
            ], spacing=12),
            ft.Container(height=10),
        ])

        # Profile presets
        profile_options = [ft.dropdown.Option(key=k, text=k.replace("_", " ").title()) for k in PROFILE_PRESETS]
        active_profile = settings.get("active_profile", "retroarch_frontend")

        profile_dropdown = ft.Dropdown(
            label="Active Profile", options=profile_options,
            value=active_profile,
            border_radius=RADIUS_SM, bgcolor=MOCHA["surface0"], color=MOCHA["text"],
            label_style=ft.TextStyle(color=MOCHA["subtext0"]),
            border_color=MOCHA["surface1"], focused_border_color=MOCHA["mauve"],
            width=300, text_size=13,
            on_select=self._on_profile_change,
        )

        profile_info = PROFILE_PRESETS.get(active_profile, {})
        profile_details = []
        if profile_info:
            profile_details = [
                ft.Text(f"Strategy: {profile_info.get('strategy', 'N/A')}", size=12, color=MOCHA["subtext0"]),
                ft.Text(f"Naming: {profile_info.get('naming_template', 'N/A')}", size=12, color=MOCHA["subtext0"]),
                ft.Text(f"Region Priority: {', '.join(profile_info.get('region_priority', [])[:5])}", size=12, color=MOCHA["subtext0"]),
                ft.Text(f"Exclude: {', '.join(profile_info.get('exclude_tags', []))}", size=12, color=MOCHA["subtext0"]),
            ]

        self.controls.extend([
            ft.Text("Organization Profiles", size=16, weight=ft.FontWeight.W_600, color=MOCHA["text"]),
            ft.Text("Presets configure strategy, naming, and region priority.", size=12, color=MOCHA["subtext0"]),
            ft.Container(height=6),
            _card_container(ft.Column(controls=[
                profile_dropdown,
                *profile_details,
            ], spacing=8)),
        ])

        # Region Priority
        region_policy = settings.get("region_policy", {})
        global_priority = region_policy.get("global_priority", [])
        allow_tags = region_policy.get("allow_tags", [])
        exclude_tags = region_policy.get("exclude_tags", [])

        self.region_field = ft.TextField(
            label="Region Priority (comma-separated)", value=", ".join(global_priority),
            border_radius=RADIUS_SM, bgcolor=MOCHA["surface0"], color=MOCHA["text"],
            border_color=MOCHA["surface1"], focused_border_color=MOCHA["mauve"],
            text_size=12, expand=True,
        )
        self.allow_tags_field = ft.TextField(
            label="Allow Tags", value=", ".join(allow_tags),
            border_radius=RADIUS_SM, bgcolor=MOCHA["surface0"], color=MOCHA["text"],
            border_color=MOCHA["surface1"], focused_border_color=MOCHA["mauve"],
            text_size=12, width=300,
        )
        self.exclude_tags_field = ft.TextField(
            label="Exclude Tags", value=", ".join(exclude_tags),
            border_radius=RADIUS_SM, bgcolor=MOCHA["surface0"], color=MOCHA["text"],
            border_color=MOCHA["surface1"], focused_border_color=MOCHA["mauve"],
            text_size=12, width=300,
        )

        self.controls.extend([
            ft.Container(height=20),
            ft.Text("Region & Tag Policy", size=16, weight=ft.FontWeight.W_600, color=MOCHA["text"]),
            ft.Container(height=6),
            _card_container(ft.Column(controls=[
                self.region_field,
                ft.Row(controls=[self.allow_tags_field, self.exclude_tags_field], spacing=12),
            ], spacing=10)),
        ])

        # Naming
        naming = settings.get("naming", {})
        self.naming_template_field = ft.TextField(
            label="Naming Template", value=naming.get("template", "{name}"),
            border_radius=RADIUS_SM, bgcolor=MOCHA["surface0"], color=MOCHA["text"],
            border_color=MOCHA["surface1"], focused_border_color=MOCHA["mauve"],
            text_size=12, width=300,
        )
        self.keep_tags_switch = ft.Switch(
            label="Keep name tags", value=naming.get("keep_tags", True),
            active_color=MOCHA["mauve"],
            label_text_style=ft.TextStyle(color=MOCHA["text"], size=12),
        )

        self.controls.extend([
            ft.Container(height=20),
            ft.Text("Naming", size=16, weight=ft.FontWeight.W_600, color=MOCHA["text"]),
            ft.Text("Available: {name}, {game}, {region}, {system}, {crc}", size=12, color=MOCHA["subtext0"]),
            ft.Container(height=6),
            _card_container(ft.Row(controls=[self.naming_template_field, self.keep_tags_switch], spacing=12)),
        ])

        # Health Check settings
        health = settings.get("health", {})
        self.health_enabled = ft.Switch(label="Enable health checks", value=health.get("enabled", True), active_color=MOCHA["mauve"], label_text_style=ft.TextStyle(color=MOCHA["text"], size=12))
        self.warn_duplicates = ft.Switch(label="Warn on duplicates", value=health.get("warn_on_duplicates", True), active_color=MOCHA["mauve"], label_text_style=ft.TextStyle(color=MOCHA["text"], size=12))
        self.warn_unknown_ext = ft.Switch(label="Warn on unknown extensions", value=health.get("warn_on_unknown_ext", True), active_color=MOCHA["mauve"], label_text_style=ft.TextStyle(color=MOCHA["text"], size=12))

        self.controls.extend([
            ft.Container(height=20),
            ft.Text("Health Checks", size=16, weight=ft.FontWeight.W_600, color=MOCHA["text"]),
            ft.Container(height=6),
            _card_container(ft.Row(controls=[self.health_enabled, self.warn_duplicates, self.warn_unknown_ext], spacing=16)),
        ])

        # Save button
        self.controls.extend([
            ft.Container(height=20),
            ft.Row(controls=[
                ft.Button("Save Settings", icon=ft.Icons.SAVE, bgcolor=MOCHA["green"], color=MOCHA["crust"], on_click=self._save_settings),
                ft.Button("Reset to Defaults", icon=ft.Icons.RESTORE, bgcolor=MOCHA["surface1"], color=MOCHA["text"], on_click=self._reset_settings),
            ], spacing=12),
        ])

    def _on_profile_change(self, e):
        profile_name = e.control.value
        self.state.settings["active_profile"] = profile_name
        apply_runtime_settings(self.state.settings, profile_name)
        self.build_content()
        self.update()
        self.state.emit_activity("ui:settings:profile", f"Profile changed: {profile_name.replace('_', ' ').title()}", MOCHA["green"])
        _show_snack(self._pg, f"Profile changed: {profile_name.replace('_', ' ').title()}", MOCHA["green"])

    def _save_settings(self, e):
        s = self.state.settings
        # Region policy
        s["region_policy"]["global_priority"] = [r.strip() for r in self.region_field.value.split(",") if r.strip()]
        s["region_policy"]["allow_tags"] = [t.strip() for t in self.allow_tags_field.value.split(",") if t.strip()]
        s["region_policy"]["exclude_tags"] = [t.strip() for t in self.exclude_tags_field.value.split(",") if t.strip()]
        # Naming
        s["naming"]["template"] = self.naming_template_field.value or "{name}"
        s["naming"]["keep_tags"] = bool(self.keep_tags_switch.value)
        # Health
        s["health"]["enabled"] = bool(self.health_enabled.value)
        s["health"]["warn_on_duplicates"] = bool(self.warn_duplicates.value)
        s["health"]["warn_on_unknown_ext"] = bool(self.warn_unknown_ext.value)

        try:
            save_settings(s)
            apply_runtime_settings(s)
            self.state.persist_session()
            self.state.emit_activity("ui:settings:save", "Settings saved.", MOCHA["green"])
            _show_snack(self._pg, "Settings saved!", MOCHA["green"])
        except Exception as ex:
            self.state.emit_activity("ui:settings:save_error", f"Save error: {ex}", MOCHA["red"])
            _show_snack(self._pg, f"Save error: {ex}", MOCHA["red"])

    def _reset_settings(self, e):
        from copy import deepcopy
        self.state.settings = deepcopy(DEFAULT_SETTINGS)
        apply_runtime_settings(self.state.settings)
        self.build_content()
        self.update()
        self.state.persist_session()
        self.state.emit_activity("ui:settings:reset", "Settings reset to defaults.", MOCHA["green"])
        _show_snack(self._pg, "Settings reset to defaults.", MOCHA["green"])


# ─── Main Application ───────────────────────────────────────────────────────────
def main(page: ft.Page):
    page.title = f"{_tr('flet_brand')} - {_tr('title_main')}"
    page.bgcolor = MOCHA["base"]
    page.padding = 0
    page.spacing = 0
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 1300
    page.window.height = 850
    page.window.min_width = 900
    page.window.min_height = 600

    state = AppState()
    state.restore_session()
    flet_version = getattr(ft, "__version__", "unknown")
    state.emit_activity("startup:ui", "Flet UI initialized.", MOCHA["green"])
    state.emit_activity("startup:flet_version", f"Flet runtime version: {flet_version}", MOCHA["subtext0"])
    if flet_version != "unknown" and _version_tuple(flet_version) < _version_tuple(MIN_FLET_VERSION):
        state.emit_activity("startup:flet_version:warning", f"Flet {flet_version} is below required {MIN_FLET_VERSION}.", MOCHA["yellow"])
    content_area = ft.Container(expand=True, bgcolor=MOCHA["base"])
    session_save_picker = ft.FilePicker()
    page.services.append(session_save_picker)

    def ask_new_session():
        state.emit_activity("ui:new_session:prompt_opened", "New session prompt opened.", MOCHA["blue"])

        def _reset_session(clear_cache: bool, close_dialog: Optional[ft.Control] = None):
            if clear_cache:
                _clear_app_cache()
            state.reset_session()
            state.emit_activity("ui:new_session:reset", "Session reset completed.", MOCHA["green"])
            switch_view(0)
            if close_dialog:
                _safe_close_overlay(page, close_dialog)
            _show_snack(page, "Nova sessão iniciada.", MOCHA["green"])

        async def _save_and_reset(_):
            state.emit_activity("ui:new_session:save_confirmed", "User chose to save before starting a new session.", MOCHA["blue"])
            os.makedirs(SESSION_EXPORTS_DIR, exist_ok=True)
            default_name = f"session-{int(time.time())}.romcol.json"
            save_path = await session_save_picker.save_file(
                dialog_title="Salvar coleção atual",
                file_name=default_name,
                initial_directory=SESSION_EXPORTS_DIR,
                allowed_extensions=["json"],
            )
            if not save_path:
                state.emit_activity("ui:new_session:save_picker_cancel", "Save collection dialog canceled.", MOCHA["peach"])
                _show_snack(page, "Salvar cancelado.", MOCHA["peach"])
                return

            try:
                now = time.strftime("%Y-%m-%dT%H:%M:%S")
                collection = Collection(
                    name=os.path.splitext(os.path.basename(save_path))[0],
                    created_at=now,
                    updated_at=now,
                    dat_infos=state.multi_matcher.get_dat_list(),
                    dat_filepaths=[d.filepath for d in state.multi_matcher.get_dat_list()],
                    identified=[s.to_dict() for s in state.identified],
                    unidentified=[s.to_dict() for s in state.unidentified],
                )
                state.collection_manager.save(collection, filepath=save_path)
                state.emit_activity("ui:new_session:save_success", f"Collection saved before reset: {save_path}", MOCHA["green"])
                _show_snack(page, "Coleção salva com sucesso.", MOCHA["green"])
                _reset_session(clear_cache=True, close_dialog=dialog)
            except Exception as ex:
                state.emit_activity("ui:new_session:save_error", f"Error saving collection before reset: {ex}", MOCHA["red"])
                _show_snack(page, f"Erro ao salvar coleção: {ex}", MOCHA["red"], 5000)

        def _dont_save(_):
            state.emit_activity("ui:new_session:no_save", "User skipped saving current collection.", MOCHA["peach"])
            _show_snack(page, "Coleção atual descartada.", MOCHA["peach"])
            _reset_session(clear_cache=True, close_dialog=dialog)

        def _cancel(_):
            state.emit_activity("ui:new_session:cancel", "New session canceled.", MOCHA["overlay0"])
            _safe_close_overlay(page, dialog)
            _show_snack(page, "Nova sessão cancelada.", MOCHA["overlay0"])

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Nova sessão"),
            content=ft.Text("Deseja salvar a coleção atual antes de iniciar uma sessão limpa?"),
            actions=[
                ft.TextButton("Cancelar", on_click=_cancel),
                ft.TextButton("Não", on_click=_dont_save),
                ft.ElevatedButton("Sim", on_click=_save_and_reset),
            ],
        )
        _safe_open_overlay(page, dialog)

    def navigate(index: int):
        state.emit_activity("ui:navigate", f"Navigated to view index {index}.", MOCHA["blue"])
        nav_rail.selected_index = index
        nav_rail.update()
        switch_view(index)

    dashboard_view = DashboardView(state, page, navigate, ask_new_session)
    library_view = LibraryView(state, page, navigate)
    import_scan_view = ImportScanView(state, page, on_scan_complete=lambda: switch_view(nav_rail.selected_index))
    tools_logs_view = ToolsLogsView(state, page)
    missing_view = MissingReportsView(state, page)
    settings_view = SettingsView(state, page)

    views = [dashboard_view, library_view, import_scan_view, tools_logs_view, missing_view, settings_view]

    def switch_view(index: int):
        view = views[index]
        view.build_content()
        content_area.content = view
        content_area.update()
        state.persist_session()

    language_is_pt = _safe_get_language() == LANG_PT_BR

    def _toggle_language(e):
        _set_language(LANG_PT_BR if e.control.value else LANG_EN)
        page.clean()
        main(page)

    nav_rail = ft.NavigationRail(
        selected_index=0,
        extended=False,
        label_type=ft.NavigationRailLabelType.NONE,
        min_width=104,
        min_extended_width=104,
        bgcolor=MOCHA["mantle"],
        indicator_color=MOCHA["surface1"],
        leading=ft.Container(
            content=ft.Column(controls=[
                ft.Icon(ft.Icons.SPORTS_ESPORTS, size=24, color=MOCHA["mauve"]),
                ft.Text(_tr("flet_brand"), size=11, weight=ft.FontWeight.W_500, color=MOCHA["mauve"]),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=SPACE_8),
            padding=ft.Padding.only(top=SPACE_16, bottom=SPACE_8),
        ),
        trailing=ft.Container(
            content=ft.Row(
                controls=[
                    ft.Text("EN", size=11, color=MOCHA["subtext0"]),
                    ft.Switch(value=language_is_pt, on_change=_toggle_language, active_color=MOCHA["mauve"]),
                    ft.Text("PT", size=11, color=MOCHA["subtext0"]),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.only(bottom=SPACE_16),
        ),
        destinations=[
            ft.NavigationRailDestination(icon=ft.Icons.DASHBOARD_OUTLINED, selected_icon=ft.Icons.DASHBOARD, label=_tr("flet_nav_dashboard")),
            ft.NavigationRailDestination(icon=ft.Icons.GRID_VIEW_OUTLINED, selected_icon=ft.Icons.GRID_VIEW, label=_tr("flet_nav_library")),
            ft.NavigationRailDestination(icon=ft.Icons.UPLOAD_FILE_OUTLINED, selected_icon=ft.Icons.UPLOAD_FILE, label=_tr("flet_nav_import")),
            ft.NavigationRailDestination(icon=ft.Icons.BUILD_OUTLINED, selected_icon=ft.Icons.BUILD, label=_tr("flet_nav_tools")),
            ft.NavigationRailDestination(icon=ft.Icons.ASSIGNMENT_OUTLINED, selected_icon=ft.Icons.ASSIGNMENT, label=_tr("tab_missing")),
            ft.NavigationRailDestination(icon=ft.Icons.SETTINGS_OUTLINED, selected_icon=ft.Icons.SETTINGS, label=_tr("menu_settings")),
        ],
        on_change=lambda e: navigate(e.control.selected_index),
    )

    page.add(ft.Row(controls=[
        nav_rail,
        ft.VerticalDivider(width=1, color=MOCHA["surface1"]),
        content_area,
    ], expand=True, spacing=0))

    page.on_disconnect = lambda e: state.persist_session()

    switch_view(0)
    if flet_version != "unknown" and _version_tuple(flet_version) < _version_tuple(MIN_FLET_VERSION):
        _show_snack(page, f"Aviso: Flet {flet_version} < {MIN_FLET_VERSION}. Atualize para evitar incompatibilidades.", MOCHA["yellow"], 6000)


# ─── Entry Point ─────────────────────────────────────────────────────────────────
GUI_FLET_AVAILABLE = True


def run_flet_gui():
    """Launch the Flet desktop GUI."""
    _ensure_app_structure()
    apply_runtime_settings(load_settings())
    ft.run(main)
    return 0


if __name__ == "__main__":
    run_flet_gui()
