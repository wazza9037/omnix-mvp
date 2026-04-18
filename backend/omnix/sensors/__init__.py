"""OMNIX Sensor Dashboard — registry, alerts, and simulation."""

from omnix.sensors.registry import SensorRegistry, SensorChannel, SensorReading
from omnix.sensors.alerts import AlertManager, AlertRule, Alert
from omnix.sensors.simulator import SensorSimulator

__all__ = [
    "SensorRegistry", "SensorChannel", "SensorReading",
    "AlertManager", "AlertRule", "Alert",
    "SensorSimulator",
]
