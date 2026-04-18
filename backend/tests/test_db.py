"""Tests for the database persistence layer."""

import os
import tempfile
import time
import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from omnix.auth.models import User, UserRole
from omnix.db.migrations import MigrationManager
from omnix.db.repository import InMemoryRepository, SQLiteRepository


@pytest.fixture
def mem_repo():
    return InMemoryRepository()


@pytest.fixture
def sqlite_repo(tmp_path):
    db_path = str(tmp_path / "test.db")
    mgr = MigrationManager(db_path)
    mgr.apply_migrations()
    conn = mgr.connect()
    repo = SQLiteRepository(conn)
    yield repo
    mgr.close()


class TestMigrations:
    def test_fresh_migration(self, tmp_path):
        db_path = str(tmp_path / "fresh.db")
        mgr = MigrationManager(db_path)
        assert mgr.get_current_version() == 0
        final = mgr.apply_migrations()
        assert final >= 1
        mgr.close()

    def test_idempotent_migration(self, tmp_path):
        db_path = str(tmp_path / "idem.db")
        mgr = MigrationManager(db_path)
        v1 = mgr.apply_migrations()
        v2 = mgr.apply_migrations()
        assert v1 == v2
        mgr.close()


class TestInMemoryUsers:
    def test_save_and_get(self, mem_repo):
        user = User(username="alice", email="alice@test.com", role=UserRole.USER)
        mem_repo.save_user(user)
        got = mem_repo.get_user(user.id)
        assert got is not None
        assert got.username == "alice"

    def test_get_by_username(self, mem_repo):
        user = User(username="Bob", email="bob@test.com")
        mem_repo.save_user(user)
        got = mem_repo.get_user_by_username("bob")  # case-insensitive
        assert got is not None
        assert got.username == "Bob"

    def test_list_users(self, mem_repo):
        mem_repo.save_user(User(username="a"))
        mem_repo.save_user(User(username="b"))
        assert len(mem_repo.list_users()) == 2


class TestSQLiteUsers:
    def test_save_and_get(self, sqlite_repo):
        user = User(username="alice", email="alice@test.com",
                     password_hash="hash", role=UserRole.ADMIN)
        sqlite_repo.save_user(user)
        got = sqlite_repo.get_user(user.id)
        assert got is not None
        assert got.username == "alice"
        assert got.role == UserRole.ADMIN

    def test_get_by_email(self, sqlite_repo):
        user = User(username="carol", email="carol@test.com")
        sqlite_repo.save_user(user)
        got = sqlite_repo.get_user_by_email("carol@test.com")
        assert got is not None

    def test_list_users(self, sqlite_repo):
        sqlite_repo.save_user(User(username="x"))
        sqlite_repo.save_user(User(username="y"))
        assert len(sqlite_repo.list_users()) == 2


class TestWorkspaces:
    def _ws(self, **kw):
        defaults = {
            "workspace_id": "ws-1", "device_id": "dev-1",
            "name": "Test WS", "device_type": "drone",
            "color": "#fff", "tags": ["test"], "owner_id": "user-1",
            "created_at": time.time(), "updated_at": time.time(),
            "data": {},
        }
        defaults.update(kw)
        return defaults

    def test_mem_workspace_crud(self, mem_repo):
        ws = self._ws()
        mem_repo.save_workspace(ws)
        got = mem_repo.get_workspace("ws-1")
        assert got is not None
        assert got["name"] == "Test WS"
        assert mem_repo.delete_workspace("ws-1")
        assert mem_repo.get_workspace("ws-1") is None

    def test_sqlite_workspace_crud(self, sqlite_repo):
        ws = self._ws()
        sqlite_repo.save_workspace(ws)
        got = sqlite_repo.get_workspace("ws-1")
        assert got is not None
        assert got["name"] == "Test WS"
        assert got["tags"] == ["test"]


class TestBehaviorTrees:
    def _tree(self, **kw):
        defaults = {
            "tree_id": "bt-1", "device_id": "dev-1",
            "name": "Test Tree", "description": "A test",
            "root": {"type": "Sequence", "children": []},
            "owner_id": "user-1",
            "created_at": time.time(), "updated_at": time.time(),
        }
        defaults.update(kw)
        return defaults

    def test_mem_tree_crud(self, mem_repo):
        tree = self._tree()
        mem_repo.save_tree(tree)
        got = mem_repo.get_tree("bt-1")
        assert got is not None
        assert mem_repo.delete_tree("bt-1")

    def test_sqlite_tree_crud(self, sqlite_repo):
        tree = self._tree()
        sqlite_repo.save_tree(tree)
        got = sqlite_repo.get_tree("bt-1")
        assert got is not None
        assert got["root"]["type"] == "Sequence"
        trees = sqlite_repo.get_trees_by_device("dev-1")
        assert len(trees) == 1


class TestSecurityValidation:
    def test_sanitize_string(self):
        from omnix.security.validation import sanitize_string
        assert sanitize_string("  hello  ") == "hello"
        assert sanitize_string("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"
        assert len(sanitize_string("x" * 2000, max_length=100)) == 100

    def test_validate_input(self):
        from omnix.security.validation import validate_input
        assert validate_input("valid_user", "username")
        assert not validate_input("ab", "username")  # too short
        assert not validate_input("has spaces", "username")
        assert validate_input("test@example.com", "email")
        assert not validate_input("not-an-email", "email")
