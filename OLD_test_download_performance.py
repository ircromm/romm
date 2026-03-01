#!/usr/bin/env python
"""
ROM Manager Download Performance Profiling Script

Measures real download performance against Myrient and Archive.org sources.
Identifies bottlenecks in:
- SSL/TLS handshake (TTFB)
- Network throughput
- Disk I/O
- CRC computation
- UI callback overhead

Usage:
    python test_download_performance.py
"""

import time
import cProfile
import pstats
import os
import tempfile
import shutil
from pathlib import Path

# Add project to path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from rommanager.myrient_downloader import MyrientDownloader
from rommanager.downloader import ArchiveOrgDownloader


def format_size(bytes_val):
    """Human-readable file size"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.1f} TB"


def test_myrient_single():
    """Profile: Single ROM download from Myrient (~10-50 MB)"""
    print("\n" + "=" * 70)
    print("TEST 1: MYRIENT - SINGLE ROM (~10-50 MB)")
    print("=" * 70)

    dl = MyrientDownloader()

    # Find a test ROM
    print("\n[1] Listing available systems...")
    systems = MyrientDownloader.get_systems()
    print(f"   Found {len(systems)} systems")

    # Pick a system and find a medium-sized ROM
    print("\n[2] Searching for test ROM (1-50 MB)...")
    test_systems = [
        "Nintendo - Game Boy Advance",
        "Nintendo - Game Boy Color",
        "Atari - 2600",
        "Sega - Mega Drive - Genesis",
    ]

    test_rom = None
    test_system = None

    for sys in test_systems:
        try:
            print(f"   Trying {sys}...")
            roms = dl.list_files(sys)
            # Filter valid ROMs with size info
            valid_roms = [r for r in roms if r.size and r.size > 1_000_000]

            if valid_roms:
                # Find one in size range
                test_rom = next((r for r in valid_roms if 5_000_000 < r.size < 50_000_000), None)
                if not test_rom:
                    test_rom = valid_roms[0]  # Just take first valid one
                test_system = sys
                break
        except Exception as e:
            print(f"      Error: {e}")
            continue

    if not test_rom:
        print(f"   ERROR: No valid ROMs found in any system")
        return None

    print(f"\n   ✓ Found: {test_rom.name}")
    print(f"     System: {test_system}")
    print(f"     Size: {format_size(test_rom.size)}")
    print(f"     URL: {test_rom.url[:80]}...")

    except Exception as e:
        print(f"   ERROR: {e}")
        return None

    # Setup download
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"\n[3] Preparing download to {tmpdir}...")
        dl.queue_rom(test_rom.name, test_rom.url, tmpdir)

        # Run profiling
        print("\n[4] Starting profiled download...")
        profiler = cProfile.Profile()
        profiler.enable()

        start_time = time.time()
        call_count = [0]

        def progress_cb(prog):
            call_count[0] += 1

        try:
            result = dl.start_downloads(progress_cb)
            elapsed = time.time() - start_time

            profiler.disable()

            # Results
            print(f"\n" + "=" * 70)
            print("MYRIENT SINGLE ROM - RESULTS")
            print("=" * 70)
            print(f"Status:          {result.current_task.status.name if result.current_task else 'Unknown'}")
            print(f"Total time:      {elapsed:.2f}s")
            print(f"Throughput:      {test_rom.size / 1_000_000 / elapsed:.2f} MB/s")
            print(f"Progress calls:  {call_count[0]}")
            print(f"Avg call freq:   {call_count[0] / elapsed:.1f} Hz")

            if result.current_task and result.current_task.total_bytes > 0:
                print(f"Chunks fetched:  {result.current_task.total_bytes / 256_000:.0f}")

            # Top time consumers
            print(f"\n" + "-" * 70)
            print("TOP TIME CONSUMERS")
            print("-" * 70)
            ps = pstats.Stats(profiler)
            ps.sort_stats('cumulative')
            ps.print_stats(8)

            return elapsed

        except Exception as e:
            print(f"\nERROR during download: {e}")
            import traceback
            traceback.print_exc()
            return None


def test_myrient_batch():
    """Profile: Multiple ROM downloads from Myrient (batch)"""
    print("\n" + "=" * 70)
    print("TEST 2: MYRIENT - BATCH (5 ROMs, ~5-15 MB each)")
    print("=" * 70)

    dl = MyrientDownloader()

    print("\n[1] Listing test ROMs...")
    try:
        roms = dl.list_files("Atari - 2600")
        # Find ROMs in size range
        test_roms = [r for r in roms if 5_000_000 < r.size < 15_000_000][:5]

        if len(test_roms) < 3:
            print(f"   Warning: Only {len(test_roms)} ROMs in size range (need 5)")
            test_roms = roms[:5] if roms else []

        if not test_roms:
            print("   ERROR: No ROMs found")
            return None

        total_size = sum(r.size for r in test_roms) / 1_000_000
        print(f"   Found {len(test_roms)} ROMs, total {total_size:.1f} MB")

        for i, rom in enumerate(test_roms):
            print(f"     [{i+1}] {rom.name} ({format_size(rom.size)})")

    except Exception as e:
        print(f"   ERROR: {e}")
        return None

    # Setup downloads
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"\n[2] Queuing {len(test_roms)} downloads to {tmpdir}...")

        for rom in test_roms:
            dl.queue_rom(rom.name, rom.url, tmpdir)

        print("[3] Starting profiled batch download...")
        profiler = cProfile.Profile()
        profiler.enable()

        start_time = time.time()
        call_count = [0]

        def progress_cb(prog):
            call_count[0] += 1

        try:
            result = dl.start_downloads(progress_cb)
            elapsed = time.time() - start_time

            profiler.disable()

            # Results
            print(f"\n" + "=" * 70)
            print("MYRIENT BATCH - RESULTS")
            print("=" * 70)
            print(f"ROMs completed:  {result.completed}")
            print(f"ROMs failed:     {result.failed}")
            print(f"ROMs cancelled:  {result.cancelled}")
            print(f"Total time:      {elapsed:.2f}s")
            print(f"Total size:      {total_size:.1f} MB")
            print(f"Avg throughput:  {total_size / elapsed:.2f} MB/s")
            print(f"Time/ROM:        {elapsed / len(test_roms):.2f}s")
            print(f"Progress calls:  {call_count[0]}")

            # Top time consumers
            print(f"\n" + "-" * 70)
            print("TOP TIME CONSUMERS")
            print("-" * 70)
            ps = pstats.Stats(profiler)
            ps.sort_stats('cumulative')
            ps.print_stats(8)

            return elapsed

        except Exception as e:
            print(f"\nERROR during batch download: {e}")
            import traceback
            traceback.print_exc()
            return None


def test_network_baseline():
    """Test basic network connectivity and latency"""
    print("\n" + "=" * 70)
    print("NETWORK BASELINE")
    print("=" * 70)

    import socket
    import urllib.request

    # Test DNS resolution
    print("\n[1] DNS Resolution:")
    hosts = [
        ("myrient.erista.me", "Myrient"),
        ("archive.org", "Archive.org"),
    ]

    for host, name in hosts:
        try:
            start = time.time()
            ip = socket.gethostbyname(host)
            elapsed = time.time() - start
            print(f"   {name:20} {host:25} -> {ip:15} ({elapsed*1000:.1f}ms)")
        except Exception as e:
            print(f"   {name:20} {host:25} -> ERROR: {e}")

    # Test HTTP latency
    print("\n[2] HTTP Latency (TTFB - Time To First Byte):")

    test_urls = [
        ("https://myrient.erista.me/files/No-Intro/", "Myrient"),
        ("https://archive.org/", "Archive.org"),
    ]

    for url, name in test_urls:
        try:
            start = time.time()
            response = urllib.request.urlopen(url, timeout=10)
            elapsed = time.time() - start
            print(f"   {name:20} {elapsed*1000:7.1f}ms")
        except Exception as e:
            print(f"   {name:20} ERROR: {e}")


def main():
    """Run all profiling tests"""
    print("\n" + "=" * 70)
    print("ROM MANAGER - DOWNLOAD PERFORMANCE PROFILING")
    print("=" * 70)
    print("\nThis script profiles download performance to identify bottlenecks.")
    print("Tests will connect to real servers (Myrient, Archive.org).")

    results = {}

    # Network baseline
    try:
        test_network_baseline()
    except Exception as e:
        print(f"ERROR in network baseline: {e}")

    # Single ROM test
    try:
        elapsed = test_myrient_single()
        if elapsed:
            results["myrient_single"] = elapsed
    except Exception as e:
        print(f"\nERROR in single ROM test: {e}")
        import traceback
        traceback.print_exc()

    # Batch test
    try:
        elapsed = test_myrient_batch()
        if elapsed:
            results["myrient_batch"] = elapsed
    except Exception as e:
        print(f"\nERROR in batch test: {e}")
        import traceback
        traceback.print_exc()

    # Summary
    print("\n" + "=" * 70)
    print("PROFILING SUMMARY")
    print("=" * 70)

    if results:
        for test, elapsed in results.items():
            print(f"  {test:30} {elapsed:7.2f}s")
    else:
        print("  No successful tests. Check network connectivity.")

    print("\n" + "=" * 70)
    print("PROFILING COMPLETE")
    print("=" * 70)


if __name__ == '__main__':
    main()
