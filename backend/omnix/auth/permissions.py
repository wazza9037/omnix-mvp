"""
Role-based access control (RBAC) for OMNIX.

Permissions:
  - admin: full access to everything
  - user: CRUD own workspaces, publish to marketplace, run devices
  - viewer: read-only access (can view but not modify)
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from .models import User, UserRole, GUEST_USER


class Permission(str, Enum):
    # Device operations
    DEVICE_VIEW = "device:view"
    DEVICE_COMMAND = "device:command"
    DEVICE_CREATE = "device:create"
    DEVICE_DELETE = "device:delete"

    # Workspace operations
    WORKSPACE_VIEW = "workspace:view"
    WORKSPACE_EDIT = "workspace:edit"
    WORKSPACE_CREATE = "workspace:create"
    WORKSPACE_DELETE = "workspace:delete"

    # Simulation
    SIM_RUN = "sim:run"
    SIM_VIEW = "sim:view"

    # Behavior trees
    BT_VIEW = "bt:view"
    BT_EDIT = "bt:edit"
    BT_EXECUTE = "bt:execute"

    # Marketplace
    MARKETPLACE_VIEW = "marketplace:view"
    MARKETPLACE_PUBLISH = "marketplace:publish"
    MARKETPLACE_INSTALL = "marketplace:install"
    MARKETPLACE_REVIEW = "marketplace:review"

    # Collaboration
    COLLAB_JOIN = "collab:join"
    COLLAB_CREATE = "collab:create"
    COLLAB_EDIT = "collab:edit"

    # Custom builder
    BUILD_VIEW = "build:view"
    BUILD_EDIT = "build:edit"

    # NLP commands
    NLP_EXECUTE = "nlp:execute"

    # Digital twin
    TWIN_VIEW = "twin:view"
    TWIN_CREATE = "twin:create"

    # Admin
    ADMIN_USERS = "admin:users"
    ADMIN_SETTINGS = "admin:settings"
    ADMIN_METRICS = "admin:metrics"


# Permission sets per role
ROLE_PERMISSIONS: dict[UserRole, set[Permission]] = {
    UserRole.ADMIN: set(Permission),  # All permissions

    UserRole.USER: {
        Permission.DEVICE_VIEW,
        Permission.DEVICE_COMMAND,
        Permission.DEVICE_CREATE,
        Permission.DEVICE_DELETE,
        Permission.WORKSPACE_VIEW,
        Permission.WORKSPACE_EDIT,
        Permission.WORKSPACE_CREATE,
        Permission.WORKSPACE_DELETE,
        Permission.SIM_RUN,
        Permission.SIM_VIEW,
        Permission.BT_VIEW,
        Permission.BT_EDIT,
        Permission.BT_EXECUTE,
        Permission.MARKETPLACE_VIEW,
        Permission.MARKETPLACE_PUBLISH,
        Permission.MARKETPLACE_INSTALL,
        Permission.MARKETPLACE_REVIEW,
        Permission.COLLAB_JOIN,
        Permission.COLLAB_CREATE,
        Permission.COLLAB_EDIT,
        Permission.BUILD_VIEW,
        Permission.BUILD_EDIT,
        Permission.NLP_EXECUTE,
        Permission.TWIN_VIEW,
        Permission.TWIN_CREATE,
    },

    UserRole.VIEWER: {
        Permission.DEVICE_VIEW,
        Permission.WORKSPACE_VIEW,
        Permission.SIM_VIEW,
        Permission.BT_VIEW,
        Permission.MARKETPLACE_VIEW,
        Permission.COLLAB_JOIN,
        Permission.BUILD_VIEW,
        Permission.TWIN_VIEW,
    },
}


def check_permission(user: Optional[User], permission: Permission) -> bool:
    """Check if a user has a specific permission."""
    if user is None:
        return False
    perms = ROLE_PERMISSIONS.get(user.role, set())
    return permission in perms


def require_permission(user: Optional[User], permission: Permission) -> None:
    """Raise if the user lacks the required permission."""
    if not check_permission(user, permission):
        role = user.role.value if user else "none"
        raise PermissionError(
            f"Permission denied: {permission.value} requires higher privileges "
            f"(current role: {role})"
        )


class PermissionError(Exception):
    """Raised when a user lacks required permissions."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
        self.status = 403
