"""
R0MM - Flet-based Desktop GUI
Catppuccin Mocha color scheme with Progressive Disclosure design.
Compatible with Flet 0.80+.
"""

import os
import sys
import threading
from typing import List, Optional

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
from .shared_config import STRATEGIES
from .blindmatch import build_blindmatch_rom

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


# ─── Application State ─────────────────────────────────────────────────────────
class AppState:
    """Central application state shared across all views."""

    def __init__(self):
        self.multi_matcher = MultiROMMatcher()
        self.organizer = Organizer()
        self.collection_manager = CollectionManager()
        self.reporter = MissingROMReporter()
        self.identified: List[ScannedFile] = []
        self.unidentified: List[ScannedFile] = []
        self.scanning = False
        self.scan_progress = 0
        self.scan_total = 0
        self.blindmatch_mode = False
        self.blindmatch_system = ""


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _show_snack(pg: ft.Page, text: str, color: str = MOCHA["text"], duration: int = 3000):
    """Show a non-blocking snackbar notification."""
    sb = ft.SnackBar(
        content=ft.Text(text, color=color),
        bgcolor=MOCHA["surface0"],
        duration=duration,
    )
    pg.show_dialog(sb)


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
        padding=ft.padding.symmetric(horizontal=6, vertical=2),
    )


# ─── Game Card for Library GridView ───────────────────────────────────────────
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
                                    first_letter,
                                    size=36,
                                    weight=ft.FontWeight.BOLD,
                                    color=MOCHA["overlay0"],
                                ),
                                bgcolor=MOCHA["surface0"],
                                border_radius=ft.border_radius.only(
                                    top_left=8, top_right=8
                                ),
                                alignment=ft.Alignment(0, 0),
                                expand=True,
                            ),
                            ft.Container(
                                content=ft.Column(
                                    controls=[
                                        ft.Text(
                                            game_name,
                                            size=11,
                                            weight=ft.FontWeight.W_600,
                                            color=MOCHA["text"],
                                            max_lines=2,
                                            overflow=ft.TextOverflow.ELLIPSIS,
                                        ),
                                        ft.Text(
                                            system if system else "",
                                            size=9,
                                            color=MOCHA["subtext0"],
                                            max_lines=1,
                                            overflow=ft.TextOverflow.ELLIPSIS,
                                        ),
                                    ],
                                    spacing=2,
                                ),
                                padding=ft.padding.all(8),
                                bgcolor=MOCHA["mantle"],
                                border_radius=ft.border_radius.only(
                                    bottom_left=8, bottom_right=8
                                ),
                            ),
                        ],
                        spacing=0,
                    ),
                    border_radius=8,
                    border=ft.border.all(1, MOCHA["surface1"]),
                    clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                ),
                ft.Container(
                    content=region_badge(region),
                    top=6,
                    right=6,
                ),
            ],
        ),
        on_click=lambda e: on_click(scanned),
        animate=ft.Animation(200, ft.AnimationCurve.EASE_IN_OUT),
        ink=True,
    )


