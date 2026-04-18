"""
MarketplaceStore — in-memory store with JSON persistence.

Designed for easy swap to a database backend later. All operations
are thread-safe and return copies to prevent mutation.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any

from .models import MarketplaceItem, Review, ItemType


class MarketplaceStore:
    """In-memory marketplace store with optional file-based persistence."""

    def __init__(self, persist_path: str | None = None):
        self._items: dict[str, MarketplaceItem] = {}
        self._installed: dict[str, dict] = {}  # item_id → {installed_at, version}
        self._lock = threading.Lock()
        self._persist_path = persist_path

        if persist_path and os.path.exists(persist_path):
            self._load_from_file(persist_path)

    # ── CRUD ─────────────────────────────────────────────

    def add(self, item: MarketplaceItem) -> MarketplaceItem:
        with self._lock:
            self._items[item.item_id] = item
        self._maybe_persist()
        return item

    def get(self, item_id: str) -> MarketplaceItem | None:
        with self._lock:
            return self._items.get(item_id)

    def update(self, item_id: str, updates: dict) -> MarketplaceItem | None:
        with self._lock:
            item = self._items.get(item_id)
            if not item:
                return None
            for key, val in updates.items():
                if hasattr(item, key):
                    setattr(item, key, val)
            item.updated_at = time.time()
        self._maybe_persist()
        return item

    def delete(self, item_id: str) -> bool:
        with self._lock:
            if item_id in self._items:
                del self._items[item_id]
                self._maybe_persist()
                return True
            return False

    def count(self) -> int:
        with self._lock:
            return len(self._items)

    # ── Search & Browse ──────────────────────────────────

    def browse(self, *,
               query: str = "",
               item_type: str | None = None,
               tags: list[str] | None = None,
               compatibility: str | None = None,
               min_rating: float = 0.0,
               author: str | None = None,
               sort: str = "popular",    # popular | newest | rating | downloads
               page: int = 1,
               per_page: int = 20,
               ) -> dict:
        """Search and filter items with pagination."""
        with self._lock:
            items = list(self._items.values())

        # Filter: published only
        items = [i for i in items if i.published]

        # Filter: text search
        if query:
            q = query.lower()
            items = [i for i in items if (
                q in i.title.lower() or
                q in i.description.lower() or
                q in i.author.lower() or
                any(q in t.lower() for t in i.tags)
            )]

        # Filter: type
        if item_type:
            try:
                it = ItemType(item_type)
                items = [i for i in items if i.item_type == it]
            except ValueError:
                pass

        # Filter: tags
        if tags:
            tag_set = set(t.lower() for t in tags)
            items = [i for i in items if tag_set.intersection(
                t.lower() for t in i.tags)]

        # Filter: compatibility
        if compatibility:
            items = [i for i in items if (
                not i.compatibility or
                compatibility in i.compatibility
            )]

        # Filter: min rating
        if min_rating > 0:
            items = [i for i in items if i.rating >= min_rating]

        # Filter: author
        if author:
            items = [i for i in items if i.author.lower() == author.lower()]

        # Sort
        if sort == "popular":
            items.sort(key=lambda i: i.downloads, reverse=True)
        elif sort == "newest":
            items.sort(key=lambda i: i.created_at, reverse=True)
        elif sort == "rating":
            items.sort(key=lambda i: (i.rating, i.rating_count), reverse=True)
        elif sort == "downloads":
            items.sort(key=lambda i: i.downloads, reverse=True)
        else:
            items.sort(key=lambda i: i.downloads, reverse=True)

        # Pagination
        total = len(items)
        total_pages = max(1, (total + per_page - 1) // per_page)
        start = (page - 1) * per_page
        end = start + per_page
        page_items = items[start:end]

        return {
            "items": [i.summary() for i in page_items],
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }

    def get_by_author(self, author: str) -> list[MarketplaceItem]:
        with self._lock:
            return [i for i in self._items.values()
                    if i.author.lower() == author.lower()]

    def get_by_type(self, item_type: ItemType) -> list[MarketplaceItem]:
        with self._lock:
            return [i for i in self._items.values()
                    if i.item_type == item_type and i.published]

    # ── Reviews ──────────────────────────────────────────

    def add_review(self, item_id: str, rating: int, comment: str,
                   author: str = "User") -> Review | None:
        with self._lock:
            item = self._items.get(item_id)
            if not item:
                return None
            review = Review(
                review_id=f"rev-{uuid.uuid4().hex[:8]}",
                item_id=item_id,
                author=author,
                rating=max(1, min(5, rating)),
                comment=comment,
            )
            item.add_review(review)
        self._maybe_persist()
        return review

    # ── Downloads / Install tracking ─────────────────────

    def increment_downloads(self, item_id: str) -> None:
        with self._lock:
            item = self._items.get(item_id)
            if item:
                item.downloads += 1
        self._maybe_persist()

    def mark_installed(self, item_id: str, version: str = "") -> None:
        with self._lock:
            item = self._items.get(item_id)
            self._installed[item_id] = {
                "installed_at": time.time(),
                "version": version or (item.version if item else "1.0.0"),
                "title": item.title if item else "",
                "item_type": item.item_type.value if item else "",
            }

    def mark_uninstalled(self, item_id: str) -> None:
        with self._lock:
            self._installed.pop(item_id, None)

    def get_installed(self) -> list[dict]:
        with self._lock:
            result = []
            for iid, info in self._installed.items():
                item = self._items.get(iid)
                entry = dict(info)
                entry["item_id"] = iid
                if item:
                    entry.update(item.summary())
                    # Check for updates
                    entry["update_available"] = item.version != info.get("version")
                result.append(entry)
            return result

    def is_installed(self, item_id: str) -> bool:
        with self._lock:
            return item_id in self._installed

    # ── Persistence ──────────────────────────────────────

    def _maybe_persist(self) -> None:
        if not self._persist_path:
            return
        try:
            data = {
                "items": {k: v.to_dict() for k, v in self._items.items()},
                "installed": dict(self._installed),
            }
            with open(self._persist_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception:
            pass

    def _load_from_file(self, path: str) -> None:
        try:
            with open(path) as f:
                data = json.load(f)
            for k, v in data.get("items", {}).items():
                self._items[k] = MarketplaceItem.from_dict(v)
            self._installed = data.get("installed", {})
        except Exception:
            pass

    def all_items(self) -> list[MarketplaceItem]:
        with self._lock:
            return list(self._items.values())
