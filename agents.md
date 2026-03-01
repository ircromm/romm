# R0MM v2 Project Memory & Continuity Prompt

Use this to onboard a new agent into the R0MM v2 project context.

---

## PROJECT OVERVIEW

**R0MM v2** is a ROM Organization Manager with a modern UI/UX overhaul (as of 2026-02-23). It manages ROM libraries across 3 active frontends:
- **Web**: Single-file Flask app with React via CDN (no npm/bundler)
- **Flet**: Cross-platform desktop GUI (Python/Flutter)
- **PySide6**: Native Windows desktop GUI

**Tkinter is excluded** from all active development.

**Repository**: GitHub master branch at `D:\1 romm\romm`

**Policy**: The app contains **no remote acquisition capabilities** (ROMs, thumbnails, or direct remote fetches, including Archive.org or Myrient). Legacy acquisition-related modules and docs are archived with an `OLD_` prefix.
Exception (user-authorized, 2026-02-26): a dedicated **MyrientFetcher** tool may be implemented and used inside R0MM for controlled, rate-limited Myrient extraction workflows, provided it enforces strict concurrency limits and graceful shutdown. Local handoff to **JDownloader** (Flashgot API on localhost) is also authorized as an optional queue backend for the same workflow.

---

## SESSION INSTRUCTIONS (CHAT CONTINUITY)

