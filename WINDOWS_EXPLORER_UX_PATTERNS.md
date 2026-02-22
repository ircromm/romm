# Windows Explorer UX/UI Patterns for ROM Manager

A comprehensive guide to applying Windows Explorer's proven interface patterns to ROM Manager. These patterns reflect decades of refinement in file/collection management UX and are directly applicable to ROM management workflows.

---

## 1. Context Menu (Right-Click) Functionality

### Windows Explorer Pattern
Windows Explorer's right-click menu is hierarchical, lazy-loaded, and context-aware:
- Primary actions appear first (Copy, Cut, Delete, Rename)
- Secondary actions are grouped in submenus (Send To, Open With, Properties)
- System-provided actions (virus scan, compress) appear conditionally
- Menu length is managed through grouping and submenus

### ROM Manager Application

**Current State:**
- ROM Manager relies on toolbar buttons and menu bar actions
- No right-click context menus in the three tree views (Identified, Unidentified, Missing)

**Recommended Context Menu Patterns by Tab:**

#### Identified ROMs Tab - Right-Click Menu
```
┌─ Copy File Path
├─ Open in File Explorer
├─ Open File with Emulator
├─ Copy ROM Details ──→ [Name]
│                        [Name + System]
│                        [Full details as JSON]
├─ Export ───────────→ [Copy to Clipboard]
│                      [Save to File...]
├─ Edit Entry ────────→ [Rename...]
│                      [Change Status...]
│                      [Reassign to Game...]
├─ Remove ───────────→ [Delete File]
│                      [Remove from List (keep file)]
└─ Properties...
```

**Implementation Rationale:**
- Opens frequently-needed actions without switching focus to file explorer
- Supports bulk operations via multi-select
- "Remove" submenu prevents accidental deletion (Windows Explorer pattern)
- Avoids cluttering main toolbar

#### Unidentified Files Tab - Right-Click Menu
```
┌─ Show in File Explorer
├─ Copy File Details ──→ [Filename only]
│                        [Full path]
│                        [CRC32]
├─ Force Identify... ──→ [Select from database...]
│                        [Manual Entry...]
├─ Delete File ────────→ [Confirm]
└─ Properties...
```

**Implementation Rationale:**
- Focus on identification workflow
- Path operations prominent (users often need to locate these files)
- Delete as a cautious submenu (prevents accidental clicks)

#### Missing ROMs Tab - Right-Click Menu
```
┌─ Copy Download Info ──→ [ROM Name]
│                        [Game Name]
│                        [System + Region]
├─ Download ────────────→ [From Myrient...]
│                        [Search Archive.org...]
│                        [Search Custom URL...]
├─ Copy Search Query ───→ [Game Name]
│                        [ROM Name]
│                        [Custom format...]
└─ Mark as Excluded ────→ [Exclude from reports]
```

**Implementation Rationale:**
- Download actions immediately visible
- Copy options support external searching
- Exclusion workflow visible at point of need

### Multi-Select Behavior
When multiple items are selected:
```
┌─ Batch Operations ───→ [Copy All (preserve structure)]
│                       [Move to Folder...]
│                       [Export List...]
├─ Download Selected ──→ [All visible sources]
├─ Delete Selected ────→ [With confirmation]
└─ Properties...
```

---

## 2. Column Sorting & Filtering Behavior

### Windows Explorer Pattern
- Click column header to sort ascending/descending
- Indicator arrow shows sort direction (▲▼)
- Multiple columns sortable (Ctrl+Click secondary columns) - advanced feature
- Filter typically accessed via dropdown or toolbar
- Sort state persists within session
- Defaults to sensible primary sort (Name, Date Modified)

### ROM Manager Current Implementation
- Treeview columns defined in `shared_config.py`
- **No sorting or filtering currently implemented**

**Identified ROMs Columns (Current):**
```
Original File | ROM Name | Game | System | Region | Size | CRC32 | Status
```

### Recommended Sorting Implementation

**Primary Sort Columns by Tab:**
```
Identified ROMs:
  ├─ Default: By Game Name (alphabetical)
  ├─ Secondary options: System → Region → Game Name
  └─ Display: Arrow indicator (▲ ascending, ▼ descending)

Unidentified Files:
  ├─ Default: By Filename (alphabetical)
  ├─ Secondary: By Size (largest first)
  └─ Display: Clear visual indicator

Missing ROMs:
  ├─ Default: By System → Game Name
  ├─ Secondary: By Region (completion tracking)
  └─ Display: Visual sort direction indicator
```

