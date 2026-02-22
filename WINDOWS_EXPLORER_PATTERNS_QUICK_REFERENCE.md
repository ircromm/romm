# Windows Explorer UX Patterns - Quick Reference Guide

A condensed, implementation-focused reference for applying Windows Explorer patterns to ROM Manager.

---

## Quick Pattern Reference

### 1. RIGHT-CLICK CONTEXT MENUS

**When to use:** Every data table should have context menu

**Identified ROMs context menu:**
```
├─ Copy Path                     [Ctrl+C]
├─ Open in Explorer              [Ctrl+Shift+E]
├─ Open with Emulator
├─ Edit Entry →
│  ├─ Rename...
│  └─ Change Status
├─ Delete                        [Delete]
└─ Properties...
```

**Implementation:** `tree.bind("<Button-3>", show_context_menu)`

---

### 2. MULTI-SELECT & KEYBOARD

**Standard Windows shortcuts:**
```
Ctrl+Click     = Toggle item selection
Shift+Click    = Range select
Ctrl+A         = Select all
Delete         = Delete selected
Ctrl+C         = Copy selected
```

**Visual feedback:** Show count badge "3 items selected"

---

### 3. COLUMN SORTING

**Click header to sort:**
```
Original File ▲ | ROM Name | Game ▼ | System | Region | Size | CRC32 | Status

▲ = Ascending sort
▼ = Descending sort
(none) = No sort
```

**Default sorts by tab:**
- Identified: By Game Name
- Unidentified: By Filename
- Missing: By System → Game Name

---

### 4. FILTERING

**Column filter dropdowns:**
```
System [▼] → ☑ NES ☑ SNES ☑ Genesis ☑ All
Region [▼] → ☑ USA ☑ Europe ☑ Japan ☑ All
```

**Quick filter buttons in toolbar:**
```
[Status: All ▼] [Region: All ▼] [System: All ▼] [Clear Filters]
```

**Active filter indicator:**
```
Tab name shows: "Identified ROMs (2 filters active)"
```

---

### 5. BUTTON PLACEMENT STRATEGY

**Toolbar layout (left to right):**
```
[Refresh] [Search] | [Add] [Remove] [Edit] | [Download] [Delete]
   ↑               ↑        ↑                  ↑
   View ops       Selection ops               Bulk ops
```

**When multi-select active, floating toolbar appears:**
```
┌─────────────────────────────────────────┐
│ 3 items selected         [Download] [Delete] │
└─────────────────────────────────────────┘
```

---

### 6. BUTTON REDUNDANCY

**Critical operations in 3+ places:**

| Operation | Toolbar | Menu | Right-Click | Keyboard |
|-----------|---------|------|-------------|----------|
| Download  | ✓       | ✓    | ✓           | Ctrl+D   |
| Organize  | ✓       | ✓    | ✓           | Ctrl+O   |
| Delete    | ✓       | ✓    | ✓           | Del      |
| Refresh   | ✓       | ✓    | ✓           | F5       |

---

### 7. TAB ORGANIZATION

**Flat model (current structure, enhanced):**

```
[Identified ✓] [Unidentified ⚠] [Missing 📥]
   1,847          23              155

├─ Save/restore view state when switching
├─ Tab-specific toolbar appears
└─ Right-click tab → Close, Duplicate, Refresh
```

**Status indicators on tabs:**
- ✓ Green: Processing complete
- ⚠ Orange: Action needed
- 📥 Icon: Download available

---

### 8. DIALOG PATTERNS

**Confirmation dialog template:**
```
┌────────────────────────────────────────┐
│ Confirm Delete?                        │
├────────────────────────────────────────┤
│ You are about to delete:                │
│ • super_mario_bros.nes                  │
│ • super_mario_bros_2.nes                │
│ ... and 3 more items                    │
│                                        │
│ This action cannot be undone.          │
│ [Cancel]  [Delete]                     │
└────────────────────────────────────────┘
```

**Preview dialog pattern:**
```
┌─────────────────────────────────────────┐
│ Organize Preview                        │
├─────────────────────────────────────────┤
│ Strategy: 1 Game 1 ROM                  │
│ Output: D:\Organized ROMs                │
│ Total ROMs: 342                         │
│ Conflicts: 3                            │
│                                        │
│ Structure preview:                      │
│ ✓ NES/                                  │
│   ├─ Super Mario Bros.nes               │
│   └─ Mega Man.nes                       │
│ ✓ SNES/                                 │
│   └─ Super Mario Bros 4.sfc             │
│                                        │
│ [Cancel] [Go Back] [Proceed]           │
└─────────────────────────────────────────┘
```

---

## Implementation Checklist

### Immediate (Week 1)
- [ ] Add context menus to all three tree views
- [ ] Add Delete key binding
- [ ] Add Ctrl+C copy support
- [ ] Show selection count badge

### Short-term (Week 2-3)
- [ ] Implement column sorting (click headers)
- [ ] Add F5 refresh shortcut
- [ ] Add Ctrl+D download shortcut
- [ ] Add Ctrl+A select all shortcut

