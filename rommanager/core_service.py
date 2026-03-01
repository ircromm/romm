"""
Core service for R0MM.
Single source of truth for scanning, matching, organizing, collections, and settings.
Used by Flask (web) and can be reused by desktop UIs without HTTP.
"""

from __future__ import annotations

import concurrent.futures
import difflib
import html as html_lib
import hashlib
import json
import os
import platform
import re
import signal
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from collections import deque
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import unquote, urlencode, urljoin, urlsplit, urlunsplit
from typing import Any, Callable, Dict, List, Optional, Tuple

from .blindmatch import build_blindmatch_rom
from .collection import CollectionManager
from .dat_library import DATLibrary
from .dat_sources import DATSourceManager
from .matcher import MultiROMMatcher
from .models import Collection, DATInfo, ROMInfo, ScannedFile
from .organizer import Organizer, configure_audit, configure_naming, configure_selection_policy
from .parser import DATParser
from .reporter import MissingROMReporter
from .scanner import FileScanner
from .session_state import (
    build_snapshot,
    clear_snapshot,
    load_snapshot,
    restore_into_matcher,
    restore_scanned,
    save_snapshot,
)
from .monitor import monitor_action
from .settings import get_effective_profile, load_settings, save_settings
from .shared_config import DATS_DIR, DEFAULT_REGION_COLOR, REGION_COLORS, STRATEGIES
from .utils import format_size

try:
    import winreg  # type: ignore
except Exception:  # pragma: no cover - non-Windows runtimes
    winreg = None


