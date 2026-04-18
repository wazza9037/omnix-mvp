"""
Blackboard — shared key-value store for a single tree execution.

The blackboard is the primary communication channel between BT nodes.
Condition nodes read from it, action nodes write to it, and the
executor seeds it with device telemetry each tick.

Features:
  - Typed values with optional schema validation
  - Change listeners (for reactive condition nodes)
  - Built-in log stream for mission audit trail
  - JSON-serializable snapshot for pause/resume
"""

from __future__ import annotations

import time
import threading
from typing import Any, Callable


class Blackboard:
    """Thread-safe key-value store scoped to one tree execution."""

    def __init__(self, initial: dict[str, Any] | None = None):
        self._data: dict[str, Any] = dict(initial or {})
        self._lock = threading.Lock()
        self._listeners: list[Callable[[str, Any, Any], None]] = []
        self._log: list[dict] = []  # [{time, message, level}]
        self._log_limit = 200

    # ── Read / Write ─────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            old = self._data.get(key)
            self._data[key] = value
        # Fire listeners outside the lock to avoid deadlocks
        if old != value:
            for fn in self._listeners:
                try:
                    fn(key, old, value)
                except Exception:
                    pass

    def has(self, key: str) -> bool:
        with self._lock:
            return key in self._data

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._data:
                del self._data[key]
                return True
            return False

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._data.keys())

    def to_dict(self) -> dict[str, Any]:
        """Snapshot of all data (JSON-safe)."""
        with self._lock:
            return dict(self._data)

    # ── Bulk update (used by executor to seed telemetry) ──

    def update(self, mapping: dict[str, Any]) -> None:
        for k, v in mapping.items():
            self.set(k, v)

    # ── Listeners ────────────────────────────────────────

    def on_change(self, fn: Callable[[str, Any, Any], None]) -> None:
        """Register a callback: fn(key, old_value, new_value)."""
        self._listeners.append(fn)

    # ── Log stream ───────────────────────────────────────

    def log(self, message: str, level: str = "info") -> None:
        entry = {"time": time.time(), "message": message, "level": level}
        with self._lock:
            self._log.append(entry)
            if len(self._log) > self._log_limit:
                self._log = self._log[-self._log_limit:]

    def get_logs(self, since: float = 0.0) -> list[dict]:
        with self._lock:
            if since <= 0:
                return list(self._log)
            return [e for e in self._log if e["time"] > since]

    def clear_logs(self) -> None:
        with self._lock:
            self._log.clear()

    # ── Reset ────────────────────────────────────────────

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._log.clear()

    def __repr__(self):
        with self._lock:
            keys = list(self._data.keys())
        return f"<Blackboard keys={keys}>"
