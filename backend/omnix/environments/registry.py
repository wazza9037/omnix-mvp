"""
OMNIX Environment Registry — pre-built 3D environments for robot simulation.

Each environment is a dictionary containing:
  - metadata (id, name, description, thumbnail color)
  - obstacles (list of Obstacle dicts)
  - physics (EnvironmentPhysics config)
  - lighting (Three.js lighting params)
  - atmosphere (fog, skybox color)
  - ground (texture type, color, size)

All geometry is specified as Three.js-compatible primitives (box, cylinder,
sphere, cone, plane) so the frontend renders them directly — no external
assets required.
"""

import uuid
import time
import copy
import math
from typing import Dict, List, Optional, Any

from .obstacles import Obstacle, ObstacleManager
from .physics_env import (
    EnvironmentPhysics, WindZone, SurfaceZone,
    EARTH_INDOOR, EARTH_OUTDOOR, MARS_SURFACE, UNDERWATER,
    FACTORY, URBAN, LAB,
)


# ═══════════════════════════════════════════════════════════════════
#  Helper: build obstacle lists for each environment
# ═══════════════════════════════════════════════════════════════════

def _warehouse_obstacles() -> List[Dict]:
    """Warehouse: floor grid, shelving racks, loading dock, forklift paths, pallets, doorways."""
    obs = []

    # Shelving racks — 3 rows of tall shelves
    for row in range(3):
        for col in range(4):
            x = -12 + col * 6
            z = -8 + row * 8
            # Vertical uprights (4 per rack section)
            for ux in [x - 1.2, x + 1.2]:
                for uz in [z - 0.4, z + 0.4]:
                    obs.append(Obstacle(
                        obstacle_type="box", position=[ux, 2.5, uz],
                        size=[0.1, 5, 0.1], color="#555555",
                        label=f"rack_upright_{row}_{col}",
                    ).to_dict())
            # Shelves (3 levels)
            for level in range(3):
                y = 1.0 + level * 1.8
                obs.append(Obstacle(
                    obstacle_type="box", position=[x, y, z],
                    size=[2.6, 0.08, 1.0], color="#8B7355",
                    material_props={"roughness": 0.8},
                    label=f"shelf_{row}_{col}_L{level}",
                ).to_dict())
            # Boxes on shelves
            for level in range(3):
                y = 1.1 + level * 1.8
                for bx_off in [-0.6, 0.2, 0.8]:
                    obs.append(Obstacle(
                        obstacle_type="box",
                        position=[x + bx_off, y + 0.25, z],
                        size=[0.5, 0.5, 0.4],
                        color="#C4A265",
                        label="box_on_shelf",
                    ).to_dict())

    # Loading dock — raised platform at far end
    obs.append(Obstacle(
        obstacle_type="box", position=[0, 0.3, -18],
        size=[20, 0.6, 4], color="#666666",
        material_props={"roughness": 0.9},
        label="loading_dock",
    ).to_dict())

    # Dock bumpers
    for x in [-8, -4, 0, 4, 8]:
        obs.append(Obstacle(
            obstacle_type="box", position=[x, 0.8, -19.8],
            size=[0.8, 0.6, 0.3], color="#333333",
            label="dock_bumper",
        ).to_dict())

    # Pallets scattered near dock
    for i, (px, pz) in enumerate([(-6, -14), (-2, -14), (3, -14), (7, -13)]):
        obs.append(Obstacle(
            obstacle_type="box", position=[px, 0.08, pz],
            size=[1.2, 0.15, 1.0], color="#B8860B",
            label=f"pallet_{i}",
        ).to_dict())
        # Stacked boxes on some pallets
        if i % 2 == 0:
            obs.append(Obstacle(
                obstacle_type="box", position=[px, 0.5, pz],
                size=[1.0, 0.6, 0.8], color="#C4A265",
                label=f"pallet_box_{i}",
            ).to_dict())

    # Forklift path markings (non-collidable floor marks)
    for z in range(-16, 12, 2):
        obs.append(Obstacle(
            obstacle_type="box", position=[-16, 0.01, z],
            size=[0.15, 0.01, 1.5], color="#FFD700",
            is_collidable=False,
            label="forklift_path",
        ).to_dict())
        obs.append(Obstacle(
            obstacle_type="box", position=[16, 0.01, z],
            size=[0.15, 0.01, 1.5], color="#FFD700",
            is_collidable=False,
            label="forklift_path",
        ).to_dict())

    # Walls
    for wall in [
        {"pos": [0, 3, -20], "size": [40, 6, 0.3]},    # back
        {"pos": [0, 3, 20], "size": [40, 6, 0.3]},      # front
        {"pos": [-20, 3, 0], "size": [0.3, 6, 40]},     # left
        {"pos": [20, 3, 0], "size": [0.3, 6, 40]},      # right
    ]:
        obs.append(Obstacle(
            obstacle_type="box", position=wall["pos"],
            size=wall["size"], color="#9E9E9E",
            label="wall",
        ).to_dict())

    # Doorways (gaps in front wall)
    obs.append(Obstacle(
        obstacle_type="box", position=[0, 5.5, 20],
        size=[4, 1, 0.3], color="#9E9E9E",
        label="door_lintel",
    ).to_dict())

    return obs


