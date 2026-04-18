"""
OMNIX Swarm — Multi-robot coordination and swarm control.

Provides group management, formation control, mission templates,
and synchronization primitives for coordinating 2+ robots as a unit.
"""

from .group import RobotGroup, RobotRole
from .coordinator import SwarmCoordinator
from .formations import FormationType, Formation, FORMATIONS
from .missions import MissionType, Mission, MISSION_TEMPLATES
from .sync import Barrier, Countdown, Heartbeat, ReFormation, SyncManager

__all__ = [
    "RobotGroup", "RobotRole",
    "SwarmCoordinator",
    "FormationType", "Formation", "FORMATIONS",
    "MissionType", "Mission", "MISSION_TEMPLATES",
    "Barrier", "Countdown", "Heartbeat", "ReFormation", "SyncManager",
]
