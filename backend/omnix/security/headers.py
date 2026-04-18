"""
Secure HTTP response headers.

Sets security-related headers on all responses to mitigate
common web vulnerabilities (XSS, clickjacking, MIME sniffing, etc.).
"""

from __future__ import annotations

from typing import Any


class SecureHeaders:
    """Applies security headers to HTTP responses."""

    # Default security headers
    HEADERS: dict[str, str] = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
    }

    # Headers for static assets (more permissive caching)
    STATIC_HEADERS: dict[str, str] = {
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "public, max-age=3600",
    }

    def __init__(self, csp: str | None = None):
        self.headers = dict(self.HEADERS)
        if csp:
            self.headers["Content-Security-Policy"] = csp
        else:
            self.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
                "img-src 'self' data: blob: https:; "
                "connect-src 'self' ws: wss:; "
                "frame-ancestors 'none'"
            )

    def apply(self, handler: Any, is_static: bool = False) -> None:
        """Apply security headers to the response."""
        headers = self.STATIC_HEADERS if is_static else self.headers
        for key, value in headers.items():
            handler.send_header(key, value)

    def apply_to_dict(self, is_static: bool = False) -> dict[str, str]:
        """Return headers as a dict (useful for testing)."""
        return dict(self.STATIC_HEADERS if is_static else self.headers)
