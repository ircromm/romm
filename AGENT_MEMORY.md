# Agent Memory (Internal)

> Uso interno do agente neste repositório.  
> **Instrução mandatória:** gravar e atualizar o aprendizado de **todos** os resultados (sucessos, falhas, limitações de ambiente, workarounds, regressões, decisões e pós-mortem) neste arquivo ao final de cada tarefa relevante.

---

# Flet 0.80+ API Patterns (Breaking Changes)

## Entry Point
```python
ft.run(main)  # NOT ft.app(target=main)
```

## Reserved Properties on Controls
All Flet controls (Column, Row, Container, etc.) inherit `page` as a read-only property from `BaseControl`.
**Never** assign `self.page = page` in subclasses. Use `self._pg = pg` instead.

## FilePicker (Service-based, async)
```python
picker = ft.FilePicker()  # No on_result parameter
page.services.append(picker)  # NOT page.overlay

# In async handler:
async def on_click(self, e):
    files = await self.picker.pick_files(
        dialog_title="Select file",
        allowed_extensions=["dat", "xml"],
        allow_multiple=True,
    )
    # files is List[FilePickerFile] or None

    path = await self.picker.get_directory_path(dialog_title="Select folder")
    # path is Optional[str]
```

## SnackBar (DialogControl)
```python
sb = ft.SnackBar(
    content=ft.Text("Message", color="#cdd6f4"),
    bgcolor="#313244",
    duration=3000,
)
page.show_dialog(sb)  # NOT page.open(sb)
```

## Services (FilePicker, Clipboard)
Services must be added to `page.services`, NOT `page.overlay`:
```python
picker = ft.FilePicker()
page.services.append(picker)  # NOT page.overlay.append(picker)

clipboard = ft.Clipboard()
page.services.append(clipboard)  # NOT page.overlay.append(clipboard)

# In async handler:
await clipboard.set("text to copy")
```

## Window
```python
page.window.width = 1300
page.window.height = 850
# Close is async:
page.run_task(page.window.close)
# Or inside async context:
await page.window.close()
```

## Alignment
```python
ft.Alignment(0, 0)  # center - NOT ft.alignment.center
```

## Switch
```python
ft.Switch(
    label="Text",
    label_text_style=ft.TextStyle(...)  # NOT label_style
)
```

## Dropdown
```python
ft.Dropdown(
    label="Strategy",
    options=[ft.dropdown.Option(key="id", text="Name")],
    label_style=ft.TextStyle(...)  # This one still uses label_style
    on_select=lambda e: ...,  # NOT on_change (removed in 0.80)
)
# e.control.value still works in on_select handler
```

## Deprecated Helpers → Class Methods
```python
# OLD (deprecated, emits warnings)    # NEW (0.80+)
ft.padding.all(10)                    → ft.Padding.all(10)
ft.padding.only(top=16)               → ft.Padding.only(top=16)
ft.padding.symmetric(h=6, v=2)        → ft.Padding.symmetric(horizontal=6, vertical=2)
ft.border.all(1, color)               → ft.Border.all(1, color)
ft.border.only(left=...)              → ft.Border.only(left=...)
```

## ElevatedButton → Button
```python
# OLD                                 # NEW
ft.ElevatedButton("text", ...)        → ft.Button("text", ...)
```

---

# RetroFlow Project Memory

## Project Structure
- ROM Collection Manager v2.1.0 at `D:\1 romm\APP`
- Backend: `rommanager/` (models, scanner, matcher, parser, organizer, collection, reporter, utils, shared_config)
- GUI: `rommanager/gui_flet.py` (Flet 0.80+), `rommanager/gui.py` (legacy tkinter)
- Entry: `main.py` (default=flet, `--gui`=tkinter, `--web`=flask, `--help`=CLI)

## Flet 0.80 API Notes
See [flet-080-api.md](flet-080-api.md) for detailed API patterns.

Key breaking changes vs older Flet:
- `ft.run(main)` replaces `ft.app(target=main)`
- `FilePicker` is async: `files = await picker.pick_files()`, no `on_result` callback
- `SnackBar` is `DialogControl`, show via `page.show_dialog(sb)`
- `FilePicker`/`Clipboard` are Services — add to `page.services` NOT `page.overlay`
- `page` is a read-only property on all Controls — use `self._pg` instead of `self.page`
- `ft.alignment.center` removed — use `ft.Alignment(0, 0)`
- `Switch.label_style` renamed to `label_text_style`
- `Window.close()` is async — use `page.run_task(page.window.close)`
- `Dropdown.on_change` removed — use `on_select` instead
- `ft.padding.all/only/symmetric` → `ft.Padding.all/only/symmetric` (class methods)
- `ft.border.all/only` → `ft.Border.all/only` (class methods)
- `ElevatedButton` → `Button`

## Catppuccin Mocha Theme
The MOCHA dict in gui_flet.py contains the full Catppuccin Mocha palette.

---

## Learning Log Rule (Must Follow)
At the end of each meaningful change/task, append a short "Learning Log" entry with:
1. Context/task
2. What worked
3. What failed / constraints
4. Decisions made
5. Follow-up actions

Template:

```md
### Learning Log - YYYY-MM-DD HH:MM
- Task:
- Successes:
- Failures/Constraints:
- Decisions:
- Next steps:
```
