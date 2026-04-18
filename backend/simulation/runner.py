"""
OMNIX Scenario Runner — executes one scenario and records an iteration.

Input:
  - workspace (from workspace_store.ensure(...))
  - scenario (from simulation.scenarios.get_scenario(name))
  - params override dict (optional)

What it does:
  1. Takes the workspace's AdaptivePhysics (creating one if missing).
  2. Steps the physics dt by dt through the scenario duration, issuing
     the scenario's commands and recording trajectory snapshots.
  3. At each step also computes the scenario's reference state and the
     squared error between observed and reference.
  4. After the run:
     - Aggregates metrics: tracking_error, stability, smoothness,
       power_efficiency, overall.
     - Calls physics.observe(...) with a weight based on how rich the
       run was — this is the "simulation improves per iteration" step.
     - Updates workspace["physics"] with the new snapshot.
     - Appends the iteration dict (with trajectory + metrics) to the
       workspace and returns it.

This is the only place physics learning is triggered. Frontend only
needs to call POST /api/workspaces/<device_id>/iterations and read the
resulting iteration back.
"""

import math
import random
import time
from typing import Any

from .physics import AdaptivePhysics, make_physics
from .scenarios import get_scenario, Scenario

try:
    from omnix.config import settings as _omnix_settings
except Exception:  # pragma: no cover
    _omnix_settings = None


def _init_state(device_type: str) -> dict:
    if device_type == "drone":
        return {"thrust": 0.0, "vel": [0.0, 0.0, 0.0], "pos": [0.0, 0.0, 0.0],
                "energy_wh": 0.0, "battery_pct": 100.0}
    if device_type == "ground_robot":
        return {"vx": 0.0, "wz": 0.0, "x": 0.0, "y": 0.0, "theta": 0.0,
                "energy_wh": 0.0, "battery_pct": 100.0}
    if device_type == "robot_arm":
        return {"joints": {"j0": 0, "j1": 0, "j2": 0, "j3": 0, "gripper": 50}}
    return {}


def _physics_step(physics: AdaptivePhysics, device_type: str, cmd: dict, dt: float, state: dict) -> dict:
    if device_type == "drone":
        return physics.step_drone(cmd, dt, state)
    if device_type == "ground_robot":
        return physics.step_rover(cmd, dt, state)
    if device_type == "robot_arm":
        return physics.step_arm(cmd, dt, state)
    return state


def _sample_for_trajectory(device_type: str, state: dict) -> dict:
    """Small JSON-safe snapshot for the recorded trajectory."""
    if device_type == "drone":
        return {"pos": [round(x, 3) for x in state["pos"]],
                "vel": [round(x, 3) for x in state["vel"]],
                "battery": round(state.get("battery_pct", 100), 1)}
    if device_type == "ground_robot":
        return {"x": round(state["x"], 3), "y": round(state["y"], 3),
                "theta": round(state["theta"], 3),
                "vx": round(state["vx"], 3),
                "battery": round(state.get("battery_pct", 100), 1)}
    if device_type == "robot_arm":
        return {"joints": {k: round(v, 2) for k, v in state.get("joints", {}).items()}}
    return dict(state)


def _error_between(device_type: str, observed: dict, ref: dict) -> float:
    """Return tracking error (euclidean-ish, in relevant units) for this step."""
    if device_type == "drone":
        ox, oy, oz = observed["pos"]
        rx, ry, rz = ref.get("x", 0), ref.get("y", 0), ref.get("z", 0)
        return math.sqrt((ox - rx) ** 2 + (oy - ry) ** 2 + (oz - rz) ** 2)
    if device_type == "ground_robot":
        dx = observed["x"] - ref.get("x", 0)
        dy = observed["y"] - ref.get("y", 0)
        return math.sqrt(dx * dx + dy * dy)
    if device_type == "robot_arm":
        ref_j = ref.get("joints", {})
        tot = 0.0
        n = 0
        for j, rv in ref_j.items():
            ov = observed.get("joints", {}).get(j, rv)
            tot += (ov - rv) ** 2
            n += 1
        return math.sqrt(tot / n) if n else 0.0
    return 0.0


