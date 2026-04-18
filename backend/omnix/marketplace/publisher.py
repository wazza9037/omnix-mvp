"""
Publisher — packages workspace assets into marketplace items.

Takes a workspace's custom build, mission tree, connector config, or
physics profile and creates a validated MarketplaceItem ready for
publication.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from .models import MarketplaceItem, ItemType


class PublishError(Exception):
    pass


class Publisher:
    """Validates and packages workspace content for marketplace publication."""

    @staticmethod
    def publish_robot_build(workspace: dict, *,
                            title: str,
                            description: str,
                            author: str = "User",
                            tags: list[str] | None = None,
                            version: str = "1.0.0") -> MarketplaceItem:
        """Package a workspace's custom build as a marketplace item."""
        build = workspace.get("custom_build")
        if not build:
            raise PublishError("Workspace has no custom build to publish")

        # Validate
        Publisher._validate_metadata(title, description, tags)

        device_type = build.get("device_type", workspace.get("device_type", "custom"))
        parts = build.get("parts", [])
        if not parts:
            raise PublishError("Build has no parts — add at least one part before publishing")

        # Build payload
        payload = {
            "build": dict(build),
            "device_type": device_type,
            "part_count": len(parts),
            "part_types": list(set(p.get("type", "unknown") for p in parts)),
            "capabilities": build.get("capabilities", []),
            "mesh_params": build.get("mesh_params", {}),
        }

        # Include physics if tuned
        if workspace.get("physics"):
            payload["physics"] = dict(workspace["physics"])

        return MarketplaceItem(
            item_id=f"mkt-{uuid.uuid4().hex[:10]}",
            item_type=ItemType.ROBOT_BUILD,
            title=title,
            description=description,
            author=author,
            version=version,
            tags=list(tags or [device_type, "robot"]),
            compatibility=[device_type],
            payload=payload,
            icon="🤖",
        )

    @staticmethod
    def publish_mission(tree_data: dict, *,
                        title: str,
                        description: str,
                        author: str = "User",
                        tags: list[str] | None = None,
                        version: str = "1.0.0") -> MarketplaceItem:
        """Package a behavior tree as a marketplace mission template."""
        root = tree_data.get("root")
        if not root:
            raise PublishError("Mission tree has no root node")

        Publisher._validate_metadata(title, description, tags)

        # Count nodes
        node_count = Publisher._count_nodes(root)

        # Infer device compatibility from action nodes
        compat = set()
        for node in Publisher._flatten(root):
            cmd = node.get("properties", {}).get("command", "")
            if cmd in ("takeoff", "land", "move_to", "hover"):
                compat.add("drone")
            if cmd in ("move_joint", "set_gripper", "home"):
                compat.add("robot_arm")
            if cmd in ("drive", "turn"):
                compat.add("ground_robot")

        payload = {
            "tree": dict(tree_data),
            "node_count": node_count,
        }

        return MarketplaceItem(
            item_id=f"mkt-{uuid.uuid4().hex[:10]}",
            item_type=ItemType.MISSION_TEMPLATE,
            title=title,
            description=description,
            author=author,
            version=version,
            tags=list(tags or ["mission"]),
            compatibility=list(compat) if compat else ["drone", "ground_robot"],
            payload=payload,
            icon="🌳",
        )

    @staticmethod
    def publish_connector(connector_meta: dict, *,
                          title: str = "",
                          description: str = "",
                          author: str = "OMNIX Team",
                          tags: list[str] | None = None) -> MarketplaceItem:
        """Package connector metadata as a marketplace item."""
        cid = connector_meta.get("connector_id", "")
        title = title or connector_meta.get("display_name", cid)
        description = description or connector_meta.get("description", "")
        Publisher._validate_metadata(title, description, tags or [cid])

        payload = {
            "connector_id": cid,
            "tier": connector_meta.get("tier", 1),
            "config_fields": connector_meta.get("config_fields", []),
        }

        return MarketplaceItem(
            item_id=f"mkt-{uuid.uuid4().hex[:10]}",
            item_type=ItemType.CONNECTOR,
            title=title,
            description=description,
            author=author,
            tags=list(tags or [cid, "connector"]),
            compatibility=[],  # connectors are device-agnostic
            payload=payload,
            icon="🔌",
        )

    @staticmethod
    def publish_physics_profile(workspace: dict, *,
                                title: str,
                                description: str,
                                author: str = "User",
                                tags: list[str] | None = None) -> MarketplaceItem:
        """Package a workspace's learned physics model."""
        physics = workspace.get("physics")
        if not physics:
            raise PublishError("Workspace has no physics profile to publish")

        Publisher._validate_metadata(title, description, tags)

        device_type = workspace.get("device_type", "custom")
        payload = {
            "physics": dict(physics),
            "device_type": device_type,
            "world": dict(workspace.get("world", {})),
        }

        return MarketplaceItem(
            item_id=f"mkt-{uuid.uuid4().hex[:10]}",
            item_type=ItemType.PHYSICS_PROFILE,
            title=title,
            description=description,
            author=author,
            tags=list(tags or [device_type, "physics"]),
            compatibility=[device_type],
            payload=payload,
            icon="⚙️",
        )

    # ── Validation helpers ───────────────────────────────

    @staticmethod
    def _validate_metadata(title: str, description: str,
                           tags: list[str] | None) -> None:
        if not title or len(title.strip()) < 3:
            raise PublishError("Title must be at least 3 characters")
        if not description or len(description.strip()) < 10:
            raise PublishError("Description must be at least 10 characters")

    @staticmethod
    def _count_nodes(root: dict) -> int:
        count = 1
        for c in root.get("children", []):
            count += Publisher._count_nodes(c)
        return count

    @staticmethod
    def _flatten(root: dict) -> list[dict]:
        nodes = [root]
        for c in root.get("children", []):
            nodes.extend(Publisher._flatten(c))
        return nodes
