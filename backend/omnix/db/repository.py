"""
Data access layer abstracting storage behind a Repository interface.

Two implementations:
  - InMemoryRepository: wraps the existing in-memory dicts (dev/demo)
  - SQLiteRepository: persists to SQLite (production)

Both implement the same interface so the rest of the code doesn't care.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Optional

from omnix.logging_setup import get_logger
from omnix.auth.models import User, UserRole

log = get_logger("omnix.db.repository")


class Repository(ABC):
    """Abstract data access interface."""

    # ── Users ──
    @abstractmethod
    def save_user(self, user: User) -> None: ...
    @abstractmethod
    def get_user(self, user_id: str) -> Optional[User]: ...
    @abstractmethod
    def get_user_by_username(self, username: str) -> Optional[User]: ...
    @abstractmethod
    def get_user_by_email(self, email: str) -> Optional[User]: ...
    @abstractmethod
    def list_users(self) -> list[User]: ...

    # ── Workspaces ──
    @abstractmethod
    def save_workspace(self, workspace: dict) -> None: ...
    @abstractmethod
    def get_workspace(self, workspace_id: str) -> Optional[dict]: ...
    @abstractmethod
    def get_workspaces_by_device(self, device_id: str) -> list[dict]: ...
    @abstractmethod
    def list_workspaces(self, owner_id: str = "") -> list[dict]: ...
    @abstractmethod
    def delete_workspace(self, workspace_id: str) -> bool: ...

    # ── Behavior Trees ──
    @abstractmethod
    def save_tree(self, tree: dict) -> None: ...
    @abstractmethod
    def get_tree(self, tree_id: str) -> Optional[dict]: ...
    @abstractmethod
    def get_trees_by_device(self, device_id: str) -> list[dict]: ...
    @abstractmethod
    def delete_tree(self, tree_id: str) -> bool: ...

    # ── Marketplace Items ──
    @abstractmethod
    def save_marketplace_item(self, item: dict) -> None: ...
    @abstractmethod
    def get_marketplace_item(self, item_id: str) -> Optional[dict]: ...
    @abstractmethod
    def search_marketplace(self, query: str = "", item_type: str = "",
                           tags: list[str] | None = None, page: int = 1,
                           page_size: int = 20) -> dict: ...

    # ── Reviews ──
    @abstractmethod
    def save_review(self, review: dict) -> None: ...
    @abstractmethod
    def get_reviews(self, item_id: str) -> list[dict]: ...

    # ── Iterations ──
    @abstractmethod
    def save_iteration(self, iteration: dict) -> None: ...
    @abstractmethod
    def get_iterations(self, workspace_id: str) -> list[dict]: ...


class InMemoryRepository(Repository):
    """In-memory implementation that wraps plain dicts. Zero dependencies."""

    def __init__(self):
        self._users: dict[str, User] = {}
        self._users_by_username: dict[str, str] = {}
        self._users_by_email: dict[str, str] = {}
        self._workspaces: dict[str, dict] = {}
        self._trees: dict[str, dict] = {}
        self._marketplace: dict[str, dict] = {}
        self._reviews: dict[str, list[dict]] = {}
        self._iterations: dict[str, list[dict]] = {}

    # ── Users ──
    def save_user(self, user: User) -> None:
        self._users[user.id] = user
        self._users_by_username[user.username.lower()] = user.id
        if user.email:
            self._users_by_email[user.email.lower()] = user.id

    def get_user(self, user_id: str) -> Optional[User]:
        return self._users.get(user_id)

    def get_user_by_username(self, username: str) -> Optional[User]:
        uid = self._users_by_username.get(username.lower())
        return self._users.get(uid) if uid else None

    def get_user_by_email(self, email: str) -> Optional[User]:
        uid = self._users_by_email.get(email.lower())
        return self._users.get(uid) if uid else None

    def list_users(self) -> list[User]:
        return list(self._users.values())

    # ── Workspaces ──
    def save_workspace(self, workspace: dict) -> None:
        self._workspaces[workspace["workspace_id"]] = workspace

    def get_workspace(self, workspace_id: str) -> Optional[dict]:
        return self._workspaces.get(workspace_id)

    def get_workspaces_by_device(self, device_id: str) -> list[dict]:
        return [w for w in self._workspaces.values() if w.get("device_id") == device_id]

    def list_workspaces(self, owner_id: str = "") -> list[dict]:
        if owner_id:
            return [w for w in self._workspaces.values() if w.get("owner_id") == owner_id]
        return list(self._workspaces.values())

    def delete_workspace(self, workspace_id: str) -> bool:
        return self._workspaces.pop(workspace_id, None) is not None

    # ── Behavior Trees ──
    def save_tree(self, tree: dict) -> None:
        self._trees[tree["tree_id"]] = tree

    def get_tree(self, tree_id: str) -> Optional[dict]:
        return self._trees.get(tree_id)

    def get_trees_by_device(self, device_id: str) -> list[dict]:
        return [t for t in self._trees.values() if t.get("device_id") == device_id]

    def delete_tree(self, tree_id: str) -> bool:
        return self._trees.pop(tree_id, None) is not None

    # ── Marketplace ──
    def save_marketplace_item(self, item: dict) -> None:
        self._marketplace[item["item_id"]] = item

    def get_marketplace_item(self, item_id: str) -> Optional[dict]:
        return self._marketplace.get(item_id)

    def search_marketplace(self, query: str = "", item_type: str = "",
                           tags: list[str] | None = None, page: int = 1,
                           page_size: int = 20) -> dict:
        results = list(self._marketplace.values())
        if query:
            q = query.lower()
            results = [i for i in results
                       if q in i.get("name", "").lower() or q in i.get("description", "").lower()]
        if item_type:
            results = [i for i in results if i.get("item_type") == item_type]
        if tags:
            tag_set = set(t.lower() for t in tags)
            results = [i for i in results
                       if tag_set & set(t.lower() for t in i.get("tags", []))]
        total = len(results)
        start = (page - 1) * page_size
        return {"items": results[start:start + page_size], "total": total, "page": page}

    # ── Reviews ──
    def save_review(self, review: dict) -> None:
        item_id = review["item_id"]
        self._reviews.setdefault(item_id, []).append(review)

    def get_reviews(self, item_id: str) -> list[dict]:
        return self._reviews.get(item_id, [])

    # ── Iterations ──
    def save_iteration(self, iteration: dict) -> None:
        ws_id = iteration["workspace_id"]
        self._iterations.setdefault(ws_id, []).append(iteration)

    def get_iterations(self, workspace_id: str) -> list[dict]:
        return self._iterations.get(workspace_id, [])


class SQLiteRepository(Repository):
    """SQLite-backed implementation for production persistence."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def _commit(self) -> None:
        self._conn.commit()

    # ── Users ──
    def save_user(self, user: User) -> None:
        self._execute(
            """INSERT OR REPLACE INTO users
               (id, username, email, password_hash, display_name, avatar_color, role, created_at, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user.id, user.username, user.email, user.password_hash,
             user.display_name, user.avatar_color, user.role.value,
             user.created_at, int(user.is_active)),
        )
        self._commit()

    def get_user(self, user_id: str) -> Optional[User]:
        row = self._execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._row_to_user(row) if row else None

    def get_user_by_username(self, username: str) -> Optional[User]:
        row = self._execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username,)
        ).fetchone()
        return self._row_to_user(row) if row else None

    def get_user_by_email(self, email: str) -> Optional[User]:
        row = self._execute(
            "SELECT * FROM users WHERE LOWER(email) = LOWER(?)", (email,)
        ).fetchone()
        return self._row_to_user(row) if row else None

    def list_users(self) -> list[User]:
        rows = self._execute("SELECT * FROM users ORDER BY created_at").fetchall()
        return [self._row_to_user(r) for r in rows]

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            username=row["username"],
            email=row["email"],
            password_hash=row["password_hash"],
            display_name=row["display_name"],
            avatar_color=row["avatar_color"],
            role=UserRole(row["role"]),
            created_at=row["created_at"],
            is_active=bool(row["is_active"]),
        )

    # ── Workspaces ──
    def save_workspace(self, workspace: dict) -> None:
        tags = json.dumps(workspace.get("tags", []))
        data = json.dumps(workspace.get("data", {}))
        self._execute(
            """INSERT OR REPLACE INTO workspaces
               (workspace_id, device_id, name, device_type, color, tags, owner_id, created_at, updated_at, data_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (workspace["workspace_id"], workspace["device_id"], workspace.get("name", ""),
             workspace.get("device_type", ""), workspace.get("color", "#4A90D9"),
             tags, workspace.get("owner_id", ""),
             workspace.get("created_at", time.time()), workspace.get("updated_at", time.time()),
             data),
        )
        self._commit()

    def get_workspace(self, workspace_id: str) -> Optional[dict]:
        row = self._execute("SELECT * FROM workspaces WHERE workspace_id = ?", (workspace_id,)).fetchone()
        return self._row_to_workspace(row) if row else None

    def get_workspaces_by_device(self, device_id: str) -> list[dict]:
        rows = self._execute("SELECT * FROM workspaces WHERE device_id = ?", (device_id,)).fetchall()
        return [self._row_to_workspace(r) for r in rows]

    def list_workspaces(self, owner_id: str = "") -> list[dict]:
        if owner_id:
            rows = self._execute("SELECT * FROM workspaces WHERE owner_id = ? ORDER BY updated_at DESC", (owner_id,)).fetchall()
        else:
            rows = self._execute("SELECT * FROM workspaces ORDER BY updated_at DESC").fetchall()
        return [self._row_to_workspace(r) for r in rows]

    def delete_workspace(self, workspace_id: str) -> bool:
        cursor = self._execute("DELETE FROM workspaces WHERE workspace_id = ?", (workspace_id,))
        self._commit()
        return cursor.rowcount > 0

    @staticmethod
    def _row_to_workspace(row: sqlite3.Row) -> dict:
        return {
            "workspace_id": row["workspace_id"],
            "device_id": row["device_id"],
            "name": row["name"],
            "device_type": row["device_type"],
            "color": row["color"],
            "tags": json.loads(row["tags"]),
            "owner_id": row["owner_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "data": json.loads(row["data_json"]),
        }

    # ── Behavior Trees ──
    def save_tree(self, tree: dict) -> None:
        root = json.dumps(tree.get("root", {}))
        self._execute(
            """INSERT OR REPLACE INTO behavior_trees
               (tree_id, device_id, name, description, root_json, owner_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (tree["tree_id"], tree["device_id"], tree.get("name", ""),
             tree.get("description", ""), root, tree.get("owner_id", ""),
             tree.get("created_at", time.time()), tree.get("updated_at", time.time())),
        )
        self._commit()

    def get_tree(self, tree_id: str) -> Optional[dict]:
        row = self._execute("SELECT * FROM behavior_trees WHERE tree_id = ?", (tree_id,)).fetchone()
        if not row:
            return None
        return {
            "tree_id": row["tree_id"], "device_id": row["device_id"],
            "name": row["name"], "description": row["description"],
            "root": json.loads(row["root_json"]), "owner_id": row["owner_id"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def get_trees_by_device(self, device_id: str) -> list[dict]:
        rows = self._execute("SELECT * FROM behavior_trees WHERE device_id = ?", (device_id,)).fetchall()
        return [{
            "tree_id": r["tree_id"], "device_id": r["device_id"],
            "name": r["name"], "description": r["description"],
            "root": json.loads(r["root_json"]), "owner_id": r["owner_id"],
            "created_at": r["created_at"], "updated_at": r["updated_at"],
        } for r in rows]

    def delete_tree(self, tree_id: str) -> bool:
        cursor = self._execute("DELETE FROM behavior_trees WHERE tree_id = ?", (tree_id,))
        self._commit()
        return cursor.rowcount > 0

    # ── Marketplace Items ──
    def save_marketplace_item(self, item: dict) -> None:
        tags = json.dumps(item.get("tags", []))
        compat = json.dumps(item.get("compat", []))
        data = json.dumps(item.get("data", {}))
        self._execute(
            """INSERT OR REPLACE INTO marketplace_items
               (item_id, item_type, name, description, author, author_id, version,
                tags, compat, data_json, downloads, rating_sum, rating_count, published_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item["item_id"], item.get("item_type", ""), item.get("name", ""),
             item.get("description", ""), item.get("author", ""), item.get("author_id", ""),
             item.get("version", "1.0.0"), tags, compat, data,
             item.get("downloads", 0), item.get("rating_sum", 0),
             item.get("rating_count", 0),
             item.get("published_at", time.time()), item.get("updated_at", time.time())),
        )
        self._commit()

    def get_marketplace_item(self, item_id: str) -> Optional[dict]:
        row = self._execute("SELECT * FROM marketplace_items WHERE item_id = ?", (item_id,)).fetchone()
        if not row:
            return None
        return self._row_to_marketplace(row)

    def search_marketplace(self, query: str = "", item_type: str = "",
                           tags: list[str] | None = None, page: int = 1,
                           page_size: int = 20) -> dict:
        conditions = []
        params: list = []

        if query:
            conditions.append("(LOWER(name) LIKE ? OR LOWER(description) LIKE ?)")
            q = f"%{query.lower()}%"
            params.extend([q, q])
        if item_type:
            conditions.append("item_type = ?")
            params.append(item_type)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        count_row = self._execute(f"SELECT COUNT(*) FROM marketplace_items {where}", tuple(params)).fetchone()
        total = count_row[0] if count_row else 0

        offset = (page - 1) * page_size
        rows = self._execute(
            f"SELECT * FROM marketplace_items {where} ORDER BY published_at DESC LIMIT ? OFFSET ?",
            tuple(params) + (page_size, offset),
        ).fetchall()

        items = [self._row_to_marketplace(r) for r in rows]

        # Filter by tags in Python (SQLite JSON handling is limited)
        if tags:
            tag_set = set(t.lower() for t in tags)
            items = [i for i in items if tag_set & set(t.lower() for t in i.get("tags", []))]

        return {"items": items, "total": total, "page": page}

    @staticmethod
    def _row_to_marketplace(row: sqlite3.Row) -> dict:
        return {
            "item_id": row["item_id"], "item_type": row["item_type"],
            "name": row["name"], "description": row["description"],
            "author": row["author"], "author_id": row["author_id"],
            "version": row["version"],
            "tags": json.loads(row["tags"]), "compat": json.loads(row["compat"]),
            "data": json.loads(row["data_json"]),
            "downloads": row["downloads"],
            "rating_sum": row["rating_sum"], "rating_count": row["rating_count"],
            "published_at": row["published_at"], "updated_at": row["updated_at"],
        }

    # ── Reviews ──
    def save_review(self, review: dict) -> None:
        self._execute(
            """INSERT INTO reviews (review_id, item_id, author, author_id, rating, comment, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (review.get("review_id", str(uuid.uuid4())[:8]), review["item_id"],
             review.get("author", ""), review.get("author_id", ""),
             review.get("rating", 5), review.get("comment", ""),
             review.get("created_at", time.time())),
        )
        self._commit()

    def get_reviews(self, item_id: str) -> list[dict]:
        rows = self._execute(
            "SELECT * FROM reviews WHERE item_id = ? ORDER BY created_at DESC", (item_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Iterations ──
    def save_iteration(self, iteration: dict) -> None:
        self._execute(
            """INSERT OR REPLACE INTO iterations
               (iteration_id, workspace_id, device_id, name, scenario, score,
                metrics_json, physics_json, frames_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (iteration["iteration_id"], iteration["workspace_id"],
             iteration.get("device_id", ""), iteration.get("name", ""),
             iteration.get("scenario", ""), iteration.get("score"),
             json.dumps(iteration.get("metrics", {})),
             json.dumps(iteration.get("physics", {})),
             json.dumps(iteration.get("frames", [])),
             iteration.get("created_at", time.time())),
        )
        self._commit()

    def get_iterations(self, workspace_id: str) -> list[dict]:
        rows = self._execute(
            "SELECT * FROM iterations WHERE workspace_id = ? ORDER BY created_at DESC",
            (workspace_id,),
        ).fetchall()
        return [{
            "iteration_id": r["iteration_id"], "workspace_id": r["workspace_id"],
            "device_id": r["device_id"], "name": r["name"], "scenario": r["scenario"],
            "score": r["score"], "metrics": json.loads(r["metrics_json"]),
            "physics": json.loads(r["physics_json"]),
            "frames": json.loads(r["frames_json"]), "created_at": r["created_at"],
        } for r in rows]
