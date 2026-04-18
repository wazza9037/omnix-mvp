"""
Template library — 10 canonical starter robots.

Each entry is a full CustomBuild. Instantiating a template creates a
CustomRobotDevice from its parts, which lands in the main device
registry and gets its own workspace.

Templates are stored as factory functions (not singletons) so each
instantiation gets fresh Part instances with unique part_ids.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from custom_build.parts import Part
from custom_build.builder import CustomBuild


@dataclass(frozen=True)
class RobotTemplate:
    template_id: str
    display_name: str
    description: str
    device_type: str
    tagline: str               # short marketing-y blurb for the gallery card
    icon: str
    tags: list[str]
    color: str
    factory: Callable[[], CustomBuild]

    def instantiate(self) -> CustomBuild:
        return self.factory()

    def to_dict(self) -> dict:
        build = self.factory()
        return {
            "template_id": self.template_id,
            "display_name": self.display_name,
            "description": self.description,
            "device_type": self.device_type,
            "tagline": self.tagline,
            "icon": self.icon,
            "tags": list(self.tags),
            "color": self.color,
            "part_count": len(build.parts),
            "part_counts": build.part_counts(),
            "preview": build.to_mesh_params(),
            "capabilities_count": len(build.derive_capabilities()),
        }


# ─────────────────────────────────────────────────────────
#  Template factories
# ─────────────────────────────────────────────────────────

def _build_quadcopter() -> CustomBuild:
    parts: list[Part] = []
    parts.append(Part.new("chassis", name="Main frame", position=(0, 0.25, 0)))
    # Adjust frame proportions — a drone body is rectangular/tall
    parts[-1].geometry = {"w": 0.9, "h": 0.18, "d": 0.9}
    parts[-1].color = "#2e3a52"

    # 4 arms radiating out, 4 rotors at the ends
    for i, (ax, az) in enumerate([(0.6, 0.6), (-0.6, 0.6),
                                   (-0.6, -0.6), (0.6, -0.6)]):
        arm = Part.new("arm", name=f"Arm {i+1}", position=(ax * 0.55, 0.25, az * 0.55))
        arm.geometry = {"rt": 0.05, "rb": 0.05, "h": 0.85}
        # Lay the arm flat and rotate so it points outward
        arm.rotation = [0.0, math.atan2(az, ax), math.pi / 2]
        parts.append(arm)

        rotor = Part.new("rotor", name=f"Rotor {i+1}", position=(ax, 0.38, az))
        rotor.rotation = [math.pi / 2, 0, 0]
        parts.append(rotor)

    # Camera / gimbal on the front bottom
    cam = Part.new("camera", name="Gimbal camera", position=(0, 0.06, 0.35))
    cam.rotation = [math.pi / 2, 0, 0]
    parts.append(cam)

    # Landing gear as small vertical bars under the frame
    for x in (-0.35, 0.35):
        leg = Part.new("arm", name="Landing gear", position=(x, -0.05, 0))
        leg.geometry = {"rt": 0.02, "rb": 0.02, "h": 0.25}
        parts.append(leg)

    for i, p in enumerate(parts):
        p.order = i
    return CustomBuild(parts=parts)


def _build_6dof_arm() -> CustomBuild:
    parts: list[Part] = []
    # Base
    base = Part.new("chassis", name="Base plate", position=(0, 0.1, 0))
    base.geometry = {"w": 0.6, "h": 0.2, "d": 0.6}
    base.color = "#2a2f3a"
    parts.append(base)

    # 6 alternating joints + arm segments in a stack — representative UR5 kinematic
    segment_lengths = [0.45, 0.4, 0.35, 0.25, 0.2, 0.12]
    y = 0.25
    for i, seg_h in enumerate(segment_lengths):
        j = Part.new("joint", name=f"Joint J{i}", position=(0, y, 0))
        j.geometry = {"r": 0.11 - i * 0.008}
        j.color = "#f59e0b" if i % 2 == 0 else "#00b4d8"
        parts.append(j)

        a = Part.new("arm", name=f"Link L{i}", position=(0, y + seg_h / 2, 0))
        a.geometry = {"rt": 0.07 - i * 0.005, "rb": 0.07 - i * 0.005, "h": seg_h}
        parts.append(a)
        y += seg_h

    # End effector
    ee = Part.new("gripper", name="End effector", position=(0, y + 0.1, 0))
    ee.geometry = {"r": 0.09, "h": 0.2}
    parts.append(ee)

    for i, p in enumerate(parts):
        p.order = i
    return CustomBuild(parts=parts)


def _build_two_wheel_rover() -> CustomBuild:
    parts: list[Part] = []
    # Chassis
    ch = Part.new("chassis", name="Chassis", position=(0, 0.2, 0))
    ch.geometry = {"w": 0.8, "h": 0.25, "d": 0.6}
    ch.color = "#0f766e"
    parts.append(ch)

    # Two drive wheels + one caster
    for x in (-0.45, 0.45):
        w = Part.new("wheel", name=f"Drive wheel", position=(x, 0.15, 0))
        w.rotation = [0, 0, math.pi / 2]
        parts.append(w)
    cas = Part.new("wheel", name="Caster", position=(0, 0.08, -0.35))
    cas.geometry = {"rt": 0.1, "rb": 0.1, "h": 0.05}
    cas.rotation = [0, 0, math.pi / 2]
    parts.append(cas)

    # Sensor + camera on top
    sns = Part.new("sensor", name="IMU", position=(0, 0.38, -0.1))
    parts.append(sns)
    cam = Part.new("camera", name="RGB camera", position=(0, 0.42, 0.28))
    cam.rotation = [math.pi / 2, 0, 0]
    parts.append(cam)

    for i, p in enumerate(parts):
        p.order = i
    return CustomBuild(parts=parts)


def _build_humanoid() -> CustomBuild:
    parts: list[Part] = []
    # Torso
    torso = Part.new("chassis", name="Torso", position=(0, 1.1, 0))
    torso.geometry = {"w": 0.45, "h": 0.8, "d": 0.25}
    torso.color = "#6366f1"
    parts.append(torso)

    # Head
    head = Part.new("joint", name="Head", position=(0, 1.7, 0))
    head.geometry = {"r": 0.18}
    parts.append(head)

    # Eyes (cameras)
    for ex in (-0.07, 0.07):
        e = Part.new("camera", name="Eye", position=(ex, 1.72, 0.14))
        e.geometry = {"rt": 0.03, "rb": 0.03, "h": 0.05}
        e.rotation = [math.pi / 2, 0, 0]
        parts.append(e)

    # Shoulders + arms + grippers (hands)
    for side in (-1, 1):
        sh = Part.new("joint", name="Shoulder", position=(side * 0.28, 1.4, 0))
        sh.geometry = {"r": 0.1}
        parts.append(sh)
        upper = Part.new("arm", name="Upper arm", position=(side * 0.28, 1.1, 0))
        upper.geometry = {"rt": 0.06, "rb": 0.06, "h": 0.4}
        parts.append(upper)
        elb = Part.new("joint", name="Elbow", position=(side * 0.28, 0.85, 0))
        elb.geometry = {"r": 0.08}
        parts.append(elb)
        fore = Part.new("arm", name="Forearm", position=(side * 0.28, 0.6, 0))
        fore.geometry = {"rt": 0.05, "rb": 0.05, "h": 0.4}
        parts.append(fore)
        hand = Part.new("gripper", name="Hand", position=(side * 0.28, 0.35, 0))
        hand.geometry = {"r": 0.06, "h": 0.14}
        hand.rotation = [math.pi, 0, 0]
        parts.append(hand)

    # Legs
    for side in (-1, 1):
        hip = Part.new("joint", name="Hip", position=(side * 0.11, 0.7, 0))
        hip.geometry = {"r": 0.1}
        parts.append(hip)
        thigh = Part.new("leg", name="Thigh", position=(side * 0.11, 0.4, 0))
        thigh.geometry = {"w": 0.13, "h": 0.45, "d": 0.13}
        parts.append(thigh)
        knee = Part.new("joint", name="Knee", position=(side * 0.11, 0.2, 0))
        knee.geometry = {"r": 0.08}
        parts.append(knee)
        shin = Part.new("leg", name="Shin", position=(side * 0.11, -0.05, 0))
        shin.geometry = {"w": 0.11, "h": 0.4, "d": 0.11}
        parts.append(shin)

    for i, p in enumerate(parts):
        p.order = i
    return CustomBuild(parts=parts)


def _build_hexapod() -> CustomBuild:
    parts: list[Part] = []
    # Central body
    body = Part.new("chassis", name="Body", position=(0, 0.3, 0))
    body.geometry = {"w": 0.6, "h": 0.2, "d": 0.8}
    body.color = "#7c2d12"
    parts.append(body)
    # 6 legs in 3 pairs
    for row, z in enumerate((0.35, 0.0, -0.35)):
        for side in (-1, 1):
            hip = Part.new("joint", name=f"Hip{row}-{side}", position=(side * 0.35, 0.3, z))
            hip.geometry = {"r": 0.08}
            parts.append(hip)
            upper = Part.new("leg", name=f"Upper leg{row}-{side}",
                             position=(side * 0.55, 0.2, z))
            upper.geometry = {"w": 0.07, "h": 0.35, "d": 0.07}
            upper.rotation = [0, 0, side * math.radians(40)]
            parts.append(upper)
            lower = Part.new("leg", name=f"Lower leg{row}-{side}",
                             position=(side * 0.7, -0.05, z))
            lower.geometry = {"w": 0.06, "h": 0.35, "d": 0.06}
            parts.append(lower)
    # Head camera
    cam = Part.new("camera", name="Head camera", position=(0, 0.4, 0.45))
    cam.rotation = [math.pi / 2, 0, 0]
    parts.append(cam)

    for i, p in enumerate(parts):
        p.order = i
    return CustomBuild(parts=parts)


def _build_warehouse_agv() -> CustomBuild:
    parts: list[Part] = []
    # Flat, long chassis (pallet carrier profile)
    ch = Part.new("chassis", name="Load platform", position=(0, 0.25, 0))
    ch.geometry = {"w": 1.2, "h": 0.22, "d": 0.8}
    ch.color = "#f59e0b"
    parts.append(ch)
    # 4 wheels at the corners
    for (x, z) in ((-0.5, 0.3), (0.5, 0.3), (-0.5, -0.3), (0.5, -0.3)):
        w = Part.new("wheel", name="Wheel", position=(x, 0.12, z))
        w.geometry = {"rt": 0.16, "rb": 0.16, "h": 0.08}
        w.rotation = [0, 0, math.pi / 2]
        parts.append(w)
    # Lift tower sensor + camera
    sens1 = Part.new("sensor", name="Lidar", position=(-0.5, 0.45, 0))
    sens1.geometry = {"w": 0.12, "h": 0.1, "d": 0.12}
    parts.append(sens1)
    sens2 = Part.new("sensor", name="Safety laser", position=(0.5, 0.45, 0))
    sens2.geometry = {"w": 0.12, "h": 0.1, "d": 0.12}
    parts.append(sens2)
    cam = Part.new("camera", name="Tracking camera", position=(0, 0.45, 0.38))
    cam.rotation = [math.pi / 2, 0, 0]
    parts.append(cam)

    for i, p in enumerate(parts):
        p.order = i
    return CustomBuild(parts=parts)


def _build_fixed_wing() -> CustomBuild:
    parts: list[Part] = []
    # Fuselage
    body = Part.new("chassis", name="Fuselage", position=(0, 0.5, 0))
    body.geometry = {"w": 0.28, "h": 0.22, "d": 1.4}
    body.color = "#1e3a8a"
    parts.append(body)
    # Main wing
    wing = Part.new("wing", name="Main wing", position=(0, 0.6, 0))
    wing.geometry = {"w": 2.6, "h": 0.05, "d": 0.45}
    parts.append(wing)
    # Tail
    hstab = Part.new("wing", name="Horizontal stabilizer",
                     position=(0, 0.6, -0.65))
    hstab.geometry = {"w": 0.9, "h": 0.04, "d": 0.25}
    parts.append(hstab)
    vstab = Part.new("wing", name="Vertical stabilizer",
                     position=(0, 0.8, -0.65))
    vstab.geometry = {"w": 0.04, "h": 0.35, "d": 0.25}
    parts.append(vstab)
    # Pusher propeller
    rotor = Part.new("rotor", name="Propeller", position=(0, 0.5, 0.8))
    rotor.geometry = {"r": 0.28, "tube": 0.02}
    parts.append(rotor)
    # Camera
    cam = Part.new("camera", name="Nose camera", position=(0, 0.5, 0.7))
    cam.rotation = [math.pi / 2, 0, 0]
    parts.append(cam)

    for i, p in enumerate(parts):
        p.order = i
    return CustomBuild(parts=parts)


def _build_gripper() -> CustomBuild:
    parts: list[Part] = []
    # Mounting base
    base = Part.new("chassis", name="Mount", position=(0, 0.1, 0))
    base.geometry = {"w": 0.22, "h": 0.18, "d": 0.22}
    base.color = "#0f172a"
    parts.append(base)
    # Palm / joint
    palm = Part.new("joint", name="Wrist", position=(0, 0.3, 0))
    palm.geometry = {"r": 0.1}
    parts.append(palm)
    # Two finger cones facing inward
    for side in (-1, 1):
        f = Part.new("gripper", name=f"Finger {side}",
                     position=(side * 0.08, 0.55, 0))
        f.geometry = {"r": 0.05, "h": 0.35}
        f.rotation = [math.pi, 0, 0]
        parts.append(f)
    # Force sensor
    sns = Part.new("sensor", name="Force sensor", position=(0, 0.4, 0))
    sns.geometry = {"w": 0.08, "h": 0.06, "d": 0.08}
    parts.append(sns)

    for i, p in enumerate(parts):
        p.order = i
    return CustomBuild(parts=parts)


def _build_quadruped() -> CustomBuild:
    parts: list[Part] = []
    body = Part.new("chassis", name="Body", position=(0, 0.65, 0))
    body.geometry = {"w": 0.55, "h": 0.22, "d": 1.0}
    body.color = "#1f2937"
    parts.append(body)
    # 4 legs, each hip + thigh + shin
    for (x, z) in ((-0.28, 0.42), (0.28, 0.42), (-0.28, -0.42), (0.28, -0.42)):
        hip = Part.new("joint", name="Hip", position=(x, 0.6, z))
        hip.geometry = {"r": 0.09}
        parts.append(hip)
        thigh = Part.new("leg", name="Thigh", position=(x, 0.38, z))
        thigh.geometry = {"w": 0.09, "h": 0.35, "d": 0.09}
        parts.append(thigh)
        knee = Part.new("joint", name="Knee", position=(x, 0.2, z))
        knee.geometry = {"r": 0.07}
        parts.append(knee)
        shin = Part.new("leg", name="Shin", position=(x, 0.02, z))
        shin.geometry = {"w": 0.07, "h": 0.32, "d": 0.07}
        parts.append(shin)
    # Head / camera block
    head = Part.new("chassis", name="Head", position=(0, 0.78, 0.55))
    head.geometry = {"w": 0.22, "h": 0.18, "d": 0.25}
    parts.append(head)
    cam = Part.new("camera", name="Front camera", position=(0, 0.78, 0.7))
    cam.rotation = [math.pi / 2, 0, 0]
    parts.append(cam)

    for i, p in enumerate(parts):
        p.order = i
    return CustomBuild(parts=parts)


def _build_rov() -> CustomBuild:
    parts: list[Part] = []
    # Pressure hull — cylindrical
    hull = Part.new("arm", name="Pressure hull", position=(0, 0.3, 0))
    hull.geometry = {"rt": 0.25, "rb": 0.25, "h": 1.0}
    hull.rotation = [math.pi / 2, 0, 0]
    hull.color = "#0284c7"
    parts.append(hull)
    # Front dome
    dome = Part.new("joint", name="Dome", position=(0, 0.3, 0.5))
    dome.geometry = {"r": 0.25}
    dome.color = "#1d4ed8"
    parts.append(dome)
    # Six thrusters (propellers): 4 vertical-horizontal, 2 vertical
    for (x, z, rot) in (
        (-0.28, 0.4, [math.pi / 2, 0, 0]),
        (0.28, 0.4, [math.pi / 2, 0, 0]),
        (-0.28, -0.4, [math.pi / 2, 0, 0]),
        (0.28, -0.4, [math.pi / 2, 0, 0]),
        (0, 0.55, 0.0),
        (0, 0.55, 0.0),
    ):
        prop = Part.new("propeller", name="Thruster",
                        position=(x, 0.3 if isinstance(rot, list) else 0.55, z))
        if isinstance(rot, list):
            prop.rotation = rot
        parts.append(prop)
    # Front-facing camera inside dome
    cam = Part.new("camera", name="HD camera", position=(0, 0.3, 0.58))
    cam.rotation = [math.pi / 2, 0, 0]
    parts.append(cam)
    # Manipulator arm
    sns = Part.new("sensor", name="Sonar", position=(0, 0.05, 0.45))
    sns.geometry = {"w": 0.18, "h": 0.06, "d": 0.14}
    parts.append(sns)

    for i, p in enumerate(parts):
        p.order = i
    return CustomBuild(parts=parts)


# ─────────────────────────────────────────────────────────
#  Registry
# ─────────────────────────────────────────────────────────

TEMPLATES: dict[str, RobotTemplate] = {
    "quadcopter": RobotTemplate(
        template_id="quadcopter",
        display_name="Quadcopter Drone",
        description="Classic X-frame 4-rotor UAV with camera gimbal. "
                    "Good starting point for anything aerial.",
        device_type="drone",
        tagline="DJI-style aerial platform",
        icon="🚁",
        tags=["aerial", "4-rotor", "camera", "beginner"],
        color="#00b4d8",
        factory=_build_quadcopter,
    ),
    "6dof_arm": RobotTemplate(
        template_id="6dof_arm",
        display_name="6-DOF Robotic Arm",
        description="Six-joint revolute arm with end effector. "
                    "Workbench / manipulation / cobot use cases.",
        device_type="robot_arm",
        tagline="UR5-style industrial arm",
        icon="🦾",
        tags=["arm", "industrial", "manipulation", "6dof"],
        color="#f59e0b",
        factory=_build_6dof_arm,
    ),
    "two_wheel_rover": RobotTemplate(
        template_id="two_wheel_rover",
        display_name="Differential-drive Rover",
        description="Two-wheeled rover with caster, IMU, and forward camera. "
                    "TurtleBot-class ground robot.",
        device_type="ground_robot",
        tagline="TurtleBot-class two-wheeled rover",
        icon="🤖",
        tags=["ground", "2-wheel", "indoor", "beginner"],
        color="#10b981",
        factory=_build_two_wheel_rover,
    ),
    "humanoid": RobotTemplate(
        template_id="humanoid",
        display_name="Humanoid (Bipedal)",
        description="Two legs, two arms, head, and twin-camera eyes — "
                    "symmetric biped frame.",
        device_type="humanoid",
        tagline="Symmetric biped with twin cameras",
        icon="🧍",
        tags=["humanoid", "biped", "cobot"],
        color="#6366f1",
        factory=_build_humanoid,
    ),
    "hexapod": RobotTemplate(
        template_id="hexapod",
        display_name="Hexapod Robot",
        description="Six-legged crawler with articulated limbs — "
                    "inherently stable, rough-terrain friendly.",
        device_type="legged",
        tagline="Six-legged crawler",
        icon="🕷️",
        tags=["legged", "hexapod", "rough-terrain"],
        color="#7c2d12",
        factory=_build_hexapod,
    ),
    "warehouse_agv": RobotTemplate(
        template_id="warehouse_agv",
        display_name="Warehouse AGV",
        description="Flat-platform four-wheel AGV with lidar + safety laser. "
                    "Built for picking and pallet transport.",
        device_type="ground_robot",
        tagline="Autonomous pallet mover",
        icon="🏭",
        tags=["agv", "warehouse", "industrial"],
        color="#f97316",
        factory=_build_warehouse_agv,
    ),
    "fixed_wing": RobotTemplate(
        template_id="fixed_wing",
        display_name="Fixed-wing UAV",
        description="Main wing + horizontal/vertical stabilizers + pusher prop. "
                    "Long-range surveillance platform.",
        device_type="drone",
        tagline="Long-range surveillance plane",
        icon="✈️",
        tags=["aerial", "fixed-wing", "long-range"],
        color="#3b82f6",
        factory=_build_fixed_wing,
    ),
    "gripper": RobotTemplate(
        template_id="gripper",
        display_name="End-effector Gripper",
        description="Two-finger gripper with wrist joint and force sensor — "
                    "good for learning the manipulation loop.",
        device_type="robot_arm",
        tagline="Two-finger parallel gripper",
        icon="🤏",
        tags=["effector", "gripper", "manipulation"],
        color="#10b981",
        factory=_build_gripper,
    ),
    "quadruped": RobotTemplate(
        template_id="quadruped",
        display_name="Quadruped (Spot-style)",
        description="Four-legged dog-class robot with articulated limbs "
                    "and a head-mounted camera.",
        device_type="legged",
        tagline="Four-legged outdoor explorer",
        icon="🐕",
        tags=["legged", "quadruped", "outdoor"],
        color="#1f2937",
        factory=_build_quadruped,
    ),
    "rov": RobotTemplate(
        template_id="rov",
        display_name="Underwater ROV",
        description="Cylindrical pressure hull with 6 thrusters, HD dome camera, "
                    "and sonar. Subsea inspection.",
        device_type="marine",
        tagline="6-thruster subsea inspector",
        icon="🐟",
        tags=["marine", "rov", "subsea", "submersible"],
        color="#0284c7",
        factory=_build_rov,
    ),
}


def list_templates() -> list[dict]:
    """JSON-friendly listing for the frontend gallery."""
    return [t.to_dict() for t in TEMPLATES.values()]


def get_template(template_id: str) -> RobotTemplate | None:
    return TEMPLATES.get(template_id)
