"""
omnix — internal package holding the infrastructure pieces shared across the
server, connectors, simulation, and workspace modules.

This package is intentionally small and dependency-free: it's the glue that
lets the rest of the codebase speak the same language for errors, logging,
configuration, and data shapes.

Modules:
  errors       Structured error hierarchy + JSON error helpers
  logging      Centralized logger configuration
  models       Typed dataclasses for every shared payload shape
  config       App-wide constants and env-configurable settings
  state        Single AppState container holding all runtime singletons
"""

from .errors import (
    OmnixError,
    ValidationError,
    NotFoundError,
    ConflictError,
    UpstreamError,
    error_response,
)
from .logging_setup import get_logger, configure_logging
from .config import settings

__all__ = [
    "OmnixError",
    "ValidationError",
    "NotFoundError",
    "ConflictError",
    "UpstreamError",
    "error_response",
    "get_logger",
    "configure_logging",
    "settings",
]
