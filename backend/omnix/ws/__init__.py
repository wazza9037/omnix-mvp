"""
WebSocket transport for OMNIX real-time collaboration.

Upgrades the polling-based collab transport to real WebSocket push.
Falls back gracefully to polling if WebSocket connection fails.
"""

from .server import WebSocketServer, WebSocketConnection
from .handler import WSCollabHandler

__all__ = ["WebSocketServer", "WebSocketConnection", "WSCollabHandler"]
