"""
Twin lifecycle manager.

Holds one DigitalTwin per device_id. The twin wraps:

  * The device itself (OmnixDevice)
  * A Predictor (adaptive physics driven by incoming commands)
  * Optionally a "truth" Predictor for Virtual Hardware mode (perturbed
    parameters stand in for real hardware)
  * A history ring + optional recording

Exposes a process-wide singleton `REGISTRY` that routes talk to. A single
daemon thread ticks every live twin at the configured rate.
"""

from __future__ import annotations

import math
import random
import threading
import time
from collections import deque
from typing import Any

from .models import (
    TwinMode, SyncStatus, DivergenceMetrics, TwinSnapshot,
    SessionRecord, SessionFrame, DEFAULT_THRESHOLDS,
)
from .divergence_detector import compute_divergence, summarize
from .predictor import Predictor, initial_state, extract_for_divergence, _merge_telemetry

try:
    from simulation.physics import AdaptivePhysics, make_physics
    _HAS_PHYSICS = True
except Exception:
    _HAS_PHYSICS = False


# Perturbation factors applied to the "truth" physics instance in Virtual
# Hardware mode. These make the hidden side of the twin behave like real
# hardware would — different enough to produce visible divergence, close
# enough that the auto-tuner can converge.
_VH_PERTURBATIONS = {
    "mass_kg": 1.15,
    "thrust_to_weight": 0.92,
    "drag_coeff": 1.25,
    "motor_response_ms": 1.4,
    "battery_wh": 0.88,
    "motor_efficiency": 0.85,
    "max_speed_m_s": 0.9,
    "wheel_slip": 1.6,
    "friction_coeff": 0.9,
}


