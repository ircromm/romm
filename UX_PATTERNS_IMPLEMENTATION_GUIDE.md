# ROM Manager UX Patterns - Implementation Guide

Complete implementation roadmap for applying Windows Explorer patterns to ROM Manager's tkinter interface.

---

## Overview

This guide provides step-by-step implementation instructions for integrating Windows Explorer UX patterns into ROM Manager. The patterns are organized by complexity and impact, allowing for incremental improvement.

**Key Documents:**
- `WINDOWS_EXPLORER_UX_PATTERNS.md` - Complete reference and theory
- `WINDOWS_EXPLORER_PATTERNS_QUICK_REFERENCE.md` - Quick lookup tables
- `UX_PATTERNS_IMPLEMENTATION_GUIDE.md` - This file: step-by-step implementation

---

## Current ROM Manager Architecture

**File Structure:**
```
D:\1 romm\APP\
├── rommanager/
│   ├── gui.py              (Main tkinter GUI - 1000+ lines)
│   ├── shared_config.py    (Column definitions, colors, strategies)
│   ├── models.py           (Data models)
│   └── ...other modules
└── data/
    ├── collections/
    ├── dats/
    └── ...
```

**Key GUI Components:**
```
ROMManagerGUI class (gui.py):
├── Root Tkinter window
├── Menu bar (File, DATs, Export, Downloads)
├── Top panel
│  ├── DAT management (Add, Remove, Library)
│  └── Scan controls (Browse, Scan, Options)
├── Search bar
├── Notebook (ttk.Notebook) with 3 tabs:
│  ├─ Identified ROMs (id_tree Treeview)
│  ├─ Unidentified Files (un_tree Treeview)
│  └─ Missing ROMs (ms_tree Treeview)
└── Organization panel
   ├── Strategy selection
   ├── Output configuration
   └── Action buttons
```

**Current Treeview Usage:**
```python
# Three parallel tree views defined in _build_ui():
self.id_tree = self._make_tree(id_f, IDENTIFIED_COLUMNS)
self.un_tree = self._make_tree(un_f, UNIDENTIFIED_COLUMNS)
self.ms_tree = self._make_tree(ms_f, MISSING_COLUMNS)

# All created by _make_tree() helper:
# - Creates ttk.Treeview with columns
# - Adds vertical/horizontal scrollbars
# - Configures column headings and widths
# - Returns tree reference
```

---

## Phase 1: Right-Click Context Menus (Week 1)

### Goal: Add context menu support to all three tree views

### Implementation Steps

#### Step 1: Create Context Menu Manager Class

**File:** `rommanager/ui_context_menus.py` (new file)

