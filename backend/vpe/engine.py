"""
OMNIX Visual Physics Engine — Main Orchestrator (v2)

Multi-stage processing with detailed timing and richer output.
Each stage is timed independently so the frontend can show progress.
"""

import time
import base64
from .image_analyzer import ImageAnalyzer
from .device_classifier import DeviceClassifier
from .physics_engine import PhysicsEngine


# ── Category-aware part naming ──
# Raw detection labels everything rotary as "rotor_assembly". Once we know
# the device category, we rename those labels so a speaker's circle becomes
# "speaker_driver" instead of "rotor".
_CATEGORY_PART_MAP = {
    "drone":         {"rotary_big": "rotor", "rotary_small": "motor_hub",    "ring": "rotor_housing",   "solid_circle": "camera_lens",   "rect": "body_panel"},
    "ground_robot":  {"rotary_big": "wheel", "rotary_small": "caster",       "ring": "wheel_rim",       "solid_circle": "sensor",        "rect": "chassis_panel"},
    "legged":        {"rotary_big": "joint", "rotary_small": "servo",        "ring": "joint_hub",       "solid_circle": "foot_pad",      "rect": "leg_plate"},
    "humanoid":      {"rotary_big": "joint", "rotary_small": "actuator",     "ring": "joint_hub",       "solid_circle": "eye_or_sensor", "rect": "body_plate"},
    "home_robot":    {"rotary_big": "brush", "rotary_small": "wheel",        "ring": "brush_housing",   "solid_circle": "sensor_or_bumper", "rect": "top_panel"},
    "service_robot": {"rotary_big": "wheel", "rotary_small": "caster",       "ring": "wheel_rim",       "solid_circle": "display_or_sensor", "rect": "body_panel"},
    "warehouse":     {"rotary_big": "wheel", "rotary_small": "caster",       "ring": "wheel_rim",       "solid_circle": "sensor",        "rect": "load_surface"},
    "industrial":    {"rotary_big": "joint", "rotary_small": "rotary_joint", "ring": "joint_hub",       "solid_circle": "end_effector",  "rect": "arm_link"},
    "robot_arm":     {"rotary_big": "joint", "rotary_small": "rotary_joint", "ring": "joint_hub",       "solid_circle": "end_effector",  "rect": "arm_link"},
    "medical":       {"rotary_big": "joint", "rotary_small": "rotary_joint", "ring": "joint_hub",       "solid_circle": "instrument",    "rect": "frame_section"},
    "smart_light":   {"rotary_big": "reflector", "rotary_small": "lens",     "ring": "shade_rim",       "solid_circle": "bulb",          "rect": "fixture_plate"},
    "smart_device":  {"rotary_big": "speaker_driver", "rotary_small": "button","ring": "grille",        "solid_circle": "screen_or_btn", "rect": "faceplate"},
    "marine":        {"rotary_big": "propeller", "rotary_small": "thruster", "ring": "propeller_duct",  "solid_circle": "sonar_dome",    "rect": "hull_panel"},
    "space":         {"rotary_big": "thruster", "rotary_small": "nozzle",    "ring": "coupling_ring",   "solid_circle": "sensor_window", "rect": "body_panel"},
    "extreme":       {"rotary_big": "wheel_or_track", "rotary_small": "actuator","ring": "joint_hub",   "solid_circle": "sensor_pod",    "rect": "armor_plate"},
    "unknown":       {"rotary_big": "circular_feature", "rotary_small": "small_circular_feature",
                      "ring": "ring_feature",    "solid_circle": "round_spot",    "rect": "flat_surface"},
}

# Lines get renamed too
_CATEGORY_LINE_MAP = {
    "drone":         {"horizontal_frame": "drone_arm", "vertical_structure": "landing_gear", "diagonal_strut": "support_strut"},
    "ground_robot":  {"horizontal_frame": "chassis_rail", "vertical_structure": "body_column", "diagonal_strut": "support_brace"},
    "legged":        {"horizontal_frame": "body_frame", "vertical_structure": "leg_segment", "diagonal_strut": "leg_link"},
    "humanoid":      {"horizontal_frame": "shoulder_line", "vertical_structure": "torso_axis", "diagonal_strut": "limb_segment"},
    "home_robot":    {"horizontal_frame": "body_ridge", "vertical_structure": "body_axis", "diagonal_strut": "edge_line"},
    "robot_arm":     {"horizontal_frame": "base_plate", "vertical_structure": "arm_segment", "diagonal_strut": "link_bar"},
    "industrial":    {"horizontal_frame": "base_plate", "vertical_structure": "arm_segment", "diagonal_strut": "link_bar"},
    "smart_light":   {"horizontal_frame": "fixture_edge", "vertical_structure": "stem_or_pole", "diagonal_strut": "bracket_arm"},
    "smart_device":  {"horizontal_frame": "faceplate_edge", "vertical_structure": "side_edge", "diagonal_strut": "bezel_line"},
}