**Sorting UI Pattern:**
```
┌─ Identified ROMs Tab ────────────────────────────────┐
│                                                       │
│ Original File ▼ | ROM Name | Game ▲ | System | ... │
│                                                       │
│ When user clicks "Game" column header:              │
│ 1. Toggle sort direction (↑ ↓)                      │
│ 2. Refresh tree view (tkinter Treeview limitation) │
│ 3. Maintain selection if possible                   │
│                                                       │
│ Option: Add sort dropdown in toolbar ↓              │
│   Sort By: [Game ▼] [System ▼] [Region ▼]         │
└─────────────────────────────────────────────────────┘
```

### Recommended Filtering Implementation

**Filter Locations (Windows Explorer Pattern):**

1. **Search Bar (Already Implemented)**
   - Current: Real-time filtering as user types
   - Enhance: Add filter breadcrumb showing active filters
   ```
   Search: [━━━━━] ✕ Active Filters: USA • Identified [×]
   ```

2. **Column-Based Filtering (Add)**
   - Access via: Right-click column header or filter icon
   ```
   System column header [▼] → Shows:
     ☑ NES
     ☑ SNES
     ☑ Genesis
     ☑ All (default)

   Region column header [▼] → Shows:
     ☑ USA
     ☑ Europe
     ☑ Japan
     ☑ All (default)
   ```

3. **Quick Filter Buttons in Toolbar**
   ```
   [Status: All ▼] [Region: All ▼] [System: All ▼] [Clear Filters]
   ```

**Filter Persistence Pattern:**
```
Session-level persistence:
├─ Save filter state when user switches tabs
├─ Restore filters when user returns to tab
├─ Show "Filters Active" badge on tab name
└─ Clear button always visible when filters applied

Example tab with active filters:
  "Identified ROMs (2 filters active)" [×]
```

---

## 3. Selection Models (Single, Multi-Select)

### Windows Explorer Pattern
- **Default:** Single-click selects item, highlights row
- **Ctrl+Click:** Toggle individual item selection
- **Shift+Click:** Range selection (from last selected to clicked item)
- **Ctrl+A:** Select all
- **Arrow keys:** Navigate selection up/down
- **Space:** Toggle selected item
- **Visual feedback:** Selected items highlighted with accent color

### ROM Manager Implementation

**Current State:**
- Treeview selection is functional but underutilized
- Only individual selections used for single operations

**Recommended Multi-Select Pattern:**

```
Keyboard Shortcuts (Windows Standard):
├─ Click                → Single select (deselect others)
├─ Ctrl+Click           → Toggle item selection
├─ Shift+Click          → Range select
├─ Ctrl+A               → Select all items
├─ Arrow Up/Down        → Navigate selection
├─ Space                → Toggle current item
├─ Delete               → Delete selected (with confirmation)
├─ Ctrl+C               → Copy selection (paths/names)
└─ Ctrl+Shift+C         → Copy selection (full details)

Visual Feedback:
├─ Selected items: Highlighted with accent color (#89b4fa)
├─ Selection count badge: "3 items selected"
├─ Context toolbar: Shows count and available bulk actions
└─ Multi-select mode: Displays checkboxes (optional refinement)
```

**Multi-Select UI Implementation:**

```python
# Tkinter Treeview enhancement pattern
def _on_treeview_select(event):
    """Handle multi-select with keyboard modifiers"""
    selection = tree.selection()

    if event.state & 0x4:  # Ctrl key
        # Toggle selection
        if item in selection:
            tree.selection_remove(item)
        else:
            tree.selection_add(item)
    elif event.state & 0x1:  # Shift key
        # Range select
        first_idx = tree.selection()[0] if selection else None
        current_idx = # Get clicked item index
        # Select range between first and current
    else:
        # Single select
        tree.selection_set(item)

    update_selection_feedback()
```

**Multi-Select Action Bar Pattern:**
```
┌──────────────────────────────────────────────────────────┐
│ ☐ Select All   3 ROMs selected  [Download ▼] [Delete ▼] │
└──────────────────────────────────────────────────────────┘
```

---

## 4. Button Placement Strategies

### Windows Explorer Pattern
Windows uses a hierarchical button placement strategy:

