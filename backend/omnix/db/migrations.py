"""
Schema versioning with automatic migration on startup.

On each server boot, MigrationManager:
  1. Checks the current schema_version in the DB
  2. Applies any pending migrations in order
  3. Updates the schema_version table

Migrations are defined as a list of (version, description, sql_statements).
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from omnix.logging_setup import get_logger
from .models import DB_TABLES, DB_INDEXES, SCHEMA_VERSION

log = get_logger("omnix.db.migrations")


# Each migration is: (version, description, list_of_sql_statements)
MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (
        1,
        "Initial schema — users, workspaces, devices, iterations, marketplace, collab, BT, builds",
        [sql for sql in DB_TABLES.values()] + DB_INDEXES,
    ),
]


class MigrationManager:
    """Manages database schema versioning and migrations."""

    def __init__(self, db_path: str = "omnix.db"):
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        """Get or create the SQLite connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def get_current_version(self) -> int:
        """Get the current schema version from the database."""
        conn = self.connect()
        try:
            # Check if schema_version table exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            )
            if cursor.fetchone() is None:
                return 0

            cursor = conn.execute("SELECT MAX(version) FROM schema_version")
            row = cursor.fetchone()
            return row[0] if row and row[0] is not None else 0
        except sqlite3.Error:
            return 0

    def apply_migrations(self) -> int:
        """Apply all pending migrations. Returns the final schema version."""
        conn = self.connect()
        current = self.get_current_version()

        if current >= SCHEMA_VERSION:
            log.info("database schema up-to-date (v%d)", current)
            return current

        log.info("database at v%d, migrating to v%d...", current, SCHEMA_VERSION)

        for version, description, statements in MIGRATIONS:
            if version <= current:
                continue

            log.info("applying migration v%d: %s", version, description)

            try:
                for sql in statements:
                    conn.execute(sql)

                conn.execute(
                    "INSERT INTO schema_version (version, applied_at, description) VALUES (?, ?, ?)",
                    (version, time.time(), description),
                )
                conn.commit()
                log.info("migration v%d applied successfully", version)

            except sqlite3.Error as e:
                conn.rollback()
                log.error("migration v%d failed: %s", version, e)
                raise

        final = self.get_current_version()
        log.info("database migrated to v%d", final)
        return final

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
