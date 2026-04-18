"""
CustomBuild — the assembled state of a user's robot.

Takes a list of Parts and produces:

  - A **derived device_type** (drone / ground_robot / robot_arm / …) by
    counting part occurrences and applying priority rules.
  - A list of **DeviceCapability** objects the assembled robot exposes,
    matching the commands the CustomRobotDevice knows how to handle.
  - **mesh_params** — the same shape the VPE emits, so the Three.js
    viewer can render a CustomBuild with the existing mesh builder.
  - A **movement preset** list compatible with the scenario runner.

Capability rules (ordered; first match wins for device_type):

    >=4 rotors                                → drone
    >=1 wing  + >=1 rotor                     → fixed-wing drone
    >=3 legs                                  → legged robot
    >=1 leg (2-4) + no wheels                 → humanoid / quadruped
    >=2 wheels                                → ground_robot
    >=1 propeller + !wings                    → marine
    >=3 joints + no wheels + no rotors        → robot_arm
    >=1 gripper only                          → robot_arm (gripper dev)
    default                                   → custom / generic
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any

from .parts import Part, PART_TYPES, PartType


@dataclass
class CustomBuild:
    """A user-assembled robot description."""
    parts: list[Part] = field(default_factory=list)
    reference_image: str | None = None      # base64 dataurl
    reference_opacity: float = 0.45
    show_reference: bool = True
    last_modified: float = field(default_factory=time.time)

    # ── Serialization ─────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "parts": [p.to_dict() for p in self.parts],
            "reference_image": self.reference_image,
            "reference_opacity": self.reference_opacity,
            "show_reference": self.show_reference,
            "last_modified": self.last_modified,
            "part_counts": self.part_counts(),
            "device_type": self.derive_device_type(),
            "capabilities": [c.to_dict() for c in self.derive_capabilities()],
            "mesh_params": self.to_mesh_params(),
        }

    @staticmethod
    def from_dict(d: dict | None) -> "CustomBuild":
        if not d:
            return CustomBuild()
        parts = [Part.from_dict(p) for p in d.get("parts", [])]
        return CustomBuild(
            parts=parts,
            reference_image=d.get("reference_image"),
            reference_opacity=float(d.get("reference_opacity", 0.45)),
            show_reference=bool(d.get("show_reference", True)),
            last_modified=float(d.get("last_modified", time.time())),
        )

    # ── Part-count helpers ────────────────────────────────

    def part_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for p in self.parts:
            counts[p.type] = counts.get(p.type, 0) + 1
        return counts

    def _has(self, kind: str, n: int = 1) -> bool:
        return self.part_counts().get(kind, 0) >= n

    # ── Device type ───────────────────────────────────────

    def derive_device_type(self) -> str:
        """First rule that matches wins. Keep the list short + auditable."""
        if self._has("rotor", 4) and not self._has("wing"):
            return "drone"
        if self._has("wing", 1) and self._has("rotor", 1):
            return "drone"                    # fixed-wing still uses drone presets
        if self._has("propeller") and not self._has("wing"):
            return "marine"
        if self._has("leg", 4):
            return "legged"
        if self._has("leg", 2) and not self._has("wheel"):
            return "humanoid"
        if self._has("wheel", 2):
            return "ground_robot"
        if self._has("joint", 3) and not self._has("rotor") and not self._has("wheel"):
            return "robot_arm"
        if self._has("gripper") and not self._has("rotor") and not self._has("wheel"):
            return "robot_arm"
        return "custom"

    # ── Capabilities ──────────────────────────────────────

    def derive_capabilities(self) -> list["_BuildCapability"]:
        """Every commanding capability the assembled device exposes.

        We lean on the DeviceCapability shape OmnixDevice already accepts,
        so routes/UI need no changes.
        """
        caps: list[_BuildCapability] = []
        pc = self.part_counts()

        # Flight (quadcopter / fixed-wing)
        if pc.get("rotor", 0) >= 4 or (pc.get("rotor", 0) >= 1 and pc.get("wing", 0) >= 1):
            caps.append(_BuildCapability(
                name="takeoff", description="Take off to altitude",
                parameters={"altitude_m": {"type": "number", "min": 1, "max": 50, "default": 5}},
                category="flight"))
            caps.append(_BuildCapability(
                name="land", description="Land at current position",
                parameters={}, category="flight"))
            caps.append(_BuildCapability(
                name="hover", description="Hold current position",
                parameters={}, category="flight"))
            caps.append(_BuildCapability(
                name="move", description="Translate in a direction",
                parameters={
                    "direction": {"type": "select",
                                  "options": ["forward", "backward", "left", "right", "up", "down"]},
                    "distance_m": {"type": "number", "min": 0.5, "max": 50, "default": 2},
                },
                category="flight"))

        # Ground drive
        if pc.get("wheel", 0) >= 2:
            caps.append(_BuildCapability(
                name="drive", description="Drive the robot",
                parameters={
                    "direction": {"type": "select",
                                  "options": ["forward", "backward", "left", "right", "stop"]},
                    "speed": {"type": "number", "min": 0, "max": 100, "default": 50},
                    "duration_ms": {"type": "number", "min": 0, "max": 10000, "default": 1000},
                },
                category="movement"))

        # Legged locomotion
        if pc.get("leg", 0) >= 3:
            caps.append(_BuildCapability(
                name="walk", description="Walk in a direction",
                parameters={
                    "direction": {"type": "select",
                                  "options": ["forward", "backward", "left", "right", "stop"]},
                    "gait": {"type": "select",
                             "options": ["trot", "walk", "amble"]},
                },
                category="movement"))
            caps.append(_BuildCapability(
                name="stand", description="Stand up / lock stance",
                parameters={}, category="movement"))

        # Marine thrust
        if pc.get("propeller", 0) >= 1:
            caps.append(_BuildCapability(
                name="thrust", description="Apply propeller thrust",
                parameters={"level": {"type": "number", "min": -100, "max": 100, "default": 50}},
                category="movement"))

        # Articulation (robot arm)
        joint_n = pc.get("joint", 0)
        if joint_n >= 3:
            caps.append(_BuildCapability(
                name="move_joint", description="Move one joint",
                parameters={
                    "joint_index": {"type": "number", "min": 0, "max": joint_n - 1, "default": 0},
                    "angle_deg": {"type": "number", "min": -180, "max": 180, "default": 0},
                },
                category="movement"))
            caps.append(_BuildCapability(
                name="go_home", description="Return to home pose",
                parameters={}, category="movement"))

        # End effector
        if pc.get("gripper", 0) >= 1:
            caps.append(_BuildCapability(
                name="grip", description="Close gripper",
                parameters={"force": {"type": "number", "min": 0, "max": 100, "default": 50}},
                category="effector"))
            caps.append(_BuildCapability(
                name="release", description="Open gripper",
                parameters={}, category="effector"))

        # Sensing
        if pc.get("sensor", 0) >= 1:
            caps.append(_BuildCapability(
                name="scan", description="Take a sensor sample",
                parameters={}, category="sensors"))

        # Imaging
        if pc.get("camera", 0) >= 1:
            caps.append(_BuildCapability(
                name="take_photo", description="Capture a photo",
                parameters={}, category="sensors"))

        # Always-on
        caps.append(_BuildCapability(
            name="emergency_stop", description="Kill all actuators immediately",
            parameters={}, category="safety"))
        caps.append(_BuildCapability(
            name="ping", description="Heartbeat check",
            parameters={}, category="diag"))

        return caps

    # ── Mesh params (Three.js primitives) ─────────────────

    def to_mesh_params(self) -> dict:
        """Convert the parts list into the mesh_params dict the frontend
        already knows how to render (same shape VPE emits)."""
        primitives = []
        for p in self.parts:
            pt = PART_TYPES.get(p.type)
            if pt is None:
                continue
            mat = {
                "color": p.color,
                "metalness": p.material.get("metalness", 0.3),
                "roughness": p.material.get("roughness", 0.5),
            }
            if "emissive" in p.material:
                mat["emissive"] = p.material["emissive"]
                mat["emissiveIntensity"] = p.material.get("emissive_intensity", 0.3)

            primitives.append({
                "type": pt.geometry_type,
                "geometry": dict(p.geometry),
                "material": mat,
                "position": list(p.position),
                "rotation": list(p.rotation),
                "name": f"{p.type}:{p.name}",
                "part_id": p.part_id,
            })

        # Bounding size for camera fitting
        bsize = 2.0
        if primitives:
            max_ext = 0.0
            for pr in primitives:
                g = pr.get("geometry") or {}
                ext = max(g.get("w", 0), g.get("h", 0), g.get("d", 0),
                          g.get("r", 0) * 2, g.get("rb", 0) * 2, g.get("rt", 0) * 2)
                pos = pr.get("position") or [0, 0, 0]
                span = ext + max(abs(pos[0]), abs(pos[1]), abs(pos[2]))
                if span > max_ext: max_ext = span
            bsize = max(2.0, max_ext * 1.2)

        return {
            "primitives": primitives,
            "device_category": self.derive_device_type(),
            "device_type": self.derive_device_type(),
            "scale": [bsize, bsize, bsize],
            "bounding_size": bsize,
            "is_custom_build": True,
        }


# A minimal DeviceCapability-compatible dataclass — keeps this module
# import-free from devices/base.py so it can be tested standalone.
@dataclass
class _BuildCapability:
    name: str
    description: str
    parameters: dict = field(default_factory=dict)
    category: str = "general"

    def to_dict(self) -> dict:
        return asdict(self)


def derive_device_name_hint(build: CustomBuild) -> str:
    """Pick a friendly default name for a newly-built device."""
    dt = build.derive_device_type()
    counts = build.part_counts()
    if dt == "drone":
        return f"Custom {counts.get('rotor', 4)}-rotor Drone"
    if dt == "legged":
        return f"Custom {counts.get('leg', 4)}-leg Robot"
    if dt == "humanoid":
        return "Custom Biped"
    if dt == "ground_robot":
        return "Custom Rover"
    if dt == "robot_arm":
        return f"Custom {counts.get('joint', 3)}-DOF Arm"
    if dt == "marine":
        return "Custom Submersible"
    return "Custom Robot"