# ─── Detail Panel (slides in from right) ──────────────────────────────────────
class DetailPanel(ft.Container):
    """Right-side sliding panel showing ROM metadata."""

    def __init__(self, pg: ft.Page):
        super().__init__()
        self._pg = pg
        self._scanned: Optional[ScannedFile] = None

        self._clipboard = ft.Clipboard()
        self._pg.overlay.append(self._clipboard)

        self.title_text = ft.Text("", size=18, weight=ft.FontWeight.BOLD, color=MOCHA["text"])
        self.system_text = ft.Text("", size=13, color=MOCHA["subtext0"])
        self.region_container = ft.Row(controls=[], spacing=6)

        self.meta_column = ft.Column(controls=[], spacing=8, scroll=ft.ScrollMode.AUTO)
        self.action_row = ft.Row(controls=[], spacing=8)

        self.close_btn = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_color=MOCHA["overlay1"],
            icon_size=18,
            on_click=self._close,
        )

        self.width = 340
        self.bgcolor = MOCHA["mantle"]
        self.border = ft.border.only(left=ft.BorderSide(1, MOCHA["surface1"]))
        self.padding = ft.padding.all(20)
        self.visible = False
        self.animate_opacity = ft.Animation(250, ft.AnimationCurve.EASE_OUT)
        self.opacity = 0

        self.content = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Column(
                            controls=[self.title_text, self.system_text],
                            spacing=4,
                            expand=True,
                        ),
                        self.close_btn,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                self.region_container,
                ft.Divider(height=1, color=MOCHA["surface1"]),
                self.meta_column,
                ft.Divider(height=1, color=MOCHA["surface1"]),
                self.action_row,
            ],
            spacing=12,
            expand=True,
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
        meta_items = [
            ("File", scanned.filename),
            ("Path", scanned.path),
            ("Size", format_size(scanned.size)),
            ("CRC32", scanned.crc32.upper()),
        ]
        if rom:
            meta_items.extend([
                ("ROM Name", rom.name),
                ("MD5", rom.md5.upper() if rom.md5 else "N/A"),
                ("SHA1", rom.sha1.upper() if rom.sha1 else "N/A"),
                ("Status", rom.status if rom.status else "Verified"),
                ("Languages", rom.languages if rom.languages else "N/A"),
            ])

        for label, value in meta_items:
            self.meta_column.controls.append(
                ft.Column(
                    controls=[
                        ft.Text(label, size=10, color=MOCHA["overlay1"], weight=ft.FontWeight.BOLD),
                        ft.Text(
                            value,
                            size=12,
                            color=MOCHA["text"],
                            selectable=True,
                            max_lines=3,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ],
                    spacing=2,
                )
            )

        self.action_row.controls = [
            ft.ElevatedButton(
                _tr("flet_open_folder"),
                icon=ft.Icons.FOLDER_OPEN,
                bgcolor=MOCHA["surface0"],
                color=MOCHA["text"],
                on_click=self._open_folder,
            ),
            ft.ElevatedButton(
                _tr("flet_copy_crc"),
                icon=ft.Icons.CONTENT_COPY,
                bgcolor=MOCHA["surface0"],
                color=MOCHA["text"],
                on_click=self._copy_crc,
            ),
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


# ─── Empty State Widget ──────────────────────────────────────────────────────
def empty_state(message: str, sub: str, button_label: str, on_button) -> ft.Container:
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Icon(ft.Icons.SPORTS_ESPORTS_OUTLINED, size=80, color=MOCHA["overlay0"]),
                ft.Text(message, size=22, weight=ft.FontWeight.BOLD, color=MOCHA["text"], text_align=ft.TextAlign.CENTER),
                ft.Text(sub, size=14, color=MOCHA["subtext0"], text_align=ft.TextAlign.CENTER),
                ft.Container(height=16),
                ft.ElevatedButton(
                    button_label,
                    icon=ft.Icons.ADD,
                    bgcolor=MOCHA["mauve"],
                    color=MOCHA["crust"],
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
                    on_click=on_button,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=8,
        ),
        expand=True,
        alignment=ft.Alignment(0, 0),
    )


# ─── Dashboard View ──────────────────────────────────────────────────────────
class DashboardView(ft.Column):
    def __init__(self, state: AppState, pg: ft.Page, navigate_cb):
        super().__init__(expand=True, spacing=20, scroll=ft.ScrollMode.AUTO)
        self.state = state
        self._pg = pg
        self.navigate_cb = navigate_cb
        self.padding = ft.padding.all(30)

    def build_content(self):
        self.controls.clear()

        dats = self.state.multi_matcher.get_dat_list()
        id_count = len(self.state.identified)
        un_count = len(self.state.unidentified)
        total = id_count + un_count

        self.controls.append(
            ft.Row(
                controls=[
                    ft.Icon(ft.Icons.DASHBOARD_OUTLINED, size=28, color=MOCHA["mauve"]),
                    ft.Text(_tr("flet_nav_dashboard"), size=26, weight=ft.FontWeight.BOLD, color=MOCHA["text"]),
                ],
                spacing=12,
            )
        )

        stats = [
            (_tr("flet_dat_files"), str(len(dats)), ft.Icons.DESCRIPTION_OUTLINED, MOCHA["blue"]),
            (_tr("tab_identified"), str(id_count), ft.Icons.CHECK_CIRCLE_OUTLINE, MOCHA["green"]),
            (_tr("tab_unidentified"), str(un_count), ft.Icons.HELP_OUTLINE, MOCHA["peach"]),
            (_tr("flet_total"), str(total), ft.Icons.STORAGE_OUTLINED, MOCHA["lavender"]),
        ]

        stat_cards = []
        for label, value, icon, color in stats:
            stat_cards.append(
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Icon(icon, size=32, color=color),
                            ft.Column(
                                controls=[
                                    ft.Text(value, size=28, weight=ft.FontWeight.BOLD, color=MOCHA["text"]),
                                    ft.Text(label, size=12, color=MOCHA["subtext0"]),
                                ],
                                spacing=2,
                            ),
                        ],
                        spacing=14,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor=MOCHA["surface0"],
                    border_radius=12,
                    padding=ft.padding.all(20),
                    expand=True,
                    border=ft.border.all(1, MOCHA["surface1"]),
                )
            )

        self.controls.append(ft.Row(controls=stat_cards, spacing=16))

        if dats:
            self.controls.append(
                ft.Text(_tr("flet_collection_completeness"), size=18, weight=ft.FontWeight.W_600, color=MOCHA["text"])
            )
            completeness = self.state.multi_matcher.get_completeness_by_dat(self.state.identified)
            for dat_id, comp in completeness.items():
                dat_info = self.state.multi_matcher.dat_infos.get(dat_id)
                if not dat_info:
                    continue
                pct = comp.get("percentage", 0)
                found = comp.get("found", 0)
                total_in_dat = comp.get("total_in_dat", 0)
                bar_color = MOCHA["green"] if pct > 75 else MOCHA["yellow"] if pct > 40 else MOCHA["red"]

                self.controls.append(
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Text(dat_info.system_name or dat_info.name, size=13, weight=ft.FontWeight.W_600, color=MOCHA["text"], expand=True),
                                        ft.Text(f"{found}/{total_in_dat} ({pct:.1f}%)", size=12, color=MOCHA["subtext0"]),
                                    ],
                                ),
                                ft.ProgressBar(value=pct / 100, bgcolor=MOCHA["surface1"], color=bar_color, bar_height=6, border_radius=3),
                            ],
                            spacing=6,
                        ),
                        bgcolor=MOCHA["surface0"],
                        border_radius=10,
                        padding=ft.padding.all(16),
                        border=ft.border.all(1, MOCHA["surface1"]),
                    )
                )
        else:
            self.controls.append(
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Icon(ft.Icons.INFO_OUTLINE, size=40, color=MOCHA["overlay0"]),
                            ft.Text("No DAT files loaded yet", size=16, color=MOCHA["subtext0"]),
                            ft.ElevatedButton(
                                "Go to Import & Scan",
                                icon=ft.Icons.UPLOAD_FILE,
                                bgcolor=MOCHA["mauve"],
                                color=MOCHA["crust"],
                                on_click=lambda e: self.navigate_cb(2),
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=10,
                    ),
                    alignment=ft.Alignment(0, 0),
                    padding=ft.padding.all(40),
                    bgcolor=MOCHA["surface0"],
                    border_radius=12,
                    border=ft.border.all(1, MOCHA["surface1"]),
                )
            )


