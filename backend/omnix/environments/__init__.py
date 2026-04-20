"""
OMNIX Environments — rich 3D simulation environments for robots.

Provides pre-built environments (warehouse, outdoor, office, etc.),
obstacle management, and per-environment physics settings.
"""

from .registry import EnvironmentRegistry, get_environment, list_environments
from .obstacles import Obstacle, ObstacleManager
from .physics_env import EnvironmentPhysics

__all__ = [
    "EnvironmentRegistry",
    "get_environment",
    "list_environments",
    "Obstacle",
    "ObstacleManager",
    "EnvironmentPhysics",
]
