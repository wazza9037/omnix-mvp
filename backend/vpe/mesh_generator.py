"""
OMNIX VPE — 3D Mesh Generator

Converts VPE analysis into parametric Three.js mesh descriptions.
The frontend interprets these parameters to build actual Three.js geometry.

Each mesh is described as a list of primitives:
  { type, geometry, material, position, rotation, scale }

Primitive types: box, sphere, cylinder, torus, cone
Material properties: color, metalness, roughness, emissive, emissiveIntensity, opacity
"""


def generate_mesh(classification: dict, image_analysis: dict, physics: dict) -> dict:
    """Generate 3D mesh parameters from VPE results."""
    cat = classification["device_category"]
    dtype = classification["device_type"]

    # Extract key dimensions (in meters for Three.js scene)
    dims_cm = image_analysis.get("geometry", {}).get("estimated_dimensions_cm", [20, 20, 10])
    # Scale to reasonable 3D scene size (1 unit = ~10cm)
    sx = dims_cm[0] / 10
    sy = dims_cm[1] / 10
    sz = dims_cm[2] / 10

    material_str = image_analysis.get("color_profile", {}).get("estimated_material", "unknown")
    colors = image_analysis.get("color_profile", {}).get("dominant_colors", [])
    primary_color = colors[0]["hex"] if colors else "#666666"
    secondary_color = colors[1]["hex"] if len(colors) > 1 else "#444444"

    mat_props = _material_to_3d(material_str, primary_color)
    accent_mat = _material_to_3d(material_str, secondary_color)

    # Component data — count from both raw and relabeled names
    components = image_analysis.get("structural", {}).get("components", [])
    _rotary_names = {
        "rotor_assembly", "wheel_or_joint", "rotor", "motor_hub", "wheel",
        "caster", "joint", "servo", "brush", "propeller", "thruster",
        "speaker_driver", "reflector", "wheel_or_track",
    }
    _linear_names = {
        "arm_segment", "structural_beam", "drone_arm", "landing_gear",
        "support_strut", "chassis_rail", "body_column", "leg_segment",
        "leg_link", "shoulder_line", "torso_axis", "limb_segment",
        "base_plate", "arm_segment", "link_bar",
    }
    rotary_count = sum(1 for c in components if c.get("name") in _rotary_names
                       or c.get("shape") == "circle")
    linear_count = sum(1 for c in components if c.get("name") in _linear_names
                       or c.get("shape") == "line")

    generators = {
        "drone": _gen_drone,
        "ground_robot": _gen_ground_robot,
        "robot_arm": _gen_arm,
        "industrial": _gen_arm,
        "humanoid": _gen_humanoid,
        "legged": _gen_legged,
        "home_robot": _gen_home_robot,
        "service_robot": _gen_service_robot,
        "warehouse": _gen_warehouse,
        "medical": _gen_medical,
        "smart_light": _gen_smart_light,
        "smart_device": _gen_smart_device,
        "marine": _gen_marine,
        "space": _gen_space,
        "extreme": _gen_extreme,
    }

    gen = generators.get(cat, _gen_generic)
    primitives = gen(sx, sy, sz, mat_props, accent_mat, rotary_count, linear_count, classification, physics)

    return {
        "primitives": primitives,
        "device_category": cat,
        "device_type": dtype,
        "scale": [sx, sy, sz],
        "bounding_size": max(sx, sy, sz),
    }


def _material_to_3d(material_str: str, hex_color: str) -> dict:
    """Convert VPE material string to Three.js material properties."""
    presets = {
        "polished_metal": {"metalness": 0.85, "roughness": 0.15},
        "brushed_metal": {"metalness": 0.75, "roughness": 0.35},
        "textured_metal": {"metalness": 0.7, "roughness": 0.5},
        "carbon_fiber": {"metalness": 0.3, "roughness": 0.4},
        "glossy_plastic": {"metalness": 0.05, "roughness": 0.2},
        "matte_plastic": {"metalness": 0.0, "roughness": 0.7},
        "white_plastic": {"metalness": 0.0, "roughness": 0.6},
        "dark_composite": {"metalness": 0.2, "roughness": 0.5},
        "composite": {"metalness": 0.15, "roughness": 0.55},
        "fabric_or_soft": {"metalness": 0.0, "roughness": 0.9},
    }
    props = presets.get(material_str, {"metalness": 0.3, "roughness": 0.5})
    props["color"] = hex_color
    return props


