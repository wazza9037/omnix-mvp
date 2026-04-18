"""
Structured error hierarchy + JSON response helpers.

Every route handler should raise one of these (or let one propagate) rather
than handcrafting error dicts. The handler catches them and renders a
consistent payload shape:

    {
      "error": {
        "code":    "not_found",
        "message": "Device not found",
        "details": { … optional structured context … }
      }
    }

Callers (frontend, SDK) can rely on `code` being one of a known set:

    validation_error
    not_found
    conflict
    upstream_error
    internal_error

This avoids the churn of matching on human-readable `message` strings that
change over time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Tuple


class OmnixError(Exception):
    """Base for every error raised from within the app.

    Subclasses set `status` (HTTP status) and `code` (stable machine code).
    """

    status: int = 500
    code: str = "internal_error"

    def __init__(self, message: str = "", details: Mapping[str, Any] | None = None):
        super().__init__(message or self.__class__.__name__)
        self.message = message or self.__class__.__name__
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            out["details"] = self.details
        return out


class ValidationError(OmnixError):
    status = 400
    code = "validation_error"


class NotFoundError(OmnixError):
    status = 404
    code = "not_found"


class ConflictError(OmnixError):
    status = 409
    code = "conflict"


class UpstreamError(OmnixError):
    """An upstream system (vendor SDK, network) failed — not our fault."""
    status = 502
    code = "upstream_error"


def error_response(exc: BaseException) -> Tuple[int, dict]:
    """Convert any exception into (status_code, body) for the HTTP layer.

    Unknown exceptions are squashed to a generic internal_error so we don't
    leak tracebacks to clients. The server logs the original with stack.
    """
    if isinstance(exc, OmnixError):
        return exc.status, {"error": exc.to_dict()}
    return 500, {
        "error": {
            "code": "internal_error",
            "message": "Internal server error",
            "details": {"exception_type": type(exc).__name__},
        }
    }
