# Sequential Downloads (Browser-Style) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace parallel download engine with sequential (1 file at a time) downloads with configurable delay between files, matching browser download behavior.

**Architecture:** Remove ThreadPoolExecutor from MyrientDownloader.start_downloads(). Process queue sequentially in a simple loop. Add `download_delay` parameter (0-60s, default 5s) configurable from CLI, GUI, and webapp.

**Tech Stack:** Python (requests, threading for background worker), tkinter (GUI), Flask + React (webapp)

---

### Task 1: Rewrite MyrientDownloader.start_downloads() — Sequential Engine

**Files:**
- Modify: `rommanager/myrient_downloader.py:450-479` (start_downloads method)
- Modify: `rommanager/myrient_downloader.py:11-17` (remove concurrent.futures import)
- Modify: `rommanager/myrient_downloader.py:289-290` (remove _lock)

**Step 1: Remove parallel imports and threading lock**

In `myrient_downloader.py`, remove the concurrent.futures import and the threading lock:

Remove from imports (line 17):
```python
from concurrent.futures import ThreadPoolExecutor, wait
```

Remove from `__init__` (line 290):
```python
        self._lock = threading.Lock()
```

**Step 2: Rewrite start_downloads() to be sequential with download_delay**

Replace the entire `start_downloads` method (lines 450-479) with:

```python
    def start_downloads(self,
                        progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
                        download_delay: int = 5) -> DownloadProgress:
        """
        Execute downloads SEQUENTIALLY, one file at a time (browser-style).

        Args:
            progress_callback: Called when progress changes.
            download_delay: Seconds to wait between downloads (0-60, default 5).
        """
        self._cancel_flag = False
        self._pause_flag = False

        download_delay = max(0, min(60, download_delay))

        progress = DownloadProgress(total_count=len(self._queue))

        for i, task in enumerate(self._queue):
            if self._cancel_flag:
                task.status = DownloadStatus.CANCELLED
                progress.cancelled += 1
                self._safe_callback(progress, progress_callback)
                continue

            # Wait if paused
            while self._pause_flag and not self._cancel_flag:
                time.sleep(0.5)

            # Delay between downloads (skip before first file)
            if i > 0 and download_delay > 0 and not self._cancel_flag:
                for _ in range(download_delay * 2):  # Check cancel every 0.5s during delay
                    if self._cancel_flag or self._pause_flag:
                        break
                    time.sleep(0.5)
                # Re-check pause after delay
                while self._pause_flag and not self._cancel_flag:
                    time.sleep(0.5)

            if self._cancel_flag:
                task.status = DownloadStatus.CANCELLED
                progress.cancelled += 1
                self._safe_callback(progress, progress_callback)
                continue

            task.status = DownloadStatus.DOWNLOADING
            progress.current_task = task
            self._safe_callback(progress, progress_callback)

            try:
                self._download_file(task, progress, progress_callback)
            except Exception as e:
                task.status = DownloadStatus.FAILED
                task.error = str(e)
                progress.failed += 1
                self._safe_callback(progress, progress_callback)
                continue

            if self._cancel_flag:
                continue

            # CRC Verification
            if task.expected_crc:
                actual_crc = task.computed_crc
                if actual_crc.lower() == task.expected_crc.lower():
                    task.status = DownloadStatus.COMPLETE
                    progress.completed += 1
                else:
                    inner_crc = self._check_inner_zip_crc(task.dest_path, task.expected_crc)
                    if inner_crc and inner_crc.lower() == task.expected_crc.lower():
                        task.status = DownloadStatus.COMPLETE
                        progress.completed += 1
                    else:
                        task.status = DownloadStatus.CRC_MISMATCH
                        task.error = f"CRC mismatch: expected {task.expected_crc}, got {actual_crc}"
                        progress.failed += 1
            else:
                task.status = DownloadStatus.COMPLETE
                progress.completed += 1

            progress.current_index = progress.completed + progress.failed + progress.cancelled
            self._safe_callback(progress, progress_callback)

        return progress
```

**Step 3: Simplify _safe_callback (no lock needed)**

Replace the `_safe_callback` method (lines 492-497) with:

```python
    def _safe_callback(self, progress: DownloadProgress,
                       callback: Optional[Callable[[DownloadProgress], None]]):
        """Invoke the UI callback."""
        if callback:
            callback(progress)
```

**Step 4: Remove _process_single_task method entirely**

Delete the entire `_process_single_task` method (lines 499-566) — it was the parallel worker, no longer needed.

**Step 5: Remove _lock reset from start_downloads init area**

In the old start_downloads there was `self._lock = threading.Lock()` on line 466. Make sure it's removed (already handled by the rewrite above).

**Step 6: Verify the `_download_file` method still works standalone**

The `_download_file` method (lines 568-607) should work as-is — it downloads a single file with streaming CRC. No changes needed. Just confirm the `_safe_callback` calls inside it still work without the lock.

**Step 7: Commit**

```
feat: rewrite download engine to sequential (browser-style)

Removes ThreadPoolExecutor parallel downloads. Downloads now
process one file at a time with configurable delay between files.
```

---

### Task 2: Add --download-delay to CLI

**Files:**
- Modify: `rommanager/cli.py:18-143` (argument parser)

**Step 1: Add download-delay argument to the parser**

In `create_parser()`, after the `--no-recursive` argument (line 92), add:

```python
    cli_group.add_argument(
        '--download-delay', '-dd',
        type=int,
        default=5,
        help='Seconds to wait between downloads (0-60, default: 5)'
    )
```

