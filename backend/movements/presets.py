"""
OMNIX Movement Presets Engine

High-level movements (walk, fly, patrol, scan, etc.) are composed
of smaller atomic sub-movements that the device actually executes.

Each preset is a sequence of timed steps. When played, the server
sends each step to the device at the right time, updating telemetry
in real-time so the 3D viewer can show the motion.

Movement presets are device-type-aware: a drone gets "fly_circle",
a robot arm gets "pick_and_place", etc.
"""

import time
import math
import copy
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class MovementStep:
    """A single atomic action inside a movement preset."""
    command: str                    # The device command to execute
    params: dict = field(default_factory=dict)
    delay_ms: int = 0              # Wait this long BEFORE executing
    duration_ms: int = 500         # How long this step takes to complete
    label: str = ""                # Human-readable description


@dataclass
class MovementPreset:
    """A named, reusable sequence of movement steps."""
    name: str                       # e.g., "fly_circle"
    display_name: str               # e.g., "Fly in Circle"
    description: str
    device_type: str                # Which device type this applies to
    category: str                   # walk, fly, manipulate, patrol, etc.
    steps: list = field(default_factory=list)
    loop: bool = False              # Whether to repeat continuously
    estimated_duration_ms: int = 0  # Total time for one cycle
    icon: str = ""                  # Emoji icon for UI

    def to_dict(self):
        d = asdict(self)
        return d


# ─────────────────────────────────────────────────
#  DRONE MOVEMENT PRESETS
# ─────────────────────────────────────────────────

def _drone_fly_circle(radius=5, segments=12, altitude=10):
    """Fly in a circle at a given altitude."""
    steps = [
        MovementStep("takeoff", {"altitude": altitude}, delay_ms=0, duration_ms=1500, label="Take off"),
    ]
    angle_step = 360 / segments
    for i in range(segments):
        angle = math.radians(i * angle_step)
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        steps.append(MovementStep(
            "move", {"direction": "forward", "distance": 2 * radius * math.sin(math.radians(angle_step / 2))},
            delay_ms=100, duration_ms=600,
            label=f"Arc segment {i+1}/{segments}"
        ))
        steps.append(MovementStep(
            "rotate", {"degrees": angle_step},
            delay_ms=0, duration_ms=300,
            label=f"Turn {angle_step:.0f} deg"
        ))
    steps.append(MovementStep("hover", {}, delay_ms=200, duration_ms=500, label="Hover"))
    steps.append(MovementStep("land", {}, delay_ms=500, duration_ms=1500, label="Land"))
    return steps


def _drone_patrol_square(side=8, altitude=10):
    """Fly a square patrol pattern."""
    steps = [
        MovementStep("takeoff", {"altitude": altitude}, duration_ms=1500, label="Take off"),
    ]
    directions = ["forward", "right", "backward", "left"]
    for i, d in enumerate(directions):
        steps.append(MovementStep(
            "move", {"direction": d, "distance": side},
            delay_ms=200, duration_ms=1000,
            label=f"Patrol leg {i+1}: {d} {side}m"
        ))
        steps.append(MovementStep(
            "rotate", {"degrees": 90},
            delay_ms=100, duration_ms=400,
            label="Turn 90 deg"
        ))
    steps.append(MovementStep("hover", {}, delay_ms=200, duration_ms=500, label="Hover at start"))
    steps.append(MovementStep("land", {}, delay_ms=300, duration_ms=1500, label="Land"))
    return steps


def _drone_survey_scan(width=10, passes=4, altitude=15):
    """Lawn-mower survey pattern for aerial scanning."""
    steps = [
        MovementStep("takeoff", {"altitude": altitude}, duration_ms=1500, label="Take off to survey altitude"),
    ]
    spacing = width / passes
    for i in range(passes):
        direction = "forward" if i % 2 == 0 else "backward"
        steps.append(MovementStep(
            "move", {"direction": direction, "distance": width},
            delay_ms=100, duration_ms=1200,
            label=f"Scan pass {i+1}: {direction}"
        ))
        steps.append(MovementStep(
            "take_photo", {},
            delay_ms=0, duration_ms=300,
            label="Capture photo"
        ))
        if i < passes - 1:
            steps.append(MovementStep(
                "move", {"direction": "right", "distance": spacing},
                delay_ms=100, duration_ms=600,
                label="Move to next lane"
            ))
    steps.append(MovementStep("return_home", {}, delay_ms=500, duration_ms=2000, label="Return home"))
    steps.append(MovementStep("land", {}, delay_ms=200, duration_ms=1500, label="Land"))
    return steps


