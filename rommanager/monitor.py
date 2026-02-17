"""Realtime application monitoring utilities."""

from __future__ import annotations

import logging
import os
import time
from logging.handlers import RotatingFileHandler
from typing import Optional


MONITOR_LOG_PATH = os.path.join(os.path.expanduser("~"), ".rommanager", "events.log")
LOGGER_NAME = "rommanager.monitor"


def setup_monitoring(log_file: Optional[str] = None, echo: bool = True) -> logging.Logger:
    """Configure process-wide monitoring logger.

    Args:
        log_file: Destination path for structured event logs.
        echo: If True, mirror events to stdout.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)

    destination = os.path.abspath(log_file or MONITOR_LOG_PATH)
    os.makedirs(os.path.dirname(destination), exist_ok=True)

    # Reconfigure logger cleanly when called multiple times.
    if logger.handlers:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    file_handler = RotatingFileHandler(destination, maxBytes=2_000_000, backupCount=3)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(event)s | %(message)s",
        "%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(file_handler)

    if echo:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%H:%M:%S"))
        logger.addHandler(stream_handler)

    return logger


def log_event(event: str, message: str, level: int = logging.INFO):
    """Emit a structured monitoring event."""
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        logger = setup_monitoring(echo=False)
    logger.log(level, message, extra={"event": event})


def tail_events(log_file: Optional[str] = None, poll_interval: float = 0.25):
    """Tail event log continuously (CLI realtime mode)."""
    destination = os.path.abspath(log_file or MONITOR_LOG_PATH)
    print(f"Monitoring realtime events from: {destination}")
    print("Press Ctrl+C to stop.\n")

    os.makedirs(os.path.dirname(destination), exist_ok=True)
    if not os.path.exists(destination):
        open(destination, "a", encoding="utf-8").close()

    with open(destination, "r", encoding="utf-8") as f:
        f.seek(0, os.SEEK_END)
        try:
            while True:
                line = f.readline()
                if line:
                    print(line.rstrip())
                else:
                    time.sleep(poll_interval)
        except KeyboardInterrupt:
            print("\nMonitor stopped.")