**Step 2: Commit**

```
feat: add --download-delay CLI argument
```

---

### Task 3: Wire download_delay into GUI download dialog

**Files:**
- Modify: `rommanager/gui.py:773-978` (download dialog)

**Step 1: Add delay spinbox to the download dialog**

In `_start_download_flow` method, after the destination frame (after line 812), add a delay control:

```python
        # Delay between downloads
        delay_frame = ttk.LabelFrame(win, text="Download Settings", padding=8)
        delay_frame.pack(fill=tk.X, padx=15, pady=(0, 10))
        delay_row = ttk.Frame(delay_frame)
        delay_row.pack(fill=tk.X)
        ttk.Label(delay_row, text="Delay between downloads (seconds):").pack(side=tk.LEFT)
        delay_var = tk.IntVar(value=5)
        delay_spin = ttk.Spinbox(delay_row, from_=0, to=60, textvariable=delay_var, width=5)
        delay_spin.pack(side=tk.LEFT, padx=(8, 0))
```

**Step 2: Pass delay to start_downloads**

In the `worker()` function inside `start_download()` (line 900), change the call from:
```python
                    result = dl.start_downloads(on_progress)
```
to:
```python
                    result = dl.start_downloads(on_progress, download_delay=delay_var.get())
```

**Step 3: Also update the Myrient Browser download_selected worker**

In `_show_myrient_browser`, the `download_selected()` inner function (line 1145), its `worker()` calls `dl.start_downloads(on_prog)`. Change to:
```python
                    result = dl.start_downloads(on_prog, download_delay=0)
```

The browser download uses delay=0 because the user explicitly selected specific files (not a batch of missing ROMs).

**Step 4: Commit**

```
feat: add download delay setting to GUI
```

---

### Task 4: Wire download_delay into Flask webapp backend

**Files:**
- Modify: `rommanager/web.py:641-715` (download-missing endpoint)
- Modify: `rommanager/web.py:718-772` (download-files endpoint)

**Step 1: Accept download_delay in download-missing endpoint**

In `myrient_download_missing()` (line 642), after extracting `selected_names` (line 651), add:

```python
    download_delay = data.get('download_delay', 5)
    download_delay = max(0, min(60, int(download_delay)))
```

Then in the `worker()` function, change:
```python
            result = dl.start_downloads(on_progress)
```
to:
```python
            result = dl.start_downloads(on_progress, download_delay=download_delay)
```

**Step 2: Accept download_delay in download-files endpoint**

In `myrient_download_files()` (line 719), after extracting `files` (line 728), add:

```python
    download_delay = data.get('download_delay', 5)
    download_delay = max(0, min(60, int(download_delay)))
```

Then in its `worker()`, change:
```python
            result = dl.start_downloads(on_progress)
```
to:
```python
            result = dl.start_downloads(on_progress, download_delay=download_delay)
```

**Step 3: Commit**

```
feat: accept download_delay in Flask API endpoints
```

---

### Task 5: Add download delay input to React UI

**Files:**
- Modify: `rommanager/web.py:1047-1053` (React state declarations)
- Modify: `rommanager/web.py:1264-1277` (startDownloadMissing function)
- Modify: `rommanager/web.py:1256-1262` (downloadMyrientFiles function)
- Modify: `rommanager/web.py:1509-1561` (Download Progress Modal JSX)

**Step 1: Add dlDelay state**

After line 1052 (`// No speed limits...`), replace that comment and add:

```javascript
            const [dlDelay, setDlDelay] = useState(5);
```

**Step 2: Pass download_delay in startDownloadMissing**

In `startDownloadMissing` (line 1269), change the API call to:

```javascript
                const res = await api.post('/api/myrient/download-missing', {
                    dest_folder: dest,
                    selected_names: selectedNames,
                    download_delay: dlDelay,
                });
```

**Step 3: Pass download_delay in downloadMyrientFiles**

In `downloadMyrientFiles` (line 1258), change:

```javascript
                const res = await api.post('/api/myrient/download-files', { dest_folder: dest, files, download_delay: dlDelay });
```

**Step 4: Add delay input to Download Progress Modal**

In the Download Progress Modal (around line 1519, after the destination input div), add before the progress section:

```jsx
                                <div>
                                    <label className="text-sm text-slate-400">Delay between downloads (seconds):</label>
                                    <input type="number" min="0" max="60" value={dlDelay} onChange={e => setDlDelay(Math.max(0, Math.min(60, parseInt(e.target.value) || 0)))}
                                        className="mt-1 w-24 px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-sm focus:outline-none focus:border-cyan-500" />
                                </div>
```

**Step 5: Commit**

```
feat: add download delay control to React UI
```

---

### Task 6: Update documentation

**Files:**
- Modify: `readme.txt`

**Step 1: Add download section to readme.txt**

At the end of the file (before the final closing), add a new section:

```
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
```

**Step 2: Commit**

```
docs: update readme with download engine documentation
```

---

### Task 7: Clean up PERFORMANCE_ANALYSIS.md

**Files:**
- Modify: `PERFORMANCE_ANALYSIS.md`

**Step 1: Add a note at the top of the analysis doc**

After the header (line 4), add:

```markdown
**Update 2026-02-15**: Download engine has been rewritten to use sequential (browser-style) downloads — one file at a time with configurable delay. Parallel downloads were removed as Myrient performs better with single-connection downloads. The analysis below is historical.
```

**Step 2: Commit**

```
docs: update performance analysis with sequential rewrite note
```