def _outdoor_obstacles() -> List[Dict]:
    """Outdoor field: trees, rocks, fence, hills, path/road."""
    obs = []

    # Trees — cone (foliage) + cylinder (trunk)
    tree_positions = [
        (-12, 5), (-8, 12), (-3, 8), (6, 10), (10, 4),
        (14, 12), (-10, -6), (8, -8), (15, -3), (-14, -10),
        (-5, -12), (3, -15), (12, -12),
    ]
    for i, (tx, tz) in enumerate(tree_positions):
        trunk_h = 1.5 + (i % 3) * 0.5
        foliage_h = 2.0 + (i % 4) * 0.5
        foliage_r = 1.2 + (i % 3) * 0.3
        obs.append(Obstacle(
            obstacle_type="cylinder",
            position=[tx, trunk_h / 2, tz],
            size=[0.25, trunk_h, 0.25],
            color="#8B4513",
            label=f"tree_trunk_{i}",
        ).to_dict())
        obs.append(Obstacle(
            obstacle_type="cone",
            position=[tx, trunk_h + foliage_h / 2, tz],
            size=[foliage_r, foliage_h, foliage_r],
            color="#2E8B57" if i % 2 == 0 else "#228B22",
            label=f"tree_foliage_{i}",
        ).to_dict())

    # Rocks — spheres of varying sizes
    rock_positions = [
        (-6, 3, 0.4), (2, -5, 0.6), (9, 7, 0.3), (-11, -2, 0.5),
        (5, -10, 0.35), (-3, 14, 0.45), (13, -7, 0.55),
    ]
    for i, (rx, rz, rr) in enumerate(rock_positions):
        obs.append(Obstacle(
            obstacle_type="sphere",
            position=[rx, rr * 0.6, rz],
            size=[rr * 2, rr * 2, rr * 2],
            color="#808080" if i % 2 == 0 else "#696969",
            label=f"rock_{i}",
        ).to_dict())

    # Fence perimeter
    fence_h = 1.2
    for x in range(-18, 19, 2):
        # Front and back fence
        for z in [-18, 18]:
            obs.append(Obstacle(
                obstacle_type="box",
                position=[x, fence_h / 2, z],
                size=[0.08, fence_h, 0.08],
                color="#8B7355", is_collidable=True,
                label="fence_post",
            ).to_dict())
    for z in range(-18, 19, 2):
        for x in [-18, 18]:
            obs.append(Obstacle(
                obstacle_type="box",
                position=[x, fence_h / 2, z],
                size=[0.08, fence_h, 0.08],
                color="#8B7355",
                label="fence_post",
            ).to_dict())
    # Horizontal rails
    for z in [-18, 18]:
        obs.append(Obstacle(
            obstacle_type="box", position=[0, 0.4, z],
            size=[36, 0.06, 0.06], color="#A0856C",
            label="fence_rail",
        ).to_dict())
        obs.append(Obstacle(
            obstacle_type="box", position=[0, 0.9, z],
            size=[36, 0.06, 0.06], color="#A0856C",
            label="fence_rail",
        ).to_dict())
    for x in [-18, 18]:
        obs.append(Obstacle(
            obstacle_type="box", position=[x, 0.4, 0],
            size=[0.06, 0.06, 36], color="#A0856C",
            label="fence_rail",
        ).to_dict())
        obs.append(Obstacle(
            obstacle_type="box", position=[x, 0.9, 0],
            size=[0.06, 0.06, 36], color="#A0856C",
            label="fence_rail",
        ).to_dict())

    # Hills — flat wide boxes raised slightly to simulate terrain bumps
    for hx, hz, hs, hh in [(-8, -4, 6, 0.8), (10, 8, 5, 0.6), (4, -12, 4, 0.5)]:
        obs.append(Obstacle(
            obstacle_type="box",
            position=[hx, hh / 2, hz],
            size=[hs, hh, hs],
            color="#4A7C3F",
            material_props={"roughness": 0.95},
            is_collidable=True,
            label="hill",
        ).to_dict())

    # Dirt path / road — non-collidable ground markings
    for z in range(-16, 17, 2):
        obs.append(Obstacle(
            obstacle_type="box",
            position=[0, 0.02, z],
            size=[3, 0.02, 2.2],
            color="#C4A882",
            is_collidable=False,
            label="path",
        ).to_dict())

    return obs