```python
"""Context menu handlers for tree views"""

import tkinter as tk
from tkinter import messagebox
import os
import subprocess

class TreeViewContextMenu:
    """Manages right-click context menus for tree views"""

    def __init__(self, parent_gui):
        self.gui = parent_gui
        self._create_menus()

    def _create_menus(self):
        """Create context menus for each tree view"""
        # Identified ROMs menu
        self.id_menu = tk.Menu(self.gui.id_tree, tearoff=0)
        self.id_menu.add_command(
            label="Copy File Path",
            command=lambda: self._copy_path(self.gui.id_tree, 0)
        )
        self.id_menu.add_command(
            label="Open in File Explorer",
            command=lambda: self._open_in_explorer(self.gui.id_tree, 0)
        )
        self.id_menu.add_separator()
        self.id_menu.add_command(
            label="Delete File",
            command=lambda: self._delete_file(self.gui.id_tree)
        )
        self.id_menu.add_separator()
        self.id_menu.add_command(
            label="Properties",
            command=lambda: self._show_properties(self.gui.id_tree)
        )

        # Unidentified Files menu
        self.un_menu = tk.Menu(self.gui.un_tree, tearoff=0)
        self.un_menu.add_command(
            label="Show in File Explorer",
            command=lambda: self._open_in_explorer(self.gui.un_tree, 1)
        )
        self.un_menu.add_separator()
        self.un_menu.add_command(
            label="Copy Path",
            command=lambda: self._copy_path(self.gui.un_tree, 1)
        )
        self.un_menu.add_separator()
        self.un_menu.add_command(
            label="Delete File",
            command=lambda: self._delete_file(self.gui.un_tree)
        )

        # Missing ROMs menu
        self.ms_menu = tk.Menu(self.gui.ms_tree, tearoff=0)
        self.ms_menu.add_command(
            label="Copy ROM Name",
            command=lambda: self._copy_path(self.gui.ms_tree, 1)
        )
        self.ms_menu.add_command(
            label="Search Archive.org",
            command=lambda: self._search_external(self.gui.ms_tree, 'archive')
        )
        self.ms_menu.add_separator()
        self.ms_menu.add_command(
            label="Download",
            command=lambda: self._download_rom(self.gui.ms_tree)
        )

    def bind_to_tree(self, tree, menu):
        """Bind right-click to show context menu"""
        tree.bind("<Button-3>", lambda e: self._show_menu(tree, menu, e))

    def _show_menu(self, tree, menu, event):
        """Show context menu at cursor position"""
        item = tree.identify('item', event.x, event.y)
        if item:
            tree.selection_set(item)
            menu.tk_popup(event.x_root, event.y_root)

    def _copy_path(self, tree, col_index):
        """Copy selected item's column value to clipboard"""
        selection = tree.selection()
        if not selection:
            return
        item = selection[0]
        value = tree.item(item)['values'][col_index]
        self.gui.root.clipboard_clear()
        self.gui.root.clipboard_append(value)

    def _open_in_explorer(self, tree, col_index):
        """Open folder containing selected item in File Explorer"""
        selection = tree.selection()
        if not selection:
            return
        item = selection[0]
        path = tree.item(item)['values'][col_index]

        # Handle both file and folder paths
        if os.path.isfile(path):
            folder = os.path.dirname(path)
        else:
            folder = path

        if os.path.exists(folder):
            subprocess.Popen(f'explorer /select,"{path}"')

    def _delete_file(self, tree):
        """Delete selected file with confirmation"""
        selection = tree.selection()
        if not selection:
            return

        count = len(selection)
        msg = f"Delete {count} item(s)?" if count > 1 else "Delete this item?"

        if messagebox.askyesno("Confirm Delete", msg):
            for item in selection:
                # Implementation depends on tree type
                # For now, just remove from display
                tree.delete(item)

    def _show_properties(self, tree):
        """Show item properties dialog"""
        selection = tree.selection()
        if not selection:
            return

        item = selection[0]
        values = tree.item(item)['values']
        # TODO: Implement properties dialog
        messagebox.showinfo("Properties", str(values))

    def _search_external(self, tree, source):
        """Search for ROM on external service"""
        selection = tree.selection()
        if not selection:
            return
        # Implementation
        pass

    def _download_rom(self, tree):
        """Download selected ROM"""
        selection = tree.selection()
        if not selection:
            return
        # Implementation
        pass
```

#### Step 2: Integrate into ROMManagerGUI

**File:** `rommanager/gui.py` - Modify class initialization

```python
# In ROMManagerGUI.__init__(), add:
from .ui_context_menus import TreeViewContextMenu

class ROMManagerGUI:
    def __init__(self):
        # ... existing code ...

        # Setup UI
        self._setup_theme()
        self._build_menu()
        self._build_ui()

        # NEW: Setup context menus
        self._setup_context_menus()

    def _setup_context_menus(self):
        """Initialize right-click context menus"""
        self.context_menus = TreeViewContextMenu(self)
        self.context_menus.bind_to_tree(self.id_tree, self.context_menus.id_menu)
        self.context_menus.bind_to_tree(self.un_tree, self.context_menus.un_menu)
        self.context_menus.bind_to_tree(self.ms_tree, self.context_menus.ms_menu)
```

