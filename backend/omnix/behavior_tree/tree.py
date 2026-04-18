"""
BehaviorTree — the top-level container.

A BehaviorTree owns a root node, a Blackboard, and metadata (name,
description, device_id). It's fully JSON-serializable so trees can
be saved to the workspace store and loaded in the visual editor.

The tree itself has no threading — it exposes a `tick()` method that
the TreeExecutor calls on a daemon thread at a configurable rate.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from .nodes import BTNode, NodeStatus, node_from_dict
from .blackboard import Blackboard


class BehaviorTree:
    """A complete behavior tree definition + execution state."""

    def __init__(self, *, tree_id: str | None = None, name: str = "Untitled Mission",
                 description: str = "", device_id: str = "",
                 root: BTNode | None = None):
        self.tree_id: str = tree_id or f"bt-{uuid.uuid4().hex[:10]}"
        self.name: str = name
        self.description: str = description
        self.device_id: str = device_id
        self.root: BTNode | None = root
        self.blackboard: Blackboard = Blackboard()
        self.created_at: float = time.time()
        self.updated_at: float = time.time()
        # Execution metadata (populated during runs)
        self.tick_count: int = 0
        self.status: NodeStatus = NodeStatus.PENDING
        self.started_at: float | None = None
        self.completed_at: float | None = None

    # ── Tick ──────────────────────────────────────────────

    def tick(self, context: dict) -> NodeStatus:
        """Advance the tree by one tick. Returns the root's status."""
        if self.root is None:
            self.status = NodeStatus.FAILURE
            return NodeStatus.FAILURE

        if self.started_at is None:
            self.started_at = time.time()

        self.tick_count += 1
        result = self.root.tick(self.blackboard, context)
        self.status = result

        if result in (NodeStatus.SUCCESS, NodeStatus.FAILURE):
            self.completed_at = time.time()

        return result

    def reset(self):
        """Reset tree to initial state for re-execution."""
        if self.root:
            self.root.reset()
        self.tick_count = 0
        self.status = NodeStatus.PENDING
        self.started_at = None
        self.completed_at = None
        self.blackboard.clear()

    # ── Node queries ─────────────────────────────────────

    def all_nodes(self) -> list[BTNode]:
        """Flat list of every node in the tree (BFS order)."""
        if not self.root:
            return []
        result = []
        queue = [self.root]
        while queue:
            node = queue.pop(0)
            result.append(node)
            queue.extend(node.children)
        return result

    def find_node(self, node_id: str) -> BTNode | None:
        for n in self.all_nodes():
            if n.node_id == node_id:
                return n
        return None

    def node_count(self) -> int:
        return len(self.all_nodes())

    # ── Serialization ────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "tree_id": self.tree_id,
            "name": self.name,
            "description": self.description,
            "device_id": self.device_id,
            "root": self.root.to_dict() if self.root else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tick_count": self.tick_count,
            "status": self.status.value,
        }

    @staticmethod
    def from_dict(d: dict) -> "BehaviorTree":
        root = node_from_dict(d["root"]) if d.get("root") else None
        tree = BehaviorTree(
            tree_id=d.get("tree_id"),
            name=d.get("name", "Untitled"),
            description=d.get("description", ""),
            device_id=d.get("device_id", ""),
            root=root,
        )
        tree.created_at = d.get("created_at", tree.created_at)
        tree.updated_at = d.get("updated_at", tree.updated_at)
        tree.tick_count = d.get("tick_count", 0)
        tree.status = NodeStatus(d.get("status", "pending"))
        return tree

    def __repr__(self):
        return (f"<BehaviorTree id={self.tree_id} name={self.name!r} "
                f"nodes={self.node_count()} status={self.status.value}>")