def _drone_rise_and_scan():
    """Rise to altitude, do a 360 scan, descend."""
    steps = [
        MovementStep("takeoff", {"altitude": 5}, duration_ms=1500, label="Take off"),
        MovementStep("move", {"direction": "up", "distance": 15}, delay_ms=200, duration_ms=1500, label="Rise to 20m"),
    ]
    for i in range(4):
        steps.append(MovementStep("rotate", {"degrees": 90}, delay_ms=300, duration_ms=600, label=f"Scan quadrant {i+1}"))
        steps.append(MovementStep("take_photo", {}, delay_ms=0, duration_ms=300, label="Capture"))
    steps.append(MovementStep("move", {"direction": "down", "distance": 15}, delay_ms=500, duration_ms=1500, label="Descend"))
    steps.append(MovementStep("land", {}, delay_ms=200, duration_ms=1500, label="Land"))
    return steps


# ─────────────────────────────────────────────────
#  ROBOT ARM MOVEMENT PRESETS
# ─────────────────────────────────────────────────

def _arm_pick_and_place():
    """Full pick-and-place cycle: reach, grab, move, release."""
    return [
        MovementStep("go_to_preset", {"preset": "home"}, duration_ms=800, label="Home position"),
        MovementStep("go_to_preset", {"preset": "pick_ready"}, delay_ms=200, duration_ms=1000, label="Reach to pick"),
        MovementStep("move_joint", {"joint": "elbow", "angle": -110}, delay_ms=200, duration_ms=600, label="Lower to object"),
        MovementStep("gripper", {"action": "close", "force": 70}, delay_ms=300, duration_ms=500, label="Grab object"),
        MovementStep("move_joint", {"joint": "elbow", "angle": -60}, delay_ms=200, duration_ms=600, label="Lift object"),
        MovementStep("move_joint", {"joint": "base", "angle": 90}, delay_ms=200, duration_ms=1000, label="Rotate to place zone"),
        MovementStep("go_to_preset", {"preset": "place_ready"}, delay_ms=200, duration_ms=800, label="Position to place"),
        MovementStep("move_joint", {"joint": "elbow", "angle": -80}, delay_ms=200, duration_ms=500, label="Lower object"),
        MovementStep("gripper", {"action": "open"}, delay_ms=300, duration_ms=400, label="Release object"),
        MovementStep("go_to_preset", {"preset": "home"}, delay_ms=500, duration_ms=1000, label="Return home"),
    ]


def _arm_wave():
    """Friendly wave gesture."""
    steps = [
        MovementStep("go_to_preset", {"preset": "wave"}, duration_ms=800, label="Raise arm"),
    ]
    for i in range(3):
        steps.append(MovementStep(
            "move_joint", {"joint": "wrist_yaw", "angle": 45},
            delay_ms=150, duration_ms=300, label="Wave right"
        ))
        steps.append(MovementStep(
            "move_joint", {"joint": "wrist_yaw", "angle": -45},
            delay_ms=150, duration_ms=300, label="Wave left"
        ))
    steps.append(MovementStep("go_to_preset", {"preset": "home"}, delay_ms=300, duration_ms=800, label="Return home"))
    return steps


def _arm_scan_workspace():
    """Scan the workspace by sweeping the arm across."""
    steps = [
        MovementStep("go_to_preset", {"preset": "home"}, duration_ms=800, label="Home position"),
    ]
    sweep_angles = [-120, -60, 0, 60, 120]
    for angle in sweep_angles:
        steps.append(MovementStep(
            "move_joint", {"joint": "base", "angle": angle},
            delay_ms=200, duration_ms=700, label=f"Sweep to {angle} deg"
        ))
        steps.append(MovementStep(
            "move_joint", {"joint": "shoulder", "angle": 30},
            delay_ms=100, duration_ms=400, label="Tilt forward"
        ))
        steps.append(MovementStep(
            "move_joint", {"joint": "shoulder", "angle": 0},
            delay_ms=100, duration_ms=400, label="Tilt back"
        ))
    steps.append(MovementStep("go_to_preset", {"preset": "home"}, delay_ms=300, duration_ms=800, label="Return home"))
    return steps