#### Step 3: Test Implementation

**Testing Checklist:**
```
☐ Right-click on Identified ROM shows menu
☐ Right-click on Unidentified File shows menu
☐ Right-click on Missing ROM shows menu
☐ Right-click empty space shows nothing
☐ Menu options work (Copy Path, Open, Delete)
☐ Multi-select shows menu for last selected item
☐ Menu closes on selection
☐ Menu closes on click outside
```

---

## Phase 2: Keyboard Shortcuts & Multi-Select Feedback (Week 2)

### Goal: Add standard Windows keyboard shortcuts

### Implementation Steps

#### Step 1: Create Keyboard Handler

**File:** `rommanager/ui_keyboard_shortcuts.py` (new file)

```python
"""Keyboard shortcut handling for ROM Manager"""

import tkinter as tk

class KeyboardShortcutHandler:
    """Manages keyboard shortcuts and event handling"""

    def __init__(self, gui):
        self.gui = gui
        self._setup_shortcuts()

    def _setup_shortcuts(self):
        """Setup all keyboard shortcuts"""
        # Refresh operations
        self.gui.root.bind('<F5>', self._on_refresh)

        # Selection operations
        self.gui.root.bind('<Control-a>', self._on_select_all)
        self.gui.root.bind('<Control-Shift-a>', self._on_deselect_all)

        # Clipboard operations
        self.gui.root.bind('<Control-c>', self._on_copy)

        # Destructive operations
        self.gui.root.bind('<Delete>', self._on_delete)

        # File operations
        self.gui.root.bind('<Control-o>', self._on_organize)
        self.gui.root.bind('<Control-d>', self._on_download)

        # Navigation
        self.gui.root.bind('<Control-f>', self._on_focus_search)

    def _on_refresh(self, event=None):
        """F5: Refresh current tab"""
        tab_id = self.gui.notebook.index(self.gui.notebook.select())
        if tab_id == 0:  # Identified
            self.gui._refresh_identified()
        elif tab_id == 1:  # Unidentified
            pass  # Typically doesn't need refresh
        elif tab_id == 2:  # Missing
            self.gui._refresh_missing()

    def _on_select_all(self, event=None):
        """Ctrl+A: Select all items in current tree"""
        tree = self._get_active_tree()
        if tree:
            all_items = tree.get_children()
            tree.selection_set(all_items)
            self._update_selection_count(tree)

    def _on_deselect_all(self, event=None):
        """Ctrl+Shift+A: Deselect all items"""
        tree = self._get_active_tree()
        if tree:
            tree.selection_remove(tree.selection())
            self._update_selection_count(tree)

    def _on_copy(self, event=None):
        """Ctrl+C: Copy selected items"""
        tree = self._get_active_tree()
        if tree:
            selection = tree.selection()
            if selection:
                paths = []
                for item in selection:
                    values = tree.item(item)['values']
                    # Copy first column (usually filename/path)
                    paths.append(str(values[0]) if values else '')

                text = '\n'.join(paths)
                self.gui.root.clipboard_clear()
                self.gui.root.clipboard_append(text)

    def _on_delete(self, event=None):
        """Delete key: Delete selected items with confirmation"""
        tree = self._get_active_tree()
        if not tree:
            return

        selection = tree.selection()
        if not selection:
            return

        count = len(selection)
        from tkinter import messagebox
        msg = f"Delete {count} item(s)?" if count > 1 else "Delete this item?"

        if messagebox.askyesno("Confirm Delete", msg):
            for item in selection:
                tree.delete(item)

    def _on_organize(self, event=None):
        """Ctrl+O: Start organize operation"""
        self.gui._organize()

    def _on_download(self, event=None):
        """Ctrl+D: Download selected ROMs"""
        # Only works in Missing ROMs tab
        tab_id = self.gui.notebook.index(self.gui.notebook.select())
        if tab_id == 2:  # Missing ROMs tab
            self.gui._download_selected_missing()

    def _on_focus_search(self, event=None):
        """Ctrl+F: Focus search box"""
        # Find search widget and focus it
        # This requires storing reference to search entry
        pass

    def _get_active_tree(self):
        """Get currently active tree view"""
        tab_id = self.gui.notebook.index(self.gui.notebook.select())
        if tab_id == 0:
            return self.gui.id_tree
        elif tab_id == 1:
            return self.gui.un_tree
        elif tab_id == 2:
            return self.gui.ms_tree
        return None

    def _update_selection_count(self, tree):
        """Update selection count display"""
        count = len(tree.selection())
        # Update label or status bar
        # Requires adding selection_label to GUI
        pass
```