def _relabel_components_for_category(image_analysis, category: str):
    """Rename raw detected components to more accurate, category-specific names."""
    if not category or not image_analysis or not image_analysis.components:
        return
    part_map = _CATEGORY_PART_MAP.get(category, _CATEGORY_PART_MAP["unknown"])
    line_map = _CATEGORY_LINE_MAP.get(category, {})

    img_w = image_analysis.image_size[0] if image_analysis.image_size else 100

    for comp in image_analysis.components:
        raw = comp.name
        # Circles
        if comp.shape == "circle":
            # Infer size bucket from bounding box
            bw = comp.bounding_box[2] if comp.bounding_box else 0
            rel = bw / max(img_w, 1)
            if raw == "rotor_assembly":
                comp.name = part_map["rotary_big"]
            elif raw == "wheel_or_joint":
                comp.name = part_map["rotary_small"] if rel < 0.10 else part_map["rotary_big"]
            elif raw == "led_indicator":
                # LEDs stay as LEDs except for lights where they become "bulb"
                if category == "smart_light":
                    comp.name = part_map["solid_circle"]
                # else keep led_indicator
            elif raw == "sensor_or_button":
                # Keep sensor_or_button but clarify for some categories
                if category == "smart_device":
                    comp.name = "button_or_sensor"
            elif raw == "circular_component":
                comp.name = part_map["ring"] if rel > 0.15 else part_map["solid_circle"]
        elif comp.shape == "rectangle":
            if raw == "panel_or_plate":
                comp.name = part_map["rect"]
        elif comp.shape == "line":
            if raw in line_map:
                comp.name = line_map[raw]


class _SimulatedAnalysis:
    """Minimal analysis object for simulated scans (name generation only)."""
    def __init__(self, device_type, category):
        self.rotary_count = {"drone": 4, "ground_robot": 4, "marine": 2}.get(category, 0)
        self.linear_count = {"robot_arm": 5, "industrial": 5, "legged": 6, "humanoid": 8}.get(category, 0)
        self.components = [None] * max(self.rotary_count, self.linear_count, 3)
        self.dominant_colors = []
        self.estimated_dimensions_cm = [30, 30, 15]
        # Set specific rotary counts for known drone types
        if "hexacopter" in device_type:
            self.rotary_count = 6
        elif "octocopter" in device_type:
            self.rotary_count = 8
        elif "quadcopter" in device_type or "racing" in device_type:
            self.rotary_count = 4
        elif "fixed_wing" in device_type or "flying_wing" in device_type or "blimp" in device_type:
            self.rotary_count = 0
        elif "single_rotor" in device_type or "helicopter" in device_type:
            self.rotary_count = 1
        elif "coaxial" in device_type:
            self.rotary_count = 2
        elif "vtol" in device_type:
            self.rotary_count = 4  # VTOL has rotors but is named differently


_SIMULATED_DEVICE_TYPES = [
    ("quadcopter_drone", "drone"),
    ("wheeled_robot", "ground_robot"),
    ("robot_arm_6dof", "robot_arm"),
    ("humanoid_robot", "humanoid"),
    ("hexapod_robot", "legged"),
    ("robotic_vacuum", "home_robot"),
    ("underwater_rov", "marine"),
    ("smart_speaker", "smart_device"),
    ("surgical_robot", "medical"),
    ("amr_warehouse", "warehouse"),
    ("hexacopter_drone", "drone"),
    ("tracked_robot", "ground_robot"),
    ("quadruped_robot", "legged"),
    ("fixed_wing_drone", "drone"),
    ("collaborative_cobot", "robot_arm"),
]


