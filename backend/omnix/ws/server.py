"""
WebSocket server running alongside the HTTP server.

Uses the `websockets` library (already in requirements.txt) with asyncio.
Runs in a dedicated thread so it doesn't block the stdlib HTTP server.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Callable

from omnix.logging_setup import get_logger

log = get_logger("omnix.ws")

# Try to import websockets; fall back gracefully
try:
    import websockets
    import websockets.server
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False
    log.warning("websockets library not available — WebSocket transport disabled, using polling fallback")


@dataclass
class WebSocketConnection:
    """Represents a single WebSocket client connection."""
    ws: Any  # websockets.WebSocketServerProtocol
    peer_id: str = ""
    session_id: str = ""
    connected_at: float = field(default_factory=time.time)
    last_ping: float = field(default_factory=time.time)

    async def send(self, data: dict) -> bool:
        """Send a JSON message. Returns False if the connection is dead."""
        try:
            await self.ws.send(json.dumps(data))
            return True
        except Exception:
            return False


class WebSocketServer:
    """
    Manages WebSocket connections for real-time collaboration.

    Runs an asyncio event loop in a background thread. The HTTP server
    can query connection state and push messages via thread-safe methods.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8766):
        self.host = host
        self.port = port
        self._connections: dict[str, WebSocketConnection] = {}  # peer_id -> conn
        self._sessions: dict[str, set[str]] = {}  # session_id -> {peer_ids}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._message_handler: Optional[Callable] = None

    @property
    def available(self) -> bool:
        return HAS_WEBSOCKETS and self._running

    def set_message_handler(self, handler: Callable) -> None:
        """Set the callback for incoming messages: handler(session_id, peer_id, msg_dict)."""
        self._message_handler = handler

    def start(self) -> bool:
        """Start the WebSocket server in a background thread. Returns False if unavailable."""
        if not HAS_WEBSOCKETS:
            return False

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ws-server")
        self._thread.start()
        log.info("WebSocket server starting on ws://%s:%d", self.host, self.port)
        return True

    def stop(self) -> None:
        """Shut down the WebSocket server."""
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        log.info("WebSocket server stopped")

    def _run_loop(self) -> None:
        """Background thread: run the asyncio event loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._serve())
        except Exception as e:
            log.error("WebSocket server error: %s", e)
        finally:
            self._loop.close()

    async def _serve(self) -> None:
        """Main WebSocket server coroutine."""
        async with websockets.serve(self._handle_connection, self.host, self.port):
            while self._running:
                await asyncio.sleep(0.5)

    async def _handle_connection(self, ws: Any) -> None:
        """Handle a single WebSocket client connection."""
        conn = WebSocketConnection(ws=ws)
        peer_id = ""

        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await ws.send(json.dumps({"type": "error", "message": "Invalid JSON"}))
                    continue

                msg_type = msg.get("type", "")

                # Authentication / session join
                if msg_type == "auth":
                    peer_id = msg.get("peer_id", "")
                    session_id = msg.get("session_id", "")
                    token = msg.get("token", "")

                    conn.peer_id = peer_id
                    conn.session_id = session_id
                    self._connections[peer_id] = conn
                    self._sessions.setdefault(session_id, set()).add(peer_id)

                    await ws.send(json.dumps({
                        "type": "auth_ok",
                        "peer_id": peer_id,
                        "session_id": session_id,
                        "transport": "websocket",
                    }))
                    log.debug("WS peer connected: %s -> session %s", peer_id, session_id)
                    continue

                # Route message to handler
                if conn.session_id and conn.peer_id and self._message_handler:
                    response = self._message_handler(conn.session_id, conn.peer_id, msg)
                    if response:
                        await ws.send(json.dumps(response))

        except Exception as e:
            log.debug("WS connection closed: %s (%s)", peer_id or "unknown", e)
        finally:
            # Cleanup
            if peer_id:
                self._connections.pop(peer_id, None)
                if conn.session_id in self._sessions:
                    self._sessions[conn.session_id].discard(peer_id)
                    if not self._sessions[conn.session_id]:
                        del self._sessions[conn.session_id]

    def broadcast_to_session(self, session_id: str, event: dict,
                             exclude_peer: str = "") -> int:
        """
        Broadcast an event to all WebSocket peers in a session.
        Thread-safe — can be called from the HTTP server thread.
        Returns the number of peers notified.
        """
        if not self._loop or not self._running:
            return 0

        peer_ids = self._sessions.get(session_id, set())
        count = 0

        for pid in peer_ids:
            if pid == exclude_peer:
                continue
            conn = self._connections.get(pid)
            if conn:
                asyncio.run_coroutine_threadsafe(conn.send(event), self._loop)
                count += 1

        return count

    def is_peer_connected(self, peer_id: str) -> bool:
        """Check if a peer has an active WebSocket connection."""
        return peer_id in self._connections

    def get_session_peers(self, session_id: str) -> set[str]:
        """Get the set of WebSocket-connected peers for a session."""
        return self._sessions.get(session_id, set()).copy()

    def get_stats(self) -> dict:
        """Return WebSocket server stats."""
        return {
            "available": self.available,
            "connections": len(self._connections),
            "sessions": len(self._sessions),
        }
