# ROM Manager UX Patterns - Visual Mockups & Diagrams

Visual representation of Windows Explorer patterns applied to ROM Manager.

---

## Current vs. Recommended Layout

### Current Layout (As Is)

```
┌─────────────────────────────────────────────────────────────────────┐
│ File DATs Export Downloads                                          │
├─────────────────────────────────────────────────────────────────────┤
│ ┌─ DAT Files ──────────────────┐ ┌─ Scan ROMs ──────────────────┐ │
│ │ [Add DAT] [Remove] [Library] │ │ [No folder selected] [Browse] │ │
│ │ [---listing DAT files---]    │ │ [Scan] [options]             │ │
│ └──────────────────────────────┘ └──────────────────────────────┘ │
│                                                                    │
│ Search: [________________]                                        │
│                                                                    │
│ ┌─ Identified ROMs | Unidentified Files | Missing ROMs ──────────┐ │
│ │ Original File │ROM Name│ Game │ System │ Region │ Size │ CRC32│ │
│ │ ──────────────────────────────────────────────────────────────│ │
│ │ [ROM entries displayed in rows]                              │ │
│ │ (no buttons, no context menu)                                │ │
│ │                                                              │ │
│ └──────────────────────────────────────────────────────────────┘ │
│ Stats: 342 identified, 23 unidentified, 155 missing              │
│                                                                    │
│ ┌─ Organization ──────────────────────────────────────────────────┐ │
│ │ Strategy: [1G1R] [By Region] [By System] [Alphabetical]        │ │
│ │ Output: [path field] [Browse...]                               │ │
│ │ Action: [Copy] [Move]                                          │ │
│ │ [Preview] [Organize!] [Undo]                                   │ │
│ └─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

### Recommended Enhanced Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│ File DATs Export Downloads                                          │
├─────────────────────────────────────────────────────────────────────┤
│ ┌─ DAT Files ──────────────────┐ ┌─ Scan ROMs ──────────────────┐ │
│ │ [Add DAT] [Remove] [Library] │ │ [No folder selected] [Browse] │ │
│ │ [---listing DAT files---]    │ │ [Scan] [options]             │ │
│ └──────────────────────────────┘ └──────────────────────────────┘ │
│                                                                    │
│ Search: [________________]     [3 items selected] [Download] [×]  │  ← Selection feedback
│                                                                    │
│ ┌─ Identified ✓ | Unidentified ⚠ | Missing 📥 ─────────────────┐ │
│ │                                                              │ │
│ │ [🔄 Refresh] [⚙ Settings] | [+ Add] [- Remove] [✎ Edit] | │ │  ← Tab toolbar
│ │ [↓ Download] [⊠ Delete] [...More]                         │ │
│ │                                                              │ │
│ │ Original File ▼ │ROM Name│ Game ▲ │ System │ Region │ ...│ │  ← Sortable headers
│ │ ──────────────────────────────────────────────────────────│ │
│ │ [ROM entries - multi-select enabled]                       │ │  ← Multi-select ready
│ │ [Can Ctrl+Click, Shift+Click for selection]               │ │
│ │                                                              │ │
│ │ ┌──────────────────────────────────────────────────────┐  │ │
│ │ │ 2 items selected                    [Download] [Delete] │  │ │  ← Context toolbar
│ │ └──────────────────────────────────────────────────────┘  │ │
│ └──────────────────────────────────────────────────────────────┘ │
│ Stats: 342 identified, 23 unidentified, 155 missing              │
│                                                                    │
│ ┌─ Organization ──────────────────────────────────────────────────┐ │
│ │ Strategy: [1G1R] [By Region] [By System] [Alphabetical]        │ │
│ │ Output: [path field] [Browse...]                               │ │
│ │ Action: [Copy] [Move]                                          │ │
│ │ [Preview] [Organize!] [Undo]                                   │ │
│ └─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Context Menu Mockups

### Identified ROMs Tab - Right-Click Menu

```
Mouse right-click on "Super Mario Bros.nes" row:

    ┌─ Copy File Path              (Ctrl+C)
    ├─ Open in File Explorer       (Ctrl+Shift+E)
    ├─ Open File with Emulator
    ├─ Copy ROM Details ──────→ Name
    │                          Name + System
    │                          Full JSON
    ├─ Export ──────────────→ Copy to Clipboard
    │                        Save to File...
    ├─ Edit Entry ──────────→ Rename...
    │                        Change Status...
    │                        Reassign to Game...
    ├─ Delete ──────────────→ Delete File      (Ctrl+Delete)
    │                        Remove from List (Keep file)
    ├──────────────────────────────────────
    └─ Properties...          (Alt+Return)
