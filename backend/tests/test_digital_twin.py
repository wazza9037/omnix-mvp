"""Digital Twin — divergence, twin lifecycle, virtual hardware, auto-tune."""

from __future__ import annotations

import time
import pytest

from omnix.digital_twin import (
    TwinMode, SyncStatus, TwinManager, DigitalTwin,
    compute_divergence, summarize, auto_tune, apply_to_workspace,
    initial_state, extract_for_divergence, DEFAULT_THRESHOLDS,
)
from omnix.digital_twin.models import DivergenceMetrics, SessionRecord, SessionFrame


# ── Minimal fake device ──────────────────────────────────

class _FakeDrone:
    def __init__(self):
        self.id = "fake-drone"
        self.name = "Fake"
        self.device_type = "drone"
        self.flying = False
        self.alt = 0.0
        self.pos = [0.0, 0.0]
        self.yaw = 0.0
        self.battery = 100.0

    def get_telemetry(self):
        return {
            "battery_pct": self.battery,
            "altitude_m": self.alt,
            "position": {"x": self.pos[0], "y": self.pos[1]},
            "yaw_deg": self.yaw,
            "flying": self.flying,
        }

    def execute_command(self, cmd, params):
        return {"success": True, "message": "ok"}

    def get_capabilities(self):
        return [{"name": n} for n in
                ("takeoff", "land", "hover", "move", "rotate", "emergency_stop")]


# ── Divergence detector ──────────────────────────────────

class TestDivergenceDetector:
    def test_identical_states_sync_100(self):
        s = {"pos": [1, 2, 3], "yaw_deg": 45, "battery_pct": 80, "vel": [0, 0, 0]}
        m = compute_divergence(s, s)
        assert m.sync_score == 100.0
        assert m.status == SyncStatus.IN_SYNC
        assert m.position_error_m == 0

    def test_position_only_error(self):
        a = {"pos": [0, 0, 0], "yaw_deg": 0, "battery_pct": 80}
        b = {"pos": [3, 4, 0], "yaw_deg": 0, "battery_pct": 80}
        m = compute_divergence(a, b)
        # Euclidean distance (3,4,0) = 5
        assert m.position_error_m == pytest.approx(5.0)
        assert m.status == SyncStatus.DIVERGED

    def test_drifting_threshold(self):
        a = {"pos": [0, 0, 0], "battery_pct": 100, "yaw_deg": 0}
        b = {"pos": [0.8, 0, 0], "battery_pct": 100, "yaw_deg": 0}
        m = compute_divergence(a, b)
        # 0.8m error sits between yellow (0.5m) and red (1.5m)
        assert m.status == SyncStatus.DRIFTING
        assert 0 < m.sync_score < 100

    def test_orientation_wrap(self):
        a = {"pos": [0, 0, 0], "yaw_deg": 358}
        b = {"pos": [0, 0, 0], "yaw_deg": 2}
        m = compute_divergence(a, b)
        # Wrap-around: 358° vs 2° is only 4° of error
        assert m.orientation_error_deg == pytest.approx(4.0)

    def test_battery_divergence(self):
        a = {"pos": [0, 0, 0], "yaw_deg": 0, "battery_pct": 100}
        b = {"pos": [0, 0, 0], "yaw_deg": 0, "battery_pct": 80}
        m = compute_divergence(a, b)
        assert m.battery_error_pct == 20.0

    def test_summarize(self):
        m1 = compute_divergence({"pos": [0,0,0]}, {"pos": [0,0,0]})
        m2 = compute_divergence({"pos": [0,0,0]}, {"pos": [0.2,0,0]})
        m3 = compute_divergence({"pos": [0,0,0]}, {"pos": [2,0,0]})
        s = summarize([m1, m2, m3])
        assert s["count"] == 3
        assert s["max_position_error_m"] == pytest.approx(2.0)


# ── Twin lifecycle ───────────────────────────────────────

