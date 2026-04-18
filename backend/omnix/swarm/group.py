"""
Robot Group — manages a named set of devices for coordinated control.

A group is the fundamental unit of swarm operations. It holds references
to devices (by ID), assigns roles, and broadcasts commands to all members.
Groups can contain any mix of device types (drones, rovers, arms, etc.).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class RobotRole(str, Enum):
    LEADER = "leader"
    FOLLOWER = "follower"
    SCOUT = "scout"
    GUARD = "guard"
    RELAY = "relay"
    UNASSIGNED = "unassigned"


ROLE_COLORS = {
    RobotRole.LEADER: "#FFD700",      # gold
    RobotRole.FOLLOWER: "#4A90D9",    # blue
    RobotRole.SCOUT: "#4CAF50",       # green
    RobotRole.GUARD: "#E53935",       # red
    RobotRole.RELAY: "#AB47BC",       # purple
    RobotRole.UNASSIGNED: "#9E9E9E",  # grey
}


@dataclass
class GroupMember:
    """A device enrolled in a group with its role and formation slot."""
    device_id: str
    role: RobotRole = RobotRole.UNASSIGNED
    formation_index: int = -1          # slot in the current formation
    joined_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    connected: bool = True

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "role": self.role.value,
            "formation_index": self.formation_index,
            "joined_at": self.joined_at,
            "last_heartbeat": self.last_heartbeat,
            "connected": self.connected,
        }


class RobotGroup:
    """
    A named collection of devices that can be controlled as a unit.

    Operations:
        - add / remove devices
        - assign roles (leader, follower, scout, guard)
        - broadcast a command to every member
        - query aggregate status
    """

    def __init__(self, name: str, description: str = ""):
        self.id: str = str(uuid.uuid4())[:8]
        self.name: str = name
        self.description: str = description
        self.created_at: float = time.time()
        self.members: dict[str, GroupMember] = {}   # device_id → member
        self.formation_type: str | None = None
        self.formation_params: dict = {}
        self.active_mission: str | None = None
        self.mission_state: dict = {}

    # ── membership ──────────────────────────────────────────────────

    def add_device(self, device_id: str, role: RobotRole = RobotRole.UNASSIGNED) -> GroupMember:
        if device_id in self.members:
            raise ValueError(f"Device {device_id} already in group '{self.name}'")
        idx = len(self.members)
        member = GroupMember(device_id=device_id, role=role, formation_index=idx)
        self.members[device_id] = member
        return member

    def remove_device(self, device_id: str) -> bool:
        if device_id not in self.members:
            return False
        del self.members[device_id]
        # Re-index remaining members
        for i, mid in enumerate(self.members):
            self.members[mid].formation_index = i
        return True

    def set_role(self, device_id: str, role: RobotRole) -> bool:
        if device_id not in self.members:
            return False
        self.members[device_id].role = role
        return True

    def get_leader(self) -> str | None:
        for mid, m in self.members.items():
            if m.role == RobotRole.LEADER:
                return mid
        return None

    def device_ids(self) -> list[str]:
        return list(self.members.keys())

    @property
    def size(self) -> int:
        return len(self.members)

    # ── commands ────────────────────────────────────────────────────

    def broadcast_command(self, command: str, params: dict, devices: dict) -> list[dict]:
        """Send a command to every member. `devices` is the global device registry."""
        results = []
        for did in self.members:
            dev = devices.get(did)
            if dev is None:
                results.append({"device_id": did, "success": False, "message": "device not found"})
                continue
            try:
                r = dev.execute_command(command, params or {})
                r["device_id"] = did
                results.append(r)
            except Exception as e:
                results.append({"device_id": did, "success": False, "message": str(e)})
        return results

    # ── heartbeat ───────────────────────────────────────────────────

    def heartbeat(self, device_id: str) -> None:
        if device_id in self.members:
            self.members[device_id].last_heartbeat = time.time()
            self.members[device_id].connected = True

    def check_health(self, timeout: float = 10.0) -> dict[str, bool]:
        """Return {device_id: is_healthy} based on heartbeat freshness."""
        now = time.time()
        status = {}
        for did, m in self.members.items():
            healthy = (now - m.last_heartbeat) < timeout
            m.connected = healthy
            status[did] = healthy
        return status

    # ── serialization ───────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "size": self.size,
            "members": [m.to_dict() for m in self.members.values()],
            "formation_type": self.formation_type,
            "formation_params": self.formation_params,
            "active_mission": self.active_mission,
            "mission_state": self.mission_state,
        }

    def status(self, devices: dict) -> dict:
        """Aggregate status with live telemetry from every member."""
        member_statuses = []
        for did, m in self.members.items():
            dev = devices.get(did)
            entry = m.to_dict()
            if dev:
                entry["name"] = dev.name
                entry["device_type"] = dev.device_type
                entry["telemetry"] = dev.get_telemetry()
                entry["connected"] = dev.connected
            else:
                entry["name"] = "unknown"
                entry["device_type"] = "unknown"
                entry["telemetry"] = {}
                entry["connected"] = False
            entry["role_color"] = ROLE_COLORS.get(m.role, "#9E9E9E")
            member_statuses.append(entry)
        return {
            **self.to_dict(),
            "members": member_statuses,
        }
