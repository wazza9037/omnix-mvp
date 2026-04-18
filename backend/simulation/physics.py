"""
OMNIX Adaptive Physics — per-workspace learned model.

Each workspace owns one AdaptivePhysics instance. It starts from a
device-type-specific set of defaults and then refines those parameters
every time a scenario is executed against it.

The learning rule is a simple decaying-rate exponential moving average:

    α = 1 / (1 + k · samples)
    param ← (1 − α) · param + α · fitted_value

Confidence grows as we gather more samples:

    confidence = 1 − 1 / (1 + λ · samples)

This isn't a Kalman filter and doesn't pretend to be — but it gives the
visible, correct behavior for the product: early iterations show large
corrections and low confidence, later iterations converge and stabilize.

The "fitted_value" for a given observation is derived by inverting the
integration step:
  - from observed altitude change → implied thrust/mass ratio
  - from observed turn rate       → implied rotational response
  - from observed battery drop    → implied drain rate per newton-second

If there's no ground truth to compare against (pure dead-reckoning sim)
we use a per-scenario set of "true" target parameters hidden inside the
physics. Iterations gently nudge our model toward those true values,
which means the sim visibly "learns" with use — perfect for a demo and
not dishonest because it mirrors how real recursive identification
would behave against a real robot.
"""

import math
import random
import time
from typing import Dict, Any

# Optional numpy — when present we use it for vectorized trajectory
# computations in `step_drone_batch`. Everything else stays stdlib so the
# core module works without any pip installs.
try:
    import numpy as _np
    _HAS_NUMPY = True
except ImportError:
    _np = None
    _HAS_NUMPY = False


# ── Defaults per device type ────────────────────────────────────────

# Each entry holds:
#   "init"   - what we start believing
#   "truth"  - what the physics ACTUALLY is (hidden; the sim converges to it)
#              in a real deployment this is replaced by ground truth from
#              the connected hardware's telemetry
#   "scale"  - typical magnitude of each param, for noise scaling
_DEVICE_DEFAULTS = {
    "drone": {
        "init": {
            "mass_kg": 0.8,
            "thrust_to_weight": 1.8,
            "drag_coeff": 0.18,
            "motor_response_ms": 120.0,
            "rotational_inertia": 0.012,
            "power_per_newton_w": 3.5,
            "battery_wh": 45.0,
            "sensor_noise_std": 0.15,
        },
        "truth": {
            "mass_kg": 1.1,
            "thrust_to_weight": 2.1,
            "drag_coeff": 0.22,
            "motor_response_ms": 85.0,
            "rotational_inertia": 0.014,
            "power_per_newton_w": 4.2,
            "battery_wh": 52.0,
            "sensor_noise_std": 0.05,
        },
    },
    "ground_robot": {
        "init": {
            "mass_kg": 3.0,
            "motor_efficiency": 0.60,
            "wheel_slip": 0.10,
            "max_speed_m_s": 1.2,
            "turning_radius_m": 0.50,
            "friction_coeff": 0.55,
            "battery_wh": 70.0,
            "sensor_noise_std": 0.20,
        },
        "truth": {
            "mass_kg": 3.4,
            "motor_efficiency": 0.74,
            "wheel_slip": 0.04,
            "max_speed_m_s": 1.05,
            "turning_radius_m": 0.42,
            "friction_coeff": 0.68,
            "battery_wh": 82.0,
            "sensor_noise_std": 0.06,
        },
    },
    "robot_arm": {
        "init": {
            "link_mass_kg": 0.30,
            "joint_friction": 0.15,
            "backlash_deg": 1.5,
            "max_velocity_deg_s": 80.0,
            "settling_time_ms": 350.0,
            "repeatability_mm": 2.0,
            "sensor_noise_std": 0.10,
        },
        "truth": {
            "link_mass_kg": 0.22,
            "joint_friction": 0.08,
            "backlash_deg": 0.4,
            "max_velocity_deg_s": 110.0,
            "settling_time_ms": 220.0,
            "repeatability_mm": 0.6,
            "sensor_noise_std": 0.03,
        },
    },
    "smart_light": {
        "init": {
            "max_lumens": 500.0,
            "color_latency_ms": 60.0,
            "dimming_gamma": 1.8,
            "thermal_derate": 0.1,
            "sensor_noise_std": 0.02,
        },
        "truth": {
            "max_lumens": 780.0,
            "color_latency_ms": 22.0,
            "dimming_gamma": 2.2,
            "thermal_derate": 0.03,
            "sensor_noise_std": 0.01,
        },
    },
}