def _office_obstacles() -> List[Dict]:
    """Office/Room: walls, desks, chairs, doorway, windows, carpet area."""
    obs = []

    # Room walls (10m x 8m)
    walls = [
        {"pos": [0, 1.5, -4], "size": [10, 3, 0.2]},     # back
        {"pos": [0, 1.5, 4], "size": [10, 3, 0.2]},       # front
        {"pos": [-5, 1.5, 0], "size": [0.2, 3, 8]},       # left
        {"pos": [5, 1.5, 0], "size": [0.2, 3, 8]},        # right
    ]
    for w in walls:
        obs.append(Obstacle(
            obstacle_type="box", position=w["pos"],
            size=w["size"], color="#F5F5DC",
            label="wall",
        ).to_dict())

    # Doorway in front wall (gap + lintel)
    obs.append(Obstacle(
        obstacle_type="box", position=[2, 2.7, 4],
        size=[1.2, 0.3, 0.2], color="#8B7355",
        label="door_frame_top",
    ).to_dict())

    # Windows on right wall (transparent panels)
    for wz in [-2, 1]:
        obs.append(Obstacle(
            obstacle_type="box", position=[4.9, 1.8, wz],
            size=[0.05, 1.2, 1.5], color="#87CEEB",
            material_props={"transparent": True, "opacity": 0.3},
            is_collidable=False,
            label="window",
        ).to_dict())

    # Desks
    for dx, dz in [(-2, -2), (2, -2), (-2, 1.5)]:
        # Desktop surface
        obs.append(Obstacle(
            obstacle_type="box", position=[dx, 0.75, dz],
            size=[1.6, 0.05, 0.8], color="#D2B48C",
            label="desk_top",
        ).to_dict())
        # Legs
        for lx, lz in [(dx - 0.7, dz - 0.3), (dx + 0.7, dz - 0.3),
                        (dx - 0.7, dz + 0.3), (dx + 0.7, dz + 0.3)]:
            obs.append(Obstacle(
                obstacle_type="box", position=[lx, 0.37, lz],
                size=[0.05, 0.72, 0.05], color="#A0856C",
                label="desk_leg",
            ).to_dict())

    # Chairs (simplified: seat + back + 4 legs)
    for cx, cz in [(-2, -1), (2, -1), (-2, 2.5)]:
        obs.append(Obstacle(
            obstacle_type="box", position=[cx, 0.45, cz],
            size=[0.5, 0.05, 0.5], color="#404040",
            label="chair_seat",
        ).to_dict())
        obs.append(Obstacle(
            obstacle_type="box", position=[cx, 0.75, cz + 0.22],
            size=[0.5, 0.6, 0.05], color="#404040",
            label="chair_back",
        ).to_dict())

    # Carpet area (non-collidable)
    obs.append(Obstacle(
        obstacle_type="box", position=[0, 0.01, 0],
        size=[6, 0.01, 5], color="#8B4513",
        material_props={"roughness": 0.95},
        is_collidable=False,
        label="carpet",
    ).to_dict())

    return obs


def _factory_obstacles() -> List[Dict]:
    """Factory floor: conveyor belts, workstations, safety barriers, assembly line."""
    obs = []

    # Conveyor belts — 2 long parallel belts
    for cz in [-4, 4]:
        # Belt surface (animated in frontend)
        obs.append(Obstacle(
            obstacle_type="box", position=[0, 0.9, cz],
            size=[18, 0.08, 1.2], color="#444444",
            is_dynamic=True,
            dynamic_config={"motion": "conveyor", "speed": 0.5, "axis": [1, 0, 0]},
            label="conveyor_belt",
        ).to_dict())
        # Belt supports
        for sx in range(-8, 9, 4):
            obs.append(Obstacle(
                obstacle_type="box", position=[sx, 0.44, cz - 0.5],
                size=[0.15, 0.88, 0.15], color="#666666",
                label="conveyor_support",
            ).to_dict())
            obs.append(Obstacle(
                obstacle_type="box", position=[sx, 0.44, cz + 0.5],
                size=[0.15, 0.88, 0.15], color="#666666",
                label="conveyor_support",
            ).to_dict())
        # Side rails
        obs.append(Obstacle(
            obstacle_type="box", position=[0, 1.0, cz - 0.65],
            size=[18, 0.15, 0.06], color="#888888",
            label="conveyor_rail",
        ).to_dict())
        obs.append(Obstacle(
            obstacle_type="box", position=[0, 1.0, cz + 0.65],
            size=[18, 0.15, 0.06], color="#888888",
            label="conveyor_rail",
        ).to_dict())

    # Workstations between conveyors
    for wx in [-6, 0, 6]:
        obs.append(Obstacle(
            obstacle_type="box", position=[wx, 0.5, 0],
            size=[2, 1, 1.5], color="#5C5C5C",
            label="workstation",
        ).to_dict())
        # Tool rack on workstation
        obs.append(Obstacle(
            obstacle_type="box", position=[wx, 1.4, 0],
            size=[0.6, 0.8, 0.1], color="#777777",
            label="tool_rack",
        ).to_dict())

    # Safety barriers — yellow/black striped posts + rails
    barrier_positions = [
        (-10, -7), (-10, 7), (10, -7), (10, 7),
        (-10, 0), (10, 0),
    ]
    for bx, bz in barrier_positions:
        obs.append(Obstacle(
            obstacle_type="cylinder",
            position=[bx, 0.5, bz],
            size=[0.12, 1.0, 0.12], color="#FFD700",
            label="safety_post",
        ).to_dict())

    # Safety barrier rails (horizontal)
    obs.append(Obstacle(
        obstacle_type="box", position=[-10, 0.8, 0],
        size=[0.08, 0.08, 14], color="#FFD700",
        label="safety_rail",
    ).to_dict())
    obs.append(Obstacle(
        obstacle_type="box", position=[10, 0.8, 0],
        size=[0.08, 0.08, 14], color="#FFD700",
        label="safety_rail",
    ).to_dict())

    # Assembly line stations at ends
    for ax in [-10, 10]:
        obs.append(Obstacle(
            obstacle_type="box", position=[ax, 0.7, -4],
            size=[1.5, 1.4, 1.5], color="#4A4A4A",
            label="assembly_station",
        ).to_dict())
        obs.append(Obstacle(
            obstacle_type="box", position=[ax, 0.7, 4],
            size=[1.5, 1.4, 1.5], color="#4A4A4A",
            label="assembly_station",
        ).to_dict())

    # Floor markings (non-collidable)
    for z in range(-8, 9, 2):
        obs.append(Obstacle(
            obstacle_type="box", position=[0, 0.005, z],
            size=[20, 0.005, 0.1], color="#FFD700",
            is_collidable=False,
            label="floor_marking",
        ).to_dict())

    return obs


