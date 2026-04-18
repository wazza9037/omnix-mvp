"""
Centralized logging setup.

`configure_logging()` should be called exactly once at startup. After that,
every module uses `get_logger(__name__)` to get a named logger.

Features:
  - Level controlled by OMNIX_LOG_LEVEL env var (default INFO)
  - Structured, human-readable format with module name + level + message
  - Optional JSON formatter when OMNIX_LOG_JSON=1 (useful for log pipelines)
  - Never emits bare print() — uses logging throughout
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any


class _JsonFormatter(logging.Formatter):
    """Structured JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Pick up any extra={…} keys the caller attached
        for k, v in record.__dict__.items():
            if k in ("name", "msg", "args", "levelname", "levelno", "pathname",
                    "filename", "module", "exc_info", "exc_text", "stack_info",
                    "lineno", "funcName", "created", "msecs", "relativeCreated",
                    "thread", "threadName", "processName", "process", "message"):
                continue
            try:
                json.dumps(v)
                payload[k] = v
            except (TypeError, ValueError):
                payload[k] = repr(v)
        return json.dumps(payload, default=str)


class _PrettyFormatter(logging.Formatter):
    """Human-readable colored(ish) formatter."""

    COLORS = {
        "DEBUG": "\033[37m",     # grey
        "INFO": "\033[36m",      # cyan
        "WARNING": "\033[33m",   # yellow
        "ERROR": "\033[31m",     # red
        "CRITICAL": "\033[41m",  # red bg
    }
    RESET = "\033[0m"

    def __init__(self, use_color: bool = True):
        super().__init__("%(asctime)s %(levelname)-7s %(name)-28s %(message)s",
                         datefmt="%H:%M:%S")
        self.use_color = use_color and sys.stderr.isatty()

    def format(self, record: logging.LogRecord) -> str:
        raw = super().format(record)
        if self.use_color:
            color = self.COLORS.get(record.levelname, "")
            if color:
                raw = color + raw + self.RESET
        return raw


_configured = False


def configure_logging(level: str | None = None, as_json: bool | None = None) -> None:
    """Set up the root logger exactly once."""
    global _configured
    if _configured:
        return

    level = (level or os.getenv("OMNIX_LOG_LEVEL") or "INFO").upper()
    if as_json is None:
        as_json = os.getenv("OMNIX_LOG_JSON", "0").lower() in ("1", "true", "yes")

    root = logging.getLogger()
    root.handlers[:] = []   # clear defaults

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter() if as_json else _PrettyFormatter())
    root.addHandler(handler)
    root.setLevel(level)

    # Silence noisy stdlib modules unless explicitly debug
    for quiet in ("urllib3", "asyncio"):
        logging.getLogger(quiet).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger. Safe to call before configure_logging — the
    logger just won't emit until configuration happens."""
    return logging.getLogger(name)
