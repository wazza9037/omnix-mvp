"""
CollabSession — Manages a shared editing session for an OMNIX workspace.

Tracks connected peers (id, name, color, cursor, active view), assigns
unique peer colors, and handles join/leave/reconnect lifecycle.
"""

from __future__ import annotations

import time
import uuid
import random
import string
from dataclasses import dataclass, field
from typing import Optional

# Palette of distinct colors for collaborators (max 12, then cycle)
PEER_COLORS = [
    "#FF6B6B",  # coral
    "#4ECDC4",  # teal
    "#FFE66D",  # yellow
    "#A78BFA",  # purple
    "#F97316",  # orange
    "#06B6D4",  # cyan
    "#EC4899",  # pink
    "#84CC16",  # lime
    "#F59E0B",  # amber
    "#6366F1",  # indigo
    "#14B8A6",  # emerald
    "#E879F9",  # fuchsia
]


@dataclass
class Peer:
    """A connected collaborator."""
    peer_id: str
    name: str
    color: str
    cursor: Optional[dict] = None          # {x, y, z, canvas_x, canvas_y}
    active_view: str = "3d"                # 3d | overview | iterate | simulate | mission | nlp | twin
    selected_part: Optional[str] = None    # part_id in custom build
    selected_node: Optional[str] = None    # node_id in behavior tree
    typing: bool = False
    connected: bool = True
    last_seen: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "peer_id": self.peer_id,
            "name": self.name,
            "color": self.color,
            "cursor": self.cursor,
            "active_view": self.active_view,
            "selected_part": self.selected_part,
            "selected_node": self.selected_node,
            "typing": self.typing,
            "connected": self.connected,
            "last_seen": self.last_seen,
        }


@dataclass
class CollabSession:
    """A collaborative editing session tied to a workspace."""

    session_id: str
    share_code: str
    owner_id: str
    workspace_device_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    peers: dict[str, Peer] = field(default_factory=dict)
    _color_index: int = 0
    chat_messages: list[dict] = field(default_factory=list)

    def _next_color(self) -> str:
        color = PEER_COLORS[self._color_index % len(PEER_COLORS)]
        self._color_index += 1
        return color

    def join(self, peer_id: str, name: str) -> Peer:
        """Add or reconnect a peer. Returns the Peer object."""
        if peer_id in self.peers:
            # Reconnect
            peer = self.peers[peer_id]
            peer.connected = True
            peer.last_seen = time.time()
            return peer

        peer = Peer(
            peer_id=peer_id,
            name=name,
            color=self._next_color(),
        )
        self.peers[peer_id] = peer
        return peer

    def leave(self, peer_id: str) -> Optional[Peer]:
        """Mark peer as disconnected (keep for history/reconnect)."""
        peer = self.peers.get(peer_id)
        if peer:
            peer.connected = False
            peer.last_seen = time.time()
        return peer

    def remove(self, peer_id: str) -> Optional[Peer]:
        """Fully remove a peer."""
        return self.peers.pop(peer_id, None)

    def get_peer(self, peer_id: str) -> Optional[Peer]:
        return self.peers.get(peer_id)

    def active_peers(self) -> list[Peer]:
        """Return only connected peers."""
        return [p for p in self.peers.values() if p.connected]

    def all_peers(self) -> list[Peer]:
        return list(self.peers.values())

    def add_chat(self, peer_id: str, text: str) -> dict:
        msg = {
            "id": str(uuid.uuid4())[:8],
            "peer_id": peer_id,
            "text": text,
            "timestamp": time.time(),
        }
        self.chat_messages.append(msg)
        # Keep last 200 messages
        if len(self.chat_messages) > 200:
            self.chat_messages = self.chat_messages[-200:]
        return msg

    def to_dict(self, include_chat: bool = False) -> dict:
        d = {
            "session_id": self.session_id,
            "share_code": self.share_code,
            "owner_id": self.owner_id,
            "workspace_device_id": self.workspace_device_id,
            "created_at": self.created_at,
            "peers": [p.to_dict() for p in self.peers.values()],
            "active_count": len(self.active_peers()),
        }
        if include_chat:
            d["chat"] = self.chat_messages[-50:]
        return d


def _generate_share_code(length: int = 6) -> str:
    """Generate a human-friendly share code (uppercase + digits, no ambiguous chars)."""
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # skip 0/O/1/I
    return "".join(random.choices(chars, k=length))


class SessionStore:
    """In-memory registry of active collaboration sessions."""

    def __init__(self):
        self._sessions: dict[str, CollabSession] = {}   # session_id -> session
        self._by_code: dict[str, str] = {}               # share_code -> session_id

    def create(self, owner_id: str, owner_name: str,
               device_id: Optional[str] = None) -> CollabSession:
        session_id = f"collab-{uuid.uuid4().hex[:10]}"
        code = _generate_share_code()
        # Ensure unique code
        while code in self._by_code:
            code = _generate_share_code()

        session = CollabSession(
            session_id=session_id,
            share_code=code,
            owner_id=owner_id,
            workspace_device_id=device_id,
        )
        # Auto-join owner
        session.join(owner_id, owner_name)

        self._sessions[session_id] = session
        self._by_code[code] = session_id
        return session

    def get(self, session_id: str) -> Optional[CollabSession]:
        return self._sessions.get(session_id)

    def get_by_code(self, code: str) -> Optional[CollabSession]:
        sid = self._by_code.get(code.upper())
        return self._sessions.get(sid) if sid else None

    def remove(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if session:
            self._by_code.pop(session.share_code, None)
            return True
        return False

    def list_all(self) -> list[dict]:
        return [s.to_dict() for s in self._sessions.values()]

    def find_by_peer(self, peer_id: str) -> Optional[CollabSession]:
        """Find the session a peer belongs to."""
        for s in self._sessions.values():
            if peer_id in s.peers:
                return s
        return None