def _urban_obstacles() -> List[Dict]:
    """Urban street: road, sidewalks, buildings, traffic lights, crosswalks."""
    obs = []

    # Road surface (non-collidable)
    obs.append(Obstacle(
        obstacle_type="box", position=[0, 0.01, 0],
        size=[8, 0.01, 40], color="#3A3A3A",
        is_collidable=False,
        label="road",
    ).to_dict())

    # Lane markings (dashed center line)
    for z in range(-18, 19, 3):
        obs.append(Obstacle(
            obstacle_type="box", position=[0, 0.02, z],
            size=[0.15, 0.01, 1.5], color="#FFFFFF",
            is_collidable=False,
            label="lane_marking",
        ).to_dict())

    # Sidewalks
    for sx in [-6, 6]:
        obs.append(Obstacle(
            obstacle_type="box", position=[sx, 0.1, 0],
            size=[4, 0.2, 40], color="#AAAAAA",
            is_collidable=False,
            label="sidewalk",
        ).to_dict())

    # Buildings (tall boxes with different heights)
    buildings = [
        {"pos": [-12, 6, -10], "size": [6, 12, 8], "color": "#8899AA"},
        {"pos": [-12, 4, 5], "size": [6, 8, 10], "color": "#AA9988"},
        {"pos": [12, 8, -8], "size": [6, 16, 10], "color": "#7788AA"},
        {"pos": [12, 5, 8], "size": [6, 10, 8], "color": "#99AA88"},
        {"pos": [-12, 3, 16], "size": [6, 6, 6], "color": "#AA8877"},
        {"pos": [12, 7, -18], "size": [6, 14, 4], "color": "#8877AA"},
    ]
    for b in buildings:
        obs.append(Obstacle(
            obstacle_type="box", position=b["pos"],
            size=b["size"], color=b["color"],
            label="building",
        ).to_dict())
        # Window pattern (non-collidable decorations on facade)
        bx, by, bz = b["pos"]
        bw, bh, bd = b["size"]
        facade_x = bx + bw / 2 + 0.01 if bx > 0 else bx - bw / 2 - 0.01
        for wy in range(2, int(bh), 2):
            for wz_off in range(-int(bd / 2) + 1, int(bd / 2), 2):
                obs.append(Obstacle(
                    obstacle_type="box",
                    position=[facade_x, wy, bz + wz_off],
                    size=[0.02, 0.8, 0.6],
                    color="#DDDDFF",
                    material_props={"transparent": True, "opacity": 0.5},
                    is_collidable=False,
                    label="window",
                ).to_dict())

    # Traffic lights
    for tz in [-5, 5]:
        pole_x = 3.5
        obs.append(Obstacle(
            obstacle_type="cylinder", position=[pole_x, 2.0, tz],
            size=[0.08, 4.0, 0.08], color="#333333",
            label="traffic_pole",
        ).to_dict())
        # Light housing
        obs.append(Obstacle(
            obstacle_type="box", position=[pole_x, 3.8, tz],
            size=[0.3, 0.8, 0.3], color="#222222",
            label="traffic_light",
        ).to_dict())
        # Red/yellow/green lights
        for li, (ly, lc) in enumerate([(4.05, "#FF0000"), (3.8, "#FFD700"), (3.55, "#00FF00")]):
            obs.append(Obstacle(
                obstacle_type="sphere",
                position=[pole_x + 0.16, ly, tz],
                size=[0.12, 0.12, 0.12],
                color=lc,
                material_props={"emissive": lc, "emissiveIntensity": 0.6},
                is_collidable=False,
                label=f"traffic_light_{'rgy'[li]}",
            ).to_dict())

    # Crosswalks
    for cz in [-5, 5]:
        for stripe in range(-3, 4):
            obs.append(Obstacle(
                obstacle_type="box", position=[stripe, 0.02, cz],
                size=[0.5, 0.01, 2.5], color="#FFFFFF",
                is_collidable=False,
                label="crosswalk",
            ).to_dict())

    return obs