```

### Unidentified Files Tab - Right-Click Menu

```
Mouse right-click on "unknown_game.zip" row:

    ┌─ Show in File Explorer   (Ctrl+Shift+E)
    ├─ Copy File Details ──→ Filename only
    │                       Full path
    │                       CRC32
    ├─ Force Identify... ──→ Select from database...
    │                       Manual entry...
    ├─ Delete ──────────→ Confirm Delete    (Del)
    │                     Permanent Delete  (Shift+Del)
    └─ Properties...
```

### Missing ROMs Tab - Right-Click Menu

```
Mouse right-click on "Metroid.nes (USA)" row:

    ┌─ Copy Download Info ──→ ROM Name
    │                        Game Name
    │                        System + Region
    ├─ Download ────────────→ From Myrient...
    │                        Search Archive.org...
    │                        Search Custom URL...
    ├─ Copy Search Query ───→ Game Name
    │                        ROM Name
    │                        Custom format
    ├─ Google Search
    └─ Mark as Excluded
```

---

## Column Header Interactions

### Before Click (Default)

```
┌────────────────────────────────────────────────────────────┐
│ Original File | ROM Name | Game | System | Region | Size  │
│────────────────────────────────────────────────────────────│
│ super_mario.nes  │ Super Mario Bros.  │ NES    │ USA   │ 40KB
│ sonic.gen        │ Sonic the Hedgehog │ Genesis│ USA   │ 512KB
│ kirby.sfc        │ Kirby Super Star   │ SNES   │ USA   │ 512KB
└────────────────────────────────────────────────────────────┘
```

### After Clicking "Game" Header (Ascending)

```
┌────────────────────────────────────────────────────────────┐
│ Original File | ROM Name | Game ▲ | System | Region | Size│  ← Arrow indicator
│────────────────────────────────────────────────────────────│
│ kirby.sfc        │ Kirby Super Star   │ SNES   │ USA   │ 512KB
│ sonic.gen        │ Sonic the Hedgehog │ Genesis│ USA   │ 512KB
│ super_mario.nes  │ Super Mario Bros.  │ NES    │ USA   │ 40KB
│ [alphabetically sorted by game name]                       │
└────────────────────────────────────────────────────────────┘
```

### After Clicking "Game" Header Again (Descending)

```
┌────────────────────────────────────────────────────────────┐
│ Original File | ROM Name | Game ▼ | System | Region | Size│  ← Arrow reversed
│────────────────────────────────────────────────────────────│
│ super_mario.nes  │ Super Mario Bros.  │ NES    │ USA   │ 40KB
│ sonic.gen        │ Sonic the Hedgehog │ Genesis│ USA   │ 512KB
│ kirby.sfc        │ Kirby Super Star   │ SNES   │ USA   │ 512KB
│ [reverse alphabetical order]                               │
└────────────────────────────────────────────────────────────┘
```

---

## Selection & Multi-Select Visual Feedback

### Single Item Selected

```
┌────────────────────────────────────────────────────────────┐
│ Original File | ROM Name | Game | System | Region | Size  │
│────────────────────────────────────────────────────────────│
│ super_mario.nes  │ Super Mario Bros.  │ NES    │ USA   │ 40KB  ← Selected (blue highlight)
│ sonic.gen        │ Sonic the Hedgehog │ Genesis│ USA   │ 512KB
│ kirby.sfc        │ Kirby Super Star   │ SNES   │ USA   │ 512KB
└────────────────────────────────────────────────────────────┘

Status bar shows: [1 item selected]
```

### Multiple Items Selected (Ctrl+Click)

```
┌────────────────────────────────────────────────────────────┐
│ Original File | ROM Name | Game | System | Region | Size  │
│────────────────────────────────────────────────────────────│
│ super_mario.nes  │ Super Mario Bros.  │ NES    │ USA   │ 40KB  ← Selected
│ sonic.gen        │ Sonic the Hedgehog │ Genesis│ USA   │ 512KB ← Selected
│ kirby.sfc        │ Kirby Super Star   │ SNES   │ USA   │ 512KB
└────────────────────────────────────────────────────────────┘

