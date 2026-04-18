"""
omnix.collab — Real-time collaboration module (Figma-style multiplayer).

Provides session management, change broadcasting with conflict resolution,
real-time presence tracking, collaborative edit history, and WebSocket/polling
transport for the OMNIX Studio.
"""

from .session import CollabSession, SessionStore
from .sync import SyncEngine, Change, ChangeType
from .presence import PresenceTracker, CursorPosition
from .history import CollabHistory, HistoryEntry
from .ws_handler import CollabWSHandler

__all__ = [
    "CollabSession",
    "SessionStore",
    "SyncEngine",
    "Change",
    "ChangeType",
    "PresenceTracker",
    "CursorPosition",
    "CollabHistory",
    "HistoryEntry",
    "CollabWSHandler",
]
