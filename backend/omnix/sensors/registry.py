"""
OMNIX Sensor Registry — tracks all sensor channels per device.

Each device can have multiple sensor channels (temperature, distance, IMU, etc.).
The registry stores current values and a rolling history window for charting.
"""

import time
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


# ── Sensor types ──────────────────────────────────────────

SENSOR_TYPES = [
    "temperature", "distance", "light", "humidity", "pressure",
    "imu_accel", "imu_gyro", "voltage", "current", "gas",
    "sound", "color", "encoder", "force", "gps", "compass",
    "barometer", "airspeed", "line_sensor", "custom",
]

# Default units per sensor type
DEFAULT_UNITS = {
    "temperature": "°C",
    "distance": "cm",
    "light": "lux",
    "humidity": "%",
    "pressure": "hPa",
    "imu_accel": "m/s²",
    "imu_gyro": "°/s",
    "voltage": "V",
    "current": "A",
    "gas": "ppm",
    "sound": "dB",
    "color": "RGB",
    "encoder": "ticks",
    "force": "N",
    "gps": "°",
    "compass": "°",
    "barometer": "m",
    "airspeed": "m/s",
    "line_sensor": "raw",
    "custom": "",
}


# ── Data classes ──────────────────────────────────────────

@dataclass
class SensorReading:
    """A single timestamped sensor reading."""
    timestamp: float
    value: float

    def to_dict(self):
        return {"t": round(self.timestamp, 3), "v": round(self.value, 4)}


@dataclass
class SensorChannel:
    """One sensor channel on a device."""
    id: str
    name: str
    sensor_type: str
    unit: str
    range_min: float
    range_max: float
    current_value: float = 0.0
    last_updated: float = 0.0
    history: deque = field(default_factory=lambda: deque(maxlen=500))
    status: str = "normal"  # normal | warning | alert
    device_id: str = ""

    def push(self, value: float, timestamp: Optional[float] = None):
        """Record a new sensor reading."""
        ts = timestamp or time.time()
        self.current_value = value
        self.last_updated = ts
        self.history.append(SensorReading(timestamp=ts, value=value))

    def get_history(self, last_n: Optional[int] = None) -> list:
        """Return history as list of dicts."""
        data = list(self.history)
        if last_n is not None:
            data = data[-last_n:]
        return [r.to_dict() for r in data]

    def get_sparkline(self, points: int = 30) -> list:
        """Return last N values for mini sparkline chart."""
        data = list(self.history)[-points:]
        return [round(r.value, 4) for r in data]

    def to_dict(self, include_history: bool = False) -> dict:
        result = {
            "id": self.id,
            "name": self.name,
            "sensor_type": self.sensor_type,
            "unit": self.unit,
            "range_min": self.range_min,
            "range_max": self.range_max,
            "current_value": round(self.current_value, 4),
            "last_updated": round(self.last_updated, 3),
            "status": self.status,
            "device_id": self.device_id,
            "sparkline": self.get_sparkline(),
        }
        if include_history:
            result["history"] = self.get_history()
        return result


# ── Registry ──────────────────────────────────────────────

class SensorRegistry:
    """Central registry of all sensor channels across all devices."""

    def __init__(self):
        self._lock = threading.Lock()
        # device_id → {sensor_id → SensorChannel}
        self._channels: dict[str, dict[str, SensorChannel]] = {}

    def register(self, device_id: str, sensor_id: str, name: str,
                 sensor_type: str, range_min: float, range_max: float,
                 unit: Optional[str] = None) -> SensorChannel:
        """Register a new sensor channel for a device."""
        if unit is None:
            unit = DEFAULT_UNITS.get(sensor_type, "")
        ch = SensorChannel(
            id=sensor_id,
            name=name,
            sensor_type=sensor_type,
            unit=unit,
            range_min=range_min,
            range_max=range_max,
            device_id=device_id,
        )
        with self._lock:
            if device_id not in self._channels:
                self._channels[device_id] = {}
            self._channels[device_id][sensor_id] = ch
        return ch

    def unregister_device(self, device_id: str):
        """Remove all sensor channels for a device."""
        with self._lock:
            self._channels.pop(device_id, None)

    def push_reading(self, device_id: str, sensor_id: str,
                     value: float, timestamp: Optional[float] = None):
        """Push a reading to a specific sensor channel."""
        with self._lock:
            dev_channels = self._channels.get(device_id, {})
            ch = dev_channels.get(sensor_id)
        if ch:
            ch.push(value, timestamp)

    def push_bulk(self, device_id: str, readings: dict[str, float],
                  timestamp: Optional[float] = None):
        """Push multiple readings at once: {sensor_id: value}."""
        ts = timestamp or time.time()
        with self._lock:
            dev_channels = self._channels.get(device_id, {})
        for sid, val in readings.items():
            ch = dev_channels.get(sid)
            if ch:
                ch.push(val, ts)

    def get_device_sensors(self, device_id: str) -> list[dict]:
        """Get all sensor channels for a device with current values."""
        with self._lock:
            dev_channels = self._channels.get(device_id, {})
        return [ch.to_dict() for ch in dev_channels.values()]

    def get_sensor(self, device_id: str, sensor_id: str) -> Optional[SensorChannel]:
        """Get a specific sensor channel."""
        with self._lock:
            dev_channels = self._channels.get(device_id, {})
            return dev_channels.get(sensor_id)

    def get_sensor_history(self, device_id: str, sensor_id: str,
                           last_n: Optional[int] = None) -> list[dict]:
        """Get time-series history for a sensor."""
        ch = self.get_sensor(device_id, sensor_id)
        if ch:
            return ch.get_history(last_n)
        return []

    def get_all_device_ids(self) -> list[str]:
        """Get all device IDs with registered sensors."""
        with self._lock:
            return list(self._channels.keys())

    def update_status(self, device_id: str, sensor_id: str, status: str):
        """Update a sensor's status (normal/warning/alert)."""
        ch = self.get_sensor(device_id, sensor_id)
        if ch:
            ch.status = status

    def export_csv(self, device_id: str, sensor_id: Optional[str] = None) -> str:
        """Export sensor data as CSV string."""
        lines = ["timestamp,sensor_id,sensor_name,value,unit"]
        with self._lock:
            dev_channels = self._channels.get(device_id, {})
        channels = dev_channels.values()
        if sensor_id:
            ch = dev_channels.get(sensor_id)
            channels = [ch] if ch else []
        for ch in channels:
            for reading in ch.history:
                lines.append(
                    f"{reading.timestamp:.3f},{ch.id},{ch.name},"
                    f"{reading.value:.4f},{ch.unit}"
                )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Full registry snapshot."""
        with self._lock:
            return {
                did: {sid: ch.to_dict() for sid, ch in channels.items()}
                for did, channels in self._channels.items()
            }
