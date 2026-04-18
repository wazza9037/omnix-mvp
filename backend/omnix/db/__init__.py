"""
Database persistence layer for OMNIX.

SQLite by default, designed for easy swap to Postgres.
Falls back to in-memory mode for development/demo.
"""

from .models import DB_TABLES
from .migrations import MigrationManager
from .repository import Repository, InMemoryRepository, SQLiteRepository

__all__ = [
    "DB_TABLES",
    "MigrationManager",
    "Repository", "InMemoryRepository", "SQLiteRepository",
]
