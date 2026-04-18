"""
OMNIX Scenarios — canned "test procedures" that get run as iterations.

A scenario is a small dataclass describing:
  - what commands to issue vs. time
  - what trajectory/state we expect
  - which metrics to compute from the resulting trajectory

Runner executes the scenario against an AdaptivePhysics model, which
integrates state forward dt by dt, then returns the recorded trajectory
plus aggregated metrics. Metrics feed into the workspace so the user
can see "stability" / "tracking_error" / "overall" trend across runs.
"""

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class Scenario:
    name: str
    display_name: str
    description: str
    device_types: List[str]      # which device types this applies to
    duration_s: float
    dt_s: float                  # integration step
    icon: str = "🎯"
    tags: List[str] = field(default_factory=list)
    # Produces the command dict for a given time. Closes over scenario params.
    command_at: Callable[[float, dict], dict] = None
    # Expected reference state at time t (used to compute tracking error).
    reference_at: Callable[[float, dict], dict] = None
    # User-tweakable params with defaults, shown in the UI
    params: dict = field(default_factory=dict)


# ── Drone scenarios ─────────────────────────────────────────────────

def _drone_hover_cmd(t, p):
    # Climb to target altitude then hold
    target_alt = p.get("altitude_m", 5.0)
    thrust = 1.0 if t < 1.5 else 0.85    # big push, then hover
    return {"thrust": thrust, "target_alt_m": target_alt}

def _drone_hover_ref(t, p):
    target = p.get("altitude_m", 5.0)
    if t < 2.5:
        return {"z": target * min(1.0, t / 2.5)}
    return {"z": target}

def _drone_square_cmd(t, p):
    side = p.get("side_m", 4.0)
    period = p.get("period_s", 12.0)
    phase = (t % period) / period
    thrust = 0.9
    if t < 2.0:
        return {"thrust": 1.0, "ax": 0, "ay": 0}
    # Move along each side for 1/4 of the period
    ax = ay = 0.0
    mag = 2.0 * side / period * 2   # roughly side/quarter-time, doubled for accel feel
    if phase < 0.25: ax = mag
    elif phase < 0.5: ay = mag
    elif phase < 0.75: ax = -mag
    else: ay = -mag
    return {"thrust": thrust, "ax": ax, "ay": ay, "target_alt_m": p.get("altitude_m", 5.0)}

def _drone_square_ref(t, p):
    side = p.get("side_m", 4.0)
    period = p.get("period_s", 12.0)
    phase = (max(0, t - 2) % period) / period
    if phase < 0.25: x, y = side * (phase / 0.25), 0
    elif phase < 0.5: x, y = side, side * ((phase - 0.25) / 0.25)
    elif phase < 0.75: x, y = side - side * ((phase - 0.5) / 0.25), side
    else:              x, y = 0, side - side * ((phase - 0.75) / 0.25)
    return {"x": x, "y": y, "z": p.get("altitude_m", 5.0)}

def _drone_ramp_cmd(t, p):
    peak = p.get("peak_alt_m", 10.0)
    # 0-4s climb, 4-6s hold, 6-10s descend
    if t < 4: thrust = 1.0
    elif t < 6: thrust = 0.85
    else: thrust = 0.65
    return {"thrust": thrust, "target_alt_m": peak}

def _drone_ramp_ref(t, p):
    peak = p.get("peak_alt_m", 10.0)
    if t < 4: return {"z": peak * (t / 4)}
    if t < 6: return {"z": peak}
    if t < 10: return {"z": peak * max(0, (10 - t) / 4)}
    return {"z": 0}


# ── Rover scenarios ─────────────────────────────────────────────────

def _rover_straight_cmd(t, p):
    v = p.get("speed_m_s", 0.5)
    if t < 1.0: v *= t    # ramp
    if t > p.get("duration_s", 8) - 1: v *= max(0, (p.get("duration_s", 8) - t))
    return {"vx": v, "wz": 0.0}

