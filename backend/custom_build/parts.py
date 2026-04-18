"""
Part type registry for the Custom Robot Builder.

A Part is the atomic unit a user snaps together to build a robot. Every
part has:

  - A **type** (e.g., "rotor", "wheel") that determines its geometry,
    default material, and UI icon.
  - A **geometry dict** that the Three.js frontend interprets to build
    the actual mesh. Keys depend on geometry_type:
        box       → {w, h, d}
        sphere    → {r}
        cylinder  → {rt, rb, h}   (top radius, bottom radius, height)
        torus     → {r, tube}
        cone      → {r, h}
  - **Position**, **rotation**, **color**, **material** (metalness/roughness).
  - An **order** field so the part list in the UI is deterministic.

The registry also records `capability_contributions` — how many of each
part type are needed to unlock a functional capability on the assembled
device. When a build has enough parts of the right kinds, the derived
OmnixDevice gets those capabilities automatically.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


# ─────────────────────────────────────────────────────────
#  Part type registry
# ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PartType:
    """Static definition of what a given kind of part looks and acts like."""
    id: str                           # "rotor", "chassis", …
    display_name: str
    category: str                     # "structural" | "actuator" | "sensor" | "effector"
    geometry_type: str                # "box" | "sphere" | "cylinder" | "torus" | "cone"
    default_geometry: dict[str, float]
    default_color: str
    default_material: dict[str, float]
    icon: str
    description: str
    # Snap hint: where a fresh part of this type should land when added.
    # Relative to the current build's bounding center.
    default_offset: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["default_offset"] = list(d["default_offset"])
        return d


PART_TYPES: dict[str, PartType] = {
    "chassis": PartType(
        id="chassis",
        display_name="Chassis",
        category="structural",
        geometry_type="box",
        default_geometry={"w": 1.2, "h": 0.3, "d": 0.8},
        default_color="#3a4d6b",
        default_material={"metalness": 0.55, "roughness": 0.4},
        icon="📦",
        description="Main body of the robot — everything attaches to it.",
        default_offset=(0.0, 0.2, 0.0),
    ),
    "rotor": PartType(
        id="rotor",
        display_name="Rotor",
        category="actuator",
        geometry_type="torus",
        default_geometry={"r": 0.4, "tube": 0.035},
        default_color="#00b4d8",
        default_material={"metalness": 0.6, "roughness": 0.3,
                          "emissive": "#00b4d8", "emissive_intensity": 0.35},
        icon="🌀",
        description="Spinning propeller — 4+ of these unlock flight.",
        default_offset=(0.0, 0.4, 0.0),
    ),
    "arm": PartType(
        id="arm",
        display_name="Arm segment",
        category="structural",
        geometry_type="cylinder",
        default_geometry={"rt": 0.06, "rb": 0.06, "h": 1.1},
        default_color="#555c6e",
        default_material={"metalness": 0.5, "roughness": 0.45},
        icon="📏",
        description="Rigid strut — connects joints, rotors, frames.",
        default_offset=(0.0, 0.4, 0.0),
    ),
    "joint": PartType(
        id="joint",
        display_name="Joint",
        category="actuator",
        geometry_type="sphere",
        default_geometry={"r": 0.12},
        default_color="#222831",
        default_material={"metalness": 0.7, "roughness": 0.35},
        icon="⚙️",
        description="Articulation point. 3+ joints → robot-arm control.",
        default_offset=(0.0, 0.8, 0.0),
    ),
    "wheel": PartType(
        id="wheel",
        display_name="Wheel",
        category="actuator",
        geometry_type="cylinder",
        default_geometry={"rt": 0.22, "rb": 0.22, "h": 0.1},
        default_color="#181a1f",
        default_material={"metalness": 0.25, "roughness": 0.8},
        icon="🛞",
        description="Rolling element. 2+ wheels → drive capability.",
        default_offset=(0.5, 0.0, 0.4),
    ),
    "leg": PartType(
        id="leg",
        display_name="Leg",
        category="structural",
        geometry_type="box",
        default_geometry={"w": 0.12, "h": 0.7, "d": 0.12},
        default_color="#3d4552",
        default_material={"metalness": 0.45, "roughness": 0.55},
        icon="🦿",
        description="Limb. 4+ → quadruped; 6+ → hexapod.",
        default_offset=(0.5, 0.0, 0.4),
    ),
    "gripper": PartType(
        id="gripper",
        display_name="Gripper",
        category="effector",
        geometry_type="cone",
        default_geometry={"r": 0.12, "h": 0.25},
        default_color="#10b981",
        default_material={"metalness": 0.3, "roughness": 0.4,
                          "emissive": "#10b981", "emissive_intensity": 0.2},
        icon="🤏",
        description="End effector — adds pick/place commands.",
        default_offset=(0.0, 1.4, 0.0),
    ),
    "sensor": PartType(
        id="sensor",
        display_name="Sensor",
        category="sensor",
        geometry_type="box",
        default_geometry={"w": 0.16, "h": 0.08, "d": 0.12},
        default_color="#f59e0b",
        default_material={"metalness": 0.3, "roughness": 0.4,
                          "emissive": "#f59e0b", "emissive_intensity": 0.3},
        icon="📡",
        description="Generic sensor — adds scan/sample commands.",
        default_offset=(0.0, 0.6, 0.0),
    ),
    "camera": PartType(
        id="camera",
        display_name="Camera",
        category="sensor",
        geometry_type="cylinder",
        default_geometry={"rt": 0.08, "rb": 0.08, "h": 0.12},
        default_color="#111318",
        default_material={"metalness": 0.8, "roughness": 0.15,
                          "emissive": "#00b4d8", "emissive_intensity": 0.15},
        icon="📷",
        description="Optical sensor — adds take_photo + streaming.",
        default_offset=(0.0, 0.5, 0.45),
    ),
    "wing": PartType(
        id="wing",
        display_name="Wing",
        category="structural",
        geometry_type="box",
        default_geometry={"w": 2.4, "h": 0.05, "d": 0.4},
        default_color="#aab0bc",
        default_material={"metalness": 0.35, "roughness": 0.55},
        icon="✈️",
        description="Aerodynamic surface — enables fixed-wing flight.",
        default_offset=(0.0, 0.3, 0.0),
    ),
    "propeller": PartType(
        id="propeller",
        display_name="Propeller (thrust)",
        category="actuator",
        geometry_type="torus",
        default_geometry={"r": 0.22, "tube": 0.025},
        default_color="#f59e0b",
        default_material={"metalness": 0.55, "roughness": 0.3,
                          "emissive": "#f59e0b", "emissive_intensity": 0.2},
        icon="🌊",
        description="Thrust propeller — marine/underwater propulsion.",
        default_offset=(0.0, 0.2, -0.5),
    ),
}


def all_part_types() -> list[dict]:
    """JSON-friendly listing of every part type (for the frontend palette)."""
    return [pt.to_dict() for pt in PART_TYPES.values()]


def get_part_type(type_id: str) -> PartType | None:
    return PART_TYPES.get(type_id)


# ─────────────────────────────────────────────────────────
#  Part instance — a single part in a CustomBuild
# ─────────────────────────────────────────────────────────

@dataclass
class Part:
    """One concrete part in a user's build."""
    part_id: str
    type: str                            # one of PART_TYPES keys
    name: str
    geometry: dict[str, float]
    position: list[float]                # [x, y, z]
    rotation: list[float]                # [rx, ry, rz] radians
    color: str
    material: dict[str, float]
    order: int = 0

    @staticmethod
    def new(type_id: str, *,
            name: str | None = None,
            position: tuple | list | None = None,
            order: int = 0) -> "Part":
        """Create a fresh part instance using the type's defaults."""
        pt = PART_TYPES.get(type_id)
        if pt is None:
            raise ValueError(f"Unknown part type '{type_id}'")
        return Part(
            part_id=f"p-{uuid.uuid4().hex[:8]}",
            type=type_id,
            name=name or pt.display_name,
            geometry=dict(pt.default_geometry),
            position=list(position) if position is not None else list(pt.default_offset),
            rotation=[0.0, 0.0, 0.0],
            color=pt.default_color,
            material=dict(pt.default_material),
            order=order,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Part":
        return Part(
            part_id=d.get("part_id", f"p-{uuid.uuid4().hex[:8]}"),
            type=d["type"],
            name=d.get("name", PART_TYPES[d["type"]].display_name),
            geometry=dict(d.get("geometry") or PART_TYPES[d["type"]].default_geometry),
            position=list(d.get("position", [0.0, 0.0, 0.0])),
            rotation=list(d.get("rotation", [0.0, 0.0, 0.0])),
            color=d.get("color", PART_TYPES[d["type"]].default_color),
            material=dict(d.get("material") or PART_TYPES[d["type"]].default_material),
            order=int(d.get("order", 0)),
        )