def _mars_obstacles() -> List[Dict]:
    """Mars surface: craters, rocks, rover tracks, habitat dome."""
    obs = []

    # Craters — concave effect via ring + depression
    crater_data = [
        (5, -8, 3.0), (-10, 4, 2.0), (12, 6, 1.5), (-5, -12, 2.5), (0, 10, 4.0),
    ]
    for i, (cx, cz, cr) in enumerate(crater_data):
        # Crater rim (torus)
        obs.append(Obstacle(
            obstacle_type="cylinder",
            position=[cx, 0.15, cz],
            size=[cr * 2, 0.3, cr * 2],
            color="#C1440E",
            label=f"crater_rim_{i}",
        ).to_dict())
        # Inner depression (darker disc)
        obs.append(Obstacle(
            obstacle_type="box",
            position=[cx, -0.05, cz],
            size=[cr * 1.6, 0.1, cr * 1.6],
            color="#8B3A0E",
            is_collidable=False,
            label=f"crater_floor_{i}",
        ).to_dict())

    # Rocks — varied orange/brown spheres
    rock_data = [
        (-3, -4, 0.5), (7, 2, 0.8), (-8, -8, 0.4), (3, 6, 0.6),
        (14, -3, 0.35), (-12, 8, 0.55), (8, -14, 0.7), (-6, 12, 0.45),
        (0, -6, 0.3), (10, 10, 0.5), (-14, -5, 0.6),
    ]
    for i, (rx, rz, rr) in enumerate(rock_data):
        obs.append(Obstacle(
            obstacle_type="sphere",
            position=[rx, rr * 0.5, rz],
            size=[rr * 2, rr * 2, rr * 2],
            color="#B5651D" if i % 3 == 0 else "#A0522D" if i % 3 == 1 else "#CD853F",
            label=f"mars_rock_{i}",
        ).to_dict())

    # Rover tracks (non-collidable lines)
    for t in range(-14, 10):
        obs.append(Obstacle(
            obstacle_type="box",
            position=[t + 0.5, 0.01, t * 0.3 + 2],
            size=[1.2, 0.01, 0.3],
            color="#9B6B3D",
            is_collidable=False,
            label="rover_track",
        ).to_dict())

    # Habitat dome — hemisphere approximated with sphere + cylinder base
    obs.append(Obstacle(
        obstacle_type="sphere",
        position=[-8, 2.5, -6],
        size=[5, 5, 5],
        color="#DDDDDD",
        material_props={"transparent": True, "opacity": 0.35, "metalness": 0.6},
        label="habitat_dome",
    ).to_dict())
    obs.append(Obstacle(
        obstacle_type="cylinder",
        position=[-8, 0.5, -6],
        size=[2.6, 1.0, 2.6],
        color="#AAAAAA",
        label="habitat_base",
    ).to_dict())
    # Airlock door
    obs.append(Obstacle(
        obstacle_type="box",
        position=[-5.6, 0.9, -6],
        size=[0.4, 1.8, 1.0],
        color="#888888",
        label="airlock",
    ).to_dict())

    return obs


def _underwater_obstacles() -> List[Dict]:
    """Underwater: coral, sand floor ripples, fish, kelp."""
    obs = []

    # Coral structures — clusters of colorful cylinders and spheres
    coral_data = [
        (-5, 3, "#FF6B6B"), (3, -4, "#FF69B4"), (8, 7, "#FFA07A"),
        (-10, -6, "#FF7F50"), (6, -9, "#FF6347"), (-3, 10, "#FF4500"),
        (12, 2, "#FFB6C1"), (-8, 8, "#FF69B4"),
    ]
    for i, (cx, cz, color) in enumerate(coral_data):
        # Main coral stalk
        h = 1.0 + (i % 3) * 0.5
        obs.append(Obstacle(
            obstacle_type="cylinder",
            position=[cx, h / 2, cz],
            size=[0.2, h, 0.2],
            color=color,
            label=f"coral_stalk_{i}",
        ).to_dict())
        # Coral branches (smaller cylinders at angles)
        for bj in range(2 + i % 2):
            angle = bj * 2.1 + i
            bh = 0.5 + bj * 0.2
            obs.append(Obstacle(
                obstacle_type="cylinder",
                position=[cx + 0.3 * math.cos(angle), h * 0.7 + bj * 0.2, cz + 0.3 * math.sin(angle)],
                size=[0.12, bh, 0.12],
                color=color,
                label=f"coral_branch_{i}_{bj}",
            ).to_dict())
        # Coral top sphere
        obs.append(Obstacle(
            obstacle_type="sphere",
            position=[cx, h + 0.2, cz],
            size=[0.35, 0.35, 0.35],
            color=color,
            label=f"coral_top_{i}",
        ).to_dict())

    # Sand ripples (non-collidable, subtle)
    for z in range(-14, 15, 3):
        obs.append(Obstacle(
            obstacle_type="box",
            position=[0, 0.03, z],
            size=[28, 0.03, 1.0],
            color="#DEB887",
            is_collidable=False,
            label="sand_ripple",
        ).to_dict())

    # Kelp forests — tall wavy cylinders (animated in frontend)
    kelp_positions = [
        (-12, -3), (-10, 5), (-7, -10), (4, 12), (9, -6),
        (14, 3), (-4, -14), (11, -11), (-14, 0),
    ]
    for i, (kx, kz) in enumerate(kelp_positions):
        h = 3 + (i % 3)
        obs.append(Obstacle(
            obstacle_type="cylinder",
            position=[kx, h / 2, kz],
            size=[0.08, h, 0.08],
            color="#2E8B57" if i % 2 == 0 else "#3CB371",
            is_dynamic=True,
            dynamic_config={"motion": "swing", "speed": 0.8, "amplitude": 0.3,
                            "swing_angle": 0.5, "base_position": [kx, h / 2, kz]},
            label=f"kelp_{i}",
        ).to_dict())

    # Fish (small animated spheres)
    fish_positions = [
        (2, 3, -2), (-5, 2, 6), (8, 4, -5), (-3, 1.5, -8),
        (6, 2.5, 3), (-9, 3, 1), (1, 4, 8),
    ]
    for i, (fx, fy, fz) in enumerate(fish_positions):
        obs.append(Obstacle(
            obstacle_type="sphere",
            position=[fx, fy, fz],
            size=[0.2, 0.12, 0.2],
            color="#FFD700" if i % 3 == 0 else "#87CEEB" if i % 3 == 1 else "#FF6347",
            is_dynamic=True,
            dynamic_config={"motion": "circular", "speed": 0.3 + i * 0.1,
                            "amplitude": 2.0 + i * 0.5,
                            "base_position": [fx, fy, fz]},
            is_collidable=False,
            label=f"fish_{i}",
        ).to_dict())

    return obs


