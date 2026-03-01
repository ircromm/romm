# R0MM ver 0.30rc

Web-Based ROM Organization System

---

## Recent Changes (2026-03-01)
- Fixed a PySide6 Tools tab crash when clicking "Refresh" in Collections/DATs (missing AppState refresh aliases).
- Fixed torrent search button stuck state and invokeMethod warnings in PySide6 Downloads tab.
- PySide6 now prompts on startup to optionally restore the previous session (layout, tabs, last collection) for faster cold starts.
- Restored a working torrent searcher in the Downloads tab with selectable Apibay/custom mirrors; magnets are sent to the JD queue.
- Downloads tab split into Torrent (search + magnets) and Direct/JD (Myrient catalog + JDownloader queue) sub-tabs.
- Downloads tab layout is now responsive for non-maximized windows: Torrent uses a compact control grid, Direct/JD uses a horizontal-or-vertical splitter, and the selected sub-tab plus staged inputs persist in UI state.
- Dashboard is now always the initial view on startup and was refocused into a real home screen: quick start, next actions, session snapshot, and transfer status, without the old news-feed dependency.
- Windows path display in PySide6 was normalized visually to backslashes in `Import & Scan` Operation Preview and related elided labels/tooltips, so `D:/...` now renders as `D:\...`.
- Temporary local runtime artifacts under `.tmp/` are now ignored by Git so repository snapshots stay clean.


## Desktop launch modes

You can also start desktop interfaces directly:

- `python main.py --flet`
- `python main.py --pyside6`
- `python main.py --gui`
- `python -m rommanager` (opens launcher selector with all desktop modes)

PySide6 UI files:
- `rommanager/gui_pyside6_views.py`
- `rommanager/gui_pyside6_style.qss`

Backup options:
- Full backup to `backups/` (zip, timestamped).
- Incremental-friendly backup that excludes `build/`, `.dart_tool/`, `.venv/`, and `backups/`.
- Script: `backups/backup.ps1` (run with `powershell -ExecutionPolicy Bypass -File backups/backup.ps1`).

## Local Agent Access & Autonomy (Developer Sessions)

This project is frequently edited with a local coding agent. What the agent can test is determined by the session runtime (sandbox, GUI support, approvals), not only by repository code.

What the agent can usually do in a standard local session:
- Read and edit files inside the invoked project folder.
- Run shell commands and project scripts (subject to sandbox/approval policy).
- Run headless/smoke checks (imports, `py_compile`, CLI commands, `QT_QPA_PLATFORM=offscreen` tests).
- Analyze terminal tracebacks and runtime logs.

What may still be limited even with full repository access:
- Interactive desktop GUI validation (PySide6/Flet) if the session does not provide GUI control/desktop streaming.
- Visual click-through testing unless the session supports screenshots + input events or remote desktop control.
- Installing dependencies or fetching online resources if network access is disabled.

To maximize agent autonomy in a trusted local session:
- Use a session mode with unrestricted filesystem access (or equivalent full access) for the project workspace.
- Enable network access when installs/updates/docs lookup are required.
- Allow command execution without repeated prompts, or approve persistent command prefixes used in this repo.
- Prefer the project virtual environment Python (`.venv\\Scripts\\python.exe`) for all validation commands.

Recommended recurring command approvals/prefixes (if your session supports them):
- `git`
- `.venv\\Scripts\\python.exe`
- `py`
- `pytest`
- `flutter`

PySide6/Flet validation notes:
- The agent can launch the process and capture terminal output/crashes.
- The agent can perform headless smoke tests where supported.
- Full visual verification still requires a GUI-capable session or user-provided screenshots/logs.

Runtime/tool prerequisites for deeper testing:
- Python dependencies installed (`PySide6`, `flet`, `flask`, etc.).
- External tool binaries available in `PATH` when testing Tools features (for example `chdman`, `dolphin-tool`).
- Small DAT/ROM fixtures for reproducible import/scan tests.