1. **Ribbon/Toolbar (Primary Actions):**
   - Most common operations with icons
   - Organized by workflow (Copy, Move, Delete, etc.)
   - Context-sensitive (shows/hides based on selection)

2. **Right-Click Context Menu (Secondary Actions):**
   - Less frequent but task-specific
   - Nested submenus for related operations

3. **Status Bar (Tertiary Info):**
   - Stats, counts, info messages
   - No interactive buttons typically

4. **Dialog Windows (Settings/Bulk Actions):**
   - Complex configurations
   - Confirmation for destructive actions

### ROM Manager Application

**Current Architecture Analysis:**

```
GUI Layout:
├─ Menu Bar
│  ├─ File (Save, Open, Recent, Exit)
│  ├─ DATs (DAT Library)
│  ├─ Export (TXT, CSV, JSON)
│  └─ Downloads (Myrient, Archive.org)
│
├─ Top Panel (DATs + Scan)
│  ├─ [Add DAT] [Remove] [Library...]
│  └─ [Browse...] [Scan] [with checkboxes]
│
├─ Search Bar
│  └─ [Search input field]
│
├─ Tabs with Tab-Specific Toolbars
│  ├─ Identified ROMs (no toolbar)
│  ├─ Unidentified Files
│  │  └─ [Force to Identified]
│  └─ Missing ROMs
│     └─ [Refresh] [Search Archive] [Download All] [Download Selected]
│
└─ Organization Panel (Bottom)
   ├─ Strategy selection
   ├─ [Browse...] [Preview] [Organize!] [Undo]
   └─ Action selection (Copy/Move)
```

**Recommended Button Placement Improvements:**

### Pattern 1: Toolbar-Based Organization (Recommended)

```
Primary Toolbar (Always Visible):
├─ [⟲ Refresh] [⚙ Settings] | [📊 Stats] | [🔍 Advanced Filter ▼]
├─ [+ Add] [- Remove] [✎ Rename] | [↓ Download] [⊠ Delete]
└─ Additional context-specific buttons appear here

Tab-Specific Toolbars:
├─ Identified ROMs:
│  └─ [Open File] [Open Folder] | [Export...▼] [Properties]
│
├─ Unidentified Files:
│  └─ [Show in Explorer] | [🆔 Identify...▼] [Delete ▼]
│
└─ Missing ROMs:
   └─ [📋 Copy List▼] | [↓ Download ▼] [Search...▼]
```

### Pattern 2: Action Grouping (Windows Explorer Model)

```
Organize your buttons into logical groups with separators:

File Operations Group:
  [Open] [Open Folder] [Show in Explorer]

Edit Operations Group:
  [Copy] [Cut] [Paste] [Delete]

View Operations Group:
  [Sort ▼] [Filter ▼] [Columns ▼]

Batch Operations Group:
  [Select All] [Invert Selection] [Clear Selection]

Tool-Specific Group (per tab):
  [Identify...] [Download...] [Organize...] [Preview]
```

### Pattern 3: Floating Context Toolbar

```
When items selected, show a floating toolbar:

┌─────────────────────────────────────────────┐
│ 3 items selected                  [× Close] │
├─────────────────────────────────────────────┤
│ [Download] [Delete] [Export...] [More ▼]   │
└─────────────────────────────────────────────┘

Advantages:
- Appears only when needed
- Doesn't clutter the static UI
- Clearly shows selection count
- Keyboard accessible (Tab/Enter)
```

### Button Placement Best Practice Examples

**Poor Placement (Current Issues):**
```
Missing ROMs Tab - Buttons scattered on right side:
┌──────────────────────────────────────────────────┐
│ [Refresh] [Search Archive...] [Download Selected] │ <- All right-aligned
│ [Download All Missing]                            │ <- Wraps awkwardly
└──────────────────────────────────────────────────┘
```

**Improved Placement (Logical Grouping):**
```
Missing ROMs Tab - Logical grouping:
┌──────────────────────────────────────────────────┐
│ Completeness: 45/200 (22%)                       │
├──────────────────────────────────────────────────┤
│ [Search ▼] [Download ▼] [Export...] [×] Clear   │
└──────────────────────────────────────────────────┘

Groups (left to right):
  1. Search operations
  2. Download operations
  3. Export/reporting operations
  4. Filtering operations
```

---

## 5. Common Patterns for File/List Operations

### Windows Explorer File Operation Patterns

