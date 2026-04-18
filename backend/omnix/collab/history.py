"""
CollabHistory — Collaborative edit history with per-peer attribution.

Tracks every change with timestamps and peer info, supports per-user undo
by maintaining separate undo stacks per peer.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class HistoryEntry:
    """A single entry in the collaborative edit history."""
    entry_id: str
    session_id: str
    peer_id: str
    peer_name: str
    peer_color: str
    action: str            # Human-readable description: "updated rotor_1 size"
    change_type: str       # ChangeType value
    target_id: str
    before_data: dict      # Snapshot before change (for undo)
    after_data: dict       # Snapshot after change
    timestamp: float = field(default_factory=time.time)
    undone: bool = False

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "session_id": self.session_id,
            "peer_id": self.peer_id,
            "peer_name": self.peer_name,
            "peer_color": self.peer_color,
            "action": self.action,
            "change_type": self.change_type,
            "target_id": self.target_id,
            "timestamp": self.timestamp,
            "undone": self.undone,
        }


class CollabHistory:
    """
    Per-session collaborative history with per-peer undo stacks.

    The global timeline is shared, but each peer can undo their own
    changes independently without affecting others.
    """

    def __init__(self, max_entries: int = 300):
        self._max = max_entries
        # session_id -> [HistoryEntry, ...]
        self._timeline: dict[str, list[HistoryEntry]] = {}
        # session_id -> {peer_id: [entry_id, ...]} (undo stack)
        self._undo_stacks: dict[str, dict[str, list[str]]] = {}
        # entry_id -> HistoryEntry (quick lookup)
        self._entries: dict[str, HistoryEntry] = {}

    def init_session(self, session_id: str) -> None:
        self._timeline.setdefault(session_id, [])
        self._undo_stacks.setdefault(session_id, {})

    def record(self, session_id: str, peer_id: str, peer_name: str,
               peer_color: str, action: str, change_type: str,
               target_id: str, before_data: dict,
               after_data: dict) -> HistoryEntry:
        """Record a new history entry."""
        self.init_session(session_id)

        entry = HistoryEntry(
            entry_id=f"h-{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            peer_id=peer_id,
            peer_name=peer_name,
            peer_color=peer_color,
            action=action,
            change_type=change_type,
            target_id=target_id,
            before_data=before_data,
            after_data=after_data,
        )

        timeline = self._timeline[session_id]
        timeline.append(entry)
        if len(timeline) > self._max:
            # Remove oldest and clean up lookup
            removed = timeline[:len(timeline) - self._max]
            for r in removed:
                self._entries.pop(r.entry_id, None)
            self._timeline[session_id] = timeline[-self._max:]

        self._entries[entry.entry_id] = entry

        # Push to peer's undo stack
        stacks = self._undo_stacks[session_id]
        stacks.setdefault(peer_id, [])
        stacks[peer_id].append(entry.entry_id)
        # Cap undo stack
        if len(stacks[peer_id]) > 50:
            stacks[peer_id] = stacks[peer_id][-50:]

        return entry

    def undo(self, session_id: str, peer_id: str) -> Optional[HistoryEntry]:
        """
        Undo the last change by this peer. Returns the entry that was undone
        (with before_data for reverting), or None if nothing to undo.
        """
        stacks = self._undo_stacks.get(session_id, {})
        stack = stacks.get(peer_id, [])

        while stack:
            entry_id = stack.pop()
            entry = self._entries.get(entry_id)
            if entry and not entry.undone:
                entry.undone = True
                return entry

        return None

    def get_timeline(self, session_id: str, limit: int = 50,
                     peer_id: Optional[str] = None) -> list[dict]:
        """Get recent history, optionally filtered by peer."""
        timeline = self._timeline.get(session_id, [])
        if peer_id:
            timeline = [e for e in timeline if e.peer_id == peer_id]
        return [e.to_dict() for e in timeline[-limit:]]

    def cleanup_session(self, session_id: str) -> None:
        entries = self._timeline.pop(session_id, [])
        for e in entries:
            self._entries.pop(e.entry_id, None)
        self._undo_stacks.pop(session_id, None)
