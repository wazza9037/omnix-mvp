"""
Physics-based state predictor used by the twin.

Wraps an AdaptivePhysics instance with a standard sim-state integrator for
each device family (drone / ground_robot / robot_arm). The twin issues
`set_command(...)` whenever a new NLP command is dispatched, then calls
`step(dt)` every sync tick to advance the predicted state.

Commands → physics inputs mapping mirrors what SimulatedDrone etc. do, so
the twin's prediction tracks the real device under identical commands.
"""

from __future__ import annotations

import math
import time
from typing import Any

# Optional imports — tests may construct predictors with pre-built physics
try:
    from simulation.physics import AdaptivePhysics, make_physics
    _HAS_PHYSICS = True
except Exception:   # pragma: no cover
    _HAS_PHYSICS = False


def initial_state(device_type: str, telemetry: dict | None = None) -> dict:
    """Build a fresh predictor state, optionally seeded from real telemetry."""
    s: dict[str, Any] = {"pos": [0.0, 0.0, 0.0], "yaw_deg": 0.0, "battery_pct": 100.0}
    if device_type == "drone":
        s.update({"vel": [0.0, 0.0, 0.0], "thrust": 0.0, "flying": False,
                  "energy_wh": 0.0})
    elif device_type == "ground_robot":
        s.update({"vx": 0.0, "wz": 0.0, "moving": False, "energy_wh": 0.0})
    elif device_type == "robot_arm":
        s.update({"joints": {}})
    if telemetry:
        _merge_telemetry(s, telemetry, device_type)
    return s


def _merge_telemetry(state: dict, tele: dict, device_type: str) -> None:
    """Pull every value we can find from device telemetry into our state shape."""
    # Common: battery, yaw, position
    if "battery_pct" in tele:
        state["battery_pct"] = float(tele.get("battery_pct", 100.0))
    elif "battery" in tele:
        state["battery_pct"] = float(tele.get("battery", 100.0))
    if "altitude_m" in tele:
        state["pos"][2] = float(tele.get("altitude_m", 0.0))
    elif "height_cm" in tele:
        state["pos"][2] = float(tele.get("height_cm", 0)) / 100.0
    if "position" in tele and isinstance(tele["position"], dict):
        state["pos"][0] = float(tele["position"].get("x", 0.0))
        state["pos"][1] = float(tele["position"].get("y", 0.0))
    if "yaw_deg" in tele:
        state["yaw_deg"] = float(tele["yaw_deg"])
    elif "attitude" in tele and isinstance(tele["attitude"], dict):
        state["yaw_deg"] = float(tele["attitude"].get("yaw_deg", 0.0))
    if device_type == "drone" and "flying" in tele:
        state["flying"] = bool(tele["flying"])
    if device_type == "robot_arm" and "joints" in tele and isinstance(tele["joints"], dict):
        state["joints"] = {k: float(v) for k, v in tele["joints"].items()
                           if isinstance(v, (int, float))}
    if device_type == "ground_robot" and "moving" in tele:
        state["moving"] = bool(tele["moving"])


def extract_for_divergence(state: dict, device_type: str) -> dict:
    """Shape the state for the divergence detector (consistent keys)."""
    out = {
        "pos": list(state.get("pos", [0.0, 0.0, 0.0])),
        "yaw_deg": float(state.get("yaw_deg", 0.0)),
        "battery_pct": float(state.get("battery_pct", 100.0)),
    }
    if "vel" in state:
        out["vel"] = list(state["vel"])
    if "joints" in state:
        out["joints"] = dict(state["joints"])
    return out