class DigitalTwin:
    """A live twin for one device."""

    def __init__(self, device, workspace=None,
                 mode: TwinMode = TwinMode.TWIN,
                 tick_hz: float = 10.0,
                 history_window: int = 300):
        self.device = device
        self.device_id: str = device.id
        self.device_type: str = getattr(device, "device_type", "unknown")
        self.workspace = workspace
        self.mode = mode
        self.tick_hz = tick_hz
        self.history_window = history_window

        self._lock = threading.Lock()
        self._stop = threading.Event()

        # Snapshot physics from the workspace so the twin starts out with
        # everything the lab notebook already learned.
        phys_snapshot = None
        if workspace is not None and workspace.get("physics"):
            phys_snapshot = workspace["physics"]

        # Sim (prediction) side — driven by commands
        initial_tele = _safe_telemetry(device)
        self.predictor = Predictor(
            self.device_type,
            physics=(make_physics(self.device_type, phys_snapshot)
                     if _HAS_PHYSICS else None),
            telemetry=initial_tele,
        )

        # "Truth" side for Virtual Hardware mode — a second physics with
        # perturbed params. Only used when mode == VIRTUAL_HARDWARE.
        self.truth_predictor: Predictor | None = None
        if mode == TwinMode.VIRTUAL_HARDWARE:
            self.truth_predictor = self._build_truth_predictor(initial_tele)

        # State
        self.last_command: tuple[str, dict, float] | None = None
        self.divergence = DivergenceMetrics()
        self.history: deque = deque(maxlen=history_window)

        # Recording
        self.active_session: SessionRecord | None = None

    # ── Construction helpers ──────────────────────────────

    def _build_truth_predictor(self, telemetry: dict | None) -> Predictor:
        if not _HAS_PHYSICS:
            return Predictor(self.device_type, telemetry=telemetry)
        truth_physics = make_physics(self.device_type,
                                     self.predictor.physics_snapshot())
        # Perturb the truth parameters so it diverges from the predictor
        for k, factor in _VH_PERTURBATIONS.items():
            if k in truth_physics.params:
                truth_physics.params[k] *= factor
        # Freeze the truth: no learning happens on the hidden side
        truth_physics.samples = 0
        return Predictor(self.device_type, physics=truth_physics,
                         telemetry=telemetry)

    # ── Command hook (called by NLP executor / connectors) ─

    def on_command(self, command: str, params: dict | None) -> None:
        """Record that a command has been dispatched to the device."""
        with self._lock:
            self.last_command = (command, dict(params or {}), time.time())
            self.predictor.set_command(command, params or {})
            if self.truth_predictor is not None:
                self.truth_predictor.set_command(command, params or {})

    # ── Mode control ──────────────────────────────────────

    def set_mode(self, mode: TwinMode) -> None:
        with self._lock:
            if mode == self.mode:
                return
            self.mode = mode
            if mode == TwinMode.VIRTUAL_HARDWARE and self.truth_predictor is None:
                self.truth_predictor = self._build_truth_predictor(
                    _safe_telemetry(self.device))
            elif mode != TwinMode.VIRTUAL_HARDWARE:
                self.truth_predictor = None

    # ── Per-tick ──────────────────────────────────────────

    def tick(self, dt: float) -> None:
        with self._lock:
            # Advance the sim predictor
            self.predictor.step(dt)
            sim_state = self.predictor.current_state()

            # Compute "real" state from either device telemetry or truth sim
            if self.mode == TwinMode.VIRTUAL_HARDWARE and self.truth_predictor:
                self.truth_predictor.step(dt)
                real_state = self.truth_predictor.current_state()
                # Add mild sensor noise so the trace looks real
                real_state["pos"] = [v + random.gauss(0, 0.02)
                                     for v in real_state["pos"]]
                real_state["yaw_deg"] += random.gauss(0, 0.5)
            else:
                tele = _safe_telemetry(self.device) or {}
                real_state = initial_state(self.device_type, tele)
                real_state = extract_for_divergence(real_state, self.device_type)

            # Compute divergence
            self.divergence = compute_divergence(sim_state, real_state)

            # Feed observation back into predictor's physics for learning
            # (only when we have a reasonable signal — low-noise modes)
            self._feed_observation(real_state)

            # Append to history (for sparklines)
            entry = {
                "t": time.time(),
                "sim": sim_state,
                "real": real_state,
                "divergence": self.divergence.to_dict(),
            }
            self.history.append(entry)

            # Recording
            if self.active_session is not None:
                cmd_tuple = None
                if self.last_command and self.last_command[2] > self.active_session.started_at:
                    # Only include a command in the frame if it was issued
                    # recently enough — keeps the frame a true snapshot.
                    if time.time() - self.last_command[2] < (1.5 / self.tick_hz):
                        cmd_tuple = (self.last_command[0], self.last_command[1])
                frame = SessionFrame(
                    t=time.time() - self.active_session.started_at,
                    sim=sim_state, real=real_state,
                    divergence=self.divergence.to_dict(),
                    command=cmd_tuple,
                )
                self.active_session.frames.append(frame)

    def _feed_observation(self, real_state: dict) -> None:
        """When sim and real agree roughly, nudge physics toward reality."""
        if not self.predictor.physics:
            return
        # Only learn when we're not totally diverged — otherwise we'd pull
        # params toward noise.
        if self.divergence.status == SyncStatus.DIVERGED:
            return
        # Synthesize a light observation from the current drift
        # (the adaptive model's own observe() handles the recursive update)
        self.predictor.physics.observe(weight=0.15)

    # ── Sessions ──────────────────────────────────────────

    def start_session(self, label: str = "") -> SessionRecord:
        with self._lock:
            if self.active_session is not None:
                return self.active_session
            phys = self.predictor.physics_snapshot()
            self.active_session = SessionRecord.new(
                device_id=self.device_id, mode=self.mode,
                physics_before=phys, label=label,
            )
            return self.active_session

    def stop_session(self) -> SessionRecord | None:
        with self._lock:
            sess = self.active_session
            if sess is None:
                return None
            sess.ended_at = time.time()
            sess.physics_after = self.predictor.physics_snapshot()
            # Aggregate divergence stats
            from .divergence_detector import summarize
            divergences = [
                self._deserialize_divergence(f.divergence)
                for f in sess.frames
            ]
            stats = summarize(divergences)
            sess.mean_sync_score = stats.get("mean_sync_score")
            sess.max_position_error_m = stats.get("max_position_error_m")
            self.active_session = None
            return sess

    @staticmethod
    def _deserialize_divergence(d: dict) -> DivergenceMetrics:
        m = DivergenceMetrics(
            position_error_m=d.get("position_error_m", 0),
            orientation_error_deg=d.get("orientation_error_deg", 0),
            velocity_error_m_s=d.get("velocity_error_m_s", 0),
            battery_error_pct=d.get("battery_error_pct", 0),
            joint_error_deg=d.get("joint_error_deg", 0),
            sync_score=d.get("sync_score", 100.0),
        )
        m.status = SyncStatus(d.get("status", "in_sync"))
        return m

    # ── Calibration ───────────────────────────────────────

    def run_calibration(self) -> dict:
        """Run a short, device-type-appropriate calibration sequence.

        Returns a dict describing what happened. The actual command
        dispatch is done by the caller (server route) so we re-use the
        NLP executor's infrastructure for safety and logging.
        """
        sequences = {
            "drone": [
                ("takeoff", {"altitude_m": 2.0}),
                ("hover",   {"duration_s": 1.5}),
                ("land",    {}),
            ],
            "ground_robot": [
                ("drive", {"direction": "forward", "speed": 40, "duration_ms": 1200}),
                ("emergency_stop", {}),
                ("drive", {"direction": "backward", "speed": 40, "duration_ms": 1200}),
                ("emergency_stop", {}),
            ],
            "robot_arm": [
                ("go_home", {}),
                ("move_joint", {"joint_index": 0, "angle_deg": 30.0}),
                ("move_joint", {"joint_index": 0, "angle_deg": -30.0}),
                ("go_home", {}),
            ],
        }
        seq = sequences.get(self.device_type, [("ping", {})])
        return {"device_type": self.device_type, "sequence": seq,
                "step_count": len(seq)}

    # ── Snapshot ──────────────────────────────────────────

    def snapshot(self) -> TwinSnapshot:
        with self._lock:
            last = None
            if self.last_command is not None:
                last = {
                    "name": self.last_command[0],
                    "params": self.last_command[1],
                    "ts": self.last_command[2],
                }
            return TwinSnapshot(
                twin_id=f"twin-{self.device_id}",
                device_id=self.device_id,
                device_type=self.device_type,
                mode=self.mode,
                status=self.divergence.status,
                sim_state=self.predictor.current_state(),
                real_state=(self.truth_predictor.current_state()
                            if self.truth_predictor is not None
                            else self._read_real_state()),
                divergence=self.divergence,
                sync_score=self.divergence.sync_score,
                history=list(self.history)[-80:],
                is_recording=self.active_session is not None,
                active_session_id=(self.active_session.session_id
                                   if self.active_session else None),
                tick_hz=self.tick_hz,
                physics=self.predictor.physics_snapshot(),
                last_command=last,
            )

    def _read_real_state(self) -> dict:
        tele = _safe_telemetry(self.device) or {}
        return extract_for_divergence(
            initial_state(self.device_type, tele), self.device_type)


