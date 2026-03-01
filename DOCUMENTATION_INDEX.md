# Documentation Index

This index reflects the current active documentation set. Legacy UX pattern documents that referenced deprecated behaviors were archived with an `OLD_` prefix.

## Active Docs
- `readme.txt` - Primary project documentation, launch modes, and local agent session/autonomy guidance
- `README_UX_PATTERNS.md` - UX patterns overview and guidance
- `docs/FLET_AGENT_PROTOCOL.md` - Flet UI compatibility rules

## Notes
- The application no longer contains remote ROM acquisition capabilities. Exception: DAT metadata download catalogs (No-Intro/Redump/TOSEC) are available in Tools > DAT Operations via curated mirrors.
- All user-facing UI text should support EN and PT-BR parity, including the Flutter frontend language selector.
- Import & Scan (PySide6) now auto-generates previews whenever inputs/results change and supports combining multiple organization strategies at once (checkbox set). EmulationStation is mutually exclusive with other strategies (forces "By System").
