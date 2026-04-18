"""
Authentication & authorization for OMNIX.

JWT-based auth with role-based access control. Supports:
  - Username/password registration & login
  - JWT access tokens with configurable expiry
  - Role-based permissions (admin, user, viewer)
  - Guest mode for anonymous read-only access
"""

from .models import User, UserRole
from .auth import AuthManager
from .middleware import AuthMiddleware, require_auth, get_current_user
from .permissions import Permission, check_permission, ROLE_PERMISSIONS

__all__ = [
    "User", "UserRole",
    "AuthManager",
    "AuthMiddleware", "require_auth", "get_current_user",
    "Permission", "check_permission", "ROLE_PERMISSIONS",
]
