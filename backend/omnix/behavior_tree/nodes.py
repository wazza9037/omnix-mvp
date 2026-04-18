"""
Behavior Tree node types.

Classical BT semantics — every node returns one of:
  PENDING  — not yet ticked
  RUNNING  — still working (tick me again)
  SUCCESS  — completed successfully
  FAILURE  — completed with failure

Node categories:
  Composite:  Sequence, Selector, Parallel
  Decorator:  Repeat, RetryUntilSuccess, Inverter, Timeout, ConditionGate
  Action:     ExecuteCommand, NLPCommand, Wait, Log, SetVariable, EmitEvent
  Condition:  CheckBattery, CheckPosition, CheckTelemetry, CheckVariable,
              IsConnected, IsFlying, IsMoving

All nodes are JSON-serializable via to_dict() / from_dict().
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Status enum ───────────────────────────────────────────

class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"


# ── Node registry (for deserialization) ──────────────────

_NODE_TYPES: dict[str, type] = {}


def _register(cls):
    _NODE_TYPES[cls.__name__] = cls
    return cls


def node_from_dict(d: dict) -> "BTNode":
    """Reconstruct a node (and its children) from a dict."""
    ntype = d.get("type")
    cls = _NODE_TYPES.get(ntype)
    if cls is None:
        raise ValueError(f"Unknown node type: {ntype}")
    return cls.from_dict(d)


# ── Base class ────────────────────────────────────────────

class BTNode:
    """Abstract base for every behavior tree node."""

    category: str = "unknown"  # composite | decorator | action | condition

    def __init__(self, *, node_id: str | None = None, name: str = "",
                 children: list["BTNode"] | None = None,
                 properties: dict[str, Any] | None = None):
        self.node_id: str = node_id or f"n-{uuid.uuid4().hex[:8]}"
        self.name: str = name or self.__class__.__name__
        self.children: list[BTNode] = children or []
        self.properties: dict[str, Any] = properties or {}
        self.status: NodeStatus = NodeStatus.PENDING
        # Visual editor layout (persisted but ignored by engine)
        self.x: float = 0.0
        self.y: float = 0.0

    # ── Tick (override in subclasses) ────────────────────

    def tick(self, blackboard, context: dict) -> NodeStatus:
        """Execute one tick. Must return a NodeStatus."""
        raise NotImplementedError

    def reset(self):
        """Reset this node and all children to PENDING."""
        self.status = NodeStatus.PENDING
        for c in self.children:
            c.reset()

    # ── Serialization ────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "type": self.__class__.__name__,
            "node_id": self.node_id,
            "name": self.name,
            "category": self.category,
            "properties": dict(self.properties),
            "children": [c.to_dict() for c in self.children],
            "x": self.x,
            "y": self.y,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BTNode":
        children = [node_from_dict(c) for c in d.get("children", [])]
        node = cls(
            node_id=d.get("node_id"),
            name=d.get("name", ""),
            children=children,
            properties=dict(d.get("properties", {})),
        )
        node.x = d.get("x", 0.0)
        node.y = d.get("y", 0.0)
        return node

    def __repr__(self):
        return f"<{self.__class__.__name__} id={self.node_id} status={self.status.value}>"


# ═══════════════════════════════════════════════════════════
# COMPOSITE NODES
# ═══════════════════════════════════════════════════════════

@_register
class Sequence(BTNode):
    """Ticks children left-to-right. Fails on first failure, succeeds
    when all children succeed. A running child is re-ticked next time."""

    category = "composite"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._running_idx = 0

    def tick(self, bb, ctx) -> NodeStatus:
        for i in range(self._running_idx, len(self.children)):
            child = self.children[i]
            result = child.tick(bb, ctx)
            if result == NodeStatus.RUNNING:
                self._running_idx = i
                self.status = NodeStatus.RUNNING
                return NodeStatus.RUNNING
            if result == NodeStatus.FAILURE:
                self._running_idx = 0
                self.status = NodeStatus.FAILURE
                return NodeStatus.FAILURE
        self._running_idx = 0
        self.status = NodeStatus.SUCCESS
        return NodeStatus.SUCCESS

    def reset(self):
        super().reset()
        self._running_idx = 0


@_register
class Selector(BTNode):
    """Ticks children left-to-right. Succeeds on first success, fails
    when all children fail."""

    category = "composite"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._running_idx = 0

    def tick(self, bb, ctx) -> NodeStatus:
        for i in range(self._running_idx, len(self.children)):
            child = self.children[i]
            result = child.tick(bb, ctx)
            if result == NodeStatus.RUNNING:
                self._running_idx = i
                self.status = NodeStatus.RUNNING
                return NodeStatus.RUNNING
            if result == NodeStatus.SUCCESS:
                self._running_idx = 0
                self.status = NodeStatus.SUCCESS
                return NodeStatus.SUCCESS
        self._running_idx = 0
        self.status = NodeStatus.FAILURE
        return NodeStatus.FAILURE

    def reset(self):
        super().reset()
        self._running_idx = 0


@_register
class Parallel(BTNode):
    """Ticks ALL children every tick. Succeeds when `success_threshold`
    children succeed. Fails when enough have failed that the threshold
    is unreachable."""

    category = "composite"

    def __init__(self, **kw):
        super().__init__(**kw)
        if "success_threshold" not in self.properties:
            self.properties["success_threshold"] = -1  # -1 = all

    def tick(self, bb, ctx) -> NodeStatus:
        threshold = self.properties.get("success_threshold", -1)
        if threshold == -1:
            threshold = len(self.children)

        successes = 0
        failures = 0
        for child in self.children:
            if child.status == NodeStatus.SUCCESS:
                successes += 1
                continue
            if child.status == NodeStatus.FAILURE:
                failures += 1
                continue
            result = child.tick(bb, ctx)
            if result == NodeStatus.SUCCESS:
                successes += 1
            elif result == NodeStatus.FAILURE:
                failures += 1

        if successes >= threshold:
            self.status = NodeStatus.SUCCESS
            return NodeStatus.SUCCESS
        if failures > len(self.children) - threshold:
            self.status = NodeStatus.FAILURE
            return NodeStatus.FAILURE
        self.status = NodeStatus.RUNNING
        return NodeStatus.RUNNING


# ═══════════════════════════════════════════════════════════
# DECORATOR NODES
# ═══════════════════════════════════════════════════════════

@_register
class Repeat(BTNode):
    """Repeats its single child N times (or forever if count = -1).
    Fails immediately if the child fails."""

    category = "decorator"

    def __init__(self, **kw):
        super().__init__(**kw)
        if "count" not in self.properties:
            self.properties["count"] = 3
        self._iteration = 0

    def tick(self, bb, ctx) -> NodeStatus:
        if not self.children:
            self.status = NodeStatus.FAILURE
            return NodeStatus.FAILURE

        child = self.children[0]
        count = self.properties.get("count", 3)

        result = child.tick(bb, ctx)
        if result == NodeStatus.RUNNING:
            self.status = NodeStatus.RUNNING
            return NodeStatus.RUNNING
        if result == NodeStatus.FAILURE:
            self._iteration = 0
            self.status = NodeStatus.FAILURE
            return NodeStatus.FAILURE
        # SUCCESS — one iteration done
        self._iteration += 1
        if count != -1 and self._iteration >= count:
            self._iteration = 0
            self.status = NodeStatus.SUCCESS
            return NodeStatus.SUCCESS
        child.reset()
        self.status = NodeStatus.RUNNING
        return NodeStatus.RUNNING

    def reset(self):
        super().reset()
        self._iteration = 0


@_register
class RetryUntilSuccess(BTNode):
    """Retries child up to `max_attempts` times. Succeeds on first
    child success, fails after exhausting attempts."""

    category = "decorator"

    def __init__(self, **kw):
        super().__init__(**kw)
        if "max_attempts" not in self.properties:
            self.properties["max_attempts"] = 3
        self._attempts = 0

    def tick(self, bb, ctx) -> NodeStatus:
        if not self.children:
            self.status = NodeStatus.FAILURE
            return NodeStatus.FAILURE

        child = self.children[0]
        max_a = self.properties.get("max_attempts", 3)

        result = child.tick(bb, ctx)
        if result == NodeStatus.RUNNING:
            self.status = NodeStatus.RUNNING
            return NodeStatus.RUNNING
        if result == NodeStatus.SUCCESS:
            self._attempts = 0
            self.status = NodeStatus.SUCCESS
            return NodeStatus.SUCCESS
        # FAILURE — retry?
        self._attempts += 1
        if self._attempts >= max_a:
            self._attempts = 0
            self.status = NodeStatus.FAILURE
            return NodeStatus.FAILURE
        child.reset()
        self.status = NodeStatus.RUNNING
        return NodeStatus.RUNNING

    def reset(self):
        super().reset()
        self._attempts = 0


@_register
class Inverter(BTNode):
    """Inverts child result: SUCCESS→FAILURE, FAILURE→SUCCESS."""

    category = "decorator"

    def tick(self, bb, ctx) -> NodeStatus:
        if not self.children:
            self.status = NodeStatus.FAILURE
            return NodeStatus.FAILURE
        result = self.children[0].tick(bb, ctx)
        if result == NodeStatus.RUNNING:
            self.status = NodeStatus.RUNNING
            return NodeStatus.RUNNING
        if result == NodeStatus.SUCCESS:
            self.status = NodeStatus.FAILURE
            return NodeStatus.FAILURE
        self.status = NodeStatus.SUCCESS
        return NodeStatus.SUCCESS


@_register
class Timeout(BTNode):
    """Fails if child doesn't complete within `timeout_s` seconds."""

    category = "decorator"

    def __init__(self, **kw):
        super().__init__(**kw)
        if "timeout_s" not in self.properties:
            self.properties["timeout_s"] = 10.0
        self._start_time: float | None = None

    def tick(self, bb, ctx) -> NodeStatus:
        if not self.children:
            self.status = NodeStatus.FAILURE
            return NodeStatus.FAILURE

        if self._start_time is None:
            self._start_time = time.time()

        elapsed = time.time() - self._start_time
        if elapsed > self.properties.get("timeout_s", 10.0):
            self._start_time = None
            self.status = NodeStatus.FAILURE
            return NodeStatus.FAILURE

        result = self.children[0].tick(bb, ctx)
        if result != NodeStatus.RUNNING:
            self._start_time = None
        self.status = result
        return result

    def reset(self):
        super().reset()
        self._start_time = None


