"""
Swarm Coordinator — orchestrates multi-robot tasks.

The coordinator is the central brain that ties together groups, formations,
missions, and sync primitives. It translates high-level intents ("search
this area", "form a circle") into concrete device commands.

Key capabilities:
  - Formation control: position robots in geometric patterns
  - Task allocation: split areas into zones, assign each robot a zone
  - Synchronized actions: coordinated takeoff/land/movements
  - Leader-follower: one robot leads, others maintain relative positions
  - Coverage planning: divide area into cells, assign efficiently
  - Mission execution: run multi-step mission templates
"""

from __future__ import annotations

import math
import time
import threading
import uuid
from typing import Any

from .group import RobotGroup, RobotRole
from .formations import FORMATIONS, compute_formation, FormationType
from .missions import (
    Mission, MissionStatus, MissionType, MISSION_TEMPLATES,
    create_mission,
)
from .sync import SyncManager, Barrier, Countdown


class SwarmCoordinator:
    """
    Process-wide swarm coordinator. Manages all robot groups
    and orchestrates multi-robot operations.
    """

    def __init__(self):
        self.groups: dict[str, RobotGroup] = {}
        self.missions: dict[str, Mission] = {}       # mission_id → mission
        self.sync: SyncManager = SyncManager()
        self._mission_threads: dict[str, threading.Thread] = {}
        self._stop_flags: dict[str, bool] = {}
        self._lock = threading.Lock()

    # ── Group management ────────────────────────────────────────────

    def create_group(self, name: str, description: str = "") -> RobotGroup:
        group = RobotGroup(name=name, description=description)
        with self._lock:
            self.groups[group.id] = group
        return group

    def delete_group(self, group_id: str) -> bool:
        with self._lock:
            if group_id in self.groups:
                del self.groups[group_id]
                # Clean up sync state
                self.sync.heartbeats.pop(group_id, None)
                self.sync.reformations.pop(group_id, None)
                return True
        return False

    def get_group(self, group_id: str) -> RobotGroup | None:
        return self.groups.get(group_id)

    def list_groups(self) -> list[dict]:
        return [g.to_dict() for g in self.groups.values()]

    def add_device_to_group(self, group_id: str, device_id: str,
                            role: str = "unassigned") -> dict:
        group = self.groups.get(group_id)
        if group is None:
            return {"ok": False, "error": "group not found"}
        try:
            r = RobotRole(role)
        except ValueError:
            r = RobotRole.UNASSIGNED
        try:
            member = group.add_device(device_id, r)
            # Update heartbeat tracker
            hb = self.sync.ensure_heartbeat(group_id, group.device_ids())
            hb.add_device(device_id)
            return {"ok": True, "member": member.to_dict()}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    def remove_device_from_group(self, group_id: str, device_id: str) -> dict:
        group = self.groups.get(group_id)
        if group is None:
            return {"ok": False, "error": "group not found"}
        removed = group.remove_device(device_id)
        if removed:
            hb = self.sync.heartbeats.get(group_id)
            if hb:
                hb.remove_device(device_id)
        return {"ok": removed}

    def set_device_role(self, group_id: str, device_id: str, role: str) -> dict:
        group = self.groups.get(group_id)
        if group is None:
            return {"ok": False, "error": "group not found"}
        try:
            r = RobotRole(role)
        except ValueError:
            return {"ok": False, "error": f"invalid role: {role}"}
        return {"ok": group.set_role(device_id, r)}

    # ── Formation control ───────────────────────────────────────────

    def set_formation(self, group_id: str, formation_type: str,
                      params: dict | None = None, devices: dict | None = None) -> dict:
        """
        Set a group's formation and optionally command robots to move
        to their formation positions.
        """
        group = self.groups.get(group_id)
        if group is None:
            return {"ok": False, "error": "group not found"}

        if formation_type not in FORMATIONS:
            return {"ok": False, "error": f"unknown formation: {formation_type}"}

        slots = compute_formation(formation_type, group.size, params)
        group.formation_type = formation_type
        group.formation_params = params or {}

        # Update formation indices
        member_ids = group.device_ids()
        for i, did in enumerate(member_ids):
            if i < len(slots):
                group.members[did].formation_index = slots[i]["index"]

        result = {
            "ok": True,
            "formation": formation_type,
            "slots": slots,
            "commands_sent": [],
        }

        # If devices dict provided, command robots to formation positions
        if devices:
            # Use group center or leader position as reference
            leader_id = group.get_leader()
            ref_x, ref_y, ref_z = 0.0, 0.0, 0.0
            if leader_id and leader_id in devices:
                tel = devices[leader_id].get_telemetry()
                pos = tel.get("position", {})
                ref_x = pos.get("x", 0)
                ref_y = pos.get("y", 0)
                ref_z = pos.get("z", pos.get("altitude", 5))

            for i, did in enumerate(member_ids):
                dev = devices.get(did)
                if dev and i < len(slots):
                    slot = slots[i]
                    target_x = ref_x + slot["offset_x"]
                    target_y = ref_y + slot["offset_y"]
                    target_z = ref_z + slot.get("offset_z", 0)
                    try:
                        cmd_result = dev.execute_command("go_to", {
                            "x": target_x, "y": target_y, "z": target_z,
                        })
                        result["commands_sent"].append({
                            "device_id": did,
                            "target": {"x": target_x, "y": target_y, "z": target_z},
                            **cmd_result,
                        })
                    except Exception as e:
                        result["commands_sent"].append({
                            "device_id": did,
                            "success": False,
                            "message": str(e),
                        })

        return result

    def get_formation_preview(self, formation_type: str, count: int,
                              params: dict | None = None) -> dict:
        """Get formation slot positions without applying to a group."""
        if formation_type not in FORMATIONS:
            return {"ok": False, "error": f"unknown formation: {formation_type}"}
        slots = compute_formation(formation_type, count, params)
        formation = FORMATIONS[formation_type]
        return {
            "ok": True,
            "formation": formation.to_dict(),
            "slots": slots,
        }

    # ── Broadcast command ───────────────────────────────────────────

    def broadcast_command(self, group_id: str, command: str,
                          params: dict, devices: dict) -> dict:
        group = self.groups.get(group_id)
        if group is None:
            return {"ok": False, "error": "group not found"}
        results = group.broadcast_command(command, params, devices)
        return {"ok": True, "results": results}

    # ── Synchronized actions ────────────────────────────────────────

    def synchronized_takeoff(self, group_id: str, altitude: float,
                             devices: dict) -> dict:
        """All robots in the group take off together via countdown."""
        group = self.groups.get(group_id)
        if group is None:
            return {"ok": False, "error": "group not found"}

        countdown = self.sync.create_countdown(group_id, seconds=3, label="Takeoff")
        self.sync.start_countdown(countdown.id)

        results = group.broadcast_command("takeoff", {"altitude": altitude}, devices)
        return {
            "ok": True,
            "countdown": countdown.to_dict(),
            "results": results,
        }

    def synchronized_land(self, group_id: str, devices: dict) -> dict:
        """All robots land together."""
        group = self.groups.get(group_id)
        if group is None:
            return {"ok": False, "error": "group not found"}
        results = group.broadcast_command("land", {}, devices)
        return {"ok": True, "results": results}

    def emergency_stop(self, group_id: str, devices: dict) -> dict:
        """Emergency stop all robots in a group."""
        group = self.groups.get(group_id)
        if group is None:
            return {"ok": False, "error": "group not found"}

        # Stop any running mission
        self._stop_mission_for_group(group_id)

        # Send hover/stop to all devices
        results = []
        for did in group.device_ids():
            dev = devices.get(did)
            if dev:
                try:
                    r = dev.execute_command("hover", {"duration": 0})
                    r["device_id"] = did
                    results.append(r)
                except Exception:
                    try:
                        r = dev.execute_command("stop", {})
                        r["device_id"] = did
                        results.append(r)
                    except Exception as e:
                        results.append({"device_id": did, "success": False, "message": str(e)})

        return {"ok": True, "results": results}

    # ── Mission execution ───────────────────────────────────────────

    def start_mission(self, group_id: str, mission_type: str,
                      params: dict, devices: dict) -> dict:
        group = self.groups.get(group_id)
        if group is None:
            return {"ok": False, "error": "group not found"}

        try:
            mission = create_mission(
                mission_type, group_id,
                group.device_ids(), params,
            )
        except ValueError as e:
            return {"ok": False, "error": str(e)}

        with self._lock:
            self.missions[mission.id] = mission
            group.active_mission = mission.id

        # Execute mission in background thread
        self._stop_flags[mission.id] = False
        t = threading.Thread(
            target=self._run_mission,
            args=(mission, devices),
            daemon=True,
            name=f"mission-{mission.id}",
        )
        self._mission_threads[mission.id] = t
        t.start()

        return {"ok": True, "mission": mission.to_dict()}

    def stop_mission(self, mission_id: str) -> dict:
        mission = self.missions.get(mission_id)
        if mission is None:
            return {"ok": False, "error": "mission not found"}
        self._stop_flags[mission_id] = True
        mission.status = MissionStatus.ABORTED
        mission.completed_at = time.time()
        return {"ok": True, "mission": mission.to_dict()}

    def get_mission(self, mission_id: str) -> dict | None:
        m = self.missions.get(mission_id)
        return m.to_dict() if m else None

    def _stop_mission_for_group(self, group_id: str) -> None:
        for mid, m in self.missions.items():
            if m.group_id == group_id and m.status == MissionStatus.RUNNING:
                self._stop_flags[mid] = True
                m.status = MissionStatus.ABORTED
                m.completed_at = time.time()

    def _run_mission(self, mission: Mission, devices: dict) -> None:
        """Execute mission steps sequentially on a background thread."""
        mission.status = MissionStatus.RUNNING
        mission.started_at = time.time()

        for step in mission.steps:
            if self._stop_flags.get(mission.id, False):
                step.status = "aborted"
                continue

            step.status = "running"
            step.started_at = time.time()

            dev = devices.get(step.device_id)
            if dev is None:
                step.status = "failed"
                step.completed_at = time.time()
                mission.results.append({
                    "step_id": step.id,
                    "device_id": step.device_id,
                    "success": False,
                    "message": "device not found",
                })
                continue

            try:
                result = dev.execute_command(step.command, step.params)
                step.status = "completed" if result.get("success", True) else "failed"
                step.completed_at = time.time()
                mission.results.append({
                    "step_id": step.id,
                    "device_id": step.device_id,
                    **result,
                })
            except Exception as e:
                step.status = "failed"
                step.completed_at = time.time()
                mission.results.append({
                    "step_id": step.id,
                    "device_id": step.device_id,
                    "success": False,
                    "message": str(e),
                })

            # Small delay between steps for simulation
            time.sleep(0.3)

        if not self._stop_flags.get(mission.id, False):
            mission.status = MissionStatus.COMPLETED
        mission.completed_at = time.time()

        # Clear active mission on group
        group = self.groups.get(mission.group_id)
        if group:
            group.active_mission = None

    # ── Leader-follower ─────────────────────────────────────────────

    def leader_follower_update(self, group_id: str, devices: dict) -> dict:
        """
        Move all followers to maintain their formation offset
        relative to the leader's current position.
        """
        group = self.groups.get(group_id)
        if group is None:
            return {"ok": False, "error": "group not found"}

        leader_id = group.get_leader()
        if leader_id is None:
            return {"ok": False, "error": "no leader assigned"}

        leader_dev = devices.get(leader_id)
        if leader_dev is None:
            return {"ok": False, "error": "leader device not found"}

        leader_tel = leader_dev.get_telemetry()
        leader_pos = leader_tel.get("position", {})
        lx = leader_pos.get("x", 0)
        ly = leader_pos.get("y", 0)
        lz = leader_pos.get("z", leader_pos.get("altitude", 5))

        # Get formation slots
        if not group.formation_type:
            return {"ok": False, "error": "no formation set"}

        slots = compute_formation(group.formation_type, group.size, group.formation_params)
        member_ids = group.device_ids()
        results = []

        for i, did in enumerate(member_ids):
            if did == leader_id:
                continue
            dev = devices.get(did)
            if dev and i < len(slots):
                slot = slots[i]
                target = {
                    "x": lx + slot["offset_x"],
                    "y": ly + slot["offset_y"],
                    "z": lz + slot.get("offset_z", 0),
                }
                try:
                    r = dev.execute_command("go_to", target)
                    results.append({"device_id": did, "target": target, **r})
                except Exception as e:
                    results.append({"device_id": did, "success": False, "message": str(e)})

        return {"ok": True, "leader": leader_id, "followers_updated": len(results), "results": results}

    # ── Coverage planning ───────────────────────────────────────────

    def plan_coverage(self, group_id: str, area: dict) -> dict:
        """
        Divide an area into cells and assign robots to cover them.
        Returns the assignment plan.
        """
        group = self.groups.get(group_id)
        if group is None:
            return {"ok": False, "error": "group not found"}

        width = float(area.get("width", 100))
        height = float(area.get("height", 100))
        center_x = float(area.get("center_x", 0))
        center_y = float(area.get("center_y", 0))
        cell_size = float(area.get("cell_size", 10))

        cols = max(1, int(math.ceil(width / cell_size)))
        rows = max(1, int(math.ceil(height / cell_size)))
        total_cells = rows * cols
        device_ids = group.device_ids()
        n = len(device_ids)

        if n == 0:
            return {"ok": False, "error": "group is empty"}

        # Assign cells to robots round-robin
        assignments: dict[str, list[dict]] = {did: [] for did in device_ids}
        for ci in range(total_cells):
            did = device_ids[ci % n]
            row = ci // cols
            col = ci % cols
            cell_x = center_x - width / 2 + (col + 0.5) * cell_size
            cell_y = center_y - height / 2 + (row + 0.5) * cell_size
            assignments[did].append({
                "row": row, "col": col,
                "x": round(cell_x, 1), "y": round(cell_y, 1),
            })

        return {
            "ok": True,
            "grid": {"rows": rows, "cols": cols, "cell_size": cell_size},
            "total_cells": total_cells,
            "assignments": {
                did: {
                    "cells": cells,
                    "count": len(cells),
                }
                for did, cells in assignments.items()
            },
        }

    # ── Group status ────────────────────────────────────────────────

    def group_status(self, group_id: str, devices: dict) -> dict:
        group = self.groups.get(group_id)
        if group is None:
            return {"ok": False, "error": "group not found"}

        status = group.status(devices)
        status["sync"] = self.sync.get_group_sync(group_id)

        # Include active mission progress
        if group.active_mission:
            m = self.missions.get(group.active_mission)
            if m:
                status["mission"] = m.to_dict()

        return {"ok": True, **status}

    # ── NLP integration helpers ─────────────────────────────────────

    def parse_group_command(self, text: str, devices: dict) -> dict:
        """
        Parse a natural language command that may target a group.

        Recognizes patterns like:
          - "all drones take off"
          - "drone 1 go north, drone 2 go south"
          - "form a circle with 5m radius"
          - "rover, you're the leader"
          - "search this area"
        """
        text_lower = text.lower().strip()
        result = {"type": None, "parsed": False}

        # Formation commands
        for ftype in ("line", "circle", "v_shape", "v-formation", "grid"):
            if ftype.replace("_", " ") in text_lower or ftype.replace("_", "-") in text_lower:
                params = {}
                # Extract radius
                import re
                radius_m = re.search(r'(\d+(?:\.\d+)?)\s*m?\s*radius', text_lower)
                if radius_m:
                    params["radius"] = float(radius_m.group(1))
                spacing_m = re.search(r'(\d+(?:\.\d+)?)\s*m?\s*spacing', text_lower)
                if spacing_m:
                    params["spacing"] = float(spacing_m.group(1))
                angle_m = re.search(r'(\d+(?:\.\d+)?)\s*(?:deg|°)\s*angle', text_lower)
                if angle_m:
                    params["angle"] = float(angle_m.group(1))

                ft = ftype.replace("-formation", "").replace("-", "_")
                if ft == "v":
                    ft = "v_shape"
                result = {
                    "type": "formation",
                    "parsed": True,
                    "formation_type": ft,
                    "params": params,
                }
                return result

        # Role commands
        role_keywords = {
            "leader": RobotRole.LEADER,
            "follower": RobotRole.FOLLOWER,
            "scout": RobotRole.SCOUT,
            "guard": RobotRole.GUARD,
        }
        for keyword, role in role_keywords.items():
            if keyword in text_lower and ("you're" in text_lower or "assign" in text_lower
                                          or "set" in text_lower or "be the" in text_lower):
                result = {
                    "type": "role_assignment",
                    "parsed": True,
                    "role": role.value,
                }
                return result

        # Mission commands
        mission_triggers = {
            "search": "area_search",
            "patrol": "perimeter_patrol",
            "relay": "relay_chain",
            "escort": "escort",
            "deliver": "pick_and_deliver",
            "pick up": "pick_and_deliver",
            "transport": "pick_and_deliver",
        }
        for trigger, mtype in mission_triggers.items():
            if trigger in text_lower:
                result = {
                    "type": "mission",
                    "parsed": True,
                    "mission_type": mtype,
                }
                return result

        # Synchronized actions
        if "take off" in text_lower or "takeoff" in text_lower:
            if "all" in text_lower or "everyone" in text_lower or "together" in text_lower:
                result = {"type": "sync_takeoff", "parsed": True}
                return result

        if "land" in text_lower:
            if "all" in text_lower or "everyone" in text_lower or "together" in text_lower:
                result = {"type": "sync_land", "parsed": True}
                return result

        if "stop" in text_lower and ("emergency" in text_lower or "all" in text_lower):
            result = {"type": "emergency_stop", "parsed": True}
            return result

        # Generic broadcast — if none of the above matched,
        # treat as a direct command broadcast
        result = {
            "type": "broadcast",
            "parsed": True,
            "raw_text": text,
        }
        return result
