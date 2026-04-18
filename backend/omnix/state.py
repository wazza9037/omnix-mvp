"""
Application state container.

A single `AppState` instance holds the runtime singletons the HTTP layer
talks to: the device registry, workspace store, connector manager, VPE
engine, movement executor, and Pi/ESP32 agent tables.

Historically these lived as module-level globals in server_simple.py. Moving
them into an explicit container makes dependencies testable, visible, and
swappable — tests can instantiate a fresh AppState without touching the
real server, and routes take state as a parameter instead of reaching into
module scope.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from connector_manager import ConnectorManager
    from workspace_store import WorkspaceStore
    from vpe.engine import VisualPhysicsEngine
    from device_store import DeviceStore
    from movements.executor import MovementExecutor


@dataclass
class AppState:
    """Runtime state shared across the HTTP handlers and services."""
    # Core registries — plain dicts so existing routes keep working
    devices: dict[str, Any] = field(default_factory=dict)
    pi_agents: dict[str, dict] = field(default_factory=dict)
    pi_command_queues: dict[str, list] = field(default_factory=dict)
    pi_telemetry: dict[str, dict] = field(default_factory=dict)
    pi_command_results: dict[str, dict] = field(default_factory=dict)

    # ESP32 agent tables (shared with connectors.esp32_wifi module-level dicts)
    esp32_agents: dict[str, dict] = field(default_factory=dict)
    esp32_command_queues: dict[str, list] = field(default_factory=dict)
    esp32_telemetry: dict[str, dict] = field(default_factory=dict)

    # Service singletons
    vpe_engine: "VisualPhysicsEngine | None" = None
    device_store: "DeviceStore | None" = None
    workspace_store: "WorkspaceStore | None" = None
    movement_executor: "MovementExecutor | None" = None
    connector_manager: "ConnectorManager | None" = None

    started_at: float = field(default_factory=time.time)

    def uptime_s(self) -> float:
        return time.time() - self.started_at