- Treat any user message explicitly labeled as an "instruction" as an addition to this `agents.md`.
- From now on, all changes must consider EN and PT-BR language parity; no hardcoded user-facing strings outside i18n.
- New instruction (2026-02-28): When the user mentions an "image" or "screenshot" for visual context/feedback, assume they are referring to `cap.png` in the project root unless specified otherwise.
- When estimated context drops to ~80%, notify the user and update `agents.md` with all session learnings and evolution so far.
- Also update `agents.md` every 10 user-assistant interactions during the session.
- When the user provides an error log, analyze it and apply a fix. If confidence is above 80%, proceed without asking questions.
- New instruction (2026-02-24): When asked to polish PySide6 UI, align typography/spacing and visual hierarchy to match Flutter design in `lib/` (theme + views), use #1A2517 as dominant background and #ACC8A2 as accents (20%-35% area), improve padding and hover states, and proactively fix visual inconsistencies.
- New instruction (2026-02-24): When asked to improve PySide6 typography and micro-interactions, enforce global font smoothing/antialiasing, strict typographic hierarchy (H1/H2/subtitle/body), primary text color #ACC8A2 and secondary text rgba(172,200,162,0.6), and apply padding/word-wrap/alignment fixes across all PySide6 UI.
- New instruction (2026-02-24): Avoid using unsupported QSS properties like `alignment`/`qproperty-alignment` on `QPushButton` or `QComboBox`; this causes runtime warnings. Use layout alignment instead.
- New instruction (2026-02-24): Always fix i18n keys so no raw placeholders appear in PySide6; ensure all `t("key")` usages are present in `rommanager/i18n.py` for EN/PT-BR.
- New instruction (2026-02-25): After every code update, also update the documentation.
- New note (2026-02-25): CoreService tool API contracts added; AppState now dispatches async tool workers with dedicated signals and validates missing parameters.
- New note (2026-02-25): CoreService rebuilt from scratch; tool implementations now functional (DAT diff/merge, batch convert via external tools, torrentzip repack, deep clean, duplicate finder). ToolsView now prompts for paths and logs results.
- New note (2026-02-26): Myrient downloader perf bottlenecks identified in local code review: per-chunk progress signal spam + dual UI updates (Hydra + Downloads list) and redundant HEAD on fresh downloads. Fetcher now throttles DOWNLOADING progress emissions, uses 1 MiB read chunks, skips HEAD for brand-new downloads, and auto-clears the HALT latch when a new batch starts after active jobs drain.
- New note (2026-02-26): Myrient download transport has been replaced with a local `rclone.exe copyurl` backend (Hydra Queue / Downloads tab UX preserved). R0MM still enforces 4 concurrent jobs, but transfer bytes now flow through rclone with single-stream-per-file settings to better match Myrient FAQ guidance; PySide6 progress is computed from local file growth during the rclone subprocess (avoids stdout progress parsing stalls/deadlocks).
- New note (2026-02-26): PySide6 now persists UI state in `data/settings.json` under `ui_state.pyside6` with autosave (debounced) + close flush. Restored state includes main window geometry/view/language/search, Library tab/splitter, Import & Scan inputs/toggles/combos, and Tools fields including Downloads URLs/base URL/output folder + catalog drawer/tab selections.
- New note (2026-02-26): Myrient/rclone transfer failures are now logged explicitly per file via `monitor_action` (`myrient:rclone:start|done|halted|error`) so runtime logs and the Nerve Center show the real rclone error text instead of only generic `ERROR` statuses in the Downloads list.
- New note (2026-02-26): Added Myrient rclone resilience UX: connection/timeout errors on `fN.erista.me` now trigger one automatic mirror retry to `myrient.erista.me` (same path), and the Downloads tab status list displays a shortened inline error reason while preserving the full rclone error in the item tooltip.
- New note (2026-02-26): Policy exception authorized for a controlled, rate-limited `MyrientFetcher` integration (strict max 4 concurrent connections; graceful halt required).
- New note (2026-02-26): PySide6 Nerve Center Active Operation column now supports a Hydra Queue UI (up to 4 transfer lines) fed by `AppState.download_progress`, with `[ HALT TRAFFIC ]` wired to `AppState.halt_traffic()`.
- New note (2026-02-26): ToolsView gained a dedicated `Downloads` tab for Myrient/Hydra queueing (output folder picker, one-URL-per-line parser with optional `URL | custom filename`, local status list, and tooltips/i18n parity).
- New note (2026-02-26): Added guided Myrient download UX: `Add URL...` helper in Downloads tab, Myrient listing resolver for missing ROMs (async via `AppState`), and `Library > Missing` button to send selected/all visible missing entries into `Tools > Downloads` for resolve+queue.
- New note (2026-02-26): `Add URL...` was upgraded from manual input to a Myrient directory browser modal (async listing fetch, navigation, filtering, multi-select), using `CoreService.myrient_list_directory()` + `AppState.myrient_directory_listed`.
- New note (2026-02-26): Downloads tab now has an inline Myrient Catalog panel that separates a loaded listing into Systems (directories) and DAT files, supports browsing a selected system directory, and queues selected files directly to Hydra.
- New note (2026-02-26): Myrient catalog no longer depends on manual URL entry; `CoreService.myrient_catalog_presets()` now provides built-in root presets and ToolsView auto-loads/auto-detects a working catalog root when opening the Downloads tab.
- New note (2026-02-26): Myrient Catalog moved into a collapsible drawer (hidden by default). Root catalog loads now auto-select the first system and auto-load its entries; parser hardened for more directory-listing HTML variants.
- New note (2026-02-26): Fixed downloader false busy-state conflicts by moving Myrient listing/link-resolution to a dedicated Myrient worker queue in `AppState` (separate from `_tool_thread`). Catalog autoload now starts when opening the drawer (not merely switching to the Downloads tab).
- New note (2026-02-26): Myrient/rclone transport was hardened after runtime-log triage of `fN.erista.me` connect timeouts: downloader now canonicalizes Myrient file URLs to `myrient.erista.me` before transfer (including catalog entries), uses `--multi-thread-streams 0` per Myrient FAQ guidance, and applies rclone `copyurl` compatibility flags (`--disable-http2`, `--bind 0.0.0.0`, `--user-agent curl`) with short retries/timeouts so errors surface faster and mirror/CDN host issues are easier to recover from.
- New note (2026-02-26): Myrient transport now prefers the Myrient-FAQ-supported `rclone` HTTP remote workflow (`copyto --http-url ... :http:...`) for Myrient file downloads, while keeping `copyurl` only as the generic/non-Myrient fallback. Hydra Queue progress remains file-growth-based and destination custom filenames are preserved via `copyto`.
- New note (2026-02-26): Runtime-log triage showed Myrient `myrient.erista.me` requests still being redirected to an unreachable CDN host (`f3.erista.me`) in some routes. `MyrientFetcher` now parses the redirected URL from the rclone error line and performs limited automatic CDN host hopping (`fN -> fM`, same path) before failing, while preserving Myrient URL canonicalization for normal queue/catalog entries.
- New note (2026-02-26): Additional log triage showed Myrient retries still failing with `dial tcp4` after host hopping. The rclone compatibility profile no longer forces `--bind 0.0.0.0` (IPv4-only local bind), allowing the OS to choose the best network route/protocol (including IPv6) during Myrient transfers.
- New note (2026-02-26): Introduced a secondary transport fallback for stubborn Myrient route failures: after rclone retries/profile/mirror/CDN host-hop attempts are exhausted, `MyrientFetcher` now hands the transfer off to Windows native HTTP (`PowerShell Invoke-WebRequest`) before surfacing a final error.
- New note (2026-02-26): PowerShell `Invoke-WebRequest` fallback is now opt-in only (`R0MM_ENABLE_PS_IWR_FALLBACK=1`) so default Myrient throughput remains fully rclone-based; this avoids automatic transport downgrade on performance-sensitive runs.
- New note (2026-02-26): Added JDownloader integration for the Downloads tab. CoreService now supports local Flashgot/Extern enqueue (`http://127.0.0.1:9666/flashgot`), AppState exposes `queue_jdownloader_downloads()`, and ToolsView includes `[ SEND TO JDOWNLOADER ]` + autostart toggle with EN/PT-BR i18n + tooltip parity. JDownloader submissions emit `download_progress` with status `ADDED` so Nerve Center Hydra rows can show `[JD ] ... LINKGRABBER`.
- New note (2026-02-27): Tools > Downloads now includes `[ DOWNLOAD JDOWNLOADER ]`, which opens the official JDownloader download page (`https://jdownloader.org/jdownloader2`) in the default browser. The click emits a single Nerve Center log line and has EN/PT-BR i18n + tooltip parity.
- New note (2026-02-27): Download policy switched to JDownloader-only UX in PySide6. Tools > Downloads hides/removes Hydra/rclone queue actions, Myrient catalog/missing-resolver controls, and keeps only URL input + JDownloader submission/installer actions.
- New note (2026-02-27): JDownloader enqueue now tries local endpoint variants (`127.0.0.1` and `localhost`) and emits actionable diagnostics/hint text when the endpoint is unreachable, reducing opaque `WinError 10061` failures.
- New note (2026-02-27): JDownloader handoff now supports automatic local bootstrap: when endpoint health check fails, CoreService attempts to locate and start `JDownloader2.exe` (common Windows paths or `R0MM_JDOWNLOADER_BIN`) and waits for `:9666` before sending links.
- New note (2026-02-27): JDownloader bootstrap path resolution was hardened: it now checks `R0MM_JDOWNLOADER_BIN`, PATH, uninstall registry entries scoped to JDownloader, and common install folders; installer executables (Setup) are excluded from auto-launch resolution.
- New note (2026-02-27): Fixed a bootstrap regression where uninstall-registry `DisplayIcon` values could resolve to `.ico` files and cause `WinError 193`; resolver now accepts only valid launcher executable names (`JDownloader2.exe` / `JDownloader.exe`) and includes `%LOCALAPPDATA%\\JDownloader 2\\JDownloader2.exe` in direct candidates.
- New note (2026-02-27): JDownloader bootstrap now supports mode selection via `R0MM_JDOWNLOADER_BOOT_MODE` (`gui` default for reliability, `auto`, `silent/headless`), preserving a fully silent option when headless runtime is available.
- New note (2026-02-27): Bootstrap reliability fix for `WinError 10061` timeouts in `auto` mode: if headless launch does not expose `127.0.0.1:9666` within timeout, CoreService now terminates the spawned headless PID, performs an automatic GUI fallback launch, and retries endpoint readiness before failing. Added `R0MM_JDOWNLOADER_BOOT_TIMEOUT` (seconds, clamped `6..180`, default `30`); `auto` uses a short first headless probe window (`6..12s`) before fallback.
- New note (2026-02-27): Fixed Windows launch flags so GUI bootstrap is no longer hidden (`STARTF_USESHOWWINDOW`/`SW_HIDE` now apply only to headless/silent launches). This addresses "did not invoke JDownloader" reports where the process started but no window appeared.
- New note (2026-02-27): JDownloader queue errors now append bootstrap launch context (`mode` + `pid`) when invocation succeeded but `:9666/flashgot` remained unreachable, making endpoint/config failures distinguishable from launch failures.
- New note (2026-02-27): Removed CLI-only dependency for JDownloader runtime controls in PySide6. Tools > Downloads now exposes endpoint override, explicit JDownloader executable path override, bootstrap mode, bootstrap timeout, throughput tuning enable/disable, and tuning profile directly in GUI; selections persist in UI state and are passed to `CoreService.jdownloader_queue_downloads(jd_options=...)` per submission.
- New note (2026-02-27): Added JDownloader local API self-heal flow. On queue endpoint failures, CoreService now auto-repairs `RemoteAPIConfig` (`externinterfaceenabled=true`, `externinterfacelocalhostonly=true`, `deprecatedapienabled=true`), retries bootstrap and one queue handoff retry. Tools > Downloads also exposes a manual `[ Repair JD API ]` button for the same process.
- New note (2026-02-27): JDownloader endpoint probing now tries `127.0.0.1`, `localhost`, and `[::1]`. Repair flow also supports forced controlled restart of JDownloader when config changes require restart for the local FlashGot endpoint to come up.
- New note (2026-02-27): Repair mode now forces GUI bootstrap (even when queue mode is AUTO/HEADLESS) so Extern/FlashGot authorization prompts can be accepted; this avoids silent headless stalls on first authorization.
- New note (2026-02-27): Tools > Downloads restored the Myrient directory browser workflow for link collection (`Add URL...` opens Myrient listing browser) while keeping transfer execution JDownloader-only.
- New note (2026-02-27): AppState now tracks JDownloader transfer progress post-handoff by polling destination `.part`/final files and emitting `download_progress` updates (`QUEUED`/`DOWNLOADING`/`DONE`, inferred speed and percent with async size hints), feeding both Nerve Center Hydra rows and Downloads status list.
- New note (2026-02-27): Added optional JDownloader throughput tuning prior to queue handoff (`R0MM_JDOWNLOADER_TUNE`, default enabled) by updating `GeneralSettings` with profile presets (`conservative|balanced|aggressive`) and logging a restart recommendation when settings changed.
- New instruction (2026-02-27): Never delete files during maintenance/cleanup tasks; move superseded or temporary artifacts into `_del/` instead.
- New note (2026-02-26): Hydra Queue retention logic now treats `ADDED` (JDownloader LinkGrabber handoff) as a terminal state for pruning/rotation, preventing queue-row buildup when sending many links externally.
- New note (2026-02-25): PySide6 Dashboard Command Center now pulls real intel data asynchronously: DAT Syndicate reads local DAT mtimes (OUTDATED > 30 days), Bounty Board uses missing-ROM report stats, Storage Telemetry aggregates filesystem sizes from saved collections/current session via pathlib, and The Wire fetches/parses RSS via urllib/XML with offline fallback (`OFLINE: RSS Feed inativo`).
- New note (2026-02-25): PySide6 Dashboard visual pass upgraded to an industrial telemetry panel: `CardPanel` QSS card chassis (#1A1A1A), semantic badges (`BadgeOk` / `BadgeAlert`), real QProgressBar bounty bars, transparent Wire feed, and Sans-for-UI / JetBrains-Mono-for-data typography split.
- New note (2026-02-25): PySide6 tooltip coverage expanded across MainWindow + Dashboard/Library/Import&Scan/Tools; tooltips are localized and refreshed on locale change. i18n audit also fixed missing Import & Scan keys that were surfacing raw placeholders in the GUI.
- New note (2026-02-25): Nerve Center click logging was deduplicated: `eventFilter()` no longer appends click messages directly to the terminal widget; click lines now arrive only via the runtime-log tail (`monitor_action` -> watcher), yielding one terminal line per click.
- New note (2026-02-27): JDownloader queue handoff is now asynchronous in `AppState` (dedicated `QThread`) and emits `jdownloader_handoff_progress` + `jdownloader_queue_finished` signals. MainWindow shows this as a Nerve Center progress bar/status phase indicator so bootstrap/endpoint waits no longer look like UI hangs.
- New note (2026-02-27): Tools > Downloads now falls back to `https://myrient.erista.me/files` as the default Myrient base URL when building/restoring UI state.
- New note (2026-02-25): ToolsView "Live Console" pane was removed; tool result logging is centralized in the Nerve Center via `state.log_message`. Explicit tab-change logs (sidebar / Library / Tools tabs) now emit directly to `state.log_message` so they reliably appear in the Nerve Center even when generic click-tail logging is intermittent.
- New note (2026-02-25): PySide6 no longer silences stdout/stderr; startup/runtime exceptions and Qt warnings/errors are mirrored to terminal for crash diagnosis.
- New note (2026-02-25): PySide6 Nerve Center rebuilt as 3-column footer (Hardware / Active Operation / Live Console) with GhostTyper prompt inside the terminal frame.
- New note (2026-02-25): Active Operation column now includes path elision (middle truncation), session speed/anomaly telemetry, and an emergency `[ ABORT ]` scan kill switch; Library drawer path labels and organize progress subtitle also gained path overflow guards.
- New note (2026-02-25): Nerve Center footer columns are now wrapped in symmetric QFrame modules (shared black chassis + border); terminal no longer has visual prominence mismatch against hardware/operation blocks.
- New note (2026-02-25): Nerve Center now locks fixed widths for Hardware (220px) and Operation (300px) while Terminal stretches; MainWindow enforces minimum size 1280x720 for GhostTyper/terminal readability.
- New note (2026-02-25): Nerve Center log console now uses semantic colors by prefix (`[*]` green, `[?]` magenta, `[!]` red) and PySide6 views emit dialog/action logs with explicit prefixes for better triage.
- New note (2026-02-25): PySide6 Dashboard replaced by a 4-card Command Center fed asynchronously (`dashboard_data_ready`) from new CoreService intel providers (`fetch_dat_syndicate`, `get_bounty_board`, `get_storage_telemetry`, `fetch_retro_news`).
- New note (2026-03-01): PySide6 Dashboard is now always the initial view on startup (saved `active_view` is ignored). The 4-card layout was repurposed into a workflow home screen: Quick Start, Next Actions, Session Snapshot, and Transfers. The dashboard still uses async local intel (`fetch_dat_syndicate`, `get_bounty_board`, `get_storage_telemetry`) but no longer depends on the retro news fetch for its home-screen refresh path.
- New note (2026-03-01): PySide6 Windows path display was flipped back to native-looking backslashes in UI presentation. `normalize_win_path()` now renders `/` as `\`, and `Import & Scan` Operation Preview (source/destination rows, folder fields, organize-progress tooltip/text) shows `D:\...` without changing underlying path semantics.
 
## SESSION NOTES (2026-02-23)
- User asked how to avoid Flutter load delays: prefer keeping `flutter run` open for hot reload, enable Windows Developer Mode for symlink support, and use `--release` for faster startup.
- Flutter frontend lives in project root (`D:\1 romm\romm`).
- Flutter UI parity work in progress: added AppState, API client, file browser, and real views for Dashboard, Library, Import & Scan, Tools.
- Fixed Flutter type error in `lib/views/library_view.dart` by allowing dynamic row values and stringifying in table cells.
- Fixed Flutter hot-reload LateInitializationError by initializing `AppState` field inline in `lib/main.dart`.
- Applied redesign in Flutter: new forest/sage accents, sidebar styling, status bar, library header with tabs/search, zebra tables, and flatter radii.
- Added Flutter i18n system (EN/PT-BR) with locale selector in bottom-right status bar.
- Fixed missing AppLocale import + const items in `lib/main.dart` locale selector.
- Implemented new desktop UX layout: top bar with breadcrumbs/search, operation panel, redesigned Import & Scan split view with preview table and CTA.
- Fixed Import & Scan left column overflow by making it scrollable.
- Rewrote Import & Scan per latest spec: 3 blocks, DATs list, advanced options inline, preview table, inline errors, no snackbars.
- Enforced EN/PT-BR parity in Flutter strings and updated docs (readme language selection + documentation index).
- Fixed Flutter ToolsView dropdown by removing invalid const items (i18n labels).
- Rewrote PT-BR translations in `lib/state/i18n.dart` to proper Brazilian Portuguese and fixed mojibake encoding.
- Rebuilt `lib/state/i18n.dart` fully in UTF-8 to eliminate mojibake and align EN/PT-BR keys with Import & Scan symmetry spec.
- Added BlindMatch toggle + tooltip and conditional fallback input in Import & Scan with EN/PT-BR i18n parity.
- Fixed Import & Scan Scrollbar error by attaching a dedicated ScrollController.
- Refined Import & Scan Block 2: Expanded vertical stretch, BlindMatch anchored bottom, AnimatedSize reveal above toggle per spec.
- Import & Scan layout fixes: wrapped left/right panels in bounded height using LayoutBuilder + `panelHeight` to avoid unbounded Column/Expanded errors in Flutter.
- Import & Scan left panel refactor: `CustomScrollView` with `SliverFillRemaining(hasScrollBody: false)` so the blank space and `Expanded` live in bounded constraints, eliminating `h<=Infinity`/`RenderBox was not laid out` crashes.
- New instruction: use the “Holy Grail” layout for Import & Scan (LayoutBuilder + SingleChildScrollView + ConstrainedBox(minHeight) + IntrinsicHeight) to eliminate unbounded height issues, keeping 50/50 symmetry and PT-BR UX strings.
- Flutter networking policy: Flutter desktop must run offline by default (no HTTP calls). Only Flask handles network. Flutter network calls are gated by build-time env `R0MM_FLUTTER_NETWORK=true`.
- Audit note: current unbounded flex errors trace to `SliverFillRemaining` + `Column` + `Expanded` in `import_scan_view.dart`; other scroll views use Expanded only in Rows or bounded containers.
- Flutter build issue: `google_fonts` failing due to missing `AssetManifest.bin`; suggested `flutter clean` + `flutter pub get` (tool timeouts in this environment), or delete `build/` + `.dart_tool/` and rebuild.
- Core backend refactor: introduced `rommanager/core_service.py` as the single source of truth; Flask (`rommanager/web.py`) now delegates API logic to the core.

## SESSION NOTES (2026-02-24)
- Flet frontend refactor: DAT import, scan, and collection load now go through `CoreService` (no direct `DATParser`/`FileScanner` usage).
- Flet AppState now references `core.collection_manager` and `core.reporter`.
- PySide6 frontend cleanup: removed unused direct Collection/Reporter imports; uses `CoreService` references only.
- CLI cleanup: collection save/load now uses `CoreService().collection_manager`; removed unused imports.
- Added new i18n keys for scan progress and DAT import status messaging (EN/PT-BR).
- Flutter: removed backend URL label from sidebar; file browser now shows offline path hint and skips backend listing when `networkEnabled` is false.

---

## UNIFIED DESIGN SYSTEM (CRITICAL)

### Single Source of Truth
All frontends consume a **unified Catppuccin Mocha color palette** from `rommanager/shared_config.py`. Do not hardcode colors.

### How Each Frontend Consumes THEME

**Web (Flask/React via CDN):**
- CSS `:root` block defines custom properties (e.g., `--bg`)
- Component styles use `var(--*)` values (no Tailwind color classes)

**Flet (Python/Flutter):**
- Uses backward-compatible `MOCHA` alias dict that maps to `THEME`

**PySide6 (Qt/Windows):**
- Imports THEME directly and applies it in QSS

---

## WEB FRONTEND (`rommanager/web.py`)

### Architecture
- Single Flask + React (via CDN) file
- No npm, no bundler, no build step
- React components defined as JS strings in `render_template_string()`

### Key Components
- ToastProvider / useToast
- Dropzone
- SkeletonTable / SkeletonGrid
- EmptyState
- Poster cards use local placeholder art (no thumbnail API)

---

## FLET FRONTEND (`rommanager/gui_flet.py`)

### Architecture
- Single file
- Entry point: `main(page)`
- Uses `MOCHA` alias for colors

### Critical Fix (Feb 2026)
- `ft.Button` does NOT support `icon_size` (only `ft.IconButton`)

---

## PYSIDE6 FRONTEND (`rommanager/gui_pyside6.py`)

### Architecture
- Single file
- Uses THEME directly
- Detail panel uses letter placeholder art (no thumbnails)

---

## I18N TRANSLATIONS (`rommanager/i18n.py`)

Use `_tr("key_name")` for all user-visible strings in frontends.

---

## COMMON PATTERNS & GOTCHAS

### ✅ DO
- Import THEME from `shared_config.py` in all frontends
- Use CSS custom properties (`:root` vars) in Web frontend
- Use `_tr()` for all user-visible strings
- Test each frontend independently before committing

### ❌ DON'T
- Hardcode hex colors
- Add remote acquisition features or network fetchers (except the user-authorized, rate-limited `MyrientFetcher` integration)
- Use `icon_size` on `ft.Button`

---

## ARCHIVED LEGACY FILES

Legacy acquisition-related files are prefixed with `OLD_` in both code and docs.

---

## SESSION NOTES (2026-02-27)
- PySide6 Tools > DAT Operations now uses a dedicated DAT Downloader panel (No-Intro, Redump, TOSEC mirrors via libretro catalog endpoints).
- DAT Downloader supports quick one-step download by DAT name or direct URL (`Download by Name/URL`), with best-match lookup and optional auto-import into DAT Library.
- DAT family detection now runs after download/import and tags No-Intro/Redump/TOSEC where possible.
- EN/PT-BR i18n keys and tooltips were expanded for the new DAT Downloader quick-flow.
- DAT downloader execution moved to its own async task queue in AppState (separate from generic tools worker), preventing false "busy operation" blocking when users trigger quick search/refresh repeatedly.
- DAT downloader performance optimizations: shorter network timeouts, per-family catalog cache, and parallel fetch for `All` family mode.
- DAT import usability fix: importing from path now auto-loads the DAT into active matcher; downloader auto-import path also auto-loads by default.
- Superseded by later split: Import & Scan no longer hosts DAT import/deletion actions.
- PySide6 DAT workflow was re-split: left navigation label changed to `Collection`/`Coleção`; `Import & Scan` now only enables/disables DATs for next scan, while full DAT library management (import file/folder, activate/deactivate, delete, open downloads folder) lives in `Tools > DAT Operations`.
- DATLibrary now auto-discovers DAT-like files recursively under `data/dats` (including subfolders) and surfaces them in `dat_library_list()` even if they were copied manually outside import actions.
- DAT toggling now supports button/context-menu/double-click flows and surfaces parse-invalid DATs as `[ERR]`; enabling invalid entries is blocked with explicit user feedback instead of silent failure.
- DAT parser now supports clrmamepro plain-text DAT files (in addition to XML), fixing invalidation of downloader-generated sets such as `Sega - Mega Drive - Genesis.dat`. DATLibrary refresh now revalidates entries marked invalid/with parse errors so existing index rows recover automatically after parser fixes.
- DAT import/downloader flow now avoids copy-induced duplicate entries when the DAT source file is already inside `data/dats` (including `_downloads`), and PySide6 DAT list rendering now collapses duplicate identities so OFF duplicates are hidden whenever an equivalent ON entry exists.
- Nerve Center Operation module now surfaces scan activity explicitly: AppState emits immediate scan-running status on scan start, and MainWindow renders a dedicated scan progress indicator (indeterminate startup + `current/total` progress bar) so scans are visibly active from the first moment.
- Nerve Center scan indicator styling was aligned to the app terminal motif: the scan bar now renders as a JetBrains-Mono ASCII progress line in the Operation module (instead of a native-looking progress widget), without changing scan-state behavior.
- Scan pipeline telemetry now reports phase-aware progress (`scan` vs `compare`) through the existing status/progress channels; Nerve Center displays an explicit compared-files counter (`Compared X/Y`) during DAT matching.
- `MultiROMMatcher` matching path was optimized for multi-DAT workloads by maintaining merged global hash indexes (CRC+size/MD5/SHA1), keeping deterministic first-loaded precedence while avoiding per-DAT iteration per scanned file.
- File scanning now skips obvious non-ROM extensions (docs/media/source/binaries) by default, while still scanning known ROM extensions, ZIP archives, and extensionless files for compatibility.
- AppState now emits live `results_changed` updates during scan `compare` phase (throttled), so Library identified/unidentified rows populate progressively instead of only at scan completion.
- Core scan compare path now updates `identified`/`unidentified` incrementally per compared file (including BlindMatch compare-phase loop), enabling real-time result streaming to the UI.
- Local test fixture folder `TESTE/` was created in workspace for recursive mixed-content scan validation against currently loaded DATs.
- Scanner file discovery now runs as a streaming iterator (instead of building a full file list first), reducing long "starting scan" stalls on very large recursive folders and emitting progress from the first discovered file.
- New Local DAT overlay flow implemented: Collection > Unidentified now has `Add to Local DAT`, opening a bulk metadata editor and persisting user-curated entries to `data/dats/_local/R0MM - Local Overrides.xml` (auto-import + auto-load + rematch).
- CoreService now provides metadata-assist APIs for this flow: local suggestions from loaded DAT corpus (`suggest_local_dat_metadata`) and optional online hints (`fetch_online_metadata_hints`, Wikipedia OpenSearch, timeout/restriction-safe errors for offline/firewalled environments).
- Per-DAT editable overlays: Collection > Unidentified supports `Add to DAT (_EDIT_)`, letting the user edit all fields (game/ROM/system/region/CRC/MD5/SHA1/size/status) and append them to a derived `_EDIT_<original>.dat` that auto-imports/loads/rematches on save (one `_EDIT_` per source DAT).

---

## QUICK REFERENCE

| Item | Location |
|------|----------|
| Design System (THEME) | `rommanager/shared_config.py` |
| Web Frontend | `rommanager/web.py` |
| Flet Frontend | `rommanager/gui_flet.py` |
| PySide6 Frontend | `rommanager/gui_pyside6.py` |
| Translations | `rommanager/i18n.py` |
| Design Doc | `docs/plans/2026-02-23-unified-design-system-design.md` |
| Implementation Plan | `docs/plans/2026-02-23-unified-design-system.md` |
| Project Root | `D:\1 romm\romm` |

---

**Last Updated**: 2026-02-27  
**Status**: Active frontends are Web, Flet, PySide6  
**Next Agent**: Use this prompt to onboard and maintain project continuity
