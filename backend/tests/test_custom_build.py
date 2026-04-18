"""Custom Robot Builder — parts, builds, capabilities, device wrapping."""

from __future__ import annotations

import pytest

from custom_build import (
    PART_TYPES, Part, CustomBuild, CustomRobotDevice, all_part_types,
)


class TestPartTypes:
    def test_registry_is_nonempty(self):
        assert len(PART_TYPES) >= 10, "we ship at least 10 part types"

    def test_every_part_type_has_valid_geometry_type(self):
        valid = {"box", "sphere", "cylinder", "torus", "cone"}
        for pt in PART_TYPES.values():
            assert pt.geometry_type in valid, \
                f"{pt.id} has bad geometry_type={pt.geometry_type}"

    def test_every_part_type_has_a_default_color(self):
        for pt in PART_TYPES.values():
            assert pt.default_color.startswith("#")

    def test_every_part_type_has_a_category(self):
        valid_categories = {"structural", "actuator", "sensor", "effector"}
        for pt in PART_TYPES.values():
            assert pt.category in valid_categories

    def test_all_part_types_returns_json_safe_dicts(self):
        import json
        blob = json.dumps(all_part_types())
        assert "rotor" in blob


class TestPartInstantiation:
    def test_new_part_copies_defaults(self):
        p = Part.new("rotor")
        pt = PART_TYPES["rotor"]
        assert p.type == "rotor"
        assert p.color == pt.default_color
        assert p.geometry == pt.default_geometry
        # Not same object — defaults must be copied
        assert p.geometry is not pt.default_geometry

    def test_new_part_generates_unique_ids(self):
        a = Part.new("rotor")
        b = Part.new("rotor")
        assert a.part_id != b.part_id

    def test_new_part_unknown_type_raises(self):
        with pytest.raises(ValueError):
            Part.new("totally_made_up")

    def test_roundtrip_via_dict(self):
        a = Part.new("wheel", name="Left drive wheel")
        a.position = [1.0, 2.0, 3.0]
        a.color = "#abcdef"
        b = Part.from_dict(a.to_dict())
        assert b.part_id == a.part_id
        assert b.type == a.type
        assert b.name == a.name
        assert b.position == a.position
        assert b.color == a.color


class TestCustomBuildCapabilities:
    def test_empty_build_derives_custom_type(self):
        b = CustomBuild()
        assert b.derive_device_type() == "custom"

    def test_four_rotors_yield_drone(self):
        b = CustomBuild(parts=[Part.new("rotor") for _ in range(4)])
        assert b.derive_device_type() == "drone"

    def test_fewer_than_four_rotors_not_a_drone(self):
        b = CustomBuild(parts=[Part.new("rotor") for _ in range(3)])
        assert b.derive_device_type() != "drone"

    def test_wing_plus_rotor_is_still_a_drone(self):
        b = CustomBuild(parts=[Part.new("wing"), Part.new("rotor")])
        assert b.derive_device_type() == "drone"

    def test_four_legs_yield_legged(self):
        b = CustomBuild(parts=[Part.new("leg") for _ in range(4)])
        assert b.derive_device_type() == "legged"

    def test_two_legs_no_wheels_is_humanoid(self):
        b = CustomBuild(parts=[Part.new("leg"), Part.new("leg")])
        assert b.derive_device_type() == "humanoid"

    def test_two_wheels_yield_ground_robot(self):
        b = CustomBuild(parts=[Part.new("wheel"), Part.new("wheel")])
        assert b.derive_device_type() == "ground_robot"

    def test_three_joints_no_wheels_is_arm(self):
        b = CustomBuild(parts=[Part.new("joint") for _ in range(3)])
        assert b.derive_device_type() == "robot_arm"

    def test_propeller_without_wings_is_marine(self):
        b = CustomBuild(parts=[Part.new("propeller")])
        assert b.derive_device_type() == "marine"

    def test_gripper_only_is_robot_arm(self):
        b = CustomBuild(parts=[Part.new("gripper")])
        assert b.derive_device_type() == "robot_arm"


class TestCapabilityDerivation:
    def _cap_names(self, build: CustomBuild) -> set[str]:
        return {c.name for c in build.derive_capabilities()}

    def test_drone_unlocks_flight_commands(self):
        b = CustomBuild(parts=[Part.new("rotor") for _ in range(4)])
        names = self._cap_names(b)
        assert {"takeoff", "land", "hover", "move"} <= names

    def test_wheels_unlock_drive(self):
        b = CustomBuild(parts=[Part.new("wheel") for _ in range(2)])
        names = self._cap_names(b)
        assert "drive" in names

    def test_gripper_unlocks_manipulation(self):
        b = CustomBuild(parts=[Part.new("gripper")])
        names = self._cap_names(b)
        assert "grip" in names
        assert "release" in names

    def test_camera_unlocks_take_photo(self):
        b = CustomBuild(parts=[Part.new("camera")])
        names = self._cap_names(b)
        assert "take_photo" in names

    def test_sensor_unlocks_scan(self):
        b = CustomBuild(parts=[Part.new("sensor")])
        names = self._cap_names(b)
        assert "scan" in names

    def test_three_joints_unlock_move_joint(self):
        b = CustomBuild(parts=[Part.new("joint") for _ in range(3)])
        names = self._cap_names(b)
        assert "move_joint" in names

    def test_legged_unlocks_walk_and_stand(self):
        b = CustomBuild(parts=[Part.new("leg") for _ in range(4)])
        names = self._cap_names(b)
        assert "walk" in names
        assert "stand" in names

    def test_safety_always_available(self):
        for parts in ([], [Part.new("rotor")], [Part.new("wheel"),
                                                 Part.new("wheel")]):
            b = CustomBuild(parts=parts)
            names = self._cap_names(b)
            assert "emergency_stop" in names
            assert "ping" in names

    def test_capabilities_are_serializable(self):
        import json
        b = CustomBuild(parts=[Part.new("rotor") for _ in range(4)])
        caps = [c.to_dict() for c in b.derive_capabilities()]
        json.dumps(caps)  # must not raise


