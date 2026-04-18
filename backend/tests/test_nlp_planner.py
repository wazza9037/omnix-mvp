"""Plan validator / annotator — waypoints, safety, estimates."""

from __future__ import annotations

import math
import pytest

from omnix.nlp import compile_to_plan, plan_and_validate
from omnix.nlp.models import IssueSeverity
from omnix.nlp.planner import plan_and_validate as _plan_validate


DRONE_CAPS = ["takeoff", "land", "hover", "move", "rotate", "return_home",
              "goto", "take_photo", "emergency_stop", "ping"]
ROVER_CAPS = ["drive", "rotate", "emergency_stop", "return_home", "ping"]
ARM_CAPS = ["move_joint", "grip", "release", "go_home", "emergency_stop"]


class TestWaypointAnnotation:
    def test_takeoff_sets_z(self):
        p = compile_to_plan("take off to 5m", "d1", "drone", DRONE_CAPS)
        plan_and_validate(p, "drone", capability_names=DRONE_CAPS)
        end = p.steps[0].expected_end_pos
        assert end[0] == pytest.approx(0.0)
        assert end[1] == pytest.approx(0.0)
        assert end[2] == pytest.approx(5.0)

    def test_sequence_chains_positions(self):
        p = compile_to_plan(
            "take off to 3m then move forward 4m then move right 2m",
            "d1", "drone", DRONE_CAPS)
        plan_and_validate(p, "drone", capability_names=DRONE_CAPS)
        # Start at origin
        assert p.steps[0].expected_start_pos == [0.0, 0.0, 0.0]
        # After takeoff, altitude = 3
        assert p.steps[0].expected_end_pos[2] == 3.0
        # After forward 4m (yaw=0): x=4
        assert p.steps[1].expected_end_pos[0] == pytest.approx(4.0)
        # After right 2m from (4, 0, 3): y = -2 (right is -y in our frame)
        assert p.steps[2].expected_end_pos[1] == pytest.approx(-2.0)

    def test_rotate_affects_subsequent_moves(self):
        p = compile_to_plan(
            "take off 5m then turn left 90 then move forward 3m",
            "d1", "drone", DRONE_CAPS)
        plan_and_validate(p, "drone", capability_names=DRONE_CAPS)
        last = p.steps[-1].expected_end_pos
        # After turning +90° and moving forward 3m: should be in +y direction
        assert last[0] == pytest.approx(0.0, abs=0.1)
        assert last[1] == pytest.approx(3.0, abs=0.1)

    def test_telemetry_seeds_cursor(self):
        p = compile_to_plan("fly forward 2m", "d1", "drone", DRONE_CAPS)
        _plan_validate(p, "drone",
            telemetry={"position": {"x": 10, "y": 5}, "altitude_m": 3, "yaw_deg": 0},
            capability_names=DRONE_CAPS)
        start = p.steps[0].expected_start_pos
        assert start[0] == pytest.approx(10.0)
        assert start[1] == pytest.approx(5.0)
        assert start[2] == pytest.approx(3.0)
        assert p.steps[0].expected_end_pos[0] == pytest.approx(12.0)

    def test_every_step_has_a_path(self):
        p = compile_to_plan(
            "take off then patrol a square of 2m then land",
            "d1", "drone", DRONE_CAPS)
        plan_and_validate(p, "drone", capability_names=DRONE_CAPS)
        for s in p.steps:
            assert isinstance(s.expected_path, list)
            assert len(s.expected_path) >= 2


class TestSafetyChecks:
    def test_altitude_cap_flagged(self):
        p = compile_to_plan("take off to 500m", "d1", "drone", DRONE_CAPS)
        plan_and_validate(p, "drone", capability_names=DRONE_CAPS,
                          max_altitude_m=100.0)
        assert any(i.code == "altitude_cap" and
                    i.severity == IssueSeverity.ERROR for i in p.issues)

    def test_distance_cap_flagged(self):
        p = compile_to_plan("fly forward 5000m", "d1", "drone", DRONE_CAPS)
        plan_and_validate(p, "drone", capability_names=DRONE_CAPS,
                          max_distance_m=500.0)
        assert any(i.code == "distance_cap" for i in p.issues)

    def test_joint_limit_flagged(self):
        p = compile_to_plan("move joint 0 to 500 degrees",
                             "a1", "robot_arm", ARM_CAPS)
        plan_and_validate(p, "robot_arm", capability_names=ARM_CAPS)
        assert any(i.code == "joint_limit" for i in p.issues)

    def test_safe_plan_has_no_errors(self):
        p = compile_to_plan("take off then land", "d1", "drone", DRONE_CAPS)
        plan_and_validate(p, "drone", capability_names=DRONE_CAPS)
        errors = [i for i in p.issues if i.severity == IssueSeverity.ERROR]
        assert not errors


class TestEstimates:
    def test_duration_summed(self):
        p = compile_to_plan("take off 5m then land", "d1", "drone", DRONE_CAPS)
        plan_and_validate(p, "drone", capability_names=DRONE_CAPS)
        # takeoff ≈ 2s, land 2.5s → >4s
        assert p.estimated_duration_s >= 4.0

    def test_battery_nonzero(self):
        p = compile_to_plan("take off 10m then land", "d1", "drone", DRONE_CAPS)
        plan_and_validate(p, "drone", capability_names=DRONE_CAPS)
        assert p.estimated_battery_pct > 0

    def test_large_plan_battery_warning(self):
        # Build an enormous plan manually to trigger the soft cap
        p = compile_to_plan("take off 10m", "d1", "drone", DRONE_CAPS)
        # duplicate the takeoff step 200 times
        base = p.steps[0]
        p.steps = [base] * 200
        plan_and_validate(p, "drone", capability_names=DRONE_CAPS)
        assert any(i.code == "battery_cost" for i in p.issues)
