"""Executor — threaded step-by-step run, stop control, iteration bridging."""

from __future__ import annotations

import time
import pytest

from omnix.nlp import compile_to_plan, plan_and_validate, iteration_from_state
from omnix.nlp.executor import ExecutorRegistry
from omnix.nlp.models import ExecutionStatus, StepStatus


# Minimal fake device that records calls.
class _FakeDevice:
    id = "fake-dev-1"
    name = "Test Drone"
    device_type = "drone"

    def __init__(self, fail_step: str | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.fail_step = fail_step
        self.battery = 100.0

    def get_capabilities(self):
        return [{"name": n} for n in
                ("takeoff", "land", "hover", "move", "rotate",
                 "return_home", "emergency_stop", "ping")]

    def execute_command(self, cmd, params):
        self.calls.append((cmd, dict(params or {})))
        if cmd == self.fail_step:
            return {"success": False, "message": "simulated failure"}
        return {"success": True, "message": f"{cmd} ok"}

    def get_telemetry(self):
        return {"battery_pct": self.battery, "flying": False}


def _run_to_completion(reg: ExecutorRegistry, device_id: str,
                      timeout_s: float = 5.0) -> None:
    """Block until the execution finishes or times out."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        state = reg.get(device_id)
        if state and state.status != ExecutionStatus.RUNNING:
            return
        time.sleep(0.05)
    raise AssertionError("execution timed out")


CAPS = ["takeoff", "land", "hover", "move", "rotate", "return_home",
        "emergency_stop", "ping"]


class TestExecutor:
    def test_executes_takeoff_and_land(self):
        dev = _FakeDevice()
        plan = compile_to_plan("take off then land", dev.id, "drone", CAPS)
        plan_and_validate(plan, "drone", capability_names=CAPS)
        # Zero out durations so the test is fast
        for s in plan.steps:
            s.expected_duration_s = 0.05
            s.dwell_s = 0.0

        reg = ExecutorRegistry()
        state = reg.start(plan, dev)
        assert state.status == ExecutionStatus.RUNNING
        _run_to_completion(reg, dev.id)
        final = reg.get(dev.id)
        assert final.status == ExecutionStatus.COMPLETED
        assert [c[0] for c in dev.calls] == ["takeoff", "land"]

    def test_stop_flag_halts_execution(self):
        dev = _FakeDevice()
        # Long-running plan — 10 hover steps of 1s each
        plan = compile_to_plan("hover 10 seconds", dev.id, "drone", CAPS)
        plan_and_validate(plan, "drone", capability_names=CAPS)
        plan.steps[0].expected_duration_s = 0.05
        plan.steps[0].dwell_s = 3.0   # long dwell so we can stop mid-way

        reg = ExecutorRegistry()
        reg.start(plan, dev)
        time.sleep(0.15)
        ok = reg.stop(dev.id)
        assert ok
        _run_to_completion(reg, dev.id, timeout_s=3.0)
        assert reg.get(dev.id).status == ExecutionStatus.STOPPED

    def test_failed_step_aborts_remainder(self):
        dev = _FakeDevice(fail_step="move")
        plan = compile_to_plan(
            "take off then fly forward 2m then land",
            dev.id, "drone", CAPS)
        plan_and_validate(plan, "drone", capability_names=CAPS)
        for s in plan.steps:
            s.expected_duration_s = 0.03
            s.dwell_s = 0.0

        reg = ExecutorRegistry()
        reg.start(plan, dev)
        _run_to_completion(reg, dev.id)
        state = reg.get(dev.id)
        assert state.status == ExecutionStatus.FAILED
        # The "move" step should be FAILED; later steps SKIPPED
        assert state.plan.steps[1].status == StepStatus.FAILED
        assert state.plan.steps[2].status == StepStatus.SKIPPED
        # The land step was never dispatched to the device
        assert "land" not in [c[0] for c in dev.calls]

    def test_battery_precheck_aborts(self):
        dev = _FakeDevice()
        dev.battery = 10.0   # dangerously low
        plan = compile_to_plan(
            "if battery below 50% return home, take off and fly forward 5m",
            dev.id, "drone", CAPS)
        plan_and_validate(plan, "drone", capability_names=CAPS)
        for s in plan.steps:
            s.expected_duration_s = 0.02
            s.dwell_s = 0.0

        reg = ExecutorRegistry()
        reg.start(plan, dev)
        _run_to_completion(reg, dev.id)
        state = reg.get(dev.id)
        assert state.status == ExecutionStatus.STOPPED
        # takeoff should never have fired
        assert "takeoff" not in [c[0] for c in dev.calls]

    def test_refuses_plan_with_errors(self):
        dev = _FakeDevice()
        # Simulate a plan that has an ERROR issue — go to an unsupported cmd
        plan = compile_to_plan("take off to 500m", dev.id, "drone", CAPS)
        plan_and_validate(plan, "drone", capability_names=CAPS,
                          max_altitude_m=50.0)
        reg = ExecutorRegistry()
        state = reg.start(plan, dev)
        assert state.status == ExecutionStatus.FAILED
        assert "validation errors" in (state.error or "").lower()

    def test_traveled_path_accumulates(self):
        dev = _FakeDevice()
        plan = compile_to_plan(
            "take off 3m then fly forward 5m",
            dev.id, "drone", CAPS)
        plan_and_validate(plan, "drone", capability_names=CAPS)
        for s in plan.steps:
            s.expected_duration_s = 0.03

        reg = ExecutorRegistry()
        reg.start(plan, dev)
        _run_to_completion(reg, dev.id)
        state = reg.get(dev.id)
        assert len(state.traveled_path) == 2
        assert state.traveled_path[-1][0] == pytest.approx(5.0)

    def test_concurrent_start_rejected(self):
        dev = _FakeDevice()
        plan1 = compile_to_plan("hover 10 seconds", dev.id, "drone", CAPS)
        plan_and_validate(plan1, "drone", capability_names=CAPS)
        plan1.steps[0].expected_duration_s = 0.03
        plan1.steps[0].dwell_s = 5.0
        reg = ExecutorRegistry()
        reg.start(plan1, dev)

        plan2 = compile_to_plan("land", dev.id, "drone", CAPS)
        plan_and_validate(plan2, "drone", capability_names=CAPS)
        with pytest.raises(RuntimeError, match="already running"):
            reg.start(plan2, dev)
        reg.stop(dev.id)

    def test_iteration_bridge(self):
        dev = _FakeDevice()
        plan = compile_to_plan("take off 3m", dev.id, "drone", CAPS)
        plan_and_validate(plan, "drone", capability_names=CAPS)
        plan.steps[0].expected_duration_s = 0.03

        reg = ExecutorRegistry()
        reg.start(plan, dev)
        _run_to_completion(reg, dev.id)
        state = reg.get(dev.id)
        it = iteration_from_state(state)
        assert it["scenario"] == "nlp_plan"
        assert it["metrics"]["overall"] == 1.0
        assert it["metrics"]["steps_ok"] >= 1
        assert "trajectory" in it