def _arm_sort_items():
    """Simulate sorting items from left to right."""
    steps = [MovementStep("go_to_preset", {"preset": "home"}, duration_ms=800, label="Home")]
    pick_angles = [-60, -20, 20]
    place_angles = [60, 100, 140]
    for i, (pick, place) in enumerate(zip(pick_angles, place_angles)):
        steps.extend([
            MovementStep("move_joint", {"joint": "base", "angle": pick}, delay_ms=200, duration_ms=700, label=f"Reach item {i+1}"),
            MovementStep("move_joint", {"joint": "shoulder", "angle": 50}, delay_ms=100, duration_ms=500, label="Lower"),
            MovementStep("gripper", {"action": "close", "force": 60}, delay_ms=200, duration_ms=400, label="Grab"),
            MovementStep("move_joint", {"joint": "shoulder", "angle": 10}, delay_ms=100, duration_ms=400, label="Lift"),
            MovementStep("move_joint", {"joint": "base", "angle": place}, delay_ms=100, duration_ms=800, label=f"Move to bin {i+1}"),
            MovementStep("move_joint", {"joint": "shoulder", "angle": 40}, delay_ms=100, duration_ms=400, label="Lower to bin"),
            MovementStep("gripper", {"action": "open"}, delay_ms=200, duration_ms=300, label="Release"),
        ])
    steps.append(MovementStep("go_to_preset", {"preset": "home"}, delay_ms=500, duration_ms=800, label="Done"))
    return steps


# ─────────────────────────────────────────────────
#  SMART LIGHT MOVEMENT PRESETS (light "movements" = effects)
# ─────────────────────────────────────────────────

def _light_sunrise_simulation():
    """Simulate a sunrise: warm dim to bright cool white."""
    steps = [
        MovementStep("toggle", {"state": "on"}, duration_ms=300, label="Turn on"),
        MovementStep("set_brightness", {"brightness": 5}, delay_ms=200, duration_ms=400, label="Very dim"),
        MovementStep("set_color", {"color": "FF4500"}, delay_ms=0, duration_ms=400, label="Deep orange"),
        MovementStep("set_brightness", {"brightness": 20}, delay_ms=800, duration_ms=600, label="Dim warm"),
        MovementStep("set_color", {"color": "FF8C00"}, delay_ms=0, duration_ms=500, label="Orange"),
        MovementStep("set_brightness", {"brightness": 50}, delay_ms=800, duration_ms=600, label="Medium"),
        MovementStep("set_color", {"color": "FFD700"}, delay_ms=0, duration_ms=500, label="Golden"),
        MovementStep("set_brightness", {"brightness": 80}, delay_ms=800, duration_ms=600, label="Bright warm"),
        MovementStep("set_color", {"color": "FFEFD5"}, delay_ms=0, duration_ms=500, label="Warm white"),
        MovementStep("set_brightness", {"brightness": 100}, delay_ms=800, duration_ms=600, label="Full brightness"),
        MovementStep("set_temperature", {"kelvin": 5500}, delay_ms=0, duration_ms=500, label="Daylight white"),
    ]
    return steps


def _light_alert_flash():
    """Red emergency-style flashing."""
    steps = [
        MovementStep("toggle", {"state": "on"}, duration_ms=200, label="On"),
    ]
    for i in range(6):
        steps.append(MovementStep("set_color", {"color": "FF0000"}, delay_ms=100, duration_ms=200, label="Red flash"))
        steps.append(MovementStep("set_brightness", {"brightness": 100}, delay_ms=0, duration_ms=150, label="Bright"))
        steps.append(MovementStep("set_brightness", {"brightness": 10}, delay_ms=200, duration_ms=150, label="Dim"))
    steps.append(MovementStep("set_brightness", {"brightness": 100}, delay_ms=200, duration_ms=200, label="Restore"))
    steps.append(MovementStep("set_color", {"color": "FFFFFF"}, delay_ms=0, duration_ms=300, label="White"))
    return steps