class Predictor:
    """Integrates an AdaptivePhysics model forward under user commands."""

    def __init__(self, device_type: str,
                 physics: "AdaptivePhysics | None" = None,
                 telemetry: dict | None = None):
        self.device_type = device_type
        self.physics = physics if physics is not None else (
            make_physics(device_type) if _HAS_PHYSICS else None
        )
        self.state = initial_state(device_type, telemetry)
        self._current_cmd: tuple[str, dict] | None = None
        self._cmd_started_at: float | None = None

    # ── Command intake ────────────────────────────────────

    def set_command(self, command: str, params: dict | None) -> None:
        self._current_cmd = (command, dict(params or {}))
        self._cmd_started_at = time.time()
        self._apply_instantaneous(command, params or {})

    def clear_command(self) -> None:
        self._current_cmd = None
        self._cmd_started_at = None

    def _apply_instantaneous(self, command: str, params: dict) -> None:
        """Commands that have an immediate effect (takeoff, rotate, goto)
        update state without waiting for integration."""
        if command == "takeoff":
            self.state["pos"][2] = float(params.get("altitude_m", 5.0))
            self.state["flying"] = True
        elif command == "land":
            self.state["pos"][2] = 0.0
            self.state["flying"] = False
        elif command == "rotate":
            deg = float(params.get("degrees", 0.0))
            self.state["yaw_deg"] = (self.state["yaw_deg"] + deg) % 360
        elif command == "goto":
            self.state["pos"][0] = float(params.get("x", self.state["pos"][0]))
            self.state["pos"][1] = float(params.get("y", self.state["pos"][1]))
            if "altitude_m" in params:
                self.state["pos"][2] = float(params["altitude_m"])
        elif command == "return_home":
            self.state["pos"][0] = 0.0
            self.state["pos"][1] = 0.0
        elif command == "emergency_stop":
            if "vel" in self.state:
                self.state["vel"] = [0.0, 0.0, 0.0]
            if "vx" in self.state:
                self.state["vx"] = 0.0
            if "wz" in self.state:
                self.state["wz"] = 0.0
        elif command == "move_joint":
            joints = self.state.get("joints") or {}
            idx = int(params.get("joint_index", 0))
            key = f"j{idx}"
            joints[key] = float(params.get("angle_deg", 0.0))
            self.state["joints"] = joints

    # ── Per-tick integration ──────────────────────────────

    def step(self, dt: float) -> None:
        """Advance state by dt under the current command."""
        if self.physics is None:
            return
        cmd = self._current_cmd
        if cmd is None:
            # Idle — still drain battery a tiny bit for realism
            self.state["battery_pct"] = max(
                0.0, self.state.get("battery_pct", 100.0) - 0.001 * dt)
            return
        command, params = cmd
        if self.device_type == "drone":
            self._step_drone(command, params, dt)
        elif self.device_type == "ground_robot":
            self._step_rover(command, params, dt)
        elif self.device_type == "robot_arm":
            pass  # joints are snap-to-target, already applied instantaneously

    def _step_drone(self, command: str, params: dict, dt: float) -> None:
        cmd_input: dict[str, Any] = {}
        if command == "move":
            direction = params.get("direction", "forward")
            dist = float(params.get("distance_m", 1.0))
            # Spread the move over ~expected duration so the ghost "slides"
            # smoothly like the real drone would.
            yaw = math.radians(self.state.get("yaw_deg", 0.0))
            # Use target_alt to keep altitude stable while moving
            cmd_input["target_alt_m"] = self.state["pos"][2]
            if direction == "forward":
                cmd_input["ax"] = math.cos(yaw) * dist / 2.0
                cmd_input["ay"] = math.sin(yaw) * dist / 2.0
            elif direction == "backward":
                cmd_input["ax"] = -math.cos(yaw) * dist / 2.0
                cmd_input["ay"] = -math.sin(yaw) * dist / 2.0
            elif direction == "left":
                cmd_input["ax"] = -math.sin(yaw) * dist / 2.0
                cmd_input["ay"] = math.cos(yaw) * dist / 2.0
            elif direction == "right":
                cmd_input["ax"] = math.sin(yaw) * dist / 2.0
                cmd_input["ay"] = -math.cos(yaw) * dist / 2.0
            elif direction == "up":
                cmd_input["target_alt_m"] = self.state["pos"][2] + dist
            elif direction == "down":
                cmd_input["target_alt_m"] = max(0, self.state["pos"][2] - dist)
        elif command == "takeoff":
            cmd_input["target_alt_m"] = float(params.get("altitude_m", 5.0))
        elif command == "land":
            cmd_input["target_alt_m"] = 0.0
        elif command == "hover":
            cmd_input["target_alt_m"] = self.state["pos"][2]
        else:
            cmd_input["target_alt_m"] = self.state["pos"][2]

        self.state = self.physics.step_drone(cmd_input, dt, self.state)

    def _step_rover(self, command: str, params: dict, dt: float) -> None:
        cmd_input: dict[str, Any] = {"vx": 0.0, "wz": 0.0}
        if command == "drive":
            d = params.get("direction", "forward")
            speed = float(params.get("speed", 50.0)) / 100.0   # 0..1 fraction
            if d == "forward":
                cmd_input["vx"] = speed
            elif d == "backward":
                cmd_input["vx"] = -speed
            elif d == "left":
                cmd_input["wz"] = math.radians(30) * speed
            elif d == "right":
                cmd_input["wz"] = -math.radians(30) * speed
        self.state = self.physics.step_rover(cmd_input, dt, self.state)
        # Keep yaw_deg in sync with the physics yaw
        if "theta" in self.state:
            self.state["yaw_deg"] = math.degrees(self.state["theta"]) % 360

    # ── Accessors ─────────────────────────────────────────

    def current_state(self) -> dict:
        return extract_for_divergence(self.state, self.device_type)

    def physics_snapshot(self) -> dict | None:
        return self.physics.snapshot() if self.physics else None
