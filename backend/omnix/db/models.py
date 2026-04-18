"""
Database schema definitions.

Each table is described as a dict with its columns and constraints.
These definitions drive both migration and query generation.
"""

from __future__ import annotations

# Schema version — bump when adding/altering tables
SCHEMA_VERSION = 1

DB_TABLES: dict[str, str] = {
    "schema_version": """
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            applied_at  REAL NOT NULL DEFAULT (strftime('%s', 'now')),
            description TEXT NOT NULL DEFAULT ''
        )
    """,

    "users": """
        CREATE TABLE IF NOT EXISTS users (
            id            TEXT PRIMARY KEY,
            username      TEXT NOT NULL UNIQUE,
            email         TEXT NOT NULL DEFAULT '',
            password_hash TEXT NOT NULL DEFAULT '',
            display_name  TEXT NOT NULL DEFAULT '',
            avatar_color  TEXT NOT NULL DEFAULT '#4A90D9',
            role          TEXT NOT NULL DEFAULT 'user',
            created_at    REAL NOT NULL,
            is_active     INTEGER NOT NULL DEFAULT 1
        )
    """,

    "workspaces": """
        CREATE TABLE IF NOT EXISTS workspaces (
            workspace_id  TEXT PRIMARY KEY,
            device_id     TEXT NOT NULL,
            name          TEXT NOT NULL DEFAULT '',
            device_type   TEXT NOT NULL DEFAULT '',
            color         TEXT NOT NULL DEFAULT '#4A90D9',
            tags          TEXT NOT NULL DEFAULT '[]',
            owner_id      TEXT NOT NULL DEFAULT '',
            created_at    REAL NOT NULL,
            updated_at    REAL NOT NULL,
            data_json     TEXT NOT NULL DEFAULT '{}'
        )
    """,

    "devices": """
        CREATE TABLE IF NOT EXISTS devices (
            device_id    TEXT PRIMARY KEY,
            device_type  TEXT NOT NULL DEFAULT '',
            name         TEXT NOT NULL DEFAULT '',
            owner_id     TEXT NOT NULL DEFAULT '',
            config_json  TEXT NOT NULL DEFAULT '{}',
            created_at   REAL NOT NULL,
            updated_at   REAL NOT NULL
        )
    """,

    "iterations": """
        CREATE TABLE IF NOT EXISTS iterations (
            iteration_id  TEXT PRIMARY KEY,
            workspace_id  TEXT NOT NULL,
            device_id     TEXT NOT NULL,
            name          TEXT NOT NULL DEFAULT '',
            scenario      TEXT NOT NULL DEFAULT '',
            score         REAL,
            metrics_json  TEXT NOT NULL DEFAULT '{}',
            physics_json  TEXT NOT NULL DEFAULT '{}',
            frames_json   TEXT NOT NULL DEFAULT '[]',
            created_at    REAL NOT NULL,
            FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id)
        )
    """,

    "marketplace_items": """
        CREATE TABLE IF NOT EXISTS marketplace_items (
            item_id       TEXT PRIMARY KEY,
            item_type     TEXT NOT NULL DEFAULT '',
            name          TEXT NOT NULL DEFAULT '',
            description   TEXT NOT NULL DEFAULT '',
            author        TEXT NOT NULL DEFAULT '',
            author_id     TEXT NOT NULL DEFAULT '',
            version       TEXT NOT NULL DEFAULT '1.0.0',
            tags          TEXT NOT NULL DEFAULT '[]',
            compat        TEXT NOT NULL DEFAULT '[]',
            data_json     TEXT NOT NULL DEFAULT '{}',
            downloads     INTEGER NOT NULL DEFAULT 0,
            rating_sum    REAL NOT NULL DEFAULT 0,
            rating_count  INTEGER NOT NULL DEFAULT 0,
            published_at  REAL NOT NULL,
            updated_at    REAL NOT NULL
        )
    """,

    "reviews": """
        CREATE TABLE IF NOT EXISTS reviews (
            review_id     TEXT PRIMARY KEY,
            item_id       TEXT NOT NULL,
            author        TEXT NOT NULL DEFAULT '',
            author_id     TEXT NOT NULL DEFAULT '',
            rating        INTEGER NOT NULL DEFAULT 5,
            comment       TEXT NOT NULL DEFAULT '',
            created_at    REAL NOT NULL,
            FOREIGN KEY (item_id) REFERENCES marketplace_items(item_id)
        )
    """,

    "collab_sessions": """
        CREATE TABLE IF NOT EXISTS collab_sessions (
            session_id    TEXT PRIMARY KEY,
            owner_id      TEXT NOT NULL,
            device_id     TEXT NOT NULL DEFAULT '',
            share_code    TEXT NOT NULL UNIQUE,
            created_at    REAL NOT NULL,
            ended_at      REAL,
            data_json     TEXT NOT NULL DEFAULT '{}'
        )
    """,

    "behavior_trees": """
        CREATE TABLE IF NOT EXISTS behavior_trees (
            tree_id       TEXT PRIMARY KEY,
            device_id     TEXT NOT NULL,
            name          TEXT NOT NULL DEFAULT '',
            description   TEXT NOT NULL DEFAULT '',
            root_json     TEXT NOT NULL DEFAULT '{}',
            owner_id      TEXT NOT NULL DEFAULT '',
            created_at    REAL NOT NULL,
            updated_at    REAL NOT NULL
        )
    """,

    "custom_builds": """
        CREATE TABLE IF NOT EXISTS custom_builds (
            build_id      TEXT PRIMARY KEY,
            name          TEXT NOT NULL DEFAULT '',
            device_type   TEXT NOT NULL DEFAULT 'custom',
            parts_json    TEXT NOT NULL DEFAULT '[]',
            owner_id      TEXT NOT NULL DEFAULT '',
            created_at    REAL NOT NULL,
            updated_at    REAL NOT NULL
        )
    """,
}

# Indexes for common queries
DB_INDEXES: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)",
    "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
    "CREATE INDEX IF NOT EXISTS idx_workspaces_device ON workspaces(device_id)",
    "CREATE INDEX IF NOT EXISTS idx_workspaces_owner ON workspaces(owner_id)",
    "CREATE INDEX IF NOT EXISTS idx_iterations_workspace ON iterations(workspace_id)",
    "CREATE INDEX IF NOT EXISTS idx_marketplace_type ON marketplace_items(item_type)",
    "CREATE INDEX IF NOT EXISTS idx_marketplace_author ON marketplace_items(author_id)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_item ON reviews(item_id)",
    "CREATE INDEX IF NOT EXISTS idx_bt_device ON behavior_trees(device_id)",
    "CREATE INDEX IF NOT EXISTS idx_builds_owner ON custom_builds(owner_id)",
]