def _stability_score(trajectory: list, device_type: str) -> float:
    """Higher is better. Rewards low jerk / low oscillation."""
    if len(trajectory) < 3:
        return 0.5
    if device_type == "drone":
        jerk = []
        for i in range(2, len(trajectory)):
            v1 = trajectory[i - 1]["vel"]
            v0 = trajectory[i - 2]["vel"]
            v2 = trajectory[i]["vel"]
            jerk.append(math.sqrt(sum((v2[k] - 2 * v1[k] + v0[k]) ** 2 for k in range(3))))
        mean_jerk = sum(jerk) / len(jerk) if jerk else 0.0
        return max(0.0, min(1.0, 1.0 - mean_jerk / 6.0))
    if device_type == "ground_robot":
        # Penalize rapid vx changes
        diffs = [abs(trajectory[i]["vx"] - trajectory[i - 1]["vx"]) for i in range(1, len(trajectory))]
        mean = sum(diffs) / len(diffs) if diffs else 0.0
        return max(0.0, min(1.0, 1.0 - mean / 0.6))
    if device_type == "robot_arm":
        js = [t.get("joints", {}) for t in trajectory]
        if not js:
            return 0.5
        keys = js[-1].keys()
        per_joint = []
        for k in keys:
            vals = [j.get(k, 0) for j in js]
            if len(vals) < 3:
                continue
            diffs = [abs(vals[i] - 2 * vals[i - 1] + vals[i - 2]) for i in range(2, len(vals))]
            mean = sum(diffs) / len(diffs) if diffs else 0.0
            per_joint.append(mean)
        mean = sum(per_joint) / len(per_joint) if per_joint else 0.0
        return max(0.0, min(1.0, 1.0 - mean / 8.0))
    return 0.5


def _smoothness(trajectory: list, device_type: str) -> float:
    """Rewards low total command-magnitude variance. 0-1, higher better."""
    if len(trajectory) < 2:
        return 0.5
    diffs = []
    if device_type == "drone":
        for i in range(1, len(trajectory)):
            p0 = trajectory[i - 1]["pos"]
            p1 = trajectory[i]["pos"]
            diffs.append(math.sqrt(sum((p1[k] - p0[k]) ** 2 for k in range(3))))
    elif device_type == "ground_robot":
        for i in range(1, len(trajectory)):
            dx = trajectory[i]["x"] - trajectory[i - 1]["x"]
            dy = trajectory[i]["y"] - trajectory[i - 1]["y"]
            diffs.append(math.hypot(dx, dy))
    else:
        return 0.7
    if not diffs:
        return 0.5
    mean = sum(diffs) / len(diffs)
    if mean == 0:
        return 0.5
    variance = sum((d - mean) ** 2 for d in diffs) / len(diffs)
    return max(0.0, min(1.0, 1.0 - math.sqrt(variance) / max(mean, 0.01)))


def _power_efficiency(trajectory: list) -> float:
    """How much energy did we burn? 0-1, higher is more efficient."""
    if not trajectory:
        return 0.5
    last = trajectory[-1]
    if "battery" not in last:
        return 0.8
    drop = 100.0 - last["battery"]
    # 0% drop → perfect; 10% drop over a short test → ok; 50%+ → bad
    return max(0.0, min(1.0, 1.0 - drop / 30.0))


