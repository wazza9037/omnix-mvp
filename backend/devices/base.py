"""
OMNIX Base Device — The foundation every device type inherits from.

This defines the universal interface that ALL devices must implement,
which is what makes OMNIX truly universal. Any device that speaks this
protocol can be controlled from the OMNIX app.
"""

import uuid
import time
import json
from typing import Any
from dataclasses import dataclass, field, asdict


@dataclass
class DeviceCapability:
    """A single action a device can perform."""
    name: str                    # e.g., "move", "takeoff", "set_color"
    description: str             # Human-readable description
    parameters: dict = field(default_factory=dict)  # {param_name: {type, min, max, default, options}}
    category: str = "general"    # Grouping for UI (movement, sensors, settings, etc.)


@dataclass
class DeviceTelemetry:
    """Real-time sensor/state data from the device."""
    timestamp: float = field(default_factory=time.time)
    data: dict = field(default_factory=dict)


class OmnixDevice:
    """
    Base class for all OMNIX-compatible devices.

    Every device must define:
    - device_type: what kind of device (drone, robot_arm, smart_light, etc.)
    - capabilities: what commands it accepts
    - get_telemetry(): current state/sensor readings
    - execute_command(): handle incoming commands

    The OMNIX server uses this interface to:
    1. Discover what the device can do
    2. Auto-generate appropriate UI controls
    3. Send commands and receive telemetry
    """

    def __init__(self, name: str, device_type: str):
        self.id = str(uuid.uuid4())[:8]
        self.name = name
        self.device_type = device_type
        self.connected = True
        self.created_at = time.time()
        self._capabilities: list[DeviceCapability] = []
        self._telemetry_history: list[DeviceTelemetry] = []
        self._event_log: list[dict] = []

    def register_capability(self, capability: DeviceCapability):
        """Register a command this device supports."""
        self._capabilities.append(capability)

    def get_capabilities(self) -> list[dict]:
        """Return all capabilities as dicts (for JSON serialization)."""
        return [asdict(c) for c in self._capabilities]

    def get_telemetry(self) -> dict:
        """Override in subclass — return current sensor/state data."""
        return {}

    def execute_command(self, command: str, params: dict = None) -> dict:
        """
        Override in subclass — handle a command from the OMNIX app.

        Returns: {"success": bool, "message": str, "data": any}
        """
        return {"success": False, "message": f"Unknown command: {command}"}

    def get_info(self) -> dict:
        """Full device info for the OMNIX dashboard."""
        return {
            "id": self.id,
            "name": self.name,
            "device_type": self.device_type,
            "connected": self.connected,
            "capabilities": self.get_capabilities(),
            "telemetry": self.get_telemetry(),
            "uptime": round(time.time() - self.created_at, 1),
        }

    def log_event(self, event_type: str, details: str):
        """Log an event for debugging/history."""
        entry = {
            "timestamp": time.time(),
            "type": event_type,
            "details": details,
        }
        self._event_log.append(entry)
        # Keep last 100 events
        if len(self._event_log) > 100:
            self._event_log = self._event_log[-100:]

    def get_event_log(self) -> list[dict]:
        return self._event_log[-20:]  # Last 20 events
