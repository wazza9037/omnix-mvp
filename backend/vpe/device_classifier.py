"""
OMNIX Visual Physics Engine — Device Classifier (v3)

Uses 100 device fingerprints from device_fingerprints.py.

Classification pipeline:
  1. Required features gate — disqualify if not met
  2. Positive scoring — weighted range/value matching
  3. Negative scoring — penalties for mismatching features
  4. Structural boost — data-driven from structural_hints in fingerprints
  5. Confidence = absolute_score * 0.6 + margin_over_second * 0.4
"""

from dataclasses import dataclass
from typing import Optional
import math

from .device_fingerprints import DEVICE_FINGERPRINTS


@dataclass
class DeviceClassification:
    device_type: str
    device_category: str
    confidence: float
    description: str
    generated_name: str = ""
    all_scores: dict = None
    classification_reasons: list = None

    def to_dict(self):
        return {
            "device_type": self.device_type,
            "device_category": self.device_category,
            "confidence": round(self.confidence, 3),
            "description": self.description,
            "generated_name": self.generated_name,
            "all_scores": {k: round(v, 3) for k, v in (self.all_scores or {}).items()},
            "classification_reasons": self.classification_reasons or [],
        }


class DeviceClassifier:
    """Classify images into one of 100 device types using fingerprint matching
    supplemented by a robust aspect-ratio heuristic."""

    # ── Aspect-ratio heuristic mapping ──
    # PRIMARY: image aspect ratio → likely category + default type
    _HEURISTIC_MAP = [
        # (ar_min, ar_max, category, device_type, description, base_confidence)
        (2.5, 99.0, "drone", "fixed_wing_drone", "Fixed-wing aerial vehicle", 0.70),
        (1.5, 2.5,  "ground_robot", "wheeled_robot", "Wheeled ground platform", 0.65),
        (0.7, 1.5,  "drone", "quadcopter_drone", "Multirotor aerial drone", 0.60),
        (0.5, 0.7,  "robot_arm", "robot_arm_6dof", "Articulated robotic arm", 0.65),
        (0.0, 0.5,  "humanoid", "humanoid_robot", "Humanoid robot", 0.65),
    ]

    def _heuristic_classify(self, analysis) -> tuple:
        """Aspect-ratio + edge density + color heuristic classification.

        Returns (device_type, category, description, confidence, reasons).
        """
        ar = getattr(analysis, "aspect_ratio", 1.0)
        edge_density = getattr(analysis, "edge_density", 0.0)
        dark_ratio = getattr(analysis, "dark_ratio", 0.0)
        rotary_count = getattr(analysis, "rotary_count", 0)
        linear_count = getattr(analysis, "linear_count", 0)
        circularity = getattr(analysis, "circularity", 0.5)
        solidity = getattr(analysis, "solidity", 0.5)
        nc = len(getattr(analysis, "components", []))

        reasons = []

        # Step 1: PRIMARY — aspect ratio
        cat = "unknown"
        dtype = "unknown_device"
        desc = "Unknown device"
        conf = 0.5

        for ar_min, ar_max, h_cat, h_dtype, h_desc, h_conf in self._HEURISTIC_MAP:
            if ar_min <= ar < ar_max:
                cat = h_cat
                dtype = h_dtype
                desc = h_desc
                conf = h_conf
                reasons.append(f"Aspect ratio {ar:.2f} → {cat}")
                break

        # Step 2: SECONDARY — structural evidence can refine the category
        if rotary_count >= 4 and ar >= 0.6 and ar <= 1.8:
            cat = "drone"
            dtype = "quadcopter_drone" if rotary_count <= 5 else (
                "hexacopter_drone" if rotary_count <= 7 else "octocopter_drone"
            )
            desc = "Multirotor aerial drone"
            conf = min(0.80, conf + 0.10)
            reasons.append(f"{rotary_count} rotary elements → multirotor drone")
        elif rotary_count >= 2 and ar > 1.2 and linear_count > 3:
            cat = "ground_robot"
            dtype = "wheeled_robot"
            desc = "Wheeled ground robot"
            conf = min(0.80, conf + 0.08)
            reasons.append(f"{rotary_count} wheels + {linear_count} linear → ground robot")
        elif linear_count >= 4 and ar < 0.8 and rotary_count < 2:
            cat = "robot_arm"
            dtype = "robot_arm_6dof"
            desc = "Articulated robotic arm"
            conf = min(0.80, conf + 0.10)
            reasons.append(f"{linear_count} linear elements, tall shape → robot arm")

        # Step 3: TERTIARY — edge density and color refine confidence
        if edge_density > 0.15:
            # High complexity → probably a complex device
            if cat in ("drone", "humanoid", "legged"):
                conf = min(0.80, conf + 0.05)
                reasons.append(f"High edge density {edge_density:.3f} → complex device")
        elif edge_density < 0.03:
            # Very low complexity → simple device
            if cat not in ("smart_light", "smart_device"):
                # Might be a simple smart device instead
                if solidity > 0.80 and circularity > 0.5 and nc < 3:
                    cat = "smart_device"
                    dtype = "smart_speaker"
                    desc = "Smart device"
                    conf = 0.60
                    reasons.append(f"Low edge density + high solidity → smart device")

        # Dark/metallic images are likely real device photos
        if dark_ratio > 0.3:
            conf = min(0.80, conf + 0.03)
            reasons.append(f"Dark image (ratio {dark_ratio:.2f}) → likely real device photo")

        # Clamp confidence to honest range
        conf = max(0.45, min(0.80, conf))

        return dtype, cat, desc, conf, reasons

    def classify(self, analysis) -> DeviceClassification:
        scores = {}
        reasons = {}

        for device_type, fp in DEVICE_FINGERPRINTS.items():
            # Gate: required features must all pass
            if not self._check_required(analysis, fp.get("required", {})):
                scores[device_type] = 0
                reasons[device_type] = ["DISQUALIFIED: missing required features"]
                continue

            pos_score, pos_reasons = self._score_positive(analysis, fp.get("positive", {}))
            neg_score, neg_reasons = self._score_negative(analysis, fp.get("negative", {}))

            total = max(0, pos_score - neg_score)

            # Data-driven structural boost from fingerprint hints
            boost, boost_reasons = self._structural_boost(analysis, fp.get("structural_hints", {}))
            total += boost

            all_reasons = pos_reasons + neg_reasons
            if boost_reasons:
                all_reasons += boost_reasons

            scores[device_type] = total
            reasons[device_type] = all_reasons

        # ── Heuristic fallback / blend ──
        h_dtype, h_cat, h_desc, h_conf, h_reasons = self._heuristic_classify(analysis)

        # Find the best fingerprint match
        fp_best_type = None
        fp_best_score = 0
        fp_second_score = 0
        fp_confidence = 0.0

        if scores and max(scores.values()) > 0:
            ranked = sorted(scores.items(), key=lambda x: -x[1])
            fp_best_type, fp_best_score = ranked[0]
            fp_second_score = ranked[1][1] if len(ranked) > 1 else 0

            fp_fp = DEVICE_FINGERPRINTS[fp_best_type]
            max_possible = sum(
                f.get("weight", 2.0) for f in fp_fp.get("positive", {}).values()
                if isinstance(f, dict)
            )
            abs_conf = min(1.0, fp_best_score / max(max_possible * 0.6, 1))
            margin_conf = min(1.0, (fp_best_score - fp_second_score) / max(fp_best_score, 1) * 2)
            fp_confidence = abs_conf * 0.6 + margin_conf * 0.4

        # Decision: use fingerprint result if it has a clear winner (conf > 0.5 AND
        # good margin), otherwise use heuristic, otherwise blend.
        fp_has_clear_winner = (
            fp_best_type is not None
            and fp_confidence > 0.50
            and fp_best_score > fp_second_score * 1.3
        )

        # If fingerprint and heuristic agree on category, boost confidence
        fp_cat = DEVICE_FINGERPRINTS[fp_best_type]["category"] if fp_best_type else None
        categories_agree = fp_cat == h_cat

        if fp_has_clear_winner and categories_agree:
            # Strong agreement — use fingerprint type with boosted confidence
            best_type = fp_best_type
            fp = DEVICE_FINGERPRINTS[best_type]
            confidence = min(0.85, fp_confidence * 0.6 + h_conf * 0.4 + 0.05)
            final_reasons = reasons.get(best_type, []) + [
                f"Heuristic agrees: {h_cat} (AR={getattr(analysis, 'aspect_ratio', 0):.2f})"
            ]
        elif fp_has_clear_winner:
            # Fingerprint is confident but heuristic disagrees — use fingerprint
            # but slightly lower confidence
            best_type = fp_best_type
            fp = DEVICE_FINGERPRINTS[best_type]
            confidence = min(0.75, fp_confidence * 0.8)
            final_reasons = reasons.get(best_type, [])
        elif h_conf > 0.55:
            # Fingerprint is weak — rely on heuristic
            best_type = h_dtype
            if best_type in DEVICE_FINGERPRINTS:
                fp = DEVICE_FINGERPRINTS[best_type]
            else:
                # Find any fingerprint in the heuristic category
                fp = None
                for dt, fpp in DEVICE_FINGERPRINTS.items():
                    if fpp["category"] == h_cat:
                        best_type = dt
                        fp = fpp
                        break
                if fp is None:
                    best_type = h_dtype
                    fp = {"category": h_cat, "description": h_desc}
            confidence = h_conf
            final_reasons = h_reasons
        else:
            # Both weak — use fingerprint if available, else heuristic
            if fp_best_type:
                best_type = fp_best_type
                fp = DEVICE_FINGERPRINTS[best_type]
                confidence = max(fp_confidence, h_conf) * 0.8
                final_reasons = reasons.get(best_type, []) + h_reasons
            else:
                return DeviceClassification(
                    device_type="unknown_device",
                    device_category="unknown",
                    confidence=0.0,
                    description="Could not classify — try a clearer photo.",
                    all_scores=scores,
                    classification_reasons=["No device type matched"],
                )

        # Clamp final confidence to honest range
        confidence = max(0.35, min(0.85, confidence))

        generated_name = self._generate_device_name(
            best_type, fp, analysis
        )

        return DeviceClassification(
            device_type=best_type,
            device_category=fp["category"],
            confidence=confidence,
            description=fp.get("description", h_desc),
            generated_name=generated_name,
            all_scores=scores,
            classification_reasons=final_reasons,
        )

    # ── Device Name Generation ──

    def _generate_device_name(self, device_type: str, fingerprint: dict, analysis) -> str:
        """Generate an accurate, descriptive name based on what was actually detected."""
        cat = fingerprint["category"]
        rc = analysis.rotary_count
        lc = analysis.linear_count
        nc = len(analysis.components)

        # Determine color/size descriptors
        color_desc = self._get_color_descriptor(analysis)
        size_desc = self._get_size_descriptor(analysis)

        prefix = f"{size_desc} {color_desc}".strip() if (size_desc or color_desc) else ""

        # Category-specific naming based on actual detected features
        if cat == "drone":
            name = self._name_drone(device_type, rc, prefix)
        elif cat == "ground_robot":
            name = self._name_ground_robot(device_type, rc, prefix)
        elif cat in ("robot_arm", "industrial"):
            name = self._name_arm(device_type, lc, prefix)
        elif cat == "humanoid":
            name = self._name_humanoid(device_type, nc, prefix)
        elif cat == "legged":
            name = self._name_legged(device_type, lc, prefix)
        elif cat == "home_robot":
            name = self._name_home_robot(device_type, prefix)
        elif cat == "service_robot":
            name = self._name_service_robot(device_type, prefix)
        elif cat == "warehouse":
            name = self._name_warehouse(device_type, prefix)
        elif cat == "medical":
            name = self._name_medical(device_type, prefix)
        elif cat in ("smart_light", "smart_device"):
            name = self._name_smart_device(device_type, prefix)
        elif cat == "marine":
            name = self._name_marine(device_type, prefix)
        elif cat in ("space", "extreme"):
            name = self._name_special(device_type, prefix)
        else:
            name = f"{prefix} Unidentified Device".strip()

        return name

    def _get_color_descriptor(self, analysis) -> str:
        """Extract dominant color as a descriptor."""
        colors = getattr(analysis, 'dominant_colors', [])
        if not colors:
            return ""
        # Use the first dominant color's name if available
        first = colors[0] if colors else None
        if not first:
            return ""
        # Try to get a name from the color
        if isinstance(first, dict):
            hex_val = first.get("hex", "")
        elif hasattr(first, "hex"):
            hex_val = first.hex
        else:
            return ""
        return self._hex_to_color_name(hex_val)

    def _hex_to_color_name(self, hex_val: str) -> str:
        """Map hex color to a basic color name."""
        if not hex_val or len(hex_val) < 7:
            return ""
        try:
            r = int(hex_val[1:3], 16)
            g = int(hex_val[3:5], 16)
            b = int(hex_val[5:7], 16)
        except (ValueError, IndexError):
            return ""

        brightness = (r + g + b) / 3
        if brightness < 50:
            return "Black"
        if brightness > 220 and max(r, g, b) - min(r, g, b) < 30:
            return "White"
        if brightness > 180 and max(r, g, b) - min(r, g, b) < 30:
            return "Gray"

        # Determine hue
        max_c = max(r, g, b)
        if max_c == 0:
            return "Black"
        if r > g and r > b:
            if g > 150:
                return "Orange" if r > 200 else "Yellow"
            return "Red"
        if g > r and g > b:
            return "Green"
        if b > r and b > g:
            return "Blue"
        if r > 200 and b > 200:
            return "Purple"
        return ""

    def _get_size_descriptor(self, analysis) -> str:
        """Estimate size descriptor from analysis dimensions."""
        dims = getattr(analysis, 'estimated_dimensions_cm', None)
        if not dims or not isinstance(dims, (list, tuple)) or len(dims) < 2:
            return ""
        max_dim = max(dims[:2])
        if max_dim < 10:
            return "Small"
        if max_dim > 60:
            return "Large"
        return ""

    def _name_drone(self, device_type: str, rotary_count: int, prefix: str) -> str:
        # Check device_type keywords FIRST (more specific), then fall back to rotor count
        if "fixed_wing" in device_type:
            drone_type = "Fixed-Wing"
        elif "flying_wing" in device_type:
            drone_type = "Flying Wing"
        elif "vtol" in device_type:
            drone_type = "VTOL Hybrid"
        elif "helicopter" in device_type or "single_rotor" in device_type:
            drone_type = "Helicopter"
        elif "coaxial" in device_type:
            drone_type = "Coaxial"
        elif "blimp" in device_type:
            drone_type = "Airship"
        elif "nano" in device_type:
            drone_type = "Nano"
        elif "racing" in device_type:
            drone_type = "Racing Quadcopter"
        # Fall back to rotor count for generic multi-rotors
        elif rotary_count >= 8:
            drone_type = "Octocopter"
        elif rotary_count >= 6:
            drone_type = "Hexacopter"
        elif rotary_count >= 3:
            drone_type = "Quadcopter"
        else:
            drone_type = "Drone"

        # Add usage context from device_type
        usage = ""
        if "camera" in device_type:
            usage = "Camera "
        elif "delivery" in device_type:
            usage = "Delivery "
        elif "agricultural" in device_type:
            usage = "Agricultural "
        elif "tethered" in device_type:
            usage = "Tethered "
        elif "racing" in device_type and "Racing" not in drone_type:
            usage = "Racing "

        # Use "UAV" for fixed-wing military/large drones, "Drone" for others
        suffix = "UAV" if "fixed_wing" in device_type or "flying_wing" in device_type else "Drone"
        return f"{prefix} {usage}{drone_type} {suffix}".strip()

    def _name_ground_robot(self, device_type: str, rotary_count: int, prefix: str) -> str:
        if "tracked" in device_type:
            body = "Tracked Robot"
        elif "ball" in device_type or "spherical" in device_type:
            body = "Spherical Rolling Robot"
        elif "car" in device_type or "autonomous_car" in device_type:
            body = "Autonomous Vehicle"
        elif "lawnmower" in device_type:
            body = "Robotic Lawnmower"
        elif rotary_count >= 6:
            body = "Six-Wheeled Rover"
        elif rotary_count >= 4:
            body = "Four-Wheeled Platform"
        elif rotary_count >= 2:
            body = "Two-Wheeled Rover"
        else:
            body = "Ground Robot"

        if "delivery" in device_type:
            body = f"Delivery {body}"
        elif "security" in device_type or "patrol" in device_type:
            body = f"Security {body}"
        elif "bomb" in device_type or "disposal" in device_type:
            body = f"EOD {body}"
        elif "mars" in device_type or "planetary" in device_type:
            body = "Planetary Rover"
        elif "agv" in device_type or "warehouse" in device_type:
            body = "Warehouse AGV"

        return f"{prefix} {body}".strip()

    def _name_arm(self, device_type: str, linear_count: int, prefix: str) -> str:
        # Estimate DOF from linear elements
        dof = max(linear_count, 3)
        if dof > 7:
            dof = 7  # cap at realistic max

        if "scara" in device_type:
            body = "SCARA Arm"
        elif "delta" in device_type:
            body = "Delta Robot"
        elif "cobot" in device_type or "collaborative" in device_type:
            body = f"{dof}-DOF Collaborative Arm"
        elif "gripper" in device_type:
            body = "Robotic Gripper"
        elif "soft_gripper" in device_type:
            body = "Soft Robotic Gripper"
        elif "cable" in device_type:
            body = "Cable-Driven Arm"
        elif "welding" in device_type:
            body = "Welding Robot Arm"
        elif "painting" in device_type:
            body = "Painting Robot Arm"
        elif "palletizing" in device_type:
            body = "Palletizing Arm"
        elif "cnc" in device_type or "gantry" in device_type:
            body = "CNC Gantry Robot"
        else:
            body = f"{dof}-DOF Robotic Arm"

        return f"{prefix} {body}".strip()

    def _name_humanoid(self, device_type: str, component_count: int, prefix: str) -> str:
        if "torso" in device_type:
            body = "Upper-Body Humanoid"
        elif "exoskeleton" in device_type:
            body = "Robotic Exoskeleton"
        elif "hand" in device_type:
            body = "Robotic Hand"
        else:
            body = "Humanoid Robot"
        return f"{prefix} {body}".strip()

    def _name_legged(self, device_type: str, linear_count: int, prefix: str) -> str:
        if "snake" in device_type or "serpent" in device_type:
            body = "Snake Robot"
        elif "spider" in device_type:
            body = "Spider Robot"
        elif "hexapod" in device_type:
            body = "Hexapod Robot"
        elif "quadruped" in device_type or "dog" in device_type:
            body = "Quadruped Robot"
        elif "biped" in device_type:
            body = "Bipedal Walker"
        else:
            body = "Legged Robot"
        return f"{prefix} {body}".strip()

    def _name_home_robot(self, device_type: str, prefix: str) -> str:
        if "vacuum" in device_type:
            return f"{prefix} Robotic Vacuum".strip()
        if "mop" in device_type:
            return f"{prefix} Robotic Mop".strip()
        if "pool" in device_type:
            return f"{prefix} Pool Cleaning Robot".strip()
        if "window" in device_type:
            return f"{prefix} Window Cleaning Robot".strip()
        if "gutter" in device_type:
            return f"{prefix} Gutter Cleaning Robot".strip()
        if "pet" in device_type:
            return f"{prefix} Robot Pet".strip()
        if "toy" in device_type:
            return f"{prefix} Toy Robot".strip()
        return f"{prefix} Home Robot".strip()

    def _name_service_robot(self, device_type: str, prefix: str) -> str:
        if "butler" in device_type:
            return f"{prefix} Service Butler Robot".strip()
        if "telepresence" in device_type:
            return f"{prefix} Telepresence Robot".strip()
        if "cleaning" in device_type:
            return f"{prefix} Commercial Cleaning Robot".strip()
        if "cooking" in device_type:
            return f"{prefix} Cooking Robot".strip()
        if "reception" in device_type:
            return f"{prefix} Reception Robot".strip()
        return f"{prefix} Service Robot".strip()

    def _name_warehouse(self, device_type: str, prefix: str) -> str:
        if "forklift" in device_type:
            return f"{prefix} Autonomous Forklift".strip()
        if "conveyor" in device_type:
            return f"{prefix} Conveyor Sorting Robot".strip()
        if "amr" in device_type:
            return f"{prefix} Warehouse AMR".strip()
        if "pick" in device_type or "sorting" in device_type or "bin" in device_type:
            return f"{prefix} Pick-and-Place Robot".strip()
        if "packaging" in device_type:
            return f"{prefix} Packaging Robot".strip()
        return f"{prefix} Warehouse Robot".strip()

    def _name_medical(self, device_type: str, prefix: str) -> str:
        if "surgical" in device_type:
            return f"{prefix} Surgical Robot".strip()
        if "rehabilitation" in device_type:
            return f"{prefix} Rehabilitation Robot".strip()
        if "wheelchair" in device_type:
            return f"{prefix} Robotic Wheelchair".strip()
        if "prosthetic" in device_type:
            return f"{prefix} Robotic Prosthetic".strip()
        if "disinfection" in device_type:
            return f"{prefix} UV Disinfection Robot".strip()
        if "pharmacy" in device_type:
            return f"{prefix} Pharmacy Dispensing Robot".strip()
        if "care" in device_type:
            return f"{prefix} Care Robot".strip()
        if "lab" in device_type:
            return f"{prefix} Lab Automation Robot".strip()
        return f"{prefix} Medical Robot".strip()

    def _name_smart_device(self, device_type: str, prefix: str) -> str:
        if "light" in device_type or "bulb" in device_type:
            return f"{prefix} Smart Light".strip()
        if "led_strip" in device_type:
            return f"{prefix} LED Strip Controller".strip()
        if "speaker" in device_type:
            return f"{prefix} Smart Speaker".strip()
        if "thermostat" in device_type:
            return f"{prefix} Smart Thermostat".strip()
        if "camera" in device_type:
            return f"{prefix} Smart Camera".strip()
        if "display" in device_type:
            return f"{prefix} Smart Display".strip()
        if "lock" in device_type:
            return f"{prefix} Smart Lock".strip()
        if "doorbell" in device_type:
            return f"{prefix} Smart Doorbell".strip()
        if "plug" in device_type:
            return f"{prefix} Smart Plug".strip()
        if "switch" in device_type:
            return f"{prefix} Smart Switch".strip()
        return f"{prefix} Smart Device".strip()

    def _name_marine(self, device_type: str, prefix: str) -> str:
        if "rov" in device_type:
            return f"{prefix} Underwater ROV".strip()
        if "boat" in device_type:
            return f"{prefix} Autonomous Boat".strip()
        if "glider" in device_type:
            return f"{prefix} Underwater Glider".strip()
        if "fish" in device_type:
            return f"{prefix} Robotic Fish".strip()
        return f"{prefix} Marine Robot".strip()

    def _name_special(self, device_type: str, prefix: str) -> str:
        if "space_rover" in device_type:
            return f"{prefix} Planetary Rover".strip()
        if "satellite" in device_type:
            return f"{prefix} Satellite Servicing Robot".strip()
        if "mining" in device_type:
            return f"{prefix} Mining Robot".strip()
        if "firefighting" in device_type:
            return f"{prefix} Firefighting Robot".strip()
        return f"{prefix} Specialized Robot".strip()

    # ── Required Features Gate ──

    def _check_required(self, analysis, required: dict) -> bool:
        for key, expected in required.items():
            if key == "has_rotary_elements" and expected:
                if not analysis.has_rotary_elements:
                    return False
            elif key == "has_linear_elements" and expected:
                if not analysis.has_linear_elements:
                    return False
            elif key == "min_rotary_count":
                if analysis.rotary_count < expected:
                    return False
            elif key == "min_linear_count":
                if analysis.linear_count < expected:
                    return False
            elif key == "min_component_count":
                if len(analysis.components) < expected:
                    return False
            elif key == "solidity_min":
                if analysis.solidity < expected:
                    return False
            elif key == "solidity_max":
                if analysis.solidity > expected:
                    return False
            elif key == "circularity_min":
                if analysis.circularity < expected:
                    return False
            elif key == "circularity_max":
                if analysis.circularity > expected:
                    return False
            elif key == "aspect_ratio_min":
                if analysis.aspect_ratio < expected:
                    return False
            elif key == "aspect_ratio_max":
                if analysis.aspect_ratio > expected:
                    return False
            elif key == "complexity_max":
                if analysis.complexity > expected:
                    return False
        return True

    # ── Positive Scoring ──

    def _score_positive(self, analysis, features: dict):
        score = 0
        reasons = []

        for feat_name, spec in features.items():
            if not isinstance(spec, dict):
                continue
            weight = spec.get("weight", 1.0)
            reason = spec.get("reason", feat_name)

            value = self._get_value(analysis, feat_name)
            if value is None:
                continue

            if "range" in spec:
                low, high = spec["range"]
                if low <= value <= high:
                    mid = (low + high) / 2
                    half = (high - low) / 2
                    closeness = 1 - abs(value - mid) / max(half, 0.001) * 0.4
                    gained = weight * max(0.3, closeness)
                    score += gained
                    reasons.append(f"+{gained:.1f} {feat_name}={value:.2f} in [{low},{high}]: {reason}")

            elif "equals" in spec:
                if value == spec["equals"]:
                    score += weight
                    reasons.append(f"+{weight:.1f} {feat_name}={value}: {reason}")

            elif "values" in spec:
                if value in spec["values"]:
                    score += weight
                    reasons.append(f"+{weight:.1f} {feat_name}={value}: {reason}")

        return score, reasons

    # ── Negative Scoring ──

    def _score_negative(self, analysis, features: dict):
        penalty = 0
        reasons = []

        for feat_name, spec in features.items():
            if not isinstance(spec, dict):
                continue
            pen = spec.get("penalty", 1.0)
            reason = spec.get("reason", feat_name)

            value = self._get_value(analysis, feat_name)
            if value is None:
                continue

            if "above" in spec and isinstance(value, (int, float)):
                if value > spec["above"]:
                    overshoot = (value - spec["above"]) / max(spec["above"], 0.01)
                    actual_pen = pen * min(1.5, 0.5 + overshoot)
                    penalty += actual_pen
                    reasons.append(f"-{actual_pen:.1f} {feat_name}={value:.2f} > {spec['above']}: {reason}")

            elif "below" in spec and isinstance(value, (int, float)):
                if value < spec["below"]:
                    undershoot = (spec["below"] - value) / max(spec["below"], 0.01)
                    actual_pen = pen * min(1.5, 0.5 + undershoot)
                    penalty += actual_pen
                    reasons.append(f"-{actual_pen:.1f} {feat_name}={value:.2f} < {spec['below']}: {reason}")

            elif "equals" in spec:
                if value == spec["equals"]:
                    penalty += pen
                    reasons.append(f"-{pen:.1f} {feat_name}={value}: {reason}")

        return penalty, reasons

    # ── Data-Driven Structural Boost ──

    def _structural_boost(self, analysis, hints: dict):
        """
        Interpret structural_hints from each fingerprint to give component-
        based bonuses or penalties.  This is completely data-driven — no
        per-device-type hardcoding needed.

        Supported hint keys:
          rotary_min   — min rotary components for main boost
          linear_min   — min linear components for main boost
          component_min — min total components for boost
          boost        — score to add when structural evidence matches
          rotary_boost — extra bonus if rotary_min also met (on top of boost)
          max_components — max components allowed (simple devices)
          simple_boost — bonus when component count ≤ max_components and solid
        """
        if not hints:
            return 0, []

        boost = 0
        reasons = []
        rc = analysis.rotary_count
        lc = analysis.linear_count
        nc = len(analysis.components)

        main_boost = hints.get("boost", 0)
        rotary_min = hints.get("rotary_min")
        linear_min = hints.get("linear_min")
        component_min = hints.get("component_min")
        max_components = hints.get("max_components")
        simple_boost = hints.get("simple_boost", 0)
        extra_rotary_boost = hints.get("rotary_boost", 0)

        # ── Main structural evidence check ──
        # Both rotary_min and linear_min specified → need both
        if rotary_min is not None and linear_min is not None:
            if rc >= rotary_min and lc >= linear_min:
                boost += main_boost
                reasons.append(
                    f"+{main_boost:.1f} STRUCTURAL: {rc} rotary (>={rotary_min}) "
                    f"+ {lc} linear (>={linear_min}) components detected"
                )
                if extra_rotary_boost and rc >= rotary_min:
                    boost += extra_rotary_boost
                    reasons.append(f"+{extra_rotary_boost:.1f} STRUCTURAL: rotary bonus")

        # Only rotary_min specified
        elif rotary_min is not None:
            if rc >= rotary_min:
                boost += main_boost
                reasons.append(
                    f"+{main_boost:.1f} STRUCTURAL: {rc} rotary components "
                    f"(>={rotary_min} required)"
                )
                if extra_rotary_boost:
                    boost += extra_rotary_boost
                    reasons.append(f"+{extra_rotary_boost:.1f} STRUCTURAL: rotary bonus")
            elif rc > 0 and rotary_min <= 4:
                # Partial credit for having some rotary elements
                partial = main_boost * 0.3
                boost += partial
                reasons.append(
                    f"+{partial:.1f} STRUCTURAL: {rc} rotary (partial, "
                    f"need {rotary_min})"
                )

        # Only linear_min specified
        elif linear_min is not None:
            if lc >= linear_min:
                boost += main_boost
                reasons.append(
                    f"+{main_boost:.1f} STRUCTURAL: {lc} linear components "
                    f"(>={linear_min} required)"
                )
            elif lc > 0 and linear_min <= 6:
                partial = main_boost * 0.3
                boost += partial
                reasons.append(
                    f"+{partial:.1f} STRUCTURAL: {lc} linear (partial, "
                    f"need {linear_min})"
                )

        # Component count threshold
        if component_min is not None:
            if nc >= component_min:
                boost += main_boost
                reasons.append(
                    f"+{main_boost:.1f} STRUCTURAL: {nc} total components "
                    f"(>={component_min} required)"
                )

        # ── Simple device check (lights, speakers, plugs) ──
        if max_components is not None:
            if nc <= max_components and analysis.solidity > 0.75:
                boost += simple_boost
                reasons.append(
                    f"+{simple_boost:.1f} STRUCTURAL: simple solid object "
                    f"({nc} components, solidity={analysis.solidity:.2f})"
                )
            elif nc > max_components + 3:
                # Penalize if way too complex for a simple device
                pen = simple_boost * 1.5
                boost -= pen
                reasons.append(
                    f"-{pen:.1f} STRUCTURAL: too complex ({nc} components) "
                    f"for simple device (max {max_components})"
                )

        return boost, reasons

    # ── Feature Value Extraction ──

    def _get_value(self, analysis, feat_name):
        if hasattr(analysis, feat_name):
            return getattr(analysis, feat_name)
        if feat_name == "min_rotary_count":
            return analysis.rotary_count
        if feat_name == "min_component_count":
            return len(analysis.components)
        return None