**Copy/Move Operations:**
```
Windows Pattern:
1. Select files
2. Right-click → Copy or Cut
3. Navigate to destination
4. Right-click → Paste
5. Status: Shows operation progress

Problems avoided:
- No accidental overwrites (prompts if exists)
- Undo available after paste
- Can cancel in-progress operations
- Progress shown during large operations
```

**Delete Operations:**
```
Windows Pattern (with Shift+Delete):
1. Select items
2. Press Delete key
3. Confirmation dialog appears
4. Option: Send to Recycle Bin (soft delete)
5. Option: Permanently delete (hard delete)
6. Operation proceeds with progress bar

Safety Features:
- Always confirm before delete
- Show what will be deleted
- Option to recycle vs. permanent
- Progress indicator for large operations
```

### ROM Manager Application Mapping

**Current Operations:**
```
Organize! Operation:
├─ Select strategy (1G1R, By System, etc.)
├─ Select output folder
├─ Preview operation
├─ Confirm with [Organize!] button
├─ Operation runs with progress bar
└─ Undo available

Download Operation:
├─ Select ROMs in Missing tab
├─ Click [Download Selected] or [Download All]
├─ Configure download settings
├─ Download proceeds
└─ Progress shown
```

**Recommended Enhancements:**

1. **Add Verification Step Pattern**
```
Workflow:
  [Organize!] → Preview → Review List → Confirm

Current code supports _preview() already, enhance it:
  - Show total items to organize
  - Show destination structure preview
  - Show potential conflicts/overwrites
  - Allow "Proceed" or "Cancel"
```

2. **Batch Operation Feedback**
```
Pattern used by Windows:
├─ Selection count visible
├─ Operation details in tooltip
├─ Progress indicator with item count
├─ Cancel button during operation
├─ Completion summary with counts

ROM Manager missing:
└─ Progress shows percentage, not item count
    Recommendation: "Organizing 150/342 ROMs (44%)"
```

3. **Multi-File Delete Confirmation**
```
Pattern:
┌────────────────────────────────────┐
│ Delete Items?                      │
├────────────────────────────────────┤
│ You are about to delete:           │
│ ☑ super_mario_bros.nes             │
│ ☑ super_mario_bros_2.nes           │
│ ... and 3 more items               │
│                                    │
│ This action cannot be undone.      │
│ [Cancel] [Delete]                  │
└────────────────────────────────────┘
```

---

## 6. Button Redundancy Patterns

### Windows Explorer Button Distribution

Windows deliberately provides the same operations in multiple locations:

**Common Action: Copy File**
```
1. Right-click context menu → "Copy"
2. Edit menu → "Copy"
3. Toolbar icon [Copy button]
4. Keyboard shortcut: Ctrl+C

Rationale:
- Power users: Use keyboard
- Mouse users: Use toolbar or menu
- Discovery: Users learn via context menu
- Accessibility: Multiple paths to same goal
```

**Windows Explorer Common Operations (Multi-Path Access):**
```
Delete:
  ├─ Right-click → Delete
  ├─ Edit menu → Delete
  ├─ Delete key (keyboard)
  └─ Toolbar [Delete button]

Rename:
  ├─ Right-click → Rename
  ├─ File menu → Rename
  ├─ F2 key (keyboard)
  └─ Inline edit (click file name slowly)

Refresh:
  ├─ Toolbar [Refresh button]
  ├─ View menu → Refresh
  └─ F5 key (keyboard)

Select All:
  ├─ Edit menu → Select All
  └─ Ctrl+A (keyboard)
```

### ROM Manager Recommended Redundancy

**High-Value Operations to Duplicate:**

1. **Download Missing**
```
Current paths:
  ├─ Menu: Downloads → Download Missing ROMs...
  └─ Button: [Download All Missing] (Missing tab only)

Recommended additions:
  ├─ Right-click missing ROM → Download
  ├─ Keyboard shortcut: Ctrl+Shift+D
  ├─ Toolbar button (main)
  └─ Tab context menu
```

2. **Refresh Missing List**
```
Current paths:
  └─ Button: [Refresh] (Missing tab toolbar)

Recommended additions:
  ├─ Right-click empty space → Refresh
  ├─ Keyboard shortcut: F5
  ├─ Menu: View → Refresh
  └─ Auto-refresh option in settings
```