def _lab_obstacles() -> List[Dict]:
    """Empty lab: measurement grid, reference markers, calibration targets on walls."""
    obs = []

    # Grid lines on floor (non-collidable)
    for x in range(-10, 11, 2):
        obs.append(Obstacle(
            obstacle_type="box", position=[x, 0.005, 0],
            size=[0.02, 0.005, 20], color="#CCCCCC",
            is_collidable=False,
            label="grid_line_x",
        ).to_dict())
    for z in range(-10, 11, 2):
        obs.append(Obstacle(
            obstacle_type="box", position=[0, 0.005, z],
            size=[20, 0.005, 0.02], color="#CCCCCC",
            is_collidable=False,
            label="grid_line_z",
        ).to_dict())

    # Meter markers (small cubes at integer positions)
    for x in range(-10, 11, 5):
        for z in range(-10, 11, 5):
            if x == 0 and z == 0:
                continue
            obs.append(Obstacle(
                obstacle_type="box", position=[x, 0.02, z],
                size=[0.1, 0.02, 0.1], color="#FF4444",
                is_collidable=False,
                label="meter_marker",
            ).to_dict())

    # Origin marker (larger, teal)
    obs.append(Obstacle(
        obstacle_type="box", position=[0, 0.03, 0],
        size=[0.2, 0.03, 0.2], color="#00B4D8",
        is_collidable=False,
        label="origin_marker",
    ).to_dict())

    # Walls (light)
    walls = [
        {"pos": [0, 1.5, -10], "size": [20, 3, 0.15]},
        {"pos": [0, 1.5, 10], "size": [20, 3, 0.15]},
        {"pos": [-10, 1.5, 0], "size": [0.15, 3, 20]},
        {"pos": [10, 1.5, 0], "size": [0.15, 3, 20]},
    ]
    for w in walls:
        obs.append(Obstacle(
            obstacle_type="box", position=w["pos"],
            size=w["size"], color="#F0F0F0",
            label="wall",
        ).to_dict())

    # Calibration targets on walls (checkerboard-style patches)
    cal_positions = [
        (0, 1.5, -9.9),    # back wall center
        (-4, 1.5, -9.9),   # back wall left
        (4, 1.5, -9.9),    # back wall right
        (-9.9, 1.5, 0),    # left wall center
        (9.9, 1.5, 0),     # right wall center
    ]
    for i, (cx, cy, cz) in enumerate(cal_positions):
        size = [0.8, 0.8, 0.02] if abs(cz) > 5 else [0.02, 0.8, 0.8]
        obs.append(Obstacle(
            obstacle_type="box", position=[cx, cy, cz],
            size=size, color="#000000",
            is_collidable=False,
            label=f"calibration_target_{i}",
        ).to_dict())
        # Inner white square
        inner_size = [s * 0.5 for s in size]
        obs.append(Obstacle(
            obstacle_type="box",
            position=[cx + (0.001 if size[0] < 0.1 else 0),
                      cy,
                      cz + (0.001 if size[2] < 0.1 else 0)],
            size=inner_size, color="#FFFFFF",
            is_collidable=False,
            label=f"calibration_inner_{i}",
        ).to_dict())

    return obs


# ═══════════════════════════════════════════════════════════════════
#  Environment definitions
# ═══════════════════════════════════════════════════════════════════

