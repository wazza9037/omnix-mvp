"""
OMNIX Obstacle System — static and dynamic obstacles for simulation environments.

Each obstacle carries geometry data that the frontend renders as Three.js meshes,
plus collision metadata (AABB bounding box) used for path-planning and collision
detection during simulated missions.
"""

import uuid
import time
import math
from typing import Dict, List, Optional, Any


class Obstacle:
    """A single obstacle in an environment."""

    def __init__(
        self,
        *,
        obstacle_type: str = "box",
        position: List[float] = None,
        size: List[float] = None,
        rotation: List[float] = None,
        color: str = "#888888",
        material_props: Dict[str, Any] = None,
        is_collidable: bool = True,
        is_dynamic: bool = False,
        dynamic_config: Dict[str, Any] = None,
        label: str = "",
        obstacle_id: str = None,
        primitives: List[Dict] = None,
    ):
        self.id = obstacle_id or f"obs-{uuid.uuid4().hex[:8]}"
        self.obstacle_type = obstacle_type
        self.position = position or [0, 0, 0]
        self.size = size or [1, 1, 1]
        self.rotation = rotation or [0, 0, 0]
        self.color = color
        self.material_props = material_props or {}
        self.is_collidable = is_collidable
        self.is_dynamic = is_dynamic
        self.dynamic_config = dynamic_config or {}
        self.label = label
        self.primitives = primitives  # Override: raw Three.js primitive list
        self.created_at = time.time()

    def get_aabb(self) -> Dict[str, float]:
        """Axis-aligned bounding box for collision detection."""
        px, py, pz = self.position
        sx, sy, sz = self.size
        half = [sx / 2, sy / 2, sz / 2]
        return {
            "min_x": px - half[0], "max_x": px + half[0],
            "min_y": py - half[1], "max_y": py + half[1],
            "min_z": pz - half[2], "max_z": pz + half[2],
        }

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "obstacle_type": self.obstacle_type,
            "position": self.position,
            "size": self.size,
            "rotation": self.rotation,
            "color": self.color,
            "material_props": self.material_props,
            "is_collidable": self.is_collidable,
            "is_dynamic": self.is_dynamic,
            "dynamic_config": self.dynamic_config,
            "label": self.label,
            "aabb": self.get_aabb(),
        }
        if self.primitives:
            d["primitives"] = self.primitives
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Obstacle":
        return cls(
            obstacle_id=data.get("id"),
            obstacle_type=data.get("obstacle_type", "box"),
            position=data.get("position", [0, 0, 0]),
            size=data.get("size", [1, 1, 1]),
            rotation=data.get("rotation", [0, 0, 0]),
            color=data.get("color", "#888888"),
            material_props=data.get("material_props", {}),
            is_collidable=data.get("is_collidable", True),
            is_dynamic=data.get("is_dynamic", False),
            dynamic_config=data.get("dynamic_config", {}),
            label=data.get("label", ""),
            primitives=data.get("primitives"),
        )


class ObstacleManager:
    """Manages a collection of obstacles for an environment."""

    def __init__(self):
        self.obstacles: Dict[str, Obstacle] = {}

    def add(self, obstacle: Obstacle) -> str:
        self.obstacles[obstacle.id] = obstacle
        return obstacle.id

    def remove(self, obstacle_id: str) -> bool:
        return self.obstacles.pop(obstacle_id, None) is not None

    def get(self, obstacle_id: str) -> Optional[Obstacle]:
        return self.obstacles.get(obstacle_id)

    def update(self, obstacle_id: str, updates: Dict[str, Any]) -> bool:
        obs = self.obstacles.get(obstacle_id)
        if not obs:
            return False
        for key, val in updates.items():
            if hasattr(obs, key) and key not in ("id", "created_at"):
                setattr(obs, key, val)
        return True

    def check_collision(self, point: List[float], radius: float = 0.3) -> List[Dict]:
        """Check if a point (with radius) collides with any obstacle."""
        collisions = []
        px, py, pz = point
        for obs in self.obstacles.values():
            if not obs.is_collidable:
                continue
            aabb = obs.get_aabb()
            # Expanded AABB by radius
            if (px + radius >= aabb["min_x"] and px - radius <= aabb["max_x"] and
                py + radius >= aabb["min_y"] and py - radius <= aabb["max_y"] and
                pz + radius >= aabb["min_z"] and pz - radius <= aabb["max_z"]):
                collisions.append({
                    "obstacle_id": obs.id,
                    "obstacle_type": obs.obstacle_type,
                    "label": obs.label,
                    "position": obs.position,
                })
        return collisions

    def check_path_collisions(
        self, start: List[float], end: List[float], steps: int = 20, radius: float = 0.3
    ) -> List[Dict]:
        """Check a linear path for collisions, return all collision points."""
        collisions = []
        for i in range(steps + 1):
            t = i / steps
            point = [
                start[0] + (end[0] - start[0]) * t,
                start[1] + (end[1] - start[1]) * t,
                start[2] + (end[2] - start[2]) * t,
            ]
            hits = self.check_collision(point, radius)
            if hits:
                collisions.append({"t": t, "point": point, "obstacles": hits})
        return collisions

    def get_dynamic_positions(self, elapsed_time: float) -> Dict[str, List[float]]:
        """Get updated positions for dynamic obstacles at a given time."""
        positions = {}
        for obs in self.obstacles.values():
            if not obs.is_dynamic:
                continue
            cfg = obs.dynamic_config
            motion = cfg.get("motion", "linear")
            speed = cfg.get("speed", 1.0)
            axis = cfg.get("axis", [1, 0, 0])
            amplitude = cfg.get("amplitude", 3.0)
            base = cfg.get("base_position", obs.position[:])

            if motion == "linear":
                phase = (elapsed_time * speed) % (2 * amplitude)
                offset = phase if phase < amplitude else 2 * amplitude - phase
                positions[obs.id] = [
                    base[0] + axis[0] * offset,
                    base[1] + axis[1] * offset,
                    base[2] + axis[2] * offset,
                ]
            elif motion == "circular":
                angle = elapsed_time * speed
                r = amplitude
                positions[obs.id] = [
                    base[0] + r * math.cos(angle),
                    base[1],
                    base[2] + r * math.sin(angle),
                ]
            elif motion == "swing":
                angle = math.sin(elapsed_time * speed) * cfg.get("swing_angle", 1.0)
                positions[obs.id] = [
                    base[0] + amplitude * math.sin(angle),
                    base[1],
                    base[2] + amplitude * math.cos(angle),
                ]
        return positions

    def to_list(self) -> List[Dict]:
        return [obs.to_dict() for obs in self.obstacles.values()]

    @classmethod
    def from_list(cls, data: List[Dict]) -> "ObstacleManager":
        mgr = cls()
        for item in data:
            mgr.add(Obstacle.from_dict(item))
        return mgr
