#!/usr/bin/env python3
"""Diagnose why ROMM download throughput differs from browser throughput.

Usage:
  python tools/investigate_download_gap.py --url <direct_file_url> [--mb 100]
"""

import argparse
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Optional

import requests


@dataclass
class Result:
    name: str
    bytes_downloaded: int
    seconds: float
    ttfb_ms: float
    notes: str = ""

    @property
    def mbps(self) -> float:
        if self.seconds <= 0:
            return 0.0
        return (self.bytes_downloaded / 1_000_000) / self.seconds


def _download_requests(name: str, url: str, max_bytes: int, trust_env: bool) -> Result:
    headers = {"Range": f"bytes=0-{max_bytes - 1}"}
    session = requests.Session()
    session.trust_env = trust_env
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Connection": "keep-alive",
    })

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "probe.bin")

        start = time.time()
        resp = session.get(url, headers=headers, stream=True, timeout=(10, 90))
        resp.raise_for_status()

        first_chunk_at: Optional[float] = None
        downloaded = 0
        with open(out, "wb") as f:
            for chunk in resp.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                if first_chunk_at is None:
                    first_chunk_at = time.time()
                remaining = max_bytes - downloaded
                if remaining <= 0:
                    break
                piece = chunk[:remaining]
                f.write(piece)
                downloaded += len(piece)
                if downloaded >= max_bytes:
                    break

        end = time.time()

    ttfb = ((first_chunk_at - start) * 1000.0) if first_chunk_at else 0.0
    return Result(name=name, bytes_downloaded=downloaded, seconds=end - start, ttfb_ms=ttfb)


def _download_curl(url: str, max_bytes: int) -> Result:
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "probe.bin")
        cmd = [
            "curl", "-L", "-r", f"0-{max_bytes - 1}", url,
            "-o", out,
            "--silent", "--show-error",
            "--write-out", "ttfb=%{time_starttransfer};total=%{time_total}",
        ]
        start = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        elapsed = time.time() - start
        size = os.path.getsize(out)

    ttfb = 0.0
    marker = "ttfb="
    if marker in proc.stdout:
        try:
            ttfb = float(proc.stdout.split("ttfb=")[1].split(";")[0]) * 1000.0
        except Exception:
            pass
    return Result(name="curl", bytes_downloaded=size, seconds=elapsed, ttfb_ms=ttfb, notes=proc.stdout.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="Direct file URL (Myrient/Archive/etc.)")
    ap.add_argument("--mb", type=int, default=100, help="How many MB to download per probe")
    args = ap.parse_args()

    max_bytes = max(1, args.mb) * 1024 * 1024

    print("=== Download Gap Investigation ===")
    print(f"URL: {args.url}")
    print(f"Probe size: {args.mb} MB")
    print(f"HTTP_PROXY={os.getenv('HTTP_PROXY')}")
    print(f"HTTPS_PROXY={os.getenv('HTTPS_PROXY')}")
    print(f"NO_PROXY={os.getenv('NO_PROXY')}")
    print()

    results = [
        _download_requests("requests(trust_env=True)", args.url, max_bytes, trust_env=True),
        _download_requests("requests(trust_env=False)", args.url, max_bytes, trust_env=False),
        _download_curl(args.url, max_bytes),
    ]

    print("name\tMB/s\tTTFB ms\tbytes\tseconds")
    for r in results:
        print(f"{r.name}\t{r.mbps:.2f}\t{r.ttfb_ms:.1f}\t{r.bytes_downloaded}\t{r.seconds:.2f}")
        if r.notes:
            print(f"  notes: {r.notes}")

    print("\nInterpretation:")
    print("- If trust_env=False is much faster than trust_env=True, proxy/autoconfig is likely the main bottleneck.")
    print("- If curl is much faster than both requests runs, HTTP stack/TLS/protocol differences are likely (browser/curl path).")
    print("- If all are similarly slow, bottleneck is likely route/ISP/server-side throttling.")


if __name__ == "__main__":
    main()