def _prim(ptype, geo, mat, pos=(0, 0, 0), rot=(0, 0, 0), name=""):
    return {
        "type": ptype,
        "geometry": geo,
        "material": mat,
        "position": list(pos),
        "rotation": list(rot),
        "name": name,
    }


# ═══════════════════════════════════════════
#  DRONE — body + N arms + N rotors
# ═══════════════════════════════════════════

def _gen_drone(sx, sy, sz, mat, accent, rc, lc, cls, phys):
    parts = []
    rotors = max(rc, 4)
    body_w = sx * 0.5
    body_h = sy * 0.2
    body_d = sz * 0.5

    # Central body
    parts.append(_prim("box", {"w": body_w, "h": body_h, "d": body_d}, mat, name="body"))

    # Arms + rotors arranged radially
    arm_len = max(sx, sz) * 0.45
    rotor_r = arm_len * 0.35

    for i in range(rotors):
        angle = (i / rotors) * 3.14159 * 2
        ax = arm_len * _cos(angle)
        az = arm_len * _sin(angle)

        # Arm
        parts.append(_prim("cylinder", {"rt": 0.04, "rb": 0.04, "h": arm_len * 0.9},
                           accent, (ax * 0.5, 0, az * 0.5),
                           (0, 0, _atan2(az, ax) + 1.5708), name=f"arm_{i}"))

        # Rotor ring
        parts.append(_prim("torus", {"r": rotor_r, "tube": 0.03},
                           {**accent, "emissive": accent["color"], "emissiveIntensity": 0.3},
                           (ax, body_h * 0.6, az), (1.5708, 0, 0), name=f"rotor_{i}"))

    # Camera/gimbal (bottom)
    parts.append(_prim("sphere", {"r": body_w * 0.15},
                        {"color": "#111111", "metalness": 0.5, "roughness": 0.3},
                        (0, -body_h * 0.6, 0), name="camera"))

    # Landing gear
    for lx in [-body_w * 0.4, body_w * 0.4]:
        parts.append(_prim("cylinder", {"rt": 0.02, "rb": 0.02, "h": body_h * 1.5},
                           accent, (lx, -body_h * 0.8, 0), name="landing_gear"))

    return parts


# ═══════════════════════════════════════════
#  GROUND ROBOT — chassis + wheels
# ═══════════════════════════════════════════

def _gen_ground_robot(sx, sy, sz, mat, accent, rc, lc, cls, phys):
    parts = []
    wheels = max(rc, 4)
    chassis_w = sx * 0.6
    chassis_h = sy * 0.2
    chassis_d = sz * 0.4

    # Chassis body
    parts.append(_prim("box", {"w": chassis_w, "h": chassis_h, "d": chassis_d}, mat, (0, chassis_h, 0), name="chassis"))

    # Top cover
    parts.append(_prim("box", {"w": chassis_w * 0.8, "h": chassis_h * 0.6, "d": chassis_d * 0.7},
                        accent, (0, chassis_h * 2, 0), name="cover"))

    # Wheels
    wheel_r = sy * 0.15
    wheel_w = 0.08
    positions = []
    if wheels == 4:
        positions = [(-chassis_w * 0.45, 0, chassis_d * 0.35), (chassis_w * 0.45, 0, chassis_d * 0.35),
                     (-chassis_w * 0.45, 0, -chassis_d * 0.35), (chassis_w * 0.45, 0, -chassis_d * 0.35)]
    elif wheels == 6:
        for side in [-1, 1]:
            for zp in [-0.35, 0, 0.35]:
                positions.append((side * chassis_w * 0.5, 0, chassis_d * zp))
    else:
        for i in range(wheels):
            angle = (i / wheels) * 3.14159 * 2
            positions.append((chassis_w * 0.45 * _cos(angle), 0, chassis_d * 0.35 * _sin(angle)))

    for i, (wx, wy, wz) in enumerate(positions):
        parts.append(_prim("cylinder", {"rt": wheel_r, "rb": wheel_r, "h": wheel_w},
                           {"color": "#222222", "metalness": 0.3, "roughness": 0.8},
                           (wx, wy + wheel_r * 0.5, wz), (0, 0, 1.5708), name=f"wheel_{i}"))

    # Sensor on top
    parts.append(_prim("cylinder", {"rt": 0.06, "rb": 0.08, "h": 0.12},
                        {"color": "#00b4d8", "emissive": "#00b4d8", "emissiveIntensity": 0.4, "metalness": 0.3, "roughness": 0.3},
                        (0, chassis_h * 2.8, 0), name="sensor"))

    return parts


