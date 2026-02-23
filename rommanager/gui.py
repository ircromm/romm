"""
Graphical user interface for R0MM (tkinter)
"""

from __future__ import annotations

import os
import re
import threading
import webbrowser
from datetime import datetime
from typing import List, Optional

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog, Menu
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False
    tk = None
    ttk = None
    Menu = None

from .models import ROMInfo, ScannedFile, DATInfo, Collection
from .parser import DATParser
from .scanner import FileScanner
from .matcher import MultiROMMatcher
from .organizer import Organizer
from .collection import CollectionManager
from .reporter import MissingROMReporter
from .utils import format_size
from .monitor import install_tk_exception_bridge, monitor_action, setup_runtime_monitor, start_monitored_thread
from . import i18n as _i18n
from .settings import load_settings, apply_runtime_settings
from .session_state import build_snapshot, save_snapshot, load_snapshot, restore_into_matcher, restore_scanned

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
from .blindmatch import build_blindmatch_rom
from .shared_config import (
    IDENTIFIED_COLUMNS, UNIDENTIFIED_COLUMNS, MISSING_COLUMNS,
    REGION_COLORS, DEFAULT_REGION_COLOR, STRATEGIES,
)




class _TkToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _e=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(tw, text=self.text, bg="#111827", fg="#e5e7eb", relief=tk.SOLID, borderwidth=1, padx=6, pady=3).pack()

    def _hide(self, _e=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class ROMManagerGUI:
    """Main GUI application"""

    def __init__(self):
        apply_runtime_settings(load_settings())
        if not GUI_AVAILABLE:
            raise RuntimeError("tkinter is not available")

        self.root = tk.Tk()
        install_tk_exception_bridge(self.root)
        monitor_action("tkinter gui opened")
        self.root.title(f"{_tr('title_main')} ver {__version__}")
        self.root.geometry("1300x850")
        self.root.minsize(1000, 650)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Data
        self.multi_matcher = MultiROMMatcher()
        self.scanned_files: List[ScannedFile] = []
        self.identified: List[ScannedFile] = []
        self.unidentified: List[ScannedFile] = []
        self.organizer = Organizer()
        self.collection_manager = CollectionManager()
        self.reporter = MissingROMReporter()

        # Search
        self._search_after_id = None

        # Sort state for each tree
        self.sort_state = {
            'id': {'column': None, 'reverse': False},
            'un': {'column': None, 'reverse': False},
            'ms': {'column': None, 'reverse': False},
        }

        self._tooltips = []

        # Setup
        self._setup_theme()
        self._build_menu()
        self._build_ui()
        self._apply_auto_tooltips()
        self._restore_session()
        self._refresh_dats()
        self._refill_id()
        self._refill_un()
        self._refresh_missing()
        self._update_stats()

    # ── Theme ─────────────────────────────────────────────────────

    def _setup_theme(self):
        style = ttk.Style()
        if 'clam' in style.theme_names():
            style.theme_use('clam')
        self.colors = {
            'bg': '#1e1e2e', 'fg': '#cdd6f4', 'accent': '#89b4fa',
            'success': '#a6e3a1', 'warning': '#f9e2af', 'error': '#f38ba8',
            'surface': '#313244', 'surface_alt': '#45475a',
        }
        self.root.configure(bg=self.colors['bg'])
        style.configure('TFrame', background=self.colors['bg'])
        style.configure('TLabel', background=self.colors['bg'], foreground=self.colors['fg'])
        style.configure('TLabelframe', background=self.colors['bg'], foreground=self.colors['fg'])
        style.configure('TLabelframe.Label', background=self.colors['bg'],
                        foreground=self.colors['accent'], font=('Inter', 10, 'bold'))
        style.configure('Header.TLabel', font=('Inter', 18, 'bold'), foreground=self.colors['accent'])
        style.configure('SectionTitle.TLabel', font=('Inter', 13, 'bold'), foreground=self.colors['accent'])
        style.configure('Subtle.TLabel', font=('Inter', 9), foreground=self.colors['fg'])
        style.configure('Stats.TLabel', font=('Inter', 11))
        style.configure('Treeview', background=self.colors['surface'], foreground=self.colors['fg'],
                        fieldbackground=self.colors['surface'], font=('Inter', 9))
        style.configure('Treeview.Heading', background=self.colors['bg'],
                        foreground=self.colors['accent'], font=('Inter', 10, 'bold'), borderwidth=0, relief='flat')
        style.map('Treeview', background=[('selected', self.colors['accent'])])
        style.configure('Primary.TButton', font=('Inter', 10, 'bold'), borderwidth=0, relief='flat')
        style.configure('TButton', borderwidth=0, relief='flat', padding=(10, 6))
        style.configure('TRadiobutton', background=self.colors['bg'], foreground=self.colors['fg'])

    # ── Menu ──────────────────────────────────────────────────────

    def _build_menu(self):
        menubar = tk.Menu(self.root, bg=self.colors['surface'], fg=self.colors['fg'])

        file_menu = tk.Menu(menubar, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        file_menu.add_command(label=_tr("menu_save_collection"), command=self._save_collection)
        file_menu.add_command(label=_tr("menu_open_collection"), command=self._open_collection)
        file_menu.add_separator()
        self._recent_menu = tk.Menu(file_menu, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        file_menu.add_cascade(label=_tr("menu_recent_collections"), menu=self._recent_menu)
        self._refresh_recent_menu()
        file_menu.add_separator()
        file_menu.add_command(label=_tr("menu_exit"), command=self.root.quit)
        menubar.add_cascade(label=_tr("menu_file"), menu=file_menu)

        dat_menu = tk.Menu(menubar, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        dat_menu.add_command(label=_tr("menu_dat_library"), command=self._show_dat_library)
        menubar.add_cascade(label=_tr("menu_dats"), menu=dat_menu)

        export_menu = tk.Menu(menubar, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        export_menu.add_command(label=_tr("menu_export_missing_txt"), command=lambda: self._export_missing('txt'))
        export_menu.add_command(label=_tr("menu_export_missing_csv"), command=lambda: self._export_missing('csv'))
        export_menu.add_command(label=_tr("menu_export_missing_json"), command=lambda: self._export_missing('json'))
        menubar.add_cascade(label=_tr("menu_export"), menu=export_menu)

        help_menu = tk.Menu(menubar, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        help_menu.add_command(label=_tr("menu_settings"), command=self._show_settings)
        help_menu.add_command(label=_tr("menu_about"), command=self._show_about)
        menubar.add_cascade(label=_tr("menu_help"), menu=help_menu)

        lang_var = tk.StringVar(value=_safe_get_language())
        lang_menu = tk.Menu(menubar, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        lang_menu.add_radiobutton(label=_tr("language_english"), variable=lang_var, value=LANG_EN,
                                  command=lambda: self._change_language(LANG_EN))
        lang_menu.add_radiobutton(label=_tr("language_ptbr"), variable=lang_var, value=LANG_PT_BR,
                                  command=lambda: self._change_language(LANG_PT_BR))
        menubar.add_cascade(label=_tr("menu_language"), menu=lang_menu)

        self.root.config(menu=menubar)

    # ── UI Build ──────────────────────────────────────────────────

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(main)
        header.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(header, text=_tr("title_main"), style='Header.TLabel').pack(side=tk.LEFT, anchor=tk.W)
        ttk.Button(header, text="Nova sessão", command=self._new_session).pack(side=tk.RIGHT)

        body = ttk.Frame(main)
        body.pack(fill=tk.BOTH, expand=True)

        sidebar = ttk.Frame(body, padding=(0, 0, 12, 0))
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Label(sidebar, text="Navegação", style='SectionTitle.TLabel').pack(anchor=tk.W, pady=(0, 12))
        self.current_view_var = tk.StringVar(value="dashboard")
        for label, view_key in [
            ("Dashboard/Estatísticas", "dashboard"),
            ("Scanner & DATs", "scanner"),
            ("Organizador e Resultados", "results"),
        ]:
            ttk.Radiobutton(
                sidebar,
                text=label,
                value=view_key,
                variable=self.current_view_var,
                command=self._switch_view,
            ).pack(fill=tk.X, anchor=tk.W, pady=(0, 6))

        self.view_container = ttk.Frame(body)
        self.view_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.dashboard_view = ttk.Frame(self.view_container)
        self.scan_view = ttk.Frame(self.view_container)
        self.results_view = ttk.Frame(self.view_container)

        self._build_dashboard_view()
        self._build_scanner_view()
        self._build_results_view()
        self._switch_view()

    def _build_dashboard_view(self):
        self.stats_var = tk.StringVar(value=_tr("stats_no_files"))
        ttk.Label(self.dashboard_view, text="Dashboard", style='SectionTitle.TLabel').pack(anchor=tk.W, pady=(0, 8))
        ttk.Label(self.dashboard_view, textvariable=self.stats_var, style='Stats.TLabel').pack(anchor=tk.W, pady=(0, 12))
        ttk.Label(
            self.dashboard_view,
            text="Use a barra lateral para configurar DATs, fazer scan e organizar resultados.",
            style='Subtle.TLabel',
        ).pack(anchor=tk.W)

    def _build_scanner_view(self):
        ttk.Label(self.scan_view, text=_tr("panel_dat_files"), style='SectionTitle.TLabel').pack(anchor=tk.W, pady=(0, 6))
        dat_frame = ttk.Frame(self.scan_view, padding=(0, 0, 0, 12))
        dat_frame.pack(fill=tk.BOTH, expand=True)
        dat_btn = ttk.Frame(dat_frame)
        dat_btn.pack(fill=tk.X)
        ttk.Button(dat_btn, text=_tr("btn_add_dat"), command=self._add_dat).pack(side=tk.LEFT)
        ttk.Button(dat_btn, text=_tr("btn_remove"), command=self._remove_dat).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(dat_btn, text=_tr("btn_library"), command=self._show_dat_library).pack(side=tk.LEFT, padx=(8, 0))

        dat_list_frame = ttk.Frame(dat_frame)
        dat_list_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        dat_sb = ttk.Scrollbar(dat_list_frame, orient=tk.VERTICAL)
        self.dat_listbox = tk.Listbox(dat_list_frame, height=5, bg=self.colors['surface'],
                                      fg=self.colors['fg'], selectbackground=self.colors['accent'],
                                      font=('Inter', 9), yscrollcommand=dat_sb.set)
        dat_sb.config(command=self.dat_listbox.yview)
        dat_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.dat_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.dat_info_var = tk.StringVar(value=_tr("no_dats_loaded"))
        ttk.Label(dat_frame, textvariable=self.dat_info_var, style='Subtle.TLabel').pack(anchor=tk.W, pady=(6, 0))

        ttk.Label(self.scan_view, text=_tr("panel_scan"), style='SectionTitle.TLabel').pack(anchor=tk.W, pady=(6, 6))
        scan_frame = ttk.Frame(self.scan_view)
        scan_frame.pack(fill=tk.X)
        scan_row = ttk.Frame(scan_frame)
        scan_row.pack(fill=tk.X)
        self.scan_path_var = tk.StringVar(value=_tr("no_folder_selected"))
        ttk.Label(scan_row, textvariable=self.scan_path_var, width=45).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(scan_row, text=_tr("btn_select_folder"), command=self._select_folder).pack(side=tk.LEFT)
        ttk.Button(scan_row, text=_tr("btn_scan"), command=self._start_scan).pack(side=tk.LEFT, padx=(8, 0))

        self.advanced_scan_visible = tk.BooleanVar(value=False)
        ttk.Button(scan_frame, text="Opções Avançadas", command=self._toggle_advanced_scan_options).pack(anchor=tk.W, pady=(8, 0))
        self.advanced_scan_frame = ttk.Frame(scan_frame)

        self.scan_archives_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.advanced_scan_frame, text=_tr("scan_inside_zips"), variable=self.scan_archives_var).pack(side=tk.LEFT)
        self.recursive_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.advanced_scan_frame, text=_tr("recursive"), variable=self.recursive_var).pack(side=tk.LEFT, padx=(16, 0))
        self.blindmatch_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.advanced_scan_frame, text="BlindMatch", variable=self.blindmatch_var).pack(side=tk.LEFT, padx=(16, 0))
        self.blindmatch_system_var = tk.StringVar(value="")
        ttk.Entry(self.advanced_scan_frame, textvariable=self.blindmatch_system_var, width=20).pack(side=tk.LEFT, padx=(8, 0))

        self.progress_var = tk.StringVar(value="")
        ttk.Label(scan_frame, textvariable=self.progress_var, style='Subtle.TLabel').pack(anchor=tk.W, pady=(8, 0))
        self.progress_bar = ttk.Progressbar(scan_frame, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=(4, 0))

    def _build_results_view(self):
        # Search
        sf = ttk.Frame(self.results_view)
        sf.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(sf, text=_tr("search")).pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add('write', self._on_search)
        ttk.Entry(sf, textvariable=self._search_var, width=40).pack(side=tk.LEFT, padx=(8, 0), fill=tk.X, expand=True)

        # Tabs
        self.notebook = ttk.Notebook(self.results_view)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        # Identified
        id_f = ttk.Frame(self.notebook)
        self.notebook.add(id_f, text=_tr("tab_identified"))
        self.id_tree = self._make_tree(id_f, IDENTIFIED_COLUMNS)
        self._setup_region_tags(self.id_tree)

        # Unidentified
        un_f = ttk.Frame(self.notebook)
        self.notebook.add(un_f, text=_tr("tab_unidentified_files"))
        un_tb = ttk.Frame(un_f)
        un_tb.pack(fill=tk.X, pady=(0, 3))
        ttk.Button(un_tb, text=_tr("force_to_identified"), command=self._force_identified).pack(side=tk.LEFT)
        self.un_tree = self._make_tree(un_f, UNIDENTIFIED_COLUMNS)

        # Missing
        ms_f = ttk.Frame(self.notebook)
        self.notebook.add(ms_f, text=_tr("tab_missing_roms"))

        # Toolbar (ABOVE table)
        ms_toolbar = ttk.Frame(ms_f)
        ms_toolbar.pack(fill=tk.X, padx=0, pady=(0, 5))

        # Left side: View actions
        ms_left = ttk.Frame(ms_toolbar)
        ms_left.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(ms_left, text=_tr("refresh"), command=self._refresh_missing).pack(side=tk.LEFT)
        ttk.Button(ms_left, text=_tr("search_archive"), command=self._search_archive).pack(side=tk.LEFT, padx=(5, 0))

        # Right side: Download actions with dropdown
        ms_right = ttk.Frame(ms_toolbar)
        ms_right.pack(side=tk.RIGHT)

        # Selection count label
        self.ms_selection_var = tk.StringVar(value="")
        ttk.Label(ms_right, textvariable=self.ms_selection_var).pack(side=tk.LEFT, padx=(10, 0))

        # Completeness info (BELOW toolbar)
        ms_info = ttk.Frame(ms_f)
        ms_info.pack(fill=tk.X, padx=0, pady=(0, 3))
        self.completeness_var = tk.StringVar(value=_tr("completeness_hint"))
        ttk.Label(ms_info, textvariable=self.completeness_var, style='Stats.TLabel').pack(side=tk.LEFT)

        # The table itself
        self.ms_tree = self._make_tree(ms_f, MISSING_COLUMNS)
        self._setup_region_tags(self.ms_tree)

        # Bind selection change events to update selection count
        self.ms_tree.bind('<<Change>>', self._update_ms_selection_count)
        self.ms_tree.bind('<Button-1>', lambda e: self.root.after(10, self._update_ms_selection_count))
        self.ms_tree.bind('<Control-Button-1>', lambda e: self.root.after(10, self._update_ms_selection_count))

        # Stats
        # Organization
        ttk.Label(self.results_view, text=_tr("organization"), style='SectionTitle.TLabel').pack(anchor=tk.W, pady=(6, 6))
        org = ttk.Frame(self.results_view)
        org.pack(fill=tk.X)
        sr = ttk.Frame(org)
        sr.pack(fill=tk.X)
        ttk.Label(sr, text=_tr("strategy")).pack(side=tk.LEFT)
        self.strategy_var = tk.StringVar(value='1g1r')
        for s in STRATEGIES:
            ttk.Radiobutton(sr, text=s['name'], value=s['id'], variable=self.strategy_var).pack(side=tk.LEFT, padx=(8, 0))
        orw = ttk.Frame(org)
        orw.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(orw, text=_tr("output")).pack(side=tk.LEFT)
        self.output_var = tk.StringVar()
        ttk.Entry(orw, textvariable=self.output_var, width=45).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(orw, text=_tr("browse"), command=self._select_output).pack(side=tk.LEFT, padx=(5, 0))
        ttk.Label(orw, text=f"{_tr('action')}:" ).pack(side=tk.LEFT, padx=(15, 0))
        self.action_var = tk.StringVar(value='copy')
        ttk.Radiobutton(orw, text=_tr("copy_action"), value='copy', variable=self.action_var).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Radiobutton(orw, text=_tr("move_action"), value='move', variable=self.action_var).pack(side=tk.LEFT, padx=(5, 0))
        actions_left = ttk.Frame(orw)
        actions_left.pack(side=tk.LEFT)
        ttk.Button(actions_left, text=_tr("btn_undo"), command=self._undo).pack(side=tk.LEFT)

        actions_right = ttk.Frame(orw)
        actions_right.pack(side=tk.RIGHT)
        ttk.Button(actions_right, text=_tr("btn_preview"), command=self._preview).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(actions_right, text=_tr("organize_now"), style='Primary.TButton', command=self._organize).pack(side=tk.LEFT)

        # Keyboard shortcuts
        self.root.bind('<Control-a>', self._on_select_all)
        self.root.bind('<Control-c>', self._on_copy)
        self.root.bind('<F5>', self._on_refresh)
        self.root.bind('<Delete>', self._on_delete_key)
        self.root.bind('<Escape>', self._on_escape)

    def _switch_view(self):
        target = self.current_view_var.get()
        for key, view in {
            "dashboard": self.dashboard_view,
            "scanner": self.scan_view,
            "results": self.results_view,
        }.items():
            if key == target:
                view.pack(fill=tk.BOTH, expand=True)
            else:
                view.pack_forget()

    def _toggle_advanced_scan_options(self):
        current = self.advanced_scan_visible.get()
        self.advanced_scan_visible.set(not current)
        if self.advanced_scan_visible.get():
            self.advanced_scan_frame.pack(fill=tk.X, pady=(8, 0))
        else:
            self.advanced_scan_frame.pack_forget()

    # ── Helpers ───────────────────────────────────────────────────

    def _make_tree(self, parent, col_defs):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True)
        vsb = ttk.Scrollbar(frame, orient='vertical')
        hsb = ttk.Scrollbar(frame, orient='horizontal')
        cols = [c['id'] for c in col_defs]
        tree = ttk.Treeview(frame, columns=cols, show='headings', yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.config(command=tree.yview)
        hsb.config(command=tree.xview)

        # Store column definitions on tree for sorting
        tree.col_defs = col_defs

        for c in col_defs:
            tree.heading(c['id'], text=c['label'], anchor=tk.W)
            tree.column(c['id'], width=c['width'], minwidth=50)
            # Bind click on heading for sorting
            tree.heading(c['id'], command=lambda cid=c['id']: self._on_column_click(tree, cid))

        tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        # Bind right-click for context menu
        tree.bind('<Button-3>', lambda e: self._show_context_menu(e, tree))
        return tree

    def _apply_auto_tooltips(self, root_widget=None):
        w = root_widget or self.root
        for child in w.winfo_children():
            try:
                text = child.cget("text") if "text" in child.keys() else ""
            except Exception:
                text = ""
            if text and child.winfo_class() in {"TButton", "Button", "TCheckbutton", "TRadiobutton", "Label"}:
                tooltip_map = {
                    _tr("btn_add_dat"): _tr("tip_add_dat"),
                    _tr("btn_remove"): _tr("tip_remove_dat"),
                    _tr("btn_library"): _tr("tip_open_dat_library"),
                    _tr("btn_select_folder"): _tr("tip_select_rom_folder"),
                    _tr("btn_scan"): _tr("tip_start_scan"),
                    _tr("scan_inside_zips"): _tr("tip_scan_archives"),
                    _tr("recursive"): _tr("tip_recursive_scan"),
                    "BlindMatch": _tr("tip_blindmatch_toggle"),
                    _tr("force_to_identified"): _tr("tip_force_identified"),
                    _tr("refresh"): _tr("tip_refresh_missing"),
                    _tr("search_archive"): _tr("tip_search_archive"),
                    _tr("browse"): _tr("tip_select_output_folder"),
                    _tr("copy_action"): _tr("tip_action_copy"),
                    _tr("move_action"): _tr("tip_action_move"),
                    _tr("btn_preview"): _tr("tip_preview_organization"),
                    _tr("organize_now"): _tr("tip_organize_now"),
                    _tr("btn_undo"): _tr("tip_undo_last"),
                    _tr("menu_save_collection").replace("...", ""): _tr("tip_save_collection"),
                    _tr("menu_open_collection").replace("...", ""): _tr("tip_open_collection"),
                }
                strategy_names = {s.get("name") for s in STRATEGIES if s.get("name")}
                tip_text = tooltip_map.get(text)
                if tip_text is None and text in strategy_names:
                    tip_text = _tr("tip_choose_strategy")
                self._tooltips.append(_TkToolTip(child, tip_text or text))
            self._apply_auto_tooltips(child)

    def _setup_region_tags(self, tree):
        for region, colors in REGION_COLORS.items():
            tree.tag_configure(f'r_{region}', foreground=colors['fg'])
        tree.tag_configure('r_default', foreground=DEFAULT_REGION_COLOR['fg'])

    def _rtag(self, region):
        return f'r_{region}' if region in REGION_COLORS else 'r_default'

    # ── Context Menus ─────────────────────────────────────────────────

    def _show_context_menu(self, event, tree):
        """Show right-click context menu based on which tab we're in"""
        # Select the clicked item
        item = tree.identify('item', event.x, event.y)
        if not item:
            return

        tree.selection_set(item)

        # Determine which tab this tree belongs to
        if tree == self.id_tree:
            self._show_identified_context_menu(event, tree, item)
        elif tree == self.un_tree:
            self._show_unidentified_context_menu(event, tree, item)
        elif tree == self.ms_tree:
            self._show_missing_context_menu(event, tree, item)

    def _show_identified_context_menu(self, event, tree, item):
        """Context menu for Identified tab"""
        menu = tk.Menu(tree, tearoff=False, bg=self.colors['surface'], fg=self.colors['fg'])

        menu.add_command(label=_tr("copy_action"), command=lambda: self._copy_to_clipboard(tree, item, 'name'))
        menu.add_command(label=_tr("copy_crc32"), command=lambda: self._copy_to_clipboard(tree, item, 'crc'))
        menu.add_separator()
        menu.add_command(label=_tr("search_archive"), command=lambda: self._search_archive_for_item(tree, item))
        menu.add_separator()
        menu.add_command(label=_tr("open_folder"), command=lambda: self._open_rom_folder(tree, item))

        menu.post(event.x_root, event.y_root)

    def _show_unidentified_context_menu(self, event, tree, item):
        """Context menu for Unidentified tab"""
        menu = tk.Menu(tree, tearoff=False, bg=self.colors['surface'], fg=self.colors['fg'])

        menu.add_command(label=_tr("copy_action"), command=lambda: self._copy_to_clipboard(tree, item, 'name'))
        menu.add_command(label=_tr("copy_crc32"), command=lambda: self._copy_to_clipboard(tree, item, 'crc'))
        menu.add_separator()
        menu.add_command(label=_tr("force_to_identified"), command=lambda: self._force_identified_from_context(tree, item))
        menu.add_command(label=_tr("search_archive"), command=lambda: self._search_archive_for_item(tree, item))
        menu.add_separator()
        menu.add_command(label=_tr("open_folder"), command=lambda: self._open_rom_folder(tree, item))

        menu.post(event.x_root, event.y_root)

    def _show_missing_context_menu(self, event, tree, item):
        """Context menu for Missing tab"""
        menu = tk.Menu(tree, tearoff=False, bg=self.colors['surface'], fg=self.colors['fg'])

        menu.add_command(label=_tr("copy_action"), command=lambda: self._copy_to_clipboard(tree, item, 'name'))
        menu.add_command(label=_tr("copy_crc32"), command=lambda: self._copy_to_clipboard(tree, item, 'crc'))
        menu.add_separator()
        menu.add_separator()
        menu.add_command(label=_tr("search_archive"), command=lambda: self._search_archive_for_item(tree, item))
        menu.add_command(label=_tr("copy_to_clipboard"), command=lambda: self._copy_to_clipboard(tree, item, 'name'))

        menu.post(event.x_root, event.y_root)

    def _copy_to_clipboard(self, tree, item, copy_type='name'):
        """Copy item data to clipboard"""
        values = tree.item(item)['values']
        if not values:
            return

        if copy_type == 'crc' and len(values) > 0:
            # CRC is typically the last column or second-to-last
            # For Identified: Original File, ROM Name, Game, System, Region, Size, CRC32, Status
            # For Unidentified: Filename, Path, Size, CRC32
            # For Missing: ROM Name, Game, System, Region, Size (no CRC for missing)
            crc_value = values[-2] if len(values) > 1 else values[-1]
            if tree == self.id_tree or tree == self.un_tree:
                # Find the CRC column (typically second-to-last)
                try:
                    self.root.clipboard_clear()
                    self.root.clipboard_append(crc_value)
                    messagebox.showinfo(_tr("copied"), _tr("copied_crc", value=crc_value))
                except:
                    pass
        elif copy_type == 'name':
            # Copy the name/filename (first or second column usually)
            name_value = values[1] if len(values) > 1 else values[0]
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(name_value)
                messagebox.showinfo(_tr("copied"), _tr("copied_name", value=name_value))
            except:
                pass

    def _search_archive_for_item(self, tree, item):
        """Search Archive.org for the selected item"""
        values = tree.item(item)['values']
        if not values:
            return

        # Get CRC from the item
        crc_value = values[-2] if len(values) > 1 else values[-1]
        if crc_value and crc_value.strip():
            webbrowser.open(f"https://archive.org/advancedsearch.php?q=crc32:{crc_value}&output=json")

    def _open_rom_folder(self, tree, item):
        """Open folder containing the ROM"""
        if tree == self.id_tree:
            # For identified, get the original file path from first column
            values = tree.item(item)['values']
            if values:
                filename = values[0]
                # Find the full path in self.identified
                for sc in self.identified:
                    if sc.filename == filename:
                        folder_path = os.path.dirname(sc.path)
                        if os.path.exists(folder_path):
                            os.startfile(folder_path)
                        return
        elif tree == self.un_tree:
            # For unidentified, path is in the second column
            values = tree.item(item)['values']
            if len(values) > 1:
                folder_path = os.path.dirname(values[1])
                if os.path.exists(folder_path):
                    os.startfile(folder_path)
        elif tree == self.ms_tree:
            # Missing ROMs don't have paths, so skip
            messagebox.showinfo(_tr("info"), _tr("missing_no_local_paths"))

    def _force_identified_from_context(self, tree, item):
        """Force move an unidentified item to identified (from context menu)"""
        if tree != self.un_tree:
            return

        # This should call the existing _force_identified but with specific item
        # For now, just call the existing method which processes all selected
        self._force_identified()

    # ── Keyboard Shortcuts ─────────────────────────────────────────────

    def _on_select_all(self, event=None):
        """Ctrl+A: Select all items in current tab"""
        current_tab = self.notebook.index(self.notebook.select())
        if current_tab == 0:  # Identified tab
            tree = self.id_tree
        elif current_tab == 1:  # Unidentified tab
            tree = self.un_tree
        else:  # Missing tab
            tree = self.ms_tree

        items = tree.get_children()
        tree.selection_set(*items)
        return 'break'  # Prevent default behavior

    def _on_copy(self, event=None):
        """Ctrl+C: Copy selected item(s)"""
        current_tab = self.notebook.index(self.notebook.select())

        if current_tab == 0:  # Identified
            tree = self.id_tree
        elif current_tab == 1:  # Unidentified
            tree = self.un_tree
        else:  # Missing
            tree = self.ms_tree

        selection = tree.selection()
        if not selection:
            return 'break'

        # Ask user what to copy
        response = messagebox.askyesno(_tr("copy"), _tr("copy_crc_question"))
        copy_type = 'crc' if response else 'name'

        # Copy first selected item
        if selection:
            self._copy_to_clipboard(tree, selection[0], copy_type)

        return 'break'


    def _on_refresh(self, event=None):
        """F5: Refresh Missing tab"""
        current_tab = self.notebook.index(self.notebook.select())
        if current_tab == 2:  # Missing tab
            self._refresh_missing()
        return 'break'

    def _on_delete_key(self, event=None):
        """Delete: Move selected from Unidentified to Missing"""
        current_tab = self.notebook.index(self.notebook.select())
        if current_tab != 1:  # Not Unidentified tab
            return 'break'

        selection = self.un_tree.selection()
        if not selection:
            return 'break'

        if messagebox.askyesno(_tr("unidentified_to_missing"),
                                _tr("move_to_missing_confirm", count=len(selection))):
            self._force_identified()

        return 'break'

    def _on_escape(self, event=None):
        """Esc: Deselect all or close dialog"""
        current_tab = self.notebook.index(self.notebook.select())
        if current_tab == 0:
            tree = self.id_tree
        elif current_tab == 1:
            tree = self.un_tree
        else:
            tree = self.ms_tree

        tree.selection_set()  # Clear selection
        return 'break'

    def _update_ms_selection_count(self, event=None):
        """Update the selection count label in Missing tab toolbar"""
        selection = self.ms_tree.selection()
        if selection:
            count = len(selection)
            self.ms_selection_var.set(f"({count} selected)")
        else:
            self.ms_selection_var.set("")

    # ── Column Sorting ─────────────────────────────────────────────

    def _on_column_click(self, tree, col_id):
        """Handle column header click for sorting"""
        # Determine which tree this is
        if tree == self.id_tree:
            tree_key = 'id'
            col_defs = IDENTIFIED_COLUMNS
        elif tree == self.un_tree:
            tree_key = 'un'
            col_defs = UNIDENTIFIED_COLUMNS
        else:  # ms_tree
            tree_key = 'ms'
            col_defs = MISSING_COLUMNS

        # Toggle sort direction
        if self.sort_state[tree_key]['column'] == col_id:
            # Same column clicked: toggle reverse
            self.sort_state[tree_key]['reverse'] = not self.sort_state[tree_key]['reverse']
        else:
            # New column clicked: set as sort column, ascending
            self.sort_state[tree_key]['column'] = col_id
            self.sort_state[tree_key]['reverse'] = False

        # Apply sorting and refresh display
        self._sort_and_refill(tree, tree_key, col_defs)

    def _sort_and_refill(self, tree, tree_key, col_defs):
        """Sort data and refill tree with visual indicators"""
        col_id = self.sort_state[tree_key]['column']
        reverse = self.sort_state[tree_key]['reverse']

        if not col_id:
            return

        # Find column index
        col_index = None
        for i, c in enumerate(col_defs):
            if c['id'] == col_id:
                col_index = i
                break

        if col_index is None:
            return

        # Get current data from tree
        items = []
        for item in tree.get_children():
            values = tree.item(item)['values']
            tags = tree.item(item)['tags']
            items.append((values, tags, item))

        # Sort data
        try:
            items.sort(key=lambda x: x[0][col_index] if col_index < len(x[0]) else '', reverse=reverse)
        except TypeError:
            # If mixed types, try numeric sort first, fall back to string
            try:
                items.sort(key=lambda x: float(x[0][col_index]) if col_index < len(x[0]) else 0, reverse=reverse)
            except (ValueError, TypeError):
                items.sort(key=lambda x: str(x[0][col_index]) if col_index < len(x[0]) else '', reverse=reverse)

        # Update header display with sort indicator
        arrow = "▼" if reverse else "▲"
        for c in col_defs:
            if c['id'] == col_id:
                label = f"{c['label']} {arrow}"
            else:
                label = c['label']
            tree.heading(c['id'], text=label)

        # Refill tree with sorted data
        tree.delete(*tree.get_children())
        for values, tags, _ in items:
            tree.insert('', 'end', values=values, tags=tags)

    def _center_window(self, win, width, height):
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        win.geometry(f"{width}x{height}+{x}+{y}")

    # ── DATs ──────────────────────────────────────────────────────

    def _add_dat(self):
        fp = filedialog.askopenfilename(title=_tr("select_dat_file"),
            filetypes=[("DAT files", "*.dat *.xml *.zip"), ("Compressed", "*.zip *.gz"), ("All", "*.*")])
        if not fp:
            return
        try:
            di, roms = DATParser.parse_with_info(fp)
            self.multi_matcher.add_dat(di, roms)
            self._refresh_dats()
            self._persist_session()
            messagebox.showinfo("Loaded", f"{di.system_name}\n{di.rom_count:,} ROMs")
        except Exception as e:
            messagebox.showerror(_tr("error"), f"Failed:\n{e}")

    def _remove_dat(self):
        sel = self.dat_listbox.curselection()
        if not sel:
            return
        dats = self.multi_matcher.get_dat_list()
        if sel[0] < len(dats):
            self.multi_matcher.remove_dat(dats[sel[0]].id)
            self._refresh_dats()

    def _refresh_dats(self):
        self.dat_listbox.delete(0, tk.END)
        dats = self.multi_matcher.get_dat_list()
        for d in dats:
            self.dat_listbox.insert(tk.END, f"{d.system_name} ({d.rom_count:,})")
        total = sum(d.rom_count for d in dats)
        self.dat_info_var.set(f"{len(dats)} DAT(s), {total:,} ROMs" if dats else _tr("no_dats_loaded"))

    # ── Scan ──────────────────────────────────────────────────────

    def _select_folder(self):
        f = filedialog.askdirectory(title=_tr("select_rom_folder"))
        if f:
            self.scan_path_var.set(f)

    def _select_output(self):
        f = filedialog.askdirectory(title=_tr("select_output_folder"))
        if f:
            self.output_var.set(f)

    def _start_scan(self):
        folder = self.scan_path_var.get()
        if folder == _tr("no_folder_selected") or not os.path.isdir(folder):
            messagebox.showwarning(_tr("warning"), _tr("warning_select_valid_folder"))
            return
        if not self.blindmatch_var.get() and not self.multi_matcher.matchers:
            messagebox.showwarning(_tr("warning"), _tr("warning_load_dat_first"))
            return
        self.scanned_files.clear()
        self.identified.clear()
        self.unidentified.clear()
        for t in [self.id_tree, self.un_tree, self.ms_tree]:
            t.delete(*t.get_children())
        start_monitored_thread(lambda: self._scan_worker(folder), name="tk-scan-worker")

    def _scan_worker(self, folder):
        rec = self.recursive_var.get()
        arc = self.scan_archives_var.get()
        files = FileScanner.collect_files(folder, rec, arc)
        total = len(files)
        self.root.after(0, lambda: self.progress_var.set(f"Found {total:,} files..."))
        for i, fp in enumerate(files):
            try:
                ext = os.path.splitext(fp)[1].lower()
                if ext == '.zip' and arc:
                    for sc in FileScanner.scan_archive_contents(fp):
                        self._process(sc)
                else:
                    self._process(FileScanner.scan_file(fp))
            except Exception as exc:
                monitor_action(f"scan error: {exc}")
            pct = int((i + 1) / total * 100) if total else 0
            self.root.after(0, lambda p=pct, c=i+1, t=total: self._prog(p, c, t))
        self.root.after(0, self._scan_done)

    def _process(self, sc):
        if self.blindmatch_var.get():
            m = build_blindmatch_rom(sc, self.blindmatch_system_var.get())
        else:
            m = self.multi_matcher.match(sc)
        sc.matched_rom = m
        self.scanned_files.append(sc)
        if m:
            self.identified.append(sc)
            self.root.after(0, lambda s=sc: self._ins_id(s))
        else:
            self.unidentified.append(sc)
            self.root.after(0, lambda s=sc: self._ins_un(s))

    def _ins_id(self, sc):
        r = sc.matched_rom
        reg = r.region if r else 'Unknown'
        self.id_tree.insert('', 'end', values=(
            sc.filename, r.name if r else sc.filename, r.game_name if r else '',
            r.system_name if r else '', reg, format_size(r.size if r else sc.size),
            (r.crc32 if r else sc.crc32).upper(), r.status if r else 'unknown',
        ), tags=(self._rtag(reg),))

    def _ins_un(self, sc):
        self.un_tree.insert('', 'end', iid=sc.path, values=(
            sc.filename, sc.path, format_size(sc.size), sc.crc32.upper()))

    def _prog(self, pct, cur, tot):
        self.progress_bar['value'] = pct
        self.progress_var.set(f"Scanning: {cur:,}/{tot:,}")

    def _scan_done(self):
        self.progress_bar['value'] = 100
        self.progress_var.set("Scan complete!")
        self._update_stats()
        self._refresh_missing()
        self._persist_session()
        messagebox.showinfo(_tr("done"), f"Scanned {len(self.scanned_files):,}\n"
                            f"Identified: {len(self.identified):,}\nUnidentified: {len(self.unidentified):,}")

    def _update_stats(self):
        t = len(self.scanned_files)
        i = len(self.identified)
        u = len(self.unidentified)
        p = (i / t * 100) if t > 0 else 0
        self.stats_var.set(f"Total: {t:,} | Identified: {i:,} ({p:.1f}%) | Unidentified: {u:,}")
        self.notebook.tab(0, text=f"Identified ({i:,})")
        self.notebook.tab(1, text=f"Unidentified ({u:,})")

    # ── Search ────────────────────────────────────────────────────

    def _on_search(self, *_):
        if self._search_after_id:
            self.root.after_cancel(self._search_after_id)
        self._search_after_id = self.root.after(300, self._do_search)

    def _do_search(self):
        q = self._search_var.get().lower().strip()
        self._refill_id(q)
        self._refill_un(q)
        self._refill_ms(q)

    def _refill_id(self, q=''):
        self.id_tree.delete(*self.id_tree.get_children())
        for sc in self.identified:
            r = sc.matched_rom
            gn = r.game_name if r else ''
            nm = r.name if r else sc.filename
            if q and q not in gn.lower() and q not in nm.lower() and q not in sc.filename.lower():
                continue
            reg = r.region if r else 'Unknown'
            self.id_tree.insert('', 'end', values=(
                sc.filename, nm, gn, r.system_name if r else '', reg,
                format_size(r.size if r else sc.size),
                (r.crc32 if r else sc.crc32).upper(), r.status if r else 'unknown',
            ), tags=(self._rtag(reg),))

    def _refill_un(self, q=''):
        self.un_tree.delete(*self.un_tree.get_children())
        for sc in self.unidentified:
            if q and q not in sc.filename.lower() and q not in sc.path.lower():
                continue
            self.un_tree.insert('', 'end', iid=sc.path, values=(
                sc.filename, sc.path, format_size(sc.size), sc.crc32.upper()))

    def _refill_ms(self, q=''):
        self.ms_tree.delete(*self.ms_tree.get_children())
        if not self.multi_matcher.matchers:
            return
        for rom in self.multi_matcher.get_missing(self.identified):
            if q and q not in rom.name.lower() and q not in rom.game_name.lower():
                continue
            self.ms_tree.insert('', 'end', values=(
                rom.name, rom.game_name, rom.system_name, rom.region, format_size(rom.size),
            ), tags=(self._rtag(rom.region),))

    # ── Missing ───────────────────────────────────────────────────

    def _refresh_missing(self):
        if not self.multi_matcher.matchers:
            return
        self._refill_ms()
        c = self.multi_matcher.get_completeness(self.identified)
        missing = self.multi_matcher.get_missing(self.identified)
        self.completeness_var.set(
            f"Collection: {c['found']}/{c['total_in_dat']} ({c['percentage']:.1f}%) | "
            f"Missing: {c['missing']}")
        self.notebook.tab(2, text=f"Missing ({len(missing):,})")

    def _search_archive(self):
        sel = self.ms_tree.selection()
        if not sel:
            messagebox.showwarning(_tr("warning"), "Select missing ROMs first")
            return
        for item in sel[:5]:
            vals = self.ms_tree.item(item, 'values')
            if vals:
                clean = re.sub(r'\.[^.]+$', '', vals[0])
                clean = re.sub(r'\s*\([^)]*\)', '', clean).strip()
                webbrowser.open(f"https://archive.org/search?query={clean.replace(' ', '+')}")

    # ── Force Identify ────────────────────────────────────────────

    def _force_identified(self):
        sel = self.un_tree.selection()
        if not sel:
            messagebox.showwarning(_tr("warning"), "Select files to force")
            return

        # Show detailed confirmation
        msg = f"Force {len(sel)} unidentified file(s) to Identified?\n\n" \
              "These files will be added to the Identified list\n" \
              "using their filenames as ROM names."
        if not messagebox.askyesno(_tr("confirm"), msg):
            return

        for iid in sel:
            for sc in self.unidentified:
                if sc.path == iid:
                    sc.forced = True
                    sc.matched_rom = ROMInfo(name=sc.filename, size=sc.size, crc32=sc.crc32,
                                              game_name=os.path.splitext(sc.filename)[0], region='Unknown')
                    self.identified.append(sc)
                    self.unidentified.remove(sc)
                    self._ins_id(sc)
                    self.un_tree.delete(iid)
                    break
        self._update_stats()

    # ── Organization ──────────────────────────────────────────────

    def _preview(self):
        out = self.output_var.get()
        if not out:
            messagebox.showwarning(_tr("warning"), _tr("warning_select_output"))
            return
        if not self.identified:
            messagebox.showwarning(_tr("warning"), _tr("no_identified"))
            return
        try:
            plan = self.organizer.preview(self.identified, out, self.strategy_var.get(), self.action_var.get())
        except ValueError as e:
            messagebox.showerror(_tr("error"), str(e))
            return
        win = tk.Toplevel(self.root)
        win.title(_tr("organization_preview"))
        self._center_window(win, 700, 500)
        win.configure(bg=self.colors['bg'])
        ttk.Label(win, text=f"Strategy: {plan.strategy_description}").pack(anchor=tk.W, padx=10, pady=(10, 0))
        ttk.Label(win, text=_tr("files_size", files=f"{plan.total_files:,}", size=format_size(plan.total_size))).pack(anchor=tk.W, padx=10)
        txt = tk.Text(win, bg=self.colors['surface'], fg=self.colors['fg'], font=('Consolas', 9), wrap=tk.NONE)
        txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        for a in plan.actions:
            txt.insert(tk.END, f"[{a.action_type}] {os.path.basename(a.source)} -> {os.path.relpath(a.destination, out)}\n")
        txt.config(state=tk.DISABLED)

    def _organize(self):
        out = self.output_var.get()
        if not out:
            messagebox.showwarning(_tr("warning"), _tr("warning_select_output"))
            return
        if not self.identified:
            messagebox.showwarning(_tr("warning"), _tr("no_identified"))
            return
        s = self.strategy_var.get()
        a = self.action_var.get()
        total_size = sum(f.size for f in self.identified if f.matched_rom)
        msg = f"Organize {len(self.identified):,} ROMs?\n\n" \
              f"Strategy: {s}\n" \
              f"Action: {a}\n" \
              f"Total size: {format_size(total_size)}\n" \
              f"Output: {out}"
        if not messagebox.askyesno(_tr("confirm"), msg):
            return
        try:
            acts = self.organizer.organize(self.identified, out, s, a)
            messagebox.showinfo(_tr("done"), _tr("organized_count", count=f"{len(acts):,}"))
        except Exception as e:
            messagebox.showerror(_tr("error"), str(e))

    def _undo(self):
        if not self.organizer.get_history_count():
            messagebox.showinfo(_tr("info"), _tr("nothing_to_undo"))
            return
        if messagebox.askyesno(_tr("confirm"), _tr("undo_last_org")):
            if self.organizer.undo_last():
                messagebox.showinfo(_tr("done"), _tr("undo_complete"))

    # ── Collections ───────────────────────────────────────────────

    def _save_collection(self):
        name = simpledialog.askstring("Save Collection", "Collection name:", parent=self.root)
        if not name:
            return
        dats = self.multi_matcher.get_dat_list()
        coll = Collection(
            name=name, created_at=datetime.now().isoformat(),
            dat_infos=dats, dat_filepaths=[d.filepath for d in dats],
            scan_folder=self.scan_path_var.get(),
            scan_options={'recursive': self.recursive_var.get(), 'scan_archives': self.scan_archives_var.get()},
            identified=[f.to_dict() for f in self.identified],
            unidentified=[f.to_dict() for f in self.unidentified],
            settings={'strategy': self.strategy_var.get(), 'action': self.action_var.get(), 'output': self.output_var.get()},
        )
        fp = self.collection_manager.save(coll)
        self._refresh_recent_menu()
        self._persist_session()
        messagebox.showinfo("Saved", f"Collection saved:\n{fp}")

    def _open_collection(self):
        fp = filedialog.askopenfilename(title="Open Collection",
            filetypes=[("ROM Collections", "*.romcol.json"), ("All", "*.*")])
        if fp:
            self._load_coll(fp)

    def _load_coll(self, fp):
        try:
            coll = self.collection_manager.load(fp)
        except Exception as e:
            messagebox.showerror(_tr("error"), str(e))
            return
        self.multi_matcher = MultiROMMatcher()
        for di in coll.dat_infos:
            if os.path.exists(di.filepath):
                try:
                    info, roms = DATParser.parse_with_info(di.filepath)
                    self.multi_matcher.add_dat(info, roms)
                except Exception:
                    pass
        self._refresh_dats()
        self.identified = [ScannedFile.from_dict(d) for d in coll.identified]
        self.unidentified = [ScannedFile.from_dict(d) for d in coll.unidentified]
        self.scanned_files = self.identified + self.unidentified
        self._refill_id()
        self._refill_un()
        self._update_stats()
        self._refresh_missing()
        if coll.scan_folder:
            self.scan_path_var.set(coll.scan_folder)
        s = coll.settings
        if s.get('strategy'):
            self.strategy_var.set(s['strategy'])
        if s.get('action'):
            self.action_var.set(s['action'])
        if s.get('output'):
            self.output_var.set(s['output'])
        self._refresh_recent_menu()
        self._persist_session()
        messagebox.showinfo("Loaded", f"Collection '{coll.name}' loaded")

    def _refresh_recent_menu(self):
        self._recent_menu.delete(0, tk.END)
        recent = self.collection_manager.get_recent()
        if not recent:
            self._recent_menu.add_command(label=_tr("none"), state=tk.DISABLED)
            return
        for e in recent[:10]:
            n, p = e.get('name', '?'), e.get('filepath', '')
            self._recent_menu.add_command(label=n, command=lambda pp=p: self._load_coll(pp))

    # ── Export ────────────────────────────────────────────────────

    def _export_missing(self, fmt):
        if not self.multi_matcher.matchers:
            messagebox.showwarning(_tr("warning"), _tr("load_dats_scan_first"))
            return
        exts = {'txt': '.txt', 'csv': '.csv', 'json': '.json'}
        fp = filedialog.asksaveasfilename(title=_tr("export_missing_roms"),
            defaultextension=exts.get(fmt, '.txt'),
            filetypes=[(f"{fmt.upper()}", f"*{exts.get(fmt)}"), ("All", "*.*")])
        if not fp:
            return
        report = self.reporter.generate_multi_report(
            self.multi_matcher.dat_infos, self.multi_matcher.all_roms, self.identified)
        getattr(self.reporter, f'export_{fmt}')(report, fp)
        messagebox.showinfo("Exported", f"Saved to:\n{fp}")

    # ── Settings & About ───────────────────────────────────────────

    def _show_settings(self):
        """Show settings dialog (placeholder)"""
        messagebox.showinfo(_tr("settings_title"), _tr("settings_coming"))

    def _show_about(self):
        """Show about dialog"""
        messagebox.showinfo(_tr("about_title"), f"R0MM ver {__version__}\n\n"
                            "A web-based ROM collection organizer\n"
                            "with Windows Explorer-like interface.\n\n"
                            "© 2025")

    # ── DAT Library ───────────────────────────────────────────────

    def _show_dat_library(self):
        from .dat_library import DATLibrary
        from .dat_sources import DATSourceManager
        lib = DATLibrary()
        src = DATSourceManager()

        win = tk.Toplevel(self.root)
        win.title(_tr("dat_library"))
        self._center_window(win, 800, 600)
        win.configure(bg=self.colors['bg'])
        win.transient(self.root)
        win.grab_set()

        ttk.Label(win, text=_tr("dat_library"), font=('Segoe UI', 14, 'bold')).pack(anchor=tk.W, padx=10, pady=(10, 5))
        lf = ttk.Frame(win)
        lf.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))
        lt = self._make_tree(lf, [
            {'id': 'sys', 'label': 'System', 'width': 250},
            {'id': 'ver', 'label': 'Version', 'width': 100},
            {'id': 'roms', 'label': 'ROMs', 'width': 80},
            {'id': 'date', 'label': 'Imported', 'width': 150},
        ])

        def refresh():
            lt.delete(*lt.get_children())
            for d in lib.list_dats():
                lt.insert('', 'end', iid=d.id, values=(d.system_name, d.version, f"{d.rom_count:,}", d.loaded_at[:10]))

        refresh()

        br = ttk.Frame(win)
        br.pack(fill=tk.X, padx=10, pady=(0, 5))

        def imp():
            f = filedialog.askopenfilename(title="Import DAT",
                filetypes=[("DAT", "*.dat *.xml *.zip"), ("Compressed", "*.zip *.gz"), ("All", "*.*")])
            if f:
                try:
                    lib.import_dat(f)
                    refresh()
                except Exception as e:
                    messagebox.showerror(_tr("error"), str(e))

        def load_sel():
            s = lt.selection()
            if not s:
                return
            p = lib.get_dat_path(s[0])
            if p:
                try:
                    di, roms = DATParser.parse_with_info(p)
                    self.multi_matcher.add_dat(di, roms)
                    self._refresh_dats()
                    messagebox.showinfo("Loaded", di.system_name)
                except Exception as e:
                    messagebox.showerror(_tr("error"), str(e))

        def rem():
            s = lt.selection()
            if s and messagebox.askyesno(_tr("confirm"), "Remove from library?"):
                lib.remove_dat(s[0])
                refresh()

        ttk.Button(br, text=_tr("import_dat"), command=imp).pack(side=tk.LEFT)
        ttk.Button(br, text=_tr("load_selected"), command=load_sel).pack(side=tk.LEFT, padx=(5, 0))
        ttk.Button(br, text=_tr("btn_remove"), command=rem).pack(side=tk.LEFT, padx=(5, 0))

        ttk.Label(win, text=_tr("dat_sources"), font=('Segoe UI', 12, 'bold')).pack(anchor=tk.W, padx=10, pady=(10, 5))
        for s in src.get_sources():
            r = ttk.Frame(win)
            r.pack(fill=tk.X, padx=10, pady=2)
            ttk.Label(r, text=s['name'], width=30).pack(side=tk.LEFT)
            ttk.Label(r, text=f"({s['type']})", width=10).pack(side=tk.LEFT)
            ttk.Button(r, text=_tr("open_page"),
                       command=lambda sid=s['id']: src.open_source_page(sid)).pack(side=tk.LEFT, padx=(5, 0))

    # ── Direct download features removed ───────────────────────────

    def _change_language(self, lang):
        _set_language(lang)
        self.root.destroy()
        app = ROMManagerGUI()
        app.run()

    def _persist_session(self):
        snapshot = build_snapshot(
            dats=self.multi_matcher.get_dat_list(),
            identified=self.identified,
            unidentified=self.unidentified,
            extras={
                "blindmatch_mode": bool(self.blindmatch_var.get()),
                "blindmatch_system": self.blindmatch_system_var.get().strip(),
                "scan_path": self.scan_path_var.get(),
                "output_path": self.output_var.get(),
            },
        )
        save_snapshot(snapshot)

    def _restore_session(self):
        snap = load_snapshot()
        if not snap:
            return
        restore_into_matcher(self.multi_matcher, snap)
        self.identified, self.unidentified = restore_scanned(snap)
        extras = snap.get("extras", {})
        self.blindmatch_var.set(bool(extras.get("blindmatch_mode", False)))
        self.blindmatch_system_var.set(extras.get("blindmatch_system", ""))
        scan_path = extras.get("scan_path")
        if scan_path and scan_path != _tr("no_folder_selected"):
            self.scan_path_var.set(scan_path)
        self.output_var.set(extras.get("output_path", ""))

    def _on_close(self):
        self._persist_session()
        self.root.destroy()

    def _new_session(self):
        save_first = messagebox.askyesnocancel("Nova sessão", "Deseja salvar a sessão atual antes de reiniciar?")
        if save_first is None:
            return
        if save_first:
            self._save_collection()
        self.multi_matcher = MultiROMMatcher()
        self.identified = []
        self.unidentified = []
        self.scan_path_var.set(_tr("no_folder_selected"))
        self.output_var.set("")
        self.blindmatch_var.set(False)
        self.blindmatch_system_var.set("")
        self._refresh_dats()
        self._refill_id()
        self._refill_un()
        self._refresh_missing()
        self._update_stats()
        self.notebook.select(0)
        self._persist_session()

    # ── Run ───────────────────────────────────────────────────────

    def run(self):
        self.root.mainloop()


def run_gui():
    logger = setup_runtime_monitor()
    monitor_action("run_gui called", logger=logger)
    if not GUI_AVAILABLE:
        print("Error: tkinter is not available")
        return 1
    app = ROMManagerGUI()
    app.run()
    return 0