def _light_color_cycle():
    """Cycle through RGB colors smoothly."""
    colors = [
        ("FF0000", "Red"), ("FF7F00", "Orange"), ("FFFF00", "Yellow"),
        ("00FF00", "Green"), ("0000FF", "Blue"), ("8B00FF", "Violet"),
        ("FF00FF", "Magenta"), ("FFFFFF", "White"),
    ]
    steps = [MovementStep("toggle", {"state": "on"}, duration_ms=200, label="On")]
    for hex_c, name in colors:
        steps.append(MovementStep(
            "set_color", {"color": hex_c},
            delay_ms=400, duration_ms=500, label=name
        ))
    return steps


# ─────────────────────────────────────────────────
#  PRESET REGISTRY
# ─────────────────────────────────────────────────

def get_all_presets() -> dict:
    """Returns all presets grouped by device type."""
    return {
        "drone": [
            MovementPreset(
                name="fly_circle", display_name="Fly in Circle",
                description="Take off, fly a circular path, and land",
                device_type="drone", category="flight", icon="\U0001F504",
                steps=_drone_fly_circle(),
                estimated_duration_ms=15000,
            ),
            MovementPreset(
                name="patrol_square", display_name="Square Patrol",
                description="Fly a square perimeter patrol pattern",
                device_type="drone", category="patrol", icon="\U0001F6E1\uFE0F",
                steps=_drone_patrol_square(),
                estimated_duration_ms=14000,
            ),
            MovementPreset(
                name="survey_scan", display_name="Survey Scan",
                description="Lawn-mower pattern for aerial photography",
                device_type="drone", category="survey", icon="\U0001F4F7",
                steps=_drone_survey_scan(),
                estimated_duration_ms=18000,
            ),
            MovementPreset(
                name="rise_and_scan", display_name="Rise & 360 Scan",
                description="Rise high, do a 360-degree scan, descend",
                device_type="drone", category="survey", icon="\U0001F30D",
                steps=_drone_rise_and_scan(),
                estimated_duration_ms=12000,
            ),
        ],
        "robot_arm": [
            MovementPreset(
                name="pick_and_place", display_name="Pick & Place",
                description="Reach to object, grab it, move to target, release",
                device_type="robot_arm", category="manipulate", icon="\U0001F91D",
                steps=_arm_pick_and_place(),
                estimated_duration_ms=8000,
            ),
            MovementPreset(
                name="wave", display_name="Wave Hello",
                description="Friendly wave gesture",
                device_type="robot_arm", category="gesture", icon="\U0001F44B",
                steps=_arm_wave(),
                estimated_duration_ms=5000,
            ),
            MovementPreset(
                name="scan_workspace", display_name="Scan Workspace",
                description="Sweep across the full workspace range",
                device_type="robot_arm", category="survey", icon="\U0001F50D",
                steps=_arm_scan_workspace(),
                estimated_duration_ms=10000,
            ),
            MovementPreset(
                name="sort_items", display_name="Sort Items",
                description="Pick items from left side, sort to right bins",
                device_type="robot_arm", category="manipulate", icon="\U0001F4E6",
                steps=_arm_sort_items(),
                estimated_duration_ms=14000,
            ),
        ],
        "smart_light": [
            MovementPreset(
                name="sunrise", display_name="Sunrise Simulation",
                description="Gradual warm-to-bright sunrise effect",
                device_type="smart_light", category="ambient", icon="\U0001F305",
                steps=_light_sunrise_simulation(),
                estimated_duration_ms=8000,
            ),
            MovementPreset(
                name="alert_flash", display_name="Alert Flash",
                description="Red emergency flashing pattern",
                device_type="smart_light", category="alert", icon="\U0001F6A8",
                steps=_light_alert_flash(),
                estimated_duration_ms=4000,
            ),
            MovementPreset(
                name="color_cycle", display_name="Color Cycle",
                description="Smoothly cycle through the rainbow",
                device_type="smart_light", category="ambient", icon="\U0001F308",
                steps=_light_color_cycle(),
                estimated_duration_ms=5000,
            ),
        ],
    }


def get_presets_for_device(device_type: str) -> list:
    """Get all presets available for a given device type."""
    all_p = get_all_presets()
    return all_p.get(device_type, [])


def get_preset(device_type: str, preset_name: str) -> Optional[MovementPreset]:
    """Get a specific preset by device type and name."""
    for p in get_presets_for_device(device_type):
        if p.name == preset_name:
            return p
    return None
