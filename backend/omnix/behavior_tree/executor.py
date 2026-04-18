"""
TreeExecutor — runs behavior trees on daemon threads.

Process-wide registry that manages concurrent tree executions,
one per device. Bridges action nodes to device.execute_command()
through the tick context, and feeds device telemetry into the
blackboard so condition nodes can react to real-time state.

Supports: pause, resume, stop, live status polling.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from typing import Any, Callable

from .nodes import NodeStatus
from .tree import BehaviorTree
from .blackboard import Blackboard


class ExecutionRecord:
    """Snapshot of a tree execution for status polling."""

    def __init__(self, tree: BehaviorTree, execution_id: str | None = None):
        self.execution_id: str = execution_id or f"btx-{uuid.uuid4().hex[:10]}"
        self.tree_id: str = tree.tree_id
        self.tree_name: str = tree.name
        self.device_id: str = tree.device_id
        self.status: str = "pending"  # pending|running|paused|completed|failed|stopped
        self.started_at: float | None = None
        self.completed_at: float | None = None
        self.tick_count: int = 0
        self.message: str = ""
        self.node_states: dict[str, str] = {}  # node_id → status string
        self.blackboard_snapshot: dict = {}
        self.logs: list[dict] = []
        self.events: list[dict] = []

    def to_dict(self) -> dict:
        return {
            "execution_id": self.execution_id,
            "tree_id": self.tree_id,
            "tree_name": self.tree_name,
            "device_id": self.device_id,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "tick_count": self.tick_count,
            "message": self.message,
            "node_states": dict(self.node_states),
            "blackboard": dict(self.blackboard_snapshot),
            "logs": list(self.logs),
            "events": list(self.events),
        }


class TreeExecutor:
    """Process-wide registry for running behavior trees."""

    def __init__(self, history_per_device: int = 10):
        self._active: dict[str, ExecutionRecord] = {}     # device_id → live record
        self._trees: dict[str, BehaviorTree] = {}          # device_id → running tree
        self._threads: dict[str, threading.Thread] = {}
        self._stop_flags: dict[str, threading.Event] = {}
        self._pause_flags: dict[str, threading.Event] = {}
        self._history: dict[str, deque] = {}
        self._history_size = history_per_device
        self._lock = threading.Lock()

    # ── Start / Stop / Pause / Resume ────────────────────

    def start(self, tree: BehaviorTree, device,
              tick_rate_hz: float = 5.0,
              on_complete: Callable | None = None,
              workspace_store=None,
              twin_registry=None) -> ExecutionRecord:
        """Start executing a tree on a daemon thread."""
        device_id = tree.device_id or device.id
        tree.device_id = device_id

        with self._lock:
            cur = self._active.get(device_id)
            if cur and cur.status == "running":
                raise RuntimeError(
                    f"Tree already running on {device_id} "
                    f"(execution_id={cur.execution_id})")

            tree.reset()
            record = ExecutionRecord(tree)
            record.status = "running"
            record.started_at = time.time()
            record.message = f"Starting: {tree.name}"
            self._active[device_id] = record
            self._trees[device_id] = tree

            stop = threading.Event()
            pause = threading.Event()
            self._stop_flags[device_id] = stop
            self._pause_flags[device_id] = pause

            t = threading.Thread(
                target=self._run,
                args=(tree, device, record, stop, pause, tick_rate_hz,
                      on_complete, workspace_store, twin_registry),
                name=f"bt-exec-{device_id[:8]}",
                daemon=True,
            )
            self._threads[device_id] = t
            t.start()
            return record

    def stop(self, device_id: str) -> bool:
        flag = self._stop_flags.get(device_id)
        if not flag:
            return False
        flag.set()
        # Also unpause so the thread wakes up
        pflag = self._pause_flags.get(device_id)
        if pflag:
            pflag.set()
        record = self._active.get(device_id)
        if record and record.status in ("running", "paused"):
            record.message = "Stopping…"
        return True

    def pause(self, device_id: str) -> bool:
        record = self._active.get(device_id)
        if not record or record.status != "running":
            return False
        pflag = self._pause_flags.get(device_id)
        if pflag:
            pflag.set()
        record.status = "paused"
        record.message = "Paused"
        return True

    def resume(self, device_id: str) -> bool:
        record = self._active.get(device_id)
        if not record or record.status != "paused":
            return False
        pflag = self._pause_flags.get(device_id)
        if pflag:
            pflag.clear()
        record.status = "running"
        record.message = "Resumed"
        return True

    # ── Queries ──────────────────────────────────────────

    def get(self, device_id: str) -> ExecutionRecord | None:
        return self._active.get(device_id)

    def get_tree(self, device_id: str) -> BehaviorTree | None:
        return self._trees.get(device_id)

    def history(self, device_id: str) -> list[dict]:
        return [r.to_dict() for r in self._history.get(device_id, deque())]

    def all_running(self) -> list[ExecutionRecord]:
        return [r for r in self._active.values() if r.status == "running"]

    # ── Internal runner ──────────────────────────────────

    def _run(self, tree: BehaviorTree, device, record: ExecutionRecord,
             stop: threading.Event, pause: threading.Event,
             tick_rate_hz: float, on_complete, workspace_store, twin_registry):
        interval = 1.0 / max(0.1, tick_rate_hz)
        context = {
            "device": device,
            "twin_registry": twin_registry,
            "events": [],
        }

        try:
            while not stop.is_set():
                # Pause check
                if pause.is_set() and not stop.is_set():
                    time.sleep(0.1)
                    continue

                # Feed telemetry into blackboard
                try:
                    tel = device.get_telemetry()
                    tree.blackboard.update({"_telemetry": tel})
                    # Also expose top-level fields
                    if isinstance(tel, dict):
                        for k, v in tel.items():
                            tree.blackboard.set(f"tel.{k}", v)
                except Exception:
                    pass

                # Tick the tree
                result = tree.tick(context)
                record.tick_count = tree.tick_count
                record.message = f"Tick {tree.tick_count}: {result.value}"

                # Snapshot node states for live visualization
                self._snapshot_nodes(tree, record)
                record.blackboard_snapshot = tree.blackboard.to_dict()
                record.logs = tree.blackboard.get_logs()
                record.events = list(context.get("events", []))

                if result == NodeStatus.SUCCESS:
                    record.status = "completed"
                    record.message = f"Mission complete — {tree.tick_count} ticks"
                    record.completed_at = time.time()
                    break
                elif result == NodeStatus.FAILURE:
                    record.status = "failed"
                    record.message = f"Mission failed at tick {tree.tick_count}"
                    record.completed_at = time.time()
                    break

                # Sleep until next tick (interruptible)
                stop.wait(interval)

            # If stopped by flag
            if stop.is_set() and record.status == "running":
                record.status = "stopped"
                record.message = "Stopped by user"
                record.completed_at = time.time()

        except Exception as e:
            record.status = "failed"
            record.message = f"Error: {e}"
            record.completed_at = time.time()

        finally:
            # Move to history
            with self._lock:
                h = self._history.setdefault(device_id := tree.device_id, deque(maxlen=self._history_size))
                h.append(record)

            # Log as workspace iteration if store provided
            if workspace_store and tree.device_id:
                try:
                    self._log_iteration(workspace_store, tree, record)
                except Exception:
                    pass

            if on_complete:
                try:
                    on_complete(record)
                except Exception:
                    pass

    def _snapshot_nodes(self, tree: BehaviorTree, record: ExecutionRecord):
        """Capture the status of every node for live visualization."""
        states = {}
        for node in tree.all_nodes():
            states[node.node_id] = node.status.value
        record.node_states = states

    def _log_iteration(self, workspace_store, tree: BehaviorTree,
                       record: ExecutionRecord):
        """Append a mission execution as a workspace iteration."""
        ws = workspace_store.get_by_device(tree.device_id)
        if not ws:
            return
        iteration = {
            "id": f"iter-{uuid.uuid4().hex[:8]}",
            "number": len(ws.get("iterations", [])) + 1,
            "scenario": "behavior_tree",
            "scenario_display_name": f"🌳 Mission: {tree.name}",
            "scenario_icon": "🌳",
            "duration_s": round((record.completed_at or time.time()) - (record.started_at or time.time()), 2),
            "metrics": {
                "overall": 1.0 if record.status == "completed" else 0.0,
                "ticks": record.tick_count,
                "status": record.status,
                "nodes": tree.node_count(),
            },
            "delta": {},
            "trajectory": [],
            "reference": [],
            "physics_after": None,
            "timestamp": time.time(),
            "note": f"BT execution: {record.message}",
            "tree_id": tree.tree_id,
        }
        workspace_store.append_iteration(tree.device_id, iteration)