@_register
class ConditionGate(BTNode):
    """Only ticks child if a blackboard variable meets a condition.
    Properties: variable, operator (==, !=, >, <, >=, <=), value."""

    category = "decorator"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.properties.setdefault("variable", "")
        self.properties.setdefault("operator", "==")
        self.properties.setdefault("value", True)

    def tick(self, bb, ctx) -> NodeStatus:
        var_name = self.properties.get("variable", "")
        op = self.properties.get("operator", "==")
        expected = self.properties.get("value", True)
        actual = bb.get(var_name)

        if not self._check(actual, op, expected):
            self.status = NodeStatus.FAILURE
            return NodeStatus.FAILURE

        if not self.children:
            self.status = NodeStatus.SUCCESS
            return NodeStatus.SUCCESS

        result = self.children[0].tick(bb, ctx)
        self.status = result
        return result

    @staticmethod
    def _check(actual, op, expected) -> bool:
        try:
            if op == "==":  return actual == expected
            if op == "!=":  return actual != expected
            if op == ">":   return float(actual) > float(expected)
            if op == "<":   return float(actual) < float(expected)
            if op == ">=":  return float(actual) >= float(expected)
            if op == "<=":  return float(actual) <= float(expected)
        except (TypeError, ValueError):
            return False
        return False