class VisualPhysicsEngine:
    def __init__(self):
        self.image_analyzer = ImageAnalyzer()
        self.device_classifier = DeviceClassifier()
        self.physics_engine = PhysicsEngine()
        self.analysis_count = 0
        self._sim_index = 0

    def analyze_image(self, image_bytes: bytes) -> dict:
        total_start = time.time()
        self.analysis_count += 1
        stages = {}

        # Stage 1: Image Analysis (8 internal passes)
        t = time.time()
        image_analysis = self.image_analyzer.analyze(image_bytes)
        stages["image_analysis"] = round((time.time() - t) * 1000, 1)

        # Stage 2: Device Classification
        t = time.time()
        classification = self.device_classifier.classify(image_analysis)
        stages["classification"] = round((time.time() - t) * 1000, 1)

        # Stage 2b: Relabel components based on what we actually classified
        # (prevents every circle being called "rotor" when it's not a drone)
        _relabel_components_for_category(image_analysis, classification.device_category)

        # Stage 3: Physics Estimation
        t = time.time()
        physics = self.physics_engine.analyze(image_analysis, classification)
        stages["physics"] = round((time.time() - t) * 1000, 1)

        total_ms = round((time.time() - total_start) * 1000, 1)

        return {
            "analysis_id": f"vpe-{self.analysis_count:04d}",
            "processing_time_ms": total_ms,
            "stage_times_ms": stages,
            "pass_times_ms": image_analysis.pass_times_ms,
            "classification": classification.to_dict(),
            "image_analysis": image_analysis.to_dict(),
            "physics": physics.to_dict(),
            "summary": self._summary(classification, physics, image_analysis, total_ms),
        }

    def analyze_base64(self, b64_string: str) -> dict:
        if "," in b64_string:
            b64_string = b64_string.split(",", 1)[1]
        return self.analyze_image(base64.b64decode(b64_string))

    def analyze_file(self, filepath: str) -> dict:
        with open(filepath, "rb") as f:
            return self.analyze_image(f.read())

    def simulate_scan(self, device_type_hint: str = None) -> dict:
        """
        Generate a simulated VPE scan result without a real image.
        Cycles through different device types each call, or uses the hint if provided.
        """
        from .device_fingerprints import DEVICE_FINGERPRINTS

        if device_type_hint and device_type_hint in DEVICE_FINGERPRINTS:
            dtype = device_type_hint
            fp = DEVICE_FINGERPRINTS[dtype]
            cat = fp["category"]
        else:
            # Cycle through simulated device types
            dtype, cat = _SIMULATED_DEVICE_TYPES[self._sim_index % len(_SIMULATED_DEVICE_TYPES)]
            fp = DEVICE_FINGERPRINTS[dtype]
            self._sim_index += 1

        self.analysis_count += 1

        # Build a synthetic classification
        generated_name = self.device_classifier._generate_device_name(
            dtype, fp, _SimulatedAnalysis(dtype, cat)
        )

        classification_dict = {
            "device_type": dtype,
            "device_category": cat,
            "confidence": 0.85,
            "description": fp["description"],
            "generated_name": generated_name,
            "all_scores": {dtype: 10.0},
            "classification_reasons": ["Simulated scan — no image analysis performed"],
        }

        # Minimal image analysis for mesh generation
        image_analysis_dict = {
            "geometry": {"estimated_dimensions_cm": [30, 30, 15]},
            "color_profile": {
                "estimated_material": "matte_plastic",
                "dominant_colors": [
                    {"hex": "#333333", "name": "dark gray"},
                    {"hex": "#666666", "name": "gray"},
                ],
            },
            "structural": {"components": []},
        }

        # Minimal physics
        physics_dict = {
            "physical_properties": {
                "estimated_mass_kg": 1.0,
                "drag_coefficient": 0.5,
                "structural_integrity": 0.8,
                "center_of_gravity": {"x": 0, "y": 0, "z": 0},
                "estimated_inertia": {"Ixx": 0.01, "Iyy": 0.01, "Izz": 0.01},
            },
            "scores": {"overall": 70, "efficiency": 65, "stability": 75, "maneuverability": 60},
            "operational_params": {},
            "optimizations": [],
        }

        return {
            "analysis_id": f"vpe-sim-{self.analysis_count:04d}",
            "processing_time_ms": 0,
            "stage_times_ms": {},
            "pass_times_ms": {},
            "classification": classification_dict,
            "image_analysis": image_analysis_dict,
            "physics": physics_dict,
            "summary": {
                "device": fp["description"],
                "confidence": "85%",
                "overall_score": "70/100",
                "key_findings": [
                    f"Simulated scan: {generated_name}",
                    f"Category: {cat}",
                    "No image analysis — using simulated device profile",
                ],
                "top_recommendations": [],
            },
            "simulated": True,
        }

    def _summary(self, cls, phys, img, total_ms) -> dict:
        top_opts = phys.optimizations[:3]

        device_label = cls.generated_name if cls.generated_name else cls.description
        findings = [
            f"Identified as: {device_label} ({cls.confidence:.0%} confidence)",
            f"Estimated mass: {phys.estimated_mass_kg:.3f} kg",
            f"Material: {img.estimated_material}",
            f"Structural integrity: {phys.structural_integrity_score:.0%}",
            f"Performance score: {phys.overall_score:.0f}/100",
            f"Detected {len(img.components)} structural components",
            f"Analysis completed in {total_ms:.0f}ms across 8 passes",
        ]

        if cls.classification_reasons:
            # Top 3 positive reasons
            positive = [r for r in cls.classification_reasons if r.startswith("+")][:3]
            if positive:
                findings.append("Classification driven by: " + "; ".join(
                    r.split(": ")[-1] for r in positive
                ))

        return {
            "device": cls.description,
            "confidence": f"{cls.confidence:.0%}",
            "overall_score": f"{phys.overall_score:.0f}/100",
            "key_findings": findings,
            "top_recommendations": [
                {"title": o["title"], "impact": o["expected_improvement"]}
                for o in top_opts
            ],
        }
