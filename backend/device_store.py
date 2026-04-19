"""
OMNIX Device Store — Session-based in-memory persistence.

Stores analyzed device profiles from VPE so they persist across
the application (VPE → Motion 3D → Control Panel).

Each device profile contains:
  - VPE analysis results (classification, physics, image features)
  - Generated 3D mesh parameters for Three.js rendering
  - Multi-image merge state
"""

import time
import uuid


class DeviceStore:
    """In-memory store for VPE-analyzed device profiles."""

    def __init__(self):
        self.profiles = {}       # id → profile dict
        self.active_id = None    # Currently selected device for Motion 3D

    def store(self, vpe_result: dict, mesh_params: dict, thumbnail_b64: str = None) -> dict:
        """Store a VPE result as a device profile. Returns the profile."""
        profile_id = f"vpe-{uuid.uuid4().hex[:8]}"

        cat = vpe_result["classification"]["device_category"]
        dtype = vpe_result["classification"]["device_type"]
        desc = vpe_result["classification"]["description"]

        # Use the VPE-generated descriptive name if available, otherwise fallback
        generated_name = vpe_result["classification"].get("generated_name", "")
        if generated_name:
            same_cat_count = sum(1 for p in self.profiles.values()
                                 if p.get("device_category") == cat) + 1
            default_name = f"{generated_name} #{same_cat_count}" if same_cat_count > 1 else generated_name
        else:
            cat_label = cat.replace("_", " ").title() if cat and cat != "unknown" else "Device"
            same_cat_count = sum(1 for p in self.profiles.values()
                                 if p.get("device_category") == cat) + 1
            default_name = f"Scanned {cat_label} #{same_cat_count}"

        profile = {
            "id": profile_id,
            "created_at": time.time(),
            "updated_at": time.time(),
            "image_count": 1,

            # User-editable display name (defaults to auto-generated)
            "name": default_name,
            "custom_description": None,  # None = use auto description

            # Classification
            "device_type": dtype,
            "device_category": cat,
            "description": desc,
            "confidence": vpe_result["classification"]["confidence"],

            # Physics
            "physics": vpe_result["physics"],
            "estimated_mass_kg": vpe_result["physics"]["physical_properties"]["estimated_mass_kg"],
            "material": vpe_result["image_analysis"].get("color_profile", {}).get("estimated_material", "unknown"),

            # Dimensions from image analysis
            "dimensions_cm": vpe_result["image_analysis"].get("geometry", {}).get("estimated_dimensions_cm", [20, 20, 10]),

            # 3D mesh params for Three.js
            "mesh_params": mesh_params,

            # Thumbnail for UI
            "thumbnail": thumbnail_b64,

            # Full VPE result for reference
            "vpe_result": vpe_result,
        }

        self.profiles[profile_id] = profile

        # Auto-set as active if it's the first one
        if self.active_id is None:
            self.active_id = profile_id

        return profile

    def update_with_image(self, profile_id: str, new_vpe_result: dict, new_mesh_params: dict) -> dict:
        """Merge a new image analysis into an existing profile for multi-image refinement."""
        if profile_id not in self.profiles:
            return None

        profile = self.profiles[profile_id]
        old_count = profile["image_count"]
        new_count = old_count + 1

        # Weighted merge: new analysis blended with existing
        # More images → higher confidence
        old_conf = profile["confidence"]
        new_conf = new_vpe_result["classification"]["confidence"]
        merged_conf = (old_conf * old_count + new_conf) / new_count

        profile.update({
            "updated_at": time.time(),
            "image_count": new_count,
            "confidence": merged_conf,
            "mesh_params": new_mesh_params,
            "physics": new_vpe_result["physics"],
            "vpe_result": new_vpe_result,
        })

        return profile

    def set_active(self, profile_id: str) -> bool:
        if profile_id in self.profiles:
            self.active_id = profile_id
            return True
        return False

    def get_active(self) -> dict:
        if self.active_id and self.active_id in self.profiles:
            return self.profiles[self.active_id]
        return None

    def get_profile(self, profile_id: str) -> dict:
        return self.profiles.get(profile_id)

    def get_all(self) -> list:
        """Return all profiles (without full vpe_result to keep it lightweight)."""
        result = []
        for pid, p in self.profiles.items():
            result.append({
                "id": p["id"],
                "name": p.get("name") or p["description"],
                "device_type": p["device_type"],
                "device_category": p["device_category"],
                "description": p.get("custom_description") or p["description"],
                "confidence": p["confidence"],
                "image_count": p["image_count"],
                "material": p["material"],
                "estimated_mass_kg": p["estimated_mass_kg"],
                "dimensions_cm": p["dimensions_cm"],
                "mesh_params": p["mesh_params"],
                "thumbnail": p["thumbnail"],
                "is_active": pid == self.active_id,
                "created_at": p["created_at"],
            })
        return sorted(result, key=lambda x: -x["created_at"])

    def rename(self, profile_id: str, new_name: str = None,
               new_description: str = None, new_category: str = None) -> bool:
        """Update user-editable fields of a profile."""
        if profile_id not in self.profiles:
            return False
        p = self.profiles[profile_id]
        if new_name is not None and new_name.strip():
            p["name"] = new_name.strip()
        if new_description is not None and new_description.strip():
            p["custom_description"] = new_description.strip()
        if new_category is not None and new_category.strip():
            p["device_category"] = new_category.strip()
        p["updated_at"] = time.time()
        return True

    def remove(self, profile_id: str) -> bool:
        if profile_id in self.profiles:
            del self.profiles[profile_id]
            if self.active_id == profile_id:
                self.active_id = next(iter(self.profiles), None)
            return True
        return False