#### Step 2: Add Selection Count Display

**File:** `rommanager/gui.py` - Modify `_build_ui()`

```python
# In _build_ui(), after creating notebook, add:
def _build_ui(self):
    # ... existing code ...

    # Search
    sf = ttk.Frame(main)
    sf.pack(fill=tk.X, pady=(0, 5))
    ttk.Label(sf, text="Search:").pack(side=tk.LEFT)

    # NEW: Add selection count label
    self.selection_label = ttk.Label(sf, text="", foreground=self.colors['accent'])
    self.selection_label.pack(side=tk.RIGHT, padx=(0, 8))

    self._search_var = tk.StringVar()
    self._search_var.trace_add('write', self._on_search)
    ttk.Entry(sf, textvariable=self._search_var, width=40).pack(
        side=tk.LEFT, padx=(8, 0), fill=tk.X, expand=True)

    # ... rest of code ...
```

#### Step 3: Integrate Keyboard Handler

**File:** `rommanager/gui.py` - Modify initialization

```python
# In __init__(), add:
from .ui_keyboard_shortcuts import KeyboardShortcutHandler

class ROMManagerGUI:
    def __init__(self):
        # ... existing code ...

        # Setup keyboard shortcuts
        self.keyboard_handler = KeyboardShortcutHandler(self)
```

#### Step 4: Test Implementation

**Testing Checklist:**
```
☐ F5 refreshes current tab
☐ Ctrl+A selects all items
☐ Ctrl+Shift+A deselects all items
☐ Ctrl+C copies paths to clipboard
☐ Delete key removes selected items (with confirmation)
☐ Ctrl+O starts organize operation
☐ Ctrl+D downloads selected missing ROMs
☐ Ctrl+F focuses search box
☐ Selection count displays "X items selected"
☐ Selection count updates on item click
```

---

## Phase 3: Column Sorting (Week 3-4)

### Goal: Make column headers clickable and sortable

### Implementation Steps

#### Step 1: Create Sort Manager

**File:** `rommanager/ui_sorting.py` (new file)

