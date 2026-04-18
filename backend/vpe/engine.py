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


class VisualPhysicsEngine:
    def __init__(self):
        self.image_analyzer = ImageAnalyzer()
        self.device_classifier = DeviceClassifier()
        self.physics_engine = PhysicsEngine()
        self.analysis_count = 0

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

    def _summary(self, cls, phys, img, total_ms) -> dict:
        top_opts = phys.optimizations[:3]

        findings = [
            f"Identified as: {cls.description} ({cls.confidence:.0%} confidence)",
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