### Medium-term (Week 4+)
- [ ] Column filtering dropdowns
- [ ] Tab state persistence
- [ ] Floating context toolbar on multi-select
- [ ] Advanced filter UI

### Polish (Optional)
- [ ] Tab right-click menu
- [ ] Drag-to-reorder columns
- [ ] Custom column visibility
- [ ] Filter presets/saved views

---

## Key Implementation Code Snippets

### Context Menu Setup
```python
def setup_context_menu(self, tree):
    menu = tk.Menu(tree, tearoff=0)
    menu.add_command(label="Copy Path", command=lambda: copy_selection(tree))
    menu.add_command(label="Delete", command=lambda: delete_selection(tree))
    menu.add_separator()
    menu.add_command(label="Properties", command=self.show_properties)

    tree.bind("<Button-3>", lambda e: show_context_menu(menu, e))
```

### Selection Count Display
```python
def update_selection_count(self, tree):
    count = len(tree.selection())
    if count > 0:
        self.selection_label.config(text=f"{count} items selected")
    else:
        self.selection_label.config(text="")
```

### Keyboard Shortcuts
```python
def setup_shortcuts(self):
    self.root.bind('<F5>', lambda e: self.refresh_current_tab())
    self.root.bind('<Control-d>', lambda e: self.download_selected())
    self.root.bind('<Delete>', lambda e: self.delete_selected())
    self.root.bind('<Control-a>', lambda e: self.select_all())
    self.root.bind('<Control-c>', lambda e: self.copy_selection())
```

### Column Sorting
```python
def make_sortable_column(self, tree, col_index):
    def on_header_click(col):
        self.sort_treeview(tree, col, col_index)

    tree.heading(col_index, command=on_header_click)
```

---

## UX Principles Applied

| Principle | Application |
|-----------|-------------|
| **Discoverability** | Right-click menus reveal all options |
| **Efficiency** | Keyboard shortcuts for power users |
| **Familiarity** | Patterns match Windows Explorer |
| **Accessibility** | Multiple paths to same operation |
| **Feedback** | Visual indicators (count, sort arrow) |
| **Prevention** | Confirmation dialogs for destructive actions |
| **Safety** | Undo functionality where possible |
| **Consistency** | Same shortcuts across tabs |

---

## Common Pitfalls to Avoid

```
❌ WRONG:
- Only one way to do each operation
- No keyboard shortcuts
- Context menu with 10+ items (no hierarchy)
- No visual feedback on selection
- Buttons in random order
- Same button appears in 3 places with different labels

✓ RIGHT:
- Multiple paths: Toolbar, menu, keyboard, context menu
- Standard Windows shortcuts (Ctrl+A, Delete, etc.)
- Menu items grouped in submenus
- Selection count always visible
- Buttons grouped by function
- Consistent naming and placement across UI
```

---

## Testing Checklist

**For each pattern implementation, verify:**

- [ ] Right-click shows context menu only when item selected
- [ ] Menu closes on selection or click outside
- [ ] Keyboard shortcuts work in all contexts
- [ ] Multi-select works with Ctrl/Shift click
- [ ] Selection persists until user deselects
- [ ] Column sort toggles ascending/descending
- [ ] Sort indicator (▲▼) appears in header
- [ ] Filter selections are retained on tab switch
- [ ] Active filters shown in filter controls and tab label
- [ ] Delete confirmation always appears
- [ ] Undo works after destructive operations

---

## Reference: Windows Explorer Standard Shortcuts

These are the shortcuts ROM Manager should support:

```
File Management:
  Ctrl+C          Copy selected items
  Ctrl+X          Cut selected items
  Ctrl+V          Paste items
  Delete          Delete selected items (with confirmation)
  Shift+Delete    Permanent delete (optional)

Navigation:
  F5              Refresh current view
  Backspace       Go back to parent folder

Selection:
  Ctrl+A          Select all
  Ctrl+Shift+A    Deselect all (optional)
  Spacebar        Toggle current item

View:
  Ctrl+Plus       Zoom in (optional)
  Ctrl+Minus      Zoom out (optional)

Application:
  Alt+F4          Close window
  Alt+Tab         Switch window
  F1              Help (optional)
```

---

## Visual Design Consistency

**Use consistent colors from ROM Manager palette:**
- Accent (#89b4fa): Hover, selected, focus
- Success (#a6e3a1): Confirmations, valid states
- Warning (#f9e2af): Caution, pending actions
- Error (#f38ba8): Errors, destructive actions
- Surface (#313244): Background for interactive elements

**Use consistent spacing:**
- Button margins: 5px (within group) / 15px (between groups)
- Dialog padding: 10px
- Row height: ~24px
- Column spacing: Variable (see column definitions)

---

## Recommended Priority Order

1. **Context menus** (Most visible, highest impact)
2. **Keyboard shortcuts** (F5, Ctrl+A, Delete)
3. **Multi-select visual feedback** (Selection count)
4. **Column sorting** (Data exploration)
5. **Column filtering** (Large collections)
6. **Tab state persistence** (Workflow continuity)
7. **Floating toolbar** (Polish/refinement)

This focuses on features that directly improve user efficiency and satisfaction.
