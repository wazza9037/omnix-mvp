"""Rule-based NLP compiler — intent matching + parameter extraction."""

from __future__ import annotations

import pytest

from omnix.nlp import compile_to_plan
from omnix.nlp.models import IssueSeverity
from omnix.nlp.compiler import split_clauses, preprocess_loops, extract_battery_precheck
from omnix.nlp.patterns import extract_distance, extract_angle, extract_coords, extract_count


DRONE_CAPS = ["takeoff", "land", "hover", "move", "rotate", "return_home",
              "goto", "take_photo", "emergency_stop", "ping"]
ROVER_CAPS = ["drive", "rotate", "emergency_stop", "return_home", "ping"]
ARM_CAPS = ["move_joint", "grip", "release", "go_home", "emergency_stop", "ping"]


# ── Parameter extraction ──────────────────────────────────

class TestExtractors:
    def test_distance_meters(self):
        assert extract_distance("move 3 meters") == pytest.approx(3.0)
        assert extract_distance("5m") == pytest.approx(5.0)
        assert extract_distance("2.5 metres") == pytest.approx(2.5)

    def test_distance_cm_scales(self):
        assert extract_distance("50 cm") == pytest.approx(0.5)

    def test_distance_feet(self):
        d = extract_distance("6 feet")
        assert 1.8 < d < 1.9

    def test_distance_default(self):
        assert extract_distance("move forward") == 1.0

    def test_angle_degrees_and_radians(self):
        assert extract_angle("90 degrees") == pytest.approx(90.0)
        assert extract_angle("45°") == pytest.approx(45.0)
        assert extract_angle("1.5 radians") == pytest.approx(85.9, abs=0.2)

    def test_coords_2d_and_3d(self):
        assert extract_coords("go to (3, 4)") == [3.0, 4.0, 0.0]
        assert extract_coords("fly to (1.5, -2, 5)") == [1.5, -2.0, 5.0]
        assert extract_coords("nothing to see") is None

    def test_count(self):
        assert extract_count("patrol 3 times") == 3
        assert extract_count("do it 5x") == 5
        assert extract_count("loop twice") == 2
        assert extract_count("nothing here") == 1


# ── Clause splitting ──────────────────────────────────────

class TestSplitClauses:
    def test_then_splits(self):
        cls = split_clauses("take off then move forward then land")
        assert cls == ["take off", "move forward", "land"]

    def test_comma_then_splits(self):
        cls = split_clauses("take off, then hover 5 seconds, then land")
        assert len(cls) == 3

    def test_bare_and_splits_on_action_verb(self):
        cls = split_clauses("take off and hover at 3m")
        assert "take off" in cls
        assert any("hover" in c for c in cls)

    def test_bare_and_does_not_split_arbitrary(self):
        # "forward and back" is not split — neither side starts with a
        # recognized action verb
        cls = split_clauses("back and forth")
        assert cls == ["back and forth"]

    def test_semicolon_splits(self):
        cls = split_clauses("takeoff; land")
        assert cls == ["takeoff", "land"]

    def test_empty(self):
        assert split_clauses("") == []
        assert split_clauses("   ") == []


# ── Loop pre-processing ───────────────────────────────────

class TestPreprocessLoops:
    def test_strips_trailing_count(self):
        text, n = preprocess_loops("patrol a square 3 times")
        assert n == 3
        assert "3 times" not in text

    def test_default_is_one(self):
        text, n = preprocess_loops("take off")
        assert n == 1
        assert text == "take off"

    def test_caps_large_counts(self):
        _, n = preprocess_loops("spin 500 times")
        assert n <= 20


# ── Battery pre-check ─────────────────────────────────────

class TestBatteryPrecheck:
    def test_extracts_threshold(self):
        text, thr = extract_battery_precheck("if battery below 30% return home")
        assert thr == 30.0
        assert "battery" not in text.lower() or text.strip() == ""

    def test_leaves_remainder(self):
        text, thr = extract_battery_precheck(
            "if battery below 20% return home, then take off and fly forward")
        assert thr == 20.0
        assert "take off" in text.lower()

    def test_no_match(self):
        text, thr = extract_battery_precheck("take off")
        assert thr is None
        assert text == "take off"


# ── Drone compilation ─────────────────────────────────────