3. **Delete/Remove**
```
Current paths:
  └─ Button: [Remove] (DAT panel)

Recommended for ROMs:
  ├─ Right-click → Delete File
  ├─ Delete key (keyboard)
  ├─ Menu: Edit → Delete
  ├─ Toolbar button (context-specific)
  └─ With confirmation dialog
```

4. **Organize ROMs**
```
Current paths:
  └─ Button: [Organize!] (Organization panel)

Recommended additions:
  ├─ Right-click selected ROM → Organize...
  ├─ Keyboard shortcut: Ctrl+O
  ├─ Menu: File → Organize...
  └─ Toolbar button (main toolbar)
```

### Button Redundancy Matrix

```
Operation          | Toolbar | Menu  | Right-Click | Keyboard | Inline
─────────────────┼─────────┼───────┼─────────────┼──────────┼────────
Scan             | ✓       | ✓     |             | F3       |
Organize         | ✓       | ✓     | ✓           | Ctrl+O   |
Download Missing | ✓       | ✓     | ✓           | Ctrl+D   |
Refresh          | ✓       | ✓     | ✓           | F5       |
Delete           | ✓       | ✓     | ✓           | Del      |
Rename           |         | ✓     | ✓           | F2       | ✓
Open File        | ✓       | ✓     | ✓           |          |
Properties       |         | ✓     | ✓           | Alt+Ret  |
Select All       |         | ✓     |             | Ctrl+A   |
Export           |         | ✓     | ✓           |          |
```

**Recommended Keyboard Shortcuts:**
```
File Operations:
  Ctrl+O          → Open file/folder
  Ctrl+S          → Save collection
  Ctrl+E          → Export...

Navigation:
  F5              → Refresh current tab
  Ctrl+F          → Focus search box
  Ctrl+Tab        → Next tab
  Ctrl+Shift+Tab  → Previous tab

Selection:
  Ctrl+A          → Select all
  Ctrl+Shift+A    → Deselect all

Bulk Operations:
  Ctrl+D          → Download selected
  Ctrl+Shift+D    → Download all missing
  Ctrl+O          → Organize selected
  Del             → Delete selected
```

---

## 7. Tab Organization Best Practices

### Windows Explorer Tab Pattern (Modern)

Windows 11 file explorer uses a tab-based model:
```
┌─────────────────────────────────────────────────────┐
│ [⊞ Home] [📁 Desktop] [+] [Home ▼]                  │
├─────────────────────────────────────────────────────┤
│ Breadcrumb: Home > Documents > Projects             │
└─────────────────────────────────────────────────────┘

Tab Features:
- Each tab maintains independent state (navigation, sorting)
- Close button (×) on each tab
- Drag-to-reorder tabs
- Right-click tab → Duplicate, Close, Properties
- "+" button to add new tab
- Tab groups (pinned tabs stay visible)
```

### ROM Manager Tab Implementation (Current)

**Current State (tkinter Notebook):**
```
┌─ Identified ROMs | Unidentified Files | Missing ROMs ─┐
├────────────────────────────────────────────────────────┤
│ [Tree view with identified ROMs]                       │
│ - 342 items identified                                 │
│ - Columns: Original File, ROM Name, Game, System, etc. │
└────────────────────────────────────────────────────────┘
```

### Recommended Tab Organization Improvements

**Tab Architecture (Logical Grouping):**

```
Level 1: Collection Tabs (main workflow)
├─ [⊞ Scan & Identify]
│  ├─ Identified ROMs
│  ├─ Unidentified Files
│  └─ Search/Filter across both
│
├─ [📥 Missing ROMs]
│  ├─ Complete ROM list
│  ├─ Download status
│  └─ Search/Filter
│
├─ [📂 Organization]
│  ├─ Strategy selection
│  ├─ Preview
│  ├─ Output path
│  └─ Action history/undo
│
└─ [⚙ Settings & Reports]
   ├─ Preferences
   ├─ Report generation
   └─ DAT management

Visual representation:
┌─────────────────────────────────────────────────────────┐
│ [🔍 Scan & Identify] [📥 Missing] [📂 Organize] [⚙ More] │
├─────────────────────────────────────────────────────────┤
│ Sub-tabs: [Identified ✓] [Unidentified ⚠] [Search]      │
└─────────────────────────────────────────────────────────┘
```

**Alternative: Flat Tab Model (Current, Simplified)**

Keep current 3-tab model but enhance:

