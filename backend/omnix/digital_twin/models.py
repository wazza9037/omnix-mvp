"""
Digital Twin data model.

A twin wraps a connected OmnixDevice with two parallel state streams:

  * **sim** — what the adaptive physics model *predicts* the device is doing
    given the commands issued.
  * **real** — what the device *reports* via `get_telemetry()`. For a real
    connector this is hardware telemetry; for simulated devices it's the
    simulator's state; in Virtual Hardware mode it's a separately-maintained
    physics instance seeded with perturbed parameters.

The gap between sim and real is the *divergence*, measured per-channel and
rolled up into a single `sync_score` (0-100). Divergence drives two things:

  1. **Alerts** — IN_SYNC / DRIFTING / DIVERGED thresholds feed a status
     badge in the UI.
  2. **Learning** — every observation is fed to the AdaptivePhysics model,
     which nudges its parameters toward reality. Over a session the sim
     should converge toward the real device's dynamics.

The twin is JSON round-trippable so sessions can be recorded and replayed.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


# ── Enums ──────────────────────────────────────────────────────────

class TwinMode(str, Enum):
    SIM_ONLY = "sim_only"                # just run physics, ignore telemetry
    REAL_ONLY = "real_only"              # only track real telemetry
    TWIN = "twin"                        # both, compare
    VIRTUAL_HARDWARE = "virtual_hardware" # both + use a perturbed physics as "real"


class SyncStatus(str, Enum):
    UNINIT = "uninit"
    IN_SYNC = "in_sync"       # low error
    DRIFTING = "drifting"     # error > yellow threshold
    DIVERGED = "diverged"     # error > red threshold
    DISCONNECTED = "disconnected"


# ── Divergence metrics ────────────────────────────────────────────

@dataclass
class DivergenceMetrics:
    """One sample of per-channel error between sim and real states."""
    position_error_m: float = 0.0
    orientation_error_deg: float = 0.0
    velocity_error_m_s: float = 0.0
    battery_error_pct: float = 0.0
    joint_error_deg: float = 0.0       # for arms
    sync_score: float = 100.0          # 0..100, higher = more in sync
    status: SyncStatus = SyncStatus.UNINIT
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


# ── Recorded session ──────────────────────────────────────────────

@dataclass
class SessionFrame:
    """One time-slice of a recorded twin session."""
    t: float                     # seconds since session start
    sim: dict[str, Any]
    real: dict[str, Any]
    divergence: dict[str, Any]
    command: tuple[str, dict] | None = None   # if a command was issued in this frame

    def to_dict(self) -> dict:
        out = {"t": round(self.t, 3), "sim": self.sim,
               "real": self.real, "divergence": self.divergence}
        if self.command is not None:
            out["command"] = {"name": self.command[0], "params": self.command[1]}
        return out


@dataclass
class SessionRecord:
    session_id: str
    device_id: str
    mode: TwinMode
    started_at: float
    ended_at: float | None = None
    frames: list[SessionFrame] = field(default_factory=list)
    label: str = ""
    # Stats computed on stop
    mean_sync_score: float | None = None
    max_position_error_m: float | None = None
    # Physics snapshot at start and end for tuning
    physics_before: dict | None = None
    physics_after: dict | None = None

    @staticmethod
    def new(device_id: str, mode: TwinMode,
            physics_before: dict | None = None,
            label: str = "") -> "SessionRecord":
        return SessionRecord(
            session_id=f"sess-{uuid.uuid4().hex[:10]}",
            device_id=device_id, mode=mode,
            started_at=time.time(),
            physics_before=physics_before,
            label=label,
        )

    def summary(self) -> dict:
        """Light-weight dict for listing sessions (no frames)."""
        return {
            "session_id": self.session_id,
            "device_id": self.device_id,
            "mode": self.mode.value,
            "label": self.label,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_s": round((self.ended_at or time.time()) - self.started_at, 2),
            "frame_count": len(self.frames),
            "mean_sync_score": self.mean_sync_score,
            "max_position_error_m": self.max_position_error_m,
        }

    def to_dict(self, include_frames: bool = True) -> dict:
        out = self.summary()
        if include_frames:
            out["frames"] = [f.to_dict() for f in self.frames]
            out["physics_before"] = self.physics_before
            out["physics_after"] = self.physics_after
        return out


# ── Public twin state (serialized for the frontend) ───────────────

@dataclass
class TwinSnapshot:
    """JSON-friendly view of a twin at a moment in time."""
    twin_id: str
    device_id: str
    device_type: str
    mode: TwinMode
    status: SyncStatus
    sim_state: dict[str, Any]
    real_state: dict[str, Any]
    divergence: DivergenceMetrics
    sync_score: float
    history: list[dict]          # last N frames (for sparklines)
    is_recording: bool
    active_session_id: str | None
    tick_hz: float
    physics: dict | None         # current physics snapshot
    last_command: dict | None    # {"name":..., "params":..., "ts":...}

    def to_dict(self) -> dict:
        return {
            "twin_id": self.twin_id,
            "device_id": self.device_id,
            "device_type": self.device_type,
            "mode": self.mode.value,
            "status": self.status.value,
            "sim_state": self.sim_state,
            "real_state": self.real_state,
            "divergence": self.divergence.to_dict(),
            "sync_score": round(self.sync_score, 1),
            "history": list(self.history),
            "is_recording": self.is_recording,
            "active_session_id": self.active_session_id,
            "tick_hz": self.tick_hz,
            "physics": self.physics,
            "last_command": self.last_command,
        }


# ── Threshold config ──────────────────────────────────────────────

@dataclass(frozen=True)
class TwinThresholds:
    """Yellow/red sync-status thresholds. Expressed as error magnitudes.

    The overall status is DIVERGED if ANY channel breaches the red
    threshold, DRIFTING if any breaches yellow, IN_SYNC otherwise.
    """
    yellow_position_m: float = 0.5
    red_position_m: float = 1.5
    yellow_orientation_deg: float = 10.0
    red_orientation_deg: float = 25.0
    yellow_velocity_m_s: float = 0.5
    red_velocity_m_s: float = 1.5
    yellow_battery_pct: float = 5.0
    red_battery_pct: float = 15.0


DEFAULT_THRESHOLDS = TwinThresholds()