ENVIRONMENTS = {
    "warehouse": {
        "id": "warehouse",
        "name": "Warehouse",
        "description": "Industrial warehouse with shelving racks, loading dock, forklift paths, and pallets.",
        "icon": "🏭",
        "thumbnail_color": "#8B7355",
        "ground": {
            "type": "checkered",
            "color1": "#555555",
            "color2": "#4A4A4A",
            "size": 40,
            "tile_size": 2,
        },
        "lighting": {
            "ambient_color": 0x606060,
            "ambient_intensity": 0.5,
            "key_color": 0xFFF4E0,
            "key_intensity": 0.9,
            "key_position": [10, 20, 5],
            "hemisphere_sky": 0xFFEEDD,
            "hemisphere_ground": 0x444444,
            "hemisphere_intensity": 0.3,
        },
        "atmosphere": {
            "fog_type": "linear",
            "fog_color": 0x2A2A2A,
            "fog_near": 25,
            "fog_far": 60,
            "skybox_color": 0x1A1A1A,
        },
        "physics": EARTH_INDOOR.to_dict(),
        "obstacles": _warehouse_obstacles(),
    },

    "outdoor": {
        "id": "outdoor",
        "name": "Outdoor Field",
        "description": "Open grass field with trees, rocks, fence perimeter, hills, and dirt path.",
        "icon": "🌳",
        "thumbnail_color": "#4A7C3F",
        "ground": {
            "type": "grass",
            "color1": "#4A7C3F",
            "color2": "#3D6B34",
            "size": 40,
            "tile_size": 1,
        },
        "lighting": {
            "ambient_color": 0x88AACC,
            "ambient_intensity": 0.6,
            "key_color": 0xFFEECC,
            "key_intensity": 1.3,
            "key_position": [30, 40, 20],
            "hemisphere_sky": 0x87CEEB,
            "hemisphere_ground": 0x4A7C3F,
            "hemisphere_intensity": 0.5,
        },
        "atmosphere": {
            "fog_type": "exp2",
            "fog_color": 0xCCDDEE,
            "fog_density": 0.008,
            "skybox_color": 0x87CEEB,
        },
        "physics": EARTH_OUTDOOR.to_dict(),
        "obstacles": _outdoor_obstacles(),
    },

    "office": {
        "id": "office",
        "name": "Office / Room",
        "description": "Indoor room with desks, chairs, doorway, windows, and carpet area.",
        "icon": "🏢",
        "thumbnail_color": "#D2B48C",
        "ground": {
            "type": "wood",
            "color1": "#D2B48C",
            "color2": "#C4A882",
            "size": 12,
            "tile_size": 0.5,
        },
        "lighting": {
            "ambient_color": 0x808080,
            "ambient_intensity": 0.6,
            "key_color": 0xFFF8F0,
            "key_intensity": 0.8,
            "key_position": [0, 8, 0],
            "hemisphere_sky": 0xFFF8F0,
            "hemisphere_ground": 0xD2B48C,
            "hemisphere_intensity": 0.4,
        },
        "atmosphere": {
            "fog_type": "none",
            "skybox_color": 0xF5F5DC,
        },
        "physics": EARTH_INDOOR.to_dict(),
        "obstacles": _office_obstacles(),
    },

    "factory": {
        "id": "factory",
        "name": "Factory Floor",
        "description": "Manufacturing floor with conveyor belts, workstations, safety barriers, and assembly line stations.",
        "icon": "⚙️",
        "thumbnail_color": "#5C5C5C",
        "ground": {
            "type": "concrete",
            "color1": "#555555",
            "color2": "#4D4D4D",
            "size": 30,
            "tile_size": 2,
        },
        "lighting": {
            "ambient_color": 0x606060,
            "ambient_intensity": 0.5,
            "key_color": 0xFFFFFF,
            "key_intensity": 1.0,
            "key_position": [0, 25, 0],
            "hemisphere_sky": 0xDDDDDD,
            "hemisphere_ground": 0x444444,
            "hemisphere_intensity": 0.3,
        },
        "atmosphere": {
            "fog_type": "exp2",
            "fog_color": 0x333333,
            "fog_density": 0.006,
            "skybox_color": 0x222222,
        },
        "physics": FACTORY.to_dict(),
        "obstacles": _factory_obstacles(),
    },

    "urban": {
        "id": "urban",
        "name": "Urban Street",
        "description": "City street with road, lane markings, sidewalks, buildings, traffic lights, and crosswalks.",
        "icon": "🏙️",
        "thumbnail_color": "#8899AA",
        "ground": {
            "type": "concrete",
            "color1": "#666666",
            "color2": "#5A5A5A",
            "size": 40,
            "tile_size": 2,
        },
        "lighting": {
            "ambient_color": 0x889AAB,
            "ambient_intensity": 0.5,
            "key_color": 0xFFF4E0,
            "key_intensity": 1.1,
            "key_position": [20, 35, 15],
            "hemisphere_sky": 0xAABBCC,
            "hemisphere_ground": 0x444444,
            "hemisphere_intensity": 0.4,
        },
        "atmosphere": {
            "fog_type": "exp2",
            "fog_color": 0xAABBCC,
            "fog_density": 0.005,
            "skybox_color": 0x8899AA,
        },
        "physics": URBAN.to_dict(),
        "obstacles": _urban_obstacles(),
    },

    "mars": {
        "id": "mars",
        "name": "Mars Surface",
        "description": "Red/orange Martian terrain with craters, rocks, rover tracks, and habitat dome.",
        "icon": "🔴",
        "thumbnail_color": "#C1440E",
        "ground": {
            "type": "mars",
            "color1": "#C1440E",
            "color2": "#A03A0C",
            "size": 40,
            "tile_size": 3,
        },
        "lighting": {
            "ambient_color": 0xDD8844,
            "ambient_intensity": 0.4,
            "key_color": 0xFFCC88,
            "key_intensity": 1.0,
            "key_position": [25, 30, 10],
            "hemisphere_sky": 0xFFAA66,
            "hemisphere_ground": 0x8B3A0E,
            "hemisphere_intensity": 0.5,
        },
        "atmosphere": {
            "fog_type": "exp2",
            "fog_color": 0xDD8844,
            "fog_density": 0.012,
            "skybox_color": 0xBB6633,
        },
        "physics": MARS_SURFACE.to_dict(),
        "obstacles": _mars_obstacles(),
    },

    "underwater": {
        "id": "underwater",
        "name": "Underwater",
        "description": "Deep ocean scene with coral, sand floor, fish, and kelp forests. Blue-tinted with fog.",
        "icon": "🌊",
        "thumbnail_color": "#1E6090",
        "ground": {
            "type": "sand",
            "color1": "#DEB887",
            "color2": "#D2A86E",
            "size": 30,
            "tile_size": 1.5,
        },
        "lighting": {
            "ambient_color": 0x224466,
            "ambient_intensity": 0.6,
            "key_color": 0x88BBDD,
            "key_intensity": 0.7,
            "key_position": [0, 30, 0],
            "hemisphere_sky": 0x3388BB,
            "hemisphere_ground": 0x112233,
            "hemisphere_intensity": 0.5,
        },
        "atmosphere": {
            "fog_type": "exp2",
            "fog_color": 0x0A3055,
            "fog_density": 0.025,
            "skybox_color": 0x0A3055,
        },
        "physics": UNDERWATER.to_dict(),
        "obstacles": _underwater_obstacles(),
    },

    "lab": {
        "id": "lab",
        "name": "Empty Lab",
        "description": "Clean white lab with measurement grid, reference markers, and calibration targets on walls.",
        "icon": "🔬",
        "thumbnail_color": "#E0E0E0",
        "ground": {
            "type": "grid",
            "color1": "#F0F0F0",
            "color2": "#E8E8E8",
            "size": 20,
            "tile_size": 1,
        },
        "lighting": {
            "ambient_color": 0xDDDDDD,
            "ambient_intensity": 0.7,
            "key_color": 0xFFFFFF,
            "key_intensity": 0.8,
            "key_position": [0, 15, 0],
            "hemisphere_sky": 0xFFFFFF,
            "hemisphere_ground": 0xDDDDDD,
            "hemisphere_intensity": 0.5,
        },
        "atmosphere": {
            "fog_type": "none",
            "skybox_color": 0xF8F8F8,
        },
        "physics": LAB.to_dict(),
        "obstacles": _lab_obstacles(),
    },
}


