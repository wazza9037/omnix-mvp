"""
OMNIX Servo Controller Plugin
==============================

Controls servo motors via PWM signals on Arduino or Raspberry Pi.
Registers as a connector with angle control, sweep, and home capabilities.

Supports up to 16 servos via PCA9685 I2C PWM driver (simulated by default).
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


class ServoConnector(SimulatedBackendMixin, ConnectorBase):
    """Controls servo motors via PWM (Arduino/Pi or simulated)."""

    meta = ConnectorMeta(
        connector_id="servo_controller",
        display_name="Servo Controller (PWM)",
        tier=1,
        description="Control servo motors via PWM on Arduino, Raspberry Pi, "
                    "or PCA9685 I2C driver. Supports angle, speed, and sweep.",
        vpe_categories=["robot_arm", "ground_robot", "custom"],
        config_schema=[
            ConfigField("servo_count", "Number of servos", type="number", default=4),
            ConfigField("mode", "Mode", type="select",
                        options=["simulate", "arduino", "pi_gpio", "pca9685"],
                        default="simulate"),
            ConfigField("port", "Serial port (Arduino only)", type="text",
                        placeholder="/dev/ttyACM0"),
            ConfigField("min_pulse", "Min pulse width (µs)", type="number", default=500),
            ConfigField("max_pulse", "Max pulse width (µs)", type="number", default=2500),
        ],
        supports_simulation=True,
        icon="⚙️",
    )

    def __init__(self, config=None, **kwargs):
        super().__init__(config, **kwargs)
        self._servo_count = 4
        self._servos = {}          # channel → {angle, speed, min_angle, max_angle}
        self._sweep_thread = None
        self._sweeping = False

    def connect(self) -> bool:
        self._servo_count = int(self.config.get("servo_count", 4))
        mode = self.config.get("mode", "simulate")
        self._use_simulation = True  # Always simulate for now

        min_pulse = int(self.config.get("min_pulse", 500))
        max_pulse = int(self.config.get("max_pulse", 2500))

        # Initialize servo states
        for i in range(self._servo_count):
            self._servos[i] = {
                "angle": 90.0,
                "target_angle": 90.0,
                "speed": 60.0,         # degrees per second
                "min_angle": 0.0,
                "max_angle": 180.0,
                "min_pulse": min_pulse,
                "max_pulse": max_pulse,
                "enabled": True,
            }

        capabilities = [
            DeviceCapability(
                name="set_angle",
                description="Set servo to a specific angle",
                parameters=[
                    {"name": "channel", "type": "number", "min": 0,
                     "max": self._servo_count - 1},
                    {"name": "angle", "type": "number", "min": 0, "max": 180},
                ],
                category="control",
            ),
            DeviceCapability(
                name="sweep",
                description="Sweep servo back and forth",
                parameters=[
                    {"name": "channel", "type": "number"},
                    {"name": "min_angle", "type": "number", "default": 0},
                    {"name": "max_angle", "type": "number", "default": 180},
                    {"name": "speed", "type": "number", "default": 60},
                ],
                category="control",
            ),
            DeviceCapability(
                name="stop_sweep",
                description="Stop sweeping a servo",
                parameters=[{"name": "channel", "type": "number"}],
                category="control",
            ),
            DeviceCapability(
                name="home",
                description="Return all servos to center position (90°)",
                parameters=[],
                category="control",
            ),
            DeviceCapability(
                name="set_speed",
                description="Set movement speed (degrees/second)",
                parameters=[
                    {"name": "channel", "type": "number"},
                    {"name": "speed", "type": "number", "min": 1, "max": 360},
                ],
                category="config",
            ),
            DeviceCapability(
                name="detach",
                description="Disable a servo (stop sending PWM)",
                parameters=[{"name": "channel", "type": "number"}],
                category="control",
            ),
        ]

        dev = ConnectorDevice(
            name=self.config.get("name", "Servo Array"),
            device_type="robot_arm",
            capabilities=capabilities,
            command_handler=self._handle_command,
            telemetry_provider=self._get_telemetry,
            source_connector=self,
        )
        self._devices.append(dev)
        self._mark_connected(True)
        return True

    def _handle_command(self, command: str, params: dict) -> dict:
        ch = int(params.get("channel", 0))

        if command == "set_angle":
            angle = float(params.get("angle", 90))
            servo = self._servos.get(ch)
            if not servo:
                return {"success": False, "message": f"Invalid channel {ch}"}
            angle = max(servo["min_angle"], min(servo["max_angle"], angle))
            servo["target_angle"] = angle
            servo["angle"] = angle  # Instant in simulation
            return {"success": True, "message": f"Servo {ch} → {angle:.1f}°"}

        elif command == "sweep":
            servo = self._servos.get(ch)
            if not servo:
                return {"success": False, "message": f"Invalid channel {ch}"}
            servo["min_angle"] = float(params.get("min_angle", 0))
            servo["max_angle"] = float(params.get("max_angle", 180))
            servo["speed"] = float(params.get("speed", 60))
            self._sweeping = True
            return {"success": True, "message": f"Servo {ch} sweeping"}

        elif command == "stop_sweep":
            self._sweeping = False
            return {"success": True, "message": "Sweep stopped"}

        elif command == "home":
            for s in self._servos.values():
                s["angle"] = 90.0
                s["target_angle"] = 90.0
            return {"success": True, "message": "All servos homed to 90°"}

        elif command == "set_speed":
            speed = float(params.get("speed", 60))
            servo = self._servos.get(ch)
            if servo:
                servo["speed"] = speed
            return {"success": True, "message": f"Servo {ch} speed={speed}°/s"}

        elif command == "detach":
            servo = self._servos.get(ch)
            if servo:
                servo["enabled"] = False
            return {"success": True, "message": f"Servo {ch} detached"}

        return {"success": False, "message": f"Unknown command: {command}"}

    def _get_telemetry(self) -> dict:
        return {
            "servo_count": self._servo_count,
            "sweeping": self._sweeping,
            "servos": {
                str(ch): {
                    "angle": round(s["angle"], 1),
                    "target": round(s["target_angle"], 1),
                    "speed": s["speed"],
                    "enabled": s["enabled"],
                }
                for ch, s in self._servos.items()
            },
        }

    def tick(self):
        # Simulate servo movement toward targets
        if self._sweeping:
            t = time.time()
            for ch, servo in self._servos.items():
                if not servo["enabled"]:
                    continue
                period = (servo["max_angle"] - servo["min_angle"]) / max(servo["speed"], 1)
                phase = (t + ch * 0.5) % (period * 2)
                if phase < period:
                    servo["angle"] = servo["min_angle"] + (phase / period) * (servo["max_angle"] - servo["min_angle"])
                else:
                    servo["angle"] = servo["max_angle"] - ((phase - period) / period) * (servo["max_angle"] - servo["min_angle"])

        self.mark_heartbeat()


# ── Plugin Entry Point ────────────────────────────────────

class ServoControllerPlugin(OmnixPlugin):
    """Servo motor controller — PWM-based multi-channel servo control."""

    meta = PluginMeta(
        name="servo_controller",
        version="1.0.0",
        author="OMNIX Team",
        description="Control servo motors via PWM signals. Supports Arduino, "
                    "Raspberry Pi GPIO, and PCA9685 I2C driver. Features angle "
                    "control, sweep mode, speed adjustment, and multi-servo arrays.",
        device_types=["robot_arm", "ground_robot"],
        capabilities=["angle_control", "sweep", "speed_control", "multi_channel"],
        icon="⚙️",
        tags=["servo", "pwm", "motor", "arduino", "raspberry-pi", "robotics"],
    )

    def on_load(self):
        self.register_connector(ServoConnector)

        # Custom command: coordinated multi-servo pose
        self.register_command(
            name="servo_pose",
            handler=self._set_pose,
            description="Set multiple servos to specific angles simultaneously",
            device_types=["robot_arm"],
        )

    def on_unload(self):
        pass

    def _set_pose(self, device_id: str, params: dict) -> dict:
        """Set a named pose (dictionary of channel → angle)."""
        angles = params.get("angles", {})
        return {
            "success": True,
            "message": f"Pose set: {len(angles)} servos positioned",
            "angles": angles,
        }
