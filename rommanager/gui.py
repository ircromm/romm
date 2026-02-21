"""
Graphical user interface for ROM Manager (tkinter)
"""

from __future__ import annotations

import os
import shutil
import threading
import webbrowser
import logging
from pathlib import Path
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
from .shared_config import (
    IDENTIFIED_COLUMNS, UNIDENTIFIED_COLUMNS, MISSING_COLUMNS,
    REGION_COLORS, DEFAULT_REGION_COLOR, STRATEGIES,
    APP_DATA_DIR,
)

from .monitor import setup_monitoring, log_event


class TkMonitorHandler(logging.Handler):
    """Forward monitor logger entries to the GUI thread."""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        try:
            line = self.format(record)
            self.callback(line)
        except Exception:
            pass


class ROMManagerGUI:
    """Main GUI application"""

    SYSTEM_DOWNLOAD_LINKS = [
        ("Gamecube", "https://drive.google.com/drive/folders/1sa14fWIzzZgADgVr5mOysmXY939HWrX2?usp=share_link"),
        ("Nintendo 64", "https://drive.google.com/drive/folders/1zZbCA3vlpWjLJCvRgu-w0WgFXSckY33J?usp=sharing"),
        ("Super Nintendo", "https://drive.google.com/drive/folders/1A_aPM42CHjV0fPh7HmlS8mAWZA5pEt23?usp=sharing"),
        ("Wii-Ware", "https://drive.google.com/drive/folders/1o-g-f5BNp_v9YOIU9Os1D4IsTc1oMnbf?usp=share_link"),
        ("PSX", "https://drive.google.com/drive/folders/1pt_w6WrJMw3TBc02xInbquzY6IGvKIij?usp=share_link"),
        ("PS2", "https://drive.google.com/drive/folders/1D9WPT6TZVQgdzfUv-_h6bkfGf0kD9WUY?usp=drive_link"),
        ("VIC20", "https://drive.google.com/drive/folders/1ib_WRgXhFx_wvIIMXHuvB7qfsFDWfGnc?usp=share_link"),
        ("Atari Lynx", "https://drive.google.com/drive/folders/1DpOZ61Ksb9oqyEb1Vxiwx4scRFpEBgA5?usp=share_link"),
        ("Atari Jaguar", "https://drive.google.com/drive/folders/1zEl-KhZFlQOvXTPHMhXtpd7IHvyiuhUu?usp=share_link"),
        ("Wii U", "https://drive.google.com/drive/folders/1bDMQ7hehTkgoDwOewtgtjPP0URPfecza?usp=share_link"),
        ("3DS", "https://drive.google.com/drive/folders/1qY41Om305_LrI2-brD32DG2OGh4rHvt6?usp=share_link"),
        ("NES", "https://drive.google.com/drive/folders/1iX6GbROUnYURdFD_ILi_lGQBXOR2xVK-?usp=share_link"),
        ("Nintendo DS", "https://drive.google.com/drive/folders/1txkPl-x5qfPFQtLQ-7nH82x5rs7JOczv?usp=share_link"),
        ("Atari 2600", "https://drive.google.com/drive/folders/14idkQUxxkyI0Szs1P3dSG2rLP-NBC66M?usp=share_link"),
        ("Gameboy Color", "https://drive.google.com/drive/folders/12BSJRAlt_1fg_0acrkp7emDHu-4e6hMv?usp=share_link"),
        ("Gameboy Advance", "https://drive.google.com/drive/folders/1p4AKF3l6KdtNuYxb7oV62yAV3Eh1Tvk8?usp=share_link"),
        ("Vectrex", "https://drive.google.com/drive/folders/1IyhP7tGEU9Ni3SdmwAXmUfQXK_vyukxa?usp=sharing"),
        ("Commodore Amiga", "https://drive.google.com/drive/folders/1MpANlhxScSaKRbC4oF9qPgKu0gR0SFOx?usp=share_link"),
        ("TurboGrafx-16", "https://drive.google.com/drive/folders/1axNeenw-ZeGuD2kIck2HuDWwir1Cza_d?usp=share_link"),
        ("PSP", "https://drive.google.com/drive/folders/1ayM2GHST6bTPRYFVxXRtM3oG1nbLtaoE?usp=share_link"),
        ("Dreamcast", "https://drive.google.com/drive/folders/1hoBTZXbNaYUr5YNn6KN4WvnoDpCCs5ym?usp=share_link"),
    ]

    DAT_DOWNLOAD_LINKS = [
        ("No-Intro DAT-o-MATIC", "https://datomatic.no-intro.org/index.php?page=download&s=64&op=dat"),
        ("Redump DATs", "http://redump.org/downloads/"),
    ]

    SESSION_STATE_FILE = os.path.join(APP_DATA_DIR, "session_state.json")
    DOWNLOAD_LOG_FILE = os.path.join(APP_DATA_DIR, "download_history.log")

    def __init__(self):
        if not GUI_AVAILABLE:
            raise RuntimeError("tkinter is not available")

        self.root = tk.Tk()
        self.root.title("ROM Collection Manager v2")
        self.root.geometry("1440x920")
        self.root.minsize(1150, 720)

        # Data
        self.multi_matcher = MultiROMMatcher()
        self.scanned_files: List[ScannedFile] = []
        self.identified: List[ScannedFile] = []
        self.unidentified: List[ScannedFile] = []
        self.organizer = Organizer()
        self.collection_manager = CollectionManager()
        self.reporter = MissingROMReporter()
        self.monitor_lines: List[str] = []
        self.current_collection_path: Optional[str] = None
        self.is_dirty = False
        self.download_queue: List[str] = []
        self.download_queue_paused = False
        self.ignored_missing = set()

        setup_monitoring(echo=False)
        self.monitor_logger = logging.getLogger("rommanager.monitor")
        self.monitor_handler = TkMonitorHandler(lambda line: self.root.after(0, self._append_monitor_line, line))
        self.monitor_handler.setFormatter(logging.Formatter("%(asctime)s | %(event)s | %(message)s", "%H:%M:%S"))
        self.monitor_logger.addHandler(self.monitor_handler)

        # Search
        self._search_after_id = None

        # Sort state for each tree
        self.sort_state = {
            'id': {'column': None, 'reverse': False},
            'un': {'column': None, 'reverse': False},
            'ms': {'column': None, 'reverse': False},
        }

        # Setup
        self._setup_theme()
        self._build_menu()
        self._build_ui()
        self._bind_shortcuts()
        self.root.protocol("WM_DELETE_WINDOW", self._on_app_exit)
        self._prompt_recover_last_session()

    # ── Theme ─────────────────────────────────────────────────────

    def _setup_theme(self):
        style = ttk.Style()
        if 'clam' in style.theme_names():
            style.theme_use('clam')
        self.colors = {
            'bg': '#1e1e2e', 'fg': '#cdd6f4', 'accent': '#89b4fa',
            'success': '#a6e3a1', 'warning': '#f9e2af', 'error': '#f38ba8',
            'surface': '#313244',
        }
        self.root.configure(bg=self.colors['bg'])
        style.configure('TFrame', background=self.colors['bg'])
        style.configure('TLabel', background=self.colors['bg'], foreground=self.colors['fg'])
        style.configure('TLabelframe', background=self.colors['bg'], foreground=self.colors['fg'])
        style.configure('TLabelframe.Label', background=self.colors['bg'],
                        foreground=self.colors['accent'], font=('Segoe UI', 10, 'bold'))
        style.configure('Header.TLabel', font=('Segoe UI', 18, 'bold'), foreground=self.colors['accent'])
        style.configure('Stats.TLabel', font=('Segoe UI', 11))
        style.configure('Treeview', background=self.colors['surface'], foreground=self.colors['fg'],
                        fieldbackground=self.colors['surface'], font=('Segoe UI', 9))
        style.configure('Treeview.Heading', background=self.colors['bg'],
                        foreground=self.colors['accent'], font=('Segoe UI', 10, 'bold'))
        style.map('Treeview', background=[('selected', self.colors['accent'])])

    # ── Menu ──────────────────────────────────────────────────────

    def _build_menu(self):
        menubar = tk.Menu(self.root, bg=self.colors['surface'], fg=self.colors['fg'])

        self.file_menu = tk.Menu(menubar, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        self.file_menu.add_command(label="New Collection...", accelerator="Ctrl+N", command=self._new_collection)
        self.file_menu.add_command(label="Open Collection...", accelerator="Ctrl+O", command=self._open_collection)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self._save_collection_quick)
        self.file_menu.add_command(label="Save As...", command=self._save_collection)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Backup Snapshot...", command=self._backup_snapshot)
        self.file_menu.add_command(label="Restore Snapshot...", command=self._restore_snapshot)
        self.file_menu.add_separator()
        self._recent_menu = tk.Menu(self.file_menu, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        self.file_menu.add_cascade(label="Recent Collections", menu=self._recent_menu)
        self._refresh_recent_menu()
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self._on_app_exit)
        menubar.add_cascade(label="File", menu=self.file_menu)

        dat_menu = tk.Menu(menubar, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        dat_menu.add_command(label="DAT Library...", command=self._show_dat_library)
        menubar.add_cascade(label="DATs", menu=dat_menu)

        self.export_menu = tk.Menu(menubar, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        self.export_menu.add_command(label="Export Missing (TXT)...", accelerator="Ctrl+E", command=lambda: self._export_missing('txt'))
        self.export_menu.add_command(label="Export Missing (CSV)...", command=lambda: self._export_missing('csv'))
        self.export_menu.add_command(label="Export Missing (JSON)...", command=lambda: self._export_missing('json'))
        menubar.add_cascade(label="Export", menu=self.export_menu)

        self.tools_menu = tk.Menu(menubar, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        self.tools_menu.add_command(label="Deduplicate by CRC32", command=self._dedupe_crc)
        self.tools_menu.add_command(label="Find Name Collisions", command=self._find_name_collisions)
        self.tools_menu.add_command(label="Normalize Filenames", command=self._normalize_filenames)
        self.tools_menu.add_command(label="Mass Rename (DAT Convention)", command=self._mass_rename_dat_convention)
        self.tools_menu.add_command(label="Generate Integrity Audit", command=self._generate_integrity_audit)
        menubar.add_cascade(label="Tools", menu=self.tools_menu)

        dl_menu = tk.Menu(menubar, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        sources_menu = tk.Menu(dl_menu, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        sources_menu.add_command(label="Myrient", command=self._open_myrient_site)
        sources_menu.add_separator()
        for system_name, url in self.SYSTEM_DOWNLOAD_LINKS:
            sources_menu.add_command(label=system_name, command=lambda n=system_name, u=url: self._open_download_link(n, u))
        sources_menu.add_separator()
        for label, url in self.DAT_DOWNLOAD_LINKS:
            sources_menu.add_command(label=label, command=lambda n=label, u=url: self._open_download_link(n, u))
        dl_menu.add_cascade(label="Sources", menu=sources_menu)

        self.queue_menu = tk.Menu(dl_menu, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        self.queue_menu.add_command(label="Add Missing to Queue", accelerator="Ctrl+D", command=self._queue_missing_downloads)
        self.queue_menu.add_separator()
        self.queue_menu.add_command(label="Start Queue", command=self._start_download_queue)
        self.queue_menu.add_command(label="Pause Queue", command=self._pause_download_queue)
        self.queue_menu.add_command(label="Resume Queue", command=self._resume_download_queue)
        self.queue_menu.add_command(label="Cancel Queue", command=self._cancel_download_queue)
        self.queue_menu.add_separator()
        self.queue_menu.add_command(label="Retry Failed", command=self._retry_failed_downloads)
        dl_menu.add_cascade(label="Queue", menu=self.queue_menu)

        verification_menu = tk.Menu(dl_menu, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        verification_menu.add_command(label="Verify CRC After Download", command=self._verify_crc_after_download)
        verification_menu.add_command(label="Quarantine Invalid Files", command=self._quarantine_invalid_files)
        dl_menu.add_cascade(label="Verification", menu=verification_menu)

        history_menu = tk.Menu(dl_menu, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        history_menu.add_command(label="Open Download Log", command=self._open_download_log)
        history_menu.add_command(label="Export Download Report (CSV)", command=lambda: self._export_download_report('csv'))
        history_menu.add_command(label="Export Download Report (JSON)", command=lambda: self._export_download_report('json'))
        dl_menu.add_cascade(label="History", menu=history_menu)

        dl_menu.add_separator()
        dl_menu.add_command(label="Settings", command=self._show_settings)
        dl_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Downloads", menu=dl_menu)

        help_menu = tk.Menu(menubar, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        help_menu.add_command(label="Keyboard Shortcuts", command=self._show_keyboard_shortcuts)
        help_menu.add_command(label="Command Palette", accelerator="Ctrl+Shift+P", command=self._show_command_palette)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)
        self._refresh_menu_state()

    # ── UI Build ──────────────────────────────────────────────────

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # Header
        ttk.Label(main, text="ROM Collection Manager", style='Header.TLabel').pack(anchor=tk.W, pady=(0, 10))

        # Top: DATs + Scan
        top = ttk.Frame(main)
        top.pack(fill=tk.X, pady=(0, 8))

        # DAT Panel
        dat_frame = ttk.LabelFrame(top, text="DAT Files", padding=8)
        dat_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))
        dat_btn = ttk.Frame(dat_frame)
        dat_btn.pack(fill=tk.X)
        ttk.Button(dat_btn, text="Add DAT...", command=self._add_dat).pack(side=tk.LEFT)
        ttk.Button(dat_btn, text="Remove", command=self._remove_dat).pack(side=tk.LEFT, padx=(5, 0))
        ttk.Button(dat_btn, text="Library...", command=self._show_dat_library).pack(side=tk.LEFT, padx=(5, 0))
        
        # DAT List with Scrollbar (Fixed Structure)
        dat_list_frame = ttk.Frame(dat_frame)
        dat_list_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
        
        dat_sb = ttk.Scrollbar(dat_list_frame, orient=tk.VERTICAL)
        self.dat_listbox = tk.Listbox(dat_list_frame, height=3, bg=self.colors['surface'],
                                       fg=self.colors['fg'], selectbackground=self.colors['accent'],
                                       font=('Segoe UI', 9), yscrollcommand=dat_sb.set)
        dat_sb.config(command=self.dat_listbox.yview)
        
        dat_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.dat_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.dat_info_var = tk.StringVar(value="No DATs loaded")
        ttk.Label(dat_frame, textvariable=self.dat_info_var).pack(anchor=tk.W, pady=(3, 0))

        # Scan Panel
        scan_frame = ttk.LabelFrame(top, text="Scan ROMs", padding=8)
        scan_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0))
        scan_row = ttk.Frame(scan_frame)
        scan_row.pack(fill=tk.X)
        self.scan_path_var = tk.StringVar(value="No folder selected")
        ttk.Label(scan_row, textvariable=self.scan_path_var, width=40).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(scan_row, text="Browse...", command=self._select_folder).pack(side=tk.LEFT)
        ttk.Button(scan_row, text="Scan", command=self._start_scan).pack(side=tk.LEFT, padx=(5, 0))
        opts = ttk.Frame(scan_frame)
        opts.pack(fill=tk.X, pady=(5, 0))
        self.scan_archives_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Scan inside ZIPs", variable=self.scan_archives_var).pack(side=tk.LEFT)
        self.recursive_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Recursive", variable=self.recursive_var).pack(side=tk.LEFT, padx=(15, 0))
        self.progress_var = tk.StringVar(value="")
        ttk.Label(scan_frame, textvariable=self.progress_var).pack(anchor=tk.W)
        self.progress_bar = ttk.Progressbar(scan_frame, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=(3, 0))

        # Search
        sf = ttk.Frame(main)
        sf.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(sf, text="Search:").pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add('write', self._on_search)
        ttk.Entry(sf, textvariable=self._search_var, width=40).pack(side=tk.LEFT, padx=(8, 0), fill=tk.X, expand=True)

        # Tabs
        self.notebook = ttk.Notebook(main)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        # Identified
        id_f = ttk.Frame(self.notebook)
        self.notebook.add(id_f, text="Identified ROMs")
        self.id_tree = self._make_tree(id_f, IDENTIFIED_COLUMNS)
        self._setup_region_tags(self.id_tree)

        # Unidentified
        un_f = ttk.Frame(self.notebook)
        self.notebook.add(un_f, text="Unidentified Files")
        un_tb = ttk.Frame(un_f)
        un_tb.pack(fill=tk.X, pady=(0, 3))
        ttk.Button(un_tb, text="Force to Identified", command=self._force_identified).pack(side=tk.LEFT)
        self.un_tree = self._make_tree(un_f, UNIDENTIFIED_COLUMNS)

        # Missing
        ms_f = ttk.Frame(self.notebook)
        self.notebook.add(ms_f, text="Missing ROMs")

        # Completeness info (BELOW toolbar)
        ms_info = ttk.Frame(ms_f)
        ms_info.pack(fill=tk.X, padx=0, pady=(0, 6))
        self.completeness_var = tk.StringVar(value="Load DATs and scan to see missing ROMs")
        ttk.Label(ms_info, textvariable=self.completeness_var, style='Stats.TLabel').pack(side=tk.LEFT)

        # The table itself
        self.ms_tree = self._make_tree(ms_f, MISSING_COLUMNS)
        self._setup_region_tags(self.ms_tree)

        # Stats
        self.stats_var = tk.StringVar(value="No files scanned")
        ttk.Label(main, textvariable=self.stats_var, style='Stats.TLabel').pack(anchor=tk.W, pady=(0, 8))

        monitor_frame = ttk.LabelFrame(main, text="Real-time Monitor", padding=8)
        monitor_frame.pack(fill=tk.BOTH, expand=False, pady=(0, 8))
        self.monitor_text = tk.Text(
            monitor_frame,
            height=8,
            bg=self.colors['surface'],
            fg=self.colors['fg'],
            insertbackground=self.colors['fg'],
            font=('Consolas', 9),
            wrap='none',
        )
        mon_scroll = ttk.Scrollbar(monitor_frame, orient=tk.VERTICAL, command=self.monitor_text.yview)
        self.monitor_text.configure(yscrollcommand=mon_scroll.set)
        self.monitor_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        mon_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Organization
        org = ttk.LabelFrame(main, text="Organization", padding=8)
        org.pack(fill=tk.X)
        sr = ttk.Frame(org)
        sr.pack(fill=tk.X)
        ttk.Label(sr, text="Strategy:").pack(side=tk.LEFT)
        self.strategy_var = tk.StringVar(value='1g1r')
        for s in STRATEGIES:
            ttk.Radiobutton(sr, text=s['name'], value=s['id'], variable=self.strategy_var).pack(side=tk.LEFT, padx=(8, 0))
        orw = ttk.Frame(org)
        orw.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(orw, text="Output:").pack(side=tk.LEFT)
        self.output_var = tk.StringVar()
        ttk.Entry(orw, textvariable=self.output_var, width=45).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(orw, text="Browse...", command=self._select_output).pack(side=tk.LEFT, padx=(5, 0))
        ttk.Label(orw, text="Action:").pack(side=tk.LEFT, padx=(15, 0))
        self.action_var = tk.StringVar(value='copy')
        ttk.Radiobutton(orw, text="Copy", value='copy', variable=self.action_var).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Radiobutton(orw, text="Move", value='move', variable=self.action_var).pack(side=tk.LEFT, padx=(5, 0))
        ttk.Button(orw, text="Preview", command=self._preview).pack(side=tk.LEFT, padx=(15, 0))
        ttk.Button(orw, text="Organize!", command=self._organize).pack(side=tk.LEFT, padx=(5, 0))
        ttk.Button(orw, text="Undo", command=self._undo).pack(side=tk.LEFT, padx=(5, 0))

        self._emit_event('gui.started', 'Desktop interface initialized')

    def _bind_shortcuts(self):
        self.root.bind('<Control-a>', self._on_select_all)
        self.root.bind('<Control-c>', self._on_copy)
        self.root.bind('<Control-n>', lambda *_: self._new_collection())
        self.root.bind('<Control-o>', lambda *_: self._open_collection())
        self.root.bind('<Control-s>', lambda *_: self._save_collection_quick())
        self.root.bind('<Control-e>', lambda *_: self._export_missing('txt'))
        self.root.bind('<Control-d>', lambda *_: self._queue_missing_downloads())
        self.root.bind('<Control-Shift-P>', lambda *_: self._show_command_palette())
        self.root.bind('<F5>', lambda *_: self._refresh_current_tab())
        self.root.bind('<Delete>', self._on_delete_key)
        self.root.bind('<Escape>', self._on_escape)

    # ── Helpers ───────────────────────────────────────────────────

    def _append_monitor_line(self, line):
        self.monitor_lines.append(line)
        if len(self.monitor_lines) > 500:
            self.monitor_lines = self.monitor_lines[-500:]
        self.monitor_text.delete('1.0', tk.END)
        self.monitor_text.insert(tk.END, "\n".join(self.monitor_lines) + "\n")
        self.monitor_text.see(tk.END)

    def _emit_event(self, event, message):
        log_event(event, message)

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

    def _setup_region_tags(self, tree):
        for region, colors in REGION_COLORS.items():
            tree.tag_configure(f'r_{region}', foreground=colors['fg'])
        tree.tag_configure('r_default', foreground=DEFAULT_REGION_COLOR['fg'])

    def _rtag(self, region):
        return f'r_{region}' if region in REGION_COLORS else 'r_default'

    # ── Context Menus ─────────────────────────────────────────────────

    def _show_context_menu(self, event, tree):
        """Show right-click context menu based on which tab we're in"""
        item = tree.identify('item', event.x, event.y)
        if item and item not in tree.selection():
            tree.selection_set(item)

        if tree == self.id_tree:
            self._show_identified_context_menu(event, tree)
        elif tree == self.un_tree:
            self._show_unidentified_context_menu(event, tree)
        elif tree == self.ms_tree:
            self._show_missing_context_menu(event, tree)

    def _build_common_context_menu(self, tree, include_crc=True, include_path=False):
        menu = tk.Menu(tree, tearoff=False, bg=self.colors['surface'], fg=self.colors['fg'])
        menu.add_command(label="Copy Name", command=lambda: self._copy_selection(tree, 'name'))
        if include_crc:
            menu.add_command(label="Copy CRC32", command=lambda: self._copy_selection(tree, 'crc'))
            menu.add_command(label="Copy Selected CRC32s", command=lambda: self._copy_selection(tree, 'crc', multi=True))
        if include_path:
            menu.add_command(label="Copy Full Path", command=lambda: self._copy_selection(tree, 'path'))
        menu.add_separator()
        menu.add_command(label="Search Archive.org", command=lambda: self._search_archive_for_selection(tree))
        menu.add_command(label="Open Folder", command=lambda: self._open_rom_folder_for_selection(tree))
        return menu

    def _show_identified_context_menu(self, event, tree):
        menu = self._build_common_context_menu(tree, include_crc=True, include_path=True)
        menu.post(event.x_root, event.y_root)

    def _show_unidentified_context_menu(self, event, tree):
        menu = self._build_common_context_menu(tree, include_crc=True, include_path=True)
        menu.add_separator()
        menu.add_command(label="Force to Identified", command=self._force_identified)
        menu.post(event.x_root, event.y_root)

    def _show_missing_context_menu(self, event, tree):
        menu = self._build_common_context_menu(tree, include_crc=False, include_path=False)
        menu.add_separator()
        menu.add_command(label="Queue Download", command=self._queue_selected_missing_downloads)
        menu.add_command(label="Mark as Ignored", command=self._mark_missing_as_ignored)
        menu.post(event.x_root, event.y_root)

    def _copy_selection(self, tree, copy_type='name', multi=False):
        selection = tree.selection()
        if not selection:
            return
        if not multi:
            selection = selection[:1]
        rows = [tree.item(item)['values'] for item in selection]
        payload = []
        for values in rows:
            if not values:
                continue
            if copy_type == 'crc':
                if tree == self.id_tree:
                    payload.append(str(values[6]))
                elif tree == self.un_tree:
                    payload.append(str(values[3]))
            elif copy_type == 'path':
                if tree == self.un_tree and len(values) > 1:
                    payload.append(str(values[1]))
                elif tree == self.id_tree:
                    filename = str(values[0])
                    found = next((sc.path for sc in self.identified if sc.filename == filename), None)
                    if found:
                        payload.append(found)
            else:
                payload.append(str(values[1] if len(values) > 1 else values[0]))
        if not payload:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(payload))
        messagebox.showinfo("Copied", f"Copied {len(payload)} item(s) to clipboard")

    def _search_archive_for_selection(self, tree):
        selection = tree.selection()
        if not selection:
            return
        values = tree.item(selection[0])['values']
        if tree == self.id_tree and len(values) > 6:
            query = values[6]
        elif tree == self.un_tree and len(values) > 3:
            query = values[3]
        else:
            query = values[0] if values else ''
        if query:
            webbrowser.open(f"https://archive.org/advancedsearch.php?q={query}&output=json")

    def _open_rom_folder_for_selection(self, tree):
        selection = tree.selection()
        if not selection:
            return
        item = selection[0]
        if tree == self.ms_tree:
            messagebox.showinfo("Info", "Missing ROMs don't have local paths.")
            return
        values = tree.item(item)['values']
        folder_path = None
        if tree == self.un_tree and len(values) > 1:
            folder_path = os.path.dirname(values[1])
        elif tree == self.id_tree and values:
            filename = values[0]
            for sc in self.identified:
                if sc.filename == filename:
                    folder_path = os.path.dirname(sc.path)
                    break
        if folder_path and os.path.exists(folder_path):
            try:
                os.startfile(folder_path)
            except AttributeError:
                webbrowser.open(f"file://{folder_path}")

    def _force_identified_from_context(self, tree, item):
        if tree == self.un_tree:
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
        tree = self._get_current_tree()
        if not tree.selection():
            return 'break'
        self._copy_selection(tree, 'name', multi=True)
        return 'break'


    def _on_delete_key(self, event=None):
        """Delete: Move selected from Unidentified to Missing"""
        current_tab = self.notebook.index(self.notebook.select())
        if current_tab != 1:  # Not Unidentified tab
            return 'break'

        selection = self.un_tree.selection()
        if not selection:
            return 'break'

        if messagebox.askyesno("Move to Missing",
                                f"Move {len(selection)} unidentified item(s) to Missing ROMs?"):
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

    def _get_current_tree(self):
        current_tab = self.notebook.index(self.notebook.select())
        if current_tab == 0:
            return self.id_tree
        if current_tab == 1:
            return self.un_tree
        return self.ms_tree

    def _refresh_current_tab(self):
        self._do_search()
        self._refresh_menu_state()

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
        fp = filedialog.askopenfilename(title="Select DAT File",
            filetypes=[("DAT files", "*.dat *.xml *.zip"), ("Compressed", "*.zip *.gz"), ("All", "*.*")])
        if not fp:
            return
        self._emit_event('dat.add.requested', f'Selected DAT: {fp}')
        try:
            di, roms = DATParser.parse_with_info(fp)
            self.multi_matcher.add_dat(di, roms)
            self._emit_event('dat.add.completed', f'Loaded {di.system_name} ({di.rom_count} ROMs)')
            self._refresh_dats()
            messagebox.showinfo("Loaded", f"{di.system_name}\n{di.rom_count:,} ROMs")
        except Exception as e:
            messagebox.showerror("Error", f"Failed:\n{e}")

    def _remove_dat(self):
        sel = self.dat_listbox.curselection()
        if not sel:
            return
        dats = self.multi_matcher.get_dat_list()
        if sel[0] < len(dats):
            self._emit_event('dat.remove', f'Removed DAT {dats[sel[0]].system_name}')
            self.multi_matcher.remove_dat(dats[sel[0]].id)
            self._refresh_dats()
            self._mark_dirty()
            self._refresh_menu_state()

    def _refresh_dats(self):
        self.dat_listbox.delete(0, tk.END)
        dats = self.multi_matcher.get_dat_list()
        for d in dats:
            self.dat_listbox.insert(tk.END, f"{d.system_name} ({d.rom_count:,})")
        total = sum(d.rom_count for d in dats)
        self.dat_info_var.set(f"{len(dats)} DAT(s), {total:,} ROMs" if dats else "No DATs loaded")

    # ── Scan ──────────────────────────────────────────────────────

    def _select_folder(self):
        f = filedialog.askdirectory(title="Select ROM Folder")
        if f:
            self.scan_path_var.set(f)

    def _select_output(self):
        f = filedialog.askdirectory(title="Select Output Folder")
        if f:
            self.output_var.set(f)

    def _start_scan(self):
        folder = self.scan_path_var.get()
        if folder == "No folder selected" or not os.path.isdir(folder):
            messagebox.showwarning("Warning", "Select a valid folder")
            return
        if not self.multi_matcher.matchers:
            messagebox.showwarning("Warning", "Load at least one DAT first")
            return
        self.scanned_files.clear()
        self.identified.clear()
        self.unidentified.clear()
        for t in [self.id_tree, self.un_tree, self.ms_tree]:
            t.delete(*t.get_children())
        self._emit_event('scan.started', f'Started scan at {folder}')
        thread = threading.Thread(target=self._scan_worker, args=(folder,), daemon=True)
        thread.start()

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
            except Exception as e:
                self._emit_event('scan.file.error', f'Failed to scan {fp}: {e}')
            pct = int((i + 1) / total * 100) if total else 0
            self.root.after(0, lambda p=pct, c=i+1, t=total: self._prog(p, c, t))
        self.root.after(0, self._scan_done)

    def _process(self, sc):
        m = self.multi_matcher.match(sc)
        self._emit_event('scan.file', f'Processed {sc.filename}')
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
        self._mark_dirty()
        self._refresh_missing()
        self._emit_event('scan.completed', f'Scanned {len(self.scanned_files)} files')
        self._mark_dirty()
        self._refresh_menu_state()
        messagebox.showinfo("Done", f"Scanned {len(self.scanned_files):,}\n"
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
        self._emit_event('missing.refreshed', f'Missing ROMs: {len(missing)}')

    # ── Force Identify ────────────────────────────────────────────

    def _force_identified(self):
        sel = self.un_tree.selection()
        if not sel:
            messagebox.showwarning("Warning", "Select files to force")
            return

        # Show detailed confirmation
        msg = f"Force {len(sel)} unidentified file(s) to Identified?\n\n" \
              "These files will be added to the Identified list\n" \
              "using their filenames as ROM names."
        if not messagebox.askyesno("Confirm", msg):
            return

        self._emit_event('identify.force', f'Forced {len(sel)} file(s) to identified')
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
        self._mark_dirty()

    # ── Organization ──────────────────────────────────────────────

    def _preview(self):
        out = self.output_var.get()
        if not out:
            messagebox.showwarning("Warning", "Select output folder")
            return
        if not self.identified:
            messagebox.showwarning("Warning", "No identified ROMs")
            return
        try:
            plan = self.organizer.preview(self.identified, out, self.strategy_var.get(), self.action_var.get())
        except ValueError as e:
            messagebox.showerror("Error", str(e))
            return
        win = tk.Toplevel(self.root)
        win.title("Organization Preview")
        self._center_window(win, 900, 620)
        win.configure(bg=self.colors['bg'])
        ttk.Label(win, text=f"Strategy: {plan.strategy_description}").pack(anchor=tk.W, padx=10, pady=(10, 0))
        ttk.Label(win, text=f"Files: {plan.total_files:,} | Size: {format_size(plan.total_size)}").pack(anchor=tk.W, padx=10)
        txt = tk.Text(win, bg=self.colors['surface'], fg=self.colors['fg'], font=('Consolas', 9), wrap=tk.NONE)
        txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        for a in plan.actions:
            txt.insert(tk.END, f"[{a.action_type}] {os.path.basename(a.source)} -> {os.path.relpath(a.destination, out)}\n")
        txt.config(state=tk.DISABLED)

    def _organize(self):
        out = self.output_var.get()
        if not out:
            messagebox.showwarning("Warning", "Select output folder")
            return
        if not self.identified:
            messagebox.showwarning("Warning", "No identified ROMs")
            return
        s = self.strategy_var.get()
        a = self.action_var.get()
        total_size = sum(f.size for f in self.identified if f.matched_rom)
        msg = f"Organize {len(self.identified):,} ROMs?\n\n" \
              f"Strategy: {s}\n" \
              f"Action: {a}\n" \
              f"Total size: {format_size(total_size)}\n" \
              f"Output: {out}"
        if not messagebox.askyesno("Confirm", msg):
            return
        try:
            acts = self.organizer.organize(self.identified, out, s, a)
            messagebox.showinfo("Done", f"Organized {len(acts):,} ROMs!")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _undo(self):
        if not self.organizer.get_history_count():
            messagebox.showinfo("Info", "Nothing to undo")
            return
        if messagebox.askyesno("Confirm", "Undo last organization?"):
            if self.organizer.undo_last():
                messagebox.showinfo("Done", "Undo complete")

    # ── Collections ───────────────────────────────────────────────

    def _mark_dirty(self):
        self.is_dirty = True
        self._refresh_menu_state()

    def _confirm_discard_unsaved(self):
        if not self.is_dirty:
            return True
        return messagebox.askyesno("Unsaved Changes", "You have unsaved changes. Continue and discard them?")

    def _build_collection_payload(self, name):
        dats = self.multi_matcher.get_dat_list()
        return Collection(
            name=name,
            created_at=datetime.now().isoformat(),
            dat_infos=dats,
            dat_filepaths=[d.filepath for d in dats],
            scan_folder=self.scan_path_var.get(),
            scan_options={'recursive': self.recursive_var.get(), 'scan_archives': self.scan_archives_var.get()},
            identified=[f.to_dict() for f in self.identified],
            unidentified=[f.to_dict() for f in self.unidentified],
            settings={
                'strategy': self.strategy_var.get(),
                'action': self.action_var.get(),
                'output': self.output_var.get(),
                'search_query': self._search_var.get(),
            },
        )

    def _new_collection(self):
        if not self._confirm_discard_unsaved():
            return
        self.multi_matcher = MultiROMMatcher()
        self.scanned_files.clear()
        self.identified.clear()
        self.unidentified.clear()
        self.current_collection_path = None
        self.is_dirty = False
        self.scan_path_var.set("No folder selected")
        self.output_var.set("")
        self._search_var.set("")
        self._refresh_dats()
        self._refill_id()
        self._refill_un()
        self._refill_ms()
        self._update_stats()
        self._refresh_menu_state()

    def _save_collection_quick(self):
        if self.current_collection_path:
            name = os.path.splitext(os.path.basename(self.current_collection_path))[0]
            coll = self._build_collection_payload(name)
            self.collection_manager.save(coll, self.current_collection_path)
            self.is_dirty = False
            self._save_session_state()
            self._refresh_menu_state()
            messagebox.showinfo("Saved", f"Collection saved:\n{self.current_collection_path}")
            return
        self._save_collection()

    def _save_collection(self):
        name = simpledialog.askstring("Save Collection", "Collection name:", parent=self.root)
        if not name:
            return
        coll = self._build_collection_payload(name)
        fp = self.collection_manager.save(coll)
        self.current_collection_path = fp
        self.is_dirty = False
        self._save_session_state()
        self._refresh_recent_menu()
        self._refresh_menu_state()
        messagebox.showinfo("Saved", f"Collection saved:\n{fp}")

    def _open_collection(self):
        if not self._confirm_discard_unsaved():
            return
        fp = filedialog.askopenfilename(title="Open Collection", filetypes=[("ROM Collections", "*.romcol.json"), ("All", "*.*")])
        if fp:
            self._load_coll(fp)

    def _load_coll(self, fp):
        try:
            coll = self.collection_manager.load(fp)
        except Exception as e:
            messagebox.showerror("Error", str(e))
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
        settings = coll.settings
        if settings.get('strategy'):
            self.strategy_var.set(settings['strategy'])
        if settings.get('action'):
            self.action_var.set(settings['action'])
        if settings.get('output'):
            self.output_var.set(settings['output'])
        if settings.get('search_query'):
            self._search_var.set(settings['search_query'])
        self.current_collection_path = fp
        self.is_dirty = False
        self._save_session_state()
        self._refresh_recent_menu()
        self._refresh_menu_state()
        messagebox.showinfo("Loaded", f"Collection '{coll.name}' loaded")

    def _backup_snapshot(self):
        if not self.current_collection_path or not os.path.exists(self.current_collection_path):
            messagebox.showwarning("Warning", "Save a collection first before creating snapshots.")
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{self.current_collection_path}.{ts}.bak"
        shutil.copy2(self.current_collection_path, backup_path)
        messagebox.showinfo("Snapshot", f"Snapshot created:\n{backup_path}")

    def _restore_snapshot(self):
        fp = filedialog.askopenfilename(title="Restore Snapshot", filetypes=[("Backup Files", "*.bak"), ("All", "*.*")])
        if not fp:
            return
        if not self.current_collection_path:
            self.current_collection_path = fp.replace('.bak', '')
        shutil.copy2(fp, self.current_collection_path)
        self._load_coll(self.current_collection_path)

    def _save_session_state(self):
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        state = {
            'current_collection_path': self.current_collection_path,
            'search_query': self._search_var.get() if hasattr(self, '_search_var') else '',
            'scan_path': self.scan_path_var.get() if hasattr(self, 'scan_path_var') else '',
        }
        import json
        with open(self.SESSION_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)

    def _prompt_recover_last_session(self):
        if not os.path.exists(self.SESSION_STATE_FILE):
            return
        try:
            import json
            state = json.loads(Path(self.SESSION_STATE_FILE).read_text(encoding='utf-8'))
        except Exception:
            return
        path = state.get('current_collection_path')
        if path and os.path.exists(path) and messagebox.askyesno("Recover Session", "Recover last collection session?"):
            self._load_coll(path)

    def _on_app_exit(self):
        if not self._confirm_discard_unsaved():
            return
        self._save_session_state()
        self.root.quit()

    def _refresh_recent_menu(self):
        self._recent_menu.delete(0, tk.END)
        recent = self.collection_manager.get_recent()
        if not recent:
            self._recent_menu.add_command(label="(none)", state=tk.DISABLED)
            return
        for e in recent[:10]:
            n, p = e.get('name', '?'), e.get('filepath', '')
            self._recent_menu.add_command(label=n, command=lambda pp=p: self._load_coll(pp))

    def _refresh_menu_state(self):
        has_collection = bool(self.current_collection_path or self.identified or self.unidentified)
        has_missing = bool(self.multi_matcher.matchers and self.multi_matcher.get_missing(self.identified))
        if hasattr(self, 'export_menu'):
            state = tk.NORMAL if has_missing else tk.DISABLED
            for i in range(3):
                self.export_menu.entryconfig(i, state=state)
        if hasattr(self, 'tools_menu'):
            state = tk.NORMAL if has_collection else tk.DISABLED
            for i in range(5):
                self.tools_menu.entryconfig(i, state=state)
        if hasattr(self, 'queue_menu'):
            self.queue_menu.entryconfig(0, state=tk.NORMAL if has_missing else tk.DISABLED)

    # ── Export ────────────────────────────────────────────────────

    def _export_missing(self, fmt):
        if not self.multi_matcher.matchers:
            messagebox.showwarning("Warning", "Load DATs and scan first")
            return
        exts = {'txt': '.txt', 'csv': '.csv', 'json': '.json'}
        fp = filedialog.asksaveasfilename(title="Export Missing ROMs",
            defaultextension=exts.get(fmt, '.txt'),
            filetypes=[(f"{fmt.upper()}", f"*{exts.get(fmt)}"), ("All", "*.*")])
        if not fp:
            return
        self._emit_event('dat.add.requested', f'Selected DAT: {fp}')
        report = self.reporter.generate_multi_report(
            self.multi_matcher.dat_infos, self.multi_matcher.all_roms, self.identified)
        getattr(self.reporter, f'export_{fmt}')(report, fp)
        messagebox.showinfo("Exported", f"Saved to:\n{fp}")

    def _queue_missing_downloads(self):
        if not self.multi_matcher.matchers:
            messagebox.showwarning("Warning", "Load DATs and scan first")
            return
        missing = [r.name for r in self.multi_matcher.get_missing(self.identified) if r.name not in self.ignored_missing]
        self.download_queue.extend(missing)
        self.download_queue = list(dict.fromkeys(self.download_queue))
        self._log_download_event(f"Queued {len(missing)} missing ROM(s)")
        self._refresh_menu_state()
        messagebox.showinfo("Queue", f"Added {len(missing)} ROM(s) to queue")

    def _queue_selected_missing_downloads(self):
        selection = self.ms_tree.selection()
        names = [self.ms_tree.item(item)['values'][0] for item in selection]
        self.download_queue.extend(names)
        self.download_queue = list(dict.fromkeys(self.download_queue))
        self._log_download_event(f"Queued selected ROM(s): {len(names)}")

    def _mark_missing_as_ignored(self):
        for item in self.ms_tree.selection():
            values = self.ms_tree.item(item)['values']
            if values:
                self.ignored_missing.add(values[0])
        self._refresh_missing()
        self._log_download_event("Marked selected missing ROM(s) as ignored")

    def _start_download_queue(self):
        if not self.download_queue:
            messagebox.showinfo("Queue", "Queue is empty")
            return
        self.download_queue_paused = False
        self._log_download_event(f"Started queue with {len(self.download_queue)} items")
        first = self.download_queue[0]
        webbrowser.open(f"https://myrient.erista.me/files?search={first}")

    def _pause_download_queue(self):
        self.download_queue_paused = True
        self._log_download_event("Queue paused")

    def _resume_download_queue(self):
        self.download_queue_paused = False
        self._log_download_event("Queue resumed")

    def _cancel_download_queue(self):
        count = len(self.download_queue)
        self.download_queue.clear()
        self._log_download_event(f"Queue cancelled ({count} pending)")
        self._refresh_menu_state()

    def _retry_failed_downloads(self):
        self._log_download_event("Retry failed requested")
        messagebox.showinfo("Queue", "Retry requested. Review the download log for details.")

    def _verify_crc_after_download(self):
        messagebox.showinfo("Verification", "CRC verification is enabled via scan + DAT matching.")

    def _quarantine_invalid_files(self):
        messagebox.showinfo("Verification", "Use Tools > Generate Integrity Audit to identify invalid files.")

    def _open_download_log(self):
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        Path(self.DOWNLOAD_LOG_FILE).touch(exist_ok=True)
        webbrowser.open(f"file://{os.path.abspath(self.DOWNLOAD_LOG_FILE)}")

    def _export_download_report(self, fmt):
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        lines = []
        if os.path.exists(self.DOWNLOAD_LOG_FILE):
            lines = Path(self.DOWNLOAD_LOG_FILE).read_text(encoding='utf-8').splitlines()
        ext = '.csv' if fmt == 'csv' else '.json'
        fp = filedialog.asksaveasfilename(title="Export Download Report", defaultextension=ext,
                                          filetypes=[(fmt.upper(), f"*{ext}"), ("All", "*.*")])
        if not fp:
            return
        if fmt == 'csv':
            Path(fp).write_text("timestamp,event\n" + "\n".join(l.replace(' | ', ',') for l in lines), encoding='utf-8')
        else:
            import json
            rows = []
            for line in lines:
                parts = line.split(' | ', 1)
                rows.append({'timestamp': parts[0] if parts else '', 'event': parts[1] if len(parts) > 1 else ''})
            Path(fp).write_text(json.dumps(rows, indent=2), encoding='utf-8')

    def _log_download_event(self, event):
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        with open(self.DOWNLOAD_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now().isoformat()} | {event}\n")

    def _dedupe_crc(self):
        seen = set()
        removed = 0
        keep = []
        for sc in self.identified:
            crc = (sc.crc32 or '').upper()
            if crc and crc in seen:
                removed += 1
                continue
            seen.add(crc)
            keep.append(sc)
        self.identified = keep
        self.scanned_files = self.identified + self.unidentified
        self._refill_id()
        self._update_stats()
        self._mark_dirty()
        self._refresh_missing()
        self._mark_dirty()
        messagebox.showinfo("Deduplicate", f"Removed {removed} duplicate identified ROM(s)")

    def _find_name_collisions(self):
        counts = {}
        for sc in self.identified:
            name = (sc.matched_rom.name if sc.matched_rom else sc.filename)
            counts[name] = counts.get(name, 0) + 1
        collisions = [n for n, c in counts.items() if c > 1]
        messagebox.showinfo("Name Collisions", f"Found {len(collisions)} collision(s)")

    def _normalize_filenames(self):
        changes = 0
        for sc in self.unidentified:
            normalized = " ".join(sc.filename.replace('_', ' ').split())
            if normalized != sc.filename:
                sc.filename = normalized
                changes += 1
        self._refill_un()
        self._mark_dirty()
        messagebox.showinfo("Normalize", f"Normalized {changes} filename(s)")

    def _mass_rename_dat_convention(self):
        changes = 0
        for sc in self.identified:
            if sc.matched_rom and sc.filename != sc.matched_rom.name:
                sc.filename = sc.matched_rom.name
                changes += 1
        self._refill_id()
        self._mark_dirty()
        messagebox.showinfo("Mass Rename", f"Updated {changes} item name(s) in collection view")

    def _generate_integrity_audit(self):
        os.makedirs('data', exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        fp = os.path.join('data', f'integrity_audit_{ts}.txt')
        with open(fp, 'w', encoding='utf-8') as f:
            f.write(f"Total scanned: {len(self.scanned_files)}\n")
            f.write(f"Identified: {len(self.identified)}\n")
            f.write(f"Unidentified: {len(self.unidentified)}\n")
            f.write(f"Missing: {len(self.multi_matcher.get_missing(self.identified)) if self.multi_matcher.matchers else 0}\n")
        messagebox.showinfo("Integrity Audit", f"Audit report generated:\n{fp}")

    def _show_keyboard_shortcuts(self):
        messagebox.showinfo(
            "Keyboard Shortcuts",
            "Ctrl+N New\nCtrl+O Open\nCtrl+S Save\nCtrl+E Export Missing\nCtrl+D Queue Missing\nCtrl+Shift+P Command Palette\nF5 Refresh",
        )

    def _show_command_palette(self):
        cmd = simpledialog.askstring("Command Palette", "Type command:\nnew/open/save/export/queue/audit")
        if not cmd:
            return
        cmd = cmd.strip().lower()
        actions = {
            'new': self._new_collection,
            'open': self._open_collection,
            'save': self._save_collection_quick,
            'export': lambda: self._export_missing('txt'),
            'queue': self._queue_missing_downloads,
            'audit': self._generate_integrity_audit,
        }
        action = actions.get(cmd)
        if action:
            action()
        else:
            messagebox.showinfo("Command Palette", f"Unknown command: {cmd}")

    # ── Settings & About ───────────────────────────────────────────

    def _show_settings(self):
        """Show settings dialog (placeholder)"""
        messagebox.showinfo("Settings", "Settings dialog coming soon!")

    def _show_about(self):
        """Show about dialog"""
        messagebox.showinfo("About", "ROM Collection Manager v2\n\n"
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
        win.title("DAT Library")
        self._center_window(win, 980, 720)
        win.configure(bg=self.colors['bg'])
        win.transient(self.root)
        win.grab_set()

        ttk.Label(win, text="DAT Library", font=('Segoe UI', 14, 'bold')).pack(anchor=tk.W, padx=10, pady=(10, 5))
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
                    messagebox.showerror("Error", str(e))

        def load_sel():
            s = lt.selection()
            if not s:
                return
            p = lib.get_dat_path(s[0])
            if p:
                try:
                    di, roms = DATParser.parse_with_info(p)
                    self.multi_matcher.add_dat(di, roms)
                    self._emit_event('dat.add.completed', f'Loaded {di.system_name} ({di.rom_count} ROMs)')
                    self._refresh_dats()
                    messagebox.showinfo("Loaded", di.system_name)
                except Exception as e:
                    messagebox.showerror("Error", str(e))

        def rem():
            s = lt.selection()
            if s and messagebox.askyesno("Confirm", "Remove from library?"):
                lib.remove_dat(s[0])
                refresh()

        ttk.Button(br, text="Import DAT...", command=imp).pack(side=tk.LEFT)
        ttk.Button(br, text="Load Selected", command=load_sel).pack(side=tk.LEFT, padx=(5, 0))
        ttk.Button(br, text="Remove", command=rem).pack(side=tk.LEFT, padx=(5, 0))

        ttk.Label(win, text="DAT Sources", font=('Segoe UI', 12, 'bold')).pack(anchor=tk.W, padx=10, pady=(10, 5))
        for s in src.get_sources():
            r = ttk.Frame(win)
            r.pack(fill=tk.X, padx=10, pady=2)
            ttk.Label(r, text=s['name'], width=30).pack(side=tk.LEFT)
            ttk.Label(r, text=f"({s['type']})", width=10).pack(side=tk.LEFT)
            ttk.Button(r, text="Open Page",
                       command=lambda sid=s['id']: src.open_source_page(sid)).pack(side=tk.LEFT, padx=(5, 0))

    # ── Links ─────────────────────────────────────────────────────

    def _open_myrient_site(self):
        """Open default Myrient website from Downloads menu."""
        url = "https://myrient.erista.me"
        self._emit_event('menu.downloads.myrient', f'Opened {url}')
        webbrowser.open(url)

    def _open_download_link(self, label, url):
        """Open external download links from Downloads menu."""
        self._emit_event('menu.downloads.link', f'Opened {label}: {url}')
        webbrowser.open(url)

    # ── Run ───────────────────────────────────────────────────────

    def run(self):
        self.root.mainloop()


def run_gui():
    if not GUI_AVAILABLE:
        print("Error: tkinter is not available")
        return 1
    app = ROMManagerGUI()
    app.run()
    return 0
