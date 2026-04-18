"""Adaptive physics model — learning, confidence, and integration tests."""

from __future__ import annotations

import pytest

from simulation.physics import AdaptivePhysics, make_physics


class TestInitialization:
    def test_defaults_for_known_device_type(self):
        p = AdaptivePhysics("drone")
        assert p.device_type == "drone"
        assert p.samples == 0
        assert 0 <= p.confidence < 0.01
        assert "mass_kg" in p.params
        assert "thrust_to_weight" in p.params

    def test_defaults_for_ground_robot(self):
        p = AdaptivePhysics("ground_robot")
        assert "motor_efficiency" in p.params
        assert "max_speed_m_s" in p.params

    def test_unknown_device_falls_back_to_generic(self):
        p = AdaptivePhysics("total_garbage_type")
        assert p.samples == 0
        assert "mass_kg" in p.params    # generic has mass_kg


class TestLearning:
    def test_confidence_rises_monotonically(self):
        p = AdaptivePhysics("drone")
        confidences = []
        for _ in range(10):
            p.observe()
            confidences.append(p.confidence)
        # Each step should be ≥ the previous one
        assert confidences == sorted(confidences)
        assert confidences[-1] > confidences[0]
        # After 10 samples, confidence should be well above 0.5
        assert confidences[-1] > 0.5

    def test_params_converge_toward_truth(self):
        """Given enough iterations, learned params should approach the truth."""
        p = AdaptivePhysics("drone")
        initial_err = p.fit_error
        for _ in range(25):
            p.observe()
        # fit_error should drop substantially
        assert p.fit_error < initial_err * 0.3, (
            f"fit_error did not converge: {initial_err} -> {p.fit_error}"
        )

    def test_learn_rate_decays_with_samples(self):
        """Later observations should move params less than early ones."""
        p = AdaptivePhysics("drone")
        first_mass = p.params["mass_kg"]
        p.observe()
        early_delta = abs(p.params["mass_kg"] - first_mass)
        # Advance many samples
        for _ in range(50):
            p.observe()
        before = p.params["mass_kg"]
        p.observe()
        late_delta = abs(p.params["mass_kg"] - before)
        # Late update is noticeably smaller (modulo noise)
        assert late_delta <= early_delta * 1.5


class TestSnapshotRestore:
    def test_snapshot_contains_required_keys(self):
        p = AdaptivePhysics("drone")
        p.observe()
        snap = p.snapshot()
        for k in ("device_type", "params", "samples", "confidence", "fit_error", "last_updated"):
            assert k in snap

    def test_restore_roundtrips(self):
        p = AdaptivePhysics("drone")
        for _ in range(5):
            p.observe()
        snap = p.snapshot()
        q = make_physics("drone", snap)
        assert q.samples == snap["samples"]
        assert q.params == snap["params"]


