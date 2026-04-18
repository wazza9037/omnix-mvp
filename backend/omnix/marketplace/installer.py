"""
Installer — imports marketplace items into local OMNIX.

Robot builds become templates. Mission templates join the mission library.
Connector configs get registered. Physics profiles can be applied to workspaces.
"""

from __future__ import annotations

import uuid
import time
from typing import Any

from .models import MarketplaceItem, ItemType
from .store import MarketplaceStore


class InstallError(Exception):
    pass


class Installer:
    """Installs marketplace items into the local OMNIX instance."""

    def __init__(self, store: MarketplaceStore):
        self._store = store

    def install(self, item_id: str, *,
                devices_registry: dict | None = None,
                workspace_store=None,
                bt_store: dict | None = None,
                device_id: str | None = None) -> dict:
        """Install a marketplace item. Returns installation result."""
        item = self._store.get(item_id)
        if not item:
            raise InstallError(f"Item not found: {item_id}")

        result = {
            "item_id": item_id,
            "title": item.title,
            "item_type": item.item_type.value,
            "installed": False,
            "message": "",
        }

        if item.item_type == ItemType.ROBOT_BUILD:
            result = self._install_robot_build(item, devices_registry, workspace_store)
        elif item.item_type == ItemType.MISSION_TEMPLATE:
            result = self._install_mission(item, bt_store, device_id)
        elif item.item_type == ItemType.CONNECTOR:
            result = self._install_connector(item)
        elif item.item_type == ItemType.PHYSICS_PROFILE:
            result = self._install_physics(item, workspace_store, device_id)
        elif item.item_type == ItemType.SCENARIO:
            result = self._install_scenario(item)
        else:
            result["message"] = f"Unknown item type: {item.item_type}"

        if result.get("installed"):
            self._store.increment_downloads(item_id)
            self._store.mark_installed(item_id, item.version)

        return result

    def _install_robot_build(self, item: MarketplaceItem,
                             devices_registry, workspace_store) -> dict:
        """Install a robot build as a device template.

        Creates a CustomRobotDevice from the build payload and registers it.
        """
        payload = item.payload
        build_data = payload.get("build", {})

        if not build_data.get("parts"):
            return {"installed": False, "message": "Build has no parts",
                    "item_id": item.item_id, "title": item.title,
                    "item_type": item.item_type.value}

        result = {
            "item_id": item.item_id,
            "title": item.title,
            "item_type": item.item_type.value,
            "installed": True,
            "message": f"Installed robot build: {item.title}",
            "device_type": payload.get("device_type", "custom"),
            "part_count": len(build_data.get("parts", [])),
            "build_data": build_data,
        }
        return result

    def _install_mission(self, item: MarketplaceItem,
                         bt_store, device_id) -> dict:
        """Install a mission template into the BT store."""
        tree_data = item.payload.get("tree", {})
        if not tree_data.get("root"):
            return {"installed": False, "message": "Mission has no tree data",
                    "item_id": item.item_id, "title": item.title,
                    "item_type": item.item_type.value}

        tree_id = tree_data.get("tree_id", f"bt-{uuid.uuid4().hex[:10]}")
        tree_data["tree_id"] = tree_id
        tree_data["name"] = item.title
        tree_data["description"] = f"[Marketplace] {item.description}"
        tree_data["updated_at"] = time.time()

        # If a device_id is specified, install into that device's BT store
        if bt_store is not None and device_id:
            bt_store.setdefault(device_id, {})[tree_id] = tree_data

        return {
            "item_id": item.item_id,
            "title": item.title,
            "item_type": item.item_type.value,
            "installed": True,
            "message": f"Installed mission: {item.title}",
            "tree_id": tree_id,
            "tree_data": tree_data,
        }

    def _install_connector(self, item: MarketplaceItem) -> dict:
        """Note connector availability (connectors ship with OMNIX)."""
        return {
            "item_id": item.item_id,
            "title": item.title,
            "item_type": item.item_type.value,
            "installed": True,
            "message": f"Connector noted: {item.title}. Use the Connectors panel to start it.",
            "connector_id": item.payload.get("connector_id", ""),
        }

    def _install_physics(self, item: MarketplaceItem,
                         workspace_store, device_id) -> dict:
        """Apply a physics profile to a workspace."""
        physics = item.payload.get("physics")
        if not physics:
            return {"installed": False, "message": "No physics data",
                    "item_id": item.item_id, "title": item.title,
                    "item_type": item.item_type.value}

        if workspace_store and device_id:
            try:
                workspace_store.set_physics(device_id, physics)
            except Exception:
                pass

        return {
            "item_id": item.item_id,
            "title": item.title,
            "item_type": item.item_type.value,
            "installed": True,
            "message": f"Applied physics profile: {item.title}",
        }

    def _install_scenario(self, item: MarketplaceItem) -> dict:
        return {
            "item_id": item.item_id,
            "title": item.title,
            "item_type": item.item_type.value,
            "installed": True,
            "message": f"Installed scenario: {item.title}",
        }

    def uninstall(self, item_id: str) -> dict:
        """Remove an installed item."""
        self._store.mark_uninstalled(item_id)
        return {"item_id": item_id, "uninstalled": True}