# ═══════════════════════════════════════════════════════════
# ACTION NODES (leaf nodes that DO things)
# ═══════════════════════════════════════════════════════════

@_register
class ExecuteCommand(BTNode):
    """Dispatches a device command. First tick sends the command and
    returns RUNNING. Next tick checks if enough time has elapsed
    (simulating command duration), then returns SUCCESS/FAILURE based
    on the device result."""

    category = "action"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.properties.setdefault("command", "")
        self.properties.setdefault("params", {})
        self.properties.setdefault("duration_s", 1.0)
        self._started_at: float | None = None
        self._result: dict | None = None

    def tick(self, bb, ctx) -> NodeStatus:
        device = ctx.get("device")
        if not device:
            self.status = NodeStatus.FAILURE
            return NodeStatus.FAILURE

        cmd = self.properties.get("command", "")
        params = dict(self.properties.get("params", {}))
        duration = float(self.properties.get("duration_s", 1.0))

        if self._started_at is None:
            # First tick — dispatch command
            self._started_at = time.time()
            try:
                # Notify digital twin if present
                twin_reg = ctx.get("twin_registry")
                if twin_reg:
                    try:
                        twin_reg.forward_command(device.id, cmd, params)
                    except Exception:
                        pass
                res = device.execute_command(cmd, params)
                if not isinstance(res, dict):
                    res = {"success": True, "message": str(res)}
                self._result = res
            except Exception as e:
                self._result = {"success": False, "message": str(e)}

            # For very short commands, return immediately
            if duration <= 0.05:
                return self._finish()

            self.status = NodeStatus.RUNNING
            return NodeStatus.RUNNING

        # Subsequent ticks — check duration
        if time.time() - self._started_at >= duration:
            return self._finish()

        self.status = NodeStatus.RUNNING
        return NodeStatus.RUNNING

    def _finish(self) -> NodeStatus:
        self._started_at = None
        if self._result and self._result.get("success", True):
            self.status = NodeStatus.SUCCESS
            return NodeStatus.SUCCESS
        self.status = NodeStatus.FAILURE
        return NodeStatus.FAILURE

    def reset(self):
        super().reset()
        self._started_at = None
        self._result = None