```
┌──────────────────────────────────────────────────────────┐
│ [Identified ROMs ✓] [Unidentified Files ⚠] [Missing 📥]  │
│                     (1,847)      (23)         (155)       │
├──────────────────────────────────────────────────────────┤
│ Toolbar (tab-specific)                                   │
│ [Action buttons relevant to this tab]                    │
├──────────────────────────────────────────────────────────┤
│ [Tree view content]                                      │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### Tab-Specific Features Recommendation

**Tab Status Indicators:**
```
[Identified ROMs ✓]     - Green checkmark: all processed
[Unidentified Files ⚠]  - Warning triangle: action needed
[Missing ROMs 📥]       - Download icon: download available

Sub-counts visible:
[Identified (1,847)] [Unidentified (23)] [Missing (155)]
```

**Tab-Switching Behavior (Windows Explorer Model):**
```
When switching tabs:
1. Save current tab state (scroll position, selection)
2. Restore previous tab state when returning
3. Show loading spinner if tab requires refresh
4. Display toolbar appropriate to tab
5. Update main menu options based on active tab

Example: Switch from Identified → Unidentified
- Identified: Save view state, scroll position
- Unidentified: Restore previous view state
- Toolbar changes: Remove [Open File], add [Identify...]
- Menu items: "Edit" menu shows context-appropriate options
```

**Tab Right-Click Menu (Enhancement):**
```
┌─ Close Tab
├─ Close Other Tabs
├─ Close All Tabs
├─ Duplicate Tab
├─ Pin Tab (always visible)
├─ Reload Tab
├─ Clear Tab Filters
└─ Tab Properties (stats)
```

### Multi-Tab State Management Pattern

```python
# Pseudo-code pattern for tab state management
class TabStateManager:
    def __init__(self):
        self.tab_states = {
            'identified': {
                'scroll_position': 0,
                'selection': [],
                'sort_column': 'game_name',
                'sort_direction': 'asc',
                'filter': {},
                'columns_visible': [...],
            },
            'unidentified': { ... },
            'missing': { ... },
        }

    def save_tab_state(self, tab_name):
        """Save current tab's view state"""
        state = self.tab_states[tab_name]
        state['scroll_position'] = tree.yview()[0]
        state['selection'] = tree.selection()
        state['sort_column'] = current_sort_column
        # ... save other state

    def restore_tab_state(self, tab_name):
        """Restore saved view state when returning to tab"""
        state = self.tab_states[tab_name]
        tree.yview_moveto(state['scroll_position'])
        tree.selection_set(state['selection'])
        apply_sort(state['sort_column'], state['sort_direction'])
        # ... restore other state
```

### Recommended Tab Panel Structure

```
┌─ Top Level Tabs ────────────────────────────────────────┐
│ [Scan & Identify] [Missing] [Organize] [More ▼]         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ ┌─ Sub-Level Tabs (only in Scan & Identify) ──────────┐ │
│ │ [Identified ✓] [Unidentified ⚠]                     │ │
│ ├─────────────────────────────────────────────────────┤ │
│ │                                                     │ │
│ │ [Tab-specific toolbar]                             │ │
│ │ [Treeview content]                                 │ │
│ │                                                     │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 8. Design Consistency Checklist

### Visual Consistency Patterns

```
Color Usage (Current Implementation):
├─ Background: #1e1e2e (dark gray)
├─ Foreground: #cdd6f4 (light gray)
├─ Accent: #89b4fa (blue)
├─ Success: #a6e3a1 (green)
├─ Warning: #f9e2af (yellow)
├─ Error: #f38ba8 (red)
└─ Region colors: Standardized in shared_config.py

Consistency opportunities:
├─ Button hover states (slightly lighter accent)
├─ Selected items: Consistent accent highlight
├─ Disabled items: Reduced opacity (50%)
├─ Borders: Subtle, use accent for focus
└─ Icons: Match style (consider Font Awesome or similar)
```

### Spacing & Layout Patterns

```
Windows Explorer Standard:
├─ Standard margins: 10-12px
├─ Padding inside containers: 8px
├─ Gap between button groups: 5px (small) or 15px (large)
├─ Vertical spacing between sections: 10-15px
└─ Row heights: 24-28px (for list items)

ROM Manager Current:
├─ Main padding: 10px ✓
├─ Section gaps: Inconsistent (needs standardization)
└─ Row heights: ~20px (tkinter default, adequate)
```

### Icon & Label Patterns

