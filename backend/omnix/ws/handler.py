"""
WebSocket-aware collaboration handler.

Wraps the existing CollabWSHandler, adding WebSocket push delivery
alongside the polling fallback. When a peer has a WebSocket connection,
events are pushed immediately; otherwise they queue for polling.
"""

from __future__ import annotations

from typing import Any, Optional

from omnix.logging_setup import get_logger
from omnix.collab.ws_handler import CollabWSHandler
from .server import WebSocketServer

log = get_logger("omnix.ws.handler")


class WSCollabHandler:
    """
    Hybrid WebSocket + polling collaboration handler.

    Delegates session management to the existing CollabWSHandler.
    Upgrades event delivery to use WebSocket push when available.
    """

    def __init__(self, collab: CollabWSHandler, ws_server: WebSocketServer):
        self.collab = collab
        self.ws = ws_server

        # Wire up the WebSocket message handler
        ws_server.set_message_handler(self._on_ws_message)

    def _on_ws_message(self, session_id: str, peer_id: str, msg: dict) -> Optional[dict]:
        """Handle an incoming WebSocket message by delegating to the collab handler."""
        response = self.collab.handle_message(session_id, peer_id, msg)

        # After handling, broadcast any queued events via WebSocket
        self._flush_to_websocket(session_id)

        return response

    def _flush_to_websocket(self, session_id: str) -> None:
        """
        For any peer with a WebSocket connection, drain their polling queue
        and push events immediately via WebSocket.
        """
        if not self.ws.available:
            return

        queues = self.collab._event_queues.get(session_id, {})
        ws_peers = self.ws.get_session_peers(session_id)

        for pid in ws_peers:
            q = queues.get(pid, [])
            if q:
                for event in q:
                    self.ws.broadcast_to_session(session_id, event, exclude_peer="")
                q.clear()

    # ── Delegate session lifecycle ──

    def create_session(self, owner_id: str, owner_name: str,
                       device_id: str | None = None) -> dict:
        result = self.collab.create_session(owner_id, owner_name, device_id)
        return {**result, "transport": "websocket" if self.ws.available else "polling"}

    def join_session(self, code: str, peer_id: str, peer_name: str) -> Optional[dict]:
        result = self.collab.join_session(code, peer_id, peer_name)
        if result:
            # Notify via WebSocket if possible
            sid = result["session"]["session_id"]
            self.ws.broadcast_to_session(sid, {
                "type": "peer_joined",
                "peer": result["peer"],
            }, exclude_peer=peer_id)
            result["transport"] = "websocket" if self.ws.available else "polling"
        return result

    def leave_session(self, session_id: str, peer_id: str) -> bool:
        result = self.collab.leave_session(session_id, peer_id)
        if result:
            self.ws.broadcast_to_session(session_id, {
                "type": "peer_left",
                "peer_id": peer_id,
            })
        return result

    def handle_message(self, session_id: str, peer_id: str, msg: dict) -> Optional[dict]:
        """Handle a message (from polling or direct call)."""
        response = self.collab.handle_message(session_id, peer_id, msg)
        self._flush_to_websocket(session_id)
        return response

    def poll_events(self, session_id: str, peer_id: str) -> list[dict]:
        """Polling endpoint — only returns events if peer has no WebSocket."""
        if self.ws.is_peer_connected(peer_id):
            return []  # Events already pushed via WebSocket
        return self.collab.poll_events(session_id, peer_id)

    def get_session_info(self, session_id: str) -> Optional[dict]:
        info = self.collab.get_session_info(session_id)
        if info:
            info["transport"] = "websocket" if self.ws.available else "polling"
            info["ws_peers"] = list(self.ws.get_session_peers(session_id))
        return info

    def cleanup_session(self, session_id: str) -> None:
        self.collab.cleanup_session(session_id)