Status bar shows: [2 items selected] [Download ▼] [Delete]  ← Context actions appear
```

### Range Selection (Shift+Click)

```
User clicks "sonic.gen", then Shift+Click "kirby.sfc":

┌────────────────────────────────────────────────────────────┐
│ Original File | ROM Name | Game | System | Region | Size  │
│────────────────────────────────────────────────────────────│
│ super_mario.nes  │ Super Mario Bros.  │ NES    │ USA   │ 40KB
│ sonic.gen        │ Sonic the Hedgehog │ Genesis│ USA   │ 512KB  ← Start of range
│ kirby.sfc        │ Kirby Super Star   │ SNES   │ USA   │ 512KB  ← End of range
│ [all items between start and end selected]                 │
└────────────────────────────────────────────────────────────┘

Status bar shows: [2 items selected] [Download ▼] [Delete]
```

---

## Tab Status Indicators

### Tab States with Icons

```
Before scanning:
┌─ Identified ○ | Unidentified ○ | Missing ○ ─────┐
│ No data loaded yet                              │

After initial scan:
┌─ Identified ✓ | Unidentified ⚠ | Missing 📥 ───┐
│ 342 loaded        23 issues        155 missing  │

Identified: ✓ (green checkmark) = All processed
Unidentified: ⚠ (orange warning) = Needs action
Missing: 📥 (download icon) = Available for download

Tab with active filters:
┌─ Identified ✓ (2 filters) ─────────────────────┐
│ Showing filtered results                      │
│ [Clear Filters] shown in toolbar              │
```

---

## Dialog Boxes & Confirmation Patterns

### Delete Confirmation Dialog

```
┌──────────────────────────────────────────────────────┐
│ ⚠  Delete Items?                              [×]    │
├──────────────────────────────────────────────────────┤
│                                                      │
│ You are about to delete:                            │
│                                                      │
│ ☑ super_mario_bros.nes                             │
│ ☑ sonic_the_hedgehog.gen                           │
│ ☑ kirby_super_star.sfc                             │
│ ... and 5 more items                               │
│                                                      │
│ This action cannot be undone.                       │
│                                                      │
│                [Cancel]           [Delete All]      │
├──────────────────────────────────────────────────────┤
│ ✓ Shows count and preview of items to delete        │
│ ✓ Buttons clearly indicate action                   │
│ ✓ Warning message prominent                         │
└──────────────────────────────────────────────────────┘
```

### Organize Preview Dialog

```
┌──────────────────────────────────────────────────────┐
│ 📂 Organize Preview                           [×]    │
├──────────────────────────────────────────────────────┤
│                                                      │
│ Strategy: 1 Game 1 ROM                              │
│ Output Folder: D:\Organized ROMs\                   │
│ Total ROMs to organize: 342                         │
│ Conflicts to resolve: 3                             │
│                                                      │
│ Directory Structure:                                │
│ ✓ NES/                                              │
│   ├─ Donkey Kong.nes                                │
│   ├─ Mario Bros.nes                                 │
│   └─ Metroid.nes                                    │
│ ✓ SNES/                                             │
│   ├─ Super Mario Bros 4.sfc                         │
│   ├─ Super Metroid.sfc                              │
│   └─ The Legend of Zelda - A Link to the Past.sfc  │
│ ✓ Genesis/                                          │
│   ├─ Sonic the Hedgehog.gen                         │
│   └─ Sonic the Hedgehog 2.gen                       │
│                                                      │
│            [Go Back] [Preview More] [Proceed]       │
├──────────────────────────────────────────────────────┤
│ ✓ Clear preview of what will happen                 │
│ ✓ Shows folder structure                            │
│ ✓ Clearly labeled action buttons                    │
└──────────────────────────────────────────────────────┘
```

---

## Toolbar Organization

### Identified ROMs Tab Toolbar

```
┌────────────────────────────────────────────────────────────┐
│ [🔄 Refresh] [⚙ Settings] | [+ Add] [- Remove] [✎ Edit]  │
│ [↓ Download] [⊠ Delete] [📋 Export ▼] [... More]          │
│                                                            │
│ Groups (left to right):                                   │
│ 1. View operations (Refresh, Settings)                   │
│ 2. Selection/editing (Add, Remove, Edit)                 │
│ 3. Bulk operations (Download, Delete, Export)            │
│ 4. More options (expandable menu)                        │
└────────────────────────────────────────────────────────────┘

