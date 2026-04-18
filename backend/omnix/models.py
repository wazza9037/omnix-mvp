"""
Typed dataclasses for every shared payload shape.

These are the canonical domain types — routes accept and return these;
services operate on these; tests build them directly. Using dataclasses
(instead of pulling in Pydantic) keeps the zero-dependency promise intact
while giving us:
  - Static-typing friendliness
  - Easy JSON serialization via asdict()
  - Equality + clear repr for tests

All types here are JSON-round-trippable. Nested dicts (telemetry data, for
example) are kept as `dict[str, Any]` rather than strictly typed — the
domain is too heterogeneous (a drone's telemetry differs from a light's)
to usefully enforce at the type level.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


# ── Connectors ─────────────────────────────────────────────────────

class ConnectorState(str, Enum):
    """Lifecycle states a connector instance moves through."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"       # connected but with errors / missing heartbeats
    ERROR = "error"
    RECONNECTING = "reconnecting"


@dataclass
class ConnectorStatus:
    instance_id: str
    connector_id: str
    display_name: str
    tier: int
    state: ConnectorState
    connected: bool
    device_ids: list[str]
    device_count: int
    error: str | None
    started_at: float | None
    uptime_s: float
    last_heartbeat: float | None
    reconnect_attempts: int
    config: dict[str, Any]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.value
        return d


# ── Workspaces + iterations ─────────────────────────────────────────

@dataclass
class IterationMetrics:
    tracking_error_m: float
    max_error_m: float
    tracking_score: float
    stability: float
    smoothness: float
    power_efficiency: float
    overall: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PhysicsSnapshot:
    device_type: str
    params: dict[str, float]
    samples: int
    confidence: float
    fit_error: float
    last_updated: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WorkspaceSummary:
    """Light-weight workspace entry for tab-bar / list views."""
    workspace_id: str
    device_id: str
    name: str
    device_type: str
    color: str
    tags: list[str]
    iteration_count: int
    last_iteration_at: float | None
    best_score: float | None
    physics_confidence: float
    updated_at: float


# ── API primitives ──────────────────────────────────────────────────

@dataclass
class ApiResponse:
    """Envelope for successful responses where we want to include metadata."""
    ok: bool = True
    data: Any = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "data": self.data, "meta": self.meta}


@dataclass
class HealthStatus:
    status: str                     # "healthy" | "degraded" | "unhealthy"
    version: str
    uptime_s: float
    device_count: int
    connector_instances: int
    active_workspaces: int
    started_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)
