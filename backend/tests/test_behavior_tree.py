"""
Comprehensive tests for the Behavior Tree engine.

Covers:
  - All node types (composites, decorators, actions, conditions)
  - Blackboard operations
  - Tree serialization (JSON round-trip)
  - TreeExecutor lifecycle (start, pause, resume, stop)
  - Template library
"""

from __future__ import annotations

import sys
import time
import math
import threading
from pathlib import Path

try:
    import pytest
except ImportError:
    # Allow running without pytest for manual test execution
    class _PytestShim:
        class raises:
            def __init__(self, exc, match=None):
                self.exc = exc
                self.match = match
            def __enter__(self): return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                if exc_type is None:
                    raise AssertionError(f"Expected {self.exc.__name__}")
                if not issubclass(exc_type, self.exc):
                    return False
                if self.match and self.match not in str(exc_val):
                    raise AssertionError(f"Expected match '{self.match}' in '{exc_val}'")
                return True
        @staticmethod
        def fixture(fn): return fn
    pytest = _PytestShim()

# Ensure backend is on path (same as conftest.py)
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from omnix.behavior_tree.nodes import (
    NodeStatus,
    Sequence, Selector, Parallel,
    Repeat, RetryUntilSuccess, Inverter, Timeout, ConditionGate,
    ExecuteCommand, NLPCommand, Wait, Log, SetVariable, EmitEvent,
    CheckBattery, CheckPosition, CheckTelemetry, CheckVariable,
    IsConnected, IsFlying, IsMoving,
    node_from_dict,
)
from omnix.behavior_tree.blackboard import Blackboard
from omnix.behavior_tree.tree import BehaviorTree
from omnix.behavior_tree.executor import TreeExecutor
from omnix.behavior_tree.library import TEMPLATE_LIBRARY, list_templates, get_template


# ── Test helpers ─────────────────────────────────────────

class MockDevice:
    """Minimal mock device for testing action nodes."""

    def __init__(self, device_id="test-drone", device_type="drone"):
        self.id = device_id
        self.device_type = device_type
        self.name = "Test Drone"
        self._telemetry = {
            "battery_pct": 85,
            "connected": True,
            "flying": True,
            "position": {"x": 1.0, "y": 2.0, "z": 5.0},
            "velocity": {"vx": 1.0, "vy": 0.5, "vz": 0.0},
            "status": "active",
        }
        self.commands_log = []

    def get_telemetry(self):
        return dict(self._telemetry)

    def execute_command(self, command, params):
        self.commands_log.append((command, dict(params)))
        return {"success": True, "message": f"executed {command}"}

    def get_info(self):
        return {"id": self.id, "name": self.name, "device_type": self.device_type}


class FailingDevice(MockDevice):
    """Device that fails all commands."""

    def execute_command(self, command, params):
        self.commands_log.append((command, dict(params)))
        return {"success": False, "message": "command failed"}


def _make_ctx(device=None):
    return {"device": device or MockDevice(), "events": []}


# ═══════════════════════════════════════════════════════════
# BLACKBOARD TESTS
# ═══════════════════════════════════════════════════════════

