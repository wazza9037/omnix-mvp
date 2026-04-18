"""
CollabWSHandler — WebSocket-style handler for collaboration sessions.

Since OMNIX uses Python's stdlib http.server (no asyncio/websocket lib),
this module provides a polling-based transport that mimics WebSocket
semantics. The frontend polls /api/collab/poll for events, and sends
actions via POST /api/collab/send.

Message types (client → server):
  join, leave, change, cursor_move, selection, view_switch, chat, typing, ping

Message types (server → client, via polling):
  peer_joined, peer_left, change, cursor_update, selection_update,
  view_update, chat_message, typing_update, conflict, pong

If a real WebSocket library becomes available, this can be upgraded
to push-based delivery with minimal changes.
"""

from __future__ import annotations

import time
import uuid
from typing import Optional

from .session import SessionStore, CollabSession, Peer
from .sync import SyncEngine, Change, ChangeType
from .presence import PresenceTracker
from .history import CollabHistory


class CollabWSHandler:
    """
    Central coordinator for all collab operations.

    Wires together session management, sync, presence, and history.
    The server routes call into this handler for all collab endpoints.
    """

    def __init__(self):
        self.sessions = SessionStore()
        self.sync = SyncEngine()
        self.presence = PresenceTracker()
        self.history = CollabHistory()

        # Event queues for polling: {session_id: {peer_id: [event, ...]}}
        self._event_queues: dict[str, dict[str, list[dict]]] = {}

    def _queue_event(self, session_id: str, event: dict,
                     exclude_peer: Optional[str] = None) -> None:
        """Push an event to all peers in a session (except sender)."""
        queues = self._event_queues.get(session_id, {})
        for pid, q in queues.items():
            if pid != exclude_peer:
                q.append(event)
                # Cap per-peer event queue
                if len(q) > 300:
                    del q[:len(q) - 300]

    def _init_peer_queue(self, session_id: str, peer_id: str) -> None:
        self._event_queues.setdefault(session_id, {})
        self._event_queues[session_id].setdefault(peer_id, [])

    # ── Session lifecycle ──

    def create_session(self, owner_id: str, owner_name: str,
                       device_id: Optional[str] = None) -> dict:
        session = self.sessions.create(owner_id, owner_name, device_id)
        self.sync.init_session(session.session_id)
        self.presence.init_session(session.session_id)
        self.history.init_session(session.session_id)
        self._init_peer_queue(session.session_id, owner_id)
        self.sync.register_peer(session.session_id, owner_id)
        self.presence.join(session.session_id, owner_id)
        return session.to_dict(include_chat=True)

    def join_session(self, code: str, peer_id: str,
                     peer_name: str) -> Optional[dict]:
        session = self.sessions.get_by_code(code)
        if not session:
            return None

        peer = session.join(peer_id, peer_name)
        sid = session.session_id

        self.sync.register_peer(sid, peer_id)
        self.presence.join(sid, peer_id)
        self._init_peer_queue(sid, peer_id)

        # Notify others
        self._queue_event(sid, {
            "type": "peer_joined",
            "peer": peer.to_dict(),
            "timestamp": time.time(),
        }, exclude_peer=peer_id)

        return {
            "session": session.to_dict(include_chat=True),
            "peer": peer.to_dict(),
            "presence": self.presence.get_session_presence(sid),
        }

    def leave_session(self, session_id: str, peer_id: str) -> bool:
        session = self.sessions.get(session_id)
        if not session:
            return False

        peer = session.leave(peer_id)
        if not peer:
            return False

        self.sync.unregister_peer(session_id, peer_id)
        self.presence.leave(session_id, peer_id)

        # Remove from event queues
        queues = self._event_queues.get(session_id, {})
        queues.pop(peer_id, None)

        # Notify others
        self._queue_event(session_id, {
            "type": "peer_left",
            "peer_id": peer_id,
            "peer_name": peer.name,
            "timestamp": time.time(),
        })

        # If no active peers remain, clean up session after a grace period
        # (For now, sessions persist until explicitly deleted)

        return True

    def get_session_info(self, session_id: str) -> Optional[dict]:
        session = self.sessions.get(session_id)
        if not session:
            return None
        return {
            **session.to_dict(include_chat=True),
            "presence": self.presence.get_session_presence(session_id),
            "history": self.history.get_timeline(session_id, limit=20),
        }

    # ── Real-time operations ──

    def handle_message(self, session_id: str, peer_id: str,
                       msg: dict) -> Optional[dict]:
        """
        Process an incoming message from a peer.
        Returns a direct response dict if needed, or None.
        """
        msg_type = msg.get("type", "")
        session = self.sessions.get(session_id)
        if not session:
            return {"type": "error", "message": "Session not found"}

        peer = session.get_peer(peer_id)
        if not peer:
            return {"type": "error", "message": "Not in session"}

        peer.last_seen = time.time()

        if msg_type == "ping":
            return {"type": "pong", "timestamp": time.time()}

        elif msg_type == "cursor_move":
            self.presence.update_cursor(session_id, peer_id, msg.get("cursor", {}))
            self._queue_event(session_id, {
                "type": "cursor_update",
                "peer_id": peer_id,
                "cursor": msg.get("cursor", {}),
            }, exclude_peer=peer_id)

        elif msg_type == "view_switch":
            view = msg.get("view", "3d")
            peer.active_view = view
            self.presence.update_view(session_id, peer_id, view)
            self._queue_event(session_id, {
                "type": "view_update",
                "peer_id": peer_id,
                "view": view,
            }, exclude_peer=peer_id)

        elif msg_type == "selection":
            part_id = msg.get("part_id")
            node_id = msg.get("node_id")
            peer.selected_part = part_id
            peer.selected_node = node_id
            self.presence.update_selection(session_id, peer_id, part_id, node_id)
            self._queue_event(session_id, {
                "type": "selection_update",
                "peer_id": peer_id,
                "part_id": part_id,
                "node_id": node_id,
            }, exclude_peer=peer_id)

        elif msg_type == "typing":
            typing = msg.get("typing", False)
            peer.typing = typing
            self.presence.update_typing(session_id, peer_id, typing)
            self._queue_event(session_id, {
                "type": "typing_update",
                "peer_id": peer_id,
                "typing": typing,
            }, exclude_peer=peer_id)

        elif msg_type == "change":
            change = Change(
                change_id=msg.get("change_id", str(uuid.uuid4())[:8]),
                session_id=session_id,
                peer_id=peer_id,
                change_type=ChangeType(msg["change_type"]),
                target_id=msg.get("target_id", ""),
                data=msg.get("data", {}),
            )

            # Build peer name map for conflict info
            names = {p.peer_id: p.name for p in session.all_peers()}
            conflict = self.sync.apply_change(change, names)

            # Record in history
            action_desc = _describe_change(change)
            self.history.record(
                session_id=session_id,
                peer_id=peer_id,
                peer_name=peer.name,
                peer_color=peer.color,
                action=action_desc,
                change_type=change.change_type.value,
                target_id=change.target_id,
                before_data=msg.get("before_data", {}),
                after_data=msg.get("data", {}),
            )

            # Broadcast the change
            self._queue_event(session_id, {
                "type": "change",
                "change": change.to_dict(),
                "peer_name": peer.name,
                "peer_color": peer.color,
            }, exclude_peer=peer_id)

            # If conflict, notify both peers
            if conflict:
                conflict_event = {
                    "type": "conflict",
                    "conflict": conflict.to_dict(),
                    "message": f"{conflict.conflicting_peer_name} also edited {change.target_id}",
                }
                self._queue_event(session_id, conflict_event)

            return {"type": "change_ack", "seq": change.seq}

        elif msg_type == "chat":
            text = msg.get("text", "").strip()
            if text:
                chat_msg = session.add_chat(peer_id, text)
                self._queue_event(session_id, {
                    "type": "chat_message",
                    "message": chat_msg,
                    "peer_name": peer.name,
                    "peer_color": peer.color,
                }, exclude_peer=peer_id)
                return {"type": "chat_ack", "message_id": chat_msg["id"]}

        elif msg_type == "undo":
            entry = self.history.undo(session_id, peer_id)
            if entry:
                # Broadcast undo as a change
                self._queue_event(session_id, {
                    "type": "change",
                    "change": {
                        "change_id": f"undo-{entry.entry_id}",
                        "session_id": session_id,
                        "peer_id": peer_id,
                        "change_type": entry.change_type,
                        "target_id": entry.target_id,
                        "data": entry.before_data,
                        "timestamp": time.time(),
                        "seq": 0,
                    },
                    "peer_name": peer.name,
                    "peer_color": peer.color,
                    "is_undo": True,
                }, exclude_peer=peer_id)
                return {"type": "undo_ack", "entry": entry.to_dict()}
            return {"type": "undo_ack", "entry": None}

        return None

    def poll_events(self, session_id: str, peer_id: str) -> list[dict]:
        """Drain pending events for a polling peer."""
        queues = self._event_queues.get(session_id, {})
        q = queues.get(peer_id, [])
        events = list(q)
        q.clear()
        return events

    def cleanup_session(self, session_id: str) -> None:
        self.sessions.remove(session_id)
        self.sync.cleanup_session(session_id)
        self.presence.cleanup_session(session_id)
        self.history.cleanup_session(session_id)
        self._event_queues.pop(session_id, None)


def _describe_change(change: Change) -> str:
    """Generate a human-readable description of a change."""
    ct = change.change_type
    tid = change.target_id or "unknown"
    data = change.data

    if ct == ChangeType.PART_UPDATE:
        fields = ", ".join(data.keys()) if data else "properties"
        return f"updated {tid} {fields}"
    elif ct == ChangeType.PART_ADD:
        name = data.get("name", tid)
        return f"added part {name}"
    elif ct == ChangeType.PART_REMOVE:
        return f"removed part {tid}"
    elif ct == ChangeType.NODE_UPDATE:
        return f"updated node {tid}"
    elif ct == ChangeType.NODE_ADD:
        ntype = data.get("type", "node")
        return f"added {ntype} node"
    elif ct == ChangeType.NODE_REMOVE:
        return f"removed node {tid}"
    elif ct == ChangeType.CONNECTION_CHANGE:
        return f"changed connection on {tid}"
    elif ct == ChangeType.TREE_PROPERTY:
        prop = data.get("property", "property")
        return f"updated tree {prop}"
    elif ct == ChangeType.WORKSPACE_META:
        return f"updated workspace settings"
    return f"changed {tid}"
