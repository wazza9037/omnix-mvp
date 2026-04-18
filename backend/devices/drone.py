"""
OMNIX Simulated Drone Device

Simulates a quadcopter drone with:
- Takeoff / land / hover
- 3D movement (forward, back, left, right, up, down)
- Rotation (yaw)
- Battery drain over time
- GPS position tracking
- Camera (simulated photo capture)
"""

import time
import random
import math
from .base import OmnixDevice, DeviceCapability


class SimulatedDrone(OmnixDevice):
    def __init__(self, name: str = "OMNIX Drone Alpha"):
        super().__init__(name=name, device_type="drone")

        # State
        self.is_flying = False
        self.position = {"x": 0.0, "y": 0.0, "z": 0.0}  # meters
        self.velocity = {"x": 0.0, "y": 0.0, "z": 0.0}   # m/s
        self.rotation = {"yaw": 0.0, "pitch": 0.0, "roll": 0.0}  # degrees
        self.battery = 100.0          # percentage
        self.speed_setting = 1.0      # speed multiplier
        self.gps = {"lat": 37.7749, "lng": -122.4194}  # San Francisco default
        self.camera_mode = "photo"
        self.photos_taken = 0
        self.motor_rpm = [0, 0, 0, 0]
        self.last_update = time.time()

        # Register all capabilities
        self._register_capabilities()

    def _register_capabilities(self):
        self.register_capability(DeviceCapability(
            name="takeoff",
            description="Launch the drone to a specified altitude",
            parameters={"altitude": {"type": "number", "min": 1, "max": 120, "default": 10, "unit": "meters"}},
            category="flight"
        ))
        self.register_capability(DeviceCapability(
            name="land",
            description="Safely land the drone at current position",
            parameters={},
            category="flight"
        ))
        self.register_capability(DeviceCapability(
            name="move",
            description="Move the drone in a direction",
            parameters={
                "direction": {"type": "select", "options": ["forward", "backward", "left", "right", "up", "down"]},
                "distance": {"type": "number", "min": 0.5, "max": 50, "default": 2, "unit": "meters"}
            },
            category="movement"
        ))
        self.register_capability(DeviceCapability(
            name="rotate",
            description="Rotate the drone (yaw)",
            parameters={"degrees": {"type": "number", "min": -360, "max": 360, "default": 90}},
            category="movement"
        ))
        self.register_capability(DeviceCapability(
            name="set_speed",
            description="Set flight speed multiplier",
            parameters={"speed": {"type": "number", "min": 0.1, "max": 3.0, "default": 1.0}},
            category="settings"
        ))
        self.register_capability(DeviceCapability(
            name="take_photo",
            description="Capture a photo with the onboard camera",
            parameters={},
            category="camera"
        ))
        self.register_capability(DeviceCapability(
            name="return_home",
            description="Fly back to takeoff position and land",
            parameters={},
            category="flight"
        ))
        self.register_capability(DeviceCapability(
            name="hover",
            description="Hold current position",
            parameters={},
            category="flight"
        ))
        self.register_capability(DeviceCapability(
            name="emergency_stop",
            description="Immediately cut motors (use only in emergency)",
            parameters={},
            category="safety"
        ))

    def _drain_battery(self):
        """Simulate battery drain based on activity."""
        now = time.time()
        elapsed = now - self.last_update
        self.last_update = now

        if self.is_flying:
            # Flying drains ~0.5% per second (about 3 minutes of flight)
            drain = elapsed * 0.5
            # Higher altitude = more drain
            altitude_factor = 1 + (self.position["z"] / 100)
            self.battery = max(0, self.battery - drain * altitude_factor)
        else:
            # Idle drain is minimal
            self.battery = max(0, self.battery - elapsed * 0.01)

        # Auto-land if battery critical
        if self.battery < 5 and self.is_flying:
            self.is_flying = False
            self.position["z"] = 0
            self.motor_rpm = [0, 0, 0, 0]
            self.log_event("safety", "Emergency auto-land: battery critical")

    def _update_gps(self):
        """Update simulated GPS based on position."""
        # Rough conversion: 1 meter ~ 0.00001 degrees
        self.gps["lat"] = 37.7749 + self.position["y"] * 0.00001
        self.gps["lng"] = -122.4194 + self.position["x"] * 0.00001

    def _update_motors(self):
        """Simulate motor RPM based on state."""
        if self.is_flying:
            base_rpm = 5000 + self.position["z"] * 20
            self.motor_rpm = [
                int(base_rpm + random.uniform(-100, 100)),
                int(base_rpm + random.uniform(-100, 100)),
                int(base_rpm + random.uniform(-100, 100)),
                int(base_rpm + random.uniform(-100, 100)),
            ]
        else:
            self.motor_rpm = [0, 0, 0, 0]

    def get_telemetry(self) -> dict:
        self._drain_battery()
        self._update_gps()
        self._update_motors()

        return {
            "is_flying": self.is_flying,
            "position": {k: round(v, 2) for k, v in self.position.items()},
            "velocity": {k: round(v, 2) for k, v in self.velocity.items()},
            "rotation": {k: round(v, 1) for k, v in self.rotation.items()},
            "battery": round(self.battery, 1),
            "gps": {k: round(v, 6) for k, v in self.gps.items()},
            "altitude": round(self.position["z"], 2),
            "speed_setting": self.speed_setting,
            "motor_rpm": self.motor_rpm,
            "photos_taken": self.photos_taken,
            "signal_strength": max(20, 100 - int(math.sqrt(
                self.position["x"]**2 + self.position["y"]**2
            ) * 0.5)),
        }

    def execute_command(self, command: str, params: dict = None) -> dict:
        params = params or {}

        if self.battery <= 0 and command not in ["emergency_stop"]:
            return {"success": False, "message": "Battery depleted. Recharge required."}

        if command == "takeoff":
            if self.is_flying:
                return {"success": False, "message": "Already in flight"}
            altitude = params.get("altitude", 10)
            self.is_flying = True
            self.position["z"] = altitude
            self.velocity = {"x": 0, "y": 0, "z": 0}
            self.log_event("flight", f"Takeoff to {altitude}m")
            return {"success": True, "message": f"Taking off to {altitude}m altitude"}

        elif command == "land":
            if not self.is_flying:
                return {"success": False, "message": "Already on ground"}
            self.is_flying = False
            self.position["z"] = 0
            self.velocity = {"x": 0, "y": 0, "z": 0}
            self.motor_rpm = [0, 0, 0, 0]
            self.log_event("flight", "Landed safely")
            return {"success": True, "message": "Landing initiated"}

        elif command == "move":
            if not self.is_flying:
                return {"success": False, "message": "Must be flying to move"}
            direction = params.get("direction", "forward")
            distance = params.get("distance", 2) * self.speed_setting
            moves = {
                "forward": ("y", distance),
                "backward": ("y", -distance),
                "left": ("x", -distance),
                "right": ("x", distance),
                "up": ("z", distance),
                "down": ("z", max(-self.position["z"], -distance)),
            }
            if direction in moves:
                axis, delta = moves[direction]
                self.position[axis] += delta
                if self.position["z"] < 0:
                    self.position["z"] = 0
                self.log_event("movement", f"Moved {direction} by {abs(delta):.1f}m")
                return {"success": True, "message": f"Moving {direction} {abs(delta):.1f}m"}
            return {"success": False, "message": f"Invalid direction: {direction}"}

        elif command == "rotate":
            degrees = params.get("degrees", 90)
            self.rotation["yaw"] = (self.rotation["yaw"] + degrees) % 360
            self.log_event("movement", f"Rotated {degrees} degrees")
            return {"success": True, "message": f"Rotating {degrees} degrees"}

        elif command == "set_speed":
            speed = params.get("speed", 1.0)
            self.speed_setting = max(0.1, min(3.0, speed))
            self.log_event("settings", f"Speed set to {self.speed_setting}x")
            return {"success": True, "message": f"Speed set to {self.speed_setting}x"}

        elif command == "take_photo":
            self.photos_taken += 1
            self.log_event("camera", f"Photo #{self.photos_taken} captured at {self.position}")
            return {"success": True, "message": f"Photo #{self.photos_taken} captured",
                    "data": {"photo_id": self.photos_taken, "position": dict(self.position)}}

        elif command == "return_home":
            self.position = {"x": 0, "y": 0, "z": 10}
            self.log_event("flight", "Returning to home position")
            return {"success": True, "message": "Returning to home position"}

        elif command == "hover":
            self.velocity = {"x": 0, "y": 0, "z": 0}
            self.log_event("flight", "Hovering in place")
            return {"success": True, "message": "Hovering at current position"}

        elif command == "emergency_stop":
            self.is_flying = False
            self.position["z"] = 0
            self.velocity = {"x": 0, "y": 0, "z": 0}
            self.motor_rpm = [0, 0, 0, 0]
            self.log_event("safety", "EMERGENCY STOP activated")
            return {"success": True, "message": "EMERGENCY STOP — motors cut"}

        return {"success": False, "message": f"Unknown command: {command}"}