Icon + Label Pattern:
[🔄 Refresh]  ← Icon clearly shows purpose
[⚙ Settings]  ← Self-explanatory
[+ Add]       ← Plus icon = add action
[- Remove]    ← Minus icon = remove action
```

### Missing ROMs Tab Toolbar

```
┌────────────────────────────────────────────────────────────┐
│ [Refresh] [Filter ▼] | [Search ▼] [↓ Download ▼]          │
│ [📋 Export ▼] [More...]                                    │
│                                                            │
│ Groups:                                                    │
│ 1. View (Refresh, Filter)                                │
│ 2. Search operations (Search, Download)                  │
│ 3. Export/reporting (Export)                             │
│ 4. Additional options                                     │
└────────────────────────────────────────────────────────────┘
```

---

## Keyboard Shortcut Visual Legend

### In Menu & Tooltips

```
File Menu:
├─ Save Collection        Ctrl+S
├─ Open Collection...     Ctrl+O
└─ Exit                   Alt+F4

Edit Menu:
├─ Select All             Ctrl+A
├─ Deselect All           Ctrl+Shift+A
├─ Copy                   Ctrl+C
└─ Delete                 Delete

View Menu:
├─ Refresh               F5
├─ Zoom In              Ctrl+Plus
└─ Zoom Out             Ctrl+Minus

Tools Menu:
├─ Organize             Ctrl+O
├─ Download Missing     Ctrl+D
└─ Find                 Ctrl+F
```

### Tooltip Example

```
When hovering over [Download] button:

┌─────────────────────────────────────────┐
│ Download selected ROMs                  │
│ Ctrl+D                                  │
│                                         │
│ Downloads the selected missing ROMs     │
│ from available sources.                 │
│                                         │
│ (Only available in Missing ROMs tab)    │
└─────────────────────────────────────────┘
```

---

## Keyboard Navigation Flow

### Tab Navigation

```
User presses Ctrl+Tab:
Current tab: Identified ROMs ✓
Next tab: Unidentified Files ⚠

┌─ Identified ✓ → Unidentified ⚠ → Missing 📥 → (loops) Identified ✓
│
└─ Ctrl+Shift+Tab reverses direction
```

### Focus Navigation Within Tab

```
User presses Tab key repeatedly (cycling through focusable elements):

1. Search input [━━━] (focused, shows cursor)
2. Tree view (first item highlighted)
3. Toolbar button [Refresh] (highlighted)
4. Toolbar button [Download] (highlighted)
5. ... more buttons ...
6. Back to Search input (cycle)
```

### Arrow Key Navigation in Tree

```
User in tree view, presses arrow keys:

Down arrow: Move selection down one row
Up arrow:   Move selection up one row
Home:       Jump to first row
End:        Jump to last row
Page Down:  Scroll down
Page Up:    Scroll up
```

---

## Color Scheme Reference

### Current ROM Manager Colors

```
┌─────────────────────────────┐
│ Background: #1e1e2e         │ Dark theme base
│ Foreground: #cdd6f4         │ Light text
│ Accent: #89b4fa             │ Primary interactive (blue)
│ Success: #a6e3a1            │ Confirmations (green)
│ Warning: #f9e2af            │ Cautions (yellow)
│ Error: #f38ba8              │ Errors (red)
│ Surface: #313244            │ Secondary background
└─────────────────────────────┘

