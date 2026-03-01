"""Runtime monitoring and observability helpers for R0MM."""

from __future__ import annotations

import faulthandler
import logging
import signal
import sys
import threading
import time
import traceback
from datetime import date
from pathlib import Path
from typing import Callable, Optional

_INITIALIZED = False
_HEARTBEAT_STOP = threading.Event()
_FAULT_HANDLER_FILE = None
_SESSION_LOG_DATE: Optional[date] = None


def _default_log_path() -> Path:
    from .shared_config import LOGS_DIR

    base = Path(LOGS_DIR)
    base.mkdir(parents=True, exist_ok=True)
    session_day = _SESSION_LOG_DATE or date.today()
    return base / f"runtime-{session_day.isoformat()}.log"


def get_log_path() -> Path:
    """Return the active runtime log path for this session."""
    return _default_log_path()


def setup_runtime_monitor(app_name: str = "rommanager", heartbeat_seconds: int = 0) -> logging.Logger:
    """Initialize global runtime monitoring/logging once per process."""
    global _INITIALIZED
    logger = logging.getLogger(app_name)

    if _INITIALIZED:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    global _SESSION_LOG_DATE
    if _SESSION_LOG_DATE is None:
        _SESSION_LOG_DATE = date.today()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(threadName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_path = _default_log_path()
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

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
    if heartbeat_seconds > 0:
        _start_heartbeat(logger, heartbeat_seconds)

    _INITIALIZED = True
    return logger


def _install_exception_hooks(logger: logging.Logger) -> None:
    def _print_to_terminal(exc_type, exc_value, exc_tb, *, prefix: str | None = None) -> None:
        stream = getattr(sys, "__stderr__", None) or sys.stderr
        if stream is None:
            return
        try:
            if prefix:
                print(prefix, file=stream)
            traceback.print_exception(exc_type, exc_value, exc_tb, file=stream)
            stream.flush()
        except Exception:
            pass

    def _sys_hook(exc_type, exc_value, exc_tb):
        if exc_type and issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
        _print_to_terminal(exc_type, exc_value, exc_tb, prefix="[R0MM] Unhandled exception")

    def _thread_hook(args: threading.ExceptHookArgs):
        thread_name = args.thread.name if args.thread else "<unknown>"
        logger.critical(
            "Unhandled thread exception in %s",
            thread_name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        _print_to_terminal(
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
            prefix=f"[R0MM] Unhandled thread exception ({thread_name})",
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


def attach_tk_click_monitor(root, *, logger: Optional[logging.Logger] = None) -> None:
    """Open a background monitor window and log every Tk click event."""
    if getattr(root, "_romm_click_monitor_attached", False):
        return

    log = logger or logging.getLogger("rommanager")

    try:
        import tkinter as tk
    except Exception:
        log.warning("tk click monitor unavailable: tkinter import failed")
        return

    monitor_window = tk.Toplevel(root)
    monitor_window.title(f"R0MM Event Monitor - {_SESSION_LOG_DATE or date.today():%Y-%m-%d}")
    monitor_window.geometry("560x260+40+40")
    monitor_window.configure(bg="#101018")
    monitor_window.lower()

    text = tk.Text(
        monitor_window,
        wrap="word",
        bg="#101018",
        fg="#cdd6f4",
        insertbackground="#cdd6f4",
        relief="flat",
        font=("Consolas", 9),
    )
    text.pack(fill="both", expand=True, padx=8, pady=8)

    def _write_line(line: str) -> None:
        text.insert("end", f"{line}\n")
        text.see("end")

    _write_line("[monitor] dedicated click monitor started")

    def _on_click(event):
        widget = event.widget
        widget_desc = f"{widget.winfo_class()}:{widget.winfo_name()}"
        action = f"click: widget={widget_desc} local=({event.x},{event.y}) screen=({event.x_root},{event.y_root})"
        log.info(action)
        _write_line(action)

    root.bind_all("<Button>", _on_click, add="+")
    root._romm_click_monitor_attached = True
    root._romm_click_monitor_window = monitor_window
    log.info("Tk click monitor window opened")