# ═══════════════════════════════════════════════════════════════════
#  EnvironmentRegistry
# ═══════════════════════════════════════════════════════════════════

class EnvironmentRegistry:
    """Registry for managing pre-built and custom environments."""

    def __init__(self):
        self._envs: Dict[str, Dict] = {}
        self._custom_envs: Dict[str, Dict] = {}

        # Load all pre-built environments
        for env_id, env_data in ENVIRONMENTS.items():
            self._envs[env_id] = env_data

    def list_environments(self) -> List[Dict]:
        """Return summary list of all environments (for picker UI)."""
        result = []
        for env_id, env in {**self._envs, **self._custom_envs}.items():
            result.append({
                "id": env["id"],
                "name": env["name"],
                "description": env["description"],
                "icon": env.get("icon", "📦"),
                "thumbnail_color": env.get("thumbnail_color", "#888888"),
                "is_custom": env_id in self._custom_envs,
                "obstacle_count": len(env.get("obstacles", [])),
            })
        return result

    def get_environment(self, env_id: str) -> Optional[Dict]:
        """Get full environment data by id."""
        env = self._envs.get(env_id) or self._custom_envs.get(env_id)
        if env:
            return copy.deepcopy(env)
        return None

    def create_custom(self, data: Dict) -> Dict:
        """Create a custom environment from user data."""
        env_id = f"custom-{uuid.uuid4().hex[:8]}"
        env = {
            "id": env_id,
            "name": data.get("name", "Custom Environment"),
            "description": data.get("description", "User-created environment"),
            "icon": data.get("icon", "🔧"),
            "thumbnail_color": data.get("thumbnail_color", "#888888"),
            "ground": data.get("ground", ENVIRONMENTS["lab"]["ground"]),
            "lighting": data.get("lighting", ENVIRONMENTS["lab"]["lighting"]),
            "atmosphere": data.get("atmosphere", ENVIRONMENTS["lab"]["atmosphere"]),
            "physics": data.get("physics", LAB.to_dict()),
            "obstacles": data.get("obstacles", []),
            "created_at": time.time(),
        }
        self._custom_envs[env_id] = env
        return env

    def delete_custom(self, env_id: str) -> bool:
        return self._custom_envs.pop(env_id, None) is not None

    def update_custom(self, env_id: str, updates: Dict) -> Optional[Dict]:
        env = self._custom_envs.get(env_id)
        if not env:
            return None
        for key in ("name", "description", "obstacles", "physics", "lighting",
                     "atmosphere", "ground", "icon", "thumbnail_color"):
            if key in updates:
                env[key] = updates[key]
        return copy.deepcopy(env)


# ── Module-level singleton + convenience functions ──

_registry = EnvironmentRegistry()


def list_environments() -> List[Dict]:
    return _registry.list_environments()


def get_environment(env_id: str) -> Optional[Dict]:
    return _registry.get_environment(env_id)


def get_registry() -> EnvironmentRegistry:
    return _registry
