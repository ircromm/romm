"""
Graphical user interface for ROM Manager (tkinter)
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
from .shared_config import (
    IDENTIFIED_COLUMNS, UNIDENTIFIED_COLUMNS, MISSING_COLUMNS,
    REGION_COLORS, DEFAULT_REGION_COLOR, STRATEGIES,
)


class ROMManagerGUI:
    """Main GUI application"""

    def __init__(self):
        if not GUI_AVAILABLE:
            raise RuntimeError("tkinter is not available")

        self.root = tk.Tk()
        install_tk_exception_bridge(self.root)
        monitor_action("tkinter gui opened")
        self.root.title("ROM Collection Manager v2")
        self.root.geometry("1300x850")
        self.root.minsize(1000, 650)

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

        # Setup
        self._setup_theme()
        self._build_menu()
        self._build_ui()

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

        file_menu = tk.Menu(menubar, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        file_menu.add_command(label="Save Collection...", command=self._save_collection)
        file_menu.add_command(label="Open Collection...", command=self._open_collection)
        file_menu.add_separator()
        self._recent_menu = tk.Menu(file_menu, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        file_menu.add_cascade(label="Recent Collections", menu=self._recent_menu)
        self._refresh_recent_menu()
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        dat_menu = tk.Menu(menubar, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        dat_menu.add_command(label="DAT Library...", command=self._show_dat_library)
        menubar.add_cascade(label="DATs", menu=dat_menu)

        export_menu = tk.Menu(menubar, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        export_menu.add_command(label="Export Missing (TXT)...", command=lambda: self._export_missing('txt'))
        export_menu.add_command(label="Export Missing (CSV)...", command=lambda: self._export_missing('csv'))
        export_menu.add_command(label="Export Missing (JSON)...", command=lambda: self._export_missing('json'))
        menubar.add_cascade(label="Export", menu=export_menu)

        help_menu = tk.Menu(menubar, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
        help_menu.add_command(label="Settings", command=self._show_settings)
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

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

        # Toolbar (ABOVE table)
        ms_toolbar = ttk.Frame(ms_f)
        ms_toolbar.pack(fill=tk.X, padx=0, pady=(0, 5))

        # Left side: View actions
        ms_left = ttk.Frame(ms_toolbar)
        ms_left.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(ms_left, text="Refresh", command=self._refresh_missing).pack(side=tk.LEFT)
        ttk.Button(ms_left, text="Search Archive.org", command=self._search_archive).pack(side=tk.LEFT, padx=(5, 0))

        # Right side: Download actions with dropdown
        ms_right = ttk.Frame(ms_toolbar)
        ms_right.pack(side=tk.RIGHT)

        # Selection count label
        self.ms_selection_var = tk.StringVar(value="")
        ttk.Label(ms_right, textvariable=self.ms_selection_var).pack(side=tk.LEFT, padx=(10, 0))

        # Completeness info (BELOW toolbar)
        ms_info = ttk.Frame(ms_f)
        ms_info.pack(fill=tk.X, padx=0, pady=(0, 3))
        self.completeness_var = tk.StringVar(value="Load DATs and scan to see missing ROMs")
        ttk.Label(ms_info, textvariable=self.completeness_var, style='Stats.TLabel').pack(side=tk.LEFT)

        # The table itself
        self.ms_tree = self._make_tree(ms_f, MISSING_COLUMNS)
        self._setup_region_tags(self.ms_tree)

        # Bind selection change events to update selection count
        self.ms_tree.bind('<<Change>>', self._update_ms_selection_count)
        self.ms_tree.bind('<Button-1>', lambda e: self.root.after(10, self._update_ms_selection_count))
        self.ms_tree.bind('<Control-Button-1>', lambda e: self.root.after(10, self._update_ms_selection_count))

        # Stats
        self.stats_var = tk.StringVar(value="No files scanned")
        ttk.Label(main, textvariable=self.stats_var, style='Stats.TLabel').pack(anchor=tk.W, pady=(0, 8))

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

        # Keyboard shortcuts
        self.root.bind('<Control-a>', self._on_select_all)
        self.root.bind('<Control-c>', self._on_copy)
        self.root.bind('<F5>', self._on_refresh)
        self.root.bind('<Delete>', self._on_delete_key)
        self.root.bind('<Escape>', self._on_escape)

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

        menu.add_command(label="Copy", command=lambda: self._copy_to_clipboard(tree, item, 'name'))
        menu.add_command(label="Copy CRC32", command=lambda: self._copy_to_clipboard(tree, item, 'crc'))
        menu.add_separator()
        menu.add_command(label="Search Archive.org", command=lambda: self._search_archive_for_item(tree, item))
        menu.add_separator()
        menu.add_command(label="Open Folder", command=lambda: self._open_rom_folder(tree, item))

        menu.post(event.x_root, event.y_root)

    def _show_unidentified_context_menu(self, event, tree, item):
        """Context menu for Unidentified tab"""
        menu = tk.Menu(tree, tearoff=False, bg=self.colors['surface'], fg=self.colors['fg'])

        menu.add_command(label="Copy", command=lambda: self._copy_to_clipboard(tree, item, 'name'))
        menu.add_command(label="Copy CRC32", command=lambda: self._copy_to_clipboard(tree, item, 'crc'))
        menu.add_separator()
        menu.add_command(label="Force to Identified", command=lambda: self._force_identified_from_context(tree, item))
        menu.add_command(label="Search Archive.org", command=lambda: self._search_archive_for_item(tree, item))
        menu.add_separator()
        menu.add_command(label="Open Folder", command=lambda: self._open_rom_folder(tree, item))

        menu.post(event.x_root, event.y_root)

    def _show_missing_context_menu(self, event, tree, item):
        """Context menu for Missing tab"""
        menu = tk.Menu(tree, tearoff=False, bg=self.colors['surface'], fg=self.colors['fg'])

        menu.add_command(label="Copy", command=lambda: self._copy_to_clipboard(tree, item, 'name'))
        menu.add_command(label="Copy CRC32", command=lambda: self._copy_to_clipboard(tree, item, 'crc'))
        menu.add_separator()
        menu.add_separator()
        menu.add_command(label="Search Archive.org", command=lambda: self._search_archive_for_item(tree, item))
        menu.add_command(label="Copy to Clipboard", command=lambda: self._copy_to_clipboard(tree, item, 'name'))

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
                    messagebox.showinfo("Copied", f"CRC32 copied: {crc_value}")
                except:
                    pass
        elif copy_type == 'name':
            # Copy the name/filename (first or second column usually)
            name_value = values[1] if len(values) > 1 else values[0]
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(name_value)
                messagebox.showinfo("Copied", f"Copied: {name_value}")
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
            messagebox.showinfo("Info", "Missing ROMs don't have local paths.")

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
        response = messagebox.askyesno("Copy", "Copy CRC32? (No = copy names)")
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
        fp = filedialog.askopenfilename(title="Select DAT File",
            filetypes=[("DAT files", "*.dat *.xml *.zip"), ("Compressed", "*.zip *.gz"), ("All", "*.*")])
        if not fp:
            return
        try:
            di, roms = DATParser.parse_with_info(fp)
            self.multi_matcher.add_dat(di, roms)
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
            self.multi_matcher.remove_dat(dats[sel[0]].id)
            self._refresh_dats()

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

    def _search_archive(self):
        sel = self.ms_tree.selection()
        if not sel:
            messagebox.showwarning("Warning", "Select missing ROMs first")
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
            messagebox.showwarning("Warning", "Select files to force")
            return

        # Show detailed confirmation
        msg = f"Force {len(sel)} unidentified file(s) to Identified?\n\n" \
              "These files will be added to the Identified list\n" \
              "using their filenames as ROM names."
        if not messagebox.askyesno("Confirm", msg):
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
        self._center_window(win, 700, 500)
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
        s = coll.settings
        if s.get('strategy'):
            self.strategy_var.set(s['strategy'])
        if s.get('action'):
            self.action_var.set(s['action'])
        if s.get('output'):
            self.output_var.set(s['output'])
        self._refresh_recent_menu()
        messagebox.showinfo("Loaded", f"Collection '{coll.name}' loaded")

    def _refresh_recent_menu(self):
        self._recent_menu.delete(0, tk.END)
        recent = self.collection_manager.get_recent()
        if not recent:
            self._recent_menu.add_command(label="(none)", state=tk.DISABLED)
            return
        for e in recent[:10]:
            n, p = e.get('name', '?'), e.get('filepath', '')
            self._recent_menu.add_command(label=n, command=lambda pp=p: self._load_coll(pp))

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
        report = self.reporter.generate_multi_report(
            self.multi_matcher.dat_infos, self.multi_matcher.all_roms, self.identified)
        getattr(self.reporter, f'export_{fmt}')(report, fp)
        messagebox.showinfo("Exported", f"Saved to:\n{fp}")

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
        self._center_window(win, 800, 600)
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

    # ── Myrient Download ───────────────────────────────────────────

    def _check_myrient(self):
        if not MYRIENT_AVAILABLE:
            messagebox.showerror("Error", "Myrient downloader not available.\n"
                                 "Install 'requests': pip install requests")
            return False
        return True

    def _download_selected_missing(self):
        """Download only the selected missing ROMs from the tree."""
        if not self._check_myrient():
            return
        sel = self.ms_tree.selection()
        if not sel:
            messagebox.showwarning("Warning", "Select missing ROMs to download")
            return

        # Collect selected ROM names
        selected_names = set()
        for item in sel:
            vals = self.ms_tree.item(item, 'values')
            if vals:
                selected_names.add(vals[0])  # rom_name is first column

        # Find matching ROMInfo objects
        all_missing = self.multi_matcher.get_missing(self.identified)
        to_download = [r for r in all_missing if r.name in selected_names]

        if not to_download:
            messagebox.showwarning("Warning", "Could not match selected ROMs")
            return

        total_size = sum(r.size for r in to_download)
        msg = f"Download {len(to_download)} selected ROM(s)?\n\nTotal size: {format_size(total_size)}"
        self._start_download_flow(to_download, msg)

    def _download_missing_dialog(self):
        """Download all missing ROMs."""
        if not self._check_myrient():
            return
        if not self.multi_matcher.matchers:
            messagebox.showwarning("Warning", "Load DATs and scan first")
            return
        all_missing = self.multi_matcher.get_missing(self.identified)
        if not all_missing:
            messagebox.showinfo("Info", "No missing ROMs!")
            return
        total_size = sum(r.size for r in all_missing)
        msg = f"Download {len(all_missing):,} missing ROM(s)?\n\nTotal size: {format_size(total_size)}"
        self._start_download_flow(all_missing, msg)

    def _start_download_flow(self, roms_to_download, confirm_msg):
        """
        Show a guided download dialog:
        1. Confirm count
        2. Choose destination (default = scan folder)
        3. Resolve URLs (with progress)
        4. Download sequentially (with progress, pause/cancel)
        """
        # Step 1: Determine destination
        scan_folder = self.scan_path_var.get()
        default_dest = scan_folder if scan_folder != "No folder selected" and os.path.isdir(scan_folder) else ""

        win = tk.Toplevel(self.root)
        win.title("Download Missing ROMs")
        self._center_window(win, 650, 550)
        win.configure(bg=self.colors['bg'])
        win.transient(self.root)
        win.grab_set()

        # Header
        ttk.Label(win, text="Download Missing ROMs from Myrient",
                  font=('Segoe UI', 14, 'bold')).pack(anchor=tk.W, padx=15, pady=(15, 5))

        # Info
        info_var = tk.StringVar(value=f"{len(roms_to_download):,} ROMs to download")
        ttk.Label(win, textvariable=info_var, style='Stats.TLabel').pack(anchor=tk.W, padx=15, pady=(0, 10))

        # Destination
        dest_frame = ttk.LabelFrame(win, text="Download Destination", padding=8)
        dest_frame.pack(fill=tk.X, padx=15, pady=(0, 10))
        dest_var = tk.StringVar(value=default_dest)
        ttk.Label(dest_frame, text="ROMs will be saved to your scan folder so they're\n"
                  "automatically detected on next scan.",
                  foreground=self.colors['fg']).pack(anchor=tk.W)
        dest_row = ttk.Frame(dest_frame)
        dest_row.pack(fill=tk.X, pady=(5, 0))
        ttk.Entry(dest_row, textvariable=dest_var, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(dest_row, text="Browse...",
                   command=lambda: dest_var.set(filedialog.askdirectory(title="Download Destination") or dest_var.get())
                   ).pack(side=tk.LEFT, padx=(5, 0))

        # Delay between downloads
        delay_frame = ttk.LabelFrame(win, text="Download Settings", padding=8)
        delay_frame.pack(fill=tk.X, padx=15, pady=(0, 10))
        delay_row = ttk.Frame(delay_frame)
        delay_row.pack(fill=tk.X)
        ttk.Label(delay_row, text="Delay between downloads (seconds):").pack(side=tk.LEFT)
        delay_var = tk.IntVar(value=5)
        delay_spin = ttk.Spinbox(delay_row, from_=0, to=60, textvariable=delay_var, width=5)
        delay_spin.pack(side=tk.LEFT, padx=(8, 0))

        # Progress area
        prog_frame = ttk.LabelFrame(win, text="Progress", padding=8)
        prog_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 10))

        status_var = tk.StringVar(value="Ready to start")
        ttk.Label(prog_frame, textvariable=status_var).pack(anchor=tk.W)

        # Overall progress
        ttk.Label(prog_frame, text="Overall:").pack(anchor=tk.W, pady=(5, 0))
        overall_bar = ttk.Progressbar(prog_frame, mode='determinate')
        overall_bar.pack(fill=tk.X)
        overall_label = tk.StringVar(value="0 / 0")
        ttk.Label(prog_frame, textvariable=overall_label).pack(anchor=tk.W)

        # Current file progress
        ttk.Label(prog_frame, text="Current file:").pack(anchor=tk.W, pady=(5, 0))
        file_bar = ttk.Progressbar(prog_frame, mode='determinate')
        file_bar.pack(fill=tk.X)
        file_label = tk.StringVar(value="")
        ttk.Label(prog_frame, textvariable=file_label).pack(anchor=tk.W)

        # Log area
        log = tk.Text(prog_frame, height=6, bg=self.colors['surface'],
                      fg=self.colors['fg'], font=('Consolas', 8), wrap=tk.WORD)
        log.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        # Buttons
        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=15, pady=(0, 15))

        downloader = [None]  # mutable ref
        downloading = [False]

        def log_msg(msg):
            log.insert(tk.END, msg + '\n')
            log.see(tk.END)

        def on_progress(prog: DownloadProgress):
            """Called from download thread — schedule GUI updates."""
            task = prog.current_task
            def update():
                # Overall (Corrected Math: based on COMPLETED items, not current index)
                done_count = prog.completed + prog.failed
                pct = (done_count / prog.total_count * 100) if prog.total_count else 0
                overall_bar['value'] = pct
                overall_label.set(f"{done_count} / {prog.total_count} "
                                  f"({prog.completed} OK, {prog.failed} failed)")

                # Current file
                if task:
                    if task.total_bytes > 0:
                        fpct = (task.downloaded_bytes / task.total_bytes * 100)
                        file_bar['value'] = fpct
                        
                        # Detailed format: "Filename (5.2MB/10MB - 52%)"
                        mb_done = task.downloaded_bytes / (1024 * 1024)
                        mb_total = task.total_bytes / (1024 * 1024)
                        file_label.set(f"{task.rom_name} ({mb_done:.1f}/{mb_total:.1f} MB - {fpct:.1f}%)")
                    else:
                        file_bar.stop()
                        file_label.set(f"{task.rom_name} — {format_size(task.downloaded_bytes)}")

                    if task.status == DownloadStatus.COMPLETE:
                        status_var.set(f"Downloaded: {task.rom_name}")
                    elif task.status == DownloadStatus.FAILED:
                        status_var.set(f"Failed: {task.rom_name}")
                        log_msg(f"FAIL: {task.rom_name} — {task.error}")
                    elif task.status == DownloadStatus.CRC_MISMATCH:
                        status_var.set(f"CRC mismatch: {task.rom_name}")
                        log_msg(f"CRC MISMATCH: {task.rom_name} — {task.error}")
                    elif task.status == DownloadStatus.CANCELLED:
                        status_var.set("Cancelled")

            win.after(0, update)

        def start_download():
            dest = dest_var.get().strip()
            if not dest or not os.path.isdir(dest):
                messagebox.showwarning("Warning", "Select a valid destination folder", parent=win)
                return

            start_btn.config(state=tk.DISABLED)
            pause_btn.config(state=tk.NORMAL)
            cancel_btn.config(state=tk.NORMAL)
            downloading[0] = True

            def worker():
                try:
                    dl = MyrientDownloader()
                    downloader[0] = dl

                    # Phase 1: Resolve URLs
                    win.after(0, lambda: status_var.set("Resolving download URLs..."))
                    win.after(0, lambda: log_msg("Looking up ROM files on Myrient..."))

                    def resolve_progress(name, cur, tot):
                        win.after(0, lambda: status_var.set(f"Resolving: {cur}/{tot} — {name}"))
                        win.after(0, lambda: overall_bar.__setitem__('value', cur / tot * 50))

                    queued = dl.queue_missing_roms(roms_to_download, dest, resolve_progress)

                    win.after(0, lambda: log_msg(f"Found {queued} of {len(roms_to_download)} ROMs on Myrient"))

                    if queued == 0:
                        win.after(0, lambda: status_var.set("No ROMs found on Myrient"))
                        win.after(0, lambda: log_msg("None of the missing ROMs were found. They may not be available."))
                        win.after(0, lambda: start_btn.config(state=tk.NORMAL))
                        downloading[0] = False
                        return

                    # Phase 2: Download
                    win.after(0, lambda: status_var.set(f"Downloading {queued} ROMs..."))
                    win.after(0, lambda: overall_bar.__setitem__('value', 0))

                    result = dl.start_downloads(on_progress, download_delay=delay_var.get())

                    win.after(0, lambda: status_var.set(
                        f"Done! {result.completed} downloaded, {result.failed} failed, {result.cancelled} cancelled"))
                    win.after(0, lambda: overall_bar.__setitem__('value', 100))
                    win.after(0, lambda: log_msg(
                        f"COMPLETE: {result.completed} OK, {result.failed} failed, {result.cancelled} cancelled"))

                except Exception as e:
                    # Capturing 'e' as a local string to pass to thread-safe callback
                    error_msg = str(e)
                    win.after(0, lambda: status_var.set(f"Error: {error_msg}"))
                    win.after(0, lambda: log_msg(f"ERROR: {error_msg}"))
                finally:
                    downloading[0] = False
                    win.after(0, lambda: start_btn.config(state=tk.NORMAL))
                    win.after(0, lambda: pause_btn.config(state=tk.DISABLED))
                    win.after(0, lambda: cancel_btn.config(state=tk.DISABLED))

            start_monitored_thread(worker, name="tk-download-worker")

        def pause_download():
            if downloader[0]:
                if pause_btn.cget('text') == 'Pause':
                    downloader[0].pause()
                    pause_btn.config(text='Resume')
                    status_var.set("Paused")
                else:
                    downloader[0].resume()
                    pause_btn.config(text='Pause')
                    status_var.set("Resuming...")

        def cancel_download():
            if downloader[0]:
                downloader[0].cancel()
                status_var.set("Cancelling...")

        def on_close():
            if downloading[0] and downloader[0]:
                downloader[0].cancel()
            win.destroy()

        start_btn = ttk.Button(btn_frame, text="Start Download", command=start_download)
        start_btn.pack(side=tk.LEFT)
        pause_btn = ttk.Button(btn_frame, text="Pause", command=pause_download, state=tk.DISABLED)
        pause_btn.pack(side=tk.LEFT, padx=(5, 0))
        cancel_btn = ttk.Button(btn_frame, text="Cancel", command=cancel_download, state=tk.DISABLED)
        cancel_btn.pack(side=tk.LEFT, padx=(5, 0))
        ttk.Button(btn_frame, text="Close", command=on_close).pack(side=tk.RIGHT)

        win.protocol("WM_DELETE_WINDOW", on_close)

    # ── Myrient Browser ────────────────────────────────────────────

    def _show_myrient_browser(self):
        """Browse and download ROMs from the Myrient catalog."""
        if not self._check_myrient():
            return

        win = tk.Toplevel(self.root)
        win.title("Myrient ROM Browser")
        self._center_window(win, 1000, 700)
        win.configure(bg=self.colors['bg'])
        win.transient(self.root)
        win.grab_set()

        # Header
        ttk.Label(win, text="Myrient ROM Browser",
                  font=('Segoe UI', 14, 'bold')).pack(anchor=tk.W, padx=10, pady=(10, 5))
        ttk.Label(win, text="Browse and download ROMs from myrient.erista.me",
                  foreground=self.colors['fg']).pack(anchor=tk.W, padx=10, pady=(0, 10))

        # Main layout: system list on left, files on right
        panes = ttk.PanedWindow(win, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))

        # Left: system list (Corrected with scrollbar in frame)
        left = ttk.Frame(panes)
        panes.add(left, weight=1)

        ttk.Label(left, text="Systems:", font=('Segoe UI', 10, 'bold')).pack(anchor=tk.W)
        sys_search_var = tk.StringVar()
        ttk.Entry(left, textvariable=sys_search_var, width=30).pack(fill=tk.X, pady=(3, 3))

        sys_frame = ttk.Frame(left)
        sys_frame.pack(fill=tk.BOTH, expand=True)
        
        sys_vsb = ttk.Scrollbar(sys_frame, orient=tk.VERTICAL)
        sys_list = tk.Listbox(sys_frame, bg=self.colors['surface'], fg=self.colors['fg'],
                              selectbackground=self.colors['accent'], font=('Segoe UI', 9),
                              yscrollcommand=sys_vsb.set)
        sys_vsb.config(command=sys_list.yview)
        
        sys_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        sys_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Right: file list (Corrected with scrollbar)
        right = ttk.Frame(panes)
        panes.add(right, weight=2)

        file_toolbar = ttk.Frame(right)
        file_toolbar.pack(fill=tk.X)
        ttk.Label(file_toolbar, text="Files:", font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT)
        file_search_var = tk.StringVar()
        ttk.Entry(file_toolbar, textvariable=file_search_var, width=30).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(file_toolbar, text="Search", command=lambda: load_files(filter_text=file_search_var.get())
                   ).pack(side=tk.LEFT, padx=(5, 0))
        file_count_var = tk.StringVar(value="")
        ttk.Label(file_toolbar, textvariable=file_count_var).pack(side=tk.RIGHT)

        # File Tree + Scrollbar container
        tree_frame = ttk.Frame(right)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        file_vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        file_tree = ttk.Treeview(tree_frame, columns=['name', 'size'], show='headings', yscrollcommand=file_vsb.set)
        file_vsb.config(command=file_tree.yview)
        
        file_tree.heading('name', text='ROM Name')
        file_tree.heading('size', text='Size')
        file_tree.column('name', width=400)
        file_tree.column('size', width=100)
        
        file_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Bottom: download controls
        bottom = ttk.Frame(win)
        bottom.pack(fill=tk.X, padx=10, pady=(5, 10))
        
        dl_dest_var = tk.StringVar(value=self.scan_path_var.get() if self.scan_path_var.get() != "No folder selected" else "")
        ttk.Label(bottom, text="Save to:").pack(side=tk.LEFT)
        ttk.Entry(bottom, textvariable=dl_dest_var, width=40).pack(side=tk.LEFT, padx=(5, 0))
        ttk.Button(bottom, text="Browse...",
                   command=lambda: dl_dest_var.set(filedialog.askdirectory() or dl_dest_var.get())
                   ).pack(side=tk.LEFT, padx=(5, 0))
        
        ttk.Button(bottom, text="Download Selected", command=lambda: download_selected()).pack(side=tk.RIGHT)

        # In-Browser Progress Bar
        status_frame = ttk.Frame(win)
        status_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        dl_progress = ttk.Progressbar(status_frame, mode='determinate')
        dl_progress.pack(fill=tk.X, pady=(0, 2))
        
        dl_status_var = tk.StringVar(value="")
        ttk.Label(status_frame, textvariable=dl_status_var, font=('Segoe UI', 9)).pack(anchor=tk.W)

        # Data
        systems = MyrientDownloader.get_systems()
        all_systems = [(s['name'], s['category']) for s in systems]
        current_files = []
        current_system_url = [None]

        def fill_systems(q=''):
            sys_list.delete(0, tk.END)
            q = q.lower()
            for name, cat in all_systems:
                if q and q not in name.lower():
                    continue
                sys_list.insert(tk.END, f"[{cat}] {name}")

        fill_systems()

        def on_sys_search(*_):
            fill_systems(sys_search_var.get())

        sys_search_var.trace_add('write', on_sys_search)

        def on_sys_select(event):
            sel = sys_list.curselection()
            if not sel:
                return
            text = sys_list.get(sel[0])
            # Extract system name from "[Category] Name"
            name = text.split('] ', 1)[1] if '] ' in text else text
            load_files(name)

        sys_list.bind('<<ListboxSelect>>', on_sys_select)

        def load_files(system_name=None, filter_text=''):
            file_tree.delete(*file_tree.get_children())
            file_count_var.set("Loading...")
            win.update_idletasks()

            def worker():
                try:
                    dl = MyrientDownloader()
                    if system_name:
                        url = dl.find_system_url(system_name)
                        current_system_url[0] = url
                        files = dl.list_files(url=url) if url else []
                    else:
                        files = dl.list_files(url=current_system_url[0]) if current_system_url[0] else []

                    if filter_text:
                        q = filter_text.lower()
                        files = [f for f in files if q in f.name.lower()]

                    nonlocal current_files
                    current_files = files

                    def update_ui():
                        file_tree.delete(*file_tree.get_children())
                        for f in files:
                            file_tree.insert('', 'end', values=(f.name, f.size_text or '?'))
                        file_count_var.set(f"{len(files):,} files")

                    win.after(0, update_ui)
                except Exception as e:
                    error_msg = str(e)
                    win.after(0, lambda: file_count_var.set(f"Error: {error_msg}"))

            start_monitored_thread(worker, name="tk-list-files-worker")

    
        def download_selected():
            sel = file_tree.selection()
            if not sel:
                messagebox.showwarning("Warning", "Select files to download", parent=win)
                return
            dest = dl_dest_var.get().strip()
            if not dest:
                messagebox.showwarning("Warning", "Select download destination", parent=win)
                return

            # Match selection to file objects
            to_dl = []
            for item in sel:
                vals = file_tree.item(item, 'values')
                if vals:
                    name = vals[0]
                    for f in current_files:
                        if f.name == name:
                            to_dl.append(f)
                            break

            if not to_dl:
                return

            dl_status_var.set(f"Downloading {len(to_dl)} file(s)...")
            dl_progress['value'] = 0

            def worker():
                try:
                    dl = MyrientDownloader()
                    for i, f in enumerate(to_dl):
                        dl.queue_rom(rom_name=f.name, url=f.url, dest_folder=dest)
                        
                    def on_prog(prog):
                        t = prog.current_task
                        if t:
                            # Update Bar
                            pct = (prog.current_index / prog.total_count * 100) if prog.total_count else 0
                            win.after(0, lambda: dl_progress.__setitem__('value', pct))
                            
                            # Update Label with DETAILED progress
                            if t.total_bytes > 0:
                                fpct = (t.downloaded_bytes / t.total_bytes * 100)
                                mb_done = t.downloaded_bytes / (1024 * 1024)
                                mb_total = t.total_bytes / (1024 * 1024)
                                msg = f"Downloading: {t.rom_name} ({mb_done:.1f}/{mb_total:.1f} MB - {fpct:.1f}%)"
                            else:
                                msg = f"Downloading: {t.rom_name}..."
                                
                            win.after(0, lambda: dl_status_var.set(msg))

                    result = dl.start_downloads(on_prog, download_delay=0)
                    win.after(0, lambda: dl_status_var.set(
                        f"Done! {result.completed} OK, {result.failed} failed"))
                    win.after(0, lambda: dl_progress.__setitem__('value', 100))
                except Exception as e:
                    error_msg = str(e)
                    win.after(0, lambda: dl_status_var.set(f"Error: {error_msg}"))

            start_monitored_thread(worker, name="tk-quick-download-worker")

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