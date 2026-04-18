"""Simulation runner — executes scenarios, records iterations, updates physics."""

from __future__ import annotations

import pytest

from simulation import run_scenario, list_scenarios, get_scenario


class TestScenarios:
    def test_every_device_type_has_at_least_one_scenario(self):
        for dt in ("drone", "ground_robot", "robot_arm"):
            lst = list_scenarios(dt)
            assert lst, f"No scenarios for {dt}"
            for s in lst:
                assert dt in s["device_types"]

    def test_get_unknown_scenario_returns_none(self):
        assert get_scenario("no_such_scenario") is None

    def test_scenario_has_callable_builders(self):
        s = get_scenario("hover")
        assert s is not None
        assert callable(s.command_at)
        assert callable(s.reference_at)


class TestRunnerOnDrone:
    def test_hover_run_produces_iteration(self, fresh_workspace_store, fake_drone):
        ws = fresh_workspace_store.ensure(fake_drone)
        it = run_scenario(ws, "hover", workspace_store=fresh_workspace_store)
        assert it["scenario"] == "hover"
        assert "metrics" in it
        assert "trajectory" in it
        assert len(it["trajectory"]) > 0
        # Each trajectory point has a timestamp
        assert all("t" in p for p in it["trajectory"])

    def test_metrics_are_in_expected_ranges(self, fresh_workspace_store, fake_drone):
        ws = fresh_workspace_store.ensure(fake_drone)
        it = run_scenario(ws, "hover", workspace_store=fresh_workspace_store)
        m = it["metrics"]
        for k in ("stability", "smoothness", "power_efficiency", "tracking_score", "overall"):
            assert 0.0 <= m[k] <= 1.0, f"{k} out of [0,1]: {m[k]}"
        assert m["tracking_error_m"] >= 0

    def test_iteration_numbering_is_sequential(self, fresh_workspace_store, fake_drone):
        ws = fresh_workspace_store.ensure(fake_drone)
        for i in range(3):
            it = run_scenario(ws, "hover", workspace_store=fresh_workspace_store)
            assert it["number"] == i + 1

    def test_physics_confidence_rises_across_runs(self, fresh_workspace_store, fake_drone):
        ws = fresh_workspace_store.ensure(fake_drone)
        confidences = []
        for _ in range(5):
            it = run_scenario(ws, "hover", workspace_store=fresh_workspace_store)
            confidences.append(it["physics_after"]["confidence"])
        assert confidences[-1] > confidences[0]


class TestRunnerOnRover:
    def test_straight_line_moves_forward(self, fresh_workspace_store, fake_rover):
        ws = fresh_workspace_store.ensure(fake_rover)
        it = run_scenario(ws, "straight_line", workspace_store=fresh_workspace_store)
        # Last point should be ahead of first
        first = it["trajectory"][0]
        last = it["trajectory"][-1]
        assert last["x"] > first["x"]

    def test_u_turn_changes_heading(self, fresh_workspace_store, fake_rover):
        ws = fresh_workspace_store.ensure(fake_rover)
        it = run_scenario(ws, "u_turn", workspace_store=fresh_workspace_store)
        # Heading should have changed substantially
        first = it["trajectory"][0]
        last = it["trajectory"][-1]
        assert abs(last["theta"] - first["theta"]) > 1.0   # radians


class TestRunnerOnArm:
    def test_reach_pose_joints_approach_target(self, fresh_workspace_store, fake_arm):
        ws = fresh_workspace_store.ensure(fake_arm)
        it = run_scenario(ws, "reach_pose", workspace_store=fresh_workspace_store)
        last = it["trajectory"][-1]
        target = {"j0": 45, "j1": -30, "j2": 60}
        for k, v in target.items():
            if k in last.get("joints", {}):
                assert abs(last["joints"][k] - v) < 5.0, f"{k} didn't reach target"


class TestRunnerErrorHandling:
    def test_unknown_scenario_raises(self, fresh_workspace_store, fake_drone):
        ws = fresh_workspace_store.ensure(fake_drone)
        with pytest.raises(ValueError, match="Unknown scenario"):
            run_scenario(ws, "nope", workspace_store=fresh_workspace_store)

    def test_wrong_device_type_raises(self, fresh_workspace_store, fake_drone):
        ws = fresh_workspace_store.ensure(fake_drone)
        # reach_pose is arm-only
        with pytest.raises(ValueError, match="for.*robot_arm"):
            run_scenario(ws, "reach_pose", workspace_store=fresh_workspace_store)
