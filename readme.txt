# ROM Collection Manager v2

Web-Based ROM Organization System

---

## 1. Overview

ROM Collection Manager v2 is a **web application** for scanning, identifying, analyzing, and organizing ROM collections using XML-based DAT files.

It supports:

* No-Intro
* Redump
* TOSEC
* Any XML-based DAT format (Logiqx-compatible)

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
* `parser` – DAT XML parsing
* `scanner` – filesystem ROM scanning + hashing
* `matcher` – ROM ↔ DAT matching logic
* `downloader` – DAT download support
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

* Accepts XML-based DAT files
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

* XML-based DAT parsing
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
ROM Collection Manager v2
```

Indicates this is a second-generation web-based rewrite, likely replacing a previous CLI or desktop version.

---

## 11. Summary

ROM Collection Manager v2 is a local web application that:

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

## 12. Download Engine

The application downloads ROMs from Myrient (myrient.erista.me) sequentially, one file at a time — matching how a browser downloads files.

### Key features:

* Single-file sequential downloads (full bandwidth per file)
* Configurable delay between downloads (0-60 seconds, default: 5s)
* Streaming CRC32 verification during download
* Connection pooling with keep-alive for performance
* Pause, resume, and cancel controls
* Automatic retry with exponential backoff

### Configuring download delay:

CLI:
  python main.py --dat nointro.dat --roms ./roms --download-delay 10

GUI:
  Downloads > Download Missing ROMs > "Delay between downloads" spinbox

Web:
  Download dialog > "Delay between downloads" input field

The delay is a courtesy wait between file completions. During each individual download, the connection runs at full speed with no throttling.

---

## 13. Myrient System Catalog

The downloader includes a built-in catalog of ~50 systems mapped to their Myrient URLs, covering:

* Nintendo (NES, SNES, N64, GB, GBA, DS, 3DS, GameCube, Wii, Wii U)
* Sony (PS1, PS2, PS3, PSP, Vita)
* Sega (Master System, Genesis, Saturn, Dreamcast, Game Gear, 32X)
* Microsoft (Xbox, Xbox 360)
* Atari (2600, 5200, 7800, Jaguar, Lynx, ST)
* NEC (PC Engine, SuperGrafx, PC Engine CD, PC-FX)
* SNK (Neo Geo Pocket, Neo Geo CD)
* And many more (Commodore, Bandai, Coleco, Panasonic, Sharp, etc.)