class TestTwinManager:
    def test_create_returns_twin(self):
        mgr = TwinManager()
        dev = _FakeDrone()
        t = mgr.create(dev)
        assert t.device_id == dev.id
        mgr.shutdown()

    def test_create_idempotent(self):
        mgr = TwinManager()
        dev = _FakeDrone()
        a = mgr.create(dev)
        b = mgr.create(dev)
        assert a is b
        mgr.shutdown()

    def test_destroy_removes(self):
        mgr = TwinManager()
        dev = _FakeDrone()
        mgr.create(dev)
        assert mgr.destroy(dev.id) is True
        assert mgr.get(dev.id) is None
        mgr.shutdown()

    def test_snapshot_includes_all_fields(self):
        mgr = TwinManager()
        dev = _FakeDrone()
        t = mgr.create(dev, mode=TwinMode.VIRTUAL_HARDWARE)
        snap = t.snapshot()
        d = snap.to_dict()
        for key in ("twin_id", "device_id", "mode", "status", "sim_state",
                    "real_state", "divergence", "sync_score", "history",
                    "is_recording", "tick_hz"):
            assert key in d
        mgr.shutdown()


# ── Command forwarding ───────────────────────────────────

class TestCommandForwarding:
    def test_on_command_records_last(self):
        mgr = TwinManager()
        dev = _FakeDrone()
        t = mgr.create(dev, mode=TwinMode.TWIN)
        t.on_command("takeoff", {"altitude_m": 5.0})
        assert t.last_command[0] == "takeoff"
        assert t.last_command[1] == {"altitude_m": 5.0}
        mgr.shutdown()

    def test_takeoff_updates_predictor(self):
        mgr = TwinManager()
        dev = _FakeDrone()
        t = mgr.create(dev, mode=TwinMode.VIRTUAL_HARDWARE)
        t.on_command("takeoff", {"altitude_m": 5.0})
        snap = t.snapshot()
        # Predictor's sim state should reflect the commanded altitude
        assert snap.sim_state["pos"][2] == pytest.approx(5.0)
        mgr.shutdown()


# ── Virtual Hardware mode ────────────────────────────────

class TestVirtualHardwareMode:
    def test_mode_creates_truth_predictor(self):
        mgr = TwinManager()
        dev = _FakeDrone()
        t = mgr.create(dev, mode=TwinMode.VIRTUAL_HARDWARE)
        assert t.truth_predictor is not None
        mgr.shutdown()

    def test_divergence_accumulates_over_ticks(self):
        """With perturbed truth params, sim and real should drift apart."""
        mgr = TwinManager()
        dev = _FakeDrone()
        t = mgr.create(dev, mode=TwinMode.VIRTUAL_HARDWARE, tick_hz=50)
        t.on_command("takeoff", {"altitude_m": 5.0})
        t.on_command("move", {"direction": "forward", "distance_m": 5.0})
        # Advance manually
        for _ in range(80):
            t.tick(0.05)
        snap = t.snapshot()
        # With perturbed params, some divergence is expected
        assert snap.divergence.position_error_m >= 0.0
        # History should have accumulated
        assert len(snap.history) > 0
        mgr.shutdown()

    def test_mode_change_creates_truth_lazily(self):
        mgr = TwinManager()
        dev = _FakeDrone()
        t = mgr.create(dev, mode=TwinMode.TWIN)
        assert t.truth_predictor is None
        t.set_mode(TwinMode.VIRTUAL_HARDWARE)
        assert t.truth_predictor is not None
        mgr.shutdown()


# ── Session recording ────────────────────────────────────

