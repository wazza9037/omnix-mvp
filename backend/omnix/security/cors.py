"""
CORS (Cross-Origin Resource Sharing) middleware.

Configurable allowed origins, methods, and headers.
"""

from __future__ import annotations

import os
from typing import Any

from omnix.logging_setup import get_logger

log = get_logger("omnix.security.cors")


class CORSMiddleware:
    """Handles CORS preflight and response headers."""

    def __init__(
        self,
        allowed_origins: list[str] | None = None,
        allowed_methods: list[str] | None = None,
        allowed_headers: list[str] | None = None,
        max_age: int = 86400,
        allow_credentials: bool = True,
    ):
        # Parse from env or use defaults
        env_origins = os.getenv("OMNIX_CORS_ORIGINS", "")
        if env_origins:
            self.allowed_origins = [o.strip() for o in env_origins.split(",")]
        elif allowed_origins:
            self.allowed_origins = allowed_origins
        else:
            self.allowed_origins = ["*"]  # Permissive default for development

        self.allowed_methods = allowed_methods or [
            "GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS",
        ]
        self.allowed_headers = allowed_headers or [
            "Content-Type", "Authorization", "X-Requested-With",
            "Accept", "Origin", "Cache-Control",
        ]
        self.max_age = max_age
        self.allow_credentials = allow_credentials

    def get_headers(self, request_origin: str = "") -> dict[str, str]:
        """Generate CORS response headers based on the request origin."""
        headers: dict[str, str] = {}

        # Determine the allowed origin for this request
        if "*" in self.allowed_origins:
            headers["Access-Control-Allow-Origin"] = "*"
        elif request_origin in self.allowed_origins:
            headers["Access-Control-Allow-Origin"] = request_origin
            headers["Vary"] = "Origin"
        elif self.allowed_origins:
            # No match — still set Vary so caches behave correctly
            headers["Vary"] = "Origin"
            return headers  # No CORS headers = browser blocks the request

        headers["Access-Control-Allow-Methods"] = ", ".join(self.allowed_methods)
        headers["Access-Control-Allow-Headers"] = ", ".join(self.allowed_headers)
        headers["Access-Control-Max-Age"] = str(self.max_age)

        if self.allow_credentials and "*" not in self.allowed_origins:
            headers["Access-Control-Allow-Credentials"] = "true"

        return headers

    def handle_preflight(self, handler: Any) -> bool:
        """
        Handle an OPTIONS preflight request.
        Returns True if it was a preflight (response already sent).
        """
        if handler.command != "OPTIONS":
            return False

        origin = handler.headers.get("Origin", "")
        cors_headers = self.get_headers(origin)

        handler.send_response(204)
        for k, v in cors_headers.items():
            handler.send_header(k, v)
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return True

    def apply_headers(self, handler: Any) -> None:
        """Apply CORS headers to a regular response."""
        origin = handler.headers.get("Origin", "")
        for k, v in self.get_headers(origin).items():
            handler.send_header(k, v)