class TestDroneCompilation:
    def test_simple_takeoff(self):
        p = compile_to_plan("take off to 5m", "d1", "drone", DRONE_CAPS)
        assert not p.has_errors()
        assert [s.command for s in p.steps] == ["takeoff"]
        assert p.steps[0].params["altitude_m"] == 5.0

    def test_default_takeoff_altitude(self):
        p = compile_to_plan("take off", "d1", "drone", DRONE_CAPS)
        assert p.steps[0].params["altitude_m"] == 5.0

    def test_sequence_takeoff_then_land(self):
        p = compile_to_plan("take off then land", "d1", "drone", DRONE_CAPS)
        assert [s.command for s in p.steps] == ["takeoff", "land"]

    def test_bare_and_splits_actions(self):
        p = compile_to_plan("take off and hover 3 seconds", "d1", "drone", DRONE_CAPS)
        cmds = [s.command for s in p.steps]
        assert "takeoff" in cmds and "hover" in cmds

    def test_move_direction_and_distance(self):
        p = compile_to_plan("fly forward 10 meters", "d1", "drone", DRONE_CAPS)
        assert p.steps[0].command == "move"
        assert p.steps[0].params["direction"] == "forward"
        assert p.steps[0].params["distance_m"] == 10.0

    def test_compass_directions_map(self):
        p = compile_to_plan("fly north 5m", "d1", "drone", DRONE_CAPS)
        assert p.steps[0].params["direction"] == "forward"
        p = compile_to_plan("fly east 3m", "d1", "drone", DRONE_CAPS)
        assert p.steps[0].params["direction"] == "right"

    def test_rotate_left_right(self):
        p = compile_to_plan("turn left 90 degrees", "d1", "drone", DRONE_CAPS)
        assert p.steps[0].command == "rotate"
        assert p.steps[0].params["degrees"] > 0
        p = compile_to_plan("turn right 45 degrees", "d1", "drone", DRONE_CAPS)
        assert p.steps[0].params["degrees"] < 0

    def test_patrol_square_expands(self):
        p = compile_to_plan("patrol a square of 4 meters at 3m altitude",
                             "d1", "drone", DRONE_CAPS)
        assert len(p.steps) >= 5   # takeoff + 4 moves
        assert p.steps[0].command == "takeoff"
        assert p.steps[0].params["altitude_m"] == 3.0

    def test_patrol_with_count(self):
        p = compile_to_plan("patrol a square 3 times",
                             "d1", "drone", DRONE_CAPS)
        # 1 takeoff + 3*4 moves + 1 hover = 14 steps
        move_count = sum(1 for s in p.steps if s.command == "move")
        assert move_count == 12

    def test_return_home_rtl(self):
        for phrase in ("return home", "rtl", "come home"):
            p = compile_to_plan(phrase, "d1", "drone", DRONE_CAPS)
            assert p.steps[0].command == "return_home"

    def test_battery_precheck_prepended(self):
        p = compile_to_plan(
            "if battery below 25% return home, take off and fly forward 5m",
            "d1", "drone", DRONE_CAPS)
        assert p.steps[0].command == "_battery_precheck"
        assert p.steps[0].params["min_pct"] == 25.0

    def test_unparsed_fragment_recorded(self):
        p = compile_to_plan("gibberish that no one understands",
                             "d1", "drone", DRONE_CAPS)
        assert p.has_errors()
        assert any(i.code == "no_steps" for i in p.issues)


# ── Rover compilation ─────────────────────────────────────

class TestRoverCompilation:
    def test_drive_forward(self):
        p = compile_to_plan("drive forward 2m", "r1", "ground_robot", ROVER_CAPS)
        assert p.steps[0].command == "drive"
        assert p.steps[0].params["direction"] == "forward"

    def test_drive_up_coerces_to_forward(self):
        # Rovers can't fly — "drive up" should fall back to forward
        p = compile_to_plan("drive up 1m", "r1", "ground_robot", ROVER_CAPS)
        assert p.steps[0].params["direction"] == "forward"

    def test_stop_is_emergency(self):
        p = compile_to_plan("stop", "r1", "ground_robot", ROVER_CAPS)
        assert p.steps[0].command == "emergency_stop"

    def test_takeoff_not_available_on_rover(self):
        # Rover doesn't have "takeoff" as an intent
        p = compile_to_plan("take off", "r1", "ground_robot", ROVER_CAPS)
        # Either no steps OR if matched, should be flagged as unsupported
        if p.steps:
            assert any(i.code == "unsupported_command" for i in p.issues)
        else:
            assert p.has_errors()


# ── Arm compilation ───────────────────────────────────────

class TestArmCompilation:
    def test_grip_and_release(self):
        p = compile_to_plan("grip then release", "a1", "robot_arm", ARM_CAPS)
        cmds = [s.command for s in p.steps]
        assert "grip" in cmds and "release" in cmds

    def test_go_home(self):
        p = compile_to_plan("go home", "a1", "robot_arm", ARM_CAPS)
        assert p.steps[0].command == "go_home"

    def test_move_joint_with_angle(self):
        p = compile_to_plan("move joint 2 to 45 degrees",
                             "a1", "robot_arm", ARM_CAPS)
        assert p.steps[0].command == "move_joint"
        assert p.steps[0].params["joint_index"] == 2
        assert p.steps[0].params["angle_deg"] == 45.0

    def test_pick_at_expands(self):
        p = compile_to_plan("pick up the object at (0.3, 0, 0.2)",
                             "a1", "robot_arm", ARM_CAPS)
        cmds = [s.command for s in p.steps]
        # pick_at produces release, move_joint, grip, go_home
        assert "grip" in cmds
        assert "go_home" in cmds


# ── Capability check ──────────────────────────────────────

class TestCapabilityChecking:
    def test_flags_unsupported_commands(self):
        # Arm without 'grip' capability but user asks to grip
        p = compile_to_plan("grip", "a1", "robot_arm",
                             ["release", "go_home"])
        assert any(i.code == "unsupported_command" for i in p.issues)

    def test_accepts_when_cap_list_missing(self):
        # No caps provided → just accept everything
        p = compile_to_plan("takeoff", "d1", "drone", None)
        assert not p.has_errors()
