"""
Tests for the Marketplace / Community Hub.

Covers: models, store CRUD, search/filter/sort, reviews, publisher
validation, installer, featured collections, and seed data.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from omnix.marketplace.models import MarketplaceItem, Review, ItemType, ITEM_TYPE_LABELS
from omnix.marketplace.store import MarketplaceStore
from omnix.marketplace.publisher import Publisher, PublishError
from omnix.marketplace.installer import Installer, InstallError
from omnix.marketplace.featured import FeaturedCollections, seed_marketplace


# ── Models ───────────────────────────────────────────────

class TestModels:

    def test_item_creation(self):
        item = MarketplaceItem(
            item_id="test-1", item_type=ItemType.ROBOT_BUILD,
            title="Test Bot", description="A test robot build")
        assert item.item_id == "test-1"
        assert item.item_type == ItemType.ROBOT_BUILD
        assert item.downloads == 0

    def test_item_serialization(self):
        item = MarketplaceItem(
            item_id="test-2", item_type=ItemType.MISSION_TEMPLATE,
            title="Mission", description="Test mission",
            tags=["drone", "patrol"], compatibility=["drone"])
        d = item.to_dict()
        item2 = MarketplaceItem.from_dict(d)
        assert item2.title == "Mission"
        assert item2.tags == ["drone", "patrol"]
        assert item2.compatibility == ["drone"]

    def test_item_summary(self):
        item = MarketplaceItem(
            item_id="test-3", item_type=ItemType.CONNECTOR,
            title="Test Conn", description="Long desc " * 30)
        s = item.summary()
        assert len(s["description"]) <= 200
        assert "payload" not in s
        assert "reviews" not in s

    def test_review(self):
        review = Review(review_id="r1", item_id="test-1",
                        author="User", rating=5, comment="Great!")
        d = review.to_dict()
        r2 = Review.from_dict(d)
        assert r2.rating == 5
        assert r2.author == "User"

    def test_add_review_updates_rating(self):
        item = MarketplaceItem(
            item_id="test-4", item_type=ItemType.ROBOT_BUILD,
            title="Bot", description="Test")
        item.add_review(Review("r1", "test-4", "A", 5, ""))
        item.add_review(Review("r2", "test-4", "B", 3, ""))
        assert item.rating == 4.0
        assert item.rating_count == 2

    def test_item_type_labels(self):
        assert ITEM_TYPE_LABELS[ItemType.ROBOT_BUILD] == "Robot Build"
        assert ITEM_TYPE_LABELS[ItemType.CONNECTOR] == "Connector"


# ── Store ────────────────────────────────────────────────

class TestStore:

    def _fresh(self):
        return MarketplaceStore()

    def test_add_get(self):
        store = self._fresh()
        item = MarketplaceItem(item_id="s1", item_type=ItemType.ROBOT_BUILD,
                               title="Bot", description="Test")
        store.add(item)
        got = store.get("s1")
        assert got is not None
        assert got.title == "Bot"

    def test_update(self):
        store = self._fresh()
        item = MarketplaceItem(item_id="s2", item_type=ItemType.ROBOT_BUILD,
                               title="Old", description="Test")
        store.add(item)
        store.update("s2", {"title": "New"})
        assert store.get("s2").title == "New"

    def test_delete(self):
        store = self._fresh()
        item = MarketplaceItem(item_id="s3", item_type=ItemType.ROBOT_BUILD,
                               title="Del", description="Test")
        store.add(item)
        assert store.delete("s3")
        assert store.get("s3") is None

    def test_browse_basic(self):
        store = self._fresh()
        for i in range(5):
            store.add(MarketplaceItem(
                item_id=f"b{i}", item_type=ItemType.ROBOT_BUILD,
                title=f"Bot {i}", description=f"Description {i}",
                downloads=i * 100))
        result = store.browse()
        assert result["total"] == 5
        # Default sort is popular (by downloads desc)
        assert result["items"][0]["title"] == "Bot 4"

    def test_browse_search(self):
        store = self._fresh()
        store.add(MarketplaceItem(item_id="q1", item_type=ItemType.ROBOT_BUILD,
                                  title="Racing Drone", description="Fast drone"))
        store.add(MarketplaceItem(item_id="q2", item_type=ItemType.ROBOT_BUILD,
                                  title="Patrol Robot", description="Security robot"))
        result = store.browse(query="drone")
        assert result["total"] == 1
        assert result["items"][0]["title"] == "Racing Drone"

    def test_browse_type_filter(self):
        store = self._fresh()
        store.add(MarketplaceItem(item_id="t1", item_type=ItemType.ROBOT_BUILD,
                                  title="Bot", description="Test"))
        store.add(MarketplaceItem(item_id="t2", item_type=ItemType.CONNECTOR,
                                  title="Conn", description="Test"))
        result = store.browse(item_type="connector")
        assert result["total"] == 1

    def test_browse_tag_filter(self):
        store = self._fresh()
        store.add(MarketplaceItem(item_id="tg1", item_type=ItemType.ROBOT_BUILD,
                                  title="Bot1", description="Test", tags=["beginner"]))
        store.add(MarketplaceItem(item_id="tg2", item_type=ItemType.ROBOT_BUILD,
                                  title="Bot2", description="Test", tags=["advanced"]))
        result = store.browse(tags=["beginner"])
        assert result["total"] == 1

    def test_browse_compatibility(self):
        store = self._fresh()
        store.add(MarketplaceItem(item_id="c1", item_type=ItemType.ROBOT_BUILD,
                                  title="Drone", description="Test", compatibility=["drone"]))
        store.add(MarketplaceItem(item_id="c2", item_type=ItemType.ROBOT_BUILD,
                                  title="Arm", description="Test", compatibility=["robot_arm"]))
        result = store.browse(compatibility="drone")
        assert result["total"] == 1

    def test_browse_sort_newest(self):
        store = self._fresh()
        store.add(MarketplaceItem(item_id="n1", item_type=ItemType.ROBOT_BUILD,
                                  title="Old", description="Test", created_at=1000))
        store.add(MarketplaceItem(item_id="n2", item_type=ItemType.ROBOT_BUILD,
                                  title="New", description="Test", created_at=2000))
        result = store.browse(sort="newest")
        assert result["items"][0]["title"] == "New"

    def test_browse_sort_rating(self):
        store = self._fresh()
        store.add(MarketplaceItem(item_id="r1", item_type=ItemType.ROBOT_BUILD,
                                  title="Low", description="Test", rating=2.0))
        store.add(MarketplaceItem(item_id="r2", item_type=ItemType.ROBOT_BUILD,
                                  title="High", description="Test", rating=5.0))
        result = store.browse(sort="rating")
        assert result["items"][0]["title"] == "High"

    def test_browse_pagination(self):
        store = self._fresh()
        for i in range(25):
            store.add(MarketplaceItem(item_id=f"p{i}", item_type=ItemType.ROBOT_BUILD,
                                      title=f"Bot {i}", description="Test"))
        r1 = store.browse(per_page=10, page=1)
        assert len(r1["items"]) == 10
        assert r1["total_pages"] == 3
        r3 = store.browse(per_page=10, page=3)
        assert len(r3["items"]) == 5

    def test_reviews(self):
        store = self._fresh()
        store.add(MarketplaceItem(item_id="rv1", item_type=ItemType.ROBOT_BUILD,
                                  title="Bot", description="Test"))
        review = store.add_review("rv1", 4, "Good!", "User1")
        assert review is not None
        item = store.get("rv1")
        assert item.rating == 4.0
        assert item.rating_count == 1

    def test_install_tracking(self):
        store = self._fresh()
        store.add(MarketplaceItem(item_id="i1", item_type=ItemType.ROBOT_BUILD,
                                  title="Bot", description="Test"))
        store.increment_downloads("i1")
        assert store.get("i1").downloads == 1
        store.mark_installed("i1", "1.0.0")
        assert store.is_installed("i1")
        installed = store.get_installed()
        assert len(installed) == 1
        store.mark_uninstalled("i1")
        assert not store.is_installed("i1")


# ── Publisher ────────────────────────────────────────────

class TestPublisher:

    def test_publish_robot_build(self):
        ws = {
            "custom_build": {
                "parts": [{"type": "rotor", "part_id": "p1"}],
                "device_type": "drone",
                "capabilities": [],
            },
            "device_type": "drone",
        }
        item = Publisher.publish_robot_build(
            ws, title="My Drone", description="A great drone build for testing",
            author="Builder", tags=["drone"])
        assert item.item_type == ItemType.ROBOT_BUILD
        assert item.title == "My Drone"
        assert "drone" in item.compatibility

    def test_publish_requires_build(self):
        try:
            Publisher.publish_robot_build(
                {}, title="X", description="Missing build data", author="Test")
            assert False
        except PublishError:
            pass

    def test_publish_requires_parts(self):
        ws = {"custom_build": {"parts": [], "device_type": "custom"}}
        try:
            Publisher.publish_robot_build(
                ws, title="Empty", description="Build has no parts at all",
                author="Test")
            assert False
        except PublishError:
            pass

    def test_publish_validates_title(self):
        ws = {"custom_build": {"parts": [{"type": "x"}], "device_type": "custom"}}
        try:
            Publisher.publish_robot_build(ws, title="", description="Valid description here",
                                         author="Test")
            assert False
        except PublishError:
            pass

    def test_publish_validates_description(self):
        ws = {"custom_build": {"parts": [{"type": "x"}], "device_type": "custom"}}
        try:
            Publisher.publish_robot_build(ws, title="Valid Title", description="",
                                         author="Test")
            assert False
        except PublishError:
            pass

    def test_publish_mission(self):
        tree = {
            "tree_id": "bt-test",
            "root": {
                "type": "Sequence", "node_id": "root",
                "children": [
                    {"type": "ExecuteCommand", "node_id": "n1",
                     "properties": {"command": "takeoff"}, "children": []},
                ],
            },
        }
        item = Publisher.publish_mission(
            tree, title="Test Mission", description="A patrol mission for testing drones",
            author="Mission Builder")
        assert item.item_type == ItemType.MISSION_TEMPLATE
        assert "drone" in item.compatibility

    def test_publish_physics(self):
        ws = {
            "physics": {"params": {"drag": 0.5}, "confidence": 0.8},
            "device_type": "drone",
            "world": {"gravity_m_s2": 9.81},
        }
        item = Publisher.publish_physics_profile(
            ws, title="Tello Model", description="Tuned physics for Tello drone flights",
            author="Physicist")
        assert item.item_type == ItemType.PHYSICS_PROFILE


# ── Installer ────────────────────────────────────────────

class TestInstaller:

    def test_install_robot_build(self):
        store = MarketplaceStore()
        item = MarketplaceItem(
            item_id="inst-1", item_type=ItemType.ROBOT_BUILD,
            title="Bot", description="Test",
            payload={"build": {"parts": [{"type": "rotor"}]}, "device_type": "drone"})
        store.add(item)
        installer = Installer(store)
        result = installer.install("inst-1")
        assert result["installed"]
        assert store.is_installed("inst-1")

    def test_install_connector(self):
        store = MarketplaceStore()
        item = MarketplaceItem(
            item_id="inst-2", item_type=ItemType.CONNECTOR,
            title="Pi Conn", description="Test",
            payload={"connector_id": "pi_agent"})
        store.add(item)
        installer = Installer(store)
        result = installer.install("inst-2")
        assert result["installed"]

    def test_install_missing_item(self):
        store = MarketplaceStore()
        installer = Installer(store)
        try:
            installer.install("nonexistent")
            assert False
        except InstallError:
            pass

    def test_uninstall(self):
        store = MarketplaceStore()
        store.mark_installed("x", "1.0")
        installer = Installer(store)
        result = installer.uninstall("x")
        assert result["uninstalled"]
        assert not store.is_installed("x")


# ── Featured & Seeding ───────────────────────────────────

class TestFeatured:

    def test_seed_marketplace(self):
        store = MarketplaceStore()
        count = seed_marketplace(store)
        assert count == 32  # 10 builds + 6 missions + 6 connectors + 10 community

    def test_no_double_seed(self):
        store = MarketplaceStore()
        seed_marketplace(store)
        count2 = seed_marketplace(store)
        assert count2 == 0

    def test_featured_collections(self):
        store = MarketplaceStore()
        seed_marketplace(store)
        collections = FeaturedCollections.get_collections(store)
        assert len(collections) == 6
        names = [c["title"] for c in collections]
        assert "Staff Picks" in names
        assert "Most Popular This Week" in names
        assert "Best for Beginners" in names

    def test_seeded_items_have_reviews(self):
        store = MarketplaceStore()
        seed_marketplace(store)
        item = store.get("mkt-quadcopter")
        assert item is not None
        assert len(item.reviews) >= 2

    def test_seeded_items_browsable(self):
        store = MarketplaceStore()
        seed_marketplace(store)
        result = store.browse(query="patrol")
        assert result["total"] >= 2  # Patrol & Return + Warehouse Patrol Bot


# ── Run all tests ────────────────────────────────────────

if __name__ == "__main__":
    passed = failed = 0
    errors = []

    test_classes = [
        TestModels, TestStore, TestPublisher, TestInstaller, TestFeatured,
    ]

    for cls in test_classes:
        print(f"\n{cls.__name__}:")
        instance = cls()
        for attr in sorted(dir(instance)):
            if attr.startswith("test_"):
                try:
                    getattr(instance, attr)()
                    passed += 1
                    print(f"  PASS {attr}")
                except Exception as e:
                    failed += 1
                    errors.append(f"{cls.__name__}.{attr}: {e}")
                    print(f"  FAIL {attr}: {e}")

    print(f"\n===== {passed} passed, {failed} failed =====")
    if errors:
        for e in errors:
            print(f"  {e}")
