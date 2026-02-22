# Design: Sequential Downloads (Browser-Style)

**Date**: 2026-02-15
**Status**: Approved

## Problem

Downloads are slow because the app uses parallel ThreadPoolExecutor (3 workers).
Myrient works best with single-connection downloads — exactly like a browser does.

## Solution

Rewrite download engine: sequential (1 file at a time), full speed, configurable delay between files.

## Changes

### `myrient_downloader.py`
- Remove ThreadPoolExecutor/parallel logic from `start_downloads()`
- Add `download_delay` parameter (int, 0-60, default 5 seconds)
- Process queue sequentially: download file -> CRC check -> sleep(delay) -> next
- Remove threading.Lock (no longer needed with single thread)
- Keep: connection pooling, keep-alive, streaming CRC32, retry strategy

### `cli.py`
- Add `--download-delay` / `-dd` argument (int, 0-60, default 5)
- Add `--download` flag to download missing ROMs from CLI

### `gui.py`
- Add spinbox "Delay between downloads (s)" in download dialog (0-60, default 5)
- Pass value to `start_downloads(download_delay=X)`

### `web.py`
- `POST /api/myrient/download-missing` accepts `download_delay` parameter
- `POST /api/myrient/download-files` accepts `download_delay` parameter
- React UI: numeric input "Delay between downloads (s)"

### `readme.txt`
- Update download section with new sequential architecture
- Document `--download-delay` CLI flag

## Constraints
- 1 file at a time (sequential)
- Full speed per file (no artificial throttling within a download)
- Configurable timeout between downloads: 0-60s, default 5s
- Available in all 3 interfaces: CLI, GUI, webapp