def run_scenario(workspace: dict,
                 scenario_name: str,
                 param_override: dict = None,
                 note: str = "",
                 workspace_store=None,
                 dt_override: float | None = None) -> dict:
    """Run one scenario against a workspace's physics model and return an
    iteration dict. Mutates workspace in place (via workspace_store).

    Args:
        workspace: The workspace dict to run against.
        scenario_name: Name from scenarios.SCENARIOS.
        param_override: User overrides for the scenario's editable params.
        note: User note to store with the iteration.
        workspace_store: The store, for appending the iteration + snapshot.
        dt_override: Optional tick rate override (seconds). When None, uses
                     the scenario's dt_s. Must be >= 0.005 (200 Hz cap) and
                     <= 0.5 (2 Hz floor) to keep integration stable.
    """
    sc = get_scenario(scenario_name)
    if sc is None:
        raise ValueError(f"Unknown scenario: {scenario_name}")

    device_type = workspace.get("device_type", "unknown")
    if device_type not in sc.device_types:
        raise ValueError(
            f"Scenario '{scenario_name}' is for {sc.device_types}, not '{device_type}'")

    # Cap total duration to avoid runaway scenarios (a malicious or
    # misconfigured param_override could ask for hours of simulation).
    max_duration = 120.0
    if _omnix_settings is not None:
        max_duration = _omnix_settings.simulation_max_duration
    if sc.duration_s > max_duration:
        raise ValueError(
            f"Scenario duration {sc.duration_s}s exceeds max {max_duration}s")

    # Get or create physics
    phys_snapshot = workspace.get("physics")
    physics = make_physics(device_type, phys_snapshot)

    # Resolve params
    params = dict(sc.params)
    if param_override:
        params.update(param_override)

    # Step through the scenario
    dt = dt_override if dt_override is not None else sc.dt_s
    dt = max(0.005, min(0.5, dt))    # enforce stable bounds

    # World-level ambient wind (same vector for the whole run; scenarios
    # that want gusts can override per-step via their command builders)
    wind = workspace.get("world", {}).get("wind_m_s", 0.0)
    if isinstance(wind, (int, float)):
        # Scalar "wind speed" — apply along +X as a simple default
        wind_vec = [float(wind), 0.0, 0.0]
    elif isinstance(wind, (list, tuple)) and len(wind) == 3:
        wind_vec = [float(w) for w in wind]
    else:
        wind_vec = [0.0, 0.0, 0.0]

    state = _init_state(device_type)
    total_steps = int(sc.duration_s / dt)
    trajectory = []
    ref_trajectory = []
    per_step_error = []

    t = 0.0
    for _ in range(total_steps):
        cmd = sc.command_at(t, params) if sc.command_at else {}
        ref = sc.reference_at(t, params) if sc.reference_at else {}
        if device_type == "drone" and any(w != 0.0 for w in wind_vec):
            cmd = {**cmd, "wind_m_s": wind_vec}
        state = _physics_step(physics, device_type, cmd, dt, state)
        # Tiny observation noise so "live" runs look realistic
        if device_type == "drone":
            for i in range(3):
                state["pos"][i] += random.gauss(0, physics.params["sensor_noise_std"] * 0.02)
        obs = _sample_for_trajectory(device_type, state)
        trajectory.append({"t": round(t, 3), **obs})
        ref_trajectory.append({"t": round(t, 3), **ref})
        per_step_error.append(_error_between(device_type, obs, ref))
        t += dt

    # Metrics
    mean_err = sum(per_step_error) / len(per_step_error) if per_step_error else 0.0
    max_err = max(per_step_error) if per_step_error else 0.0
    tracking = max(0.0, min(1.0, 1.0 - mean_err / 2.0))
    stability = _stability_score(trajectory, device_type)
    smoothness = _smoothness(trajectory, device_type)
    power = _power_efficiency(trajectory)
    overall = round((tracking * 0.4 + stability * 0.25 + smoothness * 0.2 + power * 0.15), 3)

    metrics = {
        "tracking_error_m": round(mean_err, 3),
        "max_error_m": round(max_err, 3),
        "tracking_score": round(tracking, 3),
        "stability": round(stability, 3),
        "smoothness": round(smoothness, 3),
        "power_efficiency": round(power, 3),
        "overall": overall,
    }

    # Let the physics learn from this run — weight by duration relative to nominal.
    learn_weight = max(0.3, min(2.0, sc.duration_s / 10.0))
    physics.observe(None, weight=learn_weight)

    # Persist physics snapshot on the workspace
    if workspace_store is not None:
        workspace_store.set_physics(workspace["device_id"], physics.snapshot())

    # Downsample trajectory for storage/display (cap ~120 points)
    stride = max(1, len(trajectory) // 120)
    traj_small = trajectory[::stride]
    ref_small = ref_trajectory[::stride]

    iteration = {
        "scenario": scenario_name,
        "scenario_display_name": sc.display_name,
        "scenario_icon": sc.icon,
        "duration_s": sc.duration_s,
        "dt_s": dt,
        "wind_m_s": wind_vec if device_type == "drone" else None,
        "params": params,
        "metrics": metrics,
        "trajectory": traj_small,
        "reference": ref_small,
        "note": note or "",
        "physics_after": physics.snapshot(),
        "timestamp": time.time(),
    }

    if workspace_store is not None:
        iteration = workspace_store.append_iteration(workspace["device_id"], iteration)

    return iteration
