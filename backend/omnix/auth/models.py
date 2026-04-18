"""
User model and role definitions.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"
    VIEWER = "viewer"


@dataclass
class User:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    username: str = ""
    email: str = ""
    password_hash: str = ""
    display_name: str = ""
    avatar_color: str = "#4A90D9"
    role: UserRole = UserRole.USER
    created_at: float = field(default_factory=time.time)
    is_active: bool = True

    def to_dict(self, include_sensitive: bool = False) -> dict[str, Any]:
        """Serialize to dict. Excludes password_hash unless include_sensitive."""
        d = asdict(self)
        d["role"] = self.role.value
        if not include_sensitive:
            d.pop("password_hash", None)
        return d

    def to_public(self) -> dict[str, Any]:
        """Minimal public profile (for collab presence, etc.)."""
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name or self.username,
            "avatar_color": self.avatar_color,
            "role": self.role.value,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> User:
        role = d.get("role", "user")
        if isinstance(role, str):
            role = UserRole(role)
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            username=d.get("username", ""),
            email=d.get("email", ""),
            password_hash=d.get("password_hash", ""),
            display_name=d.get("display_name", ""),
            avatar_color=d.get("avatar_color", "#4A90D9"),
            role=role,
            created_at=d.get("created_at", time.time()),
            is_active=d.get("is_active", True),
        )


# Guest pseudo-user for anonymous access
GUEST_USER = User(
    id="guest",
    username="guest",
    display_name="Guest",
    avatar_color="#999999",
    role=UserRole.VIEWER,
    is_active=True,
)