```python
"""Column sorting functionality for tree views"""

import tkinter as tk
from typing import List, Tuple, Any

class TreeViewSortManager:
    """Manages column sorting for tree views"""

    def __init__(self, gui):
        self.gui = gui
        self.sort_state = {
            'identified': {'column': None, 'reverse': False},
            'unidentified': {'column': None, 'reverse': False},
            'missing': {'column': None, 'reverse': False},
        }

    def setup_sorting(self, tree, tab_name, columns):
        """Setup column headers as clickable sort controls"""
        for col_def in columns:
            col_id = col_def['id']
            tree.heading(
                col_id,
                text=col_def['label'],
                command=lambda c=col_id, t=tab_name: self._on_header_click(tree, t, c)
            )

    def _on_header_click(self, tree, tab_name, column):
        """Handle column header click for sorting"""
        state = self.sort_state[tab_name]

        # Toggle sort direction if same column clicked
        if state['column'] == column:
            state['reverse'] = not state['reverse']
        else:
            state['column'] = column
            state['reverse'] = False

        # Perform sort
        self._sort_tree(tree, column, state['reverse'])

        # Update sort indicators
        self._update_sort_indicators(tree, column, state['reverse'])

    def _sort_tree(self, tree, column, reverse=False):
        """Sort tree items by specified column"""
        # Get all items and their values
        items = []
        for item in tree.get_children(''):
            values = tree.item(item)['values']
            items.append((item, values))

        # Find column index
        col_index = self._get_column_index(tree, column)
        if col_index is None:
            return

        # Sort items
        try:
            # Try numeric sort first
            items.sort(
                key=lambda x: float(x[1][col_index]) if x[1] else 0,
                reverse=reverse
            )
        except (ValueError, TypeError):
            # Fall back to string sort
            items.sort(
                key=lambda x: str(x[1][col_index]).lower() if x[1] else '',
                reverse=reverse
            )

        # Reorder items in tree
        for idx, (item, values) in enumerate(items):
            tree.move(item, '', idx)

    def _get_column_index(self, tree, column_id):
        """Get index of column by ID"""
        columns = tree['columns']
        try:
            return list(columns).index(column_id)
        except ValueError:
            return None

    def _update_sort_indicators(self, tree, sorted_column, reverse):
        """Update column headers to show sort direction"""
        arrow = '▼' if not reverse else '▲'
        columns = tree['columns']

        for col_id in columns:
            heading_text = tree.heading(col_id)['text']

            # Remove existing arrow
            heading_text = heading_text.replace(' ▼', '').replace(' ▲', '')

            if col_id == sorted_column:
                # Add arrow to sorted column
                tree.heading(col_id, text=f'{heading_text} {arrow}')
            else:
                # Clear arrow from other columns
                tree.heading(col_id, text=heading_text)
```

#### Step 2: Integrate into GUI

**File:** `rommanager/gui.py` - Modify `_make_tree()` and related

```python
# In __init__(), add:
from .ui_sorting import TreeViewSortManager

class ROMManagerGUI:
    def __init__(self):
        # ... existing code ...
        self.sort_manager = TreeViewSortManager(self)

    def _build_ui(self):
        # ... existing code ...

        # In tab creation sections, add sorting setup:
        # After creating id_tree:
        self.sort_manager.setup_sorting(
            self.id_tree, 'identified', IDENTIFIED_COLUMNS)

        # After creating un_tree:
        self.sort_manager.setup_sorting(
            self.un_tree, 'unidentified', UNIDENTIFIED_COLUMNS)

        # After creating ms_tree:
        self.sort_manager.setup_sorting(
            self.ms_tree, 'missing', MISSING_COLUMNS)
```

#### Step 3: Test Implementation

**Testing Checklist:**
```
☐ Click column header to sort ascending
☐ Click same header again to sort descending
☐ Click different header to change sort column
☐ Sort arrow (▲▼) appears on sorted column
☐ Arrow toggles on repeated clicks
☐ Numeric columns sort numerically (size, CRC32)
☐ String columns sort alphabetically
☐ Sort state persists within session
☐ Multi-select preserved during sort
```

---

## Phase 4: Column Filtering (Week 4-5)

### Goal: Add filtering capability (optional advanced feature)

Implementation similar to sorting, but creates filter UI elements.

**Basic Filter Pattern:**
```python
# Simple filter for region column
region_values = set()
for item in tree.get_children():
    region = tree.item(item)['values'][region_col_index]
    region_values.add(region)

# Create filter UI
for region in sorted(region_values):
    tk.Checkbutton(filter_frame, text=region,
                  variable=region_vars[region]).pack()

# Apply filters
def apply_filters():
    for item in tree.get_children():
        region = tree.item(item)['values'][region_col_index]
        if region not in active_filters:
            tree.delete(item)  # Or hide, don't delete
```

---

## Phase 5: Tab State Persistence (Week 5+)

### Goal: Save and restore view state when switching tabs