# ─── Library View ─────────────────────────────────────────────────────────────
class LibraryView(ft.Row):
    def __init__(self, state: AppState, pg: ft.Page, navigate_cb):
        super().__init__(expand=True, spacing=0)
        self.state = state
        self._pg = pg
        self.navigate_cb = navigate_cb

        self.search_field = ft.TextField(
            hint_text="Search games...",
            prefix_icon=ft.Icons.SEARCH,
            border_radius=8,
            bgcolor=MOCHA["surface0"],
            color=MOCHA["text"],
            hint_style=ft.TextStyle(color=MOCHA["overlay0"]),
            border_color=MOCHA["surface1"],
            focused_border_color=MOCHA["mauve"],
            height=42,
            text_size=13,
            on_change=self._on_search,
            expand=True,
        )

        self.grid = ft.GridView(
            expand=True,
            runs_count=5,
            max_extent=200,
            child_aspect_ratio=0.72,
            spacing=14,
            run_spacing=14,
            padding=ft.padding.all(20),
        )

        self.detail_panel = DetailPanel(pg)
        self._search_text = ""

    def build_content(self):
        items = self.state.identified
        if not items:
            main_area = ft.Column(
                controls=[
                    self._build_toolbar(),
                    empty_state(
                        "Your library is empty",
                        "Import a DAT file and scan a folder to see your ROMs here.",
                        "Import & Scan",
                        lambda e: self.navigate_cb(2),
                    ),
                ],
                expand=True,
                spacing=0,
            )
        else:
            self._populate_grid(items)
            main_area = ft.Column(
                controls=[
                    self._build_toolbar(),
                    self.grid,
                ],
                expand=True,
                spacing=0,
            )

        self.controls = [main_area, self.detail_panel]

    def _build_toolbar(self):
        id_count = len(self.state.identified)
        un_count = len(self.state.unidentified)
        total = id_count + un_count
        pct = (id_count / total * 100) if total else 0

        return ft.Container(
            content=ft.Row(
                controls=[
                    self.search_field,
                    ft.Container(width=12),
                    ft.Text(
                        f"{id_count} identified  |  {un_count} unidentified  |  {pct:.0f}%",
                        size=12,
                        color=MOCHA["subtext0"],
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=20, vertical=12),
            bgcolor=MOCHA["mantle"],
            border=ft.border.only(bottom=ft.BorderSide(1, MOCHA["surface1"])),
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


# ─── Import & Scan View ──────────────────────────────────────────────────────
class ImportScanView(ft.Column):
    def __init__(self, state: AppState, pg: ft.Page, on_scan_complete):
        super().__init__(expand=True, spacing=0, scroll=ft.ScrollMode.AUTO)
        self.state = state
        self._pg = pg
        self.on_scan_complete = on_scan_complete

        # File pickers (Flet 0.80 Service-based, async)
        self.dat_picker = ft.FilePicker()
        self._pg.overlay.append(self.dat_picker)

        self.folder_picker = ft.FilePicker()
        self._pg.overlay.append(self.folder_picker)

        self.dat_list = ft.ListView(spacing=4, height=180, padding=ft.padding.all(8))
        self.folder_path_text = ft.Text(_tr("flet_no_folder"), size=13, color=MOCHA["subtext0"], expand=True)
        self.recursive_switch = ft.Switch(label="Recursive", value=True, active_color=MOCHA["mauve"], label_text_style=ft.TextStyle(color=MOCHA["text"], size=12))
        self.archives_switch = ft.Switch(label="Scan archives", value=True, active_color=MOCHA["mauve"], label_text_style=ft.TextStyle(color=MOCHA["text"], size=12))

        self.scan_btn = ft.ElevatedButton(
            "Start Scan",
            icon=ft.Icons.RADAR,
            bgcolor=MOCHA["green"],
            color=MOCHA["crust"],
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=self._start_scan,
            disabled=True,
        )

        self.progress_text = ft.Text("", size=12, color=MOCHA["subtext0"])
        self.blindmatch_switch = ft.Switch(label="BlindMatch", value=False)
        self.blindmatch_system_field = ft.TextField(label="System", width=220)
        self._selected_folder = ""

    def build_content(self):
        self.controls.clear()
        self.padding = ft.padding.all(30)

        self._refresh_dat_list()

        self.controls.extend([
            ft.Row(
                controls=[
                    ft.Icon(ft.Icons.UPLOAD_FILE, size=28, color=MOCHA["mauve"]),
                    ft.Text(_tr("flet_import_scan"), size=26, weight=ft.FontWeight.BOLD, color=MOCHA["text"]),
                ],
                spacing=12,
            ),
            ft.Container(height=10),

            ft.Text(_tr("flet_dat_files"), size=16, weight=ft.FontWeight.W_600, color=MOCHA["text"]),
            ft.Text(_tr("flet_dat_help"), size=12, color=MOCHA["subtext0"]),
            ft.Container(height=6),
            ft.Container(
                content=ft.Column(
                    controls=[
                        self.dat_list,
                        ft.Row(
                            controls=[
                                ft.ElevatedButton(
                                    _tr("flet_add_dat"),
                                    icon=ft.Icons.ADD,
                                    bgcolor=MOCHA["blue"],
                                    color=MOCHA["crust"],
                                    on_click=self._on_add_dat_click,
                                ),
                                ft.ElevatedButton(
                                    _tr("flet_remove_selected"),
                                    icon=ft.Icons.DELETE_OUTLINE,
                                    bgcolor=MOCHA["surface1"],
                                    color=MOCHA["text"],
                                    on_click=self._remove_selected_dat,
                                ),
                            ],
                            spacing=8,
                        ),
                    ],
                    spacing=10,
                ),
                bgcolor=MOCHA["surface0"],
                border_radius=12,
                padding=ft.padding.all(16),
                border=ft.border.all(1, MOCHA["surface1"]),
            ),

            ft.Container(height=20),

            ft.Text(_tr("flet_scan_folder"), size=16, weight=ft.FontWeight.W_600, color=MOCHA["text"]),
            ft.Text(_tr("flet_scan_help"), size=12, color=MOCHA["subtext0"]),
            ft.Container(height=6),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.FOLDER_OUTLINED, color=MOCHA["overlay1"]),
                                self.folder_path_text,
                                ft.ElevatedButton(
                                    _tr("flet_browse"),
                                    icon=ft.Icons.FOLDER_OPEN,
                                    bgcolor=MOCHA["surface1"],
                                    color=MOCHA["text"],
                                    on_click=self._on_browse_folder_click,
                                ),
                            ],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Row(controls=[self.recursive_switch, self.archives_switch, self.blindmatch_switch, self.blindmatch_system_field], spacing=16),
                        ft.Divider(height=1, color=MOCHA["surface1"]),
                        ft.Row(
                            controls=[
                                self.scan_btn,
                                self.progress_text,
                            ],
                            spacing=12,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    ],
                    spacing=10,
                ),
                bgcolor=MOCHA["surface0"],
                border_radius=12,
                padding=ft.padding.all(16),
                border=ft.border.all(1, MOCHA["surface1"]),
            ),
        ])

    def _refresh_dat_list(self):
        self.dat_list.controls.clear()
        dats = self.state.multi_matcher.get_dat_list()
        if not dats:
            self.dat_list.controls.append(
                ft.Text("No DAT files loaded", size=12, color=MOCHA["overlay0"], italic=True)
            )
            return
        for dat in dats:
            self.dat_list.controls.append(
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Checkbox(value=False, data=dat.id, active_color=MOCHA["mauve"]),
                            ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, size=18, color=MOCHA["blue"]),
                            ft.Column(
                                controls=[
                                    ft.Text(dat.system_name or dat.name, size=13, weight=ft.FontWeight.W_600, color=MOCHA["text"]),
                                    ft.Text(f"{dat.rom_count} ROMs  |  v{dat.version}" if dat.version else f"{dat.rom_count} ROMs", size=11, color=MOCHA["subtext0"]),
                                ],
                                spacing=1,
                                expand=True,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor=MOCHA["mantle"],
                    border_radius=8,
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                )
            )
        self._update_scan_btn_state()

    async def _on_add_dat_click(self, e):
        files = await self.dat_picker.pick_files(
            dialog_title="Select DAT file",
            allowed_extensions=["dat", "xml", "gz", "zip"],
            allow_multiple=True,
        )
        if not files:
            return
        errors = []
        for f in files:
            try:
                dat_info, roms = DATParser.parse_with_info(f.path)
                self.state.multi_matcher.add_dat(dat_info, roms)
            except Exception as ex:
                errors.append(f"{f.name}: {ex}")

        self._refresh_dat_list()
        self.build_content()
        self.update()

        if errors:
            _show_snack(self._pg, f"Errors: {'; '.join(errors)}", MOCHA["red"], 5000)
        else:
            _show_snack(self._pg, f"Loaded {len(files)} DAT file(s)", MOCHA["green"])

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

    async def _on_browse_folder_click(self, e):
        path = await self.folder_picker.get_directory_path(dialog_title="Select ROM folder")
        if path:
            self._selected_folder = path
            self.folder_path_text.value = path
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
        self.state.blindmatch_mode = bool(self.blindmatch_switch.value)
        self.state.blindmatch_system = (self.blindmatch_system_field.value or "").strip()
        self.scan_btn.disabled = True
        self.scan_btn.text = "Scanning..."
        self.scan_btn.update()

        recursive = self.recursive_switch.value
        scan_archives = self.archives_switch.value

        thread = threading.Thread(
            target=self._scan_worker,
            args=(folder, recursive, scan_archives),
            daemon=True,
        )
        thread.start()

    def _scan_worker(self, folder: str, recursive: bool, scan_archives: bool):
        try:
            files = FileScanner.collect_files(folder, recursive=recursive, scan_archives=scan_archives)
            total = len(files)
            self.state.scan_total = total
            self.state.scan_progress = 0

            scanned_all: List[ScannedFile] = []

            for i, fpath in enumerate(files):
                try:
                    if fpath.lower().endswith('.zip') and scan_archives:
                        results = FileScanner.scan_archive_contents(fpath)
                    else:
                        results = [FileScanner.scan_file(fpath)]
                    scanned_all.extend(results)
                except Exception:
                    pass

                self.state.scan_progress = i + 1

                if (i + 1) % 50 == 0 or (i + 1) == total:
                    self.progress_text.value = f"Scanned {i + 1}/{total} files..."
                    try:
                        self.progress_text.update()
                    except Exception:
                        pass

            identified, unidentified = self.state.multi_matcher.match_all(scanned_all)
            self.state.identified = identified
            self.state.unidentified = unidentified

        except Exception as ex:
            _show_snack(self._pg, f"Scan error: {ex}", MOCHA["red"], 5000)
        finally:
            self.state.scanning = False
            self.scan_btn.disabled = False
            self.scan_btn.text = "Start Scan"

            id_count = len(self.state.identified)
            un_count = len(self.state.unidentified)
            self.progress_text.value = f"Done! {id_count} identified, {un_count} unidentified"

            try:
                self.scan_btn.update()
                self.progress_text.update()
            except Exception:
                pass

            _show_snack(self._pg, f"Scan complete: {id_count} identified, {un_count} unidentified", MOCHA["green"], 4000)

            if self.on_scan_complete:
                self.on_scan_complete()