Practical workflow when GUI control is unavailable:
- Let the agent patch code and run headless checks.
- Run the desktop app locally and share traceback/log/screenshot output.
- The agent uses the observed runtime error to apply the next fix quickly.

---

## 1. Overview

R0MM ver 0.30rc is a **web application** for scanning, identifying, analyzing, and organizing ROM collections using DAT files (XML/Logiqx and clrmamepro text DAT).

It supports:

* No-Intro
* Redump
* TOSEC
* XML-based DAT format (Logiqx-compatible)
* Plain text DAT format (clrmamepro style)

The system consists of:

* A **Flask backend**
* A **React-based frontend**
* ROM scanning + CRC32 hashing
* DAT parsing and matching engine
* Organization strategies with preview and undo
* Collection completeness analysis

The application runs locally and exposes a web interface.

---

## 2. Architecture

### Backend: Flask Application

Core modules identified in the project:

* `models` – data structures
* `parser` – DAT parsing (XML + clrmamepro text)
* `scanner` – filesystem ROM scanning + hashing
* `matcher` – ROM ↔ DAT matching logic
* `utils` – helpers
* `shared_config` – configuration layer
* `router` – API endpoints
* `config` – runtime config
* `run_server()` – server bootstrap

The server starts on:

```
127.0.0.1
```

Default Flask configuration uses:

* host
* port
* debug
* threaded

The backend exposes API endpoints consumed by the frontend.

---

### Frontend: React Interface

Single-page interface rendered into `#root`.

Main sections:

1. Identified ROMs
2. Unidentified Files
3. Missing ROMs
4. Organization Controls

UI is styled using Tailwind-like utility classes.

---

## 3. Core Functionalities

### 3.1 DAT Loading

* Accepts XML DAT and clrmamepro text DAT files
* Parses games and ROM entries
* Extracts metadata:

  * Game name
  * ROM name
  * System
  * Region
  * Size
  * CRC32

---

### 3.2 ROM Scanning

Scans selected folder and computes:

* File size
* CRC32 hash
* Filename
* Path

Files are matched against loaded DAT entries.

---

### 3.3 Matching Results

Results are separated into three logical groups:

#### Identified

ROMs successfully matched against DAT:

Columns shown:

* Original file
* ROM name
* Game
* System
* Region
* Size
* CRC32
* Status

---

#### Unidentified

Files scanned but not matched:

Columns:

* Filename
* Path
* Size
* CRC32

Selectable for further action.

---

#### Missing

DAT entries not found in collection.

Includes completeness stats:

* Total in DAT
* Found count
* Percentage complete
* Visual progress bar

---

## 4. Organization Engine

User-selectable organization strategies:

| Strategy ID        | Description                           |
| ------------------ | ------------------------------------- |
| `system`           | Per-system folders                    |
| `1g1r`             | 1 Game 1 ROM (best version selection) |
| `region`           | Region-based folders                  |
| `alphabetical`     | A-Z folders                           |
| `emulationstation` | ES / RetroPie layout                  |
| `flat`             | Rename only (no subfolders)           |

---

Note: Organization output paths are sanitized for Windows-safe filenames (invalid characters like `:` or `?` are replaced). Preview mirrors the sanitized destination paths.

### Actions

Two file operations supported:

* Copy
* Move

---

### Workflow

1. Load DAT
2. Scan ROM folder
3. Review identified / unidentified / missing
4. Select strategy
5. Set output folder
6. Choose Copy or Move
7. Click:

   * Preview (dry run)
   * Organize! (execute)
8. Optional: Undo

---

## 5. Organization Controls

UI includes:

* Output folder field
* Strategy selector
* Action selector (Copy / Move)
* Preview button
* Organize button
* Undo button

Preview prevents accidental destructive operations.

Undo reverses last organization action.

## 5.1 Tools UI (PySide6)

Tools actions are wired to core service methods. Some advanced tools currently return a
“not implemented” response until the core implementations are completed.