```
Toolbar Icons (Recommended):
├─ Size: 16x16 or 24x24 (consistent)
├─ Style: Monochrome with accent color
├─ Labels: Icon + text for primary buttons
├─ Tooltips: Available on hover
├─ Disabled state: Reduced opacity

Label Patterns:
├─ Button labels: Verb + noun (Download, Organize, Delete)
├─ Field labels: Noun only (System, Region, Size)
├─ Status labels: Clear and concise
└─ Error messages: Begin with Icon + clear description
```

---

## 9. Accessibility & Keyboard Navigation

### Windows Explorer Accessibility Patterns

```
Keyboard Navigation:
├─ Tab key: Cycles through focusable elements
├─ Arrow keys: Navigate list items
├─ Space: Select/deselect
├─ Enter: Open/confirm
├─ Escape: Cancel dialog or close menu
├─ Alt+key: Access menu items
└─ Function keys: Common operations (F5 refresh)

ROM Manager Enhancements Needed:
├─ Keyboard focus indicators (visible outline)
├─ Tab order in dialogs (logical flow)
├─ Screen reader support (label associations)
└─ High contrast mode support
```

### Recommended Keyboard Shortcut Implementation

```python
# tkinter keyboard binding pattern
def _setup_keyboard_bindings(self):
    """Setup Windows Explorer-style keyboard shortcuts"""
    # File operations
    self.root.bind('<Control-s>', lambda e: self._save_collection())
    self.root.bind('<Control-o>', lambda e: self._organize())

    # Navigation
    self.root.bind('<F5>', lambda e: self._refresh_current_tab())
    self.root.bind('<Control-f>', lambda e: self._focus_search())

    # Selection
    self.root.bind('<Control-a>', lambda e: self._select_all())
    self.root.bind('<Control-Shift-a>', lambda e: self._deselect_all())

    # Delete
    self.root.bind('<Delete>', lambda e: self._delete_selected())

    # Bulk operations
    self.root.bind('<Control-d>', lambda e: self._download_selected())
    self.root.bind('<Control-Shift-d>', lambda e: self._download_all_missing())
```

---

## Implementation Priority

### Phase 1: High-Impact, Low-Effort (Start Here)

1. **Context Menus**
   - Add right-click menus to tree views
   - Most commonly expected by users
   - Effort: Medium (1-2 days)
   - Impact: High (discovery, efficiency)

2. **Keyboard Shortcuts**
   - Add F5 (refresh), Ctrl+D (download), Delete key
   - Quick wins, high user satisfaction
   - Effort: Low (4-6 hours)
   - Impact: High (power users)

3. **Multi-Select Support**
   - Enhance selection feedback
   - Show count ("3 items selected")
   - Effort: Low-Medium (1 day)
   - Impact: Medium (common workflow)

### Phase 2: Medium-Impact, Medium-Effort (Next)

1. **Column Sorting**
   - Clickable column headers
   - Sort direction indicators
   - Effort: Medium (2-3 days)
   - Impact: High (data exploration)

2. **Advanced Filtering**
   - Column-based filters
   - Filter state persistence
   - Effort: Medium (2-3 days)
   - Impact: Medium (large collections)

3. **Button Organization**
   - Reorganize toolbar layout
   - Add visual grouping
   - Effort: Medium (1-2 days)
   - Impact: Medium (usability)

### Phase 3: Polish (Later)

1. **Tab Enhancements**
   - Tab state persistence
   - Tab right-click menu
   - Effort: Medium-High (2-3 days)
   - Impact: Low-Medium (nice-to-have)

2. **Advanced Context Menus**
   - Submenus with bulk operations
   - Dynamic menu generation
   - Effort: Medium (2 days)
   - Impact: Medium (power users)

3. **Floating Context Toolbar**
   - Shows on multi-select
   - Dynamic button availability
   - Effort: High (3-4 days)
   - Impact: Medium (modern feel)

---

## Code Examples

### Example 1: Basic Context Menu Implementation