# ─── Tools & Logs View ───────────────────────────────────────────────────────
class ToolsLogsView(ft.Column):
    def __init__(self, state: AppState, pg: ft.Page):
        super().__init__(expand=True, spacing=0, scroll=ft.ScrollMode.AUTO)
        self.state = state
        self._pg = pg

        self.output_picker = ft.FilePicker()
        self._pg.overlay.append(self.output_picker)

        self.save_name_field = ft.TextField(
            hint_text="Collection name",
            border_radius=8,
            bgcolor=MOCHA["surface0"],
            color=MOCHA["text"],
            hint_style=ft.TextStyle(color=MOCHA["overlay0"]),
            border_color=MOCHA["surface1"],
            focused_border_color=MOCHA["mauve"],
            height=42,
            text_size=13,
            expand=True,
        )

        self.collection_picker = ft.FilePicker()
        self._pg.overlay.append(self.collection_picker)

        self.strategy_dropdown = ft.Dropdown(
            label="Strategy",
            options=[ft.dropdown.Option(key=s["id"], text=s["name"]) for s in STRATEGIES],
            value="flat",
            border_radius=8,
            bgcolor=MOCHA["surface0"],
            color=MOCHA["text"],
            label_style=ft.TextStyle(color=MOCHA["subtext0"]),
            border_color=MOCHA["surface1"],
            focused_border_color=MOCHA["mauve"],
            width=200,
            text_size=13,
        )

        self.action_dropdown = ft.Dropdown(
            label="Action",
            options=[
                ft.dropdown.Option(key="copy", text="Copy"),
                ft.dropdown.Option(key="move", text="Move"),
            ],
            value="copy",
            border_radius=8,
            bgcolor=MOCHA["surface0"],
            color=MOCHA["text"],
            label_style=ft.TextStyle(color=MOCHA["subtext0"]),
            border_color=MOCHA["surface1"],
            focused_border_color=MOCHA["mauve"],
            width=140,
            text_size=13,
        )

        self.output_path_text = ft.Text(_tr("flet_no_output"), size=13, color=MOCHA["subtext0"], expand=True)
        self._output_folder = ""

        self.log_view = ft.ListView(spacing=2, height=200, padding=ft.padding.all(8), auto_scroll=True)

    def build_content(self):
        self.controls.clear()
        self.padding = ft.padding.all(30)

        self.controls.extend([
            ft.Row(
                controls=[
                    ft.Icon(ft.Icons.BUILD_OUTLINED, size=28, color=MOCHA["mauve"]),
                    ft.Text(_tr("flet_tools_logs"), size=26, weight=ft.FontWeight.BOLD, color=MOCHA["text"]),
                ],
                spacing=12,
            ),
            ft.Container(height=10),

            ft.Text(_tr("flet_organize_roms"), size=16, weight=ft.FontWeight.W_600, color=MOCHA["text"]),
            ft.Text(_tr("flet_organize_help"), size=12, color=MOCHA["subtext0"]),
            ft.Container(height=6),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[self.strategy_dropdown, self.action_dropdown],
                            spacing=12,
                        ),
                        ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.FOLDER_OUTLINED, color=MOCHA["overlay1"]),
                                self.output_path_text,
                                ft.ElevatedButton(
                                    _tr("flet_browse"),
                                    icon=ft.Icons.FOLDER_OPEN,
                                    bgcolor=MOCHA["surface1"],
                                    color=MOCHA["text"],
                                    on_click=self._on_browse_output_click,
                                ),
                            ],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Divider(height=1, color=MOCHA["surface1"]),
                        ft.Row(
                            controls=[
                                ft.ElevatedButton(
                                    _tr("flet_preview"),
                                    icon=ft.Icons.PREVIEW,
                                    bgcolor=MOCHA["surface1"],
                                    color=MOCHA["text"],
                                    on_click=self._preview_organize,
                                ),
                                ft.ElevatedButton(
                                    _tr("flet_organize"),
                                    icon=ft.Icons.AUTO_FIX_HIGH,
                                    bgcolor=MOCHA["green"],
                                    color=MOCHA["crust"],
                                    on_click=self._execute_organize,
                                ),
                                ft.ElevatedButton(
                                    _tr("flet_undo_last"),
                                    icon=ft.Icons.UNDO,
                                    bgcolor=MOCHA["peach"],
                                    color=MOCHA["crust"],
                                    on_click=self._undo_organize,
                                ),
                            ],
                            spacing=8,
                        ),
                    ],
                    spacing=10,
                ),
                bgcolor=MOCHA["surface0"],
                border_radius=12,
                padding=ft.padding.all(16),
                border=ft.border.all(1, MOCHA["surface1"]),
            ),

            ft.Container(height=20),

            ft.Text(_tr("flet_collections"), size=16, weight=ft.FontWeight.W_600, color=MOCHA["text"]),
            ft.Text(_tr("flet_collections_help"), size=12, color=MOCHA["subtext0"]),
            ft.Container(height=6),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                self.save_name_field,
                                ft.ElevatedButton(
                                    _tr("flet_save"),
                                    icon=ft.Icons.SAVE,
                                    bgcolor=MOCHA["blue"],
                                    color=MOCHA["crust"],
                                    on_click=self._save_collection,
                                ),
                                ft.ElevatedButton(
                                    _tr("flet_load"),
                                    icon=ft.Icons.FOLDER_OPEN,
                                    bgcolor=MOCHA["surface1"],
                                    color=MOCHA["text"],
                                    on_click=self._on_load_collection_click,
                                ),
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    ],
                    spacing=10,
                ),
                bgcolor=MOCHA["surface0"],
                border_radius=12,
                padding=ft.padding.all(16),
                border=ft.border.all(1, MOCHA["surface1"]),
            ),

            ft.Container(height=20),

            ft.Text(_tr("flet_activity_log"), size=16, weight=ft.FontWeight.W_600, color=MOCHA["text"]),
            ft.Container(height=6),
            ft.Container(
                content=self.log_view,
                bgcolor=MOCHA["crust"],
                border_radius=12,
                padding=ft.padding.all(4),
                border=ft.border.all(1, MOCHA["surface1"]),
            ),
        ])

    def _log(self, msg: str, color: str = MOCHA["text"]):
        self.log_view.controls.append(
            ft.Text(msg, size=11, color=color, selectable=True, font_family="Consolas,monospace")
        )
        try:
            self.log_view.update()
        except Exception:
            pass

    async def _on_browse_output_click(self, e):
        path = await self.output_picker.get_directory_path(dialog_title="Select output folder")
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

        def progress(current, total, filename):
            self._log(f"  [{current}/{total}] {filename}", MOCHA["subtext0"])

        try:
            actions = self.state.organizer.organize(
                self.state.identified, self._output_folder, strategy, action,
                progress_callback=progress,
            )
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
            name=name,
            created_at=now,
            updated_at=now,
            dat_infos=self.state.multi_matcher.get_dat_list(),
            dat_filepaths=[d.filepath for d in self.state.multi_matcher.get_dat_list()],
            identified=[sc.to_dict() for sc in self.state.identified],
            unidentified=[sc.to_dict() for sc in self.state.unidentified],
        )
        try:
            path = self.state.collection_manager.save(coll)
            self._log(f"Collection saved: {path}", MOCHA["green"])
            _show_snack(self._pg, f"Collection '{name}' saved!", MOCHA["green"])
        except Exception as ex:
            self._log(f"Save error: {ex}", MOCHA["red"])

    async def _on_load_collection_click(self, e):
        files = await self.collection_picker.pick_files(
            dialog_title="Open Collection",
            allowed_extensions=["json"],
        )
        if not files:
            return
        filepath = files[0].path
        try:
            coll = self.state.collection_manager.load(filepath)

            self.state.multi_matcher = MultiROMMatcher()
            for di in coll.dat_infos:
                try:
                    _, roms = DATParser.parse_with_info(di.filepath)
                    self.state.multi_matcher.add_dat(di, roms)
                except Exception:
                    pass

            self.state.identified = [ScannedFile.from_dict(d) for d in coll.identified]
            self.state.unidentified = [ScannedFile.from_dict(d) for d in coll.unidentified]

            self._log(f"Collection loaded: {coll.name}", MOCHA["green"])
            _show_snack(self._pg, f"Collection '{coll.name}' loaded!", MOCHA["green"])
        except Exception as ex:
            self._log(f"Load error: {ex}", MOCHA["red"])