Core tool contracts (stubs with type hints + docstrings):
- DAT Diff (Compare)
- DAT Merger
- Batch Convert (CHD/RVZ)
- Apply TorrentZip
- Deep Clean (Remove Junk)
- Find Duplicates (By Hash)

Tool implementations:
- DAT diff/merge implemented in Python.
- Batch convert requires external binaries in PATH: `chdman` (CHD) and `dolphin-tool` (RVZ).
- TorrentZip uses a deterministic ZIP repack (no external dependency).

---

## 6. Completeness Tracking

For loaded DAT:

* Total entries in DAT
* Matched entries
* Percentage calculation
* Visual progress bar

This allows tracking full-set completion.

---

## 7. Web Server Execution

Entry function:

```
run_server()
```

Prints:

* Host
* Port
* URL ([http://127.0.0.1:PORT](http://127.0.0.1:PORT))
* Stop instruction (Ctrl+C)

The app runs as a local web service.

---

## 8. Intended Use Case

Designed for users who:

* Maintain multi-system ROM collections
* Use curated DAT sets
* Want structured organization
* Want completeness visibility
* Need deterministic matching (CRC-based)

---

## 9. Key Technical Characteristics

* DAT parsing (XML + clrmamepro text)
* CRC32 matching
* Browser-based UI
* Flask REST backend
* Modular architecture
* Strategy-based file output
* Undo capability
* Preview safety layer

---

## 10. Version Identifier

Displayed in footer:

```
R0MM ver 0.30rc
```

Indicates this is a second-generation web-based rewrite, likely replacing a previous CLI or desktop version.

---

## 11. Summary

R0MM ver 0.30rc is a local web application that:

* Parses DAT files
* Scans ROM collections
* Matches via CRC32
* Displays identified, unidentified, and missing ROMs
* Calculates completeness
* Organizes ROMs using selectable strategies
* Supports preview and undo
* Runs via Flask on localhost

It is a full-stack ROM management tool intended for structured archival organization.

---

## 12. Language Selection

The app now includes a language selector in desktop menus:
- **English** (default)
- **Português Brasileiro**

Where to change:
- Launcher window: `Language` menu
- Tkinter desktop app: `Language` menu
- Flet desktop app: language dropdown in the left navigation panel
- PySide6 desktop app: language dropdown in the status bar

Default language at startup is **English**.

Language switching refreshes labels in the PySide6 Import/Scan view (including section titles) and the drawer feedback.

Module entry behavior:
- `python -m rommanager` always opens the visual mode selector (launcher).


## 13. BlindMatch mode

BlindMatch allows scanning without any DAT file.

How it works (best effort):
- User provides the system name (for example: SNES).
- The app infers region from filename tokens such as `(U)`, `US`, `(E)`, `(J)`, `BR`, etc.
- All scanned files are treated as identified in this mode.
- There are no "missing ROMs" and no "unidentified" results in BlindMatch mode.

Available in:
- CLI: `--blindmatch-system <SYSTEM>`
- Web UI: BlindMatch system field in scan section
- Tkinter UI: BlindMatch toggle + system input
- Flet UI: BlindMatch toggle + system input

## 15. Advanced Settings foundation

R0MM now includes a shared settings foundation (`~/.rommanager/settings.json`) used by CLI, Tkinter, Flet and Web runtime initialization.

Implemented foundations:
- Collection profiles by objective: historical_preservation, mister_playset, retroarch_frontend, full_set_no_hacks.
- Region/variant policy (global + per-system priority).
- Naming template engine for organized output (`{name}`, `{game}`, `{region}`, `{system}`, `{crc}`).
- Optional curated metadata database support (CLI: `--metadata-db`).
- Audit trail logging for organization actions (`~/.rommanager/logs/audit.log`).
- Collection health checks (duplicates, unknown extension, missing/zero files) via CLI `--health-check`.
- Museum organization strategy (`museum`) for generation/system/region hierarchy.
- Accessibility settings placeholders (font scale, high contrast, dense tables, reduced motion).

CLI additions:
- `--settings-file <path>`
- `--profile <preset_name>`
- `--health-check`
- `--metadata-db <path>`

## 16. Flet Stability Protocol (Mandatory)

When changing Flet desktop UI (`rommanager/gui_flet.py`), follow the protocol in:

- `docs/FLET_AGENT_PROTOCOL.md`

This is mandatory to prevent regressions like:

- `'Page' object has no attribute 'open'`

Minimum rule set:
- Treat Flet API usage as version-sensitive.
- Do not ship dialog/overlay changes without compatibility fallback.
- Document compatibility risk and manual validation steps in each PR.

---

## UI Notes (PySide6)

* Cyberpunk Industrial theme: base #1E1E1E, surface #2D2D2D, accents #39FF14, alerts #FF00FF.
* Library drawer is persistent; empty state remains visible when no row is selected.
* Drawer alert border toggles for Unidentified/Missing selections.

* Nerve Center now displays a live log monitor that tails the runtime log file in real time (tab changes, scans, and errors are logged).

* Nerve Center includes a GhostTyper easter egg (retro quotes typing animation) above the live log monitor.

* PySide6 no longer silences terminal output; startup/runtime exceptions and Qt warnings/errors are printed to stderr, while runtime logs remain mirrored in the Nerve Center log monitor.
* Fixed PySide6 startup crash in Nerve Center by initializing `ghost_label` before binding `GhostTyper`.
* Nerve Center refactored into 3 aligned columns (Hardware, Active Operation, Live Console) and now embeds the GhostTyper prompt line inside the terminal frame.
* Dashboard tab no longer duplicates system monitors; global runtime telemetry lives only in the Nerve Center footer.
* Active Operation column now includes path elision (fixed-width middle truncation), session speed/anomaly telemetry, and an emergency `[ ABORT ]` kill switch for long scans.
* Proactive path overflow guards were added to PySide6 labels that display file paths (Library drawer details and organize progress subtitle).
* Nerve Center columns are now encapsulated as symmetrical module frames (shared `#090909` chassis + border) to remove the floating-text/gridline mismatch and unify visual weight.
* Nerve Center sizing is now constrained (Hardware 220px, Operation 300px fixed; Terminal expands), and PySide6 main window enforces `setMinimumSize(1280, 720)` to preserve GhostTyper/terminal readability.
* Nerve Center event stream now uses semantic log colors by prefix: `[*]` green (normal/navigation), `[?]` magenta (user interaction/dialog waits), `[!]` red (critical/error).
* PySide6 Dashboard was rebuilt as a 4-card Command Center (DAT Syndicate, Bounty Board, Storage Heatmap, The Wire) with industrial telemetry cards (`CardPanel` depth `#1A1A1A`, square borders, green/magenta badges).
* Dashboard data now loads asynchronously via `AppState.refresh_dashboard_intel()` using real CoreService intel providers (local DAT age checks, missing-ROM bounty stats, filesystem storage telemetry from saved collections/current session, and live RSS parsing with offline fallback).
* PySide6 Dashboard Bounty Board now uses real `QProgressBar` telemetry bars (no ASCII bars), DAT statuses render as semantic badges, and The Wire feed blends into the card with a transparent terminal surface.
* PySide6 typography was tightened for telemetry readability: global UI font is now Sans-Serif, while JetBrains Mono is reserved for data surfaces (tables, logs, paths, hashes, dashboard telemetry values).
* PySide6 GUI now applies localized tooltips across main navigation, Dashboard, Library, Import & Scan, and Tools panels (including heavy-operation controls), with tooltip text refreshed on language change.
* PySide6 i18n audit fixed missing keys that were leaking raw placeholders in Import & Scan (`DAT add`, `scan`, `scan archives`, BlindMatch placeholder/help, folder selection titles); visible dialog filter labels now reuse localized UI strings.
* Nerve Center click logging no longer duplicates lines: global click events are now written once via `monitor_action(...)` and displayed only through the runtime-log tail (the direct console append path for clicks was removed).
* Tools tab no longer contains its own "Live Console"; tool results/logs are now centralized in the Nerve Center monitor only.
* Tab changes (main sidebar, Library tabs, Tools tabs) now emit directly through `state.log_message`, guaranteeing they appear in the Nerve Center even if the runtime-log tail misses generic click events.
* Policy exception added for a user-authorized, rate-limited `MyrientFetcher` integration (strict max 4 concurrent connections, graceful halt support).
* Nerve Center Active Operation column now supports a "Hydra Queue" (up to 4 dynamic Myrient transfer lines) with `[ HALT TRAFFIC ]` control, wired to `AppState.download_progress` and `halt_traffic()`.
* ToolsView now includes a dedicated `Downloads` tab for Myrient/Hydra workflows (output folder + URL list parser with optional `URL | custom-filename`, queue action, local status list, and halt button).
* Downloads tab now includes guided line creation (`Add URL...`) and a Myrient listing-based link resolver (`Base URL` + `Resolve Missing -> Queue`) that can match Missing ROM rows against a Myrient directory index and auto-send matches to the Hydra Queue.
* `Add URL...` now opens a dedicated Myrient directory browser modal (async listing load, folder navigation, filter, multi-select) and appends selected file links into the Downloads queue input.
* Downloads tab now also includes an inline `Myrient Catalog` panel that splits a loaded listing into `Systems` (directories) and `DAT` files, lets the user browse a selected system directory, and sends selected files directly to the Hydra Queue.
* Myrient catalog no longer depends on manual base URL entry: the app now ships with built-in Myrient root presets and auto-detects/auto-loads a working catalog root when the **Myrient Catalog drawer is opened** (manual base URL remains as an advanced override).
* The `Myrient Catalog` is hidden by default inside a drawer (toggle-open on demand); root loads auto-select the first system and auto-load its entries. Myrient listing parsing was hardened (anchors with/without quotes and directory detection via link text).
* Fixed false "Another operation is already running" conflicts in the downloader: Myrient directory listing / link-resolution now run on a dedicated Myrient worker queue (separate from the generic Tools worker), so root->system autoload chaining and downloader actions no longer trip the generic busy guard.
* LibraryView (Missing tab) now exposes a `Get Links` action that sends selected (or optionally all visible) missing rows to `Tools > Downloads`, where they can be resolved/queued for Myrient download.
* Heartbeat polling disabled; status updates are event-driven.
* GhostTyper now includes a blinking cursor animation.

* GhostTyper cursor uses a thin glyph for a lighter blink.

* Nerve Center log monitor is per-session only (starts at end of log file on launch).

* Nerve Center height fixed across views; GhostTyper line and log monitor share a seamless surface (no separator).

* Nerve Center monitor and GhostTyper line share the same dark gray surface to avoid visual separation.

* Nerve Center log monitor now records all user clicks via a global event filter.

* Nerve Center height reduced by ~30% and click events mirror instantly into the on-screen monitor.

* GhostTyper label now uses explicit JetBrains Mono styling with solid #39FF14 and transparent background.

* GhostTyper moved under Database Health; Nerve Center log monitor now matches the app background.

* Myrient downloader throughput tuned: progress updates are now throttled (reducing PySide6 UI/event-loop spam), download chunks increased to 1 MiB, and fresh downloads skip the preflight HEAD request (HEAD is still used for resume/size checks).

* `HALT TRAFFIC` no longer leaves the downloader permanently latched off; a new batch clears the halt flag automatically after active jobs drain.

* Myrient downloader backend was reworked to use local `rclone.exe` (`copyurl`) instead of the Python HTTP transfer loop. Hydra Queue and the Downloads tab remain the same UX, but transfers now run through `rclone` with the same 4-slot queue limit and a single-stream-per-file profile (`--multi-thread-streams 1`) to respect Myrient guidance.

* The PySide6 downloader still drives live Hydra Queue / Downloads status rows, but progress/speed are now inferred from local file growth while `rclone` runs (avoiding stdout progress parsing stalls).

* PySide6 now persists UI state into `data/settings.json` (`ui_state.pyside6`) with autosave + flush on close: main window geometry/view/language/search, Library tab + splitter, Import & Scan form inputs/toggles, and Tools fields (including Downloads URLs/base URL/output folder/catalog drawer + tabs). The app restores these values on next launch.

* Myrient/rclone downloads now write explicit per-file runtime log lines (`start`, `done`, `halted`, `error`) via `monitor_action`, so the Nerve Center and `data/logs/runtime-YYYY-MM-DD.log` capture the real failure reason instead of only generic `ERROR` statuses.

* On Myrient `fN.erista.me` connection/timeout failures, the rclone downloader now retries automatically once against `myrient.erista.me` (same path) before surfacing an error. The Downloads list also shows a shortened error reason inline and keeps the full rclone error text in the item tooltip.

* Myrient/rclone transport now normalizes queued/catalog URLs to the canonical `myrient.erista.me` host before download (avoiding brittle direct `fN.erista.me` links), uses `--multi-thread-streams 0` to respect the FAQ guidance (one connection/chunk), and enables rclone `copyurl` compatibility flags (`--disable-http2`, `--bind 0.0.0.0`, `--user-agent curl`) with short retries/timeouts so failures surface quickly in the UI/logs.

* Myrient transfers now prefer the FAQ-aligned `rclone` HTTP remote path (`copyto --http-url ... :http:...`) instead of `copyurl` for Myrient file downloads. This keeps R0MM on the supported rclone HTTP-remote workflow while preserving exact destination filenames and the same Hydra Queue UX.

* When `rclone` reports a Myrient CDN timeout on a redirected host (for example `f3.erista.me`), R0MM now parses the failing URL from the rclone error line and performs limited automatic CDN host hopping (`fN -> fM`, same path) before surfacing the error. This mitigates route-specific failures where one Myrient file server is unreachable but others are fine.

* After runtime logs showed every Myrient timeout failing on `dial tcp4 ...` even across CDN host hops, the rclone compatibility profile stopped forcing `--bind 0.0.0.0` (IPv4-only source bind). R0MM now leaves source-address selection to the OS so Windows can use the best available route/protocol (including IPv6 where available).

* If Myrient downloads still fail after rclone retries/CDN host-hop attempts, R0MM can hand off to the Windows native HTTP stack (`PowerShell Invoke-WebRequest`) as a secondary transport fallback. This fallback is now **opt-in** via environment variable `R0MM_ENABLE_PS_IWR_FALLBACK=1` so default downloader behavior remains fully rclone-based for better throughput.

* The Downloads tab now runs in JDownloader-only mode (local Flashgot/Extern API at `127.0.0.1:9666`). The Hydra/rclone download actions were removed from the UI; queue submission is now only through `[ SEND TO JDOWNLOADER ]`.
* The Downloads tab now includes `[ DOWNLOAD JDOWNLOADER ]`, which opens the official JDownloader download page in the default browser for quick setup on fresh machines.
* The Myrient directory browser was restored in `Add URL...` so links can be picked directly from Myrient listings and appended to the JDownloader queue input.
* JDownloader enqueue now probes local endpoint variants (`127.0.0.1` / `localhost`) and returns actionable diagnostics when unreachable (instead of only raw socket refusal), including an explicit hint to enable/check Extern/FlashGot on `:9666`.
* Endpoint error diagnostics now include bootstrap launch context (mode/PID) when R0MM successfully invoked JDownloader but `:9666/flashgot` did not answer.
* Tools > Downloads now exposes a GUI runtime panel for JDownloader (endpoint override, explicit `JDownloader2.exe` path override, bootstrap mode, bootstrap timeout, throughput-tuning toggle, and tuning profile). These settings are persisted in PySide6 UI state and applied per-queue submission without requiring CLI/env configuration.
* The queue path now includes automatic local API self-heal on endpoint failures: R0MM updates JDownloader `RemoteAPIConfig` (Extern enabled + localhost-only + deprecated API enabled), retries bootstrap, and automatically retries queue handoff once before surfacing an error.
* Tools > Downloads includes `[ Repair JD API ]` to trigger the same self-heal manually from GUI.
* Local endpoint probing now also includes IPv6 localhost (`[::1]`) alongside `127.0.0.1`/`localhost` to avoid false negatives on systems where JDownloader binds only IPv6 loopback.
* API repair can now force a controlled JDownloader restart when config changes require restart before `:9666/flashgot` becomes reachable.
* During repair, R0MM forces a GUI bootstrap attempt to surface any JDownloader permission prompts that cannot be accepted in headless mode.
* If the local JDownloader endpoint is down, R0MM now attempts automatic local bootstrap: it tries to locate `JDownloader2.exe` using `R0MM_JDOWNLOADER_BIN`, PATH, Windows uninstall registry entries, and common install folders, then starts it in background before retrying queue handoff.
* Bootstrap binary resolution now rejects non-executable registry artifacts (for example `.ico` `DisplayIcon` values) and only accepts trusted launcher names (`JDownloader2.exe`/`JDownloader.exe`), preventing `WinError 193` on auto-start.
* Bootstrap mode is configurable via `R0MM_JDOWNLOADER_BOOT_MODE`: `gui` (default, launches JDownloader executable directly), `auto` (tries headless first and, if `:9666` does not come up in time, terminates the spawned headless process and retries with GUI), or `silent`/`headless` (no GUI fallback).
* Windows launch visibility fix: hidden-window startup flags are applied only to headless/silent launches. GUI launches are no longer hidden.
* Bootstrap wait timeout is configurable with `R0MM_JDOWNLOADER_BOOT_TIMEOUT` (seconds, clamped to `6..180`, default `30`). This controls how long R0MM waits for `127.0.0.1:9666` before switching/failing.
* In `auto`, the first headless readiness window is intentionally short (`6..12s`) to avoid long stalls before GUI fallback.
* AppState now monitors JDownloader handoff targets by polling destination files (`.part`/final) and emits live `download_progress` updates (`QUEUED`/`DOWNLOADING`/`DONE` + inferred speed and percent when size hints are available), so Nerve Center and Tools status rows reflect ongoing JDownloader transfers.
* R0MM now applies an optional JDownloader throughput tuning profile before enqueue (`R0MM_JDOWNLOADER_TUNE=1`, default on). Default `balanced` profile sets `maxsimultanedownloads=4`, `maxsimultanedownloadsperhost=4`, `maxdownloadsperhostenabled=true`, `maxchunksperfile=4`, and disables JD speed limiter. Profile can be changed with `R0MM_JDOWNLOADER_TUNE_PROFILE=conservative|balanced|aggressive`.
* Nerve Center Hydra Queue now recognizes JDownloader handoff rows as terminal `ADDED` states (`[JD ] ... LINKGRABBER`), and rotates/prunes them like other completed statuses to prevent row buildup during large batch submissions.
* JDownloader queue submission now runs asynchronously in PySide6 (`QThread`) and emits handoff phase progress events (`prepare/bootstrap/collect/enqueue/repair/retry/done/error`) so the UI remains responsive during bootstrap/endpoint waits.
* Nerve Center Operation module now shows a dedicated handoff progress bar/status line while JDownloader queue submission is in progress; this prevents the app from looking frozen during long bootstrap checks.
* Tools > Downloads now defaults the Myrient base URL to `https://myrient.erista.me/files` (also used as fallback when restored UI state has an empty base URL).
* Tools > DAT Operations now replaces "DAT Sources" with a dedicated `DAT Downloader` panel. The app fetches DAT catalogs for No-Intro, Redump, and TOSEC (libretro mirrors), allows multi-select download, recognizes DAT family, and can auto-import downloaded files into the local DAT Library.
* DAT Downloader now supports one-step quick download by name or URL: user types the desired DAT (for example `Nintendo - SNES`) and clicks `Download by Name/URL`; R0MM resolves best match in the selected family and downloads/imports automatically.
* DAT Downloader tasks now run on a dedicated async queue (separate from generic Tools workers), removing false "Outra operação já está em andamento" conflicts in quick-search/refresh flows and reducing wait time with cached + parallel family catalog fetches.
* Imported DATs are now automatically loaded into the active matcher in PySide6 flows (manual import path and downloader auto-import), so the app uses them immediately without requiring a second manual load step.
* Import & Scan no longer performs DAT import/deletion; it is now focused on selecting which DATs are ON/OFF for the next scan.
* Sidebar naming update (PySide6): `Library` is now `Collection` / `Coleção` in the main left navigation.
* DAT flow split (PySide6): `Import & Scan` now only toggles DATs ON/OFF for the next scan; all DAT management (import file/folder, enable/disable, delete with confirmation, open DAT download folder) is centralized in `Tools > DAT Operations`.
* DAT library discovery now includes all DAT-like files recursively under the app DAT folder (`data/dats` and subfolders), so dropped files appear automatically in the DAT Library list.
* DAT toggle UX now supports all three interaction paths (button, context menu, and double-click) and marks invalid entries as `[ERR]` with clear feedback when enabling is blocked by parse errors.
* DAT parser now supports clrmamepro plain-text DAT files (including downloader output like Genesis/No-Intro sets). DAT library refresh also revalidates previously invalid entries, so old `[ERR]` rows recover automatically after parser updates.
* DAT import/downloader no longer creates duplicate library rows when the source DAT is already inside `data/dats` (for example `_downloads`); and PySide6 DAT lists now collapse duplicate identities so `[OFF]` clones are hidden while an equivalent `[ON]` entry exists.
* Nerve Center now shows explicit scan activity in the Operation module: an immediate "starting scan" indicator plus a live progress bar/counter (`current/total`) during scanning, so long scans no longer look idle/frozen before first results.
* Nerve Center scan indicator was visually realigned to the terminal aesthetic: scan progress now renders as a mono ASCII bar line (same style family as Disk/DB/Hydra) while preserving the same scan-state behavior (`starting` + live `current/total` updates).
* Nerve Center scan telemetry now exposes scan phases explicitly: `Scanning` (file hashing) and `Comparing` (DAT matching), with a dedicated compared-files counter (`Compared X/Y`) so long multi-DAT scans no longer look stalled after hashing ends.
* Scan startup latency was reduced for large folders: file discovery now streams directly into hashing/matching (no full pre-list pass), so progress leaves "Starting scan..." almost immediately instead of waiting for a complete recursive file list.
* Multi-DAT matching path was optimized for large mixed-system scans: `MultiROMMatcher` now keeps merged global hash indexes (CRC+size / MD5 / SHA1) for O(1) lookup across loaded DATs instead of iterating matcher-by-matcher per file.
* Scanner now skips obvious non-ROM/document/media/source extensions by default while preserving compatibility for known ROM extensions, ZIP archives, and extensionless files; this reduces wasted hashing work in mixed folders.
* PySide6 now updates Library results incrementally during the `Comparing` phase (without waiting for scan completion), so identified/unidentified tables populate live as files are matched.
* A local recursive scan fixture folder `TESTE/` is included in the workspace for smoke tests with mixed content (multi-system ROM-like files, archives, and non-ROM files).
* Collection > Unidentified agora tem `Add to DAT (_EDIT_)`: escolhe o DAT ativo, edita todos os campos (jogo/ROM/sistema/região/CRC/MD5/SHA1/tamanho/status) e grava num DAT derivado com prefixo `_EDIT_` ao lado do original (auto-import + auto-load + rematch).
* Editor `_EDIT_` inclui assistência de metadados: sugestões a partir dos DATs carregados (fuzzy) e dicas online (Wikipedia OpenSearch; falha tratada quando offline), sempre com escolha explícita do usuário antes de gravar.
