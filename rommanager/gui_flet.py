"""Flet desktop GUI for RetroFlow (ROM Manager)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Dict, List, Optional

import flet as ft

from .matcher import MultiROMMatcher
from .models import DATInfo, ROMInfo, ScannedFile
from .parser import DATParser
from .scanner import FileScanner
from .utils import format_size


class RetroFlowFletApp:
    """Main Flet application shell implementing progressive disclosure UI."""

    NAV_DASHBOARD = 0
    NAV_LIBRARY = 1
    NAV_IMPORT = 2
    NAV_TOOLS = 3

    CATPPUCCIN = {
        "base": "#1E1E2E",
        "mantle": "#181825",
        "crust": "#11111B",
        "surface0": "#313244",
        "surface1": "#45475A",
        "text": "#CDD6F4",
        "subtext1": "#BAC2DE",
        "blue": "#89B4FA",
        "green": "#A6E3A1",
        "yellow": "#F9E2AF",
        "red": "#F38BA8",
        "mauve": "#CBA6F7",
    }

    REGION_COLORS = {
        "USA": "#89B4FA",
        "Europe": "#A6E3A1",
        "Japan": "#F9E2AF",
        "World": "#CBA6F7",
        "Unknown": "#6C7086",
    }

    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.multi_matcher = MultiROMMatcher()
        self.scanned_files: List[ScannedFile] = []
        self.identified: List[ScannedFile] = []
        self.unidentified: List[ScannedFile] = []
        self.selected_item: Optional[ScannedFile] = None

        self.nav_rail: Optional[ft.NavigationRail] = None
        self.main_content = ft.Container(expand=True)
        container_cls = getattr(ft, "AnimatedContainer", ft.Container)
        self.details_panel = container_cls(
            width=0,
            animate=ft.Animation(duration=250, curve=ft.AnimationCurve.EASE_IN_OUT),
            bgcolor=self.CATPPUCCIN["mantle"],
            padding=16,
            content=ft.Container(),
        )
        self.library_grid = ft.GridView(
            runs_count=5,
            max_extent=220,
            child_aspect_ratio=0.72,
            spacing=12,
            run_spacing=12,
            expand=True,
        )
        self.dat_picker = ft.FilePicker(on_result=self._on_dat_selected)
        self.folder_picker = ft.FilePicker(on_result=self._on_scan_folder_selected)

    def configure_page(self) -> None:
        """Configure theme and page shell."""
        self.page.title = "RetroFlow"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = self.CATPPUCCIN["base"]
        self.page.padding = 0
        self.page.window_width = 1440
        self.page.window_height = 920
        self.page.window_min_width = 1100
        self.page.window_min_height = 700
        self.page.overlay.extend([self.dat_picker, self.folder_picker])

    def build(self) -> None:
        """Build the root layout with left nav, body, and progressive details pane."""
        self.nav_rail = ft.NavigationRail(
            selected_index=self.NAV_DASHBOARD,
            extended=True,
            min_extended_width=240,
            bgcolor=self.CATPPUCCIN["crust"],
            indicator_color=self.CATPPUCCIN["surface0"],
            leading=ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Icon(ft.icons.GAMEPAD_ROUNDED, color=self.CATPPUCCIN["mauve"], size=32),
                        ft.Text("RetroFlow", size=20, weight=ft.FontWeight.W_700),
                        ft.Text("ROM Manager", size=11, color=self.CATPPUCCIN["subtext1"]),
                    ],
                    spacing=4,
                    horizontal_alignment=ft.CrossAxisAlignment.START,
                ),
                padding=ft.Padding(20, 20, 20, 20),
            ),
            destinations=[
                ft.NavigationRailDestination(icon=ft.icons.DASHBOARD_OUTLINED, selected_icon=ft.icons.DASHBOARD, label="Dashboard"),
                ft.NavigationRailDestination(icon=ft.icons.VIEW_MODULE_OUTLINED, selected_icon=ft.icons.VIEW_MODULE, label="Biblioteca"),
                ft.NavigationRailDestination(icon=ft.icons.PUBLISH_OUTLINED, selected_icon=ft.icons.PUBLISH, label="Importação & Scan"),
                ft.NavigationRailDestination(icon=ft.icons.TERMINAL_OUTLINED, selected_icon=ft.icons.TERMINAL, label="Ferramentas & Logs"),
            ],
            on_change=self._on_nav_change,
        )

        root = ft.Row(
            controls=[
                self.nav_rail,
                ft.VerticalDivider(width=1, color=self.CATPPUCCIN["surface0"]),
                ft.Expanded(self.main_content),
                self.details_panel,
            ],
            spacing=0,
            expand=True,
        )
        self.page.add(root)
        self._render_current_view(self.NAV_DASHBOARD)

    def _on_nav_change(self, event: ft.ControlEvent) -> None:
        self._render_current_view(event.control.selected_index)

    def _render_current_view(self, nav_index: int) -> None:
        if nav_index == self.NAV_DASHBOARD:
            self.main_content.content = self._build_dashboard_view()
            self._hide_details_panel()
        elif nav_index == self.NAV_LIBRARY:
            self.main_content.content = self._build_library_view()
        elif nav_index == self.NAV_IMPORT:
            self.main_content.content = self._build_import_view()
            self._hide_details_panel()
        else:
            self.main_content.content = self._build_tools_view()
            self._hide_details_panel()
        self.page.update()

    def _build_dashboard_view(self) -> ft.Control:
        return ft.Container(
            padding=24,
            content=ft.Column(
                controls=[
                    ft.Text("Dashboard", size=28, weight=ft.FontWeight.BOLD),
                    ft.Text("Resumo rápido da coleção e estado de identificação.", color=self.CATPPUCCIN["subtext1"]),
                    ft.ResponsiveRow(
                        controls=[
                            self._metric_card("ROMs identificadas", str(len(self.identified)), self.CATPPUCCIN["green"]),
                            self._metric_card("Não identificadas", str(len(self.unidentified)), self.CATPPUCCIN["yellow"]),
                            self._metric_card("DATs carregados", str(len(self.multi_matcher.get_dat_list())), self.CATPPUCCIN["blue"]),
                        ]
                    ),
                ],
                spacing=20,
            ),
        )

    def _build_library_view(self) -> ft.Control:
        self._refresh_library_grid()
        return ft.Container(
            padding=24,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text("Biblioteca", size=28, weight=ft.FontWeight.BOLD),
                            ft.Container(expand=True),
                            ft.Text(f"{len(self.identified)} itens", color=self.CATPPUCCIN["subtext1"]),
                        ]
                    ),
                    ft.Divider(color=self.CATPPUCCIN["surface0"]),
                    ft.Container(expand=True, content=self.library_grid),
                ],
                expand=True,
            ),
        )

    def _build_import_view(self) -> ft.Control:
        return ft.Container(
            padding=24,
            content=ft.Column(
                controls=[
                    ft.Text("Importação & Scan", size=28, weight=ft.FontWeight.BOLD),
                    ft.Text("Adiciona DATs e faz scan de diretórios sem bloquear a interface.", color=self.CATPPUCCIN["subtext1"]),
                    ft.Row(
                        controls=[
                            ft.ElevatedButton("Adicionar DAT", icon=ft.icons.NOTE_ADD, on_click=lambda _: self.dat_picker.pick_files(allow_multiple=True)),
                            ft.ElevatedButton("Selecionar Pasta para Scan", icon=ft.icons.FOLDER_OPEN, on_click=lambda _: self.folder_picker.get_directory_path()),
                        ]
                    ),
                    ft.Text(f"DATs carregados: {len(self.multi_matcher.get_dat_list())}", color=self.CATPPUCCIN["subtext1"]),
                ],
                spacing=16,
            ),
        )

    def _build_tools_view(self) -> ft.Control:
        return ft.Container(
            padding=24,
            content=ft.Column(
                controls=[
                    ft.Text("Ferramentas & Logs", size=28, weight=ft.FontWeight.BOLD),
                    ft.Text("Área reservada para monitor de logs e ações em lote.", color=self.CATPPUCCIN["subtext1"]),
                ]
            ),
        )

    def _metric_card(self, title: str, value: str, accent: str) -> ft.Control:
        return ft.Container(
            col={"xs": 12, "md": 4},
            bgcolor=self.CATPPUCCIN["mantle"],
            border_radius=16,
            padding=16,
            content=ft.Column(
                controls=[ft.Text(title, color=self.CATPPUCCIN["subtext1"]), ft.Text(value, size=36, weight=ft.FontWeight.BOLD, color=accent)],
                spacing=10,
            ),
        )

    def _refresh_library_grid(self) -> None:
        if not self.identified:
            self.library_grid.controls = [self._build_empty_state()]
            return

        controls: List[ft.Control] = []
        for item in self.identified:
            region = (item.matched_rom.region if item.matched_rom else "Unknown") or "Unknown"
            badge_color = self.REGION_COLORS.get(region, self.REGION_COLORS["Unknown"])
            title = item.matched_rom.game_name if item.matched_rom and item.matched_rom.game_name else item.filename
            controls.append(
                ft.GestureDetector(
                    on_tap=lambda _, scanned=item: self._show_details_panel(scanned),
                    content=ft.Container(
                        bgcolor=self.CATPPUCCIN["mantle"],
                        border_radius=16,
                        padding=10,
                        content=ft.Stack(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Container(
                                            height=180,
                                            border_radius=12,
                                            bgcolor=self.CATPPUCCIN["surface0"],
                                            alignment=ft.alignment.center,
                                            content=ft.Icon(ft.icons.SPORTS_ESPORTS, size=54, color=self.CATPPUCCIN["text"]),
                                        ),
                                        ft.Text(title, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                                    ],
                                    spacing=8,
                                ),
                                ft.Container(
                                    right=8,
                                    top=8,
                                    bgcolor=badge_color,
                                    border_radius=8,
                                    padding=ft.Padding(8, 3, 8, 3),
                                    content=ft.Text(region, size=10, color=self.CATPPUCCIN["crust"], weight=ft.FontWeight.W_700),
                                ),
                            ]
                        ),
                    ),
                )
            )
        self.library_grid.controls = controls

    def _build_empty_state(self) -> ft.Control:
        return ft.Container(
            alignment=ft.alignment.center,
            content=ft.Column(
                controls=[
                    ft.Icon(ft.icons.DATA_ARRAY, size=96, color=self.CATPPUCCIN["surface1"]),
                    ft.Text("A tua coleção está vazia", size=24, weight=ft.FontWeight.BOLD),
                    ft.Text("Começa por importar um DAT para desbloquear a biblioteca.", color=self.CATPPUCCIN["subtext1"]),
                    ft.ElevatedButton("Adicionar primeiro DAT", icon=ft.icons.ADD_CIRCLE_OUTLINE, on_click=lambda _: self._go_to_import()),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
            ),
            expand=True,
        )

    def _show_details_panel(self, scanned: ScannedFile) -> None:
        self.selected_item = scanned
        rom: Optional[ROMInfo] = scanned.matched_rom
        self.details_panel.content = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text("Detalhes da ROM", size=20, weight=ft.FontWeight.BOLD),
                        ft.Container(expand=True),
                        ft.IconButton(icon=ft.icons.CLOSE, on_click=lambda _: self._hide_details_panel()),
                    ]
                ),
                ft.Divider(color=self.CATPPUCCIN["surface0"]),
                ft.Text(f"Nome: {rom.game_name if rom and rom.game_name else scanned.filename}"),
                ft.Text(f"Região: {rom.region if rom and rom.region else 'Unknown'}"),
                ft.Text(f"CRC32: {scanned.crc32.upper()}"),
                ft.Text(f"Tamanho: {format_size(scanned.size)}"),
                ft.Text(f"Path: {scanned.path}", selectable=True),
                ft.Row(
                    controls=[
                        ft.OutlinedButton("Abrir Pasta", icon=ft.icons.FOLDER, on_click=lambda _: self._open_parent_folder(scanned.path)),
                        ft.FilledButton("Copiar CRC32", icon=ft.icons.CONTENT_COPY, on_click=lambda _: self._copy_crc(scanned.crc32)),
                    ]
                ),
            ],
            spacing=12,
        )
        self.details_panel.width = 360
        self.page.update()

    def _hide_details_panel(self) -> None:
        self.details_panel.width = 0
        self.details_panel.content = ft.Container()

    def _copy_crc(self, crc32: str) -> None:
        self.page.set_clipboard(crc32.upper())
        self.page.snack_bar = ft.SnackBar(ft.Text("CRC32 copiado para a área de transferência."), open=True)
        self.page.update()

    def _open_parent_folder(self, file_path: str) -> None:
        folder = Path(file_path.split("|")[0]).parent
        self.page.launch_url(folder.as_uri())

    def _go_to_import(self) -> None:
        if self.nav_rail is None:
            return
        self.nav_rail.selected_index = self.NAV_IMPORT
        self._render_current_view(self.NAV_IMPORT)

    def _on_dat_selected(self, event: ft.FilePickerResultEvent) -> None:
        if not event.files:
            return
        loaded = 0
        for f in event.files:
            try:
                dat_info, roms = DATParser.parse_with_info(f.path)
                self.multi_matcher.add_dat(dat_info, roms)
                loaded += 1
            except Exception as exc:
                self.page.snack_bar = ft.SnackBar(ft.Text(f"Erro a carregar DAT {f.name}: {exc}"), open=True)
                self.page.update()
        self.page.snack_bar = ft.SnackBar(ft.Text(f"{loaded} DAT(s) carregado(s)."), open=True)
        self._render_current_view(self.nav_rail.selected_index if self.nav_rail else self.NAV_IMPORT)

    def _on_scan_folder_selected(self, event: ft.FilePickerResultEvent) -> None:
        if not event.path:
            return
        self.page.run_task(self._run_scan_pipeline, event.path)

    async def _run_scan_pipeline(self, folder: str) -> None:
        files = await asyncio.to_thread(FileScanner.collect_files, folder, True, True)
        total = len(files)
        self.page.snack_bar = ft.SnackBar(ft.Text(f"Scan iniciado: 0/{total}"), duration=120000, open=True)
        self.page.update()

        scanned: List[ScannedFile] = []
        for index, filepath in enumerate(files, start=1):
            ext = os.path.splitext(filepath)[1].lower()
            if ext == ".zip":
                archive_items = await asyncio.to_thread(FileScanner.scan_archive_contents, filepath)
                scanned.extend(archive_items)
            else:
                scanned_file = await asyncio.to_thread(FileScanner.scan_file, filepath)
                scanned.append(scanned_file)

            if index % 5 == 0 or index == total:
                self.page.snack_bar = ft.SnackBar(ft.Text(f"Scan em progresso: {index}/{total}"), duration=120000, open=True)
                self.page.update()

        identified, unidentified = await asyncio.to_thread(self.multi_matcher.match_all, scanned)
        self.scanned_files = scanned
        self.identified = identified
        self.unidentified = unidentified

        self.page.snack_bar = ft.SnackBar(
            ft.Text(f"Scan concluído: {len(identified)} identificadas, {len(unidentified)} não identificadas."),
            open=True,
        )
        if self.nav_rail:
            self._render_current_view(self.nav_rail.selected_index)
        self.page.update()


def main(page: ft.Page) -> None:
    """Flet application entrypoint."""
    app = RetroFlowFletApp(page)
    app.configure_page()
    app.build()


def run_gui() -> int:
    """Run RetroFlow desktop app using Flet."""
    ft.app(target=main)
    return 0
