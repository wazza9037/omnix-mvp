"""
Auth middleware for the stdlib HTTP server.

Validates JWT tokens on protected routes and injects user context.
"""

from __future__ import annotations

import threading
from typing import Any, Optional, Callable

from omnix.logging_setup import get_logger
from .models import User, GUEST_USER
from .auth import AuthManager

log = get_logger("omnix.auth.middleware")

# Thread-local storage for current request's user
_request_context = threading.local()


def get_current_user() -> Optional[User]:
    """Get the authenticated user for the current request."""
    return getattr(_request_context, "user", None)


def set_current_user(user: Optional[User]) -> None:
    """Set the user for the current request context."""
    _request_context.user = user


# Routes that don't require authentication
PUBLIC_ROUTES = {
    "/healthz",
    "/api/health",
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/refresh",
    "/api/auth/guest",
    "/api/metrics",
}

# Prefixes that are public (static files, etc.)
PUBLIC_PREFIXES = (
    "/static/",
    "/assets/",
    "/favicon",
)


def is_public_route(path: str) -> bool:
    """Check if a route is public (no auth required)."""
    # Strip query string
    clean = path.split("?")[0].rstrip("/")
    if clean in PUBLIC_ROUTES or clean == "":
        return True
    for prefix in PUBLIC_PREFIXES:
        if clean.startswith(prefix):
            return True
    # Static file serving (HTML, JS, CSS, images)
    if "." in clean.split("/")[-1]:
        ext = clean.rsplit(".", 1)[-1].lower()
        if ext in ("html", "js", "css", "png", "jpg", "svg", "ico", "woff", "woff2", "ttf", "map"):
            return True
    return False


class AuthMiddleware:
    """
    Validates JWT tokens and manages request authentication.

    Usage in the HTTP handler:
        user = auth_middleware.authenticate(self)
        if user is None and not is_public:
            self._json_response({"error": "Unauthorized"}, 401)
            return
    """

    def __init__(self, auth_manager: AuthManager):
        self.auth = auth_manager

    def authenticate(self, handler: Any) -> Optional[User]:
        """
        Extract and validate the JWT from the request.

        Checks the Authorization header for a Bearer token.
        Returns the User if valid, GUEST_USER if guest mode, or None.
        """
        path = handler.path.split("?")[0]

        # Public routes don't need auth
        if is_public_route(path):
            guest = self.auth.get_guest_user()
            set_current_user(guest)
            return guest

        # Extract token from Authorization header
        auth_header = handler.headers.get("Authorization", "")
        token = None

        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

        if not token:
            # Check query param fallback (for WebSocket upgrades, etc.)
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(handler.path).query)
            token = qs.get("token", [None])[0]

        if token:
            payload = self.auth.validate_token(token)
            if payload:
                user = self.auth.get_user(payload["sub"])
                if user and user.is_active:
                    set_current_user(user)
                    return user

        # Fall back to guest mode if enabled
        if self.auth.guest_mode:
            set_current_user(GUEST_USER)
            return GUEST_USER

        set_current_user(None)
        return None


def require_auth(handler: Any, auth_middleware: AuthMiddleware) -> Optional[User]:
    """
    Convenience: authenticate and return 401 if not authenticated.

    Returns the User if authenticated, or None (after sending 401).
    The caller should check and return early if None.
    """
    user = auth_middleware.authenticate(handler)
    if user is None:
        handler._json_response(
            {"error": {"code": "unauthorized", "message": "Authentication required"}},
            401,
        )
        return None
    return user
