"""
CustomRobotDevice — an OmnixDevice whose behavior is derived from a
user-defined CustomBuild.

It:
  - Registers whichever DeviceCapabilities the build implies
  - Simulates a plausible telemetry stream (battery, position, attitude)
  - Handles the common command set in a lightweight physics-free manner
  - Exposes `mesh_params` so the 3D viewer can render exactly what the
    user built

Swapping the build in-place via `update_build()` atomically re-derives
capabilities so a live-editing Build view can flip the device's surface
without tearing down the workspace.
"""

from __future__ import annotations

import math
import random
import threading
import time
from typing import Any

from devices.base import OmnixDevice, DeviceCapability

from .builder import CustomBuild


class CustomRobotDevice(OmnixDevice):
    """OmnixDevice backed by a CustomBuild."""

    def __init__(self, name: str, build: CustomBuild):
        # derive device_type from the build so the existing UI picks
        # the right icon / physics / movement set
        super().__init__(name=name, device_type=build.derive_device_type())
        self._build = build
        self._build_lock = threading.Lock()
        self._boot_ts = time.time()
        self._battery_pct = 100.0

        # Per-device-type runtime state (filled lazily)
        self._pos = [0.0, 0.0, 0.0]
        self._yaw = 0.0
        self._flying = False
        self._moving = False
        self._last_cmd: str | None = None

        self._refresh_capabilities()

    # ── Build accessors ───────────────────────────────────

    def get_build(self) -> CustomBuild:
        with self._build_lock:
            return self._build

    def update_build(self, new_build: CustomBuild) -> None:
        """Atomically swap the underlying build. Used by the Build view
        whenever the user adds, removes, or tweaks a part."""
        with self._build_lock:
            self._build = new_build
            # device_type may have flipped (e.g. user added a wheel)
            new_type = new_build.derive_device_type()
            if new_type != self.device_type:
                self.device_type = new_type
            self._refresh_capabilities()

    def _refresh_capabilities(self) -> None:
        self._capabilities = []
        for c in self._build.derive_capabilities():
            self.register_capability(DeviceCapability(
                name=c.name, description=c.description,
                parameters=dict(c.parameters), category=c.category,
            ))

    # ── Telemetry ─────────────────────────────────────────

    def get_telemetry(self) -> dict:
        self._battery_pct = max(0.0, self._battery_pct - 0.002)
        uptime = round(time.time() - self._boot_ts, 1)
        cnt = self._build.part_counts()
        tele: dict[str, Any] = {
            "battery_pct": round(self._battery_pct, 1),
            "uptime_s": uptime,
            "device_type": self.device_type,
            "is_custom_build": True,
            "part_counts": cnt,
            "last_command": self._last_cmd,
        }
        dt = self.device_type
        if dt == "drone":
            tele.update({
                "flying": self._flying,
                "altitude_m": round(self._pos[2], 2),
                "position": {"x": round(self._pos[0], 2), "y": round(self._pos[1], 2)},
                "yaw_deg": round(math.degrees(self._yaw) % 360, 1),
            })
        elif dt in ("ground_robot", "legged", "humanoid", "marine"):
            tele.update({
                "moving": self._moving,
                "position": {"x": round(self._pos[0], 2), "y": round(self._pos[1], 2)},
                "yaw_deg": round(math.degrees(self._yaw) % 360, 1),
            })
        elif dt == "robot_arm":
            n = max(1, cnt.get("joint", 3))
            tele.update({
                "joints": {f"j{i}": round(math.sin((uptime + i) * 0.5) * 30, 1)
                           for i in range(n)},
                "gripper": cnt.get("gripper", 0) > 0,
            })
        return tele

    # ── Command dispatch ──────────────────────────────────

    def execute_command(self, command: str, params: dict | None = None) -> dict:
        params = params or {}
        self._last_cmd = command
        cap_names = {c.name for c in self._capabilities}
        if command not in cap_names:
            return {
                "success": False,
                "message": f"Command '{command}' not supported by this build. "
                           f"Available: {sorted(cap_names)}",
            }

        try:
            return self._dispatch(command, params)
        except Exception as e:
            return {"success": False, "message": f"error: {e}"}

    def _dispatch(self, cmd: str, p: dict) -> dict:
        if cmd == "takeoff":
            self._flying = True
            self._pos[2] = float(p.get("altitude_m", 5))
            return {"success": True, "message": f"takeoff → {self._pos[2]}m"}
        if cmd == "land":
            self._flying = False
            self._pos[2] = 0.0
            return {"success": True, "message": "landed"}
        if cmd == "hover":
            self._moving = False
            return {"success": True, "message": "holding position"}
        if cmd == "move":
            d = p.get("direction", "forward")
            dist = float(p.get("distance_m", 2))
            step = {
                "forward":  (math.cos(self._yaw) * dist,  math.sin(self._yaw) * dist, 0),
                "backward": (-math.cos(self._yaw) * dist, -math.sin(self._yaw) * dist, 0),
                "left":     (-math.sin(self._yaw) * dist, math.cos(self._yaw) * dist, 0),
                "right":    (math.sin(self._yaw) * dist, -math.cos(self._yaw) * dist, 0),
                "up":       (0, 0, dist),
                "down":     (0, 0, -dist),
            }.get(d, (0, 0, 0))
            self._pos = [self._pos[i] + step[i] for i in range(3)]
            self._pos[2] = max(0.0, self._pos[2])
            return {"success": True, "message": f"moved {d} {dist}m"}
        if cmd == "drive":
            d = p.get("direction", "forward")
            speed = float(p.get("speed", 50))
            dur = float(p.get("duration_ms", 1000)) / 1000.0
            self._moving = d != "stop" and speed > 0
            delta = speed * 0.01 * dur
            if d == "forward":
                self._pos[0] += math.cos(self._yaw) * delta
                self._pos[1] += math.sin(self._yaw) * delta
            elif d == "backward":
                self._pos[0] -= math.cos(self._yaw) * delta
                self._pos[1] -= math.sin(self._yaw) * delta
            elif d == "left":
                self._yaw += math.radians(30) * dur
            elif d == "right":
                self._yaw -= math.radians(30) * dur
            return {"success": True, "message": f"drive {d} @ {speed} for {dur:.1f}s"}
        if cmd == "walk":
            d = p.get("direction", "forward")
            self._moving = d != "stop"
            if d != "stop":
                self._pos[0] += math.cos(self._yaw) * 0.3
                self._pos[1] += math.sin(self._yaw) * 0.3
            return {"success": True, "message": f"walking {d} ({p.get('gait','trot')})"}
        if cmd == "stand":
            self._moving = False
            return {"success": True, "message": "standing"}
        if cmd == "thrust":
            lvl = float(p.get("level", 0))
            self._pos[0] += math.cos(self._yaw) * lvl * 0.02
            return {"success": True, "message": f"thrust {lvl}"}
        if cmd == "move_joint":
            return {"success": True,
                    "message": f"joint {p.get('joint_index', 0)} → {p.get('angle_deg', 0)}°"}
        if cmd == "go_home":
            return {"success": True, "message": "returning to home pose"}
        if cmd == "grip":
            return {"success": True, "message": f"gripper closed ({p.get('force', 50)})"}
        if cmd == "release":
            return {"success": True, "message": "gripper open"}
        if cmd == "scan":
            return {"success": True,
                    "message": "scan complete",
                    "data": {"temperature_c": round(20 + random.random() * 8, 1),
                             "distance_cm": random.randint(5, 300)}}
        if cmd == "take_photo":
            return {"success": True, "message": "photo captured"}
        if cmd == "emergency_stop":
            self._flying = False
            self._moving = False
            return {"success": True, "message": "E-stop engaged"}
        if cmd == "ping":
            return {"success": True, "message": "pong"}
        return {"success": False, "message": f"Unhandled command: {cmd}"}

    # ── Info override so mesh_params is exposed to the frontend ──

    def get_info(self) -> dict:
        info = super().get_info()
        info["is_custom_build"] = True
        info["mesh_params"] = self._build.to_mesh_params()
        info["part_counts"] = self._build.part_counts()
        return info