class MyrientFetcher:
    """Rate-limited Myrient downloader powered by rclone copyurl."""

    _executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="R0MM-Myrient")
    _user_agent = "R0MM/2 MyrientFetcher (+local desktop app)"
    _progress_min_interval_s = 0.20
    _progress_min_percent_step = 1.0
    _myrient_host = "myrient.erista.me"

    def __init__(self) -> None:
        self._cancel_event = threading.Event()
        self._lock = threading.Lock()
        self._futures: Dict[concurrent.futures.Future, dict] = {}
        self._progress_emit_state: Dict[str, tuple[float, float, str]] = {}
        self._active_processes: Dict[str, subprocess.Popen] = {}
        self._rclone_path: Optional[str] = None

    @staticmethod
    def _filename_for(url: str, dest_path: str) -> str:
        if dest_path:
            name = Path(dest_path).name
            if name:
                return name
        tail = Path(urlsplit(url).path).name
        return tail or "download.bin"

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _emit_progress(
        self,
        progress_callback: Optional[Callable[[str, float, str, str], None]],
        filename: str,
        percent: float,
        speed: str,
        status: str,
    ) -> None:
        if not callable(progress_callback):
            return
        safe_percent = max(0.0, min(100.0, self._safe_float(percent)))
        safe_speed = str(speed or "")
        safe_status = str(status or "").upper().strip() or "QUEUED"
        key = (filename or "").strip() or "download.bin"
        now = time.monotonic()

        if safe_status == "DOWNLOADING":
            with self._lock:
                prev = self._progress_emit_state.get(key)
                if prev is not None:
                    last_ts, last_pct, _last_status = prev
                    if (
                        (now - last_ts) < self._progress_min_interval_s
                        and abs(safe_percent - last_pct) < self._progress_min_percent_step
                    ):
                        return
                self._progress_emit_state[key] = (now, safe_percent, safe_status)
        else:
            with self._lock:
                if safe_status in {"DONE", "HALTED", "ERROR"}:
                    self._progress_emit_state.pop(key, None)
                else:
                    self._progress_emit_state[key] = (now, safe_percent, safe_status)
        try:
            progress_callback(key, safe_percent, safe_speed, safe_status)
        except Exception:
            pass

    @staticmethod
    def _request(url: str, *, method: str = "GET", headers: Optional[dict] = None) -> urllib.request.Request:
        req_headers = {"User-Agent": MyrientFetcher._user_agent}
        if headers:
            req_headers.update(headers)
        return urllib.request.Request(url, headers=req_headers, method=method)

    def _resolve_rclone_binary(self) -> str:
        cached = (self._rclone_path or "").strip()
        if cached and Path(cached).exists():
            return cached

        names = ["rclone.exe", "rclone"] if os.name == "nt" else ["rclone", "rclone.exe"]
        repo_root = Path(__file__).resolve().parent.parent
        candidates = [repo_root / name for name in names]
        for candidate in candidates:
            try:
                if candidate.exists() and candidate.is_file():
                    self._rclone_path = str(candidate)
                    return self._rclone_path
            except OSError:
                continue

        resolved = shutil.which("rclone")
        if resolved:
            self._rclone_path = resolved
            return self._rclone_path

        raise FileNotFoundError("rclone binary not found (expected in project root or PATH)")

    def _build_rclone_copyurl_command(
        self,
        url: str,
        dest_path: str,
        *,
        troubleshoot_profile: bool = False,
    ) -> List[str]:
        cmd = [
            self._resolve_rclone_binary(),
            "copyurl",
            url,
            dest_path,
            "--retries",
            "1",
            "--low-level-retries",
            "1",
            "--retries-sleep",
            "0s",
            "--contimeout",
            "15s",
            "--timeout",
            "45s",
            "--multi-thread-streams",
            "0",
        ]
        if troubleshoot_profile:
            cmd.extend([
                "--disable-http2",
                "--user-agent",
                "curl",
            ])
        return cmd

    def _build_rclone_http_copyto_command(
        self,
        url: str,
        dest_path: str,
        *,
        troubleshoot_profile: bool = False,
    ) -> List[str]:
        """
        Build an rclone HTTP-remote command for Myrient.

        This follows Myrient FAQ guidance (rclone HTTP remote + copy/sync family) while
        still preserving an exact destination filename via copyto.
        """
        parts = urlsplit(url)
        host = (parts.hostname or "").strip() or self._myrient_host
        raw_path = (parts.path or "/").lstrip("/")
        if not raw_path:
            raise ValueError("Myrient file URL path is empty")

        # Myrient FAQ examples use https://myrient.erista.me/files/ as the HTTP remote root.
        # If the URL is under /files/, use that base; otherwise use domain root.
        lower_path = raw_path.lower()
        if lower_path.startswith("files/"):
            remote_root = f"{parts.scheme or 'https'}://{host}/files/"
            remote_rel = raw_path[len("files/") :]
        else:
            remote_root = f"{parts.scheme or 'https'}://{host}/"
            remote_rel = raw_path
        remote_rel = unquote(remote_rel)
        if not remote_rel:
            raise ValueError("Myrient relative path is empty")

        cmd = [
            self._resolve_rclone_binary(),
            "copyto",
            "--http-url",
            remote_root,
            "--http-no-head",
            f":http:{remote_rel}",
            dest_path,
            "--retries",
            "1",
            "--low-level-retries",
            "1",
            "--retries-sleep",
            "0s",
            "--contimeout",
            "15s",
            "--timeout",
            "45s",
            "--multi-thread-streams",
            "0",
        ]
        if troubleshoot_profile:
            cmd.extend([
                "--disable-http2",
                "--user-agent",
                "curl",
            ])
        return cmd

    @staticmethod
    def _last_meaningful_output_line(output: str) -> str:
        text = str(output or "").replace("\r", "\n")
        for line in reversed([ln.strip() for ln in text.splitlines() if ln.strip()]):
            if "Config file" in line and "using defaults" in line:
                continue
            return line
        return ""

    def _build_powershell_iwr_command(self, url: str, dest_path: str) -> List[str]:
        ps_bin = shutil.which("powershell") or shutil.which("pwsh")
        if not ps_bin:
            raise FileNotFoundError("PowerShell not found for HTTP fallback transfer")
        safe_url = str(url or "").replace("'", "''")
        safe_dest = str(dest_path or "").replace("'", "''")
        script = (
            "$ErrorActionPreference='Stop'; "
            "$ProgressPreference='SilentlyContinue'; "
            "try { [Net.ServicePointManager]::SecurityProtocol = "
            "[Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls11 } catch { } ; "
            f"Invoke-WebRequest -Uri '{safe_url}' -OutFile '{safe_dest}' -MaximumRedirection 10 -TimeoutSec 45"
        )
        cmd = [
            ps_bin,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ]
        return cmd

    @staticmethod
    def _ps_iwr_fallback_enabled() -> bool:
        raw = os.getenv("R0MM_ENABLE_PS_IWR_FALLBACK", "").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    @staticmethod
    def _is_retryable_transport_error(message: str) -> bool:
        text = (message or "").lower()
        if not text:
            return False
        retry_markers = (
            "timed out",
            "timeout",
            "failed to respond",
            "connectex",
            "connection attempt failed",
            "i/o timeout",
            "no such host",
            "temporary failure",
        )
        return any(marker in text for marker in retry_markers)

    @staticmethod
    def _canonicalize_myrient_url(url: str) -> str:
        try:
            parts = urlsplit(url)
        except Exception:
            return url
        netloc = parts.netloc or ""
        if not netloc:
            return url
        host = netloc.split("@")[-1].split(":")[0]
        if not re.fullmatch(r"f\d+\.erista\.me", host, flags=re.IGNORECASE):
            return url
        canonical_netloc = re.sub(
            r"^f\d+\.erista\.me",
            MyrientFetcher._myrient_host,
            netloc,
            flags=re.IGNORECASE,
        )
        return urlunsplit((parts.scheme, canonical_netloc, parts.path, parts.query, parts.fragment))

    @staticmethod
    def _is_myrient_url(url: str) -> bool:
        try:
            host = (urlsplit(url).netloc or "").split("@")[-1].split(":")[0].lower()
        except Exception:
            return False
        return host.endswith(".erista.me") or host == MyrientFetcher._myrient_host

    @staticmethod
    def _myrient_mirror_fallback_url(url: str) -> str:
        try:
            parts = urlsplit(url)
        except Exception:
            return ""
        netloc = parts.netloc or ""
        if not netloc:
            return ""
        host = netloc.split("@")[-1].split(":")[0].lower()
        if not re.fullmatch(r"f\d+\.erista\.me", host):
            return ""
        fallback_netloc = re.sub(r"^f\d+\.erista\.me", "myrient.erista.me", netloc, flags=re.IGNORECASE)
        candidate = urlunsplit((parts.scheme, fallback_netloc, parts.path, parts.query, parts.fragment))
        return candidate if candidate != url else ""

    @staticmethod
    def _extract_rclone_error_url(message: str) -> str:
        text = str(message or "")
        if not text:
            return ""
        match = re.search(r'''(?:Get|Head)\s+"([^"]+)"''', text, flags=re.IGNORECASE)
        return str(match.group(1)).strip() if match else ""

    @staticmethod
    def _replace_url_host(url: str, new_host: str) -> str:
        safe_host = (new_host or "").strip()
        if not safe_host:
            return ""
        try:
            parts = urlsplit(url)
        except Exception:
            return ""
        netloc = (parts.netloc or "").strip()
        if not netloc:
            return ""
        if "@" in netloc:
            userinfo, hostport = netloc.rsplit("@", 1)
            userinfo = userinfo + "@"
        else:
            userinfo, hostport = "", netloc
        port = ""
        if hostport.startswith("["):  # IPv6 literal (not expected here, but keep parser safe)
            host_only = hostport
        elif ":" in hostport:
            host_only, maybe_port = hostport.rsplit(":", 1)
            if maybe_port.isdigit():
                port = ":" + maybe_port
            else:
                host_only = hostport
        else:
            host_only = hostport
        if not host_only:
            return ""
        new_netloc = f"{userinfo}{safe_host}{port}"
        return urlunsplit((parts.scheme, new_netloc, parts.path, parts.query, parts.fragment))

    @staticmethod
    def _myrient_host_hop_fallback_url(url: str, error_message: str, *, tried_hosts: Optional[Tuple[str, ...]] = None) -> str:
        """
        If a Myrient URL redirects to an unreachable fN.erista.me host, hop to another
        CDN host directly while preserving the same path.
        """
        failed_url = MyrientFetcher._extract_rclone_error_url(error_message)
        reference_url = failed_url if MyrientFetcher._is_myrient_url(failed_url) else url
        try:
            ref_parts = urlsplit(reference_url)
        except Exception:
            return ""
        ref_host = (ref_parts.netloc or "").split("@")[-1].split(":")[0].lower()
        if not ref_host or not ref_parts.path:
            return ""
        tried = {h.lower() for h in (tried_hosts or ()) if str(h or "").strip()}
        tried.add(ref_host)
        try:
            input_host = (urlsplit(url).netloc or "").split("@")[-1].split(":")[0].lower()
        except Exception:
            input_host = ""
        if input_host:
            tried.add(input_host)

        failed_match = re.fullmatch(r"f(\d+)\.erista\.me", ref_host)
        host_order: List[str] = []
        max_hosts = 8
        if failed_match:
            failed_n = int(failed_match.group(1))
            for offset in range(1, max_hosts + 1):
                cand_n = ((failed_n - 1 + offset) % max_hosts) + 1
                host_order.append(f"f{cand_n}.erista.me")
        else:
            host_order.extend([f"f{i}.erista.me" for i in range(1, max_hosts + 1)])
        # Keep canonical host as a last resort if it wasn't already tried.
        host_order.append(MyrientFetcher._myrient_host)

        for candidate_host in host_order:
            if candidate_host.lower() in tried:
                continue
            candidate_url = MyrientFetcher._replace_url_host(reference_url, candidate_host)
            if candidate_url and candidate_url != reference_url:
                return candidate_url
        return ""

    @staticmethod
    def _terminate_subprocess(proc: Optional[subprocess.Popen], timeout_s: float = 1.0) -> None:
        if proc is None:
            return
        try:
            if proc.poll() is not None:
                return
        except Exception:
            return
        try:
            proc.terminate()
        except Exception:
            return
        try:
            proc.wait(timeout=timeout_s)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _download_via_powershell_iwr(
        self,
        *,
        url: str,
        dest: Path,
        filename: str,
        progress_callback: Optional[Callable[[str, float, str, str], None]],
        remote_size: Optional[int],
        initial_pct: float,
    ) -> dict:
        cmd = self._build_powershell_iwr_command(url, str(dest))
        monitor_action(f"[!] myrient:ps_iwr:start {filename}")
        creationflags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW"))

        try:
            start_size = int(dest.stat().st_size) if dest.exists() and dest.is_file() else 0
        except OSError:
            start_size = 0
        current_pct = initial_pct
        current_speed = "0 B/s"
        proc: Optional[subprocess.Popen] = None
        output = ""
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
            with self._lock:
                self._active_processes[str(dest)] = proc

            speed_window = deque([(time.monotonic(), int(start_size))], maxlen=32)
            self._emit_progress(progress_callback, filename, current_pct, current_speed, "DOWNLOADING")

            while True:
                if self._cancel_event.is_set():
                    self._terminate_subprocess(proc)
                rc = proc.poll()
                try:
                    bytes_now = int(dest.stat().st_size) if dest.exists() and dest.is_file() else 0
                except OSError:
                    bytes_now = 0
                now = time.monotonic()
                speed_window.append((now, bytes_now))
                while len(speed_window) >= 2 and (now - speed_window[0][0]) > 1.5:
                    speed_window.popleft()

                speed_bps = 0.0
                if len(speed_window) >= 2:
                    delta_t = speed_window[-1][0] - speed_window[0][0]
                    delta_b = speed_window[-1][1] - speed_window[0][1]
                    if delta_t > 0 and delta_b >= 0:
                        speed_bps = delta_b / delta_t
                if speed_bps >= 1024 * 1024:
                    current_speed = f"{speed_bps / (1024 * 1024):.1f} MiB/s"
                elif speed_bps >= 1024:
                    current_speed = f"{speed_bps / 1024:.0f} KiB/s"
                else:
                    current_speed = f"{speed_bps:.0f} B/s"

                if isinstance(remote_size, int) and remote_size > 0:
                    current_pct = max(0.0, min(100.0, (bytes_now / remote_size) * 100.0))
                self._emit_progress(progress_callback, filename, current_pct, current_speed, "DOWNLOADING")

                if rc is not None:
                    break
                time.sleep(0.25)

            return_code = int(proc.wait())
            try:
                out, _ = proc.communicate(timeout=0.25)
            except Exception:
                out = ""
            output = str(out or "")
            if self._cancel_event.is_set():
                monitor_action(f"[!] myrient:ps_iwr:halted {filename}")
                self._emit_progress(progress_callback, filename, current_pct, "", "HALTED")
                return {
                    "url": url,
                    "dest_path": str(dest),
                    "bytes": int(dest.stat().st_size) if dest.exists() and dest.is_file() else 0,
                    "halted": True,
                    "status": "HALTED",
                    "backend": "powershell-iwr",
                    "transport": "http-iwr",
                }
            if return_code == 0:
                try:
                    bytes_written = int(dest.stat().st_size) if dest.exists() and dest.is_file() else 0
                except OSError:
                    bytes_written = 0
                monitor_action(f"[*] myrient:ps_iwr:done {filename} bytes={bytes_written}")
                self._emit_progress(progress_callback, filename, 100.0, "", "DONE")
                return {
                    "url": url,
                    "dest_path": str(dest),
                    "bytes": bytes_written,
                    "status": "DONE",
                    "backend": "powershell-iwr",
                    "transport": "http-iwr",
                }
            error_line = self._last_meaningful_output_line(output)
            if not error_line:
                error_line = f"Invoke-WebRequest exited with code {return_code}"
            monitor_action(f"[!] myrient:ps_iwr:error {filename} :: {error_line}")
            self._emit_progress(progress_callback, filename, current_pct if current_pct > 0 else 0.0, error_line, "ERROR")
            return {
                "url": url,
                "dest_path": str(dest),
                "error": error_line,
                "status": "ERROR",
                "backend": "powershell-iwr",
                "transport": "http-iwr",
            }
        finally:
            if proc is not None:
                if self._cancel_event.is_set():
                    self._terminate_subprocess(proc)
                with self._lock:
                    self._active_processes.pop(str(dest), None)

    def check_remote_file(self, url: str, local_path: str) -> dict:
        """Passive inspection via HEAD to compare local and remote metadata."""
        result = {
            "url": url,
            "local_path": local_path,
            "exists_local": False,
            "local_size": 0,
            "remote_size": None,
            "remote_last_modified": "",
            "remote_last_modified_ts": None,
            "same_size": False,
            "error": "",
        }

        path = Path(local_path)
        try:
            if path.exists() and path.is_file():
                result["exists_local"] = True
                result["local_size"] = int(path.stat().st_size)
        except OSError:
            pass

        req = self._request(url, method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                headers = resp.headers
                cl = headers.get("Content-Length")
                if cl is not None:
                    try:
                        result["remote_size"] = int(cl)
                    except ValueError:
                        result["remote_size"] = None
                lm = (headers.get("Last-Modified") or "").strip()
                if lm:
                    result["remote_last_modified"] = lm
                    try:
                        dt = parsedate_to_datetime(lm)
                        result["remote_last_modified_ts"] = dt.timestamp()
                    except Exception:
                        result["remote_last_modified_ts"] = None
        except Exception as exc:
            result["error"] = str(exc)
            return result

        remote_size = result.get("remote_size")
        if isinstance(remote_size, int) and remote_size >= 0:
            result["same_size"] = int(result.get("local_size", 0)) == remote_size
        return result

    def submit_download(
        self,
        url: str,
        dest_path: str,
        progress_callback: Optional[Callable[[str, float, str, str], None]] = None,
    ) -> concurrent.futures.Future:
        filename = self._filename_for(url, dest_path)
        with self._lock:
            if self._cancel_event.is_set() and not any(not future.done() for future in self._futures):
                # Allow a new batch after a previous HALT once active jobs have drained.
                self._cancel_event.clear()
                self._progress_emit_state.clear()
        self._emit_progress(progress_callback, filename, 0.0, "", "QUEUED")

        future = self._executor.submit(self.download_target, url, dest_path, progress_callback)
        with self._lock:
            self._futures[future] = {"url": url, "dest_path": dest_path, "filename": filename}

        def _cleanup(done_future: concurrent.futures.Future) -> None:
            with self._lock:
                self._futures.pop(done_future, None)

        future.add_done_callback(_cleanup)
        return future

    def download_target(
        self,
        url: str,
        dest_path: str,
        progress_callback: Optional[Callable[[str, float, str, str], None]] = None,
        *,
        _attempt: int = 0,
        _use_troubleshoot_profile: bool = False,
        _preserve_myrient_host: bool = False,
        _tried_myrient_hosts: Tuple[str, ...] = (),
    ) -> dict:
        original_url = str(url or "")
        canonical_url = original_url if _preserve_myrient_host else self._canonicalize_myrient_url(original_url)
        if canonical_url and canonical_url != original_url:
            try:
                old_host = urlsplit(original_url).netloc
                new_host = urlsplit(canonical_url).netloc
            except Exception:
                old_host = original_url
                new_host = canonical_url
            monitor_action(f"[*] myrient:rclone:rewrite_host {old_host} -> {new_host}")
        url = canonical_url or original_url
        filename = self._filename_for(url, dest_path)
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        if self._cancel_event.is_set():
            self._emit_progress(progress_callback, filename, 0.0, "", "HALTED")
            return {"url": url, "dest_path": str(dest), "halted": True}

        try:
            local_size = int(dest.stat().st_size) if dest.exists() and dest.is_file() else 0
        except OSError:
            local_size = 0
        remote_meta = self.check_remote_file(url, str(dest)) if local_size > 0 else {"remote_size": None}
        remote_size = remote_meta.get("remote_size")
        if isinstance(remote_size, int) and remote_size > 0 and local_size == remote_size:
            monitor_action(f"[*] myrient:rclone:skip {filename} (already complete)")
            self._emit_progress(progress_callback, filename, 100.0, "", "DONE")
            return {
                "url": url,
                "dest_path": str(dest),
                "bytes": local_size,
                "resumed": False,
                "skipped": True,
                "status": "DONE",
            }

        initial_pct = 0.0
        if isinstance(remote_size, int) and remote_size > 0 and local_size > 0:
            initial_pct = (min(local_size, remote_size) / remote_size) * 100.0

        # For rclone-backed transfers we do a lightweight HEAD to support percent/skip logic.
        if not isinstance(remote_size, int) or remote_size <= 0:
            remote_meta = self.check_remote_file(url, str(dest))
            remote_size = remote_meta.get("remote_size")
            if isinstance(remote_size, int) and remote_size > 0 and local_size == remote_size:
                self._emit_progress(progress_callback, filename, 100.0, "", "DONE")
                return {
                    "url": url,
                    "dest_path": str(dest),
                    "bytes": local_size,
                    "resumed": False,
                    "skipped": True,
                    "status": "DONE",
                }

        is_myrient = self._is_myrient_url(url)
        use_troubleshoot_profile = bool(_use_troubleshoot_profile or is_myrient)
        rclone_transport = "copyurl"
        if is_myrient:
            cmd = self._build_rclone_http_copyto_command(
                url,
                str(dest),
                troubleshoot_profile=use_troubleshoot_profile,
            )
            rclone_transport = "http-copyto"
        else:
            cmd = self._build_rclone_copyurl_command(
                url,
                str(dest),
                troubleshoot_profile=use_troubleshoot_profile,
            )
        monitor_action(f"[*] myrient:rclone:start {filename} transport={rclone_transport}")
        creationflags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW"))

        proc: Optional[subprocess.Popen] = None
        rclone_output = ""
        current_pct = initial_pct
        current_speed = "0 B/s"
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
            with self._lock:
                self._active_processes[str(dest)] = proc

            # Poll local file growth instead of parsing rclone progress text to avoid stdout pipe stalls.
            speed_window = deque([(time.monotonic(), int(local_size))], maxlen=32)
            self._emit_progress(progress_callback, filename, current_pct, current_speed, "DOWNLOADING")

            while True:
                if self._cancel_event.is_set():
                    self._terminate_subprocess(proc)
                rc = proc.poll()
                try:
                    bytes_now = int(dest.stat().st_size) if dest.exists() and dest.is_file() else 0
                except OSError:
                    bytes_now = 0
                now = time.monotonic()
                speed_window.append((now, bytes_now))
                while len(speed_window) >= 2 and (now - speed_window[0][0]) > 1.5:
                    speed_window.popleft()

                speed_bps = 0.0
                if len(speed_window) >= 2:
                    delta_t = speed_window[-1][0] - speed_window[0][0]
                    delta_b = speed_window[-1][1] - speed_window[0][1]
                    if delta_t > 0 and delta_b >= 0:
                        speed_bps = delta_b / delta_t
                if speed_bps >= 1024 * 1024:
                    current_speed = f"{speed_bps / (1024 * 1024):.1f} MiB/s"
                elif speed_bps >= 1024:
                    current_speed = f"{speed_bps / 1024:.0f} KiB/s"
                else:
                    current_speed = f"{speed_bps:.0f} B/s"

                if isinstance(remote_size, int) and remote_size > 0:
                    current_pct = max(0.0, min(100.0, (bytes_now / remote_size) * 100.0))
                self._emit_progress(progress_callback, filename, current_pct, current_speed, "DOWNLOADING")

                if rc is not None:
                    break
                time.sleep(0.25)

            return_code = int(proc.wait())
            try:
                out, _ = proc.communicate(timeout=0.25)
            except Exception:
                out = ""
            rclone_output = str(out or "")
            if self._cancel_event.is_set():
                monitor_action(f"[!] myrient:rclone:halted {filename}")
                self._emit_progress(progress_callback, filename, current_pct, "", "HALTED")
                return {
                    "url": url,
                    "dest_path": str(dest),
                    "bytes": int(dest.stat().st_size) if dest.exists() and dest.is_file() else 0,
                    "halted": True,
                    "status": "HALTED",
                }

            if return_code == 0:
                try:
                    bytes_written = int(dest.stat().st_size) if dest.exists() and dest.is_file() else 0
                except OSError:
                    bytes_written = 0
                monitor_action(f"[*] myrient:rclone:done {filename} bytes={bytes_written} transport={rclone_transport}")
                self._emit_progress(progress_callback, filename, 100.0, "", "DONE")
                return {
                    "url": url,
                    "dest_path": str(dest),
                    "bytes": bytes_written,
                    "resumed": bool(local_size > 0),
                    "status": "DONE",
                    "backend": "rclone",
                    "transport": rclone_transport,
                }

            # Keep the last meaningful rclone line as the error summary.
            error_line = self._last_meaningful_output_line(rclone_output)
            if not error_line:
                error_line = f"rclone copyurl exited with code {return_code}"
            retry_url = ""
            should_retry = (not self._cancel_event.is_set() and self._is_retryable_transport_error(error_line))
            if should_retry and _attempt == 0 and not use_troubleshoot_profile and is_myrient:
                monitor_action(f"[!] myrient:rclone:retry_profile {filename} :: enabling troubleshoot profile")
                return self.download_target(
                    url,
                    str(dest),
                    progress_callback,
                    _attempt=_attempt + 1,
                    _use_troubleshoot_profile=True,
                )
            if should_retry and _attempt == 0:
                retry_url = self._myrient_mirror_fallback_url(url)
            if retry_url and retry_url != url:
                try:
                    old_host = urlsplit(url).netloc
                    new_host = urlsplit(retry_url).netloc
                except Exception:
                    old_host = url
                    new_host = retry_url
                monitor_action(f"[!] myrient:rclone:retry_mirror {filename} :: {old_host} -> {new_host}")
                return self.download_target(
                    retry_url,
                    str(dest),
                    progress_callback,
                    _attempt=_attempt + 1,
                    _use_troubleshoot_profile=True,
                )
            if should_retry and is_myrient and _attempt < 3:
                failed_rclone_url = self._extract_rclone_error_url(error_line)
                attempted_hosts = set(h.lower() for h in _tried_myrient_hosts if str(h or "").strip())
                for candidate in (url, failed_rclone_url):
                    try:
                        host = (urlsplit(candidate).netloc or "").split("@")[-1].split(":")[0].lower()
                    except Exception:
                        host = ""
                    if host:
                        attempted_hosts.add(host)
                retry_host_hop_url = self._myrient_host_hop_fallback_url(
                    url,
                    error_line,
                    tried_hosts=tuple(sorted(attempted_hosts)),
                )
                if retry_host_hop_url and retry_host_hop_url != url:
                    try:
                        old_host = (urlsplit(failed_rclone_url or url).netloc or urlsplit(url).netloc)
                        new_host = urlsplit(retry_host_hop_url).netloc
                    except Exception:
                        old_host = failed_rclone_url or url
                        new_host = retry_host_hop_url
                    monitor_action(f"[!] myrient:rclone:retry_host_hop {filename} :: {old_host} -> {new_host}")
                    hop_hosts = set(attempted_hosts)
                    try:
                        hop_hosts.add((urlsplit(retry_host_hop_url).netloc or "").split("@")[-1].split(":")[0].lower())
                    except Exception:
                        pass
                    return self.download_target(
                        retry_host_hop_url,
                        str(dest),
                        progress_callback,
                        _attempt=_attempt + 1,
                        _use_troubleshoot_profile=True,
                        _preserve_myrient_host=True,
                        _tried_myrient_hosts=tuple(sorted(h for h in hop_hosts if h)),
                    )
            if should_retry and is_myrient and _attempt >= 3 and self._ps_iwr_fallback_enabled():
                fallback_source_url = self._extract_rclone_error_url(error_line) or url
                fallback_url = self._canonicalize_myrient_url(fallback_source_url)
                if fallback_url:
                    monitor_action(f"[!] myrient:rclone:handoff_ps_iwr {filename}")
                    ps_res = self._download_via_powershell_iwr(
                        url=fallback_url,
                        dest=dest,
                        filename=filename,
                        progress_callback=progress_callback,
                        remote_size=remote_size if isinstance(remote_size, int) and remote_size > 0 else None,
                        initial_pct=current_pct,
                    )
                    if str(ps_res.get("status", "")).upper() in {"DONE", "HALTED"}:
                        return ps_res
                    ps_error = str(ps_res.get("error", "") or "").strip()
                    if ps_error:
                        error_line = f"{error_line} | ps_iwr: {ps_error}"
            monitor_action(f"[!] myrient:rclone:error {filename} :: {error_line}")
            self._emit_progress(progress_callback, filename, current_pct if current_pct > 0 else 0.0, error_line, "ERROR")
            return {"url": url, "dest_path": str(dest), "error": error_line, "status": "ERROR", "backend": "rclone", "transport": rclone_transport}
        except FileNotFoundError as exc:
            monitor_action(f"[!] myrient:rclone:error {filename} :: {exc}")
            self._emit_progress(progress_callback, filename, 0.0, str(exc), "ERROR")
            return {"url": url, "dest_path": str(dest), "error": str(exc), "status": "ERROR", "backend": "rclone", "transport": "copyurl"}
        except Exception as exc:
            monitor_action(f"[!] myrient:rclone:error {filename} :: {exc}")
            self._emit_progress(progress_callback, filename, current_pct if current_pct > 0 else 0.0, str(exc), "ERROR")
            return {"url": url, "dest_path": str(dest), "error": str(exc), "status": "ERROR", "backend": "rclone", "transport": "copyurl"}
        finally:
            if proc is not None:
                if self._cancel_event.is_set():
                    self._terminate_subprocess(proc)
                with self._lock:
                    self._active_processes.pop(str(dest), None)

    def halt(self) -> dict:
        """Gracefully stop traffic: cancel queued jobs, signal active jobs to stop."""
        self._cancel_event.set()
        with self._lock:
            items = list(self._futures.items())
            self._futures.clear()
            active_procs = list(self._active_processes.values())
        cancelled = 0
        running = 0
        for future, _meta in items:
            if future.cancel():
                cancelled += 1
            elif future.running():
                running += 1
        for proc in active_procs:
            self._terminate_subprocess(proc)
        return {"success": True, "cancelled": cancelled, "active_signalled": running}


class CoreService:
    def __init__(self, network_enabled: bool = False) -> None:
        self.network_enabled = network_enabled
        self.multi_matcher = MultiROMMatcher()
        self.identified: List[ScannedFile] = []
        self.unidentified: List[ScannedFile] = []
        self.organizer = Organizer()
        self.collection_manager = CollectionManager()
        self.reporter = MissingROMReporter()
        self.dat_library = DATLibrary()
        self.dat_source_manager = DATSourceManager()
        self.scanning = False
        self.scan_progress = 0
        self.scan_total = 0
        self.scan_phase = "idle"
        self.blindmatch_mode = False
        self.blindmatch_system = ""
        self.settings = load_settings()
        self._scan_thread: Optional[threading.Thread] = None
        self._myrient_fetcher = MyrientFetcher()
        self._local_overlay_dir = Path(DATS_DIR) / "_local"
        self._local_overlay_path = self._local_overlay_dir / "R0MM - Local Overrides.xml"
        self._local_overlay_name = "R0MM - Local Overrides"
        self._apply_settings()

    def _apply_settings(self) -> None:
        profile = get_effective_profile(self.settings)
        configure_selection_policy({
            "global_priority": profile.get("region_priority"),
            "per_system": self.settings.get("region_policy", {}).get("per_system", {}),
            "allow_tags": profile.get("allow_tags", []),
            "exclude_tags": profile.get("exclude_tags", []),
        })
        naming = self.settings.get("naming", {})
        configure_naming(naming.get("template"), naming.get("keep_tags"))
        audit = self.settings.get("audit", {})
        configure_audit(audit.get("path"), audit.get("enabled"))

    def get_pyside6_ui_state(self) -> Dict[str, Any]:
        ui_state = self.settings.get("ui_state", {})
        if not isinstance(ui_state, dict):
            return {}
        payload = ui_state.get("pyside6", {})
        return dict(payload) if isinstance(payload, dict) else {}

    def save_pyside6_ui_state(self, payload: Dict[str, Any]) -> None:
        if not isinstance(self.settings.get("ui_state"), dict):
            self.settings["ui_state"] = {}
        safe_payload = dict(payload) if isinstance(payload, dict) else {}
        self.settings["ui_state"]["pyside6"] = safe_payload
        save_settings(self.settings)

    # Session persistence
    def persist_session(self) -> None:
        snapshot = build_snapshot(
            dats=self.multi_matcher.get_dat_list(),
            identified=self.identified,
            unidentified=self.unidentified,
            extras={
                "blindmatch_mode": self.blindmatch_mode,
                "blindmatch_system": self.blindmatch_system,
            },
        )
        save_snapshot(snapshot)

    def restore_session(self) -> None:
        snap = load_snapshot()
        if not snap:
            return
        restore_into_matcher(self.multi_matcher, snap)
        self.identified, self.unidentified = restore_scanned(snap)
        extras = snap.get("extras", {})
        self.blindmatch_mode = bool(extras.get("blindmatch_mode", False))
        self.blindmatch_system = extras.get("blindmatch_system", "")

    def new_session(self) -> None:
        self.multi_matcher = MultiROMMatcher()
        self.identified = []
        self.unidentified = []
        self.blindmatch_mode = False
        self.blindmatch_system = ""
        clear_snapshot()

    # Filesystem browsing
    def fs_list(self, path: str) -> dict:
        if not path:
            if platform.system() == "Windows":
                drives = []
                import string
                from ctypes import windll

                bitmask = windll.kernel32.GetLogicalDrives()
                for letter in string.ascii_uppercase:
                    if bitmask & 1:
                        drives.append(f"{letter}:\\")
                    bitmask >>= 1
                return {"drives": drives, "folders": []}
            return {"drives": ["/"], "folders": []}

        if not os.path.isdir(path):
            return {"error": "Path not found"}

        folders = []
        for name in os.listdir(path):
            full = os.path.join(path, name)
            if os.path.isdir(full):
                folders.append({"name": name, "path": full})
        return {"drives": [], "folders": folders}

    # DAT loading
    def list_dats(self) -> dict:
        return {"dats": [d.to_dict() for d in self.multi_matcher.get_dat_list()]}

    def load_dat(self, filepath: str) -> dict:
        if not filepath or not os.path.exists(filepath):
            return {"error": "File not found"}
        try:
            dat_info, roms = DATParser.parse_with_info(filepath)
            self.multi_matcher.add_dat(dat_info, roms)
            self._rematch_all()
            return {"success": True, "dat": dat_info.to_dict()}
        except Exception as exc:
            return {"error": str(exc)}

    def remove_dat(self, dat_id: str) -> dict:
        if not dat_id:
            return {"error": "dat_id required"}
        self.multi_matcher.remove_dat(dat_id)
        self._rematch_all()
        return {"success": True}

    # Scan
    def start_scan(self, folder: str, scan_archives: bool = True, recursive: bool = True, blindmatch_system: str = "") -> dict:
        if self.scanning:
            return {"error": "Scan already running"}
        if not folder or not os.path.isdir(folder):
            return {"error": "Folder not found"}

        def _worker():
            self.scan_sync(folder, recursive, scan_archives, blindmatch_system)

        self._scan_thread = threading.Thread(target=_worker, daemon=True)
        self._scan_thread.start()
        return {"success": True}

    def scan_sync(
        self,
        folder: str,
        recursive: bool = True,
        scan_archives: bool = True,
        blindmatch_system: str = "",
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> dict:
        if not folder or not os.path.isdir(folder):
            return {"error": "Folder not found"}

        self.scanning = True
        self.scan_progress = 0
        self.scan_total = 0
        self.scan_phase = "scan"
        self.blindmatch_mode = bool(blindmatch_system)
        self.blindmatch_system = blindmatch_system.strip()

        def _progress(current: int, total: int) -> None:
            self.scan_progress = current
            self.scan_total = total
            self.scan_phase = "scan"
            if progress_callback:
                progress_callback(current, total)

        scanned = FileScanner.scan_folder(folder, recursive, scan_archives, progress_callback=_progress)

        if self.blindmatch_mode:
            self.scan_phase = "compare"
            self.scan_progress = 0
            self.scan_total = len(scanned)
            self.identified = []
            self.unidentified = []
            if progress_callback:
                progress_callback(0, self.scan_total)
            for s in scanned:
                s.matched_rom = build_blindmatch_rom(s, self.blindmatch_system)
                self.identified.append(s)
                self.scan_progress += 1
                if progress_callback:
                    progress_callback(self.scan_progress, self.scan_total)
        else:
            self.scan_phase = "compare"
            self.scan_progress = 0
            self.scan_total = len(scanned)
            self.identified = []
            self.unidentified = []
            if progress_callback:
                progress_callback(0, self.scan_total)

            def _compare_progress(current: int, total: int) -> None:
                self.scan_progress = current
                self.scan_total = total
                self.scan_phase = "compare"
                if progress_callback:
                    progress_callback(current, total)

            def _compare_item(
                scanned_item: ScannedFile,
                matched_rom: Optional[ROMInfo],
                _current: int,
                _total: int,
            ) -> None:
                if matched_rom is not None:
                    self.identified.append(scanned_item)
                else:
                    self.unidentified.append(scanned_item)

            identified, unidentified = self.multi_matcher.match_all(
                scanned,
                progress_callback=_compare_progress,
                item_callback=_compare_item,
            )
            # Keep final references aligned with matcher output.
            self.identified = identified
            self.unidentified = unidentified

        self.scanning = False
        self.scan_phase = "idle"
        return {"success": True, "identified": len(self.identified), "unidentified": len(self.unidentified)}

    def _rematch_all(self) -> None:
        all_scanned = self.identified + self.unidentified
        if not all_scanned:
            return
        if self.blindmatch_mode:
            for s in all_scanned:
                s.matched_rom = build_blindmatch_rom(s, self.blindmatch_system)
            self.identified = all_scanned
            self.unidentified = []
            return
        identified, unidentified = self.multi_matcher.match_all(all_scanned)
        self.identified = identified
        self.unidentified = unidentified

    # Force identify
    def force_identify(self, paths: List[str]) -> dict:
        if not paths:
            return {"error": "paths required"}
        to_promote: List[ScannedFile] = []
        remaining: List[ScannedFile] = []
        for f in self.unidentified:
            if f.path in paths or f.filename in paths:
                match = self.multi_matcher.match(f)
                if match:
                    f.matched_rom = match
                    f.forced = True
                    to_promote.append(f)
                elif self.blindmatch_mode:
                    f.matched_rom = build_blindmatch_rom(f, self.blindmatch_system)
                    f.forced = True
                    to_promote.append(f)
                else:
                    remaining.append(f)
            else:
                remaining.append(f)
        self.unidentified = remaining
        self.identified.extend(to_promote)
        return {"success": True, "forced": len(to_promote)}

    @staticmethod
    def _normalize_overlay_text(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _overlay_match_key(*, crc32: str, size: int, md5: str, sha1: str) -> str:
        crc = str(crc32 or "").strip().lower()
        md5v = str(md5 or "").strip().lower()
        sha1v = str(sha1 or "").strip().lower()
        safe_size = max(0, int(size or 0))
        if crc and safe_size > 0:
            return f"crc:{crc}:{safe_size}"
        if md5v:
            return f"md5:{md5v}"
        if sha1v:
            return f"sha1:{sha1v}"
        return ""

    @staticmethod
    def _clean_title_token(text: str) -> str:
        value = str(text or "")
        value = re.sub(r"\[[^\]]*\]", " ", value)
        value = re.sub(r"\([^)]*\)", " ", value)
        value = re.sub(r"[._]+", " ", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    def _infer_title_from_scanned(self, scanned: ScannedFile) -> str:
        raw_path = str(scanned.path or "")
        source_name = str(scanned.filename or "").strip()
        if "|" in raw_path:
            container = raw_path.split("|", 1)[0]
            source_name = Path(container).stem or source_name
        else:
            source_name = Path(source_name).stem or source_name
        cleaned = self._clean_title_token(source_name)
        return cleaned or source_name or "Unknown"

    @staticmethod
    def _infer_system_from_path(path: str) -> str:
        source = str(path or "")
        if "|" in source:
            source = source.split("|", 1)[0]
        parts = [p for p in re.split(r"[\\/]+", source) if p]
        if len(parts) >= 2:
            return parts[-2]
        return "Unknown"

    def _load_local_overlay_roms(self) -> List[ROMInfo]:
        if not self._local_overlay_path.exists():
            return []
        try:
            _header, roms = DATParser.parse(str(self._local_overlay_path))
            return list(roms or [])
        except Exception:
            return []

    def _write_local_overlay_dat(self, roms: List[ROMInfo]) -> None:
        self._local_overlay_dir.mkdir(parents=True, exist_ok=True)

        root = ET.Element("datafile")
        header = ET.SubElement(root, "header")
        ET.SubElement(header, "name").text = self._local_overlay_name
        ET.SubElement(header, "description").text = "User-curated DAT overrides created by R0MM."
        ET.SubElement(header, "version").text = time.strftime("%Y.%m.%d")
        ET.SubElement(header, "author").text = "R0MM"

        self._write_roms_to_xml(
            root=root,
            roms=roms,
            default_status="local",
        )

        tree = ET.ElementTree(root)
        tree.write(str(self._local_overlay_path), encoding="utf-8", xml_declaration=True)

    @staticmethod
    def _write_roms_to_xml(root: ET.Element, roms: List[ROMInfo], default_status: str = "verified") -> None:
        grouped: Dict[str, List[ROMInfo]] = {}
        for rom in roms:
            game = str(rom.game_name or "").strip() or str(rom.name or "").strip() or "Unknown Game"
            grouped.setdefault(game, []).append(rom)

        for game_name in sorted(grouped.keys(), key=lambda x: x.lower()):
            game_node = ET.SubElement(root, "game", {"name": game_name})
            ET.SubElement(game_node, "description").text = game_name
            for rom in sorted(
                grouped[game_name],
                key=lambda item: (
                    str(item.system_name or "").lower(),
                    str(item.name or "").lower(),
                    int(item.size or 0),
                ),
            ):
                attrs: Dict[str, str] = {"name": str(rom.name or game_name)}
                attrs["size"] = str(max(0, int(rom.size or 0)))
                if str(rom.crc32 or "").strip():
                    attrs["crc"] = str(rom.crc32).strip().lower()
                if str(rom.md5 or "").strip():
                    attrs["md5"] = str(rom.md5).strip().lower()
                if str(rom.sha1 or "").strip():
                    attrs["sha1"] = str(rom.sha1).strip().lower()
                attrs["status"] = str(rom.status or default_status or "verified")
                ET.SubElement(game_node, "rom", attrs)

    def suggest_local_dat_metadata(self, scan_id: str, limit: int = 8) -> dict:
        lookup: Dict[str, ScannedFile] = {}
        for scanned in self.unidentified + self.identified:
            lookup[str(scanned.path)] = scanned
            lookup[str(scanned.filename)] = scanned

        target = lookup.get(str(scan_id or "").strip())
        if not target:
            return {"error": "scan entry not found"}

        inferred_title = self._infer_title_from_scanned(target)
        query = self._clean_title_token(inferred_title).lower()
        if not query:
            query = self._clean_title_token(str(target.filename or "")).lower()
        if not query:
            return {"suggestions": []}

        suggestions: List[dict] = []
        for roms in self.multi_matcher.all_roms.values():
            for rom in roms:
                game_name = str(rom.game_name or "").strip() or str(rom.name or "").strip()
                if not game_name:
                    continue
                token = self._clean_title_token(game_name).lower()
                if not token:
                    continue
                score = difflib.SequenceMatcher(None, query, token).ratio()
                if query in token:
                    score += 0.30
                elif token in query:
                    score += 0.20
                if score < 0.45:
                    continue
                suggestions.append(
                    {
                        "game_name": game_name,
                        "rom_name": str(rom.name or game_name).strip() or game_name,
                        "system_name": str(rom.system_name or "").strip(),
                        "region": str(rom.region or "").strip(),
                        "score": round(min(1.0, score), 3),
                    }
                )

        # Deduplicate by core identity and keep highest-score first.
        dedup: Dict[Tuple[str, str, str], dict] = {}
        for item in sorted(suggestions, key=lambda x: (-float(x.get("score", 0.0)), str(x.get("game_name", "")).lower())):
            key = (
                str(item.get("game_name", "")).lower(),
                str(item.get("system_name", "")).lower(),
                str(item.get("region", "")).lower(),
            )
            if key not in dedup:
                dedup[key] = item

        top = list(dedup.values())[: max(1, int(limit or 8))]
        return {
            "query": inferred_title,
            "suggestions": top,
        }

    def fetch_online_metadata_hints(self, query: str, system: str = "", limit: int = 6) -> dict:
        term = self._normalize_overlay_text(query)
        if not term:
            return {"error": "query required"}
        if system:
            term = f"{term} {self._normalize_overlay_text(system)}"

        params = urlencode(
            {
                "action": "opensearch",
                "search": term,
                "limit": max(1, min(10, int(limit or 6))),
                "namespace": 0,
                "format": "json",
            }
        )
        url = f"https://en.wikipedia.org/w/api.php?{params}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "R0MM/2 MetadataHint (+local desktop app)"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
        except Exception as exc:
            return {"error": str(exc)}

        items: List[dict] = []
        try:
            titles = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
            descriptions = payload[2] if isinstance(payload, list) and len(payload) > 2 else []
            links = payload[3] if isinstance(payload, list) and len(payload) > 3 else []
            for idx, title in enumerate(titles):
                t = str(title or "").strip()
                if not t:
                    continue
                desc = str(descriptions[idx] if idx < len(descriptions) else "").strip()
                link = str(links[idx] if idx < len(links) else "").strip()
                items.append({"title": t, "description": desc, "url": link, "source": "wikipedia"})
        except Exception:
            items = []
        return {"query": query, "items": items}

    def add_unidentified_to_local_dat(self, entries: List[Dict[str, Any]]) -> dict:
        if not entries:
            return {"error": "entries required"}

        by_scan_id: Dict[str, ScannedFile] = {}
        for scanned in self.unidentified:
            by_scan_id[str(scanned.path)] = scanned
            by_scan_id[str(scanned.filename)] = scanned

        existing_roms = self._load_local_overlay_roms()
        indexed: Dict[str, ROMInfo] = {}
        for rom in existing_roms:
            key = self._overlay_match_key(
                crc32=rom.crc32,
                size=int(rom.size or 0),
                md5=rom.md5,
                sha1=rom.sha1,
            )
            if key:
                indexed[key] = rom

        added = 0
        updated = 0
        skipped = 0
        touched_scan_ids: List[str] = []

        for row in entries:
            if not isinstance(row, dict):
                skipped += 1
                continue
            scan_id = self._normalize_overlay_text(row.get("id") or row.get("path"))
            if not scan_id:
                skipped += 1
                continue
            scanned = by_scan_id.get(scan_id)
            if not scanned:
                skipped += 1
                continue

            key = self._overlay_match_key(
                crc32=scanned.crc32,
                size=int(scanned.size or 0),
                md5=scanned.md5,
                sha1=scanned.sha1,
            )
            if not key:
                skipped += 1
                continue

            inferred_title = self._infer_title_from_scanned(scanned)
            game_name = self._normalize_overlay_text(row.get("game_name")) or inferred_title
            rom_name = self._normalize_overlay_text(row.get("rom_name")) or str(scanned.filename or game_name)
            system_name = (
                self._normalize_overlay_text(row.get("system_name"))
                or self._normalize_overlay_text(row.get("system"))
                or self._infer_system_from_path(scanned.path)
                or "Unknown"
            )
            region = self._normalize_overlay_text(row.get("region")) or DATParser._extract_region(game_name)
            status = self._normalize_overlay_text(row.get("status")) or "local"

            candidate = ROMInfo(
                name=rom_name,
                size=max(0, int(scanned.size or 0)),
                crc32=str(scanned.crc32 or "").strip().lower(),
                md5=str(scanned.md5 or "").strip().lower(),
                sha1=str(scanned.sha1 or "").strip().lower(),
                description=game_name,
                game_name=game_name,
                region=region,
                languages="",
                status=status,
                system_name=system_name,
            )
            if key in indexed:
                updated += 1
            else:
                added += 1
            indexed[key] = candidate
            touched_scan_ids.append(scan_id)

        if added <= 0 and updated <= 0:
            return {"error": "no valid unidentified entries selected"}

        final_roms = list(indexed.values())
        self._write_local_overlay_dat(final_roms)

        imported = self.dat_library_import(str(self._local_overlay_path))
        if imported.get("error"):
            return imported
        dat = imported.get("dat", {}) if isinstance(imported, dict) else {}
        dat_id = self._normalize_overlay_text(dat.get("id"))

        loaded = False
        if dat_id:
            loaded_res = self.dat_library_load(dat_id)
            loaded = bool(loaded_res.get("success"))

        self._rematch_all()
        return {
            "success": True,
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "selected": len(entries),
            "matched_after": len(touched_scan_ids),
            "dat_id": dat_id,
            "filepath": str(self._local_overlay_path),
            "loaded": loaded,
        }

    # --- Editable per-DAT overlays (_EDIT_ prefix) ---
    def _find_dat_by_id(self, dat_id: str) -> Optional[DATInfo]:
        for d in self.multi_matcher.get_dat_list():
            if d.id == dat_id:
                return d
        for d in self.dat_library.list_dats():
            if d.id == dat_id:
                return d
        return None

    def _load_roms_from_dat(self, filepath: str) -> Tuple[dict, List[ROMInfo]]:
        header, roms = DATParser.parse(filepath)
        return header, roms

    def _edit_dat_path_for(self, dat_info: DATInfo) -> Path:
        src = Path(dat_info.filepath)
        if src.name.startswith("_EDIT_"):
            return src
        name = "_EDIT_" + src.name
        return src.with_name(name)

    def add_to_edit_dat(self, entries: List[Dict[str, Any]], target_dat_id: str) -> dict:
        if not entries:
            return {"error": "entries required"}
        target = self._find_dat_by_id(str(target_dat_id or "").strip())
        if not target:
            return {"error": "target DAT not found"}
        if not target.filepath or not os.path.exists(target.filepath):
            return {"error": "target DAT file missing"}

        edit_path = self._edit_dat_path_for(target)

        # Load baseline ROMs (existing edit dat or original dat)
        try:
            base_header, base_roms = self._load_roms_from_dat(str(edit_path if edit_path.exists() else target.filepath))
        except Exception as exc:
            return {"error": f"failed to read base DAT: {exc}"}

        # Deduplicate by hash key
        existing: Dict[str, ROMInfo] = {}
        for rom in base_roms:
            key = self._overlay_match_key(
                crc32=rom.crc32,
                size=int(rom.size or 0),
                md5=rom.md5,
                sha1=rom.sha1,
            )
            if key:
                existing[key] = rom

        added = 0
        updated = 0
        skipped = 0

        for row in entries:
            if not isinstance(row, dict):
                skipped += 1
                continue
            crc32 = str(row.get("crc32", "") or "").strip().lower()
            md5 = str(row.get("md5", "") or "").strip().lower()
            sha1 = str(row.get("sha1", "") or "").strip().lower()
            try:
                size = int(row.get("size", 0) or 0)
            except Exception:
                size = 0
            key = self._overlay_match_key(crc32=crc32, size=size, md5=md5, sha1=sha1)
            if not key:
                skipped += 1
                continue
            rom = ROMInfo(
                name=str(row.get("rom_name", "") or row.get("game_name", "") or "Unknown"),
                size=size,
                crc32=crc32,
                md5=md5,
                sha1=sha1,
                description=str(row.get("game_name", "") or row.get("rom_name", "") or ""),
                game_name=str(row.get("game_name", "") or row.get("rom_name", "") or ""),
                region=str(row.get("region", "") or ""),
                languages="",
                status=str(row.get("status", "") or "verified"),
                dat_id="",
                system_name=str(row.get("system_name", "") or row.get("system", "") or target.system_name),
            )
            if key in existing:
                updated += 1
            else:
                added += 1
            existing[key] = rom

        if added <= 0 and updated <= 0:
            return {"error": "no valid entries to add"}

        header_name = str(base_header.get("name") or target.name or Path(edit_path).stem)
        header_desc = str(base_header.get("description") or header_name)
        header_version = str(base_header.get("version") or target.version or time.strftime("%Y.%m.%d"))

        root = ET.Element("datafile")
        header_node = ET.SubElement(root, "header")
        ET.SubElement(header_node, "name").text = header_name
        ET.SubElement(header_node, "description").text = header_desc
        ET.SubElement(header_node, "version").text = header_version
        ET.SubElement(header_node, "author").text = "R0MM _EDIT_"

        self._write_roms_to_xml(root=root, roms=list(existing.values()), default_status="verified")

        edit_path.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(root).write(str(edit_path), encoding="utf-8", xml_declaration=True)

        imported = self.dat_library_import(str(edit_path))
        if imported.get("error"):
            return imported
        dat = imported.get("dat", {}) if isinstance(imported, dict) else {}
        dat_id = str(dat.get("id", "") or "").strip()
        loaded = False
        if dat_id:
            load_res = self.dat_library_load(dat_id)
            loaded = bool(load_res.get("success"))
        self._rematch_all()
        return {
            "success": True,
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "dat_id": dat_id,
            "filepath": str(edit_path),
            "loaded": loaded,
        }

    # Status / results
    def get_status(self) -> dict:
        loaded_dats = self.multi_matcher.get_dat_list()
        return {
            "scanning": self.scanning,
            "scan_progress": self.scan_progress,
            "scan_total": self.scan_total,
            "scan_phase": self.scan_phase,
            "dat_count": len(loaded_dats),
            "dats_loaded": [d.to_dict() for d in loaded_dats],
            "identified_count": len(self.identified),
            "unidentified_count": len(self.unidentified),
            "blindmatch_mode": self.blindmatch_mode,
            "blindmatch_system": self.blindmatch_system,
        }

    @staticmethod
    def _region_css(region: str) -> dict:
        c = REGION_COLORS.get(region, None)
        css_bg = c.get("bg") if isinstance(c, dict) else None
        css_fg = c.get("fg") if isinstance(c, dict) else None
        if not css_bg:
            css_bg = DEFAULT_REGION_COLOR.get("bg", "#333333")
        if not css_fg:
            css_fg = DEFAULT_REGION_COLOR.get("fg", "#ffffff")
        return {"css_bg": css_bg, "css_fg": css_fg}

    def _serialize_scanned(self, f: ScannedFile) -> dict:
        rom = f.matched_rom
        region = rom.region if rom else "Unknown"
        rc = self._region_css(region)
        return {
            "id": f.path,
            "path": f.path,
            "filename": f.filename,
            "size": f.size,
            "size_formatted": format_size(f.size),
            "crc32": f.crc32.upper() if f.crc32 else "",
            "md5": f.md5.upper() if f.md5 else "",
            "sha1": f.sha1.upper() if f.sha1 else "",
            "rom_name": rom.name if rom else "",
            "game_name": rom.game_name if rom else "",
            "system": rom.system_name if rom else "",
            "region": region,
            "status": rom.status if rom else "",
            "forced": f.forced,
            "original_file": f.path,
            "css_bg": rc["css_bg"],
            "css_fg": rc["css_fg"],
        }

    def get_results(self) -> dict:
        return {
            "identified": [self._serialize_scanned(f) for f in self.identified],
            "unidentified": [self._serialize_scanned(f) for f in self.unidentified],
        }

    def get_missing(self) -> dict:
        report = self.reporter.generate_multi_report(
            self.multi_matcher.dat_infos, self.multi_matcher.all_roms, self.identified
        )
        missing = []
        for dat_report in report.get("by_dat", {}).values():
            for m in dat_report.get("missing", []):
                rc = self._region_css(m.get("region") or "Unknown")
                missing.append({
                    "rom_name": m.get("name"),
                    "game_name": m.get("game_name"),
                    "system": dat_report.get("system_name"),
                    "region": m.get("region"),
                    "size": m.get("size"),
                    "size_formatted": m.get("size_formatted"),
                    "crc32": m.get("crc32"),
                    "css_bg": rc["css_bg"],
                    "css_fg": rc["css_fg"],
                })
        completeness = {
            "total_in_dat": report.get("total_in_all_dats", 0),
            "found": report.get("found_in_all", 0),
            "missing": report.get("missing_in_all", 0),
            "percentage": report.get("overall_percentage", 0),
        }
        return {"missing": missing, "completeness": completeness, "completeness_by_dat": report.get("by_dat", {})}

    # Dashboard intel (dynamic providers; only RSS uses offline fallback)
    def fetch_dat_syndicate(self) -> dict:
        now = time.time()
        stale_after_seconds = 30 * 24 * 60 * 60
        items: List[dict] = []
        seen_paths: set[str] = set()

        # Prefer indexed DAT library entries, then include any ad-hoc loaded DATs.
        dat_candidates = list(self.dat_library.list_dats()) + list(self.multi_matcher.get_dat_list())
        for dat in dat_candidates:
            filepath = (getattr(dat, "filepath", "") or "").strip()
            if not filepath:
                continue
            try:
                path = Path(filepath)
            except Exception:
                continue
            norm = os.path.normcase(os.path.normpath(str(path)))
            if norm in seen_paths:
                continue
            seen_paths.add(norm)
            try:
                stat = path.stat()
            except OSError:
                continue

            age_seconds = max(0.0, now - float(stat.st_mtime))
            age_days = int(age_seconds // 86400)
            status = "OUTDATED" if age_seconds > stale_after_seconds else "SYNCED"
            version = (getattr(dat, "version", "") or "").strip() or time.strftime("%Y%m%d", time.localtime(stat.st_mtime))
            name = (getattr(dat, "system_name", "") or getattr(dat, "name", "") or path.stem).strip() or path.stem
            items.append({
                "name": name,
                "status": status,
                "version": version,
                "path": str(path),
                "age_days": age_days,
                "mtime": int(stat.st_mtime),
            })

        # Fallback to raw file scan in the DAT library folder if index is empty/stale.
        if not items:
            dat_root = Path(DATS_DIR)
            if dat_root.is_dir():
                for path in sorted(dat_root.rglob("*")):
                    if not path.is_file():
                        continue
                    if path.suffix.lower() not in {".dat", ".xml", ".zip", ".gz"}:
                        continue
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    age_seconds = max(0.0, now - float(stat.st_mtime))
                    items.append({
                        "name": path.stem,
                        "status": "OUTDATED" if age_seconds > stale_after_seconds else "SYNCED",
                        "version": time.strftime("%Y%m%d", time.localtime(stat.st_mtime)),
                        "path": str(path),
                        "age_days": int(age_seconds // 86400),
                        "mtime": int(stat.st_mtime),
                    })

        items.sort(key=lambda row: (row.get("status") != "OUTDATED", -int(row.get("mtime", 0)), str(row.get("name", "")).lower()))
        return {
            "items": items[:8],
            "source_dir": str(Path(DATS_DIR)),
            "generated_at": int(now),
            "simulated": False,
        }

    def get_bounty_board(self) -> dict:
        rows: List[dict] = []

        # Optional future compatibility with a DB-backed stats provider.
        db = getattr(self, "_db", None)
        db_stats = getattr(db, "get_missing_stats", None)
        if callable(db_stats):
            try:
                for item in db_stats() or []:
                    total = int(item.get("total", 0) or 0)
                    missing = int(item.get("missing", 0) or 0)
                    have = max(0, total - missing)
                    if missing <= 0:
                        continue
                    pct = (have / total * 100.0) if total > 0 else 0.0
                    rows.append({
                        "system": item.get("system") or item.get("name") or "Unknown",
                        "have": have,
                        "total": total,
                        "missing": missing,
                        "pct": round(pct, 1),
                    })
            except Exception:
                rows = []

        if not rows:
            report = self.reporter.generate_multi_report(
                self.multi_matcher.dat_infos,
                self.multi_matcher.all_roms,
                self.identified,
            )
            for dat_report in report.get("by_dat", {}).values():
                total = int(dat_report.get("total_in_dat", 0) or 0)
                found = int(dat_report.get("found", 0) or 0)
                missing = int(dat_report.get("missing_count", 0) or 0)
                if missing <= 0:
                    continue
                rows.append({
                    "system": dat_report.get("system_name") or dat_report.get("dat_name") or "Unknown",
                    "have": found,
                    "total": total,
                    "missing": missing,
                    "pct": round(float(dat_report.get("percentage", 0.0) or 0.0), 1),
                })

        rows.sort(key=lambda r: (-int(r.get("missing", 0)), float(r.get("pct", 0.0)), str(r.get("system", "")).lower()))
        return {
            "items": rows[:4],
            "generated_at": int(time.time()),
            "simulated": False,
        }

    def get_storage_telemetry(self) -> dict:
        tracked_files: Dict[str, dict] = {}
        base_dirs: set[str] = set()

        def _register_entry(entry: dict, fallback_system: str = "Unidentified", scan_folder: str = "") -> None:
            raw_path = str(entry.get("path", "") or "").strip()
            if not raw_path:
                return
            try:
                path = Path(raw_path)
            except Exception:
                return

            matched = entry.get("matched_rom") or {}
            system = str(matched.get("system_name") or fallback_system or "Unidentified").strip() or "Unidentified"
            norm = os.path.normcase(os.path.normpath(str(path)))
            existing = tracked_files.get(norm)
            if existing and existing.get("system") == "Unidentified" and system != "Unidentified":
                existing["system"] = system
            elif not existing:
                tracked_files[norm] = {
                    "path": str(path),
                    "system": system,
                    "size_hint": int(entry.get("size", 0) or 0),
                }

            base_candidate = str(scan_folder or path.parent)
            if base_candidate:
                base_dirs.add(base_candidate)

        # Current in-memory session first.
        for scanned in self.identified + self.unidentified:
            system = "Unidentified"
            if scanned.matched_rom and getattr(scanned.matched_rom, "system_name", ""):
                system = scanned.matched_rom.system_name
            _register_entry({
                "path": getattr(scanned, "path", ""),
                "size": int(getattr(scanned, "size", 0) or 0),
                "matched_rom": {"system_name": system},
            }, fallback_system=system)

        # Saved collections on disk (dynamic filesystem-backed telemetry source).
        for meta in self.collection_manager.list_saved():
            col_path = str(meta.get("filepath", "") or "").strip()
            if not col_path:
                continue
            try:
                payload = json.loads(Path(col_path).read_text(encoding="utf-8"))
            except Exception:
                continue
            scan_folder = str(payload.get("scan_folder", "") or "").strip()
            for entry in payload.get("identified", []) or []:
                if isinstance(entry, dict):
                    _register_entry(entry, fallback_system="Unknown", scan_folder=scan_folder)
            for entry in payload.get("unidentified", []) or []:
                if isinstance(entry, dict):
                    _register_entry(entry, fallback_system="Unidentified", scan_folder=scan_folder)

        buckets: Dict[str, int] = {}
        seen_files: set[str] = set()

        # Walk the known base directories using pathlib, but count only tracked files.
        for raw_base in sorted(base_dirs):
            try:
                base = Path(raw_base)
            except Exception:
                continue
            if not base.is_dir():
                continue
            try:
                iterator = base.rglob("*")
            except Exception:
                continue
            for child in iterator:
                try:
                    if not child.is_file():
                        continue
                except OSError:
                    continue
                norm = os.path.normcase(os.path.normpath(str(child)))
                tracked = tracked_files.get(norm)
                if not tracked or norm in seen_files:
                    continue
                try:
                    size = int(child.stat().st_size)
                except OSError:
                    size = int(tracked.get("size_hint", 0) or 0)
                buckets[tracked["system"]] = buckets.get(tracked["system"], 0) + max(size, 0)
                seen_files.add(norm)

        # If a tracked file was outside/inaccessible from a base dir walk, count it directly.
        for norm, tracked in tracked_files.items():
            if norm in seen_files:
                continue
            try:
                path = Path(tracked["path"])
                size = int(path.stat().st_size) if path.is_file() else 0
            except OSError:
                size = int(tracked.get("size_hint", 0) or 0)
            if size <= 0:
                continue
            buckets[tracked["system"]] = buckets.get(tracked["system"], 0) + size

        rows = [
            {
                "system": system,
                "size_gb": round(size_bytes / (1024 ** 3), 1),
                "size_bytes": int(size_bytes),
            }
            for system, size_bytes in buckets.items()
            if size_bytes > 0
        ]
        rows.sort(key=lambda r: (-int(r.get("size_bytes", 0)), str(r.get("system", "")).lower()))
        return {
            "items": rows[:12],
            "base_dirs": sorted(base_dirs),
            "tracked_files": len(tracked_files),
            "generated_at": int(time.time()),
            "simulated": False,
        }

    def fetch_retro_news(self) -> dict:
        feeds = [
            "https://www.romhacking.net/rss/news/",
            "https://www.retroarch.com/rss.xml",
        ]
        headlines: List[str] = []
        source = ""
        last_error = ""

        for url in feeds:
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "R0MM/2 Dashboard Intel (+https://localhost)",
                        "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.1",
                    },
                )
                with urllib.request.urlopen(req, timeout=3) as resp:
                    raw = resp.read(512 * 1024)
                parser = ET.XMLParser()
                root = ET.fromstring(raw, parser=parser)
                titles: List[str] = []

                for item in root.findall(".//channel/item"):
                    title = (item.findtext("title") or "").strip()
                    if title:
                        titles.append(title)

                # Atom fallback if RSS <item> nodes are not present.
                if not titles:
                    for elem in root.findall(".//{*}entry/{*}title"):
                        title = ("".join(elem.itertext()) if elem is not None else "").strip()
                        if title:
                            titles.append(title)

                if titles:
                    headlines = titles[:5]
                    source = url
                    break
            except Exception as exc:
                last_error = str(exc)
                continue

        if not headlines:
            headlines = [
                "OFLINE: RSS Feed inativo",
                "OFLINE: Verifique conectividade para atualizar o painel",
                "OFLINE: Fallback local ativo",
            ]
            source = "offline-fallback"

        return {
            "items": headlines[:5],
            "source": source,
            "error": last_error,
            "generated_at": int(time.time()),
            "simulated": False,
        }

    # Remote extraction (user-authorized exception: MyrientFetcher)
    @staticmethod
    def _jdownloader_endpoint() -> str:
        endpoint = (os.getenv("R0MM_JDOWNLOADER_ENDPOINT", "") or "").strip()
        if not endpoint:
            endpoint = "http://127.0.0.1:9666/flashgot"
        return endpoint

    @staticmethod
    def _normalize_jdownloader_boot_mode(raw: str, default: str = "gui") -> str:
        mode = (raw or "").strip().lower()
        if mode not in {"auto", "gui", "silent", "headless"}:
            mode = (default or "gui").strip().lower()
        if mode not in {"auto", "gui", "silent", "headless"}:
            mode = "gui"
        return mode

    @staticmethod
    def _normalize_jdownloader_tune_profile(raw: str, default: str = "balanced") -> str:
        profile = (raw or "").strip().lower()
        if profile not in {"conservative", "balanced", "aggressive"}:
            profile = (default or "balanced").strip().lower()
        if profile not in {"conservative", "balanced", "aggressive"}:
            profile = "balanced"
        return profile

    @staticmethod
    def _coerce_optional_bool(value: Any) -> Optional[bool]:
        if isinstance(value, bool):
            return bool(value)
        if value is None:
            return None
        raw = str(value).strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
        return None

    @staticmethod
    def _normalize_jdownloader_flashgot_url(endpoint: str) -> str:
        safe = (endpoint or "").strip()
        if not safe:
            safe = "http://127.0.0.1:9666/flashgot"
        parsed = urlsplit(safe)
        if not parsed.path or parsed.path == "/":
            safe = safe.rstrip("/") + "/flashgot"
        return safe

    @classmethod
    def _jdownloader_endpoint_candidates(cls, endpoint: str) -> List[str]:
        raw = (endpoint or cls._jdownloader_endpoint()).strip()
        if not raw:
            raw = "http://127.0.0.1:9666/flashgot"

        candidates: List[str] = []
        seen: set[str] = set()

        def _push(url: str) -> None:
            normalized = cls._normalize_jdownloader_flashgot_url(url)
            if normalized not in seen:
                seen.add(normalized)
                candidates.append(normalized)

        _push(raw)

        parts = urlsplit(raw)
        scheme = parts.scheme or "http"
        host = (parts.hostname or "").strip().lower()
        port = parts.port
        port_suffix = f":{port}" if port else ""
        path = parts.path or "/flashgot"
        if not path or path == "/":
            path = "/flashgot"

        if host == "127.0.0.1":
            _push(f"{scheme}://localhost{port_suffix}{path}")
            _push(f"{scheme}://[::1]{port_suffix}{path}")
        elif host == "localhost":
            _push(f"{scheme}://127.0.0.1{port_suffix}{path}")
            _push(f"{scheme}://[::1]{port_suffix}{path}")
        elif host == "::1":
            _push(f"{scheme}://localhost{port_suffix}{path}")
            _push(f"{scheme}://127.0.0.1{port_suffix}{path}")
        else:
            _push(f"{scheme}://127.0.0.1:9666/flashgot")
            _push(f"{scheme}://localhost:9666/flashgot")
            _push(f"{scheme}://[::1]:9666/flashgot")

        return candidates

    @staticmethod
    def _jdownloader_endpoint_hint(base_endpoint: str) -> str:
        parsed = urlsplit(base_endpoint or "")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 9666
        return (
            "Ensure JDownloader is running and its local Extern/FlashGot interface "
            f"is reachable at http://{host}:{port}/flashgot."
        )

    @staticmethod
    def _jdownloader_general_settings_path() -> str:
        env_cfg = (os.getenv("R0MM_JDOWNLOADER_GENERAL_SETTINGS", "") or "").strip()
        if env_cfg:
            p = Path(env_cfg)
            if p.is_file():
                return str(p)
        local_appdata = Path(os.getenv("LOCALAPPDATA", "") or "")
        appdata = Path(os.getenv("APPDATA", "") or "")
        candidates = [
            local_appdata / "JDownloader 2" / "cfg" / "org.jdownloader.settings.GeneralSettings.json",
            local_appdata / "JDownloader 2.0" / "cfg" / "org.jdownloader.settings.GeneralSettings.json",
            appdata / "JDownloader 2" / "cfg" / "org.jdownloader.settings.GeneralSettings.json",
            appdata / "JDownloader 2.0" / "cfg" / "org.jdownloader.settings.GeneralSettings.json",
        ]
        for candidate in candidates:
            try:
                if candidate.is_file():
                    return str(candidate)
            except Exception:
                continue
        return ""

    @classmethod
    def _jdownloader_remote_api_config_path(cls, binary_path: str = "") -> str:
        safe_bin = str(binary_path or "").strip().strip('"')
        candidates: List[Path] = []
        if safe_bin:
            try:
                bin_parent = Path(safe_bin).parent
                candidates.append(bin_parent / "cfg" / "org.jdownloader.api.RemoteAPIConfig.json")
            except Exception:
                pass

        local_appdata = Path(os.getenv("LOCALAPPDATA", "") or "")
        appdata = Path(os.getenv("APPDATA", "") or "")
        candidates.extend(
            [
                local_appdata / "JDownloader 2" / "cfg" / "org.jdownloader.api.RemoteAPIConfig.json",
                local_appdata / "JDownloader 2.0" / "cfg" / "org.jdownloader.api.RemoteAPIConfig.json",
                appdata / "JDownloader 2" / "cfg" / "org.jdownloader.api.RemoteAPIConfig.json",
                appdata / "JDownloader 2.0" / "cfg" / "org.jdownloader.api.RemoteAPIConfig.json",
            ]
        )

        for candidate in candidates:
            try:
                if candidate.is_file():
                    return str(candidate)
            except Exception:
                continue

        # Fallback path for first-run setups where config file does not exist yet.
        for candidate in candidates:
            try:
                parent = candidate.parent
                if parent and parent.exists():
                    return str(candidate)
            except Exception:
                continue
        return ""

    def _jdownloader_apply_perf_tuning(
        self,
        *,
        enabled: Optional[bool] = None,
        profile: str = "",
    ) -> dict:
        enabled_value = enabled
        if enabled_value is None:
            enabled_value = self._coerce_optional_bool(os.getenv("R0MM_JDOWNLOADER_TUNE", "1"))
        if enabled_value is False:
            return {"enabled": False, "applied": False, "reason": "disabled"}
        profile_value = (profile or "").strip()
        if not profile_value:
            profile_value = (os.getenv("R0MM_JDOWNLOADER_TUNE_PROFILE", "balanced") or "balanced").strip()
        profile = self._normalize_jdownloader_tune_profile(profile_value, default="balanced")

        cfg_path = self._jdownloader_general_settings_path()
        if not cfg_path:
            return {"enabled": True, "applied": False, "reason": "settings_not_found", "profile": profile}

        try:
            raw = Path(cfg_path).read_text(encoding="utf-8", errors="ignore")
            payload = json.loads(raw or "{}")
            if not isinstance(payload, dict):
                payload = {}
        except Exception as exc:
            return {
                "enabled": True,
                "applied": False,
                "reason": f"read_failed:{exc}",
                "profile": profile,
                "path": cfg_path,
            }

        if profile == "conservative":
            targets = {
                "downloadspeedlimitenabled": False,
                "maxdownloadsperhostenabled": True,
                "maxsimultanedownloads": 3,
                "maxsimultanedownloadsperhost": 2,
                "maxchunksperfile": 2,
            }
        elif profile == "aggressive":
            targets = {
                "downloadspeedlimitenabled": False,
                "maxdownloadsperhostenabled": False,
                "maxsimultanedownloads": 20,
                "maxsimultanedownloadsperhost": 20,
                "maxchunksperfile": 20,
            }
        else:
            targets = {
                "downloadspeedlimitenabled": False,
                "maxdownloadsperhostenabled": True,
                "maxsimultanedownloads": 4,
                "maxsimultanedownloadsperhost": 4,
                "maxchunksperfile": 4,
            }

        changes: Dict[str, Dict[str, Any]] = {}

        def _set_if_diff(key: str, value: Any) -> None:
            old = payload.get(key)
            if old == value:
                return
            payload[key] = value
            changes[key] = {"old": old, "new": value}

        for key, value in targets.items():
            _set_if_diff(key, value)

        if not changes:
            return {
                "enabled": True,
                "applied": True,
                "changed": False,
                "changes": {},
                "profile": profile,
                "path": cfg_path,
            }

        try:
            text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            Path(cfg_path).write_text(text, encoding="utf-8", errors="ignore")
        except Exception as exc:
            return {
                "enabled": True,
                "applied": False,
                "reason": f"write_failed:{exc}",
                "changes": changes,
                "profile": profile,
                "path": cfg_path,
            }
        return {
            "enabled": True,
            "applied": True,
            "changed": True,
            "changes": changes,
            "profile": profile,
            "path": cfg_path,
        }

    @staticmethod
    def jdownloader_probe_content_length(url: str, timeout_s: float = 2.5) -> int:
        safe_url = str(url or "").strip()
        if not safe_url:
            return 0

        headers = {
            "User-Agent": "R0MM/2 JDownloaderBridge (+local desktop app)",
            "Accept": "*/*",
        }
        try:
            head_req = urllib.request.Request(safe_url, headers=headers, method="HEAD")
            with urllib.request.urlopen(head_req, timeout=float(timeout_s)) as resp:
                content_length = int(resp.headers.get("Content-Length") or 0)
                if content_length > 0:
                    return content_length
        except Exception:
            pass

        try:
            range_headers = dict(headers)
            range_headers["Range"] = "bytes=0-0"
            get_req = urllib.request.Request(safe_url, headers=range_headers, method="GET")
            with urllib.request.urlopen(get_req, timeout=float(timeout_s)) as resp:
                content_range = str(resp.headers.get("Content-Range") or "").strip()
                if content_range:
                    match = re.search(r"/(\d+)\s*$", content_range)
                    if match:
                        return int(match.group(1))
                content_length = int(resp.headers.get("Content-Length") or 0)
                if content_length > 0:
                    return content_length
        except Exception:
            pass
        return 0

    @staticmethod
    def _is_local_host(hostname: str) -> bool:
        host = (hostname or "").strip().lower()
        return host in {"127.0.0.1", "localhost", "::1"}

    @staticmethod
    def _tcp_port_open(host: str, port: int, timeout_s: float = 0.35) -> bool:
        if not host or port <= 0:
            return False
        try:
            with socket.create_connection((host, int(port)), timeout=timeout_s):
                return True
        except OSError:
            return False

    @classmethod
    def _resolve_jdownloader_binary(cls) -> str:
        def _normalize_exe(raw: str) -> str:
            safe = (raw or "").strip().strip('"')
            if not safe:
                return ""
            # Registry fields may come as `"C:\path\app.exe",0` or include CLI args.
            if "," in safe and safe.lower().endswith((".exe,0", ".exe,1", ".exe,2", ".exe,3")):
                safe = safe.split(",", 1)[0].strip().strip('"')
            if ".exe" in safe.lower() and not safe.lower().endswith(".exe"):
                m = re.match(r'^\s*"?(?P<p>[^"]+?\.exe)"?(?:\s+.*)?$', safe, flags=re.IGNORECASE)
                if m:
                    safe = m.group("p").strip()
            p = Path(safe)
            allowed_names = {"jdownloader2.exe", "jdownloader.exe"}
            if p.is_file():
                name = p.name.lower().strip()
                if p.suffix.lower() != ".exe" or name not in allowed_names:
                    return ""
                return str(p)
            if p.is_dir():
                for name in ("JDownloader2.exe", "JDownloader.exe"):
                    candidate = p / name
                    if candidate.is_file():
                        return str(candidate)
            return ""

        env_path = (os.getenv("R0MM_JDOWNLOADER_BIN", "") or "").strip()
        env_resolved = _normalize_exe(env_path)
        if env_resolved:
            return env_resolved

        for name in (
            "JDownloader2.exe",
            "JDownloader2",
            "jdownloader2.exe",
            "jdownloader2",
            "JDownloader.exe",
            "jdownloader.exe",
            "jdownloader",
        ):
            resolved = shutil.which(name)
            if resolved:
                return str(Path(resolved))

        local_appdata = Path(os.getenv("LOCALAPPDATA", "") or "")
        appdata = Path(os.getenv("APPDATA", "") or "")
        userprofile = Path(os.getenv("USERPROFILE", "") or "")
        pf = Path(os.getenv("ProgramFiles", "") or "")
        pfx86 = Path(os.getenv("ProgramFiles(x86)", "") or "")
        cwd = Path.cwd()
        candidates = [
            local_appdata / "JDownloader 2" / "JDownloader2.exe",
            local_appdata / "JDownloader 2.0" / "JDownloader2.exe",
            local_appdata / "JDownloader2" / "JDownloader2.exe",
            local_appdata / "JDownloader" / "JDownloader2.exe",
            appdata / "JDownloader 2" / "JDownloader2.exe",
            appdata / "JDownloader 2.0" / "JDownloader2.exe",
            appdata / "JDownloader2" / "JDownloader2.exe",
            pf / "JDownloader" / "JDownloader2.exe",
            pf / "JDownloader 2.0" / "JDownloader2.exe",
            pfx86 / "JDownloader" / "JDownloader2.exe",
            pfx86 / "JDownloader 2.0" / "JDownloader2.exe",
            cwd / "JDownloader2.exe",
            cwd / "jdownloader2.exe",
            cwd / "JDownloader.exe",
            userprofile / "Downloads" / "JDownloader2.exe",
            userprofile / "Downloads" / "JDownloader" / "JDownloader2.exe",
            userprofile / "Desktop" / "JDownloader2.exe",
            userprofile / "Desktop" / "JDownloader" / "JDownloader2.exe",
        ]
        for candidate in candidates:
            try:
                if candidate and candidate.is_file():
                    return str(candidate)
            except Exception:
                continue

        if os.name == "nt" and winreg is not None:
            uninstall_paths = [
                (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            ]
            for hive, root_path in uninstall_paths:
                try:
                    with winreg.OpenKey(hive, root_path) as root_key:
                        sub_count = int(winreg.QueryInfoKey(root_key)[0] or 0)
                        for idx in range(sub_count):
                            try:
                                sub_name = winreg.EnumKey(root_key, idx)
                                with winreg.OpenKey(root_key, sub_name) as sub_key:
                                    try:
                                        display_name = str(winreg.QueryValueEx(sub_key, "DisplayName")[0] or "")
                                    except Exception:
                                        display_name = ""
                                    marker = f"{sub_name} {display_name}".lower()
                                    if "jdownloader" not in marker:
                                        continue
                                    for value_name in ("DisplayIcon", "InstallLocation"):
                                        try:
                                            raw_val = str(winreg.QueryValueEx(sub_key, value_name)[0] or "")
                                        except Exception:
                                            continue
                                        resolved = _normalize_exe(raw_val)
                                        if resolved:
                                            return resolved
                            except Exception:
                                continue
                except Exception:
                    continue

        for root in (cwd, userprofile / "Downloads", userprofile / "Desktop"):
            try:
                if not root.is_dir():
                    continue
                patterns = ("JDownloader2*.exe", "JDownloader*.exe")
                for pat in patterns:
                    for candidate in root.glob(f"**/{pat}"):
                        try:
                            if not candidate.is_file():
                                continue
                            name = candidate.name.lower().strip()
                            if name not in {"jdownloader2.exe", "jdownloader.exe"}:
                                continue
                            if "setup" in name or "install" in name:
                                continue
                            return str(candidate)
                        except Exception:
                            continue
            except Exception:
                continue
        raise FileNotFoundError(
            "JDownloader executable not found. Set R0MM_JDOWNLOADER_BIN to JDownloader2.exe path."
        )

    @classmethod
    def _resolve_jdownloader_headless_cmd(cls, binary_path: str) -> List[str]:
        bin_path = Path(str(binary_path or "").strip())
        install_dir = bin_path.parent
        jar_path = install_dir / "JDownloader.jar"
        if not jar_path.is_file():
            return []

        java_candidates = []
        if os.name == "nt":
            java_candidates.extend(
                [
                    install_dir / "jre" / "bin" / "javaw.exe",
                    install_dir / "jre" / "bin" / "java.exe",
                ]
            )
        else:
            java_candidates.extend(
                [
                    install_dir / "jre" / "bin" / "java",
                ]
            )

        for name in ("javaw", "java"):
            resolved = shutil.which(name)
            if resolved:
                java_candidates.append(Path(resolved))

        java_bin = ""
        for candidate in java_candidates:
            try:
                if candidate and candidate.is_file():
                    java_bin = str(candidate)
                    break
            except Exception:
                continue

        if not java_bin:
            return []
        return [java_bin, "-Djava.awt.headless=true", "-jar", str(jar_path)]

    @staticmethod
    def _jdownloader_boot_timeout_s(raw_value: Any = None) -> float:
        if raw_value is None:
            raw = (os.getenv("R0MM_JDOWNLOADER_BOOT_TIMEOUT", "") or "").strip()
        else:
            raw = str(raw_value).strip()
        if not raw:
            return 30.0
        try:
            parsed = float(raw)
        except Exception:
            return 30.0
        if parsed < 6.0:
            return 6.0
        if parsed > 180.0:
            return 180.0
        return parsed

    @classmethod
    def _launch_jdownloader_background(cls, binary_path: str, *, mode_override: str = "") -> dict:
        exe = str(binary_path or "").strip()
        if not exe:
            raise RuntimeError("jdownloader binary path is empty")
        bin_path = Path(exe)
        if not bin_path.is_file():
            raise FileNotFoundError(f"jdownloader binary not found: {bin_path}")

        boot_mode_seed = (mode_override or os.getenv("R0MM_JDOWNLOADER_BOOT_MODE", "") or "gui").strip()
        boot_mode = cls._normalize_jdownloader_boot_mode(boot_mode_seed, default="gui")

        base_kwargs: Dict[str, Any] = {
            "cwd": str(bin_path.parent),
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "stdin": subprocess.DEVNULL,
        }
        kwargs_headless: Dict[str, Any] = dict(base_kwargs)
        kwargs_gui: Dict[str, Any] = dict(base_kwargs)
        if os.name == "nt":
            new_group_flag = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) or 0)
            detached_flag = int(getattr(subprocess, "DETACHED_PROCESS", 0) or 0)
            gui_flags = new_group_flag
            if gui_flags:
                kwargs_gui["creationflags"] = gui_flags
            headless_flags = new_group_flag | detached_flag
            if headless_flags:
                kwargs_headless["creationflags"] = headless_flags
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0) or 0)
            kwargs_headless["startupinfo"] = startup

        headless_cmd = cls._resolve_jdownloader_headless_cmd(str(bin_path))
        can_headless = len(headless_cmd) > 0
        if boot_mode in {"silent", "headless"} and not can_headless:
            raise RuntimeError(
                "headless bootstrap requested but headless runtime was not found "
                "(missing JDownloader.jar or Java runtime)"
            )

        if boot_mode in {"auto", "silent", "headless"} and can_headless:
            try:
                proc = subprocess.Popen(headless_cmd, **kwargs_headless)
                return {
                    "mode": "headless",
                    "command": " ".join(headless_cmd[:2] + ["-jar", "JDownloader.jar"]),
                    "pid": int(getattr(proc, "pid", 0) or 0),
                }
            except Exception as exc:
                if boot_mode in {"silent", "headless"}:
                    raise RuntimeError(f"failed to launch headless jdownloader: {exc}")
                monitor_action(f"[!] jdownloader:bootstrap:headless_fallback {exc}")

        proc = subprocess.Popen([str(bin_path)], **kwargs_gui)
        return {"mode": "gui", "command": str(bin_path), "pid": int(getattr(proc, "pid", 0) or 0)}

    @classmethod
    def _wait_jdownloader_endpoint(
        cls,
        check_hosts: List[str],
        port: int,
        timeout_s: float,
        *,
        poll_s: float = 0.40,
    ) -> Tuple[bool, str]:
        deadline = time.monotonic() + max(0.5, float(timeout_s))
        while time.monotonic() < deadline:
            for check_host in check_hosts:
                if cls._tcp_port_open(check_host, port):
                    return True, check_host
            time.sleep(max(0.10, float(poll_s)))
        return False, (check_hosts[0] if check_hosts else "127.0.0.1")

    @staticmethod
    def _terminate_pid(pid: int) -> bool:
        safe_pid = int(pid or 0)
        if safe_pid <= 0:
            return False
        try:
            os.kill(safe_pid, signal.SIGTERM)
            return True
        except Exception:
            pass
        if os.name == "nt":
            try:
                res = subprocess.run(
                    ["taskkill", "/PID", str(safe_pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    check=False,
                    timeout=4,
                )
                return int(getattr(res, "returncode", 1) or 1) == 0
            except Exception:
                return False
        return False

    @staticmethod
    def _kill_running_jdownloader_processes(install_dir: str = "") -> dict:
        if os.name != "nt":
            return {"success": False, "reason": "unsupported_os", "killed_pids": []}

        safe_dir = str(install_dir or "").strip().replace("\\", "/").lower().rstrip("/")
        script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$dir = $args[0]
$killed = New-Object System.Collections.Generic.List[string]
Get-CimInstance Win32_Process | ForEach-Object {
  $name = [string]$_.Name
  $exe = [string]$_.ExecutablePath
  $pid = [string]$_.ProcessId
  $match = $false
  if ($name -ieq 'JDownloader2.exe' -or $name -ieq 'JDownloader.exe') {
    $match = $true
  } elseif ($exe) {
    $normalized = $exe.Replace('\','/').ToLower()
    if ($dir -and $normalized.StartsWith($dir + '/')) {
      $match = $true
    }
  }
  if ($match) {
    try {
      Stop-Process -Id ([int]$pid) -Force -ErrorAction Stop
      [void]$killed.Add($pid)
    } catch {}
  }
}
if ($killed.Count -gt 0) { [string]::Join(',', $killed) }
"""
        try:
            out = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    script,
                    safe_dir,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                check=False,
                timeout=12,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
            raw = (out.stdout or "").strip()
            pids = [p.strip() for p in raw.split(",") if p.strip()]
            return {
                "success": int(getattr(out, "returncode", 1) or 1) == 0,
                "killed_pids": pids,
                "stderr": (out.stderr or "").strip(),
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "killed_pids": []}

    @classmethod
    def _bootstrap_jdownloader_for_endpoint(
        cls,
        endpoint_url: str,
        *,
        requested_mode: str = "",
        boot_timeout_s: Optional[float] = None,
        binary_path: str = "",
    ) -> dict:
        normalized = cls._normalize_jdownloader_flashgot_url(endpoint_url)
        parts = urlsplit(normalized)
        host = parts.hostname or "127.0.0.1"
        port = int(parts.port or 9666)
        if not cls._is_local_host(host):
            return {"attempted": False, "ready": False, "reason": "non-local-endpoint"}
        if cls._tcp_port_open(host, port):
            return {"attempted": False, "ready": True, "already_running": True}

        safe_binary_override = str(binary_path or "").strip().strip('"')
        if safe_binary_override:
            candidate = Path(safe_binary_override)
            try:
                if candidate.is_file():
                    bin_path = str(candidate)
                else:
                    return {
                        "attempted": True,
                        "ready": False,
                        "error": f"configured jdownloader binary not found: {safe_binary_override}",
                        "host": host,
                        "port": port,
                    }
            except Exception as exc:
                return {"attempted": True, "ready": False, "error": str(exc), "host": host, "port": port}
        else:
            try:
                bin_path = cls._resolve_jdownloader_binary()
            except Exception as exc:
                return {"attempted": True, "ready": False, "error": str(exc), "host": host, "port": port}

        check_hosts = [host]
        if host == "127.0.0.1":
            check_hosts.append("localhost")
            check_hosts.append("::1")
        elif host == "localhost":
            check_hosts.append("127.0.0.1")
            check_hosts.append("::1")
        elif host == "::1":
            check_hosts.append("localhost")
            check_hosts.append("127.0.0.1")
        if not requested_mode:
            requested_mode = (os.getenv("R0MM_JDOWNLOADER_BOOT_MODE", "") or "gui").strip()
        requested_mode = cls._normalize_jdownloader_boot_mode(requested_mode, default="gui")

        boot_timeout = cls._jdownloader_boot_timeout_s(boot_timeout_s)
        attempts: List[str] = []

        def _launch_and_wait(mode: str, wait_s: float) -> Tuple[bool, dict]:
            monitor_action(f"[?] jdownloader:bootstrap:start mode={mode} bin={bin_path}")
            launch_info = cls._launch_jdownloader_background(bin_path, mode_override=mode)
            launch_mode = str(launch_info.get("mode", "unknown"))
            launch_pid = int(launch_info.get("pid", 0) or 0)
            attempts.append(launch_mode)
            monitor_action(f"[*] jdownloader:bootstrap:mode {launch_mode}")
            ready, ready_host = cls._wait_jdownloader_endpoint(check_hosts, port, wait_s)
            if ready:
                monitor_action(f"[*] jdownloader:bootstrap:ready {ready_host}:{port}")
                return True, {
                    "attempted": True,
                    "ready": True,
                    "mode": launch_mode,
                    "binary": bin_path,
                    "host": ready_host,
                    "port": port,
                    "attempts": attempts,
                    "pid": launch_pid,
                    "boot_timeout_s": boot_timeout,
                }
            return False, {
                "attempted": True,
                "ready": False,
                "mode": launch_mode,
                "binary": bin_path,
                "host": host,
                "port": port,
                "attempts": attempts,
                "pid": launch_pid,
                "boot_timeout_s": boot_timeout,
            }

        primary_wait_s = boot_timeout
        if requested_mode == "auto":
            primary_wait_s = max(6.0, min(12.0, boot_timeout))

        try:
            primary_ok, primary_payload = _launch_and_wait(requested_mode, primary_wait_s)
            if primary_ok:
                return primary_payload
        except Exception as exc:
            return {
                "attempted": True,
                "ready": False,
                "error": f"failed to launch jdownloader: {exc}",
                "binary": bin_path,
                "host": host,
                "port": port,
                "attempts": attempts,
                "boot_timeout_s": boot_timeout,
            }

        primary_mode = str(primary_payload.get("mode", "unknown"))
        if requested_mode == "auto" and primary_mode == "headless":
            try:
                primary_pid = int(primary_payload.get("pid", 0) or 0)
                if primary_pid > 0:
                    stopped = cls._terminate_pid(primary_pid)
                    monitor_action(
                        f"[*] jdownloader:bootstrap:headless_stop pid={primary_pid} ok={1 if stopped else 0}"
                    )
                    if stopped:
                        time.sleep(0.25)
                monitor_action("[?] jdownloader:bootstrap:fallback gui_after_headless_timeout")
                fallback_ok, fallback_payload = _launch_and_wait("gui", max(12.0, boot_timeout))
                if fallback_ok:
                    fallback_payload["fallback"] = "headless_to_gui"
                    return fallback_payload
                return {
                    **fallback_payload,
                    "error": (
                        f"timeout waiting for jdownloader endpoint {host}:{port} "
                        "(headless->gui fallback exhausted)"
                    ),
                    "fallback": "headless_to_gui",
                }
            except Exception as exc:
                return {
                    "attempted": True,
                    "ready": False,
                    "binary": bin_path,
                    "host": host,
                    "port": port,
                    "attempts": attempts,
                    "fallback": "headless_to_gui",
                    "error": f"failed gui fallback after headless timeout: {exc}",
                    "boot_timeout_s": boot_timeout,
                }

        return {
            **primary_payload,
            "error": f"timeout waiting for jdownloader endpoint {host}:{port}",
        }

    def jdownloader_repair_local_api(
        self,
        *,
        endpoint: str = "",
        binary_path: str = "",
        requested_mode: str = "gui",
        boot_timeout_s: float = 18.0,
        enable_deprecated_api: bool = True,
        force_restart_on_change: bool = False,
    ) -> dict:
        endpoint_seed = (endpoint or self._jdownloader_endpoint()).strip()
        normalized = self._normalize_jdownloader_flashgot_url(endpoint_seed)
        cfg_path = self._jdownloader_remote_api_config_path(binary_path=binary_path)
        if not cfg_path:
            return {
                "success": False,
                "error": "JDownloader RemoteAPIConfig path was not found.",
                "endpoint": normalized,
            }

        cfg_file = Path(cfg_path)
        payload: Dict[str, Any] = {}
        if cfg_file.is_file():
            try:
                payload = json.loads(cfg_file.read_text(encoding="utf-8", errors="ignore") or "{}")
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}

        targets: Dict[str, Any] = {
            "externinterfaceenabled": True,
            "externinterfacelocalhostonly": True,
        }
        if enable_deprecated_api:
            targets["deprecatedapienabled"] = True

        changes: Dict[str, Dict[str, Any]] = {}
        for key, value in targets.items():
            old = payload.get(key)
            if old == value:
                continue
            payload[key] = value
            changes[key] = {"old": old, "new": value}

        write_error = ""
        if changes or not cfg_file.is_file():
            try:
                cfg_file.parent.mkdir(parents=True, exist_ok=True)
                cfg_file.write_text(
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                    errors="ignore",
                )
            except Exception as exc:
                write_error = str(exc)

        boot_mode = self._normalize_jdownloader_boot_mode(requested_mode, default="gui")
        safe_bin = str(binary_path or "").strip()
        if not safe_bin:
            try:
                safe_bin = self._resolve_jdownloader_binary()
            except Exception:
                safe_bin = ""

        bootstrap = self._bootstrap_jdownloader_for_endpoint(
            normalized,
            requested_mode=boot_mode,
            boot_timeout_s=self._jdownloader_boot_timeout_s(boot_timeout_s),
            binary_path=safe_bin,
        )
        ready = bool(bootstrap.get("ready"))
        restart_required = bool(changes) and not ready
        restarted = False
        restart_info: Dict[str, Any] = {}

        if force_restart_on_change and (restart_required or (not ready and bool(changes))):
            install_dir = str(Path(safe_bin).parent) if safe_bin else ""
            restart_info = self._kill_running_jdownloader_processes(install_dir=install_dir)
            restarted = bool((restart_info.get("killed_pids") or []))
            if restarted:
                time.sleep(0.6)
                bootstrap = self._bootstrap_jdownloader_for_endpoint(
                    normalized,
                    requested_mode=boot_mode,
                    boot_timeout_s=self._jdownloader_boot_timeout_s(boot_timeout_s),
                    binary_path=safe_bin,
                )
                ready = bool(bootstrap.get("ready"))
                restart_required = bool(changes) and not ready

        out = {
            "success": write_error == "",
            "ready": ready,
            "endpoint": normalized,
            "config_path": str(cfg_file),
            "changed": bool(changes),
            "changes": changes,
            "restart_required": restart_required,
            "restarted": restarted,
            "restart_info": restart_info,
            "bootstrap": bootstrap,
        }
        if write_error:
            out["error"] = f"failed to write RemoteAPIConfig: {write_error}"
        return out

    def jdownloader_queue_downloads(
        self,
        targets: List[dict],
        *,
        autostart: bool = True,
        package_name: str = "R0MM Hydra Queue",
        endpoint: str = "",
        jd_options: Optional[Dict[str, Any]] = None,
        phase_callback=None,
    ) -> dict:
        """
        Send links to local JDownloader using the Extern/Flashgot API.
        Reference: http://127.0.0.1:9666/flashgot
        """
        def _emit_phase(phase: str, percent: int) -> None:
            callback = phase_callback
            if not callable(callback):
                return
            try:
                callback(str(phase or "").strip(), max(0, min(100, int(percent or 0))))
            except Exception:
                return

        _emit_phase("prepare", 2)
        if not targets:
            _emit_phase("error", 100)
            return {"error": "targets required"}

        options = dict(jd_options) if isinstance(jd_options, dict) else {}
        endpoint_opt = str(options.get("endpoint", "") or "").strip()
        binary_path_opt = str(options.get("binary_path", "") or "").strip()
        endpoint_seed = (endpoint or endpoint_opt or self._jdownloader_endpoint()).strip()
        boot_mode = self._normalize_jdownloader_boot_mode(str(options.get("boot_mode", "") or "").strip(), default="gui")
        tune_profile = self._normalize_jdownloader_tune_profile(
            str(options.get("tune_profile", "") or "").strip(),
            default="balanced",
        )
        tune_enabled = self._coerce_optional_bool(options.get("tune_enabled"))
        boot_timeout_s = self._jdownloader_boot_timeout_s(options.get("boot_timeout_s"))
        runtime_opts = {
            "boot_mode": boot_mode,
            "boot_timeout_s": boot_timeout_s,
            "tune_enabled": True if tune_enabled is None else bool(tune_enabled),
            "tune_profile": tune_profile,
            "binary_override": bool(binary_path_opt),
        }
        candidate_urls = self._jdownloader_endpoint_candidates(endpoint_seed)
        flashgot_url = candidate_urls[0] if candidate_urls else self._normalize_jdownloader_flashgot_url(endpoint_seed)
        tune = self._jdownloader_apply_perf_tuning(enabled=tune_enabled, profile=tune_profile)
        if tune.get("applied") and tune.get("changed"):
            try:
                changed_keys = ",".join(sorted((tune.get("changes") or {}).keys()))
            except Exception:
                changed_keys = ""
            monitor_action(
                f"[*] jdownloader:tune profile={tune.get('profile','balanced')} keys={changed_keys}"
            )
        _emit_phase("bootstrap", 20)
        bootstrap = self._bootstrap_jdownloader_for_endpoint(
            flashgot_url,
            requested_mode=boot_mode,
            boot_timeout_s=boot_timeout_s,
            binary_path=binary_path_opt,
        )
        _emit_phase("collect_targets", 45)
        accepted: List[dict] = []
        errors: List[dict] = []
        url_lines: List[str] = []
        desc_lines: List[str] = []
        parent_dirs: List[str] = []

        for target in targets:
            if not isinstance(target, dict):
                errors.append({"target": target, "error": "invalid target"})
                continue
            raw_url = str(target.get("url", "") or "").strip()
            raw_dest = str(target.get("dest_path", "") or "").strip()
            if not raw_url or not raw_dest:
                errors.append({"url": raw_url, "dest_path": raw_dest, "error": "url and dest_path are required"})
                continue
            filename = Path(raw_dest).name or Path(urlsplit(raw_url).path).name or "download.bin"
            accepted.append({"url": raw_url, "dest_path": raw_dest, "filename": filename})
            url_lines.append(raw_url)
            desc_lines.append(filename)
            parent_dirs.append(str(Path(raw_dest).parent))

        if not accepted:
            _emit_phase("error", 100)
            return {"error": "no valid targets", "errors": errors}

        common_dir = ""
        try:
            if parent_dirs:
                common_dir = os.path.commonpath(parent_dirs)
        except Exception:
            common_dir = parent_dirs[0] if parent_dirs else ""

        payload = {
            "urls": "\n".join(url_lines),
            # flashgot API expects the same number/order as urls
            "description": "\n".join(desc_lines),
            "autostart": "1" if autostart else "0",
            "package": (package_name or "R0MM Hydra Queue").strip(),
            "source": "R0MM",
            "referer": "https://myrient.erista.me/",
        }
        if common_dir:
            payload["dir"] = common_dir

        monitor_action(
            f"[*] jdownloader:flashgot:start count={len(accepted)} autostart={1 if autostart else 0}"
        )
        _emit_phase("enqueue", 70)
        data = urlencode(payload).encode("utf-8", errors="ignore")
        body = ""
        status_code = 0
        request_error: str = ""
        attempts: List[str] = []
        used_endpoint = flashgot_url
        repair_result: Dict[str, Any] = {}

        for candidate in candidate_urls or [flashgot_url]:
            used_endpoint = candidate
            req = urllib.request.Request(
                candidate,
                data=data,
                headers={
                    "User-Agent": "R0MM/2 JDownloaderBridge (+local desktop app)",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "*/*",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=4) as resp:
                    body = resp.read(4096).decode("utf-8", errors="ignore").strip()
                    status_code = int(getattr(resp, "status", 200) or 200)
                if status_code < 400:
                    break
                request_error = f"HTTP {status_code}"
                attempts.append(f"{candidate} -> HTTP {status_code}")
            except urllib.error.URLError as exc:
                reason = getattr(exc, "reason", exc)
                request_error = str(reason)
                attempts.append(f"{candidate} -> {reason}")
                continue
            except Exception as exc:
                request_error = str(exc)
                attempts.append(f"{candidate} -> {exc}")
                continue

        flashgot_url = used_endpoint

        if status_code <= 0:
            _emit_phase("repair", 82)
            try:
                repair_result = self.jdownloader_repair_local_api(
                    endpoint=endpoint_seed,
                    binary_path=binary_path_opt,
                    requested_mode="gui",
                    boot_timeout_s=boot_timeout_s,
                    enable_deprecated_api=True,
                    force_restart_on_change=True,
                )
            except Exception as exc:
                repair_result = {"success": False, "error": str(exc)}

            if bool(repair_result.get("ready")):
                monitor_action("[*] jdownloader:repair:auto_retry")
                _emit_phase("retry", 90)
                body = ""
                status_code = 0
                request_error = ""
                attempts.append("[repair] applied; retrying flashgot post")
                for candidate in candidate_urls or [flashgot_url]:
                    used_endpoint = candidate
                    req = urllib.request.Request(
                        candidate,
                        data=data,
                        headers={
                            "User-Agent": "R0MM/2 JDownloaderBridge (+local desktop app)",
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Accept": "*/*",
                        },
                        method="POST",
                    )
                    try:
                        with urllib.request.urlopen(req, timeout=4) as resp:
                            body = resp.read(4096).decode("utf-8", errors="ignore").strip()
                            status_code = int(getattr(resp, "status", 200) or 200)
                        if status_code < 400:
                            break
                        request_error = f"HTTP {status_code}"
                        attempts.append(f"{candidate} -> HTTP {status_code}")
                    except urllib.error.URLError as exc:
                        reason = getattr(exc, "reason", exc)
                        request_error = str(reason)
                        attempts.append(f"{candidate} -> {reason}")
                        continue
                    except Exception as exc:
                        request_error = str(exc)
                        attempts.append(f"{candidate} -> {exc}")
                        continue
                flashgot_url = used_endpoint

        # JDownloader may respond with informational text; consider HTTP success as queued.
        if status_code >= 400:
            hint = self._jdownloader_endpoint_hint(endpoint_seed)
            monitor_action(f"[!] jdownloader:flashgot:error HTTP {status_code}")
            _emit_phase("error", 100)
            return {
                "error": f"jdownloader returned HTTP {status_code}. {hint}",
                "endpoint": flashgot_url,
                "queued": 0,
                "accepted": [],
                "errors": errors,
                "backend": "jdownloader",
                "response": body,
                "hint": hint,
                "attempts": attempts,
                "tune": tune,
                "runtime": runtime_opts,
                "repair": repair_result,
            }
        if status_code <= 0:
            hint = self._jdownloader_endpoint_hint(endpoint_seed)
            reason = request_error or "endpoint unavailable"
            if bootstrap.get("attempted") and bootstrap.get("error"):
                reason = f"{reason}; bootstrap: {bootstrap.get('error')}"
            if repair_result.get("error"):
                reason = f"{reason}; repair: {repair_result.get('error')}"
            if repair_result.get("restart_required"):
                reason = f"{reason}; repair: restart JDownloader required"
            if bootstrap.get("attempted") and not bootstrap.get("ready"):
                launch_mode = str(bootstrap.get("mode", "") or "").strip().lower()
                launch_pid = int(bootstrap.get("pid", 0) or 0)
                if launch_mode == "gui" and launch_pid > 0:
                    reason = f"{reason}; launcher started (mode=gui pid={launch_pid})"
            if bootstrap.get("ready") and "timed out" in reason.lower():
                reason = (
                    f"{reason}; local port answered but /flashgot did not respond "
                    "(possible wrong service on port or Extern/FlashGot disabled)"
                )
            monitor_action(f"[!] jdownloader:flashgot:error {reason}")
            _emit_phase("error", 100)
            return {
                "error": f"jdownloader endpoint unreachable: {reason}. {hint}",
                "endpoint": flashgot_url,
                "queued": 0,
                "accepted": [],
                "errors": errors,
                "backend": "jdownloader",
                "hint": hint,
                "attempts": attempts,
                "bootstrap": bootstrap,
                "tune": tune,
                "runtime": runtime_opts,
                "repair": repair_result,
            }
        monitor_action(
            f"[*] jdownloader:flashgot:done count={len(accepted)} endpoint={flashgot_url}"
        )
        _emit_phase("done", 100)

        return {
            "success": len(accepted) > 0,
            "queued": len(accepted),
            "accepted": accepted,
            "errors": errors,
            "backend": "jdownloader",
            "endpoint": flashgot_url,
            "response": body,
            "autostart": bool(autostart),
            "package": payload["package"],
            "dir": common_dir,
            "tune": tune,
            "runtime": runtime_opts,
            "repair": repair_result,
        }

    def myrient_check_remote_file(self, url: str, local_path: str) -> dict:
        if not url or not local_path:
            return {"error": "url and local_path are required"}
        return self._myrient_fetcher.check_remote_file(url, local_path)

    def myrient_queue_download(
        self,
        url: str,
        dest_path: str,
        progress_callback: Optional[Callable[[str, float, str, str], None]] = None,
    ) -> dict:
        if not url or not dest_path:
            return {"error": "url and dest_path are required"}
        try:
            future = self._myrient_fetcher.submit_download(url, dest_path, progress_callback=progress_callback)
            return {"success": True, "queued": True, "future": future}
        except Exception as exc:
            return {"error": str(exc)}

    def myrient_queue_downloads(
        self,
        targets: List[dict],
        progress_callback: Optional[Callable[[str, float, str, str], None]] = None,
    ) -> dict:
        if not targets:
            return {"error": "targets required"}
        try:
            rclone_path = self._myrient_fetcher._resolve_rclone_binary()
        except Exception as exc:
            return {"error": str(exc)}
        queued = 0
        errors: List[dict] = []
        for target in targets:
            if not isinstance(target, dict):
                errors.append({"target": target, "error": "invalid target"})
                continue
            url = str(target.get("url", "") or "").strip()
            dest = str(target.get("dest_path", "") or "").strip()
            res = self.myrient_queue_download(url, dest, progress_callback=progress_callback)
            if res.get("error"):
                errors.append({"url": url, "dest_path": dest, "error": res["error"]})
            else:
                queued += 1
        return {"success": queued > 0 and not errors, "queued": queued, "errors": errors, "backend": "rclone", "rclone": rclone_path}

    def myrient_catalog_presets(self) -> dict:
        """
        Built-in Myrient roots so the UI can work out-of-the-box without requiring
        the user to manually type a base URL.
        """
        presets = [
            {
                "id": "myrient_files",
                "label": "Myrient /files/",
                "root_url": "https://myrient.erista.me/files",
            },
            {
                "id": "myrient_root",
                "label": "Myrient root",
                "root_url": "https://myrient.erista.me/",
            },
            {
                "id": "myrient_no_intro",
                "label": "Myrient No-Intro",
                "root_url": "https://myrient.erista.me/files/No-Intro/",
            },
            {
                "id": "myrient_redump",
                "label": "Myrient Redump",
                "root_url": "https://myrient.erista.me/files/Redump/",
            },
        ]
        return {"success": True, "default_id": "myrient_files", "presets": presets}

    def myrient_list_directory(self, base_url: str) -> dict:
        """Fetch and parse a Myrient-style directory listing page (HTML index)."""
        base = (base_url or "").strip()
        if not base:
            return {"error": "base_url required"}
        if not base.endswith("/"):
            base += "/"

        req = urllib.request.Request(
            base,
            headers={
                "User-Agent": "R0MM/2 MyrientDirectoryBrowser (+local desktop app)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.1",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read(2 * 1024 * 1024)
        except Exception as exc:
            return {"error": str(exc), "base_url": base}

        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            text = str(raw)
        text = html_lib.unescape(text)

        entries: List[dict] = []
        seen = set()
        anchor_matches = re.findall(
            r"""<a\b[^>]*href\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s>]+))[^>]*>(.*?)</a>""",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if anchor_matches:
            link_rows = []
            for g1, g2, g3, anchor_text in anchor_matches:
                href = (g1 or g2 or g3 or "").strip()
                label = re.sub(r"<[^>]+>", "", anchor_text or "").strip()
                link_rows.append((href, label))
        else:
            hrefs = re.findall(r"""href\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s>]+))""", text, flags=re.IGNORECASE)
            link_rows = [((a or b or c or "").strip(), "") for a, b, c in hrefs]

        for href, label in link_rows:
            href = (href or "").strip()
            if not href or href.startswith("#") or href.startswith("?"):
                continue
            if href in {"./"}:
                continue
            full_url = urljoin(base, href)
            full_url = MyrientFetcher._canonicalize_myrient_url(full_url)
            parsed = urlsplit(full_url)
            name = unquote(Path(parsed.path.rstrip("/")).name)
            if href == "../":
                name = ".."
            if not name:
                label_name = (label or "").strip().rstrip("/")
                if label_name:
                    name = label_name
            if not name:
                continue
            label_clean = (label or "").strip()
            is_dir = href.endswith("/") or label_clean.endswith("/")
            key = (os.path.normcase(name), bool(is_dir))
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                {
                    "name": name,
                    "url": full_url if href != "../" else full_url,
                    "href": href,
                    "is_dir": is_dir,
                }
            )

        # Keep parent and directories first, then files.
        entries.sort(key=lambda e: (0 if e.get("name") == ".." else 1, 0 if e.get("is_dir") else 1, str(e.get("name", "")).lower()))
        return {"success": True, "base_url": base, "entries": entries, "count": len(entries)}

    def myrient_resolve_links_from_missing(self, base_url: str, missing_items: List[dict]) -> dict:
        """
        Resolve direct file links from a Myrient directory listing for missing ROM rows.
        Performs a single GET on the listing page and matches by filename/stem heuristics.
        """
        listing = self.myrient_list_directory(base_url)
        if listing.get("error"):
            return {"error": listing.get("error"), "base_url": (base_url or "").strip()}
        if not missing_items:
            return {"error": "missing_items required"}
        base = str(listing.get("base_url", "") or "").strip()
        files: List[dict] = [
            {
                "href": str(entry.get("href", "")),
                "url": str(entry.get("url", "")),
                "name": str(entry.get("name", "")),
            }
            for entry in list(listing.get("entries", []) or [])
            if isinstance(entry, dict) and not bool(entry.get("is_dir")) and str(entry.get("name", "")) != ".."
        ]

        def _norm_name(value: str) -> str:
            safe = (value or "").strip()
            if not safe:
                return ""
            safe = unquote(safe)
            safe = Path(safe).stem if Path(safe).suffix else safe
            safe = safe.lower()
            # Remove common punctuation differences while keeping alnum content.
            safe = re.sub(r"[_\-.]+", " ", safe)
            safe = re.sub(r"[^a-z0-9]+", " ", safe)
            return " ".join(safe.split())

        file_by_exact_lower = {f["name"].lower(): f for f in files}
        file_groups_by_norm: Dict[str, List[dict]] = {}
        for f in files:
            key = _norm_name(f["name"])
            if not key:
                continue
            file_groups_by_norm.setdefault(key, []).append(f)

        matches: List[dict] = []
        unmatched: List[dict] = []
        ambiguous: List[dict] = []

        for raw_item in missing_items:
            if not isinstance(raw_item, dict):
                continue
            rom_name = str(raw_item.get("rom_name", "") or "").strip()
            game_name = str(raw_item.get("game_name", "") or "").strip()
            system = str(raw_item.get("system", "") or "").strip()
            candidates = [c for c in [rom_name, game_name] if c]

            chosen: Optional[dict] = None
            candidate_matches: List[dict] = []

            # 1) Exact filename match (full name with extension)
            for c in candidates:
                exact = file_by_exact_lower.get(c.lower())
                if exact is not None:
                    chosen = exact
                    break
            # 2) Exact normalized stem match
            if chosen is None:
                for c in candidates:
                    norm = _norm_name(c)
                    if not norm:
                        continue
                    group = file_groups_by_norm.get(norm, [])
                    if len(group) == 1:
                        chosen = group[0]
                        break
                    if len(group) > 1:
                        candidate_matches = group
                        break
            # 3) Prefix/contains heuristics, choose unique shortest candidate
            if chosen is None and not candidate_matches:
                for c in candidates:
                    norm = _norm_name(c)
                    if not norm:
                        continue
                    hits = [f for key, group in file_groups_by_norm.items() for f in group if key.startswith(norm) or norm in key]
                    # dedupe by name
                    dedup: Dict[str, dict] = {h["name"]: h for h in hits}
                    hits = list(dedup.values())
                    if len(hits) == 1:
                        chosen = hits[0]
                        break
                    if len(hits) > 1:
                        candidate_matches = sorted(hits, key=lambda item: len(item.get("name", "")))
                        break

            payload_item = {
                "rom_name": rom_name,
                "game_name": game_name,
                "system": system,
                "region": raw_item.get("region"),
                "crc32": raw_item.get("crc32"),
            }
            if chosen is not None:
                matches.append(
                    {
                        **payload_item,
                        "filename": chosen["name"],
                        "url": chosen["url"],
                    }
                )
            elif candidate_matches:
                ambiguous.append(
                    {
                        **payload_item,
                        "candidates": [m.get("name", "") for m in candidate_matches[:8]],
                    }
                )
            else:
                unmatched.append(payload_item)

        return {
            "success": True,
            "base_url": base,
            "listing_count": len(files),
            "requested": len([i for i in missing_items if isinstance(i, dict)]),
            "matches": matches,
            "unmatched": unmatched,
            "ambiguous": ambiguous,
        }

    def halt_traffic(self) -> dict:
        old_fetcher = self._myrient_fetcher
        try:
            res = old_fetcher.halt()
        finally:
            # New fetcher instance lets future queues proceed after a halt without inheriting the cancel flag.
            self._myrient_fetcher = MyrientFetcher()
        return res

    # Organization
    def preview_organize(self, output: str, strategy: str, action: str) -> dict:
        if not output:
            return {"error": "output required"}
        plan = self.organizer.preview(self.identified, output, strategy, action)
        return {
            "actions": [
                {"action": a.action_type, "source": a.source, "destination": a.destination}
                for a in plan.actions
            ],
            "total_files": plan.total_files,
            "total_size": plan.total_size,
            "total_size_formatted": format_size(plan.total_size),
        }

    def organize(
        self, output: str, strategy: str, action: str, progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> dict:
        if not output:
            return {"error": "output required"}

        def _progress(current: int, total: int, filename: str = "") -> None:
            if progress_callback:
                progress_callback(current, total, filename)

        actions = self.organizer.organize(self.identified, output, strategy, action, progress_callback=_progress)
        return {"success": True, "actions": [a.to_dict() for a in actions]}

    def organize_unidentified(
        self, output: str, action: str, progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> dict:
        if not output:
            return {"error": "output required"}

        import os
        quarantine_dir = os.path.join(output, "_Quarantine_")

        def _progress(current: int, total: int, filename: str = "") -> None:
            if progress_callback:
                progress_callback(current, total, filename)

        actions = self.organizer.organize(self.unidentified, quarantine_dir, "flat", action, progress_callback=_progress)
        return {"success": True, "actions": [a.to_dict() for a in actions]}

    def undo(self) -> dict:
        ok = self.organizer.undo_last()
        if not ok:
            return {"error": "nothing to undo"}
        return {"success": True}

    # Collections
    def save_collection(self, name: str) -> dict:
        if not name:
            return {"error": "name required"}
        collection = Collection(
            name=name,
            dat_infos=self.multi_matcher.get_dat_list(),
            identified=[s.to_dict() for s in self.identified],
            unidentified=[s.to_dict() for s in self.unidentified],
            settings=self.settings,
        )
        path = self.collection_manager.save(collection)
        return {"success": True, "filepath": path}

    def load_collection(self, filepath: str) -> dict:
        if not filepath or not os.path.exists(filepath):
            return {"error": "collection not found"}
        col = self.collection_manager.load(filepath)
        self.multi_matcher = MultiROMMatcher()
        for dat in col.dat_infos:
            if dat.filepath and os.path.exists(dat.filepath):
                try:
                    dat_info, roms = DATParser.parse_with_info(dat.filepath)
                    dat_info.id = dat.id or dat_info.id
                    self.multi_matcher.add_dat(dat_info, roms)
                except Exception:
                    continue
        self.identified = [ScannedFile.from_dict(s) for s in col.identified]
        self.unidentified = [ScannedFile.from_dict(s) for s in col.unidentified]
        return {"success": True, "collection": col.to_dict()}

    def list_collections(self) -> dict:
        return {"collections": self.collection_manager.list_saved()}

    def list_recent_collections(self) -> dict:
        return {"recent": self.collection_manager.get_recent()}

    # DAT Library
    def dat_library_list(self) -> dict:
        dats = self.dat_library.list_dats()
        return {"dats": [d.to_dict() for d in dats]}

    def dat_library_import(self, filepath: str) -> dict:
        if not filepath or not os.path.exists(filepath):
            return {"error": "File not found"}
        try:
            info = self.dat_library.import_dat(filepath)
            return {"success": True, "dat": info.to_dict()}
        except Exception as exc:
            return {"error": str(exc)}

    def dat_library_load(self, dat_id: str) -> dict:
        try:
            info = self.dat_library.get_dat_info(dat_id)
            if not info or not info.filepath:
                return {"error": "DAT not found in library"}
            if not bool(getattr(info, "is_valid", True)):
                return {"error": f"Invalid DAT: {getattr(info, 'parse_error', '') or 'parse failed'}"}
            _, roms = DATParser.parse(info.filepath)
            self.multi_matcher.add_dat(info, roms)
            self._rematch_all()
            return {"success": True, "dat": info.to_dict()}
        except Exception as exc:
            return {"error": str(exc)}

    def dat_library_remove(self, dat_id: str) -> dict:
        try:
            removed = bool(self.dat_library.remove_dat(dat_id))
            if not removed:
                return {"error": "DAT not found in library"}
            was_active = dat_id in self.multi_matcher.dat_infos
            if was_active:
                self.multi_matcher.remove_dat(dat_id)
                self._rematch_all()
            return {"success": True, "removed_active": was_active}
        except Exception as exc:
            return {"error": str(exc)}

    # DAT Sources / Downloader
    def dat_sources(self) -> dict:
        return {"sources": self.dat_source_manager.get_sources()}

    @staticmethod
    def _resolve_unique_path(path: Path) -> Path:
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        idx = 1
        while True:
            candidate = parent / f"{stem}-{idx}{suffix}"
            if not candidate.exists():
                return candidate
            idx += 1

    def _detect_dat_family(
        self,
        filepath: str,
        *,
        filename_hint: str = "",
        url_hint: str = "",
        family_hint: str = "",
    ) -> str:
        family = self.dat_source_manager.recognize_family(
            filename_hint or Path(str(filepath or "")).name,
            url=url_hint,
            family_hint=family_hint,
        )
        if family != "Unknown":
            return family
        try:
            header, _roms = DATParser.parse(filepath)
            family = self.dat_source_manager.recognize_family(
                filename_hint or Path(str(filepath or "")).name,
                url=url_hint,
                header_name=str(header.get("name", "") or ""),
                header_description=str(header.get("description", "") or ""),
                family_hint=family_hint,
            )
        except Exception:
            family = self.dat_source_manager.recognize_family(
                filename_hint or Path(str(filepath or "")).name,
                url=url_hint,
                family_hint=family_hint,
            )
        return family

    def dat_downloader_catalog(
        self,
        family: str = "",
        limit_per_family: int = 5000,
        force_refresh: bool = False,
    ) -> dict:
        try:
            result = self.dat_source_manager.list_download_catalog(
                family=str(family or "").strip().lower(),
                limit_per_family=max(100, int(limit_per_family or 5000)),
                force_refresh=bool(force_refresh),
            )
            if not isinstance(result, dict):
                return {"items": [], "error": "invalid catalog response"}
            return result
        except Exception as exc:
            return {"items": [], "error": str(exc)}

    def dat_downloader_find_and_download(
        self,
        query: str,
        family: str = "",
        output_dir: str = "",
        auto_import: bool = True,
    ) -> dict:
        safe_query = str(query or "").strip()
        if not safe_query:
            return {"error": "query required"}

        if safe_query.lower().startswith(("http://", "https://")):
            payload = self.dat_downloader_download(
                safe_query,
                family=str(family or "").strip().lower(),
                output_dir=output_dir,
                auto_import=auto_import,
            )
            payload["resolved_via"] = "direct_url"
            payload["query"] = safe_query
            return payload

        found = self.dat_source_manager.find_best_match(
            safe_query,
            family=str(family or "").strip().lower(),
            limit_per_family=5000,
        )
        match = found.get("match")
        if not isinstance(match, dict):
            err = str(found.get("error", "") or "no match found")
            return {"error": err, "query": safe_query, "alternatives": list(found.get("alternatives", []) or [])}

        url = str(match.get("url", "") or "").strip()
        if not url:
            return {"error": "matched entry has no url", "query": safe_query}

        payload = self.dat_downloader_download(
            url,
            family=str(match.get("family_id", "") or family).strip().lower(),
            output_dir=output_dir,
            auto_import=auto_import,
        )
        payload["resolved_via"] = "catalog_match"
        payload["query"] = safe_query
        payload["match"] = dict(match)
        payload["alternatives"] = list(found.get("alternatives", []) or [])
        payload["total_candidates"] = int(found.get("total_candidates", 0) or 0)
        if found.get("catalog_error"):
            payload["catalog_error"] = str(found.get("catalog_error", "") or "")
        return payload

    def dat_downloader_download(
        self,
        url: str,
        family: str = "",
        output_dir: str = "",
        auto_import: bool = True,
        auto_load: bool = True,
    ) -> dict:
        safe_url = str(url or "").strip()
        if not safe_url:
            return {"error": "url required"}

        root_dir = Path(output_dir) if output_dir else Path(DATS_DIR) / "_downloads"
        try:
            root_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return {"error": f"failed to prepare output dir: {exc}"}

        filename = self.dat_source_manager.suggest_filename(safe_url, fallback="download.dat")
        if not filename:
            filename = "download.dat"
        suffix = Path(filename).suffix.lower()
        if suffix not in {".dat", ".xml", ".zip", ".gz", ".7z"}:
            filename = f"{filename}.dat"

        dest_path = self._resolve_unique_path(root_dir / filename)
        tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")

        req = urllib.request.Request(
            safe_url,
            headers={"User-Agent": "R0MM/2 DATDownloader (+local desktop app)"},
            method="GET",
        )

        byte_count = 0
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                with open(tmp_path, "wb") as handle:
                    while True:
                        chunk = resp.read(1024 * 512)
                        if not chunk:
                            break
                        handle.write(chunk)
                        byte_count += len(chunk)
            tmp_path.replace(dest_path)
        except Exception as exc:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            return {"error": str(exc), "url": safe_url}

        family_name = self._detect_dat_family(
            str(dest_path),
            filename_hint=filename,
            url_hint=safe_url,
            family_hint=family,
        )
        payload: Dict[str, Any] = {
            "success": True,
            "url": safe_url,
            "filepath": str(dest_path),
            "filename": dest_path.name,
            "bytes": int(byte_count),
            "family": family_name,
            "auto_import": bool(auto_import),
        }

        if auto_import:
            imported = self.dat_library_import(str(dest_path))
            if imported.get("error"):
                payload["imported"] = False
                payload["import_error"] = str(imported.get("error", "") or "")
            else:
                payload["imported"] = True
                payload["dat"] = dict(imported.get("dat", {}) or {})
                payload["dat_family"] = family_name
                if bool(auto_load):
                    dat_id = str(payload["dat"].get("id", "") or "").strip()
                    if dat_id:
                        loaded = self.dat_library_load(dat_id)
                        if loaded.get("error"):
                            payload["loaded"] = False
                            payload["load_error"] = str(loaded.get("error", "") or "")
                        else:
                            payload["loaded"] = True
                            self.persist_session()

        return payload

    def dat_sources_libretro(self) -> dict:
        result = self.dat_source_manager.list_family_dats("nointro", limit=2000)
        return {"dats": list(result.get("items", []) or []), "error": str(result.get("error", "") or "")}

    # Reports
    def export_report(self, format_name: str, filepath: str) -> dict:
        if not filepath:
            return {"error": "filepath required"}
        report = self.reporter.generate_multi_report(
            self.multi_matcher.dat_infos, self.multi_matcher.all_roms, self.identified
        )
        try:
            if format_name == "txt":
                self.reporter.export_txt(report, filepath)
            elif format_name == "csv":
                self.reporter.export_csv(report, filepath)
            else:
                self.reporter.export_json(report, filepath)
            return {"success": True, "filepath": filepath}
        except Exception as exc:
            return {"error": str(exc)}

    # Tools (API + implementation)
    @staticmethod
    def _hash_file(path: str, algo: str = "md5", chunk_size: int = 1024 * 1024) -> str:
        h = hashlib.new(algo)
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _crc32_file(path: str, chunk_size: int = 1024 * 1024) -> str:
        import zlib

        crc = 0
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                crc = zlib.crc32(chunk, crc)
        return f"{crc & 0xFFFFFFFF:08x}"

    @staticmethod
    def _tool_available(name: str) -> bool:
        return shutil.which(name) is not None

    def compare_dats(self, dat_path_a: str, dat_path_b: str) -> dict:
        if not dat_path_a or not dat_path_b:
            return {"error": "dat_path_a and dat_path_b are required"}
        if not os.path.exists(dat_path_a) or not os.path.exists(dat_path_b):
            return {"error": "DAT files not found"}

        _, roms_a = DATParser.parse(dat_path_a)
        _, roms_b = DATParser.parse(dat_path_b)

        def _key(rom: ROMInfo) -> Tuple[str, int, str, str, str]:
            return (rom.name, rom.size, rom.crc32 or "", rom.md5 or "", rom.sha1 or "")

        set_a = {_key(r) for r in roms_a}
        set_b = {_key(r) for r in roms_b}

        added = set_b - set_a
        removed = set_a - set_b

        names_a = {r.name for r in roms_a}
        names_b = {r.name for r in roms_b}
        common_names = names_a & names_b
        modified = 0
        for name in common_names:
            a_keys = {k for k in set_a if k[0] == name}
            b_keys = {k for k in set_b if k[0] == name}
            if a_keys != b_keys:
                modified += 1

        return {
            "success": True,
            "stats": {
                "added": len(added),
                "removed": len(removed),
                "modified": modified,
            },
        }

    def merge_dats(self, dat_paths: list[str], output_path: str, strategy: str = "strict") -> dict:
        if not dat_paths or not output_path:
            return {"error": "dat_paths and output_path are required"}

        all_roms: Dict[str, List[ROMInfo]] = {}
        seen_keys: set[Tuple[str, int, str, str, str]] = set()
        conflicts = 0

        for path in dat_paths:
            if not os.path.exists(path):
                return {"error": f"DAT not found: {path}"}
            _, roms = DATParser.parse(path)
            for rom in roms:
                key = (rom.name, rom.size, rom.crc32 or "", rom.md5 or "", rom.sha1 or "")
                if key in seen_keys:
                    continue
                if rom.name in all_roms:
                    for existing in all_roms[rom.name]:
                        existing_key = (
                            existing.name,
                            existing.size,
                            existing.crc32 or "",
                            existing.md5 or "",
                            existing.sha1 or "",
                        )
                        if existing.name == rom.name and existing_key != key:
                            conflicts += 1
                            if strategy == "prefer_first":
                                break
                    else:
                        all_roms.setdefault(rom.game_name or rom.name, []).append(rom)
                        seen_keys.add(key)
                        continue
                    if strategy == "prefer_latest":
                        all_roms.setdefault(rom.game_name or rom.name, []).append(rom)
                        seen_keys.add(key)
                    continue
                all_roms.setdefault(rom.game_name or rom.name, []).append(rom)
                seen_keys.add(key)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        import xml.etree.ElementTree as ET

        root = ET.Element("datafile")
        header = ET.SubElement(root, "header")
        name = ET.SubElement(header, "name")
        name.text = "Merged DAT"
        description = ET.SubElement(header, "description")
        description.text = "Merged DAT generated by R0MM"
        version = ET.SubElement(header, "version")
        version.text = "1.0"

        for game_name in sorted(all_roms.keys()):
            game = ET.SubElement(root, "game", {"name": game_name})
            desc = ET.SubElement(game, "description")
            desc.text = game_name
            for rom in all_roms[game_name]:
                attrs = {"name": rom.name}
                if rom.size:
                    attrs["size"] = str(rom.size)
                if rom.crc32:
                    attrs["crc"] = rom.crc32
                if rom.md5:
                    attrs["md5"] = rom.md5
                if rom.sha1:
                    attrs["sha1"] = rom.sha1
                if rom.status:
                    attrs["status"] = rom.status
                ET.SubElement(game, "rom", attrs)

        tree = ET.ElementTree(root)
        tree.write(output_path, encoding="utf-8", xml_declaration=True)

        return {
            "success": True,
            "output": output_path,
            "stats": {"total": len(seen_keys), "conflicts": conflicts},
        }

    def batch_convert(
        self,
        source_dir: str,
        output_dir: str,
        target_format: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict:
        if not source_dir or not output_dir or not target_format:
            return {"error": "source_dir, output_dir and target_format are required"}

        target = target_format.lower()
        if target not in {"chd", "rvz"}:
            return {"error": "target_format must be 'chd' or 'rvz'"}

        tool = "chdman" if target == "chd" else "dolphin-tool"
        if not self._tool_available(tool):
            return {"error": f"Required tool not found in PATH: {tool}"}

        exts = {".cue", ".iso", ".gdi"} if target == "chd" else {".iso"}
        inputs: List[str] = []
        for root_dir, _, files in os.walk(source_dir):
            for name in files:
                if os.path.splitext(name)[1].lower() in exts:
                    inputs.append(os.path.join(root_dir, name))

        if not inputs:
            return {"error": "No input files found"}

        os.makedirs(output_dir, exist_ok=True)
        converted = 0
        failed = 0
        bytes_saved = 0

        for idx, path in enumerate(inputs, start=1):
            if progress_callback:
                progress_callback(idx, len(inputs), path)

            base = os.path.splitext(os.path.basename(path))[0]
            out_path = os.path.join(output_dir, f"{base}.{target}")

            try:
                if target == "chd":
                    cmd = [tool, "createcd", "-i", path, "-o", out_path]
                else:
                    cmd = [tool, "convert", "-i", path, "-o", out_path, "-f", "rvz"]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    failed += 1
                    continue
                converted += 1
                try:
                    bytes_saved += max(0, os.path.getsize(path) - os.path.getsize(out_path))
                except OSError:
                    pass
            except Exception:
                failed += 1

        return {
            "success": True,
            "stats": {"converted": converted, "failed": failed, "bytes_saved": bytes_saved},
        }

    def apply_torrentzip(
        self, target_dir: str, progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> dict:
        if not target_dir:
            return {"error": "target_dir is required"}

        zip_paths: List[str] = []
        for root_dir, _, files in os.walk(target_dir):
            for name in files:
                if name.lower().endswith(".zip"):
                    zip_paths.append(os.path.join(root_dir, name))

        processed = 0
        skipped = 0
        failed = 0

        for idx, path in enumerate(zip_paths, start=1):
            if progress_callback:
                progress_callback(idx, len(zip_paths), path)
            tmp_path = ""
            try:
                with zipfile.ZipFile(path, "r") as zf:
                    entries = sorted(zf.infolist(), key=lambda z: z.filename.lower())
                    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip")
                    os.close(tmp_fd)
                    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as out_zf:
                        for info in entries:
                            data = zf.read(info.filename)
                            zi = zipfile.ZipInfo(info.filename)
                            zi.date_time = (1980, 1, 1, 0, 0, 0)
                            zi.compress_type = zipfile.ZIP_DEFLATED
                            out_zf.writestr(zi, data)

                orig_hash = self._hash_file(path, "sha1")
                new_hash = self._hash_file(tmp_path, "sha1")
                if orig_hash == new_hash:
                    skipped += 1
                    os.remove(tmp_path)
                else:
                    os.replace(tmp_path, path)
                    processed += 1
            except Exception:
                failed += 1
                try:
                    if tmp_path and os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass

        return {
            "success": True,
            "stats": {"processed": processed, "skipped": skipped, "failed": failed},
        }

    def deep_clean(
        self,
        target_dir: str,
        dat_id: Optional[str] = None,
        dry_run: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict:
        if not target_dir:
            return {"error": "target_dir is required"}

        junk_exts = {".txt", ".nfo", ".url", ".sfv", ".md", ".db", ".ini"}
        expected_names: Optional[set[str]] = None
        if dat_id:
            dat_path = self.dat_library.get_dat_path(dat_id)
            if dat_path and os.path.exists(dat_path):
                _, roms = DATParser.parse(dat_path)
                expected_names = {rom.name for rom in roms}

        candidates: List[str] = []
        total_size = 0
        all_files: List[str] = []
        for root_dir, _, files in os.walk(target_dir):
            for name in files:
                all_files.append(os.path.join(root_dir, name))

        for idx, path in enumerate(all_files, start=1):
            if progress_callback:
                progress_callback(idx, len(all_files), path)
            ext = os.path.splitext(path)[1].lower()
            base = os.path.basename(path)
            if ext in junk_exts:
                candidates.append(path)
            elif expected_names is not None and base not in expected_names:
                candidates.append(path)

        removed = 0
        for path in candidates:
            try:
                total_size += os.path.getsize(path)
            except OSError:
                pass
            if not dry_run:
                try:
                    os.remove(path)
                    removed += 1
                except Exception:
                    pass

        return {
            "success": True,
            "stats": {"candidates": len(candidates), "removed": removed, "bytes": total_size},
            "files": candidates,
        }

    def find_duplicates(
        self, target_dir: str, progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> dict:
        if not target_dir:
            return {"error": "target_dir is required"}

        file_paths: List[str] = []
        for root_dir, _, files in os.walk(target_dir):
            for name in files:
                file_paths.append(os.path.join(root_dir, name))

        buckets: Dict[str, List[str]] = {}
        for idx, path in enumerate(file_paths, start=1):
            if progress_callback:
                progress_callback(idx, len(file_paths), path)
            try:
                crc = self._crc32_file(path)
                size = os.path.getsize(path)
                key = f"{crc}:{size}"
                buckets.setdefault(key, []).append(path)
            except Exception:
                continue

        duplicates = {k: v for k, v in buckets.items() if len(v) > 1}
        return {"success": True, "duplicates": duplicates}