def _rover_straight_ref(t, p):
    v = p.get("speed_m_s", 0.5)
    dur = p.get("duration_s", 8)
    if t < 1.0: x = 0.5 * v * t * t
    elif t < dur - 1: x = 0.5 * v + v * (t - 1)
    else: x = 0.5 * v + v * (dur - 2)  # roughly
    return {"x": x, "y": 0, "theta": 0}

def _rover_figure8_cmd(t, p):
    v = p.get("speed_m_s", 0.5)
    r = p.get("radius_m", 1.2)
    # Two lobes: first counter-clockwise, then clockwise
    period = p.get("period_s", 16.0)
    phase = (t % period) / period
    wz = v / r
    if phase > 0.5: wz = -wz
    return {"vx": v, "wz": wz}

def _rover_figure8_ref(t, p):
    v = p.get("speed_m_s", 0.5)
    r = p.get("radius_m", 1.2)
    period = p.get("period_s", 16.0)
    # Not exact, but good enough for metric comparison
    ang = 2 * math.pi * (t / (period / 2))
    if (t % period) < period / 2:
        x = r * math.sin(ang)
        y = r - r * math.cos(ang)
    else:
        ang = 2 * math.pi * ((t - period / 2) / (period / 2))
        x = -r * math.sin(ang) + 0
        y = r + r * math.cos(ang) - 2 * r
    return {"x": x, "y": y, "theta": 0}

def _rover_turn_cmd(t, p):
    angle = p.get("angle_deg", 180)
    duration = p.get("duration_s", 6)
    rate = math.radians(angle) / duration
    return {"vx": 0.0, "wz": rate if t < duration else 0.0}

def _rover_turn_ref(t, p):
    angle = p.get("angle_deg", 180)
    duration = p.get("duration_s", 6)
    theta = math.radians(angle) * min(1.0, t / duration)
    return {"x": 0, "y": 0, "theta": theta}


# ── Arm scenarios ───────────────────────────────────────────────────

def _arm_reach_cmd(t, p):
    pose = p.get("target", {"j0": 45, "j1": -30, "j2": 60})
    hold_time = p.get("hold_time_s", 2.0)
    if t < hold_time:
        # Ramp toward target
        frac = min(1.0, t / hold_time)
        return {"joints": {k: v * frac for k, v in pose.items()}}
    return {"joints": pose}

def _arm_reach_ref(t, p):
    pose = p.get("target", {"j0": 45, "j1": -30, "j2": 60})
    hold_time = p.get("hold_time_s", 2.0)
    frac = min(1.0, t / hold_time)
    return {"joints": {k: v * frac for k, v in pose.items()}}

def _arm_pick_place_cmd(t, p):
    # Three phases: reach → grip → lift → place
    above = {"j0": 30, "j1": -20, "j2": 40, "gripper": 90}
    grip  = {"j0": 30, "j1": -40, "j2": 50, "gripper": 20}
    lift  = {"j0": 30, "j1": -20, "j2": 40, "gripper": 20}
    place = {"j0": -30, "j1": -20, "j2": 40, "gripper": 90}
    if   t < 1.5: target = above
    elif t < 3.0: target = grip
    elif t < 4.5: target = lift
    elif t < 6.0: target = place
    else: target = place
    return {"joints": target}

def _arm_pick_place_ref(t, p):
    return _arm_pick_place_cmd(t, p)


# ── Registry ────────────────────────────────────────────────────────

