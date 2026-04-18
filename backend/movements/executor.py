"""
OMNIX Movement Executor

Plays movement presets on real/simulated devices step-by-step,
and generates predicted 3D path data for the visualizer.

Two modes:
  1. predict() — generates the full 3D path WITHOUT executing
  2. execute() — actually runs each step on the device in real-time
"""

import time
import math
import copy
import threading
from dataclasses import dataclass, field, asdict
from typing import Optional
from .presets import MovementPreset, MovementStep, get_preset


@dataclass
class PathPoint:
    """A single point in 3D predicted/actual path."""
    x: float
    y: float
    z: float
    t_ms: int          # Time offset from start
    yaw: float = 0.0   # Rotation in degrees
    label: str = ""
    step_index: int = 0


@dataclass
class PredictedPath:
    """Full predicted movement path."""
    preset_name: str
    device_type: str
    points: list = field(default_factory=list)
    total_duration_ms: int = 0
    bounding_box: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "preset_name": self.preset_name,
            "device_type": self.device_type,
            "points": [asdict(p) for p in self.points],
            "total_duration_ms": self.total_duration_ms,
            "bounding_box": self.bounding_box,
        }


class MovementExecutor:
    """
    Runs movement presets on devices and generates 3D paths.
    """

    def __init__(self, devices_registry: dict):
        self.devices = devices_registry
        self._running = {}        # device_id -> threading.Event (stop signal)
        self._progress = {}       # device_id -> {current_step, total_steps, status, preset_name}

    def predict_path(self, device_type: str, preset_name: str,
                     start_position: dict = None) -> dict:
        """
        Generate the full predicted 3D path for a movement preset
        WITHOUT executing anything. Used for the 3D preview.
        """
        preset = get_preset(device_type, preset_name)
        if not preset:
            return {"error": f"Preset '{preset_name}' not found for {device_type}"}

        pos = start_position or {"x": 0, "y": 0, "z": 0}
        x, y, z = pos.get("x", 0), pos.get("y", 0), pos.get("z", 0)
        yaw = 0.0
        t_ms = 0
        points = []

        # Starting point
        points.append(PathPoint(x=x, y=y, z=z, t_ms=0, yaw=yaw,
                                label="Start", step_index=0))

        if device_type == "drone":
            points = self._predict_drone_path(preset.steps, x, y, z, yaw)
        elif device_type == "robot_arm":
            points = self._predict_arm_path(preset.steps)
        elif device_type == "smart_light":
            points = self._predict_light_path(preset.steps)
        else:
            # Generic: just timestamps
            for i, step in enumerate(preset.steps):
                t_ms += step.delay_ms + step.duration_ms
                points.append(PathPoint(x=x, y=y, z=z, t_ms=t_ms,
                                        label=step.label, step_index=i))

        # Calculate bounding box
        if points:
            xs = [p.x for p in points]
            ys = [p.y for p in points]
            zs = [p.z for p in points]
            bbox = {
                "min_x": min(xs), "max_x": max(xs),
                "min_y": min(ys), "max_y": max(ys),
                "min_z": min(zs), "max_z": max(zs),
            }
            total_t = max(p.t_ms for p in points)
        else:
            bbox = {"min_x": 0, "max_x": 0, "min_y": 0, "max_y": 0, "min_z": 0, "max_z": 0}
            total_t = 0

        path = PredictedPath(
            preset_name=preset_name,
            device_type=device_type,
            points=points,
            total_duration_ms=total_t,
            bounding_box=bbox,
        )
        return path.to_dict()

    def _predict_drone_path(self, steps, x=0, y=0, z=0, yaw=0):
        """Simulate a drone following movement commands to build a 3D path."""
        points = [PathPoint(x=x, y=y, z=z, t_ms=0, yaw=yaw, label="Start", step_index=0)]
        t_ms = 0
        speed = 1.0

        for i, step in enumerate(steps):
            t_ms += step.delay_ms

            if step.command == "takeoff":
                z = step.params.get("altitude", 10)
                t_ms += step.duration_ms
                points.append(PathPoint(x=x, y=y, z=z, t_ms=t_ms, yaw=yaw,
                                        label=step.label, step_index=i))

            elif step.command == "land":
                z = 0
                t_ms += step.duration_ms
                points.append(PathPoint(x=x, y=y, z=z, t_ms=t_ms, yaw=yaw,
                                        label=step.label, step_index=i))

            elif step.command == "move":
                d = step.params.get("direction", "forward")
                dist = step.params.get("distance", 2) * speed
                yaw_rad = math.radians(yaw)

                if d == "forward":
                    x += dist * math.sin(yaw_rad)
                    y += dist * math.cos(yaw_rad)
                elif d == "backward":
                    x -= dist * math.sin(yaw_rad)
                    y -= dist * math.cos(yaw_rad)
                elif d == "left":
                    x -= dist * math.cos(yaw_rad)
                    y += dist * math.sin(yaw_rad)
                elif d == "right":
                    x += dist * math.cos(yaw_rad)
                    y -= dist * math.sin(yaw_rad)
                elif d == "up":
                    z += dist
                elif d == "down":
                    z = max(0, z - dist)

                t_ms += step.duration_ms
                points.append(PathPoint(x=round(x, 2), y=round(y, 2), z=round(z, 2),
                                        t_ms=t_ms, yaw=yaw, label=step.label, step_index=i))

            elif step.command == "rotate":
                yaw = (yaw + step.params.get("degrees", 0)) % 360
                t_ms += step.duration_ms
                points.append(PathPoint(x=round(x, 2), y=round(y, 2), z=round(z, 2),
                                        t_ms=t_ms, yaw=yaw, label=step.label, step_index=i))

            elif step.command == "return_home":
                x, y, z = 0, 0, 10
                t_ms += step.duration_ms
                points.append(PathPoint(x=0, y=0, z=10, t_ms=t_ms, yaw=yaw,
                                        label=step.label, step_index=i))

            elif step.command == "hover":
                t_ms += step.duration_ms
                points.append(PathPoint(x=round(x, 2), y=round(y, 2), z=round(z, 2),
                                        t_ms=t_ms, yaw=yaw, label=step.label, step_index=i))

            elif step.command == "set_speed":
                speed = step.params.get("speed", 1.0)
                t_ms += step.duration_ms

            else:
                # Photo, etc. — stay in place
                t_ms += step.duration_ms
                points.append(PathPoint(x=round(x, 2), y=round(y, 2), z=round(z, 2),
                                        t_ms=t_ms, yaw=yaw, label=step.label, step_index=i))

        return points

    def _predict_arm_path(self, steps):
        """
        Simulate robot arm movement as end-effector positions.
        Uses simplified forward kinematics (2-link planar arm).
        """
        # Arm link lengths (meters)
        L1, L2 = 0.4, 0.35
        joints = {"base": 0, "shoulder": 0, "elbow": 0,
                  "wrist_pitch": 0, "wrist_roll": 0, "wrist_yaw": 0}
        presets = {
            "home":       {"base": 0, "shoulder": 0, "elbow": 0, "wrist_pitch": 0, "wrist_roll": 0, "wrist_yaw": 0},
            "pick_ready": {"base": 0, "shoulder": 45, "elbow": -90, "wrist_pitch": -45, "wrist_roll": 0, "wrist_yaw": 0},
            "place_ready":{"base": 90, "shoulder": 30, "elbow": -60, "wrist_pitch": -30, "wrist_roll": 0, "wrist_yaw": 0},
            "rest":       {"base": 0, "shoulder": -45, "elbow": 90, "wrist_pitch": 45, "wrist_roll": 0, "wrist_yaw": 0},
            "wave":       {"base": 0, "shoulder": 60, "elbow": -30, "wrist_pitch": 0, "wrist_roll": 45, "wrist_yaw": 0},
        }

        def fk(j):
            """Forward kinematics: joint angles → end effector xyz."""
            base_rad = math.radians(j["base"])
            sh_rad = math.radians(j["shoulder"])
            el_rad = math.radians(j["elbow"])
            # Shoulder + elbow form a 2-link arm in the vertical plane
            r = L1 * math.cos(sh_rad) + L2 * math.cos(sh_rad + el_rad)
            z = L1 * math.sin(sh_rad) + L2 * math.sin(sh_rad + el_rad)
            # Base rotation swings the arm in the XY plane
            x = r * math.cos(base_rad)
            y = r * math.sin(base_rad)
            return round(x, 3), round(y, 3), round(z + 0.3, 3)  # +0.3 for base height

        points = []
        t_ms = 0
        x, y, z = fk(joints)
        points.append(PathPoint(x=x, y=y, z=z, t_ms=0, label="Start", step_index=0))

        for i, step in enumerate(steps):
            t_ms += step.delay_ms

            if step.command == "go_to_preset":
                preset_name = step.params.get("preset", "home")
                if preset_name in presets:
                    joints = dict(presets[preset_name])
            elif step.command == "move_joint":
                jname = step.params.get("joint", "base")
                angle = step.params.get("angle", 0)
                if jname in joints:
                    joints[jname] = angle
            elif step.command == "move_all_joints":
                for jname in joints:
                    if jname in step.params:
                        joints[jname] = step.params[jname]

            t_ms += step.duration_ms
            x, y, z = fk(joints)
            points.append(PathPoint(x=x, y=y, z=z, t_ms=t_ms,
                                    label=step.label, step_index=i))

        return points

    def _predict_light_path(self, steps):
        """
        For lights, the 'path' is a color/brightness timeline.
        We encode brightness as Z and color-hue as rotation around a circle.
        """
        points = []
        t_ms = 0
        brightness = 0
        color = "FFFFFF"

        for i, step in enumerate(steps):
            t_ms += step.delay_ms + step.duration_ms

            if step.command == "set_brightness":
                brightness = step.params.get("brightness", 100)
            elif step.command == "set_color":
                color = step.params.get("color", "FFFFFF")
            elif step.command == "toggle":
                if step.params.get("state") == "on":
                    brightness = max(brightness, 50)
                else:
                    brightness = 0

            # Map color to a position on a color wheel (x, y)
            r_val = int(color[0:2], 16) / 255 if len(color) >= 6 else 1
            g_val = int(color[2:4], 16) / 255 if len(color) >= 6 else 1
            b_val = int(color[4:6], 16) / 255 if len(color) >= 6 else 1

            # Simple hue calculation
            hue = math.atan2(g_val - b_val, r_val - 0.5 * (g_val + b_val))
            radius = 2  # Fixed radius for color wheel viz
            x = round(radius * math.cos(hue), 3)
            y = round(radius * math.sin(hue), 3)
            z = round(brightness / 100 * 3, 3)  # Height = brightness

            points.append(PathPoint(
                x=x, y=y, z=z, t_ms=t_ms, yaw=math.degrees(hue),
                label=step.label, step_index=i
            ))

        return points

    # ─── Live Execution ───

    def execute_preset(self, device_id: str, preset_name: str,
                       callback=None) -> dict:
        """
        Execute a movement preset on a device in real-time.
        Runs in a background thread. Returns immediately with execution ID.

        callback(device_id, step_index, total_steps, step_label, telemetry)
            called after each step completes.
        """
        if device_id not in self.devices:
            return {"error": "Device not found"}

        device = self.devices[device_id]
        preset = get_preset(device.device_type, preset_name)
        if not preset:
            return {"error": f"Preset '{preset_name}' not found for {device.device_type}"}

        # Stop any current execution on this device
        if device_id in self._running:
            self._running[device_id].set()
            time.sleep(0.1)

        stop_event = threading.Event()
        self._running[device_id] = stop_event
        self._progress[device_id] = {
            "preset_name": preset_name,
            "current_step": 0,
            "total_steps": len(preset.steps),
            "status": "running",
            "current_label": "",
        }

        def run():
            try:
                for i, step in enumerate(preset.steps):
                    if stop_event.is_set():
                        self._progress[device_id]["status"] = "stopped"
                        return

                    # Wait the delay
                    if step.delay_ms > 0:
                        stop_event.wait(step.delay_ms / 1000)
                        if stop_event.is_set():
                            self._progress[device_id]["status"] = "stopped"
                            return

                    # Execute the command
                    result = device.execute_command(step.command, step.params)

                    # Update progress
                    self._progress[device_id].update({
                        "current_step": i + 1,
                        "current_label": step.label,
                        "last_result": result,
                    })

                    # Notify via callback
                    if callback:
                        try:
                            callback(device_id, i, len(preset.steps),
                                     step.label, device.get_telemetry())
                        except Exception:
                            pass

                    # Simulate step duration
                    if step.duration_ms > 0:
                        stop_event.wait(step.duration_ms / 1000)

                self._progress[device_id]["status"] = "completed"
            except Exception as e:
                self._progress[device_id]["status"] = f"error: {str(e)}"
            finally:
                if device_id in self._running:
                    del self._running[device_id]

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

        return {
            "success": True,
            "message": f"Executing '{preset.display_name}' on {device.name}",
            "total_steps": len(preset.steps),
            "estimated_duration_ms": preset.estimated_duration_ms,
        }

    def stop_execution(self, device_id: str) -> dict:
        """Stop any running preset on this device."""
        if device_id in self._running:
            self._running[device_id].set()
            return {"success": True, "message": "Execution stopped"}
        return {"success": False, "message": "No execution running"}

    def get_progress(self, device_id: str) -> dict:
        """Get current execution progress for a device."""
        if device_id in self._progress:
            return self._progress[device_id]
        return {"status": "idle"}
