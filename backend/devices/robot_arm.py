"""
OMNIX Simulated Robot Arm Device

Simulates a 6-DOF robotic arm with:
- Joint angle control (6 joints)
- Gripper open/close
- Preset positions (home, pick, place)
- Speed control
- Safety limits and collision detection (simulated)
"""

import time
import random
import math
from .base import OmnixDevice, DeviceCapability


class SimulatedRobotArm(OmnixDevice):
    def __init__(self, name: str = "OMNIX Arm R1"):
        super().__init__(name=name, device_type="robot_arm")

        # Joint angles in degrees (6-DOF arm)
        self.joints = {
            "base": 0.0,       # -180 to 180
            "shoulder": 0.0,   # -90 to 90
            "elbow": 0.0,      # -135 to 135
            "wrist_pitch": 0.0, # -90 to 90
            "wrist_roll": 0.0,  # -180 to 180
            "wrist_yaw": 0.0,   # -90 to 90
        }
        self.joint_limits = {
            "base": (-180, 180),
            "shoulder": (-90, 90),
            "elbow": (-135, 135),
            "wrist_pitch": (-90, 90),
            "wrist_roll": (-180, 180),
            "wrist_yaw": (-90, 90),
        }

        self.gripper_open = True
        self.gripper_force = 0.0       # 0-100 (percentage of max grip)
        self.speed = 50                # 1-100 (% of max speed)
        self.is_moving = False
        self.holding_object = False
        self.temperature = 25.0        # Motor temperature (C)
        self.power_consumption = 0.0   # Watts
        self.cycle_count = 0
        self.error_state = None
        self.last_update = time.time()

        self._register_capabilities()

    def _register_capabilities(self):
        self.register_capability(DeviceCapability(
            name="move_joint",
            description="Move a specific joint to an angle",
            parameters={
                "joint": {"type": "select", "options": list(self.joints.keys())},
                "angle": {"type": "number", "min": -180, "max": 180, "default": 0, "unit": "degrees"}
            },
            category="movement"
        ))
        self.register_capability(DeviceCapability(
            name="move_all_joints",
            description="Move all joints simultaneously",
            parameters={
                "base": {"type": "number", "min": -180, "max": 180, "default": 0},
                "shoulder": {"type": "number", "min": -90, "max": 90, "default": 0},
                "elbow": {"type": "number", "min": -135, "max": 135, "default": 0},
                "wrist_pitch": {"type": "number", "min": -90, "max": 90, "default": 0},
                "wrist_roll": {"type": "number", "min": -180, "max": 180, "default": 0},
                "wrist_yaw": {"type": "number", "min": -90, "max": 90, "default": 0},
            },
            category="movement"
        ))
        self.register_capability(DeviceCapability(
            name="gripper",
            description="Open or close the gripper",
            parameters={
                "action": {"type": "select", "options": ["open", "close"]},
                "force": {"type": "number", "min": 0, "max": 100, "default": 50, "unit": "%"}
            },
            category="gripper"
        ))
        self.register_capability(DeviceCapability(
            name="go_to_preset",
            description="Move to a preset position",
            parameters={
                "preset": {"type": "select", "options": ["home", "pick_ready", "place_ready", "rest", "wave"]}
            },
            category="presets"
        ))
        self.register_capability(DeviceCapability(
            name="set_speed",
            description="Set movement speed",
            parameters={"speed": {"type": "number", "min": 1, "max": 100, "default": 50, "unit": "%"}},
            category="settings"
        ))
        self.register_capability(DeviceCapability(
            name="emergency_stop",
            description="Immediately stop all movement",
            parameters={},
            category="safety"
        ))

    def _get_preset(self, name: str) -> dict:
        presets = {
            "home": {"base": 0, "shoulder": 0, "elbow": 0, "wrist_pitch": 0, "wrist_roll": 0, "wrist_yaw": 0},
            "pick_ready": {"base": 0, "shoulder": 45, "elbow": -90, "wrist_pitch": -45, "wrist_roll": 0, "wrist_yaw": 0},
            "place_ready": {"base": 90, "shoulder": 30, "elbow": -60, "wrist_pitch": -30, "wrist_roll": 0, "wrist_yaw": 0},
            "rest": {"base": 0, "shoulder": -45, "elbow": 90, "wrist_pitch": 45, "wrist_roll": 0, "wrist_yaw": 0},
            "wave": {"base": 0, "shoulder": 60, "elbow": -30, "wrist_pitch": 0, "wrist_roll": 45, "wrist_yaw": 0},
        }
        return presets.get(name, presets["home"])

    def _update_physics(self):
        """Simulate temperature and power consumption."""
        now = time.time()
        elapsed = now - self.last_update
        self.last_update = now

        if self.is_moving:
            self.temperature = min(80, self.temperature + elapsed * 0.3)
            self.power_consumption = 120 + random.uniform(-10, 10)
        else:
            self.temperature = max(25, self.temperature - elapsed * 0.1)
            self.power_consumption = max(5, self.power_consumption - elapsed * 5)

        # Overheat protection
        if self.temperature > 75:
            self.error_state = "warning_overheat"
            self.log_event("safety", f"Temperature warning: {self.temperature:.1f}C")

    def get_telemetry(self) -> dict:
        self._update_physics()

        # Calculate end-effector position (simplified forward kinematics)
        total_reach = 0.8  # meters
        angle_sum = abs(self.joints["shoulder"]) + abs(self.joints["elbow"])
        reach = total_reach * math.cos(math.radians(angle_sum / 2))

        return {
            "joints": {k: round(v, 1) for k, v in self.joints.items()},
            "gripper_open": self.gripper_open,
            "gripper_force": round(self.gripper_force, 1),
            "holding_object": self.holding_object,
            "speed": self.speed,
            "is_moving": self.is_moving,
            "temperature": round(self.temperature, 1),
            "power_consumption": round(self.power_consumption, 1),
            "cycle_count": self.cycle_count,
            "error_state": self.error_state,
            "estimated_reach": round(reach, 3),
        }

    def execute_command(self, command: str, params: dict = None) -> dict:
        params = params or {}

        if command == "move_joint":
            joint = params.get("joint", "base")
            angle = params.get("angle", 0)

            if joint not in self.joints:
                return {"success": False, "message": f"Invalid joint: {joint}"}

            min_a, max_a = self.joint_limits[joint]
            angle = max(min_a, min(max_a, angle))
            self.joints[joint] = angle
            self.is_moving = True
            self.cycle_count += 1
            self.log_event("movement", f"Joint '{joint}' moved to {angle} deg")

            # Simulate movement completion
            self.is_moving = False
            return {"success": True, "message": f"Joint '{joint}' moved to {angle}\u00b0"}

        elif command == "move_all_joints":
            for joint_name in self.joints:
                if joint_name in params:
                    min_a, max_a = self.joint_limits[joint_name]
                    # Ensure angle is numeric before clamping
                    angle_value = params[joint_name]
                    if not isinstance(angle_value, (int, float)):
                        continue
                    self.joints[joint_name] = max(min_a, min(max_a, float(angle_value)))
            self.cycle_count += 1
            self.log_event("movement", "All joints repositioned")
            return {"success": True, "message": "All joints moved to target positions"}

        elif command == "gripper":
            action = params.get("action", "open")
            force = params.get("force", 50)

            if action == "close":
                self.gripper_open = False
                self.gripper_force = force
                # Simulate grabbing something with 60% probability
                if random.random() < 0.6:
                    self.holding_object = True
                self.log_event("gripper", f"Gripper closed (force: {force}%)")
                return {"success": True, "message": f"Gripper closed with {force}% force",
                        "data": {"holding_object": self.holding_object}}
            else:
                self.gripper_open = True
                self.gripper_force = 0
                self.holding_object = False
                self.log_event("gripper", "Gripper opened")
                return {"success": True, "message": "Gripper opened"}

        elif command == "go_to_preset":
            preset_name = params.get("preset", "home")
            preset = self._get_preset(preset_name)
            for joint, angle in preset.items():
                self.joints[joint] = angle
            self.cycle_count += 1
            self.log_event("preset", f"Moved to preset: {preset_name}")
            return {"success": True, "message": f"Moved to '{preset_name}' position"}

        elif command == "set_speed":
            self.speed = max(1, min(100, params.get("speed", 50)))
            self.log_event("settings", f"Speed set to {self.speed}%")
            return {"success": True, "message": f"Speed set to {self.speed}%"}

        elif command == "emergency_stop":
            self.is_moving = False
            self.error_state = None
            self.log_event("safety", "Emergency stop activated")
            return {"success": True, "message": "EMERGENCY STOP \u2014 all motion halted"}

        return {"success": False, "message": f"Unknown command: {command}"}