@_register
class NLPCommand(BTNode):
    """Compiles a natural-language description into an execution plan
    and runs it through the device. Bridges BT actions to the NLP
    pipeline so missions can contain human-readable steps."""

    category = "action"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.properties.setdefault("text", "")
        self.properties.setdefault("duration_s", 2.0)
        self._started_at: float | None = None
        self._result: dict | None = None

    def tick(self, bb, ctx) -> NodeStatus:
        device = ctx.get("device")
        if not device:
            self.status = NodeStatus.FAILURE
            return NodeStatus.FAILURE

        duration = float(self.properties.get("duration_s", 2.0))

        if self._started_at is None:
            self._started_at = time.time()
            text = self.properties.get("text", "")
            try:
                # Use the NLP compiler to convert text to plan, then
                # execute each step in the plan
                from omnix.nlp import compile_to_plan, list_capabilities_for_device
                caps = list_capabilities_for_device(device)
                plan = compile_to_plan(text, device.id, device.device_type, caps)
                success = True
                messages = []
                for step in plan.steps:
                    try:
                        res = device.execute_command(step.command, step.params)
                        if isinstance(res, dict) and not res.get("success", True):
                            success = False
                            messages.append(res.get("message", "failed"))
                    except Exception as e:
                        success = False
                        messages.append(str(e))
                self._result = {
                    "success": success,
                    "message": "; ".join(messages) if messages else "ok",
                    "steps_count": len(plan.steps),
                }
            except Exception as e:
                self._result = {"success": False, "message": str(e)}

            if duration <= 0.05:
                return self._finish()
            self.status = NodeStatus.RUNNING
            return NodeStatus.RUNNING

        if time.time() - self._started_at >= duration:
            return self._finish()
        self.status = NodeStatus.RUNNING
        return NodeStatus.RUNNING

    def _finish(self) -> NodeStatus:
        self._started_at = None
        if self._result and self._result.get("success", True):
            self.status = NodeStatus.SUCCESS
            return NodeStatus.SUCCESS
        self.status = NodeStatus.FAILURE
        return NodeStatus.FAILURE

    def reset(self):
        super().reset()
        self._started_at = None
        self._result = None


