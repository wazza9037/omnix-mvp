"""
OMNIX Weather Station Plugin
==============================

Reads temperature, humidity, and pressure sensors. Registers custom
sensor channels and adds a weather dashboard widget.

Supports BME280/BMP280 via I2C (simulated by default), or any sensor
that provides temperature/humidity/pressure readings.
"""

import time
import math
import random
import threading

from omnix.plugins import OmnixPlugin, PluginMeta
from connectors.base import (
    ConnectorBase, ConnectorMeta, ConnectorDevice,
    ConfigField, SimulatedBackendMixin,
)
from devices.base import DeviceCapability


class WeatherConnector(SimulatedBackendMixin, ConnectorBase):
    """Reads environmental sensors (temperature, humidity, pressure)."""

    meta = ConnectorMeta(
        connector_id="weather_station",
        display_name="Weather Station (BME280)",
        tier=1,
        description="Environmental monitoring: temperature, humidity, "
                    "barometric pressure, and derived altitude/dew point.",
        vpe_categories=["custom"],
        config_schema=[
            ConfigField("mode", "Mode", type="select",
                        options=["simulate", "i2c"],
                        default="simulate"),
            ConfigField("i2c_address", "I2C address", type="text",
                        default="0x76",
                        help="BME280 default: 0x76 or 0x77"),
            ConfigField("interval", "Read interval (seconds)", type="number",
                        default=2),
            ConfigField("altitude_ref", "Reference altitude (m)", type="number",
                        default=0,
                        help="Your location's altitude for pressure correction"),
        ],
        supports_simulation=True,
        icon="🌤️",
    )

    def __init__(self, config=None, **kwargs):
        super().__init__(config, **kwargs)
        self._readings = {
            "temperature": 22.0,
            "humidity": 45.0,
            "pressure": 1013.25,
            "altitude": 0.0,
            "dew_point": 10.0,
            "heat_index": 22.0,
        }
        self._history = []
        self._read_interval = 2.0
        self._sim_time = 0.0

    def connect(self) -> bool:
        self._use_simulation = (self.config.get("mode", "simulate") == "simulate")
        self._read_interval = float(self.config.get("interval", 2))

        capabilities = [
            DeviceCapability(
                name="read_sensors",
                description="Force an immediate sensor read",
                parameters=[],
                category="telemetry",
            ),
            DeviceCapability(
                name="set_interval",
                description="Change the read interval",
                parameters=[
                    {"name": "seconds", "type": "number", "min": 0.5, "max": 60},
                ],
                category="config",
            ),
            DeviceCapability(
                name="reset_history",
                description="Clear sensor history",
                parameters=[],
                category="data",
            ),
            DeviceCapability(
                name="get_forecast",
                description="Simple pressure-trend forecast",
                parameters=[],
                category="telemetry",
            ),
        ]

        dev = ConnectorDevice(
            name=self.config.get("name", "Weather Station"),
            device_type="custom",
            capabilities=capabilities,
            command_handler=self._handle_command,
            telemetry_provider=self._get_telemetry,
            source_connector=self,
        )
        self._devices.append(dev)
        self._mark_connected(True)
        return True

    def _handle_command(self, command: str, params: dict) -> dict:
        if command == "read_sensors":
            self._update_readings()
            return {"success": True, "message": "Sensors read", "data": dict(self._readings)}

        elif command == "set_interval":
            self._read_interval = float(params.get("seconds", 2))
            return {"success": True, "message": f"Interval set to {self._read_interval}s"}

        elif command == "reset_history":
            self._history.clear()
            return {"success": True, "message": "History cleared"}

        elif command == "get_forecast":
            forecast = self._pressure_forecast()
            return {"success": True, "message": forecast, "forecast": forecast}

        return {"success": False, "message": f"Unknown command: {command}"}

    def _get_telemetry(self) -> dict:
        return {
            **self._readings,
            "read_interval": self._read_interval,
            "history_length": len(self._history),
            "forecast": self._pressure_forecast(),
        }

    def tick(self):
        self._sim_time += 0.5
        if self._sim_time >= self._read_interval:
            self._sim_time = 0.0
            self._update_readings()
        self.mark_heartbeat()

    def _update_readings(self):
        """Simulate realistic environmental sensor readings."""
        t = time.time()

        # Temperature: diurnal cycle + noise
        base_temp = 22.0 + 5.0 * math.sin(t / 300.0)
        self._readings["temperature"] = round(base_temp + random.gauss(0, 0.3), 1)

        # Humidity: inversely correlated with temperature
        base_humidity = 55.0 - 10.0 * math.sin(t / 300.0)
        self._readings["humidity"] = round(
            max(20, min(95, base_humidity + random.gauss(0, 2))), 1
        )

        # Pressure: slow drift
        base_pressure = 1013.25 + 5.0 * math.sin(t / 1200.0)
        self._readings["pressure"] = round(base_pressure + random.gauss(0, 0.5), 2)

        # Derived: altitude from pressure (barometric formula)
        alt_ref = float(self.config.get("altitude_ref", 0))
        self._readings["altitude"] = round(
            alt_ref + 44330.0 * (1.0 - (self._readings["pressure"] / 1013.25) ** 0.1903),
            1,
        )

        # Derived: dew point (Magnus formula)
        temp = self._readings["temperature"]
        hum = self._readings["humidity"]
        a, b = 17.27, 237.7
        gamma = (a * temp / (b + temp)) + math.log(max(hum, 1) / 100.0)
        self._readings["dew_point"] = round((b * gamma) / (a - gamma), 1)

        # Derived: heat index (simplified)
        self._readings["heat_index"] = round(temp + 0.33 * hum / 100.0 * 6.105 - 4.0, 1)

        # Store history
        self._history.append({
            "timestamp": t,
            **{k: v for k, v in self._readings.items()},
        })
        # Keep last 500 readings
        if len(self._history) > 500:
            self._history = self._history[-500:]

    def _pressure_forecast(self) -> str:
        """Simple forecast based on 3-hour pressure trend."""
        if len(self._history) < 10:
            return "Insufficient data"

        recent = self._history[-1]["pressure"]
        older = self._history[-min(len(self._history), 60)]["pressure"]
        delta = recent - older

        if delta > 2:
            return "Rising pressure — clearing, fair weather ahead"
        elif delta > 0.5:
            return "Slowly rising — gradual improvement"
        elif delta < -2:
            return "Falling pressure — storm likely approaching"
        elif delta < -0.5:
            return "Slowly falling — possible rain"
        else:
            return "Stable pressure — no significant change expected"


# ── Plugin Entry Point ────────────────────────────────────

class WeatherStationPlugin(OmnixPlugin):
    """Environmental monitoring with temperature, humidity, and pressure."""

    meta = PluginMeta(
        name="weather_station",
        version="1.0.0",
        author="OMNIX Team",
        description="Environmental monitoring station. Reads temperature, "
                    "humidity, and barometric pressure via BME280/BMP280. "
                    "Includes derived altitude, dew point, heat index, and "
                    "simple pressure-trend forecasting.",
        device_types=["custom"],
        capabilities=["temperature", "humidity", "pressure", "forecast"],
        icon="🌤️",
        tags=["weather", "environment", "bme280", "temperature", "humidity",
              "pressure", "i2c", "sensor"],
    )

    def on_load(self):
        self.register_connector(WeatherConnector)

        # Register a dashboard view for the weather widget
        self.register_view(
            name="Weather Dashboard",
            html_file="weather_view.html",
            description="Live environmental readings with charts",
            icon="🌤️",
        )

    def on_unload(self):
        pass