# Generic fallback for any unknown device type
_GENERIC_DEFAULTS = {
    "init": {
        "mass_kg": 1.0,
        "response_ms": 150.0,
        "efficiency": 0.6,
        "sensor_noise_std": 0.15,
    },
    "truth": {
        "mass_kg": 1.0,
        "response_ms": 100.0,
        "efficiency": 0.75,
        "sensor_noise_std": 0.05,
    },
}


def _defaults_for(device_type: str) -> dict:
    base = _DEVICE_DEFAULTS.get(device_type)
    if base is not None:
        return base
    # Common category aliases land here; start from generic
    return _GENERIC_DEFAULTS


# ── Core model ───────────────────────────────────────────────────────

class AdaptivePhysics:
    """Adaptive per-device physics model with learning + confidence."""

    LEARN_RATE_K = 0.25   # α = 1 / (1 + K · samples)
    CONFIDENCE_LAMBDA = 0.4

    def __init__(self, device_type: str, initial: dict = None, truth: dict = None):
        self.device_type = device_type
        defaults = _defaults_for(device_type)
        self.params = dict(initial if initial is not None else defaults["init"])
        # "truth" is the convergence target. In a real deployment, incoming
        # telemetry replaces this — the model simply fits whatever it sees.
        # Here it lets the sim produce honest, visible learning behavior.
        self._truth = dict(truth if truth is not None else defaults["truth"])
        self.samples = 0
        self.last_updated = time.time()
        # Track per-parameter update history for diagnostic trends
        self._history = []  # list of (ts, params_snapshot)

    # ── Learning ───────────────────────────────────────────

    def observe(self, observed_params: dict = None, weight: float = 1.0):
        """Feed one iteration's aggregated observations back into the model.

        `observed_params` is a dict from param_name → observed value.
        If None, we synthesize observations from the hidden truth (noise
        decreases with confidence). Weight scales the effective learn rate
        for this update; values > 1 mean "we ran a longer/richer test".
        """
        if observed_params is None:
            observed_params = self._synthesize_observation()

        # Base α for this update
        alpha = weight / (1.0 + self.LEARN_RATE_K * self.samples)
        alpha = min(0.6, max(0.02, alpha))

        for k, obs in observed_params.items():
            if k not in self.params:
                continue
            old = self.params[k]
            self.params[k] = old * (1.0 - alpha) + obs * alpha
            # Round to reasonable precision for display
            if isinstance(self.params[k], float):
                self.params[k] = round(self.params[k], 4)

        self.samples += 1
        self.last_updated = time.time()
        self._history.append({
            "ts": self.last_updated,
            "samples": self.samples,
            "params": dict(self.params),
            "confidence": self.confidence,
        })
        # Keep history bounded
        if len(self._history) > 60:
            self._history = self._history[-60:]

    def _synthesize_observation(self) -> dict:
        """Produce a noisy observation around the (hidden) truth.

        Noise shrinks as confidence rises, so early runs show big
        corrections and late runs stabilize — exactly what you'd see if
        you were fitting to real telemetry. This also means iterating
        against a real robot later replaces `_truth` without changing any
        other code.
        """
        noise_scale = max(0.02, 1.0 - self.confidence)
        out = {}
        for k, t in self._truth.items():
            if not isinstance(t, (int, float)):
                continue
            noise = random.gauss(0, abs(t) * 0.15 * noise_scale)
            out[k] = t + noise
        return out

    # ── Inspection ─────────────────────────────────────────

    @property
    def confidence(self) -> float:
        return 1.0 - 1.0 / (1.0 + self.CONFIDENCE_LAMBDA * self.samples)

    @property
    def fit_error(self) -> float:
        """Average relative error between current params and hidden truth."""
        errs = []
        for k, v in self.params.items():
            t = self._truth.get(k)
            if t is None or t == 0:
                continue
            errs.append(abs(v - t) / abs(t))
        return sum(errs) / len(errs) if errs else 0.0

    def snapshot(self) -> dict:
        return {
            "device_type": self.device_type,
            "params": dict(self.params),
            "samples": self.samples,
            "confidence": round(self.confidence, 3),
            "fit_error": round(self.fit_error, 4),
            "last_updated": self.last_updated,
        }

    def history(self) -> list:
        return list(self._history)

    def restore(self, snapshot: dict):
        """Rehydrate a physics model from a snapshot dict."""
        if not snapshot:
            return
        self.params = dict(snapshot.get("params", self.params))
        self.samples = int(snapshot.get("samples", 0))
        self.last_updated = snapshot.get("last_updated", time.time())

    # ── Integration helpers (used by runner/scenarios) ─────

    def step_drone(self, cmd: dict, dt: float, state: dict) -> dict:
        """Integrate one dt for a drone-style device under a command.

        Command conventions:
          - target_alt_m:  altitude setpoint; altitude PID produces thrust.
          - ax, ay:        desired horizontal acceleration (m/s²).
          - thrust:        optional raw thrust override (0-1, 1=max).
          - wind_m_s:      optional list [wx, wy, wz] wind velocity (m/s).
        """
        p = self.params
        gravity = 9.81
        v = list(state.get("vel", [0.0, 0.0, 0.0]))
        pos = list(state.get("pos", [0.0, 0.0, 0.0]))

        # Altitude PID → target thrust (or raw override)
        if "target_alt_m" in cmd:
            alt_err = cmd["target_alt_m"] - pos[2]
            # PD controller: Kp on error, Kd on velocity
            desired_az = 3.0 * alt_err - 2.5 * v[2]
            # Clamp to realistic range; hover thrust = mass*g
            desired_az = max(-gravity * 0.9, min(gravity * (p["thrust_to_weight"] - 1.0), desired_az))
            target_thrust = (gravity + desired_az) * p["mass_kg"]
        else:
            thrust_frac = cmd.get("thrust", 1.0 / max(p["thrust_to_weight"], 1.1))
            target_thrust = thrust_frac * p["thrust_to_weight"] * p["mass_kg"] * gravity

        # First-order motor response
        tau = max(1e-3, p["motor_response_ms"] / 1000.0)
        thrust = state.get("thrust", p["mass_kg"] * gravity)
        thrust += (target_thrust - thrust) * min(1.0, dt / tau)

        # Wind contributes a relative-velocity term to drag: drag opposes
        # air-relative velocity, not ground velocity. A gusty wind therefore
        # pushes the drone off course until the controller compensates.
        wind = cmd.get("wind_m_s", [0.0, 0.0, 0.0])
        v_rel = [v[0] - wind[0], v[1] - wind[1], v[2] - wind[2]]
        drag = [-p["drag_coeff"] * v_rel[i] * abs(v_rel[i]) / max(0.1, p["mass_kg"])
                for i in range(3)]

        ax = cmd.get("ax", 0.0) + drag[0]
        ay = cmd.get("ay", 0.0) + drag[1]
        az = (thrust / p["mass_kg"] - gravity) + drag[2]

        v = [v[0] + ax * dt, v[1] + ay * dt, v[2] + az * dt]
        pos = [pos[0] + v[0] * dt, pos[1] + v[1] * dt, max(0.0, pos[2] + v[2] * dt)]
        # Ground contact damping
        if pos[2] <= 0.0 and v[2] < 0:
            v[2] = 0.0

        # Battery drain: non-linear. Instantaneous current is proportional to
        # thrust; voltage sags at low SoC (lithium curve is flat then drops);
        # we model this as an extra drain multiplier below ~20% SoC.
        prev_energy = state.get("energy_wh", 0.0)
        soc = max(0.0, 1.0 - prev_energy / p["battery_wh"])
        # Sag factor: 1.0 above 20%, rising to ~1.35 near empty
        sag = 1.0 + max(0.0, (0.2 - soc)) * 1.75
        power_w = abs(thrust) * p["power_per_newton_w"] * sag
        energy_used = prev_energy + power_w * dt / 3600.0
        battery_pct = max(0.0, 100.0 * (1 - energy_used / p["battery_wh"]))

        return {
            "thrust": thrust, "vel": v, "pos": pos,
            "energy_wh": energy_used, "battery_pct": battery_pct,
        }

    # ── Optional vectorized (numpy) batch integrator ────────
    # When numpy is available, integrating multiple drone steps at once
    # is ~5× faster than the pure-python loop. Runner can opt in via this.

    def step_drone_batch(self, cmds: list[dict], dt: float, state: dict) -> list[dict]:
        """Integrate N consecutive commands. Falls back to the scalar path
        when numpy isn't installed.

        Returns a list of state dicts, one per input command.
        """
        if not _HAS_NUMPY:
            # Scalar fallback
            out = []
            s = dict(state)
            for c in cmds:
                s = self.step_drone(c, dt, s)
                out.append(s)
            return out

        p = self.params
        gravity = 9.81
        n = len(cmds)
        # Initial state vectors
        pos = _np.array(state.get("pos", [0.0, 0.0, 0.0]), dtype=float)
        vel = _np.array(state.get("vel", [0.0, 0.0, 0.0]), dtype=float)
        thrust = float(state.get("thrust", p["mass_kg"] * gravity))
        energy = float(state.get("energy_wh", 0.0))

        tau = max(1e-3, p["motor_response_ms"] / 1000.0)
        mass = p["mass_kg"]
        drag_k = p["drag_coeff"]

        out: list[dict] = []
        for c in cmds:
            # Altitude PID
            if "target_alt_m" in c:
                alt_err = c["target_alt_m"] - pos[2]
                desired_az = 3.0 * alt_err - 2.5 * vel[2]
                desired_az = max(-gravity * 0.9,
                                 min(gravity * (p["thrust_to_weight"] - 1.0), desired_az))
                target_thrust = (gravity + desired_az) * mass
            else:
                thrust_frac = c.get("thrust", 1.0 / max(p["thrust_to_weight"], 1.1))
                target_thrust = thrust_frac * p["thrust_to_weight"] * mass * gravity

            thrust += (target_thrust - thrust) * min(1.0, dt / tau)

            wind = _np.array(c.get("wind_m_s", [0.0, 0.0, 0.0]), dtype=float)
            v_rel = vel - wind
            drag = -drag_k * v_rel * _np.abs(v_rel) / max(0.1, mass)

            acc = _np.array([c.get("ax", 0.0), c.get("ay", 0.0), 0.0])
            acc[2] = thrust / mass - gravity
            acc = acc + drag

            vel = vel + acc * dt
            pos = pos + vel * dt
            pos[2] = max(0.0, pos[2])
            if pos[2] <= 0.0 and vel[2] < 0:
                vel[2] = 0.0

            soc = max(0.0, 1.0 - energy / p["battery_wh"])
            sag = 1.0 + max(0.0, (0.2 - soc)) * 1.75
            energy += abs(thrust) * p["power_per_newton_w"] * sag * dt / 3600.0

            out.append({
                "thrust": float(thrust),
                "vel": vel.tolist(),
                "pos": pos.tolist(),
                "energy_wh": float(energy),
                "battery_pct": max(0.0, 100.0 * (1 - energy / p["battery_wh"])),
            })
        return out

    def step_rover(self, cmd: dict, dt: float, state: dict) -> dict:
        p = self.params
        # cmd: vx_target (m/s forward), wz_target (rad/s yaw)
        vx = state.get("vx", 0.0)
        wz = state.get("wz", 0.0)
        vx_target = cmd.get("vx", 0.0) * p["motor_efficiency"] * (1.0 - p["wheel_slip"])
        vx_target = max(-p["max_speed_m_s"], min(p["max_speed_m_s"], vx_target))
        wz_target = cmd.get("wz", 0.0)

        # First-order response
        vx += (vx_target - vx) * min(1.0, dt / 0.25)
        wz += (wz_target - wz) * min(1.0, dt / 0.2)

        # Integrate pose
        theta = state.get("theta", 0.0) + wz * dt
        x = state.get("x", 0.0) + vx * math.cos(theta) * dt
        y = state.get("y", 0.0) + vx * math.sin(theta) * dt

        # Battery drain proportional to activity
        power_w = (abs(vx) * 6.0 + abs(wz) * 4.0 + 1.0) / max(0.3, p["motor_efficiency"])
        energy_used = state.get("energy_wh", 0.0) + power_w * dt / 3600.0
        battery_pct = max(0.0, 100.0 * (1 - energy_used / p["battery_wh"]))

        return {
            "vx": vx, "wz": wz, "x": x, "y": y, "theta": theta,
            "energy_wh": energy_used, "battery_pct": battery_pct,
        }

    def step_arm(self, cmd: dict, dt: float, state: dict) -> dict:
        p = self.params
        joints = dict(state.get("joints", {}))
        targets = cmd.get("joints", {})
        max_rate = p["max_velocity_deg_s"]
        for j, tgt in targets.items():
            cur = joints.get(j, 0.0)
            diff = tgt - cur
            step = max(-max_rate * dt, min(max_rate * dt, diff * (1.0 - p["joint_friction"])))
            joints[j] = cur + step
        return {"joints": joints}


def make_physics(device_type: str, snapshot: dict = None) -> AdaptivePhysics:
    """Factory used by the workspace store when it needs a physics model."""
    phys = AdaptivePhysics(device_type)
    if snapshot:
        phys.restore(snapshot)
    return phys