@_register
class Wait(BTNode):
    """Waits for `duration_s` seconds, then succeeds."""

    category = "action"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.properties.setdefault("duration_s", 1.0)
        self._started_at: float | None = None

    def tick(self, bb, ctx) -> NodeStatus:
        if self._started_at is None:
            self._started_at = time.time()
            self.status = NodeStatus.RUNNING
            return NodeStatus.RUNNING

        duration = float(self.properties.get("duration_s", 1.0))
        if time.time() - self._started_at >= duration:
            self._started_at = None
            self.status = NodeStatus.SUCCESS
            return NodeStatus.SUCCESS

        self.status = NodeStatus.RUNNING
        return NodeStatus.RUNNING

    def reset(self):
        super().reset()
        self._started_at = None


@_register
class Log(BTNode):
    """Writes a message to the blackboard log and succeeds immediately."""

    category = "action"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.properties.setdefault("message", "")
        self.properties.setdefault("level", "info")

    def tick(self, bb, ctx) -> NodeStatus:
        msg = self.properties.get("message", "")
        level = self.properties.get("level", "info")
        bb.log(msg, level=level)
        self.status = NodeStatus.SUCCESS
        return NodeStatus.SUCCESS


@_register
class SetVariable(BTNode):
    """Sets a blackboard variable and succeeds immediately."""

    category = "action"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.properties.setdefault("variable", "")
        self.properties.setdefault("value", "")

    def tick(self, bb, ctx) -> NodeStatus:
        bb.set(self.properties.get("variable", ""), self.properties.get("value", ""))
        self.status = NodeStatus.SUCCESS
        return NodeStatus.SUCCESS


@_register
class EmitEvent(BTNode):
    """Emits an event to the context event bus and succeeds."""

    category = "action"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.properties.setdefault("event", "")
        self.properties.setdefault("data", {})

    def tick(self, bb, ctx) -> NodeStatus:
        event_name = self.properties.get("event", "")
        event_data = self.properties.get("data", {})
        events = ctx.setdefault("events", [])
        events.append({"event": event_name, "data": event_data, "time": time.time()})
        bb.log(f"Event: {event_name}", level="event")
        self.status = NodeStatus.SUCCESS
        return NodeStatus.SUCCESS


# ═══════════════════════════════════════════════════════════
# CONDITION NODES (leaf nodes that CHECK things)
# ═══════════════════════════════════════════════════════════

@_register
class CheckBattery(BTNode):
    """Succeeds if battery >= min_pct, fails otherwise."""

    category = "condition"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.properties.setdefault("min_pct", 20)

    def tick(self, bb, ctx) -> NodeStatus:
        device = ctx.get("device")
        if not device:
            self.status = NodeStatus.FAILURE
            return NodeStatus.FAILURE
        try:
            tel = device.get_telemetry()
            battery = tel.get("battery_pct", tel.get("battery", 100))
            if battery >= self.properties.get("min_pct", 20):
                self.status = NodeStatus.SUCCESS
                return NodeStatus.SUCCESS
        except Exception:
            pass
        self.status = NodeStatus.FAILURE
        return NodeStatus.FAILURE


@_register
class CheckPosition(BTNode):
    """Succeeds if device is within `radius_m` of (target_x, target_y, target_z)."""

    category = "condition"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.properties.setdefault("target_x", 0.0)
        self.properties.setdefault("target_y", 0.0)
        self.properties.setdefault("target_z", 0.0)
        self.properties.setdefault("radius_m", 1.0)

    def tick(self, bb, ctx) -> NodeStatus:
        device = ctx.get("device")
        if not device:
            self.status = NodeStatus.FAILURE
            return NodeStatus.FAILURE
        try:
            tel = device.get_telemetry()
            pos = tel.get("position", {})
            dx = pos.get("x", 0) - float(self.properties.get("target_x", 0))
            dy = pos.get("y", 0) - float(self.properties.get("target_y", 0))
            dz = pos.get("z", 0) - float(self.properties.get("target_z", 0))
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)
            if dist <= float(self.properties.get("radius_m", 1.0)):
                self.status = NodeStatus.SUCCESS
                return NodeStatus.SUCCESS
        except Exception:
            pass
        self.status = NodeStatus.FAILURE
        return NodeStatus.FAILURE