Usage Examples:
├─ Button normal: Accent background (#89b4fa)
├─ Button hover: Lighter accent (#a7c8f7)
├─ Button pressed: Darker accent (#6b93dd)
├─ Selected row: Accent highlight (#89b4fa)
├─ Disabled item: Reduced opacity (50%)
├─ Error message: Error color (#f38ba8)
└─ Success message: Success color (#a6e3a1)
```

### Region Color Coding

```
USA:      Blue    #60a5fa (text) on #1e3a5f (background)
Europe:   Purple  #a78bfa (text) on #3b1f5e (background)
Japan:    Red     #f87171 (text) on #5f1e1e (background)
World:    Green   #4ade80 (text) on #1e5f2e (background)
Brazil:   Lime    #a3e635 (text) on #3d5f1e (background)
Korea:    Orange  #fb923c (text) on #5f3b1e (background)
China:    Yellow  #fbbf24 (text) on #5f4e1e (background)
Default:  Slate   #94a3b8 (text) on #334155 (background)
```

---

## Responsive Layout Considerations

### Full Window (1300x850)

```
┌──────────────────────────────────────────────────────────┐
│ Menu bar                                                 │
├──────────────────────────────────────────────────────────┤
│ ┌─ Top panels (60px) ──────────────────────────────────┐ │
│ │ [DAT panel] | [Scan panel]                           │ │
│ └──────────────────────────────────────────────────────┘ │
│ ┌─ Search (30px) ──────────────────────────────────────┐ │
│ │ Search: [________] [Selection feedback]              │ │
│ └──────────────────────────────────────────────────────┘ │
│ ┌─ Tree view (450px) ───────────────────────────────┐ │
│ │ [Tab headers]                                      │ │
│ │ [Toolbar]                                          │ │
│ │ [Tree with columns]                                │ │
│ │ [~ 15 rows visible]                                │ │
│ └──────────────────────────────────────────────────┘ │
│ ┌─ Stats (20px) ───────────────────────────────────┐ │
│ │ Stats summary                                     │ │
│ └──────────────────────────────────────────────────┘ │
│ ┌─ Organization (120px) ───────────────────────────┐ │
│ │ Strategy selection, output, action buttons       │ │
│ └──────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

### Minimum Window (1000x650)

```
Layout contracts but remains functional:
├─ Font sizes reduced slightly
├─ Spacing reduced (margins 5px instead of 10px)
├─ Toolbar buttons may wrap or hide into menu
├─ Tree view shows fewer columns (requires horizontal scroll)
├─ Organization panel takes full width
└─ All functionality remains accessible
```

---

## Accessibility Features Diagram

### Keyboard-Only Navigation Path

```
Alt+F     → File menu
  ↓
Keyboard through menu items
  ↓
Enter     → Activate selected item
  ↓
Dialog opens (if applicable)
  ↓
Tab       → Navigate dialog fields
  ↓
Enter/Esc → Confirm or cancel

Alternative for common operations:
├─ F5           → Refresh
├─ Ctrl+A       → Select all
├─ Ctrl+C       → Copy
├─ Delete       → Delete selected
├─ Ctrl+D       → Download
└─ Ctrl+O       → Organize
```

### Screen Reader Support Points

```
Tree view items need:
├─ Label associations for columns
├─ Role information ("column header", "row")
├─ Selection state announced
├─ Sort direction announced
├─ Context menu availability announced

Dialog boxes need:
├─ Title clearly stated
├─ Focus automatically in dialog
├─ Required fields marked
├─ Tab order logical
├─ Submit button clearly labeled
└─ Close method clear (Esc or button)
```

---

## Animation & Feedback Timeline

### User Downloads a ROM

```
Timeline:
0ms:    User clicks [Download] button
        └─ Button shows pressed state (slight scale/color change)

100ms:  Progress dialog opens
        ├─ Shows ROM name
        ├─ Shows download source
        └─ Shows "Connecting..." status

500ms:  Download begins
        ├─ Progress bar appears
        └─ Bytes downloaded shown: "2.4 MB / 8.7 MB"

5000ms: Download completes
        ├─ Progress shows 100%
        ├─ Success message appears
        └─ Auto-close after 2 seconds or user clicks

Feedback provided:
├─ Visual: Progress bar, status text
├─ Audio: Optional beep on completion (if enabled)
├─ Haptic: None (desktop application)
```

---

## Summary of Visual Improvements

**Before (Current):**
- Toolbar buttons scattered right-aligned
- No visual feedback on selection
- Clicking column header does nothing
- No context menus
- Tab names don't show status

**After (Recommended):**
- Organized toolbar with logical grouping
- Selection count badge visible
- Column headers show sort indicators (▲▼)
- Right-click opens context menus
- Tab icons show status (✓, ⚠, 📥)
- Floating toolbar on multi-select
- Clear visual hierarchy
- Consistent color coding

**Impact:**
- More professional appearance
- Better discoverability of features
- Reduced learning curve
- Improved workflow efficiency
- Increased user confidence