```python
class TabStateManager:
    """Manages tab view state (scroll, selection, sort)"""

    def __init__(self):
        self.states = {
            'identified': {},
            'unidentified': {},
            'missing': {},
        }

    def save_state(self, tab_name, tree):
        """Save current view state"""
        self.states[tab_name] = {
            'scroll': tree.yview()[0],
            'selection': tree.selection(),
            'sort_column': # get from sort_manager
            'sort_reverse': # get from sort_manager
        }

    def restore_state(self, tab_name, tree):
        """Restore saved view state"""
        state = self.states[tab_name]
        tree.yview_moveto(state['scroll'])
        tree.selection_set(state['selection'])
        # Re-apply sort
```

---

## Integration Checklist

### Before Publishing

```
Basic Functionality:
☐ All three tree views have context menus
☐ All keyboard shortcuts work
☐ Multi-select shows count
☐ Column sorting works on all columns
☐ Sorting preserves selection where possible

Testing:
☐ No errors in console
☐ No crashes on rapid operations
☐ Memory usage stable (no leaks)
☐ Performance acceptable with 1000+ items

User Experience:
☐ Right-click menu appears in expected location
☐ Keyboard shortcuts match Windows standard
☐ Sort indicators are clear
☐ Selection feedback is visible
☐ All operations complete without hang

Documentation:
☐ User documentation updated with new features
☐ Keyboard shortcuts listed in Help menu
☐ Tooltips added to new UI elements
```

---

## File Organization

**Recommended module structure after implementation:**

```
rommanager/
├── gui.py                      (Main GUI, orchestrates modules)
├── ui_context_menus.py         (Context menu handlers)
├── ui_keyboard_shortcuts.py    (Keyboard shortcut handler)
├── ui_sorting.py               (Column sorting)
├── ui_filtering.py             (Column filtering - optional)
├── ui_state_management.py      (Tab state persistence - optional)
├── shared_config.py            (Column definitions, colors)
├── models.py                   (Data models)
└── ...other modules
```

---

## Common Implementation Issues & Solutions

### Issue: Sorting breaks tree widget structure
**Solution:** Store original item IDs, restore them after sort

### Issue: Selection lost after sort
**Solution:** Save selected item IDs, restore selection after sort

### Issue: Context menu appears but items don't work
**Solution:** Verify tree.selection() returns correct item IDs

### Issue: Keyboard shortcuts conflict with system shortcuts
**Solution:** Test thoroughly on different OS, adjust as needed

### Issue: Multiple menus interfere with each other
**Solution:** Bind each menu to its specific tree, check focus

### Issue: Sort indicator arrow doesn't update
**Solution:** Call tree.heading() with text parameter, verify string update

---

## Performance Considerations

**For large collections (1000+ ROMs):**

```
Sorting:
- Current approach: Re-sort entire tree on column click
- Better approach: Keep sorted data in memory, update display
- For 10,000 items: Should complete in <500ms

Filtering:
- Current approach: Hide/show items
- Better approach: Maintain separate filtered list
- For 10,000 items: Filter update in <100ms

Context menus:
- Load only when needed (on right-click)
- Minimal performance impact

Keyboard shortcuts:
- All shortcuts should be instant (<50ms)
- Use select_all efficiently (avoid loop)
```

---

## Keyboard Shortcut Reference

**Final Recommended Shortcuts:**

| Shortcut | Action | Tab |
|----------|--------|-----|
| F5 | Refresh current tab | All |
| Ctrl+A | Select all items | All |
| Ctrl+Shift+A | Deselect all | All |
| Ctrl+C | Copy selected paths | All |
| Delete | Delete selected items | All |
| Ctrl+O | Open Organize dialog | All |
| Ctrl+D | Download selected | Missing |
| Ctrl+F | Focus search box | All |
| Ctrl+S | Save collection | All |
| Alt+F4 | Close application | All |

---

## Summary

This implementation guide provides a structured approach to modernizing ROM Manager's interface with proven Windows Explorer patterns. Start with Phase 1 (context menus) for immediate impact, then progress through subsequent phases based on user feedback and development capacity.

The modular approach allows each feature to be developed, tested, and deployed independently, minimizing risk and enabling iterative improvement.
