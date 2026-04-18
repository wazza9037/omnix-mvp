"""
JWT-based authentication manager.

Uses stdlib hashlib for password hashing (PBKDF2-SHA256) and a simple
JWT implementation using hmac + json + base64 (no external dependency).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Optional

from omnix.logging_setup import get_logger
from .models import User, UserRole, GUEST_USER

log = get_logger("omnix.auth")

# Default avatar colors for new users
_AVATAR_COLORS = [
    "#4A90D9", "#E74C3C", "#2ECC71", "#F39C12", "#9B59B6",
    "#1ABC9C", "#E67E22", "#3498DB", "#E91E63", "#00BCD4",
]


class AuthError(Exception):
    """Authentication/authorization error."""

    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.message = message
        self.status = status


class AuthManager:
    """
    Handles user registration, login, and JWT token management.

    Users are stored in-memory by default. When a database repository
    is provided, it delegates to that for persistence.
    """

    def __init__(
        self,
        secret_key: str | None = None,
        token_expiry_seconds: int = 86400,  # 24 hours
        refresh_expiry_seconds: int = 604800,  # 7 days
        guest_mode: bool = True,
    ):
        self.secret_key = secret_key or os.getenv(
            "OMNIX_JWT_SECRET", secrets.token_hex(32)
        )
        self.token_expiry = token_expiry_seconds
        self.refresh_expiry = refresh_expiry_seconds
        self.guest_mode = guest_mode

        # In-memory user store (replaced by DB repository when available)
        self._users: dict[str, User] = {}  # id -> User
        self._by_username: dict[str, str] = {}  # username -> id
        self._by_email: dict[str, str] = {}  # email -> id
        self._refresh_tokens: dict[str, str] = {}  # token -> user_id

        self._db_repo = None  # Set externally when DB is available

    def set_repository(self, repo: Any) -> None:
        """Attach a database repository for persistent user storage."""
        self._db_repo = repo

    # ── Password hashing ──

    @staticmethod
    def hash_password(password: str, salt: bytes | None = None) -> str:
        """PBKDF2-SHA256 password hash. Returns salt$hash in hex."""
        if salt is None:
            salt = os.urandom(16)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
        return salt.hex() + "$" + dk.hex()

    @staticmethod
    def verify_password(password: str, stored_hash: str) -> bool:
        """Verify a password against a stored PBKDF2 hash."""
        try:
            salt_hex, hash_hex = stored_hash.split("$", 1)
            salt = bytes.fromhex(salt_hex)
            dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
            return hmac.compare_digest(dk.hex(), hash_hex)
        except (ValueError, AttributeError):
            return False

    # ── JWT tokens ──

    def _encode_jwt(self, payload: dict[str, Any]) -> str:
        """Encode a JWT token using HMAC-SHA256."""
        header = {"alg": "HS256", "typ": "JWT"}
        h = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=")
        p = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=")
        msg = h + b"." + p
        sig = hmac.new(self.secret_key.encode(), msg, hashlib.sha256).digest()
        s = base64.urlsafe_b64encode(sig).rstrip(b"=")
        return (msg + b"." + s).decode()

    def _decode_jwt(self, token: str) -> Optional[dict[str, Any]]:
        """Decode and verify a JWT token. Returns payload or None."""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None

            msg = (parts[0] + "." + parts[1]).encode()
            sig = base64.urlsafe_b64decode(parts[2] + "==")
            expected = hmac.new(
                self.secret_key.encode(), msg, hashlib.sha256
            ).digest()

            if not hmac.compare_digest(sig, expected):
                return None

            payload_bytes = base64.urlsafe_b64decode(parts[1] + "==")
            payload = json.loads(payload_bytes)

            # Check expiration
            if payload.get("exp", 0) < time.time():
                return None

            return payload
        except Exception:
            return None

    def create_token(self, user: User) -> str:
        """Create an access token for a user."""
        payload = {
            "sub": user.id,
            "username": user.username,
            "role": user.role.value,
            "iat": time.time(),
            "exp": time.time() + self.token_expiry,
        }
        return self._encode_jwt(payload)

    def create_refresh_token(self, user: User) -> str:
        """Create a refresh token for a user."""
        token = secrets.token_urlsafe(48)
        self._refresh_tokens[token] = user.id
        return token

    def validate_token(self, token: str) -> Optional[dict[str, Any]]:
        """Validate an access token and return its payload."""
        return self._decode_jwt(token)

    def refresh_access_token(self, refresh_token: str) -> Optional[dict[str, str]]:
        """Use a refresh token to get a new access token."""
        user_id = self._refresh_tokens.get(refresh_token)
        if not user_id:
            return None

        user = self._get_user_by_id(user_id)
        if not user or not user.is_active:
            return None

        # Rotate refresh token
        del self._refresh_tokens[refresh_token]
        new_access = self.create_token(user)
        new_refresh = self.create_refresh_token(user)

        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "expires_in": self.token_expiry,
        }

    # ── User management ──

    def _get_user_by_id(self, user_id: str) -> Optional[User]:
        if self._db_repo:
            return self._db_repo.get_user(user_id)
        return self._users.get(user_id)

    def _get_user_by_username(self, username: str) -> Optional[User]:
        if self._db_repo:
            return self._db_repo.get_user_by_username(username)
        uid = self._by_username.get(username.lower())
        return self._users.get(uid) if uid else None

    def _get_user_by_email(self, email: str) -> Optional[User]:
        if self._db_repo:
            return self._db_repo.get_user_by_email(email)
        uid = self._by_email.get(email.lower())
        return self._users.get(uid) if uid else None

    def register(
        self,
        username: str,
        password: str,
        email: str = "",
        display_name: str = "",
        role: UserRole = UserRole.USER,
    ) -> dict[str, Any]:
        """Register a new user. Returns user info + tokens."""
        username = username.strip()
        email = email.strip().lower()

        # Validation
        if not username or len(username) < 3:
            raise AuthError("Username must be at least 3 characters", 400)
        if len(username) > 32:
            raise AuthError("Username must be at most 32 characters", 400)
        if not username.isalnum() and "_" not in username:
            raise AuthError("Username must be alphanumeric (underscores allowed)", 400)
        if len(password) < 6:
            raise AuthError("Password must be at least 6 characters", 400)
        if email and "@" not in email:
            raise AuthError("Invalid email address", 400)

        # Check uniqueness
        if self._get_user_by_username(username):
            raise AuthError("Username already taken", 409)
        if email and self._get_user_by_email(email):
            raise AuthError("Email already registered", 409)

        # Create user
        color_idx = len(self._users) % len(_AVATAR_COLORS)
        user = User(
            username=username,
            email=email,
            password_hash=self.hash_password(password),
            display_name=display_name or username,
            avatar_color=_AVATAR_COLORS[color_idx],
            role=role,
        )

        if self._db_repo:
            self._db_repo.save_user(user)
        else:
            self._users[user.id] = user
            self._by_username[username.lower()] = user.id
            if email:
                self._by_email[email] = user.id

        log.info("user registered: %s (role=%s)", username, role.value)

        access_token = self.create_token(user)
        refresh_token = self.create_refresh_token(user)

        return {
            "user": user.to_dict(),
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": self.token_expiry,
        }

    def login(self, username: str, password: str) -> dict[str, Any]:
        """Authenticate and return tokens."""
        user = self._get_user_by_username(username)
        if not user:
            # Try email
            user = self._get_user_by_email(username)
        if not user:
            raise AuthError("Invalid username or password")
        if not user.is_active:
            raise AuthError("Account is disabled")
        if not self.verify_password(password, user.password_hash):
            raise AuthError("Invalid username or password")

        log.info("user login: %s", user.username)

        access_token = self.create_token(user)
        refresh_token = self.create_refresh_token(user)

        return {
            "user": user.to_dict(),
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": self.token_expiry,
        }

    def get_user(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        return self._get_user_by_id(user_id)

    def list_users(self) -> list[dict[str, Any]]:
        """List all users (admin only)."""
        if self._db_repo:
            return [u.to_dict() for u in self._db_repo.list_users()]
        return [u.to_dict() for u in self._users.values()]

    def create_default_admin(self) -> Optional[User]:
        """Create the default admin account if no users exist."""
        if self._db_repo:
            users = self._db_repo.list_users()
            if users:
                return None
        elif self._users:
            return None

        admin_user = os.getenv("OMNIX_ADMIN_USER", "admin")
        admin_pass = os.getenv("OMNIX_ADMIN_PASSWORD", "omnix-admin")
        admin_email = os.getenv("OMNIX_ADMIN_EMAIL", "admin@omnix.local")

        try:
            result = self.register(
                username=admin_user,
                password=admin_pass,
                email=admin_email,
                display_name="OMNIX Admin",
                role=UserRole.ADMIN,
            )
            log.info("default admin account created: %s", admin_user)
            return User.from_dict(result["user"])
        except AuthError:
            return None

    def get_guest_user(self) -> Optional[User]:
        """Return the guest pseudo-user if guest mode is enabled."""
        if self.guest_mode:
            return GUEST_USER
        return None