# ─── Main Application ────────────────────────────────────────────────────────
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

    content_area = ft.Container(expand=True, bgcolor=MOCHA["base"])

    def navigate(index: int):
        nav_rail.selected_index = index
        nav_rail.update()
        switch_view(index)

    dashboard_view = DashboardView(state, page, navigate)
    library_view = LibraryView(state, page, navigate)
    import_scan_view = ImportScanView(state, page, on_scan_complete=lambda: switch_view(nav_rail.selected_index))
    tools_logs_view = ToolsLogsView(state, page)

    views = [dashboard_view, library_view, import_scan_view, tools_logs_view]

    def switch_view(index: int):
        view = views[index]
        view.build_content()
        content_area.content = view
        content_area.update()

    nav_rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=80,
        min_extended_width=200,
        bgcolor=MOCHA["mantle"],
        indicator_color=MOCHA["surface1"],
        leading=ft.Container(
            content=ft.Column(
                controls=[
                    ft.Icon(ft.Icons.SPORTS_ESPORTS, size=32, color=MOCHA["mauve"]),
                    ft.Text(_tr("flet_brand"), size=11, weight=ft.FontWeight.BOLD, color=MOCHA["mauve"]),
                    ft.Dropdown(
                        width=150,
                        value=_safe_get_language(),
                        options=[ft.dropdown.Option(LANG_EN, _tr("language_english")), ft.dropdown.Option(LANG_PT_BR, _tr("language_ptbr"))],
                        on_change=lambda e: (_set_language(e.control.value), page.clean(), main(page)),
                        text_size=11,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
            ),
            padding=ft.padding.only(top=16, bottom=8),
        ),
        destinations=[
            ft.NavigationRailDestination(
                icon=ft.Icons.DASHBOARD_OUTLINED,
                selected_icon=ft.Icons.DASHBOARD,
                label=_tr("flet_nav_dashboard"),
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.GRID_VIEW_OUTLINED,
                selected_icon=ft.Icons.GRID_VIEW,
                label=_tr("flet_nav_library"),
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.UPLOAD_FILE_OUTLINED,
                selected_icon=ft.Icons.UPLOAD_FILE,
                label=_tr("flet_nav_import"),
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.BUILD_OUTLINED,
                selected_icon=ft.Icons.BUILD,
                label=_tr("flet_nav_tools"),
            ),
        ],
        on_change=lambda e: switch_view(e.control.selected_index),
    )

    page.add(
        ft.Row(
            controls=[
                nav_rail,
                ft.VerticalDivider(width=1, color=MOCHA["surface1"]),
                content_area,
            ],
            expand=True,
            spacing=0,
        )
    )

    switch_view(0)


# ─── Entry Point ──────────────────────────────────────────────────────────────
GUI_FLET_AVAILABLE = True


def run_flet_gui():
    """Launch the Flet desktop GUI."""
    ft.run(main)
    return 0


if __name__ == "__main__":
    run_flet_gui()
