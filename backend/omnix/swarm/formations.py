"""
Pre-built formation patterns for multi-robot coordination.

Each formation computes target positions for N robots given a center
point and configurable parameters. Formations are purely geometric —
they produce (x, y, z) offsets that the coordinator applies relative
to the group center or leader position.

Supported formations:
  - Line:   robots side-by-side, configurable spacing
  - Circle: evenly spaced on a circle, configurable radius
  - V-shape: classic flying-V, configurable angle + spacing
  - Grid:   rows × cols rectangular arrangement
  - Custom: user supplies explicit waypoints per robot
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FormationType(str, Enum):
    LINE = "line"
    CIRCLE = "circle"
    V_SHAPE = "v_shape"
    GRID = "grid"
    CUSTOM = "custom"


@dataclass
class FormationSlot:
    """One robot's target offset within a formation."""
    index: int
    offset_x: float       # meters from center
    offset_y: float
    offset_z: float = 0.0
    heading: float = 0.0  # degrees, 0 = north

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "offset_x": round(self.offset_x, 3),
            "offset_y": round(self.offset_y, 3),
            "offset_z": round(self.offset_z, 3),
            "heading": round(self.heading, 1),
        }


@dataclass
class Formation:
    """A formation definition with parameters and slot calculator."""
    type: FormationType
    name: str
    description: str
    icon: str = "⬜"
    default_params: dict = field(default_factory=dict)

    def compute_slots(self, count: int, params: dict | None = None) -> list[FormationSlot]:
        """Compute formation slots for `count` robots with given params."""
        p = {**self.default_params, **(params or {})}
        fn = _SLOT_CALCULATORS.get(self.type)
        if fn is None:
            raise ValueError(f"No calculator for formation type {self.type}")
        return fn(count, p)

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "name": self.name,
            "description": self.description,
            "icon": self.icon,
            "default_params": self.default_params,
        }


# ── Slot calculators ────────────────────────────────────────────────

def _line_slots(count: int, params: dict) -> list[FormationSlot]:
    """Robots in a straight line, centered on origin."""
    spacing = float(params.get("spacing", 3.0))
    axis = params.get("axis", "x")  # "x" or "y"
    slots = []
    start = -spacing * (count - 1) / 2.0
    for i in range(count):
        offset = start + i * spacing
        if axis == "y":
            slots.append(FormationSlot(index=i, offset_x=0, offset_y=offset))
        else:
            slots.append(FormationSlot(index=i, offset_x=offset, offset_y=0))
    return slots


def _circle_slots(count: int, params: dict) -> list[FormationSlot]:
    """Robots evenly spaced on a circle, all facing center."""
    radius = float(params.get("radius", 5.0))
    start_angle = float(params.get("start_angle", 0))  # degrees
    slots = []
    for i in range(count):
        angle_rad = math.radians(start_angle + 360.0 * i / count)
        x = radius * math.cos(angle_rad)
        y = radius * math.sin(angle_rad)
        heading = math.degrees(math.atan2(-y, -x)) % 360  # face center
        slots.append(FormationSlot(index=i, offset_x=x, offset_y=y, heading=heading))
    return slots


def _v_shape_slots(count: int, params: dict) -> list[FormationSlot]:
    """V-formation (flying-V). Index 0 = tip. Arms alternate left/right."""
    angle = float(params.get("angle", 30))   # half-angle in degrees
    spacing = float(params.get("spacing", 3.0))
    slots = [FormationSlot(index=0, offset_x=0, offset_y=0)]
    for i in range(1, count):
        arm = (i + 1) // 2                   # distance from tip
        side = 1 if i % 2 == 1 else -1       # alternate L/R
        rad = math.radians(angle)
        x = side * arm * spacing * math.sin(rad)
        y = -arm * spacing * math.cos(rad)   # behind the leader
        slots.append(FormationSlot(index=i, offset_x=x, offset_y=y))
    return slots


def _grid_slots(count: int, params: dict) -> list[FormationSlot]:
    """Rectangular grid formation. Fills row by row, centered."""
    cols = int(params.get("cols", max(1, int(math.ceil(math.sqrt(count))))))
    spacing_x = float(params.get("spacing_x", 3.0))
    spacing_y = float(params.get("spacing_y", 3.0))
    rows = math.ceil(count / cols)
    slots = []
    for i in range(count):
        r = i // cols
        c = i % cols
        # Center the grid on the origin
        cols_this_row = min(cols, count - r * cols)
        x = (c - (cols_this_row - 1) / 2.0) * spacing_x
        y = (r - (rows - 1) / 2.0) * spacing_y
        slots.append(FormationSlot(index=i, offset_x=x, offset_y=y))
    return slots


def _custom_slots(count: int, params: dict) -> list[FormationSlot]:
    """User-defined waypoints. `params.waypoints` = [{x, y, z?, heading?}, ...]."""
    waypoints = params.get("waypoints", [])
    slots = []
    for i in range(count):
        if i < len(waypoints):
            wp = waypoints[i]
            slots.append(FormationSlot(
                index=i,
                offset_x=float(wp.get("x", 0)),
                offset_y=float(wp.get("y", 0)),
                offset_z=float(wp.get("z", 0)),
                heading=float(wp.get("heading", 0)),
            ))
        else:
            # Extra robots with no explicit waypoint — stack at origin
            slots.append(FormationSlot(index=i, offset_x=0, offset_y=i * 2.0))
    return slots


_SLOT_CALCULATORS = {
    FormationType.LINE: _line_slots,
    FormationType.CIRCLE: _circle_slots,
    FormationType.V_SHAPE: _v_shape_slots,
    FormationType.GRID: _grid_slots,
    FormationType.CUSTOM: _custom_slots,
}


# ── Pre-built formation registry ────────────────────────────────────

FORMATIONS: dict[str, Formation] = {
    "line": Formation(
        type=FormationType.LINE,
        name="Line Formation",
        description="Robots in a straight line with configurable spacing",
        icon="━━━",
        default_params={"spacing": 3.0, "axis": "x"},
    ),
    "circle": Formation(
        type=FormationType.CIRCLE,
        name="Circle Formation",
        description="Robots evenly spaced on a circle",
        icon="⭕",
        default_params={"radius": 5.0, "start_angle": 0},
    ),
    "v_shape": Formation(
        type=FormationType.V_SHAPE,
        name="V-Formation",
        description="Classic flying-V, ideal for drones",
        icon="✌️",
        default_params={"angle": 30, "spacing": 3.0},
    ),
    "grid": Formation(
        type=FormationType.GRID,
        name="Grid Formation",
        description="Rectangular grid arrangement",
        icon="⊞",
        default_params={"cols": 3, "spacing_x": 3.0, "spacing_y": 3.0},
    ),
    "custom": Formation(
        type=FormationType.CUSTOM,
        name="Custom Formation",
        description="User places each robot manually",
        icon="📍",
        default_params={"waypoints": []},
    ),
}


def compute_formation(formation_type: str, count: int, params: dict | None = None) -> list[dict]:
    """Public helper: compute slot positions for a formation."""
    f = FORMATIONS.get(formation_type)
    if f is None:
        raise ValueError(f"Unknown formation type: {formation_type}")
    slots = f.compute_slots(count, params)
    return [s.to_dict() for s in slots]
