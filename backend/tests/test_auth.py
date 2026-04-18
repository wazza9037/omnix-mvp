"""Tests for the auth module — registration, login, JWT, permissions."""

import time
import pytest

# Ensure backend is on the path
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from omnix.auth.models import User, UserRole, GUEST_USER
from omnix.auth.auth import AuthManager, AuthError
from omnix.auth.permissions import (
    Permission, check_permission, require_permission,
    PermissionError as AuthPermissionError, ROLE_PERMISSIONS,
)


@pytest.fixture
def auth():
    return AuthManager(secret_key="test-secret-key", guest_mode=True)


class TestPasswordHashing:
    def test_hash_and_verify(self, auth):
        hashed = auth.hash_password("my-password")
        assert auth.verify_password("my-password", hashed)
        assert not auth.verify_password("wrong-password", hashed)

    def test_different_salts_produce_different_hashes(self, auth):
        h1 = auth.hash_password("same-password")
        h2 = auth.hash_password("same-password")
        assert h1 != h2  # Different salts

    def test_verify_bad_hash_format(self, auth):
        assert not auth.verify_password("x", "not-a-valid-hash")


class TestJWT:
    def test_create_and_validate_token(self, auth):
        user = User(username="alice", role=UserRole.USER)
        token = auth.create_token(user)
        payload = auth.validate_token(token)
        assert payload is not None
        assert payload["sub"] == user.id
        assert payload["username"] == "alice"
        assert payload["role"] == "user"

    def test_expired_token(self, auth):
        auth_short = AuthManager(secret_key="test", token_expiry_seconds=-1)
        user = User(username="bob")
        token = auth_short.create_token(user)
        assert auth_short.validate_token(token) is None

    def test_invalid_token(self, auth):
        assert auth.validate_token("not.a.token") is None
        assert auth.validate_token("") is None

    def test_tampered_token(self, auth):
        user = User(username="carol")
        token = auth.create_token(user)
        tampered = token[:-4] + "XXXX"
        assert auth.validate_token(tampered) is None


class TestRegistration:
    def test_register_success(self, auth):
        result = auth.register("testuser", "password123", email="test@example.com")
        assert "user" in result
        assert "access_token" in result
        assert "refresh_token" in result
        assert result["user"]["username"] == "testuser"

    def test_register_short_username(self, auth):
        with pytest.raises(AuthError, match="at least 3"):
            auth.register("ab", "password123")

    def test_register_short_password(self, auth):
        with pytest.raises(AuthError, match="at least 6"):
            auth.register("validuser", "12345")

    def test_register_duplicate_username(self, auth):
        auth.register("uniqueuser", "password123")
        with pytest.raises(AuthError, match="already taken"):
            auth.register("uniqueuser", "password456")

    def test_register_duplicate_email(self, auth):
        auth.register("user1", "password123", email="same@test.com")
        with pytest.raises(AuthError, match="already registered"):
            auth.register("user2", "password456", email="same@test.com")


class TestLogin:
    def test_login_success(self, auth):
        auth.register("loginuser", "mypassword")
        result = auth.login("loginuser", "mypassword")
        assert result["user"]["username"] == "loginuser"
        assert "access_token" in result

    def test_login_wrong_password(self, auth):
        auth.register("wrongpw", "correctpassword")
        with pytest.raises(AuthError, match="Invalid"):
            auth.login("wrongpw", "wrongpassword")

    def test_login_unknown_user(self, auth):
        with pytest.raises(AuthError, match="Invalid"):
            auth.login("nonexistent", "password")

    def test_login_by_email(self, auth):
        auth.register("emailuser", "password123", email="login@test.com")
        result = auth.login("login@test.com", "password123")
        assert result["user"]["username"] == "emailuser"


class TestRefreshToken:
    def test_refresh_token_flow(self, auth):
        reg = auth.register("refreshuser", "password123")
        refresh = reg["refresh_token"]
        result = auth.refresh_access_token(refresh)
        assert result is not None
        assert "access_token" in result
        assert "refresh_token" in result
        # Old refresh token should be invalidated
        assert auth.refresh_access_token(refresh) is None

    def test_invalid_refresh_token(self, auth):
        assert auth.refresh_access_token("fake-token") is None


class TestDefaultAdmin:
    def test_creates_admin_on_empty_store(self, auth):
        admin = auth.create_default_admin()
        assert admin is not None
        assert admin.role == UserRole.ADMIN

    def test_skips_if_users_exist(self, auth):
        auth.register("existing", "password123")
        admin = auth.create_default_admin()
        assert admin is None


class TestGuestMode:
    def test_guest_user_returned(self, auth):
        guest = auth.get_guest_user()
        assert guest is not None
        assert guest.id == "guest"
        assert guest.role == UserRole.VIEWER

    def test_guest_disabled(self):
        auth_no_guest = AuthManager(secret_key="test", guest_mode=False)
        assert auth_no_guest.get_guest_user() is None


class TestPermissions:
    def test_admin_has_all_permissions(self):
        admin = User(role=UserRole.ADMIN)
        for perm in Permission:
            assert check_permission(admin, perm)

    def test_viewer_read_only(self):
        viewer = User(role=UserRole.VIEWER)
        assert check_permission(viewer, Permission.DEVICE_VIEW)
        assert check_permission(viewer, Permission.WORKSPACE_VIEW)
        assert not check_permission(viewer, Permission.DEVICE_COMMAND)
        assert not check_permission(viewer, Permission.WORKSPACE_EDIT)

    def test_user_can_modify(self):
        user = User(role=UserRole.USER)
        assert check_permission(user, Permission.DEVICE_COMMAND)
        assert check_permission(user, Permission.WORKSPACE_EDIT)
        assert not check_permission(user, Permission.ADMIN_USERS)

    def test_require_permission_raises(self):
        viewer = User(role=UserRole.VIEWER)
        with pytest.raises(AuthPermissionError):
            require_permission(viewer, Permission.DEVICE_COMMAND)

    def test_none_user_denied(self):
        assert not check_permission(None, Permission.DEVICE_VIEW)


class TestUserModel:
    def test_to_dict_excludes_password(self):
        user = User(username="test", password_hash="secret")
        d = user.to_dict()
        assert "password_hash" not in d
        assert d["username"] == "test"

    def test_to_dict_includes_sensitive(self):
        user = User(username="test", password_hash="secret")
        d = user.to_dict(include_sensitive=True)
        assert d["password_hash"] == "secret"

    def test_from_dict(self):
        d = {"username": "fromdict", "role": "admin", "email": "a@b.com"}
        user = User.from_dict(d)
        assert user.username == "fromdict"
        assert user.role == UserRole.ADMIN

    def test_guest_user_constants(self):
        assert GUEST_USER.id == "guest"
        assert GUEST_USER.role == UserRole.VIEWER
