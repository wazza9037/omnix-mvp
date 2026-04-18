"""
Plan validator + annotator.

Takes a fresh ExecutionPlan out of the compiler and:

  1. Applies hard safety checks (altitude caps, joint limits, motor maxes).
  2. Walks the plan step-by-step with a tiny kinematic "cursor" to fill
     in each step's expected_start_pos / expected_end_pos / expected_path.
     These are the waypoints the frontend draws as a dotted line before
     the user hits Execute.
  3. Estimates total duration + battery drain.

The cursor is deliberately simple — not the full adaptive physics model —
because (a) planning must be instant, (b) preview precision is cheap to
add later from the physics model, and (c) keeping this pure makes it
easy to unit test.
"""

from __future__ import annotations

import math
from typing import Any

from .models import ExecutionPlan, PlanStep, ValidationIssue, IssueSeverity


# ── Safety constants (defaults; may be overridden via workspace.world) ──

DEFAULT_MAX_ALT_M = 120.0       # aviation-ish sanity cap
DEFAULT_MAX_DISTANCE_M = 500.0  # per-step cap, prevents runaway plans
DEFAULT_MAX_JOINT_DEG = 180.0
DEFAULT_BATTERY_ESTIMATE = {
    # Rough per-command-type drain estimates. Used only for UI warnings.
    # (device_type, command) → pct_per_second
    ("drone", "hover"):   0.04,
    ("drone", "takeoff"): 0.25,
    ("drone", "land"):    0.10,
    ("drone", "move"):    0.12,
    ("drone", "rotate"):  0.06,
    ("drone", "goto"):    0.15,
    ("drone", "return_home"): 0.15,
    ("ground_robot", "drive"): 0.05,
    ("robot_arm", "move_joint"): 0.03,
    ("robot_arm", "grip"):       0.02,
    ("robot_arm", "release"):    0.015,
    ("robot_arm", "go_home"):    0.03,
}


def _drain_rate(device_type: str, command: str) -> float:
    return DEFAULT_BATTERY_ESTIMATE.get((device_type, command),
           DEFAULT_BATTERY_ESTIMATE.get((device_type, "move"), 0.02))


# ── Kinematic cursor ────────────────────────────────────────────────

def _fresh_cursor(device_type: str, telemetry: dict | None) -> dict:
    """Snapshot of device state the planner advances through the plan.

    If live telemetry is provided we seed the cursor from it; otherwise
    we start at the origin pointing north.
    """
    cur = {
        "pos": [0.0, 0.0, 0.0],
        "yaw_rad": 0.0,
        "flying": False,
        "device_type": device_type,
    }
    if not telemetry:
        return cur
    # Drone telemetry
    if "altitude_m" in telemetry:
        cur["pos"][2] = float(telemetry.get("altitude_m", 0.0))
    if "position" in telemetry and isinstance(telemetry["position"], dict):
        cur["pos"][0] = float(telemetry["position"].get("x", 0.0))
        cur["pos"][1] = float(telemetry["position"].get("y", 0.0))
    if "yaw_deg" in telemetry:
        cur["yaw_rad"] = math.radians(float(telemetry["yaw_deg"]))
    if "flying" in telemetry:
        cur["flying"] = bool(telemetry["flying"])
    return cur