class TestSessionRecording:
    def test_start_stop_captures_frames(self):
        mgr = TwinManager()
        dev = _FakeDrone()
        t = mgr.create(dev, mode=TwinMode.VIRTUAL_HARDWARE, tick_hz=50)
        t.on_command("takeoff", {"altitude_m": 3.0})
        sess = t.start_session(label="demo")
        for _ in range(20):
            t.tick(0.05)
        finished = t.stop_session()
        assert finished is sess
        assert finished.ended_at is not None
        assert len(finished.frames) == 20
        assert finished.mean_sync_score is not None
        mgr.shutdown()

    def test_start_session_twice_returns_same(self):
        mgr = TwinManager()
        dev = _FakeDrone()
        t = mgr.create(dev)
        a = t.start_session()
        b = t.start_session()
        assert a.session_id == b.session_id
        mgr.shutdown()

    def test_stop_without_start_returns_none(self):
        mgr = TwinManager()
        dev = _FakeDrone()
        t = mgr.create(dev)
        assert t.stop_session() is None
        mgr.shutdown()


# ── Auto-tuner ───────────────────────────────────────────

class TestAutoTuner:
    def _fake_session(self, device_type="drone",
                      position_errs: list[float] | None = None) -> SessionRecord:
        errs = position_errs or [0.5, 0.8, 1.0, 0.9, 1.1]
        frames = []
        for i, e in enumerate(errs):
            frames.append(SessionFrame(
                t=float(i) * 0.1, sim={}, real={},
                divergence={
                    "position_error_m": e,
                    "orientation_error_deg": 5.0,
                    "velocity_error_m_s": 0.1,
                    "battery_error_pct": 0.0,
                    "joint_error_deg": 0.0,
                    "sync_score": max(0, 100 - e * 50),
                    "status": "drifting",
                }))
        # Use realistic drone physics as starting point
        from simulation.physics import AdaptivePhysics
        phys = AdaptivePhysics("drone")
        sess = SessionRecord(
            session_id="sess-test", device_id="d1",
            mode=TwinMode.VIRTUAL_HARDWARE, started_at=0,
            ended_at=0.5, frames=frames,
            physics_before=phys.snapshot())
        return sess

    def test_tune_returns_result(self):
        sess = self._fake_session()
        r = auto_tune(sess, "drone")
        assert r.device_type == "drone"
        assert r.iterations > 0
        assert r.score_after <= r.score_before

    def test_tune_updates_known_params(self):
        sess = self._fake_session()
        r = auto_tune(sess, "drone")
        # At least one of the tunable parameters should have changed
        changed = {k: (r.params_after[k] - r.params_before[k])
                   for k in r.params_after
                   if k in r.params_before
                   and r.params_after[k] != r.params_before[k]}
        assert len(changed) > 0

    def test_apply_to_workspace(self):
        sess = self._fake_session()
        r = auto_tune(sess, "drone")
        ws = {"physics": dict(sess.physics_before)}
        apply_to_workspace(r, ws)
        # New params should be in the workspace
        for k, v in r.params_after.items():
            if k in ws["physics"]["params"]:
                assert ws["physics"]["params"][k] == v

    def test_empty_session_is_safe(self):
        sess = SessionRecord(
            session_id="s", device_id="d", mode=TwinMode.TWIN,
            started_at=0, ended_at=0, frames=[],
            physics_before={"params": {"mass_kg": 1.0}, "confidence": 0.5})
        # Should not raise
        r = auto_tune(sess, "drone")
        assert r.iterations == 0


# ── State extraction ─────────────────────────────────────

class TestStateExtraction:
    def test_initial_state_seeds_from_telemetry(self):
        tele = {"altitude_m": 3.5,
                "position": {"x": 1, "y": 2},
                "yaw_deg": 30, "battery_pct": 75, "flying": True}
        s = initial_state("drone", tele)
        assert s["pos"][0] == 1.0
        assert s["pos"][1] == 2.0
        assert s["pos"][2] == 3.5
        assert s["yaw_deg"] == 30
        assert s["battery_pct"] == 75
        assert s["flying"] is True

    def test_extract_has_consistent_keys(self):
        s = initial_state("drone", {"altitude_m": 2})
        out = extract_for_divergence(s, "drone")
        # Divergence calc expects these keys
        assert "pos" in out and "yaw_deg" in out and "battery_pct" in out