# ═══════════════════════════════════════════
#  ROBOT ARM / INDUSTRIAL — base + joints + segments
# ═══════════════════════════════════════════

def _gen_arm(sx, sy, sz, mat, accent, rc, lc, cls, phys):
    parts = []
    height = max(sy, sz) * 0.8
    joints = max(lc, 3)
    seg_len = height / max(joints, 1) * 0.9

    # Base platform
    parts.append(_prim("cylinder", {"rt": sx * 0.25, "rb": sx * 0.3, "h": 0.15},
                        mat, name="base"))

    # Build arm segments with alternating joints
    y_pos = 0.15
    for i in range(joints):
        # Joint sphere
        joint_r = 0.08 + (joints - i) * 0.01
        parts.append(_prim("sphere", {"r": joint_r},
                           {**accent, "emissive": accent["color"], "emissiveIntensity": 0.2},
                           (0, y_pos, 0), name=f"joint_{i}"))

        # Arm segment
        seg_w = 0.1 - i * 0.01
        parts.append(_prim("box", {"w": seg_w, "h": seg_len, "d": seg_w},
                           mat if i % 2 == 0 else accent,
                           (0, y_pos + seg_len * 0.5, 0), name=f"segment_{i}"))
        y_pos += seg_len

    # End effector
    parts.append(_prim("sphere", {"r": 0.1},
                        {"color": "#10b981", "emissive": "#10b981", "emissiveIntensity": 0.4, "metalness": 0.2, "roughness": 0.3},
                        (0, y_pos, 0), name="end_effector"))

    return parts


# ═══════════════════════════════════════════
#  HUMANOID — torso + head + arms + legs
# ═══════════════════════════════════════════

def _gen_humanoid(sx, sy, sz, mat, accent, rc, lc, cls, phys):
    parts = []
    h = max(sy, sz) * 0.7

    # Torso
    torso_h = h * 0.35
    parts.append(_prim("box", {"w": sx * 0.3, "h": torso_h, "d": sz * 0.2}, mat, (0, h * 0.45, 0), name="torso"))

    # Head
    parts.append(_prim("sphere", {"r": sx * 0.1}, accent, (0, h * 0.7, 0), name="head"))

    # Eyes
    for ex in [-0.04, 0.04]:
        parts.append(_prim("sphere", {"r": 0.02},
                           {"color": "#00b4d8", "emissive": "#00b4d8", "emissiveIntensity": 0.6, "metalness": 0, "roughness": 0.3},
                           (ex, h * 0.72, sx * 0.08), name="eye"))

    # Arms
    arm_len = h * 0.3
    for side in [-1, 1]:
        # Shoulder
        parts.append(_prim("sphere", {"r": 0.06}, accent, (side * sx * 0.2, h * 0.58, 0), name=f"shoulder"))
        # Upper arm
        parts.append(_prim("box", {"w": 0.06, "h": arm_len * 0.5, "d": 0.06},
                           mat, (side * sx * 0.22, h * 0.45, 0), name=f"upper_arm"))
        # Forearm
        parts.append(_prim("box", {"w": 0.05, "h": arm_len * 0.5, "d": 0.05},
                           accent, (side * sx * 0.22, h * 0.3, 0), name=f"forearm"))
        # Hand
        parts.append(_prim("sphere", {"r": 0.04},
                           {"color": "#999999", "metalness": 0.3, "roughness": 0.5},
                           (side * sx * 0.22, h * 0.2, 0), name=f"hand"))

    # Legs
    leg_len = h * 0.35
    for side in [-1, 1]:
        # Hip joint
        parts.append(_prim("sphere", {"r": 0.05}, accent, (side * sx * 0.08, h * 0.25, 0), name="hip"))
        # Upper leg
        parts.append(_prim("box", {"w": 0.07, "h": leg_len * 0.5, "d": 0.07},
                           mat, (side * sx * 0.08, h * 0.14, 0), name="thigh"))
        # Lower leg
        parts.append(_prim("box", {"w": 0.06, "h": leg_len * 0.5, "d": 0.06},
                           accent, (side * sx * 0.08, h * 0.02, 0), name="shin"))
        # Foot
        parts.append(_prim("box", {"w": 0.08, "h": 0.03, "d": 0.12},
                           {"color": "#333333", "metalness": 0.4, "roughness": 0.5},
                           (side * sx * 0.08, -0.02, 0.02), name="foot"))

    return parts