class TestBlackboard:

    def test_get_set(self):
        bb = Blackboard()
        bb.set("key1", 42)
        assert bb.get("key1") == 42

    def test_default_value(self):
        bb = Blackboard()
        assert bb.get("missing", "default") == "default"

    def test_has_delete(self):
        bb = Blackboard()
        bb.set("x", 1)
        assert bb.has("x")
        assert bb.delete("x")
        assert not bb.has("x")
        assert not bb.delete("x")

    def test_keys(self):
        bb = Blackboard({"a": 1, "b": 2})
        assert set(bb.keys()) == {"a", "b"}

    def test_update(self):
        bb = Blackboard()
        bb.update({"x": 1, "y": 2})
        assert bb.get("x") == 1
        assert bb.get("y") == 2

    def test_to_dict(self):
        bb = Blackboard({"a": 1})
        d = bb.to_dict()
        assert d == {"a": 1}

    def test_logging(self):
        bb = Blackboard()
        bb.log("hello", level="info")
        bb.log("warning!", level="warning")
        logs = bb.get_logs()
        assert len(logs) == 2
        assert logs[0]["message"] == "hello"
        assert logs[1]["level"] == "warning"

    def test_clear(self):
        bb = Blackboard({"a": 1})
        bb.log("msg")
        bb.clear()
        assert bb.keys() == []
        assert bb.get_logs() == []

    def test_listener(self):
        changes = []
        bb = Blackboard()
        bb.on_change(lambda k, old, new: changes.append((k, old, new)))
        bb.set("x", 1)
        bb.set("x", 2)
        assert changes == [("x", None, 1), ("x", 1, 2)]

    def test_thread_safety(self):
        bb = Blackboard()
        errors = []

        def writer(n):
            try:
                for i in range(100):
                    bb.set(f"key-{n}", i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors


# ═══════════════════════════════════════════════════════════
# COMPOSITE NODE TESTS
# ═══════════════════════════════════════════════════════════

class TestSequence:

    def test_all_success(self):
        bb = Blackboard()
        ctx = _make_ctx()
        c1 = Log(properties={"message": "a"})
        c2 = Log(properties={"message": "b"})
        seq = Sequence(children=[c1, c2])
        result = seq.tick(bb, ctx)
        assert result == NodeStatus.SUCCESS

    def test_fails_on_first_failure(self):
        bb = Blackboard()
        device = FailingDevice()
        ctx = _make_ctx(device)
        c1 = ExecuteCommand(properties={"command": "fail", "params": {}, "duration_s": 0})
        c2 = Log(properties={"message": "never"})
        seq = Sequence(children=[c1, c2])
        # First tick dispatches, second tick gets result
        seq.tick(bb, ctx)
        result = seq.tick(bb, ctx)
        assert result == NodeStatus.FAILURE

    def test_empty_sequence_succeeds(self):
        bb = Blackboard()
        seq = Sequence(children=[])
        assert seq.tick(bb, {}) == NodeStatus.SUCCESS


class TestSelector:

    def test_succeeds_on_first_success(self):
        bb = Blackboard()
        ctx = _make_ctx()
        c1 = Log(properties={"message": "ok"})
        sel = Selector(children=[c1])
        assert sel.tick(bb, ctx) == NodeStatus.SUCCESS

    def test_tries_all_until_success(self):
        bb = Blackboard()
        device = FailingDevice()
        ctx = _make_ctx(device)
        # First child fails (command fails), second succeeds (log always succeeds)
        c1 = ExecuteCommand(properties={"command": "x", "params": {}, "duration_s": 0})
        c2 = Log(properties={"message": "fallback"})
        sel = Selector(children=[c1, c2])
        sel.tick(bb, ctx)  # tick 1: c1 dispatches
        result = sel.tick(bb, ctx)  # tick 2: c1 fails, c2 succeeds
        assert result == NodeStatus.SUCCESS


class TestParallel:

    def test_all_succeed(self):
        bb = Blackboard()
        ctx = _make_ctx()
        c1 = Log(properties={"message": "a"})
        c2 = Log(properties={"message": "b"})
        par = Parallel(children=[c1, c2], properties={"success_threshold": -1})
        assert par.tick(bb, ctx) == NodeStatus.SUCCESS

    def test_threshold(self):
        bb = Blackboard()
        ctx = _make_ctx()
        c1 = Log(properties={"message": "a"})
        c2 = Log(properties={"message": "b"})
        par = Parallel(children=[c1, c2], properties={"success_threshold": 1})
        assert par.tick(bb, ctx) == NodeStatus.SUCCESS


# ═══════════════════════════════════════════════════════════
# DECORATOR NODE TESTS
# ═══════════════════════════════════════════════════════════

class TestRepeat:

    def test_repeats_n_times(self):
        bb = Blackboard()
        ctx = _make_ctx()
        child = Log(properties={"message": "tick"})
        rep = Repeat(children=[child], properties={"count": 3})
        # Should take 3 ticks: each tick the child succeeds and repeat continues
        r1 = rep.tick(bb, ctx)
        assert r1 == NodeStatus.RUNNING
        r2 = rep.tick(bb, ctx)
        assert r2 == NodeStatus.RUNNING
        r3 = rep.tick(bb, ctx)
        assert r3 == NodeStatus.SUCCESS

    def test_fails_on_child_failure(self):
        bb = Blackboard()
        device = FailingDevice()
        ctx = _make_ctx(device)
        child = ExecuteCommand(properties={"command": "x", "params": {}, "duration_s": 0})
        rep = Repeat(children=[child], properties={"count": 5})
        rep.tick(bb, ctx)  # dispatch
        result = rep.tick(bb, ctx)  # fail
        assert result == NodeStatus.FAILURE

    def test_no_children(self):
        bb = Blackboard()
        rep = Repeat(children=[], properties={"count": 3})
        assert rep.tick(bb, {}) == NodeStatus.FAILURE


class TestRetryUntilSuccess:

    def test_succeeds_on_first_attempt(self):
        bb = Blackboard()
        ctx = _make_ctx()
        child = Log(properties={"message": "ok"})
        retry = RetryUntilSuccess(children=[child], properties={"max_attempts": 3})
        assert retry.tick(bb, ctx) == NodeStatus.SUCCESS

    def test_exhausts_attempts(self):
        bb = Blackboard()
        device = FailingDevice()
        ctx = _make_ctx(device)
        child = ExecuteCommand(properties={"command": "x", "params": {}, "duration_s": 0})
        retry = RetryUntilSuccess(children=[child], properties={"max_attempts": 2})
        retry.tick(bb, ctx)  # attempt 1: dispatch
        retry.tick(bb, ctx)  # attempt 1: fail → attempt 2
        retry.tick(bb, ctx)  # attempt 2: dispatch
        result = retry.tick(bb, ctx)  # attempt 2: fail → exhausted
        assert result == NodeStatus.FAILURE


class TestInverter:

    def test_inverts_success(self):
        bb = Blackboard()
        child = Log(properties={"message": "ok"})
        inv = Inverter(children=[child])
        assert inv.tick(bb, {}) == NodeStatus.FAILURE

    def test_inverts_failure(self):
        bb = Blackboard()
        device = FailingDevice()
        ctx = _make_ctx(device)
        child = ExecuteCommand(properties={"command": "x", "params": {}, "duration_s": 0})
        inv = Inverter(children=[child])
        inv.tick(bb, ctx)  # dispatch
        result = inv.tick(bb, ctx)  # child fails → inverter succeeds
        assert result == NodeStatus.SUCCESS


class TestTimeout:

    def test_passes_through_success(self):
        bb = Blackboard()
        child = Log(properties={"message": "fast"})
        to = Timeout(children=[child], properties={"timeout_s": 10})
        assert to.tick(bb, {}) == NodeStatus.SUCCESS

    def test_times_out(self):
        bb = Blackboard()
        ctx = _make_ctx()
        child = Wait(properties={"duration_s": 100})
        to = Timeout(children=[child], properties={"timeout_s": 0.01})
        to.tick(bb, ctx)  # starts
        time.sleep(0.02)
        result = to.tick(bb, ctx)
        assert result == NodeStatus.FAILURE


class TestConditionGate:

    def test_passes_when_condition_met(self):
        bb = Blackboard()
        bb.set("ready", True)
        child = Log(properties={"message": "go"})
        gate = ConditionGate(children=[child],
                             properties={"variable": "ready", "operator": "==", "value": True})
        assert gate.tick(bb, {}) == NodeStatus.SUCCESS

    def test_fails_when_condition_not_met(self):
        bb = Blackboard()
        bb.set("ready", False)
        gate = ConditionGate(properties={"variable": "ready", "operator": "==", "value": True})
        assert gate.tick(bb, {}) == NodeStatus.FAILURE

    def test_numeric_comparison(self):
        bb = Blackboard()
        bb.set("temp", 75)
        gate = ConditionGate(properties={"variable": "temp", "operator": ">", "value": 50})
        assert gate.tick(bb, {}) == NodeStatus.SUCCESS


# ═══════════════════════════════════════════════════════════
# ACTION NODE TESTS
# ═══════════════════════════════════════════════════════════

class TestExecuteCommand:

    def test_dispatches_command(self):
        bb = Blackboard()
        device = MockDevice()
        ctx = _make_ctx(device)
        node = ExecuteCommand(properties={
            "command": "takeoff", "params": {"altitude": 5}, "duration_s": 0,
        })
        node.tick(bb, ctx)
        assert ("takeoff", {"altitude": 5}) in device.commands_log

    def test_success_on_good_command(self):
        bb = Blackboard()
        ctx = _make_ctx()
        node = ExecuteCommand(properties={
            "command": "takeoff", "params": {}, "duration_s": 0,
        })
        result = node.tick(bb, ctx)
        assert result == NodeStatus.SUCCESS

    def test_failure_on_bad_command(self):
        bb = Blackboard()
        device = FailingDevice()
        ctx = _make_ctx(device)
        node = ExecuteCommand(properties={
            "command": "bad", "params": {}, "duration_s": 0,
        })
        result = node.tick(bb, ctx)
        assert result == NodeStatus.FAILURE

    def test_no_device_fails(self):
        bb = Blackboard()
        node = ExecuteCommand(properties={"command": "x", "params": {}, "duration_s": 0})
        assert node.tick(bb, {}) == NodeStatus.FAILURE


class TestWait:

    def test_waits_then_succeeds(self):
        bb = Blackboard()
        node = Wait(properties={"duration_s": 0.05})
        r1 = node.tick(bb, {})
        assert r1 == NodeStatus.RUNNING
        time.sleep(0.06)
        r2 = node.tick(bb, {})
        assert r2 == NodeStatus.SUCCESS


class TestLog:

    def test_logs_message(self):
        bb = Blackboard()
        node = Log(properties={"message": "hello world", "level": "info"})
        result = node.tick(bb, {})
        assert result == NodeStatus.SUCCESS
        logs = bb.get_logs()
        assert len(logs) == 1
        assert logs[0]["message"] == "hello world"


class TestSetVariable:

    def test_sets_variable(self):
        bb = Blackboard()
        node = SetVariable(properties={"variable": "count", "value": 42})
        result = node.tick(bb, {})
        assert result == NodeStatus.SUCCESS
        assert bb.get("count") == 42


class TestEmitEvent:

    def test_emits_event(self):
        bb = Blackboard()
        ctx = {"events": []}
        node = EmitEvent(properties={"event": "alert", "data": {"level": "high"}})
        result = node.tick(bb, ctx)
        assert result == NodeStatus.SUCCESS
        assert len(ctx["events"]) == 1
        assert ctx["events"][0]["event"] == "alert"


# ═══════════════════════════════════════════════════════════
# CONDITION NODE TESTS
# ═══════════════════════════════════════════════════════════

class TestCheckBattery:

    def test_battery_ok(self):
        bb = Blackboard()
        device = MockDevice()
        device._telemetry["battery_pct"] = 80
        ctx = _make_ctx(device)
        node = CheckBattery(properties={"min_pct": 20})
        assert node.tick(bb, ctx) == NodeStatus.SUCCESS

    def test_battery_low(self):
        bb = Blackboard()
        device = MockDevice()
        device._telemetry["battery_pct"] = 10
        ctx = _make_ctx(device)
        node = CheckBattery(properties={"min_pct": 20})
        assert node.tick(bb, ctx) == NodeStatus.FAILURE


class TestCheckPosition:

    def test_within_radius(self):
        bb = Blackboard()
        device = MockDevice()
        device._telemetry["position"] = {"x": 1, "y": 1, "z": 1}
        ctx = _make_ctx(device)
        node = CheckPosition(properties={
            "target_x": 1, "target_y": 1, "target_z": 1, "radius_m": 0.5,
        })
        assert node.tick(bb, ctx) == NodeStatus.SUCCESS

    def test_outside_radius(self):
        bb = Blackboard()
        device = MockDevice()
        device._telemetry["position"] = {"x": 100, "y": 0, "z": 0}
        ctx = _make_ctx(device)
        node = CheckPosition(properties={
            "target_x": 0, "target_y": 0, "target_z": 0, "radius_m": 1.0,
        })
        assert node.tick(bb, ctx) == NodeStatus.FAILURE


class TestCheckVariable:

    def test_variable_matches(self):
        bb = Blackboard()
        bb.set("mode", "patrol")
        node = CheckVariable(properties={"variable": "mode", "operator": "==", "value": "patrol"})
        assert node.tick(bb, {}) == NodeStatus.SUCCESS

    def test_variable_mismatch(self):
        bb = Blackboard()
        bb.set("mode", "idle")
        node = CheckVariable(properties={"variable": "mode", "operator": "==", "value": "patrol"})
        assert node.tick(bb, {}) == NodeStatus.FAILURE


class TestIsConnected:

    def test_connected(self):
        bb = Blackboard()
        device = MockDevice()
        ctx = _make_ctx(device)
        assert IsConnected().tick(bb, ctx) == NodeStatus.SUCCESS

    def test_disconnected(self):
        bb = Blackboard()
        device = MockDevice()
        device._telemetry["status"] = "disconnected"
        device._telemetry["connected"] = False
        ctx = _make_ctx(device)
        assert IsConnected().tick(bb, ctx) == NodeStatus.FAILURE


class TestIsFlying:

    def test_flying(self):
        bb = Blackboard()
        device = MockDevice()
        device._telemetry["flying"] = True
        ctx = _make_ctx(device)
        assert IsFlying().tick(bb, ctx) == NodeStatus.SUCCESS

    def test_grounded(self):
        bb = Blackboard()
        device = MockDevice()
        device._telemetry["flying"] = False
        device._telemetry["position"]["z"] = 0
        ctx = _make_ctx(device)
        assert IsFlying(properties={"min_altitude": 0.5}).tick(bb, ctx) == NodeStatus.FAILURE


class TestIsMoving:

    def test_moving(self):
        bb = Blackboard()
        device = MockDevice()
        device._telemetry["velocity"] = {"vx": 2.0, "vy": 0, "vz": 0}
        ctx = _make_ctx(device)
        assert IsMoving(properties={"min_speed": 0.1}).tick(bb, ctx) == NodeStatus.SUCCESS

    def test_stationary(self):
        bb = Blackboard()
        device = MockDevice()
        device._telemetry["velocity"] = {"vx": 0, "vy": 0, "vz": 0}
        ctx = _make_ctx(device)
        assert IsMoving(properties={"min_speed": 0.1}).tick(bb, ctx) == NodeStatus.FAILURE


# ═══════════════════════════════════════════════════════════
# TREE SERIALIZATION TESTS
# ═══════════════════════════════════════════════════════════

class TestTreeSerialization:

    def test_round_trip(self):
        """Serialize a tree to dict and back, verify equality."""
        root = Sequence(name="Main", children=[
            CheckBattery(properties={"min_pct": 30}),
            ExecuteCommand(properties={"command": "takeoff", "params": {"alt": 5}, "duration_s": 1}),
            Repeat(children=[
                Log(properties={"message": "patrolling"}),
            ], properties={"count": 3}),
        ])
        tree = BehaviorTree(name="Test Mission", root=root, device_id="d1")
        d = tree.to_dict()
        tree2 = BehaviorTree.from_dict(d)

        assert tree2.name == "Test Mission"
        assert tree2.device_id == "d1"
        assert tree2.node_count() == 5  # Seq + Battery + Exec + Repeat + Log

    def test_node_from_dict(self):
        d = {
            "type": "Log",
            "node_id": "n-test",
            "name": "My Log",
            "category": "action",
            "properties": {"message": "hello", "level": "info"},
            "children": [],
        }
        node = node_from_dict(d)
        assert isinstance(node, Log)
        assert node.node_id == "n-test"
        assert node.properties["message"] == "hello"

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown node type"):
            node_from_dict({"type": "FakeNode"})

    def test_nested_tree_serialization(self):
        root = Selector(children=[
            Sequence(children=[
                CheckBattery(properties={"min_pct": 20}),
                ExecuteCommand(properties={"command": "patrol", "params": {}, "duration_s": 1}),
            ]),
            Sequence(children=[
                Log(properties={"message": "fallback"}),
                ExecuteCommand(properties={"command": "land", "params": {}, "duration_s": 1}),
            ]),
        ])
        tree = BehaviorTree(name="Complex", root=root)
        d = tree.to_dict()
        tree2 = BehaviorTree.from_dict(d)
        assert tree2.node_count() == 7


class TestBehaviorTree:

    def test_tick(self):
        root = Log(properties={"message": "single tick"})
        tree = BehaviorTree(root=root)
        result = tree.tick({"device": MockDevice()})
        assert result == NodeStatus.SUCCESS
        assert tree.tick_count == 1

    def test_reset(self):
        root = Log(properties={"message": "x"})
        tree = BehaviorTree(root=root)
        tree.tick({})
        tree.reset()
        assert tree.tick_count == 0
        assert tree.status == NodeStatus.PENDING

    def test_find_node(self):
        child = Log(node_id="target", properties={"message": "x"})
        root = Sequence(children=[child])
        tree = BehaviorTree(root=root)
        found = tree.find_node("target")
        assert found is child

    def test_all_nodes(self):
        root = Sequence(children=[
            Log(properties={"message": "a"}),
            Log(properties={"message": "b"}),
        ])
        tree = BehaviorTree(root=root)
        assert len(tree.all_nodes()) == 3


# ═══════════════════════════════════════════════════════════
# EXECUTOR TESTS
# ═══════════════════════════════════════════════════════════

class TestTreeExecutor:

    def test_execute_simple_tree(self):
        device = MockDevice()
        root = Sequence(children=[
            Log(properties={"message": "start"}),
            ExecuteCommand(properties={"command": "takeoff", "params": {"altitude": 3}, "duration_s": 0}),
            Log(properties={"message": "done"}),
        ])
        tree = BehaviorTree(name="Simple", root=root, device_id=device.id)
        executor = TreeExecutor()
        record = executor.start(tree, device, tick_rate_hz=50)
        # Wait for completion
        for _ in range(100):
            if record.status in ("completed", "failed", "stopped"):
                break
            time.sleep(0.05)
        assert record.status == "completed"
        assert ("takeoff", {"altitude": 3}) in device.commands_log

    def test_stop_execution(self):
        device = MockDevice()
        root = Repeat(children=[
            Wait(properties={"duration_s": 0.5}),
        ], properties={"count": -1})  # infinite
        tree = BehaviorTree(name="Infinite", root=root, device_id=device.id)
        executor = TreeExecutor()
        record = executor.start(tree, device, tick_rate_hz=10)
        time.sleep(0.2)
        assert record.status == "running"
        executor.stop(device.id)
        time.sleep(0.3)
        assert record.status == "stopped"

    def test_pause_resume(self):
        device = MockDevice()
        root = Repeat(children=[
            Wait(properties={"duration_s": 0.1}),
        ], properties={"count": -1})
        tree = BehaviorTree(name="Pausable", root=root, device_id=device.id)
        executor = TreeExecutor()
        record = executor.start(tree, device, tick_rate_hz=10)
        time.sleep(0.15)
        assert executor.pause(device.id)
        assert record.status == "paused"
        tick_at_pause = record.tick_count
        time.sleep(0.2)
        # Ticks should not increase while paused
        assert record.tick_count == tick_at_pause or record.tick_count <= tick_at_pause + 1
        assert executor.resume(device.id)
        time.sleep(0.15)
        assert record.tick_count > tick_at_pause
        executor.stop(device.id)

    def test_failed_tree(self):
        device = FailingDevice()
        root = ExecuteCommand(properties={"command": "bad", "params": {}, "duration_s": 0})
        tree = BehaviorTree(name="Failing", root=root, device_id=device.id)
        executor = TreeExecutor()
        record = executor.start(tree, device, tick_rate_hz=50)
        for _ in range(50):
            if record.status in ("completed", "failed"):
                break
            time.sleep(0.05)
        assert record.status == "failed"

    def test_history(self):
        device = MockDevice()
        root = Log(properties={"message": "done"})
        tree = BehaviorTree(name="Quick", root=root, device_id=device.id)
        executor = TreeExecutor()
        record = executor.start(tree, device, tick_rate_hz=50)
        for _ in range(50):
            if record.status == "completed":
                break
            time.sleep(0.05)
        assert record.status == "completed"
        time.sleep(0.1)  # Let history append
        h = executor.history(device.id)
        assert len(h) >= 1

    def test_duplicate_start_raises(self):
        device = MockDevice()
        root = Repeat(children=[Wait(properties={"duration_s": 1})], properties={"count": -1})
        tree = BehaviorTree(name="Long", root=root, device_id=device.id)
        executor = TreeExecutor()
        executor.start(tree, device, tick_rate_hz=5)
        time.sleep(0.1)
        with pytest.raises(RuntimeError, match="already running"):
            tree2 = BehaviorTree(name="Dup", root=Log(properties={"message": "x"}),
                                 device_id=device.id)
            executor.start(tree2, device, tick_rate_hz=5)
        executor.stop(device.id)


# ═══════════════════════════════════════════════════════════
# TEMPLATE LIBRARY TESTS
# ═══════════════════════════════════════════════════════════

class TestTemplateLibrary:

    def test_has_templates(self):
        assert len(TEMPLATE_LIBRARY) == 6

    def test_list_templates(self):
        summaries = list_templates()
        assert len(summaries) == 6
        names = {s["name"] for s in summaries}
        assert "Patrol & Return" in names
        assert "Emergency Response" in names

    def test_filter_by_device_type(self):
        drone_templates = list_templates("drone")
        arm_templates = list_templates("robot_arm")
        assert len(drone_templates) >= 3
        assert any(t["name"] == "Pick & Place Cycle" for t in arm_templates)

    def test_get_template(self):
        tpl = get_template("Patrol & Return")
        assert tpl is not None
        assert tpl["name"] == "Patrol & Return"
        assert tpl["root"]["type"] == "Sequence"

    def test_get_missing_template(self):
        assert get_template("Nonexistent") is None

    def test_templates_are_valid_trees(self):
        """Every template should parse into a valid BehaviorTree."""
        for tpl in TEMPLATE_LIBRARY:
            tree = BehaviorTree.from_dict({
                "tree_id": "test",
                "name": tpl["name"],
                "root": tpl["root"],
            })
            assert tree.root is not None
            assert tree.node_count() > 0


# ═══════════════════════════════════════════════════════════
# INTEGRATION TEST
# ═══════════════════════════════════════════════════════════

class TestIntegration:

    def test_patrol_template_executes(self):
        """Build a quick patrol tree (zero-duration commands) and run on mock device."""
        root_dict = {
            "type": "Sequence", "node_id": "root", "name": "Quick Patrol",
            "category": "composite", "properties": {},
            "children": [
                {"type": "CheckBattery", "node_id": "bat", "name": "Bat", "category": "condition",
                 "properties": {"min_pct": 20}, "children": []},
                {"type": "ExecuteCommand", "node_id": "take", "name": "Take Off", "category": "action",
                 "properties": {"command": "takeoff", "params": {"altitude": 5}, "duration_s": 0}, "children": []},
                {"type": "Repeat", "node_id": "loop", "name": "Patrol x2", "category": "decorator",
                 "properties": {"count": 2}, "children": [{
                     "type": "Sequence", "node_id": "lap", "name": "Lap", "category": "composite",
                     "properties": {}, "children": [
                         {"type": "ExecuteCommand", "node_id": "wp1", "name": "WP1", "category": "action",
                          "properties": {"command": "move_to", "params": {"x": 5}, "duration_s": 0}, "children": []},
                         {"type": "Log", "node_id": "log", "name": "Log", "category": "action",
                          "properties": {"message": "lap"}, "children": []},
                     ]
                 }]},
                {"type": "ExecuteCommand", "node_id": "land", "name": "Land", "category": "action",
                 "properties": {"command": "land", "params": {}, "duration_s": 0}, "children": []},
            ],
        }
        tree = BehaviorTree.from_dict({
            "tree_id": "int-test", "name": "Quick Patrol",
            "device_id": "test-drone", "root": root_dict,
        })
        device = MockDevice()
        executor = TreeExecutor()
        record = executor.start(tree, device, tick_rate_hz=100)
        for _ in range(200):
            if record.status in ("completed", "failed", "stopped"):
                break
            time.sleep(0.02)
        assert record.status == "completed"
        cmd_names = [c[0] for c in device.commands_log]
        assert "takeoff" in cmd_names
        assert "land" in cmd_names

    def test_emergency_response_template(self):
        tpl = get_template("Emergency Response")
        tree = BehaviorTree.from_dict({
            "tree_id": "er-test",
            "name": tpl["name"],
            "device_id": "test-drone",
            "root": tpl["root"],
        })
        device = MockDevice()
        executor = TreeExecutor()
        record = executor.start(tree, device, tick_rate_hz=50)
        for _ in range(200):
            if record.status in ("completed", "failed"):
                break
            time.sleep(0.05)
        assert record.status == "completed"
