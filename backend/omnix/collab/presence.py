"""
PresenceTracker — Real-time presence for collaborative sessions.

Tracks cursor positions (3D + canvas), active views, selected parts/nodes,
and typing indicators per peer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CursorPosition:
    """Cursor position in both 3D world space and 2D canvas space."""
    world_x: float = 0.0
    world_y: float = 0.0
    world_z: float = 0.0
    canvas_x: float = 0.0
    canvas_y: float = 0.0
    view: str = "3d"  # Which view the cursor is on
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "world_x": self.world_x,
            "world_y": self.world_y,
            "world_z": self.world_z,
            "canvas_x": self.canvas_x,
            "canvas_y": self.canvas_y,
            "view": self.view,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CursorPosition":
        return cls(
            world_x=d.get("world_x", 0),
            world_y=d.get("world_y", 0),
            world_z=d.get("world_z", 0),
            canvas_x=d.get("canvas_x", 0),
            canvas_y=d.get("canvas_y", 0),
            view=d.get("view", "3d"),
            timestamp=d.get("timestamp", time.time()),
        )


@dataclass
class PeerPresence:
    """Full presence state for a single peer."""
    peer_id: str
    cursor: Optional[CursorPosition] = None
    active_view: str = "3d"
    selected_part: Optional[str] = None
    selected_node: Optional[str] = None
    typing: bool = False
    last_activity: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "peer_id": self.peer_id,
            "cursor": self.cursor.to_dict() if self.cursor else None,
            "active_view": self.active_view,
            "selected_part": self.selected_part,
            "selected_node": self.selected_node,
            "typing": self.typing,
            "last_activity": self.last_activity,
        }


class PresenceTracker:
    """Tracks real-time presence state for all peers across sessions."""

    def __init__(self):
        # session_id -> {peer_id: PeerPresence}
        self._presence: dict[str, dict[str, PeerPresence]] = {}

    def init_session(self, session_id: str) -> None:
        self._presence.setdefault(session_id, {})

    def join(self, session_id: str, peer_id: str) -> PeerPresence:
        self.init_session(session_id)
        pp = PeerPresence(peer_id=peer_id)
        self._presence[session_id][peer_id] = pp
        return pp

    def leave(self, session_id: str, peer_id: str) -> None:
        peers = self._presence.get(session_id, {})
        peers.pop(peer_id, None)

    def update_cursor(self, session_id: str, peer_id: str,
                      cursor_data: dict) -> Optional[PeerPresence]:
        pp = self._presence.get(session_id, {}).get(peer_id)
        if not pp:
            return None
        pp.cursor = CursorPosition.from_dict(cursor_data)
        pp.last_activity = time.time()
        return pp

    def update_view(self, session_id: str, peer_id: str,
                    view: str) -> Optional[PeerPresence]:
        pp = self._presence.get(session_id, {}).get(peer_id)
        if not pp:
            return None
        pp.active_view = view
        pp.last_activity = time.time()
        return pp

    def update_selection(self, session_id: str, peer_id: str,
                         part_id: Optional[str] = None,
                         node_id: Optional[str] = None) -> Optional[PeerPresence]:
        pp = self._presence.get(session_id, {}).get(peer_id)
        if not pp:
            return None
        pp.selected_part = part_id
        pp.selected_node = node_id
        pp.last_activity = time.time()
        return pp

    def update_typing(self, session_id: str, peer_id: str,
                      typing: bool) -> Optional[PeerPresence]:
        pp = self._presence.get(session_id, {}).get(peer_id)
        if not pp:
            return None
        pp.typing = typing
        pp.last_activity = time.time()
        return pp

    def get_session_presence(self, session_id: str) -> list[dict]:
        """Get all presence data for a session."""
        peers = self._presence.get(session_id, {})
        return [pp.to_dict() for pp in peers.values()]

    def get_peer_presence(self, session_id: str,
                          peer_id: str) -> Optional[dict]:
        pp = self._presence.get(session_id, {}).get(peer_id)
        return pp.to_dict() if pp else None

    def cleanup_session(self, session_id: str) -> None:
        self._presence.pop(session_id, None)

    def cleanup_stale(self, session_id: str,
                      timeout_s: float = 60.0) -> list[str]:
        """Remove peers with no activity for timeout_s. Returns removed peer_ids."""
        now = time.time()
        peers = self._presence.get(session_id, {})
        stale = [pid for pid, pp in peers.items()
                 if (now - pp.last_activity) > timeout_s]
        for pid in stale:
            peers.pop(pid, None)
        return stale
