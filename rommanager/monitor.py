"""Runtime monitoring and observability helpers for R0MM."""

from __future__ import annotations

import faulthandler
import logging
import signal
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Callable, Optional

_INITIALIZED = False
_HEARTBEAT_STOP = threading.Event()
_FAULT_HANDLER_FILE = None


def _default_log_path() -> Path:
    base = Path.home() / ".rommanager" / "logs"
    base.mkdir(parents=True, exist_ok=True)
    return base / "runtime.log"


def setup_runtime_monitor(app_name: str = "rommanager", heartbeat_seconds: int = 15) -> logging.Logger:
    """Initialize global runtime monitoring/logging once per process."""
    global _INITIALIZED
    logger = logging.getLogger(app_name)

    if _INITIALIZED:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(threadName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    log_path = _default_log_path()
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)

    # low-level crash dumps (segfaults, deadlocks with signals) to dedicated file
    global _FAULT_HANDLER_FILE
    crash_log = log_path.with_name("crash.log")
    _FAULT_HANDLER_FILE = crash_log.open("a", encoding="utf-8")
    faulthandler.enable(file=_FAULT_HANDLER_FILE)

    logger.info("Runtime monitor initialized")
    logger.info("Log file: %s", log_path)

    _install_exception_hooks(logger)
    _install_signal_hooks(logger)
    _start_heartbeat(logger, heartbeat_seconds)

    _INITIALIZED = True
    return logger


def _install_exception_hooks(logger: logging.Logger) -> None:
    def _sys_hook(exc_type, exc_value, exc_tb):
        logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))

    def _thread_hook(args: threading.ExceptHookArgs):
        logger.critical(
            "Unhandled thread exception in %s",
            args.thread.name if args.thread else "<unknown>",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _sys_hook
    threading.excepthook = _thread_hook


def _install_signal_hooks(logger: logging.Logger) -> None:
    def _signal_handler(signum, _frame):
        logger.warning("Received signal %s, shutting down", signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _signal_handler)
        except Exception:
            logger.debug("Could not install signal handler for %s", sig)


def _start_heartbeat(logger: logging.Logger, heartbeat_seconds: int) -> None:
    if heartbeat_seconds <= 0:
        return

    def _worker():
        while not _HEARTBEAT_STOP.is_set():
            logger.info("heartbeat: app alive")
            _HEARTBEAT_STOP.wait(heartbeat_seconds)

    th = threading.Thread(target=_worker, name="monitor-heartbeat", daemon=True)
    th.start()


def monitor_action(action: str, *, logger: Optional[logging.Logger] = None) -> None:
    """Emit a real-time action event."""
    (logger or logging.getLogger("rommanager")).info("action: %s", action)


def start_monitored_thread(
    target: Callable[[], None],
    *,
    name: str,
    logger: Optional[logging.Logger] = None,
    daemon: bool = True,
) -> threading.Thread:
    """Start a thread that logs start/end and never fails silently."""
    log = logger or logging.getLogger("rommanager")

    def _wrapped():
        log.info("thread start: %s", name)
        started = time.time()
        try:
            target()
            log.info("thread end: %s (%.2fs)", name, time.time() - started)
        except Exception:
            log.exception("thread crash: %s", name)
            raise

    th = threading.Thread(target=_wrapped, name=name, daemon=daemon)
    th.start()
    return th


def install_tk_exception_bridge(root, *, logger: Optional[logging.Logger] = None) -> None:
    """Route Tkinter callback exceptions to monitor logs and stderr."""
    log = logger or logging.getLogger("rommanager")

    def _report_callback_exception(exc, val, tb):
        log.critical("Tk callback exception", exc_info=(exc, val, tb))
        traceback.print_exception(exc, val, tb)

    root.report_callback_exception = _report_callback_exception