```python
import tkinter as tk
from tkinter import ttk

class TreeViewWithContextMenu:
    def __init__(self, parent, columns):
        self.tree = ttk.Treeview(parent, columns=columns)
        self.tree.pack(fill=tk.BOTH, expand=True)

        # Create context menu
        self.context_menu = tk.Menu(self.tree, tearoff=0)
        self.context_menu.add_command(label="Copy Path", command=self._copy_path)
        self.context_menu.add_command(label="Open File", command=self._open_file)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Delete", command=self._delete_item)

        # Bind right-click
        self.tree.bind("<Button-3>", self._show_context_menu)

    def _show_context_menu(self, event):
        """Show context menu at click location"""
        # Select item at click location
        item = self.tree.identify('item', event.x, event.y)
        if item:
            self.tree.selection_set(item)
            # Show menu at cursor position
            self.context_menu.tk_popup(event.x_root, event.y_root)

    def _copy_path(self):
        selection = self.tree.selection()
        if selection:
            item = selection[0]
            path = self.tree.item(item)['values'][0]
            self.tree.clipboard_clear()
            self.tree.clipboard_append(path)

    def _open_file(self):
        # Implementation
        pass

    def _delete_item(self):
        # Implementation
        pass
```

### Example 2: Multi-Select with Visual Feedback

```python
def _setup_multiselect(self):
    """Enable multi-select with visual feedback"""
    self.tree.bind('<Button-1>', self._on_tree_click)
    self.tree.bind('<Control-Button-1>', self._on_tree_ctrl_click)
    self.tree.bind('<Shift-Button-1>', self._on_tree_shift_click)
    self.tree.bind('<Control-a>', self._select_all_items)
    self.tree.bind('<Delete>', self._delete_selected)

def _on_tree_click(self, event):
    """Single click: select single item"""
    item = self.tree.identify('item', event.x, event.y)
    if item:
        self.tree.selection_set(item)
        self._update_selection_count()

def _on_tree_ctrl_click(self, event):
    """Ctrl+click: toggle item selection"""
    item = self.tree.identify('item', event.x, event.y)
    if item:
        if item in self.tree.selection():
            self.tree.selection_remove(item)
        else:
            self.tree.selection_add(item)
        self._update_selection_count()

def _on_tree_shift_click(self, event):
    """Shift+click: range select"""
    item = self.tree.identify('item', event.x, event.y)
    if item and self.tree.selection():
        # Get all items between first selected and clicked
        all_items = self.tree.get_children()
        first_idx = all_items.index(self.tree.selection()[0])
        current_idx = all_items.index(item)

        start = min(first_idx, current_idx)
        end = max(first_idx, current_idx) + 1

        self.tree.selection_set(all_items[start:end])
        self._update_selection_count()

def _update_selection_count(self):
    """Show selection count"""
    count = len(self.tree.selection())
    self.selection_label.config(text=f"{count} items selected")
```

### Example 3: Column Sorting

```python
class SortableTreeview:
    def __init__(self, parent, columns):
        self.tree = ttk.Treeview(parent, columns=[c['id'] for c in columns])
        self.columns_def = columns
        self.sort_column = None
        self.sort_reverse = False

        # Setup column headers with click handlers
        for col in columns:
            self.tree.heading(col['id'], text=col['label'],
                            command=lambda c=col['id']: self._sort_column(c))
            self.tree.column(col['id'], width=col['width'])

    def _sort_column(self, column):
        """Sort by column when header clicked"""
        # Toggle sort direction if same column clicked
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = False

        # Get data and sort
        items = [(self.tree.item(item)['values'], item)
                for item in self.tree.get_children('')]

        col_index = [c['id'] for c in self.columns_def].index(column)

        items.sort(key=lambda x: x[0][col_index],
                  reverse=self.sort_reverse)

        # Reorder items
        for idx, (values, item) in enumerate(items):
            self.tree.move(item, '', idx)

        # Update column header indicator
        self._update_sort_indicator()

    def _update_sort_indicator(self):
        """Show sort direction indicator in header"""
        for col in self.columns_def:
            col_id = col['id']
            if col_id == self.sort_column:
                arrow = '▼' if not self.sort_reverse else '▲'
                self.tree.heading(col_id, text=f"{col['label']} {arrow}")
            else:
                self.tree.heading(col_id, text=col['label'])
```

---

## Summary

Applying Windows Explorer patterns to ROM Manager will:

1. **Reduce Learning Curve**: Users already understand these patterns
2. **Improve Efficiency**: Keyboard shortcuts and multi-select speedup workflows
3. **Increase Discoverability**: Context menus reveal available options
4. **Enhance Professionalism**: Consistent patterns feel polished
5. **Support Power Users**: Multiple paths to same operations

Start with Phase 1 implementations for immediate user satisfaction, then gradually add Phase 2 features based on user feedback and development capacity.
