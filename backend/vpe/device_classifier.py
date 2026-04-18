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
    all_scores: dict = None
    classification_reasons: list = None

    def to_dict(self):
        return {
            "device_type": self.device_type,
            "device_category": self.device_category,
            "confidence": round(self.confidence, 3),
            "description": self.description,
            "all_scores": {k: round(v, 3) for k, v in (self.all_scores or {}).items()},
            "classification_reasons": self.classification_reasons or [],
        }


class DeviceClassifier:
    """Classify images into one of 100 device types using fingerprint matching."""

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

        if not scores or max(scores.values()) == 0:
            return DeviceClassification(
                device_type="unknown_device",
                device_category="unknown",
                confidence=0.0,
                description="Could not classify — try a clearer photo with the device centered.",
                all_scores=scores,
                classification_reasons=["No device type matched the visual features"],
            )

        # Rank all types
        ranked = sorted(scores.items(), key=lambda x: -x[1])
        best_type, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0

        fp = DEVICE_FINGERPRINTS[best_type]

        # Confidence: absolute score vs. max possible, plus margin over runner-up
        max_possible = sum(
            f.get("weight", 2.0) for f in fp.get("positive", {}).values()
            if isinstance(f, dict)
        )
        abs_conf = min(1.0, best_score / max(max_possible * 0.6, 1))
        margin_conf = min(1.0, (best_score - second_score) / max(best_score, 1) * 2)
        confidence = abs_conf * 0.6 + margin_conf * 0.4

        return DeviceClassification(
            device_type=best_type,
            device_category=fp["category"],
            confidence=confidence,
            description=fp["description"],
            all_scores=scores,
            classification_reasons=reasons.get(best_type, []),
        )

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