@_register
class CheckTelemetry(BTNode):
    """Checks an arbitrary telemetry field. Succeeds if the field
    satisfies operator+value comparison."""

    category = "condition"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.properties.setdefault("field", "")
        self.properties.setdefault("operator", ">=")
        self.properties.setdefault("value", 0)

    def tick(self, bb, ctx) -> NodeStatus:
        device = ctx.get("device")
        if not device:
            self.status = NodeStatus.FAILURE
            return NodeStatus.FAILURE
        try:
            tel = device.get_telemetry()
            # Support nested fields via dot notation: "position.x"
            field_path = self.properties.get("field", "").split(".")
            val = tel
            for part in field_path:
                val = val[part] if isinstance(val, dict) else getattr(val, part)
            op = self.properties.get("operator", ">=")
            expected = self.properties.get("value", 0)
            if ConditionGate._check(val, op, expected):
                self.status = NodeStatus.SUCCESS
                return NodeStatus.SUCCESS
        except Exception:
            pass
        self.status = NodeStatus.FAILURE
        return NodeStatus.FAILURE


@_register
class CheckVariable(BTNode):
    """Checks a blackboard variable. Succeeds if comparison holds."""

    category = "condition"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.properties.setdefault("variable", "")
        self.properties.setdefault("operator", "==")
        self.properties.setdefault("value", True)

    def tick(self, bb, ctx) -> NodeStatus:
        actual = bb.get(self.properties.get("variable", ""))
        op = self.properties.get("operator", "==")
        expected = self.properties.get("value", True)
        if ConditionGate._check(actual, op, expected):
            self.status = NodeStatus.SUCCESS
            return NodeStatus.SUCCESS
        self.status = NodeStatus.FAILURE
        return NodeStatus.FAILURE


@_register
class IsConnected(BTNode):
    """Succeeds if the device reports as connected."""

    category = "condition"

    def tick(self, bb, ctx) -> NodeStatus:
        device = ctx.get("device")
        if not device:
            self.status = NodeStatus.FAILURE
            return NodeStatus.FAILURE
        try:
            tel = device.get_telemetry()
            if tel.get("connected", tel.get("status", "")) != "disconnected":
                self.status = NodeStatus.SUCCESS
                return NodeStatus.SUCCESS
        except Exception:
            pass
        self.status = NodeStatus.FAILURE
        return NodeStatus.FAILURE


@_register
class IsFlying(BTNode):
    """Succeeds if the drone is airborne (altitude > threshold or flying flag)."""

    category = "condition"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.properties.setdefault("min_altitude", 0.5)

    def tick(self, bb, ctx) -> NodeStatus:
        device = ctx.get("device")
        if not device:
            self.status = NodeStatus.FAILURE
            return NodeStatus.FAILURE
        try:
            tel = device.get_telemetry()
            pos = tel.get("position", {})
            alt = pos.get("z", pos.get("altitude", 0))
            if tel.get("flying", False) or alt >= float(self.properties.get("min_altitude", 0.5)):
                self.status = NodeStatus.SUCCESS
                return NodeStatus.SUCCESS
        except Exception:
            pass
        self.status = NodeStatus.FAILURE
        return NodeStatus.FAILURE


@_register
class IsMoving(BTNode):
    """Succeeds if the device's speed exceeds a threshold."""

    category = "condition"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.properties.setdefault("min_speed", 0.1)

    def tick(self, bb, ctx) -> NodeStatus:
        device = ctx.get("device")
        if not device:
            self.status = NodeStatus.FAILURE
            return NodeStatus.FAILURE
        try:
            tel = device.get_telemetry()
            vel = tel.get("velocity", {})
            speed = math.sqrt(
                vel.get("vx", 0)**2 + vel.get("vy", 0)**2 + vel.get("vz", 0)**2
            )
            if speed >= float(self.properties.get("min_speed", 0.1)):
                self.status = NodeStatus.SUCCESS
                return NodeStatus.SUCCESS
        except Exception:
            pass
        self.status = NodeStatus.FAILURE
        return NodeStatus.FAILURE
