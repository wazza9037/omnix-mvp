"""
Multi-robot mission templates.

Each mission is a high-level operational pattern that the SwarmCoordinator
can instantiate for a group. Missions combine formation control, task
allocation, and synchronization into reusable workflows.

Templates:
  1. Area Search     — divide grid, each robot searches a section
  2. Perimeter Patrol — robots spread evenly around a perimeter
  3. Relay Chain     — form a communication relay line
  4. Escort Formation — one central robot escorted by drones
  5. Pick & Deliver  — arm picks, rover transports, arm places
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MissionType(str, Enum):
    AREA_SEARCH = "area_search"
    PERIMETER_PATROL = "perimeter_patrol"
    RELAY_CHAIN = "relay_chain"
    ESCORT = "escort"
    PICK_AND_DELIVER = "pick_and_deliver"


class MissionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


@dataclass
class MissionStep:
    """One atomic step within a mission plan."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    device_id: str = ""
    command: str = ""
    params: dict = field(default_factory=dict)
    description: str = ""
    status: str = "pending"
    started_at: float | None = None
    completed_at: float | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "device_id": self.device_id,
            "command": self.command,
            "params": self.params,
            "description": self.description,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass
class Mission:
    """A multi-robot mission instance."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    type: MissionType = MissionType.AREA_SEARCH
    name: str = ""
    description: str = ""
    group_id: str = ""
    status: MissionStatus = MissionStatus.PENDING
    steps: list[MissionStep] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    results: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "name": self.name,
            "description": self.description,
            "group_id": self.group_id,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "params": self.params,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "results": self.results,
            "progress": self.progress,
        }

    @property
    def progress(self) -> float:
        if not self.steps:
            return 0.0
        done = sum(1 for s in self.steps if s.status in ("completed", "failed"))
        return done / len(self.steps)


# ── Mission planners ────────────────────────────────────────────────

def plan_area_search(device_ids: list[str], params: dict) -> list[MissionStep]:
    """Divide an area into grid cells and assign each robot a section."""
    area_width = float(params.get("width", 100))
    area_height = float(params.get("height", 100))
    center_x = float(params.get("center_x", 0))
    center_y = float(params.get("center_y", 0))
    altitude = float(params.get("altitude", 10))
    n = len(device_ids)
    if n == 0:
        return []

    # Divide into columns (simple vertical strips)
    strip_width = area_width / n
    steps = []

    # Phase 1: All takeoff
    for did in device_ids:
        steps.append(MissionStep(
            device_id=did,
            command="takeoff",
            params={"altitude": altitude},
            description=f"Takeoff to {altitude}m",
        ))

    # Phase 2: Each robot goes to its search zone center
    for i, did in enumerate(device_ids):
        zone_x = center_x - area_width / 2 + strip_width * (i + 0.5)
        zone_y = center_y
        steps.append(MissionStep(
            device_id=did,
            command="go_to",
            params={"x": round(zone_x, 1), "y": round(zone_y, 1), "z": altitude},
            description=f"Go to search zone {i+1} center ({zone_x:.0f}, {zone_y:.0f})",
        ))

    # Phase 3: Patrol within zone (simple back-and-forth)
    for i, did in enumerate(device_ids):
        zone_x = center_x - area_width / 2 + strip_width * (i + 0.5)
        steps.append(MissionStep(
            device_id=did,
            command="patrol",
            params={
                "pattern": "lawnmower",
                "zone_x": round(zone_x, 1),
                "zone_y": round(center_y, 1),
                "zone_width": round(strip_width, 1),
                "zone_height": round(area_height, 1),
            },
            description=f"Search zone {i+1} in lawnmower pattern",
        ))

    # Phase 4: All return and land
    for did in device_ids:
        steps.append(MissionStep(
            device_id=did,
            command="return_home",
            params={},
            description="Return to home position",
        ))
        steps.append(MissionStep(
            device_id=did,
            command="land",
            params={},
            description="Land",
        ))

    return steps


def plan_perimeter_patrol(device_ids: list[str], params: dict) -> list[MissionStep]:
    """Robots spread evenly around a perimeter and patrol in sync."""
    perimeter_radius = float(params.get("radius", 50))
    center_x = float(params.get("center_x", 0))
    center_y = float(params.get("center_y", 0))
    altitude = float(params.get("altitude", 10))
    laps = int(params.get("laps", 3))
    n = len(device_ids)
    if n == 0:
        return []

    steps = []

    # Takeoff all
    for did in device_ids:
        steps.append(MissionStep(
            device_id=did, command="takeoff",
            params={"altitude": altitude},
            description=f"Takeoff to {altitude}m",
        ))

    # Position each robot on the perimeter
    for i, did in enumerate(device_ids):
        angle = 2 * math.pi * i / n
        x = center_x + perimeter_radius * math.cos(angle)
        y = center_y + perimeter_radius * math.sin(angle)
        steps.append(MissionStep(
            device_id=did, command="go_to",
            params={"x": round(x, 1), "y": round(y, 1), "z": altitude},
            description=f"Move to perimeter position {i+1}",
        ))

    # Patrol laps — each robot advances to next position
    for lap in range(laps):
        for i, did in enumerate(device_ids):
            next_i = (i + lap + 1) % n
            angle = 2 * math.pi * next_i / n
            x = center_x + perimeter_radius * math.cos(angle)
            y = center_y + perimeter_radius * math.sin(angle)
            steps.append(MissionStep(
                device_id=did, command="go_to",
                params={"x": round(x, 1), "y": round(y, 1), "z": altitude},
                description=f"Patrol lap {lap+1}, advance to position {next_i+1}",
            ))

    # Land all
    for did in device_ids:
        steps.append(MissionStep(
            device_id=did, command="land", params={},
            description="Land after patrol",
        ))

    return steps


def plan_relay_chain(device_ids: list[str], params: dict) -> list[MissionStep]:
    """Form a communication relay line between two points."""
    start_x = float(params.get("start_x", 0))
    start_y = float(params.get("start_y", 0))
    end_x = float(params.get("end_x", 100))
    end_y = float(params.get("end_y", 0))
    altitude = float(params.get("altitude", 15))
    n = len(device_ids)
    if n == 0:
        return []

    steps = []

    for did in device_ids:
        steps.append(MissionStep(
            device_id=did, command="takeoff",
            params={"altitude": altitude},
            description=f"Takeoff to {altitude}m",
        ))

    # Space robots evenly along the line
    for i, did in enumerate(device_ids):
        t = i / max(1, n - 1)
        x = start_x + t * (end_x - start_x)
        y = start_y + t * (end_y - start_y)
        steps.append(MissionStep(
            device_id=did, command="go_to",
            params={"x": round(x, 1), "y": round(y, 1), "z": altitude},
            description=f"Position as relay node {i+1}/{n}",
        ))

    # Hold position (hover)
    for did in device_ids:
        steps.append(MissionStep(
            device_id=did, command="hover",
            params={"duration": 60},
            description="Hold relay position",
        ))

    return steps


def plan_escort(device_ids: list[str], params: dict) -> list[MissionStep]:
    """One central robot (first) escorted by remaining robots in circle."""
    escort_radius = float(params.get("radius", 5))
    dest_x = float(params.get("dest_x", 50))
    dest_y = float(params.get("dest_y", 50))
    altitude = float(params.get("altitude", 10))

    if len(device_ids) < 2:
        return []

    vip = device_ids[0]
    escorts = device_ids[1:]
    n_esc = len(escorts)
    steps = []

    # Takeoff all
    for did in device_ids:
        steps.append(MissionStep(
            device_id=did, command="takeoff",
            params={"altitude": altitude},
            description="Takeoff for escort mission",
        ))

    # Form escort circle around VIP
    for i, did in enumerate(escorts):
        angle = 2 * math.pi * i / n_esc
        x = escort_radius * math.cos(angle)
        y = escort_radius * math.sin(angle)
        steps.append(MissionStep(
            device_id=did, command="move",
            params={"dx": round(x, 1), "dy": round(y, 1)},
            description=f"Form escort position {i+1}",
        ))

    # VIP moves to destination; escorts follow
    steps.append(MissionStep(
        device_id=vip, command="go_to",
        params={"x": dest_x, "y": dest_y, "z": altitude},
        description=f"VIP moves to destination ({dest_x}, {dest_y})",
    ))

    for i, did in enumerate(escorts):
        angle = 2 * math.pi * i / n_esc
        x = dest_x + escort_radius * math.cos(angle)
        y = dest_y + escort_radius * math.sin(angle)
        steps.append(MissionStep(
            device_id=did, command="go_to",
            params={"x": round(x, 1), "y": round(y, 1), "z": altitude},
            description=f"Escort {i+1} follows to destination",
        ))

    # Land all
    for did in device_ids:
        steps.append(MissionStep(
            device_id=did, command="land", params={},
            description="Land after escort complete",
        ))

    return steps


def plan_pick_and_deliver(device_ids: list[str], params: dict) -> list[MissionStep]:
    """Arm picks up object, rover transports, arm places at destination."""
    pickup_x = float(params.get("pickup_x", 0))
    pickup_y = float(params.get("pickup_y", 0))
    dropoff_x = float(params.get("dropoff_x", 20))
    dropoff_y = float(params.get("dropoff_y", 20))

    # Assumes: first device is arm (picker), second is rover (transport),
    # third (optional) is arm at destination
    steps = []

    arm_id = device_ids[0] if len(device_ids) > 0 else None
    rover_id = device_ids[1] if len(device_ids) > 1 else None
    dest_arm_id = device_ids[2] if len(device_ids) > 2 else None

    if arm_id:
        steps.append(MissionStep(
            device_id=arm_id, command="grip",
            params={"force": 50},
            description="Pick up object",
        ))

    if rover_id:
        steps.append(MissionStep(
            device_id=rover_id, command="go_to",
            params={"x": pickup_x, "y": pickup_y},
            description="Rover moves to pickup location",
        ))

    if arm_id:
        steps.append(MissionStep(
            device_id=arm_id, command="release",
            params={},
            description="Place object on rover",
        ))

    if rover_id:
        steps.append(MissionStep(
            device_id=rover_id, command="go_to",
            params={"x": dropoff_x, "y": dropoff_y},
            description="Rover transports to dropoff location",
        ))

    if dest_arm_id:
        steps.append(MissionStep(
            device_id=dest_arm_id, command="grip",
            params={"force": 50},
            description="Destination arm picks up object",
        ))
        steps.append(MissionStep(
            device_id=dest_arm_id, command="release",
            params={},
            description="Place object at final position",
        ))

    return steps


# ── Mission planner registry ────────────────────────────────────────

_PLANNERS = {
    MissionType.AREA_SEARCH: plan_area_search,
    MissionType.PERIMETER_PATROL: plan_perimeter_patrol,
    MissionType.RELAY_CHAIN: plan_relay_chain,
    MissionType.ESCORT: plan_escort,
    MissionType.PICK_AND_DELIVER: plan_pick_and_deliver,
}


# ── Mission template metadata (for UI) ─────────────────────────────

MISSION_TEMPLATES: dict[str, dict] = {
    "area_search": {
        "type": "area_search",
        "name": "Area Search",
        "description": "Divide area into grid, each robot searches a section",
        "icon": "🔍",
        "min_robots": 2,
        "params": {
            "width": {"type": "number", "default": 100, "label": "Area Width (m)"},
            "height": {"type": "number", "default": 100, "label": "Area Height (m)"},
            "center_x": {"type": "number", "default": 0, "label": "Center X"},
            "center_y": {"type": "number", "default": 0, "label": "Center Y"},
            "altitude": {"type": "number", "default": 10, "label": "Altitude (m)"},
        },
    },
    "perimeter_patrol": {
        "type": "perimeter_patrol",
        "name": "Perimeter Patrol",
        "description": "Robots spread evenly around a perimeter, patrol in sync",
        "icon": "🛡️",
        "min_robots": 2,
        "params": {
            "radius": {"type": "number", "default": 50, "label": "Perimeter Radius (m)"},
            "center_x": {"type": "number", "default": 0, "label": "Center X"},
            "center_y": {"type": "number", "default": 0, "label": "Center Y"},
            "altitude": {"type": "number", "default": 10, "label": "Altitude (m)"},
            "laps": {"type": "number", "default": 3, "label": "Patrol Laps"},
        },
    },
    "relay_chain": {
        "type": "relay_chain",
        "name": "Relay Chain",
        "description": "Form a communication relay line between two points",
        "icon": "📡",
        "min_robots": 2,
        "params": {
            "start_x": {"type": "number", "default": 0, "label": "Start X"},
            "start_y": {"type": "number", "default": 0, "label": "Start Y"},
            "end_x": {"type": "number", "default": 100, "label": "End X"},
            "end_y": {"type": "number", "default": 0, "label": "End Y"},
            "altitude": {"type": "number", "default": 15, "label": "Altitude (m)"},
        },
    },
    "escort": {
        "type": "escort",
        "name": "Escort Formation",
        "description": "One central robot escorted by drones in formation",
        "icon": "🛡️",
        "min_robots": 2,
        "params": {
            "radius": {"type": "number", "default": 5, "label": "Escort Radius (m)"},
            "dest_x": {"type": "number", "default": 50, "label": "Destination X"},
            "dest_y": {"type": "number", "default": 50, "label": "Destination Y"},
            "altitude": {"type": "number", "default": 10, "label": "Altitude (m)"},
        },
    },
    "pick_and_deliver": {
        "type": "pick_and_deliver",
        "name": "Pick & Deliver",
        "description": "Arm picks, rover transports, arm places at destination",
        "icon": "📦",
        "min_robots": 2,
        "params": {
            "pickup_x": {"type": "number", "default": 0, "label": "Pickup X"},
            "pickup_y": {"type": "number", "default": 0, "label": "Pickup Y"},
            "dropoff_x": {"type": "number", "default": 20, "label": "Dropoff X"},
            "dropoff_y": {"type": "number", "default": 20, "label": "Dropoff Y"},
        },
    },
}


def create_mission(mission_type: str, group_id: str, device_ids: list[str],
                   params: dict | None = None) -> Mission:
    """Create a mission instance with planned steps."""
    mt = MissionType(mission_type)
    planner = _PLANNERS.get(mt)
    if planner is None:
        raise ValueError(f"No planner for mission type: {mission_type}")

    template = MISSION_TEMPLATES.get(mission_type, {})
    steps = planner(device_ids, params or {})

    return Mission(
        type=mt,
        name=template.get("name", mission_type),
        description=template.get("description", ""),
        group_id=group_id,
        steps=steps,
        params=params or {},
    )