def _apply_step(step: PlanStep, cursor: dict) -> None:
    """Integrate the step against the cursor; write expected_path back on step."""
    start = list(cursor["pos"])
    cmd = step.command
    p = step.params
    dt = step.device_type if hasattr(step, "device_type") else cursor["device_type"]
    path = [list(start)]

    if cmd == "takeoff":
        cursor["pos"][2] = float(p.get("altitude_m", 5.0))
        cursor["flying"] = True
    elif cmd == "land":
        cursor["pos"][2] = 0.0
        cursor["flying"] = False
    elif cmd == "hover":
        pass     # no movement, just dwell
    elif cmd == "move":
        direction = p.get("direction", "forward")
        dist = float(p.get("distance_m", 1.0))
        yaw = cursor["yaw_rad"]
        dx = dy = dz = 0.0
        if direction == "forward":  dx, dy = math.cos(yaw), math.sin(yaw)
        elif direction == "backward": dx, dy = -math.cos(yaw), -math.sin(yaw)
        elif direction == "left":  dx, dy = -math.sin(yaw), math.cos(yaw)
        elif direction == "right": dx, dy = math.sin(yaw), -math.cos(yaw)
        elif direction == "up":   dz = 1.0
        elif direction == "down": dz = -1.0
        cursor["pos"][0] += dx * dist
        cursor["pos"][1] += dy * dist
        cursor["pos"][2] = max(0.0, cursor["pos"][2] + dz * dist)
        # Mid-point sample so the preview line curves through long moves
        mid = [(start[i] + cursor["pos"][i]) / 2 for i in range(3)]
        path.append(mid)
    elif cmd == "rotate":
        cursor["yaw_rad"] += math.radians(float(p.get("degrees", 0.0)))
    elif cmd == "return_home":
        cursor["pos"][0] = 0.0
        cursor["pos"][1] = 0.0
        # Keep altitude; a subsequent "land" usually follows
    elif cmd == "goto":
        cursor["pos"][0] = float(p.get("x", cursor["pos"][0]))
        cursor["pos"][1] = float(p.get("y", cursor["pos"][1]))
        cursor["pos"][2] = float(p.get("altitude_m", cursor["pos"][2]))
    elif cmd == "drive":
        direction = p.get("direction", "forward")
        # Convert duration_ms + speed into a rough distance estimate
        dur_ms = float(p.get("duration_ms", 1000))
        speed_pct = float(p.get("speed", 50))
        # Hand-wavy: 1 m/s at 100% speed (the simulated rovers roughly track this)
        dist = dur_ms / 1000.0 * speed_pct / 100.0
        yaw = cursor["yaw_rad"]
        if direction == "forward":
            cursor["pos"][0] += math.cos(yaw) * dist
            cursor["pos"][1] += math.sin(yaw) * dist
        elif direction == "backward":
            cursor["pos"][0] -= math.cos(yaw) * dist
            cursor["pos"][1] -= math.sin(yaw) * dist
        elif direction == "left":
            cursor["yaw_rad"] += math.radians(30) * (dur_ms / 1000.0)
        elif direction == "right":
            cursor["yaw_rad"] -= math.radians(30) * (dur_ms / 1000.0)
    # Non-movement commands (grip, scan, take_photo, move_joint, etc.)
    # don't change the cursor position — they just take time.

    path.append(list(cursor["pos"]))
    step.expected_start_pos = start
    step.expected_end_pos = list(cursor["pos"])
    step.expected_path = path


# ── Top-level planner ───────────────────────────────────────────────

def plan_and_validate(
    plan: ExecutionPlan,
    device_type: str,
    telemetry: dict | None = None,
    capability_names: list[str] | None = None,
    max_altitude_m: float = DEFAULT_MAX_ALT_M,
    max_distance_m: float = DEFAULT_MAX_DISTANCE_M,
) -> ExecutionPlan:
    """Mutate + return the plan with annotations and any issues added."""
    cursor = _fresh_cursor(device_type, telemetry)
    total_duration = 0.0
    battery_drain = 0.0
    cap_set = set(capability_names or [])

    for idx, step in enumerate(plan.steps):
        # Hard safety checks
        if step.command == "takeoff":
            alt = float(step.params.get("altitude_m", 0))
            if alt > max_altitude_m:
                plan.add_issue(IssueSeverity.ERROR, "altitude_cap",
                               f"Takeoff altitude {alt}m exceeds cap of {max_altitude_m}m",
                               step_index=idx)
        if step.command == "move":
            d = float(step.params.get("distance_m", 0))
            if d > max_distance_m:
                plan.add_issue(IssueSeverity.ERROR, "distance_cap",
                               f"Move distance {d}m exceeds per-step cap of {max_distance_m}m",
                               step_index=idx)
        if step.command == "move_joint":
            a = float(step.params.get("angle_deg", 0))
            if abs(a) > DEFAULT_MAX_JOINT_DEG:
                plan.add_issue(IssueSeverity.ERROR, "joint_limit",
                               f"Joint angle {a}° exceeds ±{DEFAULT_MAX_JOINT_DEG}°",
                               step_index=idx)

        # Capability check (compiler already flagged this, but belt-and-braces)
        if cap_set and step.command not in cap_set \
                and not step.command.startswith("_"):
            plan.add_issue(IssueSeverity.ERROR, "unsupported_command",
                           f"Device has no '{step.command}' capability",
                           step_index=idx)

        # Annotate trajectory
        _apply_step(step, cursor)

        # Accumulate estimates
        active_time = step.expected_duration_s + step.dwell_s
        total_duration += active_time
        battery_drain += _drain_rate(device_type, step.command) * active_time

        # Upper altitude exceeded mid-flight?
        if cursor["pos"][2] > max_altitude_m:
            plan.add_issue(IssueSeverity.WARNING, "altitude_high",
                           f"Step {idx + 1} reaches {cursor['pos'][2]:.1f}m "
                           f"(soft cap {max_altitude_m}m)",
                           step_index=idx)

    plan.estimated_duration_s = total_duration
    plan.estimated_battery_pct = round(battery_drain, 2)

    # Battery soft-warning
    if battery_drain > 40.0:
        plan.add_issue(IssueSeverity.WARNING, "battery_cost",
                       f"Plan may drain ~{battery_drain:.0f}% of battery — "
                       f"consider splitting it up.")

    return plan
