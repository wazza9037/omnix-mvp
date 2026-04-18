"""
Request logging and metrics middleware.

Tracks request counts, durations, error rates, and active sessions.
Provides a /api/metrics endpoint for monitoring.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from omnix.logging_setup import get_logger

log = get_logger("omnix.middleware")


@dataclass
class _RequestMetric:
    count: int = 0
    error_count: int = 0
    total_duration_ms: float = 0
    max_duration_ms: float = 0


class MetricsCollector:
    """Collects and serves application metrics."""

    def __init__(self):
        self._lock = threading.Lock()
        self._started_at = time.time()
        self._total_requests = 0
        self._total_errors = 0
        self._by_method: dict[str, _RequestMetric] = defaultdict(_RequestMetric)
        self._by_status: dict[int, int] = defaultdict(int)
        self._by_path: dict[str, _RequestMetric] = defaultdict(_RequestMetric)
        self._active_requests = 0
        self._active_ws_connections = 0
        self._active_sessions = 0
        self._device_count = 0

    def record_request(self, method: str, path: str, status: int,
                       duration_ms: float) -> None:
        """Record a completed request."""
        # Normalize path (strip query string, collapse IDs)
        clean_path = path.split("?")[0]

        with self._lock:
            self._total_requests += 1
            if status >= 400:
                self._total_errors += 1

            self._by_status[status] += 1

            m = self._by_method[method]
            m.count += 1
            m.total_duration_ms += duration_ms
            m.max_duration_ms = max(m.max_duration_ms, duration_ms)
            if status >= 400:
                m.error_count += 1

            # Collapse specific IDs in paths for grouping
            p = self._by_path[clean_path]
            p.count += 1
            p.total_duration_ms += duration_ms
            if status >= 400:
                p.error_count += 1

    def request_started(self) -> None:
        with self._lock:
            self._active_requests += 1

    def request_finished(self) -> None:
        with self._lock:
            self._active_requests = max(0, self._active_requests - 1)

    def update_gauges(self, device_count: int = 0, active_sessions: int = 0,
                      ws_connections: int = 0) -> None:
        """Update gauge metrics (called periodically or on-demand)."""
        with self._lock:
            self._device_count = device_count
            self._active_sessions = active_sessions
            self._active_ws_connections = ws_connections

    def get_metrics(self) -> dict[str, Any]:
        """Return all metrics as a JSON-serializable dict."""
        with self._lock:
            uptime = time.time() - self._started_at
            avg_rps = self._total_requests / uptime if uptime > 0 else 0

            return {
                "uptime_s": round(uptime, 1),
                "started_at": self._started_at,
                "requests": {
                    "total": self._total_requests,
                    "errors": self._total_errors,
                    "active": self._active_requests,
                    "avg_rps": round(avg_rps, 2),
                    "by_method": {
                        m: {
                            "count": v.count,
                            "errors": v.error_count,
                            "avg_ms": round(v.total_duration_ms / v.count, 1) if v.count else 0,
                            "max_ms": round(v.max_duration_ms, 1),
                        }
                        for m, v in self._by_method.items()
                    },
                    "by_status": dict(self._by_status),
                },
                "connections": {
                    "websocket": self._active_ws_connections,
                    "collab_sessions": self._active_sessions,
                },
                "devices": {
                    "count": self._device_count,
                },
                "top_endpoints": self._top_endpoints(10),
            }

    def _top_endpoints(self, n: int) -> list[dict]:
        """Return the top N most-hit endpoints."""
        sorted_paths = sorted(
            self._by_path.items(),
            key=lambda x: x[1].count,
            reverse=True,
        )[:n]
        return [
            {
                "path": path,
                "count": m.count,
                "errors": m.error_count,
                "avg_ms": round(m.total_duration_ms / m.count, 1) if m.count else 0,
            }
            for path, m in sorted_paths
        ]


class RequestLogger:
    """
    Middleware that logs every request with method, path, status, and duration.
    """

    def __init__(self, metrics: MetricsCollector):
        self.metrics = metrics

    def before_request(self, handler: Any) -> float:
        """Call at the start of request handling. Returns the start timestamp."""
        self.metrics.request_started()
        return time.time()

    def after_request(self, handler: Any, start_time: float, status: int) -> None:
        """Call after request handling is complete."""
        duration_ms = (time.time() - start_time) * 1000
        method = getattr(handler, "command", "?")
        path = getattr(handler, "path", "?")

        self.metrics.request_finished()
        self.metrics.record_request(method, path, status, duration_ms)

        # Log at appropriate level
        if status >= 500:
            log.error("http %s %s -> %d (%.1fms)", method, path, status, duration_ms)
        elif status >= 400:
            log.warning("http %s %s -> %d (%.1fms)", method, path, status, duration_ms)
        else:
            log.debug("http %s %s -> %d (%.1fms)", method, path, status, duration_ms)


# Singleton instances
metrics_collector = MetricsCollector()
request_logger = RequestLogger(metrics_collector)