class TestIntegrationSteps:
    def test_drone_altitude_pid_reaches_target(self):
        """Drone under target_alt_m command should approach that altitude."""
        p = AdaptivePhysics("drone")
        state = {"thrust": 0.0, "vel": [0.0, 0.0, 0.0], "pos": [0.0, 0.0, 0.0],
                 "energy_wh": 0.0, "battery_pct": 100.0}
        for _ in range(200):
            state = p.step_drone({"target_alt_m": 5.0}, 0.05, state)
        # Should settle near 5m
        assert 4.5 <= state["pos"][2] <= 5.5

    def test_drone_battery_drains_when_flying(self):
        p = AdaptivePhysics("drone")
        state = {"thrust": 0.0, "vel": [0.0, 0.0, 0.0], "pos": [0.0, 0.0, 0.0],
                 "energy_wh": 0.0, "battery_pct": 100.0}
        for _ in range(300):
            state = p.step_drone({"target_alt_m": 10.0}, 0.05, state)
        assert state["battery_pct"] < 100.0
        assert state["battery_pct"] > 30.0    # sanity: not fully drained

    def test_rover_forward_command_advances_x(self):
        p = AdaptivePhysics("ground_robot")
        state = {"vx": 0.0, "wz": 0.0, "x": 0.0, "y": 0.0, "theta": 0.0,
                 "energy_wh": 0.0, "battery_pct": 100.0}
        for _ in range(100):
            state = p.step_rover({"vx": 0.5, "wz": 0.0}, 0.05, state)
        assert state["x"] > 0.5   # moved forward
        assert abs(state["y"]) < 0.1   # stayed on axis

    def test_rover_max_speed_clamps(self):
        p = AdaptivePhysics("ground_robot")
        state = {"vx": 0.0, "wz": 0.0, "x": 0.0, "y": 0.0, "theta": 0.0,
                 "energy_wh": 0.0, "battery_pct": 100.0}
        for _ in range(200):
            state = p.step_rover({"vx": 100.0, "wz": 0.0}, 0.05, state)
        # Speed should be clamped well below what we commanded
        assert state["vx"] < p.params["max_speed_m_s"] * 1.05

    def test_arm_joint_tracks_target(self):
        p = AdaptivePhysics("robot_arm")
        state = {"joints": {"j0": 0.0, "j1": 0.0}}
        for _ in range(50):
            state = p.step_arm({"joints": {"j0": 45.0, "j1": -30.0}}, 0.05, state)
        assert abs(state["joints"]["j0"] - 45.0) < 1.0
        assert abs(state["joints"]["j1"] - (-30.0)) < 1.0

    def test_drone_wind_pushes_laterally(self):
        """A steady wind should pull a hovering drone downwind over time."""
        p = AdaptivePhysics("drone")
        state = {"thrust": 0.0, "vel": [0.0, 0.0, 0.0], "pos": [0.0, 0.0, 0.0],
                 "energy_wh": 0.0, "battery_pct": 100.0}
        for _ in range(100):
            state = p.step_drone({"target_alt_m": 5.0, "wind_m_s": [2.0, 0.0, 0.0]},
                                 0.05, state)
        # With a +X wind, the drone should drift in +X
        assert state["pos"][0] > 0.2, f"no wind drift: {state['pos']}"

    def test_battery_curve_sags_at_low_soc(self):
        """Non-linear battery model: drain rate rises as SoC approaches 0."""
        p = AdaptivePhysics("drone")
        # High SoC: very slow drain
        s_full = {"thrust": p.params["mass_kg"] * 9.81, "vel": [0.0, 0.0, 0.0],
                  "pos": [0.0, 0.0, 5.0], "energy_wh": 0.0, "battery_pct": 100.0}
        s_full = p.step_drone({"target_alt_m": 5.0}, 0.5, s_full)
        drain_full = 100.0 - s_full["battery_pct"]

        # Very low SoC: noticeably faster drain (battery sag)
        start_energy = p.params["battery_wh"] * 0.9   # 10% SoC
        s_low = {"thrust": p.params["mass_kg"] * 9.81, "vel": [0.0, 0.0, 0.0],
                 "pos": [0.0, 0.0, 5.0], "energy_wh": start_energy,
                 "battery_pct": 10.0}
        s_low = p.step_drone({"target_alt_m": 5.0}, 0.5, s_low)
        drain_low = 10.0 - s_low["battery_pct"]
        # Low-SoC drain should be strictly greater (sag factor > 1)
        assert drain_low > drain_full

    def test_step_drone_batch_matches_scalar(self):
        """The vectorized and scalar integrators must produce the same result."""
        p = AdaptivePhysics("drone")
        init = {"thrust": 0.0, "vel": [0.0, 0.0, 0.0], "pos": [0.0, 0.0, 0.0],
                "energy_wh": 0.0, "battery_pct": 100.0}
        cmds = [{"target_alt_m": 5.0}] * 30
        # Scalar
        s = dict(init)
        scalar = []
        for c in cmds:
            s = p.step_drone(c, 0.05, s)
            scalar.append(s)
        # Batch
        batch = p.step_drone_batch(cmds, 0.05, init)
        # Both should end up at a comparable altitude (small float jitter)
        assert abs(scalar[-1]["pos"][2] - batch[-1]["pos"][2]) < 0.05