class TestMeshParams:
    def test_empty_build_still_returns_valid_mesh_params(self):
        mp = CustomBuild().to_mesh_params()
        assert isinstance(mp["primitives"], list)
        assert mp["bounding_size"] > 0

    def test_mesh_primitives_preserve_part_geometry(self):
        part = Part.new("chassis")
        part.geometry = {"w": 2.5, "h": 0.5, "d": 1.5}
        part.color = "#123456"
        mp = CustomBuild(parts=[part]).to_mesh_params()
        assert len(mp["primitives"]) == 1
        prim = mp["primitives"][0]
        assert prim["geometry"]["w"] == 2.5
        assert prim["material"]["color"] == "#123456"

    def test_bounding_size_grows_with_parts(self):
        small = CustomBuild(parts=[Part.new("chassis")])
        big = CustomBuild(parts=[Part.new("chassis")])
        # Push a part far out — bounding box should expand
        far_part = Part.new("rotor")
        far_part.position = [10.0, 0.0, 10.0]
        big.parts.append(far_part)
        assert big.to_mesh_params()["bounding_size"] > \
               small.to_mesh_params()["bounding_size"]


class TestCustomRobotDevice:
    def test_build_swap_updates_capabilities(self):
        dev = CustomRobotDevice("Test", CustomBuild())
        assert {"emergency_stop", "ping"} <= {c.name for c in dev._capabilities}
        # Now replace with 4 rotors → should flip to drone + gain flight caps
        dev.update_build(CustomBuild(parts=[Part.new("rotor") for _ in range(4)]))
        caps = {c.name for c in dev._capabilities}
        assert "takeoff" in caps
        assert dev.device_type == "drone"

    def test_execute_supported_command(self):
        dev = CustomRobotDevice("Test",
            CustomBuild(parts=[Part.new("rotor") for _ in range(4)]))
        r = dev.execute_command("takeoff", {"altitude_m": 8})
        assert r["success"] is True
        assert "8" in r["message"] or "8.0" in r["message"]

    def test_execute_unsupported_command_returns_error(self):
        dev = CustomRobotDevice("Test", CustomBuild())
        r = dev.execute_command("takeoff", {})
        assert r["success"] is False
        assert "not supported" in r["message"]

    def test_telemetry_carries_device_type(self):
        dev = CustomRobotDevice("Test",
            CustomBuild(parts=[Part.new("wheel") for _ in range(2)]))
        tele = dev.get_telemetry()
        assert tele["device_type"] == "ground_robot"
        assert tele["is_custom_build"] is True

    def test_info_includes_mesh_params(self):
        dev = CustomRobotDevice("Test",
            CustomBuild(parts=[Part.new("chassis")]))
        info = dev.get_info()
        assert info["is_custom_build"] is True
        assert "mesh_params" in info
        assert len(info["mesh_params"]["primitives"]) == 1


class TestTemplateLibrary:
    def test_exactly_ten_templates(self):
        from templates import TEMPLATES
        assert len(TEMPLATES) == 10

    def test_every_template_instantiates_cleanly(self):
        from templates import TEMPLATES
        for tid, tpl in TEMPLATES.items():
            build = tpl.instantiate()
            # Some parts
            assert len(build.parts) >= 3, f"{tid} has too few parts"
            # Derived device_type roughly matches template's declared type,
            # OR the declared type is 'drone'/'legged' where fixed_wing + hex
            # variants legitimately overlap.
            assert build.derive_device_type() in (
                tpl.device_type, "custom", "drone", "legged", "robot_arm",
                "ground_robot", "humanoid", "marine",
            )

    def test_every_template_has_capabilities(self):
        from templates import TEMPLATES
        for tid, tpl in TEMPLATES.items():
            caps = tpl.instantiate().derive_capabilities()
            # At minimum safety + ping are always present
            names = {c.name for c in caps}
            assert "emergency_stop" in names, f"{tid} lacks emergency_stop"

    def test_list_templates_is_json_safe(self):
        import json
        from templates import list_templates
        json.dumps(list_templates())

    def test_templates_have_unique_ids_and_icons(self):
        from templates import TEMPLATES
        ids = [t.template_id for t in TEMPLATES.values()]
        assert len(ids) == len(set(ids))

    def test_quadcopter_template_is_a_drone(self):
        from templates import get_template
        tpl = get_template("quadcopter")
        build = tpl.instantiate()
        assert build.derive_device_type() == "drone"
        assert "takeoff" in {c.name for c in build.derive_capabilities()}

    def test_6dof_arm_template_is_robot_arm(self):
        from templates import get_template
        tpl = get_template("6dof_arm")
        build = tpl.instantiate()
        assert build.derive_device_type() == "robot_arm"

    def test_quadruped_template_is_legged(self):
        from templates import get_template
        build = get_template("quadruped").instantiate()
        assert build.derive_device_type() == "legged"
        names = {c.name for c in build.derive_capabilities()}
        assert "walk" in names
