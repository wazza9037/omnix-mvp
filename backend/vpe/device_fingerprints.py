"""
OMNIX Visual Physics Engine — 100 Device Fingerprints

Every device type has:
  - required: must-match features or instant disqualification
  - positive: features that earn score when matched
  - negative: features that subtract score when present but wrong
  - structural_hints: component patterns that give big boosts

Categories:
  1. Aerial (drones, UAVs)           — 15 types
  2. Ground Robots                    — 15 types
  3. Manipulators (arms)              — 12 types
  4. Humanoid & Legged               — 10 types
  5. Home & Service Robots            — 12 types
  6. Industrial & Warehouse           — 10 types
  7. Medical & Assistive              — 8 types
  8. Smart Devices (IoT)              — 10 types
  9. Marine & Underwater              — 4 types
  10. Space & Extreme                 — 4 types
  ─────────────────────────────
  Total: 100 device types
"""

DEVICE_FINGERPRINTS = {

    # ═══════════════════════════════════════════
    #  1. AERIAL — Drones & UAVs (15)
    # ═══════════════════════════════════════════

    "quadcopter_drone": {
        "category": "drone", "description": "Quadcopter drone with 4 rotors",
        "required": {"has_rotary_elements": True, "min_rotary_count": 3},
        "positive": {
            "aspect_ratio": {"range": (0.7, 1.4), "weight": 2.0},
            "symmetry_score": {"range": (0.6, 1.0), "weight": 2.5},
            "solidity": {"range": (0.2, 0.65), "weight": 2.0},
            "convex_defects_count": {"range": (2, 20), "weight": 2.0},
            "component_symmetry": {"range": (0.5, 1.0), "weight": 1.5},
        },
        "negative": {
            "circularity": {"above": 0.8, "penalty": 3.0},
            "solidity": {"above": 0.85, "penalty": 2.5},
        },
        "structural_hints": {"rotary_min": 4, "boost": 6.0},
    },

    "hexacopter_drone": {
        "category": "drone", "description": "Hexacopter drone with 6 rotors",
        "required": {"has_rotary_elements": True, "min_rotary_count": 5},
        "positive": {
            "aspect_ratio": {"range": (0.7, 1.4), "weight": 2.0},
            "symmetry_score": {"range": (0.6, 1.0), "weight": 2.5},
            "component_symmetry": {"range": (0.5, 1.0), "weight": 2.0},
            "radial_symmetry": {"range": (0.5, 1.0), "weight": 2.0},
        },
        "negative": {
            "circularity": {"above": 0.8, "penalty": 3.0},
            "solidity": {"above": 0.85, "penalty": 2.0},
        },
        "structural_hints": {"rotary_min": 6, "boost": 7.0},
    },

    "octocopter_drone": {
        "category": "drone", "description": "Octocopter drone with 8 rotors — heavy-lift platform",
        "required": {"has_rotary_elements": True, "min_rotary_count": 7},
        "positive": {
            "symmetry_score": {"range": (0.6, 1.0), "weight": 2.5},
            "radial_symmetry": {"range": (0.5, 1.0), "weight": 2.5},
        },
        "negative": {"circularity": {"above": 0.8, "penalty": 2.5}},
        "structural_hints": {"rotary_min": 8, "boost": 8.0},
    },

    "fixed_wing_drone": {
        "category": "drone", "description": "Fixed-wing UAV — airplane-style long-range drone",
        "required": {"aspect_ratio_min": 1.5},
        "positive": {
            "aspect_ratio": {"range": (1.6, 5.0), "weight": 3.5},
            "symmetry_score": {"range": (0.5, 1.0), "weight": 2.0},
            "elongation": {"range": (0.15, 0.45), "weight": 2.5},
            "solidity": {"range": (0.4, 0.8), "weight": 1.5},
        },
        "negative": {
            "has_rotary_elements": {"equals": True, "penalty": 1.5},
            "circularity": {"above": 0.6, "penalty": 3.0},
        },
        "structural_hints": {},
    },

    "vtol_drone": {
        "category": "drone", "description": "VTOL hybrid drone — vertical takeoff with fixed wings",
        "required": {"has_rotary_elements": True, "aspect_ratio_min": 1.3},
        "positive": {
            "aspect_ratio": {"range": (1.3, 3.5), "weight": 2.5},
            "symmetry_score": {"range": (0.5, 1.0), "weight": 2.0},
        },
        "negative": {"circularity": {"above": 0.7, "penalty": 2.5}},
        "structural_hints": {"rotary_min": 2, "boost": 3.0},
    },

    "racing_drone": {
        "category": "drone", "description": "FPV racing drone — compact high-speed quadcopter",
        "required": {"has_rotary_elements": True, "min_rotary_count": 3},
        "positive": {
            "aspect_ratio": {"range": (0.8, 1.3), "weight": 2.0},
            "complexity": {"range": (20, 60), "weight": 2.0},
            "solidity": {"range": (0.15, 0.5), "weight": 2.5},
        },
        "negative": {"solidity": {"above": 0.7, "penalty": 2.5}},
        "structural_hints": {"rotary_min": 4, "boost": 5.0},
    },

    "camera_drone": {
        "category": "drone", "description": "Photography/videography drone with gimbal camera",
        "required": {"has_rotary_elements": True, "min_rotary_count": 2},
        "positive": {
            "solidity": {"range": (0.3, 0.65), "weight": 2.0},
            "symmetry_score": {"range": (0.4, 1.0), "weight": 2.0},
            "complexity": {"range": (20, 80), "weight": 1.5},
        },
        "negative": {"circularity": {"above": 0.75, "penalty": 2.5}},
        "structural_hints": {"rotary_min": 3, "boost": 4.0},
    },

    "nano_drone": {
        "category": "drone", "description": "Nano/micro drone — palm-sized indoor flyer",
        "required": {"has_rotary_elements": True},
        "positive": {
            "aspect_ratio": {"range": (0.8, 1.3), "weight": 2.0},
            "complexity": {"range": (8, 30), "weight": 2.0},
        },
        "negative": {"solidity": {"above": 0.85, "penalty": 2.0}},
        "structural_hints": {"rotary_min": 2, "boost": 3.0},
    },

    "delivery_drone": {
        "category": "drone", "description": "Package delivery drone with cargo bay",
        "required": {"has_rotary_elements": True, "min_rotary_count": 3},
        "positive": {
            "solidity": {"range": (0.35, 0.7), "weight": 2.0},
            "has_panel_elements": {"equals": True, "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"rotary_min": 4, "boost": 4.0},
    },

    "agricultural_drone": {
        "category": "drone", "description": "Agricultural spraying drone — large multi-rotor with tanks",
        "required": {"has_rotary_elements": True, "min_rotary_count": 3},
        "positive": {
            "aspect_ratio": {"range": (0.7, 1.5), "weight": 1.5},
            "solidity": {"range": (0.3, 0.7), "weight": 1.5},
        },
        "negative": {},
        "structural_hints": {"rotary_min": 4, "boost": 4.0},
    },

    "tethered_drone": {
        "category": "drone", "description": "Tethered drone — persistent aerial platform with power cable",
        "required": {"has_rotary_elements": True},
        "positive": {
            "has_linear_elements": {"equals": True, "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"rotary_min": 3, "boost": 3.5},
    },

    "coaxial_drone": {
        "category": "drone", "description": "Coaxial rotor drone — stacked dual-rotor helicopter style",
        "required": {"has_rotary_elements": True},
        "positive": {
            "aspect_ratio": {"range": (0.5, 1.0), "weight": 2.0},
            "circularity": {"range": (0.3, 0.7), "weight": 1.5},
        },
        "negative": {},
        "structural_hints": {"rotary_min": 2, "boost": 3.0},
    },

    "single_rotor_helicopter": {
        "category": "drone", "description": "RC helicopter — single main rotor with tail rotor",
        "required": {"has_rotary_elements": True},
        "positive": {
            "aspect_ratio": {"range": (1.2, 3.0), "weight": 2.5},
            "elongation": {"range": (0.2, 0.5), "weight": 2.0},
        },
        "negative": {"circularity": {"above": 0.6, "penalty": 2.0}},
        "structural_hints": {"rotary_min": 1, "boost": 2.0},
    },

    "flying_wing_drone": {
        "category": "drone", "description": "Flying wing — tailless blended-wing UAV",
        "required": {"aspect_ratio_min": 2.0},
        "positive": {
            "aspect_ratio": {"range": (2.0, 6.0), "weight": 3.5},
            "solidity": {"range": (0.5, 0.9), "weight": 2.0},
            "symmetry_score": {"range": (0.6, 1.0), "weight": 2.0},
        },
        "negative": {"has_rotary_elements": {"equals": True, "penalty": 2.0}},
        "structural_hints": {},
    },

    "blimp_drone": {
        "category": "drone", "description": "Blimp/airship drone — lighter-than-air autonomous vehicle",
        "required": {},
        "positive": {
            "aspect_ratio": {"range": (1.5, 4.0), "weight": 2.5},
            "circularity": {"range": (0.4, 0.8), "weight": 2.0},
            "solidity": {"range": (0.7, 1.0), "weight": 2.0},
            "texture_homogeneity": {"range": (0.5, 1.0), "weight": 2.0},
        },
        "negative": {"complexity": {"above": 30, "penalty": 2.0}},
        "structural_hints": {},
    },

    # ═══════════════════════════════════════════
    #  2. GROUND ROBOTS (15)
    # ═══════════════════════════════════════════

    "wheeled_robot": {
        "category": "ground_robot", "description": "Wheeled mobile robot — general purpose rover",
        "required": {"has_rotary_elements": True, "has_linear_elements": True},
        "positive": {
            "aspect_ratio": {"range": (0.9, 2.5), "weight": 2.0},
            "solidity": {"range": (0.5, 0.85), "weight": 1.5},
            "vertical_bias": {"range": (0.5, 0.8), "weight": 2.0},
            "has_panel_elements": {"equals": True, "weight": 1.5},
        },
        "negative": {"circularity": {"above": 0.8, "penalty": 2.0}},
        "structural_hints": {"rotary_min": 2, "linear_min": 3, "boost": 3.0},
    },

    "tracked_robot": {
        "category": "ground_robot", "description": "Tracked robot — tank-tread ground vehicle",
        "required": {"has_linear_elements": True},
        "positive": {
            "aspect_ratio": {"range": (1.2, 3.0), "weight": 2.5},
            "solidity": {"range": (0.5, 0.85), "weight": 2.0},
            "has_panel_elements": {"equals": True, "weight": 2.0},
        },
        "negative": {"circularity": {"above": 0.7, "penalty": 2.5}},
        "structural_hints": {"linear_min": 6, "boost": 3.5},
    },

    "differential_drive_robot": {
        "category": "ground_robot", "description": "Differential drive robot — two-wheel + caster",
        "required": {"has_rotary_elements": True},
        "positive": {
            "aspect_ratio": {"range": (0.8, 1.5), "weight": 2.0},
            "solidity": {"range": (0.5, 0.85), "weight": 1.5},
        },
        "negative": {},
        "structural_hints": {"rotary_min": 2, "boost": 2.5},
    },

    "omni_wheel_robot": {
        "category": "ground_robot", "description": "Omni-directional wheeled robot — mecanum/omni wheels",
        "required": {"has_rotary_elements": True, "min_rotary_count": 3},
        "positive": {
            "aspect_ratio": {"range": (0.8, 1.3), "weight": 2.0},
            "symmetry_score": {"range": (0.6, 1.0), "weight": 2.0},
            "has_panel_elements": {"equals": True, "weight": 1.5},
        },
        "negative": {},
        "structural_hints": {"rotary_min": 4, "boost": 3.0},
    },

    "mars_rover": {
        "category": "ground_robot", "description": "Planetary rover — 6-wheel rocker-bogie exploration robot",
        "required": {"has_rotary_elements": True, "min_rotary_count": 4},
        "positive": {
            "aspect_ratio": {"range": (1.0, 2.5), "weight": 2.0},
            "complexity": {"range": (25, 100), "weight": 2.0},
            "has_panel_elements": {"equals": True, "weight": 2.5},
        },
        "negative": {},
        "structural_hints": {"rotary_min": 6, "boost": 4.0},
    },

    "rc_car": {
        "category": "ground_robot", "description": "RC car — remote controlled racing vehicle",
        "required": {"has_rotary_elements": True},
        "positive": {
            "aspect_ratio": {"range": (1.5, 3.5), "weight": 3.0},
            "solidity": {"range": (0.5, 0.85), "weight": 1.5},
        },
        "negative": {"circularity": {"above": 0.6, "penalty": 2.5}},
        "structural_hints": {"rotary_min": 2, "boost": 2.0},
    },

    "delivery_robot": {
        "category": "ground_robot", "description": "Sidewalk delivery robot — autonomous last-mile courier",
        "required": {"has_rotary_elements": True, "has_panel_elements": True},
        "positive": {
            "aspect_ratio": {"range": (0.8, 1.5), "weight": 2.0},
            "solidity": {"range": (0.6, 0.95), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"rotary_min": 4, "boost": 3.0},
    },

    "agricultural_robot": {
        "category": "ground_robot", "description": "Agricultural field robot — autonomous farming vehicle",
        "required": {"has_rotary_elements": True},
        "positive": {
            "aspect_ratio": {"range": (1.0, 2.5), "weight": 2.0},
            "solidity": {"range": (0.4, 0.8), "weight": 1.5},
        },
        "negative": {},
        "structural_hints": {"rotary_min": 2, "boost": 2.0},
    },

    "security_patrol_robot": {
        "category": "ground_robot", "description": "Security patrol robot — autonomous surveillance rover",
        "required": {"has_rotary_elements": True},
        "positive": {
            "aspect_ratio": {"range": (0.7, 1.5), "weight": 2.0},
            "solidity": {"range": (0.6, 0.9), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"rotary_min": 2, "boost": 2.5},
    },

    "bomb_disposal_robot": {
        "category": "ground_robot", "description": "EOD/bomb disposal robot — tracked with manipulator arm",
        "required": {"has_linear_elements": True, "has_rotary_elements": True},
        "positive": {
            "aspect_ratio": {"range": (1.0, 2.5), "weight": 2.0},
            "complexity": {"range": (30, 120), "weight": 2.5},
            "convex_defects_count": {"range": (2, 15), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"linear_min": 5, "rotary_min": 2, "boost": 3.5},
    },

    "autonomous_car": {
        "category": "ground_robot", "description": "Autonomous vehicle — self-driving car/shuttle",
        "required": {"has_rotary_elements": True},
        "positive": {
            "aspect_ratio": {"range": (1.5, 3.0), "weight": 3.0},
            "solidity": {"range": (0.7, 0.95), "weight": 2.5},
            "has_panel_elements": {"equals": True, "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"rotary_min": 2, "boost": 2.0},
    },

    "robotic_lawnmower": {
        "category": "ground_robot", "description": "Robotic lawn mower — autonomous grass cutter",
        "required": {"has_rotary_elements": True},
        "positive": {
            "aspect_ratio": {"range": (0.9, 1.5), "weight": 2.0},
            "solidity": {"range": (0.7, 1.0), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {},
    },

    "warehouse_agv": {
        "category": "ground_robot", "description": "Warehouse AGV — automated guided vehicle for logistics",
        "required": {"has_rotary_elements": True},
        "positive": {
            "aspect_ratio": {"range": (0.8, 1.5), "weight": 2.0},
            "solidity": {"range": (0.7, 1.0), "weight": 2.5},
            "has_panel_elements": {"equals": True, "weight": 2.0},
        },
        "negative": {"convex_defects_count": {"above": 5, "penalty": 1.5}},
        "structural_hints": {},
    },

    "line_follower_robot": {
        "category": "ground_robot", "description": "Line-following robot — simple educational robot",
        "required": {},
        "positive": {
            "aspect_ratio": {"range": (0.8, 1.5), "weight": 2.0},
            "complexity": {"range": (8, 25), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {},
    },

    "robotic_ball": {
        "category": "ground_robot", "description": "Spherical rolling robot — ball-shaped ground bot",
        "required": {"circularity_min": 0.75, "solidity_min": 0.85},
        "positive": {
            "circularity": {"range": (0.8, 1.0), "weight": 3.5},
            "solidity": {"range": (0.9, 1.0), "weight": 2.0},
            "aspect_ratio": {"range": (0.9, 1.1), "weight": 2.0},
        },
        "negative": {"has_linear_elements": {"equals": True, "penalty": 2.0}},
        "structural_hints": {},
    },

    # ═══════════════════════════════════════════
    #  3. MANIPULATORS — Robot Arms (12)
    # ═══════════════════════════════════════════

    "robot_arm_6dof": {
        "category": "robot_arm", "description": "6-DOF articulated robot arm — general purpose manipulator",
        "required": {"has_linear_elements": True},
        "positive": {
            "aspect_ratio": {"range": (0.2, 0.85), "weight": 2.5},
            "convex_defects_count": {"range": (2, 15), "weight": 2.0},
            "elongation": {"range": (0.15, 0.55), "weight": 2.5},
            "strong_line_count": {"range": (5, 50), "weight": 1.5},
        },
        "negative": {
            "circularity": {"above": 0.7, "penalty": 3.0},
            "solidity": {"above": 0.85, "penalty": 2.0},
        },
        "structural_hints": {"linear_min": 5, "boost": 5.0, "rotary_min": 2, "rotary_boost": 2.5},
    },

    "scara_arm": {
        "category": "robot_arm", "description": "SCARA arm — selective compliance horizontal arm",
        "required": {"has_linear_elements": True},
        "positive": {
            "aspect_ratio": {"range": (0.5, 1.5), "weight": 2.0},
            "strong_line_count": {"range": (3, 30), "weight": 2.0},
        },
        "negative": {"circularity": {"above": 0.7, "penalty": 2.5}},
        "structural_hints": {"linear_min": 3, "boost": 3.5},
    },

    "delta_robot": {
        "category": "robot_arm", "description": "Delta/parallel robot — high-speed pick-and-place",
        "required": {"has_linear_elements": True},
        "positive": {
            "convex_defects_count": {"range": (3, 20), "weight": 2.5},
            "symmetry_score": {"range": (0.5, 1.0), "weight": 2.5},
            "solidity": {"range": (0.2, 0.55), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"linear_min": 6, "boost": 4.0},
    },

    "collaborative_cobot": {
        "category": "robot_arm", "description": "Collaborative robot (cobot) — safe human-interactive arm",
        "required": {"has_linear_elements": True},
        "positive": {
            "aspect_ratio": {"range": (0.3, 0.9), "weight": 2.0},
            "texture_homogeneity": {"range": (0.4, 1.0), "weight": 1.5},
        },
        "negative": {"circularity": {"above": 0.7, "penalty": 2.5}},
        "structural_hints": {"linear_min": 4, "boost": 4.0},
    },

    "industrial_arm": {
        "category": "industrial", "description": "Industrial robot arm — large-scale manufacturing",
        "required": {"has_linear_elements": True, "min_component_count": 3},
        "positive": {
            "solidity": {"range": (0.35, 0.7), "weight": 2.0},
            "estimated_material": {"values": ["polished_metal", "brushed_metal", "textured_metal"], "weight": 2.5},
            "complexity": {"range": (30, 150), "weight": 2.0},
        },
        "negative": {"circularity": {"above": 0.7, "penalty": 2.5}},
        "structural_hints": {"linear_min": 5, "boost": 4.0},
    },

    "welding_robot": {
        "category": "industrial", "description": "Welding robot arm — arc/spot welding manipulator",
        "required": {"has_linear_elements": True},
        "positive": {
            "complexity": {"range": (25, 120), "weight": 2.0},
            "estimated_material": {"values": ["polished_metal", "brushed_metal", "textured_metal"], "weight": 2.5},
        },
        "negative": {},
        "structural_hints": {"linear_min": 4, "boost": 3.5},
    },

    "painting_robot": {
        "category": "industrial", "description": "Spray painting robot — automotive painting arm",
        "required": {"has_linear_elements": True},
        "positive": {
            "complexity": {"range": (20, 80), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"linear_min": 4, "boost": 3.0},
    },

    "palletizing_robot": {
        "category": "industrial", "description": "Palletizing robot — heavy box stacking arm",
        "required": {"has_linear_elements": True},
        "positive": {
            "solidity": {"range": (0.4, 0.75), "weight": 2.0},
            "estimated_material": {"values": ["polished_metal", "brushed_metal", "textured_metal"], "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"linear_min": 4, "boost": 3.5},
    },

    "cnc_gantry": {
        "category": "industrial", "description": "CNC gantry/cartesian robot — XYZ linear motion system",
        "required": {"has_linear_elements": True},
        "positive": {
            "strong_line_count": {"range": (8, 60), "weight": 3.0},
            "has_panel_elements": {"equals": True, "weight": 2.0},
            "aspect_ratio": {"range": (0.8, 2.0), "weight": 1.5},
        },
        "negative": {"circularity": {"above": 0.6, "penalty": 2.5}},
        "structural_hints": {"linear_min": 8, "boost": 4.0},
    },

    "gripper_end_effector": {
        "category": "robot_arm", "description": "Robotic gripper / end effector — jaw or suction tool",
        "required": {},
        "positive": {
            "complexity": {"range": (15, 60), "weight": 2.0},
            "convex_defects_count": {"range": (1, 8), "weight": 2.0},
        },
        "negative": {"solidity": {"above": 0.9, "penalty": 1.5}},
        "structural_hints": {},
    },

    "cable_driven_arm": {
        "category": "robot_arm", "description": "Cable-driven arm — tendon-actuated lightweight manipulator",
        "required": {"has_linear_elements": True},
        "positive": {
            "solidity": {"range": (0.15, 0.5), "weight": 2.5},
            "elongation": {"range": (0.1, 0.45), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"linear_min": 4, "boost": 3.0},
    },

    "soft_gripper": {
        "category": "robot_arm", "description": "Soft robotic gripper — compliant pneumatic manipulator",
        "required": {},
        "positive": {
            "circularity": {"range": (0.3, 0.7), "weight": 2.0},
            "texture_homogeneity": {"range": (0.5, 1.0), "weight": 2.0},
            "estimated_material": {"values": ["fabric_or_soft", "matte_plastic"], "weight": 2.5},
        },
        "negative": {"estimated_material": {"values": ["polished_metal", "brushed_metal"], "weight": -2.0}},
        "structural_hints": {},
    },

    # ═══════════════════════════════════════════
    #  4. HUMANOID & LEGGED (10)
    # ═══════════════════════════════════════════

    "humanoid_robot": {
        "category": "humanoid", "description": "Full-size humanoid robot — bipedal human-shaped",
        "required": {"aspect_ratio_max": 0.75, "min_component_count": 4},
        "positive": {
            "aspect_ratio": {"range": (0.25, 0.65), "weight": 3.0},
            "convex_defects_count": {"range": (4, 20), "weight": 2.5},
            "symmetry_score": {"range": (0.5, 1.0), "weight": 2.5},
            "complexity": {"range": (35, 200), "weight": 2.0},
        },
        "negative": {
            "circularity": {"above": 0.6, "penalty": 3.0},
            "solidity": {"above": 0.9, "penalty": 2.0},
        },
        "structural_hints": {"component_min": 5, "boost": 3.0},
    },

    "humanoid_torso": {
        "category": "humanoid", "description": "Upper-body humanoid — torso + arms (no legs)",
        "required": {"min_component_count": 3},
        "positive": {
            "aspect_ratio": {"range": (0.4, 0.9), "weight": 2.5},
            "convex_defects_count": {"range": (2, 12), "weight": 2.0},
            "symmetry_score": {"range": (0.5, 1.0), "weight": 2.0},
        },
        "negative": {"circularity": {"above": 0.7, "penalty": 2.5}},
        "structural_hints": {},
    },

    "quadruped_robot": {
        "category": "legged", "description": "Quadruped robot — four-legged walking/running robot (like Spot)",
        "required": {"has_linear_elements": True, "min_component_count": 4},
        "positive": {
            "aspect_ratio": {"range": (1.0, 2.5), "weight": 2.5},
            "convex_defects_count": {"range": (3, 15), "weight": 2.5},
            "symmetry_score": {"range": (0.4, 1.0), "weight": 2.0},
            "solidity": {"range": (0.3, 0.7), "weight": 2.0},
        },
        "negative": {"circularity": {"above": 0.7, "penalty": 3.0}},
        "structural_hints": {"linear_min": 6, "boost": 4.0},
    },

    "hexapod_robot": {
        "category": "legged", "description": "Hexapod robot — six-legged walking robot (insect-inspired)",
        "required": {"has_linear_elements": True, "min_component_count": 5},
        "positive": {
            "convex_defects_count": {"range": (4, 20), "weight": 3.0},
            "symmetry_score": {"range": (0.4, 1.0), "weight": 2.0},
            "solidity": {"range": (0.2, 0.6), "weight": 2.5},
        },
        "negative": {"circularity": {"above": 0.7, "penalty": 2.5}},
        "structural_hints": {"linear_min": 8, "boost": 5.0},
    },

    "biped_walker": {
        "category": "legged", "description": "Bipedal walking robot — two-legged locomotion platform",
        "required": {"aspect_ratio_max": 0.8},
        "positive": {
            "aspect_ratio": {"range": (0.3, 0.7), "weight": 3.0},
            "convex_defects_count": {"range": (2, 10), "weight": 2.0},
        },
        "negative": {"circularity": {"above": 0.6, "penalty": 2.5}},
        "structural_hints": {"linear_min": 4, "boost": 3.0},
    },

    "snake_robot": {
        "category": "legged", "description": "Snake/serpentine robot — multi-segment limbless locomotion",
        "required": {"aspect_ratio_min": 2.5},
        "positive": {
            "aspect_ratio": {"range": (3.0, 15.0), "weight": 3.5},
            "elongation": {"range": (0.05, 0.25), "weight": 3.0},
            "solidity": {"range": (0.5, 0.9), "weight": 1.5},
        },
        "negative": {"has_rotary_elements": {"equals": True, "penalty": 2.0}},
        "structural_hints": {},
    },

    "spider_robot": {
        "category": "legged", "description": "Spider robot — 8-legged arachnid-inspired walker",
        "required": {"has_linear_elements": True, "min_component_count": 5},
        "positive": {
            "convex_defects_count": {"range": (5, 25), "weight": 3.0},
            "solidity": {"range": (0.15, 0.5), "weight": 2.5},
            "radial_symmetry": {"range": (0.3, 1.0), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"linear_min": 10, "boost": 5.0},
    },

    "robotic_exoskeleton": {
        "category": "humanoid", "description": "Robotic exoskeleton — wearable strength-augmenting frame",
        "required": {"has_linear_elements": True},
        "positive": {
            "aspect_ratio": {"range": (0.3, 0.8), "weight": 2.5},
            "solidity": {"range": (0.2, 0.6), "weight": 2.5},
            "convex_defects_count": {"range": (3, 15), "weight": 2.0},
        },
        "negative": {"circularity": {"above": 0.6, "penalty": 2.5}},
        "structural_hints": {"linear_min": 6, "boost": 3.5},
    },

    "robotic_hand": {
        "category": "humanoid", "description": "Robotic hand — dexterous multi-finger end effector",
        "required": {},
        "positive": {
            "convex_defects_count": {"range": (3, 10), "weight": 3.0},
            "solidity": {"range": (0.3, 0.7), "weight": 2.0},
            "complexity": {"range": (20, 80), "weight": 2.0},
        },
        "negative": {"circularity": {"above": 0.7, "penalty": 2.5}},
        "structural_hints": {},
    },

    "robotic_dog": {
        "category": "legged", "description": "Robotic dog — quadruped companion robot",
        "required": {"has_linear_elements": True, "min_component_count": 3},
        "positive": {
            "aspect_ratio": {"range": (1.0, 2.0), "weight": 2.5},
            "convex_defects_count": {"range": (2, 12), "weight": 2.0},
            "solidity": {"range": (0.3, 0.7), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"linear_min": 5, "boost": 3.5},
    },

    # ═══════════════════════════════════════════
    #  5. HOME & SERVICE ROBOTS (12)
    # ═══════════════════════════════════════════

    "robotic_vacuum": {
        "category": "home_robot", "description": "Robotic vacuum cleaner — autonomous floor sweeper",
        "required": {"circularity_min": 0.6, "solidity_min": 0.8},
        "positive": {
            "circularity": {"range": (0.7, 1.0), "weight": 3.5},
            "solidity": {"range": (0.85, 1.0), "weight": 2.5},
            "aspect_ratio": {"range": (0.85, 1.2), "weight": 2.0},
            "complexity": {"range": (5, 18), "weight": 2.0},
        },
        "negative": {
            "has_linear_elements": {"equals": True, "penalty": 1.5},
            "convex_defects_count": {"above": 3, "penalty": 2.5},
        },
        "structural_hints": {"max_components": 3, "simple_boost": 2.0},
    },

    "robotic_mop": {
        "category": "home_robot", "description": "Robotic mop — autonomous floor mopping robot",
        "required": {"circularity_min": 0.5, "solidity_min": 0.7},
        "positive": {
            "circularity": {"range": (0.5, 0.9), "weight": 2.5},
            "solidity": {"range": (0.7, 1.0), "weight": 2.0},
            "aspect_ratio": {"range": (0.7, 1.4), "weight": 1.5},
        },
        "negative": {"convex_defects_count": {"above": 4, "penalty": 2.0}},
        "structural_hints": {},
    },

    "robot_butler": {
        "category": "service_robot", "description": "Service/butler robot — mobile tray-carrying assistant",
        "required": {},
        "positive": {
            "aspect_ratio": {"range": (0.4, 0.8), "weight": 2.5},
            "solidity": {"range": (0.6, 0.95), "weight": 2.0},
            "has_panel_elements": {"equals": True, "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {},
    },

    "telepresence_robot": {
        "category": "service_robot", "description": "Telepresence robot — mobile video conferencing unit",
        "required": {},
        "positive": {
            "aspect_ratio": {"range": (0.3, 0.7), "weight": 2.5},
            "solidity": {"range": (0.6, 0.95), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {},
    },

    "cleaning_robot_commercial": {
        "category": "service_robot", "description": "Commercial cleaning robot — large floor scrubber",
        "required": {"has_rotary_elements": True},
        "positive": {
            "solidity": {"range": (0.7, 1.0), "weight": 2.0},
            "aspect_ratio": {"range": (0.8, 1.5), "weight": 1.5},
        },
        "negative": {},
        "structural_hints": {},
    },

    "pool_cleaning_robot": {
        "category": "home_robot", "description": "Pool cleaning robot — aquatic surface/floor cleaner",
        "required": {},
        "positive": {
            "solidity": {"range": (0.7, 1.0), "weight": 2.5},
            "circularity": {"range": (0.4, 0.8), "weight": 1.5},
        },
        "negative": {},
        "structural_hints": {},
    },

    "window_cleaning_robot": {
        "category": "home_robot", "description": "Window cleaning robot — suction-mount glass cleaner",
        "required": {},
        "positive": {
            "aspect_ratio": {"range": (0.8, 1.3), "weight": 2.0},
            "solidity": {"range": (0.8, 1.0), "weight": 2.5},
        },
        "negative": {},
        "structural_hints": {},
    },

    "gutter_cleaning_robot": {
        "category": "home_robot", "description": "Gutter cleaning robot — autonomous gutter sweeper",
        "required": {},
        "positive": {
            "aspect_ratio": {"range": (1.5, 5.0), "weight": 2.5},
            "elongation": {"range": (0.1, 0.4), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {},
    },

    "cooking_robot": {
        "category": "service_robot", "description": "Cooking robot — automated kitchen arm/station",
        "required": {"has_linear_elements": True},
        "positive": {
            "complexity": {"range": (20, 80), "weight": 2.0},
            "convex_defects_count": {"range": (1, 10), "weight": 1.5},
        },
        "negative": {},
        "structural_hints": {"linear_min": 3, "boost": 2.5},
    },

    "reception_robot": {
        "category": "service_robot", "description": "Reception/concierge robot — lobby greeting assistant",
        "required": {},
        "positive": {
            "aspect_ratio": {"range": (0.4, 0.8), "weight": 2.5},
            "solidity": {"range": (0.7, 1.0), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {},
    },

    "pet_robot": {
        "category": "home_robot", "description": "Robot pet — companion entertainment robot",
        "required": {},
        "positive": {
            "complexity": {"range": (15, 60), "weight": 2.0},
            "solidity": {"range": (0.5, 0.85), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {},
    },

    "toy_robot": {
        "category": "home_robot", "description": "Toy robot — children's programmable robot",
        "required": {},
        "positive": {
            "complexity": {"range": (10, 40), "weight": 2.0},
            "avg_brightness": {"range": (120, 220), "weight": 1.5},
        },
        "negative": {},
        "structural_hints": {},
    },

    # ═══════════════════════════════════════════
    #  6. INDUSTRIAL & WAREHOUSE (10)
    # ═══════════════════════════════════════════

    "amr_warehouse": {
        "category": "warehouse", "description": "Autonomous mobile robot (AMR) — warehouse shelf mover",
        "required": {"has_rotary_elements": True},
        "positive": {
            "aspect_ratio": {"range": (0.8, 1.3), "weight": 2.0},
            "solidity": {"range": (0.7, 1.0), "weight": 2.5},
        },
        "negative": {},
        "structural_hints": {},
    },

    "forklift_agv": {
        "category": "warehouse", "description": "Autonomous forklift — self-driving warehouse forklift",
        "required": {"has_rotary_elements": True, "has_linear_elements": True},
        "positive": {
            "aspect_ratio": {"range": (0.6, 1.2), "weight": 2.0},
            "complexity": {"range": (20, 80), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"linear_min": 3, "boost": 2.5},
    },

    "pick_place_arm": {
        "category": "warehouse", "description": "Pick-and-place station — fixed-mount sorting robot",
        "required": {"has_linear_elements": True},
        "positive": {
            "strong_line_count": {"range": (5, 40), "weight": 2.5},
            "has_panel_elements": {"equals": True, "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"linear_min": 5, "boost": 3.0},
    },

    "conveyor_robot": {
        "category": "warehouse", "description": "Conveyor sorting robot — belt-integrated sorting system",
        "required": {"has_linear_elements": True},
        "positive": {
            "aspect_ratio": {"range": (2.0, 8.0), "weight": 3.0},
            "strong_line_count": {"range": (10, 60), "weight": 2.5},
        },
        "negative": {},
        "structural_hints": {"linear_min": 8, "boost": 3.5},
    },

    "inspection_robot": {
        "category": "industrial", "description": "Inspection robot — pipe/tank/infrastructure inspector",
        "required": {},
        "positive": {
            "aspect_ratio": {"range": (1.0, 3.0), "weight": 2.0},
            "complexity": {"range": (15, 60), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {},
    },

    "3d_printer": {
        "category": "industrial", "description": "3D printer/additive manufacturing robot",
        "required": {"has_linear_elements": True},
        "positive": {
            "strong_line_count": {"range": (8, 50), "weight": 2.5},
            "aspect_ratio": {"range": (0.7, 1.4), "weight": 2.0},
            "has_panel_elements": {"equals": True, "weight": 2.5},
        },
        "negative": {},
        "structural_hints": {"linear_min": 6, "boost": 3.0},
    },

    "laser_cutter_robot": {
        "category": "industrial", "description": "Laser cutting robot — CNC laser/plasma cutter",
        "required": {"has_linear_elements": True},
        "positive": {
            "strong_line_count": {"range": (6, 40), "weight": 2.5},
            "has_panel_elements": {"equals": True, "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"linear_min": 5, "boost": 3.0},
    },

    "packaging_robot": {
        "category": "warehouse", "description": "Packaging robot — automated box packing system",
        "required": {"has_linear_elements": True},
        "positive": {
            "has_panel_elements": {"equals": True, "weight": 2.5},
            "complexity": {"range": (20, 70), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"linear_min": 4, "boost": 2.5},
    },

    "sorting_arm": {
        "category": "warehouse", "description": "Sorting robot arm — high-speed item classifier",
        "required": {"has_linear_elements": True},
        "positive": {
            "strong_line_count": {"range": (4, 30), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"linear_min": 4, "boost": 3.0},
    },

    "bin_picking_robot": {
        "category": "warehouse", "description": "Bin picking robot — random object grasping system",
        "required": {"has_linear_elements": True},
        "positive": {
            "complexity": {"range": (25, 90), "weight": 2.0},
            "convex_defects_count": {"range": (1, 8), "weight": 1.5},
        },
        "negative": {},
        "structural_hints": {"linear_min": 4, "boost": 3.0},
    },

    # ═══════════════════════════════════════════
    #  7. MEDICAL & ASSISTIVE (8)
    # ═══════════════════════════════════════════

    "surgical_robot": {
        "category": "medical", "description": "Surgical robot — precision medical manipulator (da Vinci style)",
        "required": {"has_linear_elements": True, "min_component_count": 3},
        "positive": {
            "complexity": {"range": (30, 150), "weight": 2.5},
            "estimated_material": {"values": ["polished_metal", "brushed_metal"], "weight": 2.5},
        },
        "negative": {},
        "structural_hints": {"linear_min": 5, "boost": 4.0},
    },

    "rehabilitation_robot": {
        "category": "medical", "description": "Rehabilitation robot — physical therapy assistance device",
        "required": {"has_linear_elements": True},
        "positive": {
            "solidity": {"range": (0.4, 0.8), "weight": 2.0},
            "has_panel_elements": {"equals": True, "weight": 1.5},
        },
        "negative": {},
        "structural_hints": {"linear_min": 3, "boost": 2.5},
    },

    "wheelchair_robot": {
        "category": "medical", "description": "Robotic wheelchair — autonomous mobility platform",
        "required": {"has_rotary_elements": True},
        "positive": {
            "aspect_ratio": {"range": (0.8, 1.5), "weight": 2.0},
            "has_panel_elements": {"equals": True, "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"rotary_min": 2, "boost": 2.0},
    },

    "prosthetic_limb": {
        "category": "medical", "description": "Robotic prosthetic — bionic arm or leg",
        "required": {},
        "positive": {
            "aspect_ratio": {"range": (0.2, 0.6), "weight": 3.0},
            "elongation": {"range": (0.1, 0.4), "weight": 2.5},
            "complexity": {"range": (15, 60), "weight": 2.0},
        },
        "negative": {"circularity": {"above": 0.6, "penalty": 2.5}},
        "structural_hints": {},
    },

    "disinfection_robot": {
        "category": "medical", "description": "UV disinfection robot — autonomous pathogen elimination",
        "required": {},
        "positive": {
            "aspect_ratio": {"range": (0.4, 0.8), "weight": 2.0},
            "solidity": {"range": (0.7, 1.0), "weight": 2.0},
            "has_light_elements": {"equals": True, "weight": 2.5},
        },
        "negative": {},
        "structural_hints": {},
    },

    "pharmacy_robot": {
        "category": "medical", "description": "Pharmacy dispensing robot — automated medication handler",
        "required": {"has_linear_elements": True},
        "positive": {
            "has_panel_elements": {"equals": True, "weight": 2.5},
            "solidity": {"range": (0.6, 0.95), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {},
    },

    "care_robot": {
        "category": "medical", "description": "Elderly care robot — patient monitoring companion",
        "required": {},
        "positive": {
            "solidity": {"range": (0.7, 1.0), "weight": 2.0},
            "aspect_ratio": {"range": (0.5, 0.9), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {},
    },

    "lab_automation_robot": {
        "category": "medical", "description": "Lab automation robot — sample handling and testing",
        "required": {"has_linear_elements": True},
        "positive": {
            "has_panel_elements": {"equals": True, "weight": 2.0},
            "strong_line_count": {"range": (5, 30), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"linear_min": 4, "boost": 3.0},
    },

    # ═══════════════════════════════════════════
    #  8. SMART DEVICES / IoT (10)
    # ═══════════════════════════════════════════

    "smart_light_bulb": {
        "category": "smart_light", "description": "Smart light bulb — WiFi/Zigbee connected LED",
        "required": {"solidity_min": 0.7},
        "positive": {
            "circularity": {"range": (0.5, 1.0), "weight": 3.0},
            "solidity": {"range": (0.75, 1.0), "weight": 2.5},
            "avg_brightness": {"range": (140, 255), "weight": 1.5},
            "complexity": {"range": (5, 22), "weight": 2.0},
        },
        "negative": {
            "has_rotary_elements": {"equals": True, "penalty": 3.0},
            "has_linear_elements": {"equals": True, "penalty": 2.0},
            "convex_defects_count": {"above": 3, "penalty": 2.5},
        },
        "structural_hints": {"max_components": 2, "simple_boost": 2.0},
    },

    "smart_speaker": {
        "category": "smart_device", "description": "Smart speaker — voice-controlled home assistant",
        "required": {"solidity_min": 0.8},
        "positive": {
            "circularity": {"range": (0.5, 0.95), "weight": 2.0},
            "solidity": {"range": (0.85, 1.0), "weight": 2.0},
            "complexity": {"range": (5, 18), "weight": 2.0},
            "texture_homogeneity": {"range": (0.5, 1.0), "weight": 1.5},
        },
        "negative": {
            "has_rotary_elements": {"equals": True, "penalty": 3.0},
            "convex_defects_count": {"above": 2, "penalty": 2.0},
        },
        "structural_hints": {"max_components": 2, "simple_boost": 2.0},
    },

    "smart_plug": {
        "category": "smart_device", "description": "Smart plug — WiFi power outlet adapter",
        "required": {"solidity_min": 0.8},
        "positive": {
            "solidity": {"range": (0.85, 1.0), "weight": 2.5},
            "complexity": {"range": (4, 15), "weight": 2.0},
            "aspect_ratio": {"range": (0.6, 1.5), "weight": 1.5},
        },
        "negative": {"has_rotary_elements": {"equals": True, "penalty": 3.0}},
        "structural_hints": {},
    },

    "smart_camera": {
        "category": "smart_device", "description": "Smart security camera — IP/WiFi surveillance camera",
        "required": {},
        "positive": {
            "circularity": {"range": (0.3, 0.8), "weight": 2.0},
            "complexity": {"range": (10, 35), "weight": 2.0},
            "solidity": {"range": (0.6, 0.95), "weight": 1.5},
        },
        "negative": {"convex_defects_count": {"above": 5, "penalty": 1.5}},
        "structural_hints": {},
    },

    "smart_thermostat": {
        "category": "smart_device", "description": "Smart thermostat — connected temperature controller",
        "required": {"solidity_min": 0.75},
        "positive": {
            "circularity": {"range": (0.6, 1.0), "weight": 2.5},
            "solidity": {"range": (0.8, 1.0), "weight": 2.0},
            "complexity": {"range": (5, 20), "weight": 2.0},
        },
        "negative": {"has_rotary_elements": {"equals": True, "penalty": 2.5}},
        "structural_hints": {},
    },

    "smart_display": {
        "category": "smart_device", "description": "Smart display — touchscreen home hub",
        "required": {},
        "positive": {
            "aspect_ratio": {"range": (1.2, 2.0), "weight": 2.5},
            "solidity": {"range": (0.8, 1.0), "weight": 2.0},
            "has_panel_elements": {"equals": True, "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {},
    },

    "smart_lock": {
        "category": "smart_device", "description": "Smart door lock — connected security lock",
        "required": {"solidity_min": 0.75},
        "positive": {
            "solidity": {"range": (0.8, 1.0), "weight": 2.5},
            "complexity": {"range": (8, 25), "weight": 2.0},
            "circularity": {"range": (0.3, 0.8), "weight": 1.5},
        },
        "negative": {"has_rotary_elements": {"equals": True, "penalty": 2.0}},
        "structural_hints": {},
    },

    "smart_doorbell": {
        "category": "smart_device", "description": "Smart doorbell — video doorbell with camera",
        "required": {"solidity_min": 0.7},
        "positive": {
            "aspect_ratio": {"range": (0.3, 0.7), "weight": 2.5},
            "solidity": {"range": (0.75, 1.0), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {},
    },

    "led_strip_controller": {
        "category": "smart_light", "description": "LED strip light — connected RGB light strip",
        "required": {},
        "positive": {
            "aspect_ratio": {"range": (3.0, 20.0), "weight": 3.5},
            "elongation": {"range": (0.02, 0.2), "weight": 3.0},
            "has_light_elements": {"equals": True, "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {},
    },

    "smart_switch": {
        "category": "smart_device", "description": "Smart wall switch — connected light switch panel",
        "required": {"solidity_min": 0.8},
        "positive": {
            "solidity": {"range": (0.85, 1.0), "weight": 2.0},
            "aspect_ratio": {"range": (0.6, 1.5), "weight": 1.5},
            "complexity": {"range": (5, 18), "weight": 2.0},
        },
        "negative": {"has_rotary_elements": {"equals": True, "penalty": 2.5}},
        "structural_hints": {},
    },

    # ═══════════════════════════════════════════
    #  9. MARINE & UNDERWATER (4)
    # ═══════════════════════════════════════════

    "underwater_rov": {
        "category": "marine", "description": "Underwater ROV — remotely operated submersible vehicle",
        "required": {"has_rotary_elements": True},
        "positive": {
            "solidity": {"range": (0.5, 0.85), "weight": 2.0},
            "complexity": {"range": (15, 60), "weight": 2.0},
            "has_panel_elements": {"equals": True, "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"rotary_min": 2, "boost": 2.5},
    },

    "autonomous_boat": {
        "category": "marine", "description": "Autonomous surface vessel — unmanned boat/kayak",
        "required": {},
        "positive": {
            "aspect_ratio": {"range": (1.5, 5.0), "weight": 3.0},
            "solidity": {"range": (0.6, 0.95), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {},
    },

    "underwater_glider": {
        "category": "marine", "description": "Underwater glider — buoyancy-driven ocean surveyor",
        "required": {},
        "positive": {
            "aspect_ratio": {"range": (2.0, 6.0), "weight": 3.0},
            "elongation": {"range": (0.1, 0.35), "weight": 2.5},
            "solidity": {"range": (0.7, 1.0), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {},
    },

    "robotic_fish": {
        "category": "marine", "description": "Robotic fish — bio-inspired underwater swimmer",
        "required": {},
        "positive": {
            "aspect_ratio": {"range": (1.5, 4.0), "weight": 2.5},
            "elongation": {"range": (0.15, 0.45), "weight": 2.0},
            "solidity": {"range": (0.6, 0.9), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {},
    },

    # ═══════════════════════════════════════════
    #  10. SPACE & EXTREME (4)
    # ═══════════════════════════════════════════

    "space_rover": {
        "category": "space", "description": "Space/planetary rover — extraterrestrial exploration robot",
        "required": {"has_rotary_elements": True, "min_rotary_count": 4},
        "positive": {
            "complexity": {"range": (30, 150), "weight": 2.5},
            "has_panel_elements": {"equals": True, "weight": 2.5},
            "aspect_ratio": {"range": (1.0, 2.5), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"rotary_min": 6, "boost": 4.0},
    },

    "satellite_servicing_robot": {
        "category": "space", "description": "Satellite servicing robot — orbital repair manipulator",
        "required": {"has_linear_elements": True},
        "positive": {
            "complexity": {"range": (30, 120), "weight": 2.5},
            "has_panel_elements": {"equals": True, "weight": 2.5},
        },
        "negative": {},
        "structural_hints": {"linear_min": 4, "boost": 3.0},
    },

    "mining_robot": {
        "category": "extreme", "description": "Mining robot — underground excavation autonomous vehicle",
        "required": {"has_rotary_elements": True, "has_linear_elements": True},
        "positive": {
            "complexity": {"range": (25, 100), "weight": 2.0},
            "solidity": {"range": (0.5, 0.85), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"rotary_min": 2, "linear_min": 3, "boost": 3.0},
    },

    "firefighting_robot": {
        "category": "extreme", "description": "Firefighting robot — heat-resistant emergency response bot",
        "required": {"has_rotary_elements": True},
        "positive": {
            "solidity": {"range": (0.6, 0.9), "weight": 2.0},
            "complexity": {"range": (20, 80), "weight": 2.0},
        },
        "negative": {},
        "structural_hints": {"rotary_min": 2, "boost": 2.5},
    },
}


# Quick validation
assert len(DEVICE_FINGERPRINTS) == 100, f"Expected 100, got {len(DEVICE_FINGERPRINTS)}"
