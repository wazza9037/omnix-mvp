"""
SyncEngine — Change broadcasting with last-write-wins conflict resolution.

Change types cover every collaborative operation in OMNIX Studio:
- Custom build: part_update, part_add, part_remove
- Behavior tree: node_update, node_add, node_remove, connection_change
- Tree properties, workspace metadata
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ChangeType(str, Enum):
    PART_UPDATE = "part_update"
    PART_ADD = "part_add"
    PART_REMOVE = "part_remove"
    NODE_UPDATE = "node_update"
    NODE_ADD = "node_add"
    NODE_REMOVE = "node_remove"
    CONNECTION_CHANGE = "connection_change"
    TREE_PROPERTY = "tree_property"
    WORKSPACE_META = "workspace_meta"


@dataclass
class Change:
    """A single collaborative change."""
    change_id: str
    session_id: str
    peer_id: str
    change_type: ChangeType
    target_id: str          # ID of the entity being changed
    data: dict              # The change payload
    timestamp: float = field(default_factory=time.time)
    seq: int = 0            # Sequence number within session

    def to_dict(self) -> dict:
        return {
            "change_id": self.change_id,
            "session_id": self.session_id,
            "peer_id": self.peer_id,
            "change_type": self.change_type.value if isinstance(self.change_type, ChangeType) else self.change_type,
            "target_id": self.target_id,
            "data": self.data,
            "timestamp": self.timestamp,
            "seq": self.seq,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Change":
        return cls(
            change_id=d.get("change_id", str(uuid.uuid4())[:8]),
            session_id=d["session_id"],
            peer_id=d["peer_id"],
            change_type=ChangeType(d["change_type"]),
            target_id=d.get("target_id", ""),
            data=d.get("data", {}),
            timestamp=d.get("timestamp", time.time()),
            seq=d.get("seq", 0),
        )


@dataclass
class ConflictInfo:
    """Metadata about a detected conflict."""
    change: Change
    conflicting_peer_id: str
    conflicting_peer_name: str
    target_id: str
    resolved_by: str = "last_write_wins"

    def to_dict(self) -> dict:
        return {
            "change_id": self.change.change_id,
            "conflicting_peer_id": self.conflicting_peer_id,
            "conflicting_peer_name": self.conflicting_peer_name,
            "target_id": self.target_id,
            "resolved_by": self.resolved_by,
        }


class SyncEngine:
    """
    Broadcasting + last-write-wins conflict resolution per session.

    Maintains a per-entity last-write record so concurrent edits to the
    same part/node produce conflict notifications.
    """

    def __init__(self):
        # session_id -> list of changes (append-only log)
        self._logs: dict[str, list[Change]] = {}
        # session_id -> seq counter
        self._seq: dict[str, int] = {}
        # session_id -> {target_id: (peer_id, timestamp)} for conflict detection
        self._last_write: dict[str, dict[str, tuple[str, float]]] = {}
        # session_id -> list of pending changes per peer (for polling clients)
        # {session_id: {peer_id: [Change, ...]}}
        self._pending: dict[str, dict[str, list[Change]]] = {}

    def init_session(self, session_id: str) -> None:
        self._logs.setdefault(session_id, [])
        self._seq.setdefault(session_id, 0)
        self._last_write.setdefault(session_id, {})
        self._pending.setdefault(session_id, {})

    def register_peer(self, session_id: str, peer_id: str) -> None:
        """Register a peer for pending-change polling."""
        self.init_session(session_id)
        self._pending[session_id].setdefault(peer_id, [])

    def unregister_peer(self, session_id: str, peer_id: str) -> None:
        pending = self._pending.get(session_id, {})
        pending.pop(peer_id, None)

    def apply_change(self, change: Change, peer_names: dict[str, str] | None = None
                     ) -> Optional[ConflictInfo]:
        """
        Apply a change: log it, check for conflicts, broadcast to other peers.
        Returns ConflictInfo if a conflict was detected, None otherwise.
        """
        sid = change.session_id
        self.init_session(sid)

        # Assign sequence number
        self._seq[sid] += 1
        change.seq = self._seq[sid]

        # Log
        self._logs[sid].append(change)
        # Keep last 500 changes per session
        if len(self._logs[sid]) > 500:
            self._logs[sid] = self._logs[sid][-500:]

        # Conflict detection (last-write-wins)
        conflict = None
        lw = self._last_write[sid]
        tid = change.target_id

        if tid and tid in lw:
            prev_peer, prev_ts = lw[tid]
            # Conflict if different peer edited same target within 3 seconds
            if prev_peer != change.peer_id and (change.timestamp - prev_ts) < 3.0:
                names = peer_names or {}
                conflict = ConflictInfo(
                    change=change,
                    conflicting_peer_id=prev_peer,
                    conflicting_peer_name=names.get(prev_peer, prev_peer[:6]),
                    target_id=tid,
                )

        # Update last-write record
        if tid:
            lw[tid] = (change.peer_id, change.timestamp)

        # Broadcast to other peers' pending queues
        for pid, queue in self._pending.get(sid, {}).items():
            if pid != change.peer_id:
                queue.append(change)
                # Cap pending per peer
                if len(queue) > 200:
                    del queue[:len(queue) - 200]

        return conflict

    def poll_changes(self, session_id: str, peer_id: str) -> list[dict]:
        """Drain pending changes for a polling peer."""
        pending = self._pending.get(session_id, {}).get(peer_id, [])
        changes = [c.to_dict() for c in pending]
        pending.clear()
        return changes

    def get_log(self, session_id: str, since_seq: int = 0) -> list[dict]:
        """Get change log since a sequence number."""
        log = self._logs.get(session_id, [])
        return [c.to_dict() for c in log if c.seq > since_seq]

    def cleanup_session(self, session_id: str) -> None:
        self._logs.pop(session_id, None)
        self._seq.pop(session_id, None)
        self._last_write.pop(session_id, None)
        self._pending.pop(session_id, None)
