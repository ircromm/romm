"""
Lightweight application monitor/event bus.
Tracks operations, warnings, and errors across CLI/GUI/Web flows.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from threading import Lock
from typing import Callable, Dict, List, Optional


@dataclass
class MonitorEvent:
    timestamp: str
    level: str
    source: str
    message: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


class AppMonitor:
    """Thread-safe in-memory monitor with bounded history."""

    def __init__(self, max_events: int = 2000):
        self.max_events = max_events
        self._events: List[MonitorEvent] = []
        self._listeners: List[Callable[[MonitorEvent], None]] = []
        self._lock = Lock()

    def emit(self, level: str, source: str, message: str) -> MonitorEvent:
        event = MonitorEvent(
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            level=level.upper(),
            source=source,
            message=message,
        )
        with self._lock:
            self._events.append(event)
            if len(self._events) > self.max_events:
                self._events = self._events[-self.max_events:]
            listeners = self._listeners[:]

        for listener in listeners:
            try:
                listener(event)
            except Exception:
                # Never let monitor listeners break app flow.
                pass

        return event

    def info(self, source: str, message: str) -> MonitorEvent:
        return self.emit('INFO', source, message)

    def warning(self, source: str, message: str) -> MonitorEvent:
        return self.emit('WARNING', source, message)

    def error(self, source: str, message: str) -> MonitorEvent:
        return self.emit('ERROR', source, message)

    def get_events(self, limit: int = 200) -> List[Dict[str, str]]:
        with self._lock:
            events = self._events[-limit:]
        return [e.to_dict() for e in events]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def subscribe(self, listener: Callable[[MonitorEvent], None]) -> None:
        with self._lock:
            self._listeners.append(listener)


monitor = AppMonitor()