SCENARIOS: Dict[str, Scenario] = {
    # Drones
    "hover": Scenario(
        name="hover", display_name="Hover & Hold",
        description="Climb to a target altitude, hold for the remaining duration, observe drift and stability.",
        device_types=["drone"], duration_s=10.0, dt_s=0.05, icon="🪂",
        tags=["easy", "stability"],
        command_at=_drone_hover_cmd, reference_at=_drone_hover_ref,
        params={"altitude_m": 5.0},
    ),
    "square_patrol": Scenario(
        name="square_patrol", display_name="Square Patrol",
        description="Fly a square perimeter at a fixed altitude. Measures tracking error through direction changes.",
        device_types=["drone"], duration_s=16.0, dt_s=0.05, icon="🔲",
        tags=["medium", "tracking"],
        command_at=_drone_square_cmd, reference_at=_drone_square_ref,
        params={"altitude_m": 5.0, "side_m": 4.0, "period_s": 12.0},
    ),
    "altitude_ramp": Scenario(
        name="altitude_ramp", display_name="Altitude Ramp",
        description="Climb to a peak, hold, then descend smoothly — tests thrust response and settling.",
        device_types=["drone"], duration_s=10.0, dt_s=0.05, icon="⛰️",
        tags=["medium", "response"],
        command_at=_drone_ramp_cmd, reference_at=_drone_ramp_ref,
        params={"peak_alt_m": 10.0},
    ),

    # Rovers / ground_robot
    "straight_line": Scenario(
        name="straight_line", display_name="Straight Line",
        description="Accelerate, cruise at constant speed, decelerate. Baseline for motor characterisation.",
        device_types=["ground_robot"], duration_s=8.0, dt_s=0.05, icon="📏",
        tags=["easy", "baseline"],
        command_at=_rover_straight_cmd, reference_at=_rover_straight_ref,
        params={"speed_m_s": 0.5, "duration_s": 8.0},
    ),
    "figure_eight": Scenario(
        name="figure_eight", display_name="Figure-8",
        description="Two opposite loops — tests smooth direction changes and odometry consistency.",
        device_types=["ground_robot"], duration_s=16.0, dt_s=0.05, icon="♾️",
        tags=["medium", "tracking"],
        command_at=_rover_figure8_cmd, reference_at=_rover_figure8_ref,
        params={"speed_m_s": 0.4, "radius_m": 1.2, "period_s": 16.0},
    ),
    "u_turn": Scenario(
        name="u_turn", display_name="180° Turn",
        description="Turn in place to measure yaw response.",
        device_types=["ground_robot"], duration_s=6.0, dt_s=0.05, icon="↩️",
        tags=["easy", "yaw"],
        command_at=_rover_turn_cmd, reference_at=_rover_turn_ref,
        params={"angle_deg": 180, "duration_s": 6.0},
    ),

    # Arms
    "reach_pose": Scenario(
        name="reach_pose", display_name="Reach Target Pose",
        description="Drive each joint to a target angle and hold. Measures settling time and overshoot.",
        device_types=["robot_arm"], duration_s=5.0, dt_s=0.05, icon="🎯",
        tags=["easy", "accuracy"],
        command_at=_arm_reach_cmd, reference_at=_arm_reach_ref,
        params={"target": {"j0": 45, "j1": -30, "j2": 60}, "hold_time_s": 2.0},
    ),
    "pick_and_place": Scenario(
        name="pick_and_place", display_name="Pick & Place",
        description="Full 4-phase cycle: approach, grip, lift, place. Measures repeatability under load.",
        device_types=["robot_arm"], duration_s=7.0, dt_s=0.05, icon="🤝",
        tags=["medium", "manipulation"],
        command_at=_arm_pick_place_cmd, reference_at=_arm_pick_place_ref,
    ),
}


def list_scenarios(device_type: str = None) -> list:
    out = []
    for s in SCENARIOS.values():
        if device_type and device_type not in s.device_types:
            continue
        out.append({
            "name": s.name, "display_name": s.display_name,
            "description": s.description, "device_types": s.device_types,
            "duration_s": s.duration_s, "dt_s": s.dt_s, "icon": s.icon,
            "tags": s.tags, "params": s.params,
        })
    return out


def get_scenario(name: str) -> Optional[Scenario]:
    return SCENARIOS.get(name)