# ═══════════════════════════════════════════
#  LEGGED (quadruped, hexapod, spider)
# ═══════════════════════════════════════════

def _gen_legged(sx, sy, sz, mat, accent, rc, lc, cls, phys):
    parts = []
    dtype = cls["device_type"]

    # Determine leg count from type name
    legs = 4
    if "hexapod" in dtype or "six" in dtype:
        legs = 6
    elif "spider" in dtype or "eight" in dtype or "octo" in dtype:
        legs = 8
    elif "snake" in dtype or "serpent" in dtype:
        return _gen_snake(sx, sy, sz, mat, accent)

    body_w = sx * 0.35
    body_h = sy * 0.12
    body_d = sz * 0.5

    # Body
    parts.append(_prim("box", {"w": body_w, "h": body_h, "d": body_d}, mat, (0, sy * 0.2, 0), name="body"))

    # Head
    parts.append(_prim("sphere", {"r": body_w * 0.4}, accent, (0, sy * 0.25, body_d * 0.55), name="head"))

    # Eyes
    for ex in [-0.05, 0.05]:
        parts.append(_prim("sphere", {"r": 0.025},
                           {"color": "#00b4d8", "emissive": "#00b4d8", "emissiveIntensity": 0.5, "metalness": 0, "roughness": 0.3},
                           (ex, sy * 0.28, body_d * 0.7), name="eye"))

    # Legs
    leg_upper = sy * 0.15
    leg_lower = sy * 0.2
    for i in range(legs):
        # Distribute legs along body length
        z_frac = (i % (legs // 2)) / max(legs // 2 - 1, 1) - 0.5
        side = -1 if i < legs // 2 else 1
        lz = z_frac * body_d * 0.8
        lx = side * body_w * 0.55

        # Hip joint
        parts.append(_prim("sphere", {"r": 0.04}, accent, (lx, sy * 0.18, lz), name=f"hip_{i}"))
        # Upper leg (angled outward)
        parts.append(_prim("cylinder", {"rt": 0.03, "rb": 0.035, "h": leg_upper},
                           mat, (lx * 1.3, sy * 0.12, lz), (0, 0, side * 0.4), name=f"upper_leg_{i}"))
        # Knee
        parts.append(_prim("sphere", {"r": 0.03}, accent, (lx * 1.5, sy * 0.05, lz), name=f"knee_{i}"))
        # Lower leg
        parts.append(_prim("cylinder", {"rt": 0.025, "rb": 0.03, "h": leg_lower},
                           accent, (lx * 1.5, -sy * 0.03, lz), name=f"lower_leg_{i}"))
        # Foot
        parts.append(_prim("sphere", {"r": 0.025},
                           {"color": "#333333", "metalness": 0.5, "roughness": 0.4},
                           (lx * 1.5, -sy * 0.1, lz), name=f"foot_{i}"))

    return parts


def _gen_snake(sx, sy, sz, mat, accent):
    """Snake/serpentine robot — chain of segments."""
    parts = []
    segments = 10
    seg_len = sz * 0.12
    for i in range(segments):
        z = (i - segments / 2) * seg_len * 1.1
        r = sx * 0.08 * (1 - i * 0.03)
        m = mat if i % 2 == 0 else accent
        parts.append(_prim("sphere", {"r": max(r, 0.04)}, m, (0, r, z), name=f"segment_{i}"))
        if i < segments - 1:
            parts.append(_prim("cylinder", {"rt": r * 0.5, "rb": r * 0.5, "h": seg_len * 0.4},
                               accent, (0, r, z + seg_len * 0.55), (1.5708, 0, 0), name=f"joint_{i}"))
    # Head
    parts.append(_prim("sphere", {"r": sx * 0.1},
                        {**accent, "emissive": accent["color"], "emissiveIntensity": 0.2},
                        (0, sx * 0.08, (segments / 2) * seg_len * 1.1), name="head"))
    return parts


# ═══════════════════════════════════════════
#  HOME ROBOT (vacuum, mop, pool cleaner)
# ═══════════════════════════════════════════

def _gen_home_robot(sx, sy, sz, mat, accent, rc, lc, cls, phys):
    parts = []
    diameter = max(sx, sz) * 0.4
    height = sy * 0.1

    # Main disc body
    parts.append(_prim("cylinder", {"rt": diameter, "rb": diameter, "h": height},
                        mat, (0, height * 0.5, 0), name="body"))

    # Top panel (slightly smaller)
    parts.append(_prim("cylinder", {"rt": diameter * 0.85, "rb": diameter * 0.85, "h": 0.02},
                        accent, (0, height, 0), name="top_panel"))

    # Sensor turret (LiDAR bump)
    parts.append(_prim("cylinder", {"rt": diameter * 0.15, "rb": diameter * 0.18, "h": height * 0.5},
                        {"color": "#222222", "metalness": 0.5, "roughness": 0.4},
                        (0, height * 1.2, diameter * 0.15), name="sensor"))

    # Bumper ring
    parts.append(_prim("torus", {"r": diameter * 0.95, "tube": 0.025},
                        {"color": "#333333", "metalness": 0.3, "roughness": 0.6},
                        (0, height * 0.3, 0), (1.5708, 0, 0), name="bumper"))

    # Status LED
    parts.append(_prim("sphere", {"r": 0.03},
                        {"color": "#10b981", "emissive": "#10b981", "emissiveIntensity": 0.6, "metalness": 0, "roughness": 0.3},
                        (0, height * 1.1, -diameter * 0.5), name="led"))

    return parts


# ═══════════════════════════════════════════
#  SERVICE ROBOT (butler, telepresence)
# ═══════════════════════════════════════════

def _gen_service_robot(sx, sy, sz, mat, accent, rc, lc, cls, phys):
    parts = []
    h = max(sy, sz) * 0.6

    # Base (round platform with wheels)
    base_r = sx * 0.2
    parts.append(_prim("cylinder", {"rt": base_r, "rb": base_r * 1.1, "h": 0.08},
                        {"color": "#333333", "metalness": 0.4, "roughness": 0.5}, name="base"))

    # Body column
    parts.append(_prim("cylinder", {"rt": sx * 0.08, "rb": sx * 0.1, "h": h * 0.5},
                        mat, (0, h * 0.3, 0), name="column"))

    # Tray / display area
    parts.append(_prim("cylinder", {"rt": sx * 0.2, "rb": sx * 0.15, "h": 0.04},
                        accent, (0, h * 0.55, 0), name="tray"))

    # Head / screen
    parts.append(_prim("box", {"w": sx * 0.25, "h": sy * 0.12, "d": 0.04},
                        {"color": "#111111", "metalness": 0.3, "roughness": 0.3},
                        (0, h * 0.7, 0), name="screen"))

    # Screen glow
    parts.append(_prim("box", {"w": sx * 0.22, "h": sy * 0.1, "d": 0.01},
                        {"color": "#00b4d8", "emissive": "#00b4d8", "emissiveIntensity": 0.4, "metalness": 0, "roughness": 0.3},
                        (0, h * 0.7, 0.025), name="screen_glow"))

    return parts


# ═══════════════════════════════════════════
#  WAREHOUSE (AMR, forklift, sorting)
# ═══════════════════════════════════════════

def _gen_warehouse(sx, sy, sz, mat, accent, rc, lc, cls, phys):
    parts = []
    chassis_w = sx * 0.5
    chassis_h = sy * 0.15
    chassis_d = sz * 0.5

    # Main chassis
    parts.append(_prim("box", {"w": chassis_w, "h": chassis_h, "d": chassis_d},
                        mat, (0, chassis_h, 0), name="chassis"))

    # Shelf/lift platform
    parts.append(_prim("box", {"w": chassis_w * 0.9, "h": 0.03, "d": chassis_d * 0.9},
                        accent, (0, chassis_h * 2.5, 0), name="platform"))

    # Lift columns
    for cx in [-chassis_w * 0.4, chassis_w * 0.4]:
        parts.append(_prim("box", {"w": 0.05, "h": chassis_h * 2, "d": 0.05},
                           {"color": "#ffaa00", "metalness": 0.4, "roughness": 0.5},
                           (cx, chassis_h * 1.5, -chassis_d * 0.4), name="lift_column"))

    # Wheels (4)
    wheel_r = sy * 0.08
    for wx, wz in [(-chassis_w * 0.4, chassis_d * 0.35), (chassis_w * 0.4, chassis_d * 0.35),
                   (-chassis_w * 0.4, -chassis_d * 0.35), (chassis_w * 0.4, -chassis_d * 0.35)]:
        parts.append(_prim("cylinder", {"rt": wheel_r, "rb": wheel_r, "h": 0.06},
                           {"color": "#222222", "metalness": 0.3, "roughness": 0.8},
                           (wx, wheel_r * 0.5, wz), (0, 0, 1.5708), name="wheel"))

    # Safety beacon
    parts.append(_prim("cylinder", {"rt": 0.04, "rb": 0.04, "h": 0.08},
                        {"color": "#ff6600", "emissive": "#ff6600", "emissiveIntensity": 0.5, "metalness": 0, "roughness": 0.3},
                        (0, chassis_h * 3, 0), name="beacon"))

    return parts


# ═══════════════════════════════════════════
#  MEDICAL (surgical, rehab, wheelchair)
# ═══════════════════════════════════════════

def _gen_medical(sx, sy, sz, mat, accent, rc, lc, cls, phys):
    parts = []
    # White/clean aesthetic
    med_mat = {"color": "#e8e8e8", "metalness": 0.3, "roughness": 0.4}
    med_accent = {"color": "#00b4d8", "metalness": 0.5, "roughness": 0.3}

    # Base
    parts.append(_prim("cylinder", {"rt": sx * 0.2, "rb": sx * 0.25, "h": 0.1}, med_mat, name="base"))

    # Column
    h = max(sy, sz) * 0.5
    parts.append(_prim("cylinder", {"rt": 0.05, "rb": 0.06, "h": h * 0.6},
                        med_mat, (0, h * 0.35, 0), name="column"))

    # Arm segments (surgical arm style)
    parts.append(_prim("box", {"w": 0.06, "h": h * 0.3, "d": 0.06},
                        med_accent, (0, h * 0.7, 0), name="arm_1"))
    parts.append(_prim("sphere", {"r": 0.04}, med_accent, (0, h * 0.85, 0), name="joint"))
    parts.append(_prim("box", {"w": 0.05, "h": h * 0.25, "d": 0.05},
                        med_mat, (0.05, h * 0.95, 0), (0, 0, -0.3), name="arm_2"))

    # Tool tip
    parts.append(_prim("cone", {"r": 0.03, "h": 0.08},
                        {"color": "#00b4d8", "emissive": "#00b4d8", "emissiveIntensity": 0.3, "metalness": 0.6, "roughness": 0.2},
                        (0.12, h * 1.05, 0), name="tool_tip"))

    return parts


# ═══════════════════════════════════════════
#  SMART LIGHT
# ═══════════════════════════════════════════

def _gen_smart_light(sx, sy, sz, mat, accent, rc, lc, cls, phys):
    parts = []
    bulb_r = max(sx, sz) * 0.2

    # Bulb
    parts.append(_prim("sphere", {"r": bulb_r},
                        {"color": "#ffd700", "emissive": "#ffd700", "emissiveIntensity": 0.5, "metalness": 0.05, "roughness": 0.3},
                        (0, bulb_r, 0), name="bulb"))

    # Base/socket
    parts.append(_prim("cylinder", {"rt": bulb_r * 0.4, "rb": bulb_r * 0.35, "h": bulb_r * 0.6},
                        {"color": "#888888", "metalness": 0.6, "roughness": 0.3},
                        (0, -bulb_r * 0.1, 0), name="socket"))

    # Light rays
    for i in range(6):
        angle = (i / 6) * 3.14159 * 2
        rx = bulb_r * 1.5 * _cos(angle)
        rz = bulb_r * 1.5 * _sin(angle)
        parts.append(_prim("cylinder", {"rt": 0.015, "rb": 0.015, "h": bulb_r * 1.2},
                           {"color": "#ffd700", "emissive": "#ffd700", "emissiveIntensity": 0.3, "metalness": 0, "roughness": 0.5, "opacity": 0.5},
                           (rx * 0.5, bulb_r, rz * 0.5), (0, 0, _atan2(rz, rx) + 1.5708), name=f"ray_{i}"))

    return parts


# ═══════════════════════════════════════════
#  SMART DEVICE (speaker, thermostat)
# ═══════════════════════════════════════════

def _gen_smart_device(sx, sy, sz, mat, accent, rc, lc, cls, phys):
    parts = []
    r = max(sx, sz) * 0.18
    h = sy * 0.3

    # Body (cylindrical or box based on shape)
    parts.append(_prim("cylinder", {"rt": r, "rb": r * 1.05, "h": h}, mat, (0, h * 0.5, 0), name="body"))

    # Top surface
    parts.append(_prim("cylinder", {"rt": r * 0.95, "rb": r * 0.95, "h": 0.01},
                        accent, (0, h, 0), name="top"))

    # LED ring
    parts.append(_prim("torus", {"r": r * 0.7, "tube": 0.015},
                        {"color": "#00b4d8", "emissive": "#00b4d8", "emissiveIntensity": 0.5, "metalness": 0, "roughness": 0.3},
                        (0, h * 1.01, 0), (1.5708, 0, 0), name="led_ring"))

    return parts


# ═══════════════════════════════════════════
#  MARINE (ROV, submarine, boat)
# ═══════════════════════════════════════════

def _gen_marine(sx, sy, sz, mat, accent, rc, lc, cls, phys):
    parts = []
    body_len = sz * 0.6
    body_r = max(sx, sy) * 0.12

    # Torpedo-shaped body
    parts.append(_prim("cylinder", {"rt": body_r * 0.6, "rb": body_r, "h": body_len},
                        mat, (0, 0, 0), (1.5708, 0, 0), name="hull"))

    # Nose cone
    parts.append(_prim("sphere", {"r": body_r},
                        accent, (0, 0, body_len * 0.5), name="nose"))

    # Thrusters
    thruster_r = body_r * 0.3
    for i, (tx, ty) in enumerate([(-body_r * 1.2, 0), (body_r * 1.2, 0), (0, body_r * 1.2), (0, -body_r * 1.2)]):
        parts.append(_prim("torus", {"r": thruster_r, "tube": 0.02},
                           {"color": "#ff6600", "emissive": "#ff6600", "emissiveIntensity": 0.3, "metalness": 0.3, "roughness": 0.4},
                           (tx, ty, -body_len * 0.45), name=f"thruster_{i}"))

    # Camera dome
    parts.append(_prim("sphere", {"r": body_r * 0.35},
                        {"color": "#111111", "metalness": 0.5, "roughness": 0.2, "opacity": 0.7},
                        (0, body_r * 0.7, body_len * 0.2), name="camera_dome"))

    # Light
    parts.append(_prim("sphere", {"r": 0.04},
                        {"color": "#ffffff", "emissive": "#ffffff", "emissiveIntensity": 0.6, "metalness": 0, "roughness": 0.3},
                        (0, body_r * 0.5, body_len * 0.45), name="light"))

    return parts


# ═══════════════════════════════════════════
#  SPACE (rover, satellite servicing)
# ═══════════════════════════════════════════

def _gen_space(sx, sy, sz, mat, accent, rc, lc, cls, phys):
    parts = []
    body_w = sx * 0.4
    body_h = sy * 0.15
    body_d = sz * 0.35

    # Main body (gold foil style)
    space_mat = {"color": "#c8a84e", "metalness": 0.8, "roughness": 0.25}
    parts.append(_prim("box", {"w": body_w, "h": body_h, "d": body_d}, space_mat, (0, body_h * 1.5, 0), name="body"))

    # Solar panels
    panel_w = body_w * 1.5
    for side in [-1, 1]:
        parts.append(_prim("box", {"w": panel_w, "h": 0.02, "d": body_d * 0.6},
                           {"color": "#1a237e", "metalness": 0.2, "roughness": 0.6},
                           (side * (body_w * 0.5 + panel_w * 0.5), body_h * 1.5, 0), name=f"solar_panel"))

    # Antenna
    parts.append(_prim("cylinder", {"rt": 0.015, "rb": 0.015, "h": body_h * 3},
                        {"color": "#cccccc", "metalness": 0.7, "roughness": 0.3},
                        (0, body_h * 3.5, 0), name="antenna"))
    parts.append(_prim("cone", {"r": body_w * 0.2, "h": 0.08},
                        {"color": "#cccccc", "metalness": 0.7, "roughness": 0.3},
                        (0, body_h * 5, 0), (3.14159, 0, 0), name="dish"))

    # Wheels (6 — rocker bogie style)
    wheel_r = sy * 0.08
    for wz_frac in [-0.3, 0, 0.3]:
        for side in [-1, 1]:
            parts.append(_prim("cylinder", {"rt": wheel_r, "rb": wheel_r, "h": 0.04},
                               {"color": "#888888", "metalness": 0.5, "roughness": 0.6},
                               (side * body_w * 0.5, wheel_r * 0.5, body_d * wz_frac), (0, 0, 1.5708), name="wheel"))

    return parts


# ═══════════════════════════════════════════
#  EXTREME (mining, firefighting)
# ═══════════════════════════════════════════

def _gen_extreme(sx, sy, sz, mat, accent, rc, lc, cls, phys):
    parts = []
    # Heavy-duty, chunky design
    chassis_w = sx * 0.5
    chassis_h = sy * 0.2
    chassis_d = sz * 0.5

    # Armored chassis
    armor_mat = {"color": "#5c4033", "metalness": 0.6, "roughness": 0.5}
    parts.append(_prim("box", {"w": chassis_w, "h": chassis_h, "d": chassis_d},
                        armor_mat, (0, chassis_h * 1.5, 0), name="chassis"))

    # Tracks (instead of wheels)
    track_h = chassis_h * 0.8
    for side in [-1, 1]:
        parts.append(_prim("box", {"w": 0.08, "h": track_h, "d": chassis_d * 1.1},
                           {"color": "#222222", "metalness": 0.3, "roughness": 0.9},
                           (side * chassis_w * 0.55, track_h * 0.5, 0), name=f"track"))

    # Water cannon / tool arm
    parts.append(_prim("cylinder", {"rt": 0.06, "rb": 0.08, "h": chassis_h * 3},
                        {"color": "#cc0000", "metalness": 0.5, "roughness": 0.4},
                        (0, chassis_h * 3, chassis_d * 0.3), (0.5, 0, 0), name="tool_arm"))

    # Nozzle
    parts.append(_prim("cone", {"r": 0.06, "h": 0.1},
                        {"color": "#999999", "metalness": 0.6, "roughness": 0.3},
                        (0, chassis_h * 4.2, chassis_d * 0.5), (0.5, 0, 0), name="nozzle"))

    # Warning lights
    for lx in [-chassis_w * 0.3, chassis_w * 0.3]:
        parts.append(_prim("sphere", {"r": 0.04},
                           {"color": "#ff3300", "emissive": "#ff3300", "emissiveIntensity": 0.6, "metalness": 0, "roughness": 0.3},
                           (lx, chassis_h * 2.8, 0), name="warning_light"))

    return parts


# ═══════════════════════════════════════════
#  GENERIC
# ═══════════════════════════════════════════

def _gen_generic(sx, sy, sz, mat, accent, rc, lc, cls, phys):
    parts = []
    parts.append(_prim("box", {"w": sx * 0.4, "h": sy * 0.4, "d": sz * 0.4}, mat, name="body"))
    parts.append(_prim("sphere", {"r": max(sx, sy, sz) * 0.05},
                        {"color": "#00b4d8", "emissive": "#00b4d8", "emissiveIntensity": 0.4, "metalness": 0, "roughness": 0.3},
                        (0, sy * 0.25, 0), name="indicator"))
    return parts


# ── Math helpers (avoid numpy dep) ──

import math

def _cos(a): return math.cos(a)
def _sin(a): return math.sin(a)
def _atan2(y, x): return math.atan2(y, x)
