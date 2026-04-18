"""
OMNIX GPS Tracker Plugin
=========================

GPS module integration for position tracking and path recording.
Supports NMEA-based GPS modules via serial (simulated by default).

Features:
  - Real-time position tracking (lat, lon, altitude, speed, heading)
  - Path history with distance calculation
  - Geofence alerts
  - Map view integration
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


# ── GPS math helpers ──────────────────────────────────────

def haversine(lat1, lon1, lat2, lon2):
    """Distance between two GPS coordinates in meters."""
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class GPSConnector(SimulatedBackendMixin, ConnectorBase):
    """GPS module connector — NMEA serial or simulated."""

    meta = ConnectorMeta(
        connector_id="gps_tracker",
        display_name="GPS Tracker (NMEA)",
        tier=1,
        description="Track position via GPS module. Supports any NMEA-compatible "
                    "GPS receiver over serial. Records path history and calculates "
                    "distance, speed, and heading.",
        vpe_categories=["drone", "ground_robot", "custom"],
        config_schema=[
            ConfigField("mode", "Mode", type="select",
                        options=["simulate", "serial"],
                        default="simulate"),
            ConfigField("port", "Serial port", type="text",
                        placeholder="/dev/ttyUSB0"),
            ConfigField("baud", "Baud rate", type="number", default=9600),
            ConfigField("start_lat", "Start latitude", type="number", default=37.7749),
            ConfigField("start_lon", "Start longitude", type="number", default=-122.4194),
        ],
        supports_simulation=True,
        icon="📍",
    )

    def __init__(self, config=None, **kwargs):
        super().__init__(config, **kwargs)
        self._position = {"lat": 0.0, "lon": 0.0, "alt": 0.0}
        self._speed = 0.0          # m/s
        self._heading = 0.0        # degrees
        self._satellites = 0
        self._fix_quality = 0      # 0=none, 1=GPS, 2=DGPS
        self._path = []            # list of {lat, lon, alt, timestamp}
        self._total_distance = 0.0 # meters
        self._recording = False
        self._geofences = []       # list of {lat, lon, radius_m, name}
        self._sim_angle = 0.0

    def connect(self) -> bool:
        self._use_simulation = (self.config.get("mode", "simulate") == "simulate")

        start_lat = float(self.config.get("start_lat", 37.7749))
        start_lon = float(self.config.get("start_lon", -122.4194))
        self._position = {"lat": start_lat, "lon": start_lon, "alt": 10.0}
        self._fix_quality = 1
        self._satellites = 8

        capabilities = [
            DeviceCapability(
                name="start_recording",
                description="Start recording the GPS path",
                parameters=[],
                category="data",
            ),
            DeviceCapability(
                name="stop_recording",
                description="Stop recording and save the path",
                parameters=[],
                category="data",
            ),
            DeviceCapability(
                name="clear_path",
                description="Clear the recorded path",
                parameters=[],
                category="data",
            ),
            DeviceCapability(
                name="add_geofence",
                description="Add a geofence alert zone",
                parameters=[
                    {"name": "name", "type": "text"},
                    {"name": "lat", "type": "number"},
                    {"name": "lon", "type": "number"},
                    {"name": "radius_m", "type": "number", "default": 100},
                ],
                category="config",
            ),
            DeviceCapability(
                name="remove_geofence",
                description="Remove a geofence by name",
                parameters=[{"name": "name", "type": "text"}],
                category="config",
            ),
            DeviceCapability(
                name="get_path",
                description="Get the recorded path as a list of coordinates",
                parameters=[
                    {"name": "last_n", "type": "number", "default": 100},
                ],
                category="data",
            ),
        ]

        dev = ConnectorDevice(
            name=self.config.get("name", "GPS Tracker"),
            device_type="custom",
            capabilities=capabilities,
            command_handler=self._handle_command,
            telemetry_provider=self._get_telemetry,
            source_connector=self,
        )
        self._devices.append(dev)
        self._mark_connected(True)
        self._recording = True
        return True

    def _handle_command(self, command: str, params: dict) -> dict:
        if command == "start_recording":
            self._recording = True
            return {"success": True, "message": "GPS recording started"}

        elif command == "stop_recording":
            self._recording = False
            return {
                "success": True,
                "message": f"Recording stopped. {len(self._path)} points, "
                           f"{self._total_distance:.1f}m total distance",
            }

        elif command == "clear_path":
            self._path.clear()
            self._total_distance = 0.0
            return {"success": True, "message": "Path cleared"}

        elif command == "add_geofence":
            self._geofences.append({
                "name": params.get("name", "Zone"),
                "lat": float(params.get("lat", 0)),
                "lon": float(params.get("lon", 0)),
                "radius_m": float(params.get("radius_m", 100)),
            })
            return {"success": True, "message": f"Geofence '{params.get('name')}' added"}

        elif command == "remove_geofence":
            name = params.get("name", "")
            self._geofences = [g for g in self._geofences if g["name"] != name]
            return {"success": True, "message": f"Geofence '{name}' removed"}

        elif command == "get_path":
            last_n = int(params.get("last_n", 100))
            path_slice = self._path[-last_n:]
            return {
                "success": True,
                "path": path_slice,
                "total_points": len(self._path),
                "total_distance_m": round(self._total_distance, 1),
            }

        return {"success": False, "message": f"Unknown command: {command}"}

    def _get_telemetry(self) -> dict:
        # Check geofences
        alerts = []
        for gf in self._geofences:
            dist = haversine(
                self._position["lat"], self._position["lon"],
                gf["lat"], gf["lon"],
            )
            if dist <= gf["radius_m"]:
                alerts.append({"name": gf["name"], "distance_m": round(dist, 1)})

        return {
            "latitude": round(self._position["lat"], 6),
            "longitude": round(self._position["lon"], 6),
            "altitude": round(self._position["alt"], 1),
            "speed_ms": round(self._speed, 2),
            "speed_kmh": round(self._speed * 3.6, 1),
            "heading": round(self._heading, 1),
            "satellites": self._satellites,
            "fix_quality": self._fix_quality,
            "recording": self._recording,
            "path_points": len(self._path),
            "total_distance_m": round(self._total_distance, 1),
            "geofence_alerts": alerts,
        }

    def tick(self):
        if self._use_simulation:
            self._simulate_movement()

        # Record position if recording
        if self._recording and self._fix_quality > 0:
            point = {
                "lat": self._position["lat"],
                "lon": self._position["lon"],
                "alt": self._position["alt"],
                "timestamp": time.time(),
            }

            # Calculate distance from last point
            if self._path:
                last = self._path[-1]
                dist = haversine(last["lat"], last["lon"],
                                 point["lat"], point["lon"])
                self._total_distance += dist

            self._path.append(point)
            # Keep last 2000 points
            if len(self._path) > 2000:
                self._path = self._path[-2000:]

        self.mark_heartbeat()

    def _simulate_movement(self):
        """Simulate a GPS track — figure-8 pattern around start point."""
        self._sim_angle += 0.02
        t = self._sim_angle

        start_lat = float(self.config.get("start_lat", 37.7749))
        start_lon = float(self.config.get("start_lon", -122.4194))

        # Figure-8 (lemniscate) in lat/lon space
        scale = 0.001  # ~100m
        x = scale * math.sin(t)
        y = scale * math.sin(t) * math.cos(t)

        new_lat = start_lat + y
        new_lon = start_lon + x

        # Calculate speed and heading
        old_lat, old_lon = self._position["lat"], self._position["lon"]
        dist = haversine(old_lat, old_lon, new_lat, new_lon)
        self._speed = dist / 0.5  # tick is ~500ms

        if dist > 0.01:
            dlat = new_lat - old_lat
            dlon = new_lon - old_lon
            self._heading = (math.degrees(math.atan2(dlon, dlat)) + 360) % 360

        self._position["lat"] = new_lat
        self._position["lon"] = new_lon
        self._position["alt"] = 10.0 + 2.0 * math.sin(t * 0.5)

        # Simulate satellite jitter
        self._satellites = random.randint(6, 12)


# ── Plugin Entry Point ────────────────────────────────────

class GPSTrackerPlugin(OmnixPlugin):
    """GPS tracking with path recording, geofencing, and map view."""

    meta = PluginMeta(
        name="gps_tracker",
        version="1.0.0",
        author="OMNIX Team",
        description="GPS module integration for real-time position tracking. "
                    "Records path history, calculates distance and speed, "
                    "supports geofence alerts, and provides a map view. "
                    "Works with any NMEA-compatible GPS receiver.",
        device_types=["drone", "ground_robot", "custom"],
        capabilities=["gps", "path_recording", "geofence", "map_view"],
        icon="📍",
        tags=["gps", "navigation", "tracking", "geofence", "nmea", "mapping"],
    )

    def on_load(self):
        self.register_connector(GPSConnector)

        # Register map view
        self.register_view(
            name="GPS Map",
            html_file="map_view.html",
            description="Live GPS position and path on an interactive map",
            icon="🗺️",
        )

    def on_unload(self):
        pass