# ── Process-wide manager ──────────────────────────────────────────

class TwinManager:
    def __init__(self, tick_hz_sim: float = 50.0, tick_hz_real: float = 10.0):
        self._twins: dict[str, DigitalTwin] = {}
        self._sessions: list[SessionRecord] = []         # completed + active
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.tick_hz_sim = tick_hz_sim
        self.tick_hz_real = tick_hz_real

    # ── Lifecycle ──────────────────────────────────────────

    def create(self, device, workspace=None,
               mode: TwinMode = TwinMode.TWIN,
               tick_hz: float | None = None) -> DigitalTwin:
        """Create or return the existing twin for this device."""
        with self._lock:
            if device.id in self._twins:
                t = self._twins[device.id]
                t.set_mode(mode)
                return t
            hz = tick_hz if tick_hz is not None else (
                self.tick_hz_sim if mode in (TwinMode.SIM_ONLY,
                                              TwinMode.VIRTUAL_HARDWARE)
                else self.tick_hz_real
            )
            twin = DigitalTwin(device, workspace=workspace,
                               mode=mode, tick_hz=hz)
            self._twins[device.id] = twin
            self._ensure_thread()
            return twin

    def destroy(self, device_id: str) -> bool:
        with self._lock:
            twin = self._twins.pop(device_id, None)
            if twin and twin.active_session is not None:
                sess = twin.stop_session()
                if sess:
                    self._sessions.append(sess)
            return twin is not None

    def get(self, device_id: str) -> DigitalTwin | None:
        return self._twins.get(device_id)

    def all(self) -> list[DigitalTwin]:
        return list(self._twins.values())

    def shutdown(self) -> None:
        self._stop.set()
        for did in list(self._twins.keys()):
            self.destroy(did)

    # ── Command pass-through ──────────────────────────────

    def forward_command(self, device_id: str, command: str,
                         params: dict | None = None) -> None:
        t = self._twins.get(device_id)
        if t is not None:
            t.on_command(command, params)

    # ── Session management ────────────────────────────────

    def list_sessions(self) -> list[dict]:
        """All completed sessions (summary format) plus any active one."""
        out = [s.summary() for s in self._sessions]
        for t in self._twins.values():
            if t.active_session is not None:
                out.append(t.active_session.summary())
        return sorted(out, key=lambda s: -s.get("started_at", 0))

    def get_session(self, session_id: str) -> SessionRecord | None:
        for s in self._sessions:
            if s.session_id == session_id:
                return s
        for t in self._twins.values():
            if t.active_session and t.active_session.session_id == session_id:
                return t.active_session
        return None

    def add_session(self, session: SessionRecord) -> None:
        """Called by the twin when it finishes recording."""
        with self._lock:
            self._sessions.append(session)

    # ── Background tick loop ──────────────────────────────

    def _ensure_thread(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="twin-tick", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        last = time.time()
        # Run the highest-rate schedule any live twin asks for
        while not self._stop.is_set():
            now = time.time()
            dt = now - last
            last = now
            twins = list(self._twins.values())
            for twin in twins:
                try:
                    twin.tick(dt)
                except Exception:
                    pass   # don't let one twin take down the loop
            # Sleep according to the highest-rate twin's tick_hz
            hz = max((t.tick_hz for t in twins), default=10.0)
            self._stop.wait(1.0 / max(1.0, hz))


# ── Module-level singleton ────────────────────────────────────────

REGISTRY = TwinManager()


# ── Helpers ───────────────────────────────────────────────────────

def _safe_telemetry(device) -> dict | None:
    try:
        return device.get_telemetry() or {}
    except Exception:
        return None
