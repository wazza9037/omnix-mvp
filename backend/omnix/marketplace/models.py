"""
Marketplace data models.

MarketplaceItem — a publishable asset (robot build, mission, connector, etc.)
Review          — user rating + comment on an item
ItemType        — enum of publishable asset categories
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class ItemType(str, Enum):
    ROBOT_BUILD = "robot_build"
    MISSION_TEMPLATE = "mission_template"
    CONNECTOR = "connector"
    SCENARIO = "scenario"
    PHYSICS_PROFILE = "physics_profile"


ITEM_TYPE_LABELS = {
    ItemType.ROBOT_BUILD: "Robot Build",
    ItemType.MISSION_TEMPLATE: "Mission Template",
    ItemType.CONNECTOR: "Connector",
    ItemType.SCENARIO: "Scenario",
    ItemType.PHYSICS_PROFILE: "Physics Profile",
}

ITEM_TYPE_ICONS = {
    ItemType.ROBOT_BUILD: "🤖",
    ItemType.MISSION_TEMPLATE: "🌳",
    ItemType.CONNECTOR: "🔌",
    ItemType.SCENARIO: "🧪",
    ItemType.PHYSICS_PROFILE: "⚙️",
}


@dataclass
class Review:
    review_id: str
    item_id: str
    author: str
    rating: int            # 1-5
    comment: str
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "review_id": self.review_id,
            "item_id": self.item_id,
            "author": self.author,
            "rating": self.rating,
            "comment": self.comment,
            "created_at": self.created_at,
        }

    @staticmethod
    def from_dict(d: dict) -> "Review":
        return Review(
            review_id=d.get("review_id", f"rev-{uuid.uuid4().hex[:8]}"),
            item_id=d["item_id"],
            author=d.get("author", "Anonymous"),
            rating=int(d.get("rating", 5)),
            comment=d.get("comment", ""),
            created_at=d.get("created_at", time.time()),
        )


@dataclass
class MarketplaceItem:
    """A publishable asset in the OMNIX marketplace."""

    item_id: str
    item_type: ItemType
    title: str
    description: str
    author: str = "OMNIX Team"
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)
    downloads: int = 0
    rating: float = 0.0          # running average
    rating_count: int = 0
    screenshots: list[str] = field(default_factory=list)  # preview identifiers
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    # Technical fields
    compatibility: list[str] = field(default_factory=list)  # device types
    dependencies: list[str] = field(default_factory=list)
    # Payload — the actual publishable content
    payload: dict[str, Any] = field(default_factory=dict)
    # Reviews
    reviews: list[Review] = field(default_factory=list)
    # Metadata
    icon: str = "📦"
    featured: bool = False
    published: bool = True

    def add_review(self, review: Review) -> None:
        self.reviews.append(review)
        total = sum(r.rating for r in self.reviews)
        self.rating_count = len(self.reviews)
        self.rating = round(total / self.rating_count, 1) if self.rating_count else 0.0

    def summary(self) -> dict:
        """Lightweight dict for browse listings (no payload or reviews)."""
        return {
            "item_id": self.item_id,
            "item_type": self.item_type.value,
            "item_type_label": ITEM_TYPE_LABELS.get(self.item_type, self.item_type.value),
            "item_type_icon": ITEM_TYPE_ICONS.get(self.item_type, "📦"),
            "title": self.title,
            "description": self.description[:200],
            "author": self.author,
            "version": self.version,
            "tags": list(self.tags),
            "downloads": self.downloads,
            "rating": self.rating,
            "rating_count": self.rating_count,
            "compatibility": list(self.compatibility),
            "icon": self.icon,
            "featured": self.featured,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_dict(self) -> dict:
        d = self.summary()
        d["description"] = self.description  # full description
        d["screenshots"] = list(self.screenshots)
        d["dependencies"] = list(self.dependencies)
        d["payload"] = dict(self.payload)
        d["reviews"] = [r.to_dict() for r in self.reviews]
        d["published"] = self.published
        return d

    @staticmethod
    def from_dict(d: dict) -> "MarketplaceItem":
        reviews = [Review.from_dict(r) for r in d.get("reviews", [])]
        return MarketplaceItem(
            item_id=d.get("item_id", f"mkt-{uuid.uuid4().hex[:10]}"),
            item_type=ItemType(d["item_type"]),
            title=d["title"],
            description=d.get("description", ""),
            author=d.get("author", "Anonymous"),
            version=d.get("version", "1.0.0"),
            tags=list(d.get("tags", [])),
            downloads=int(d.get("downloads", 0)),
            rating=float(d.get("rating", 0.0)),
            rating_count=int(d.get("rating_count", 0)),
            screenshots=list(d.get("screenshots", [])),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            compatibility=list(d.get("compatibility", [])),
            dependencies=list(d.get("dependencies", [])),
            payload=dict(d.get("payload", {})),
            reviews=reviews,
            icon=d.get("icon", "📦"),
            featured=d.get("featured", False),
            published=d.get("published", True),
        )
