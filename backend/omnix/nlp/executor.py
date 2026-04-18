"""
Plan executor.

One process-wide ExecutorRegistry owns all active executions. Each
execution runs on a daemon thread so HTTP handlers stay responsive.

Flow:

    registry.start(plan, device) → ExecutionState (status=running)
    executor thread walks plan.steps
    each step:
      - mark RUNNING, call device.execute_command(...)
      - wait the expected_duration_s + dwell_s (respecting the stop flag)
      - mark OK / FAILED
    on completion:
      - status = COMPLETED / STOPPED / FAILED
      - (if workspace_store given) append an iteration row summarizing the run

Important: we DON'T block the HTTP handler — /api/nlp/execute returns
immediately with the initial state and the frontend polls
/api/nlp/execution/<device_id> for progress.

The registry keeps the N most recent completed executions per device so
the UI can show a "recent runs" list.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from typing import Any

from .models import (
    ExecutionPlan, ExecutionState, ExecutionStatus, StepStatus, IssueSeverity,
)


# ── Single-process registry ─────────────────────────────────────────

class ExecutorRegistry:
    """Owns every live + recent execution."""

    def __init__(self, history_per_device: int = 5):
        self._active: dict[str, ExecutionState] = {}      # device_id → live state
        self._threads: dict[str, threading.Thread] = {}    # device_id → runner
        self._stop_flags: dict[str, threading.Event] = {}  # device_id → stop flag
        self._history: dict[str, deque] = {}              # device_id → finished states
        self._history_size = history_per_device
        self._lock = threading.Lock()

    # ── Lifecycle ──────────────────────────────────────────

    def start(self, plan: ExecutionPlan, device,
              on_iteration=None) -> ExecutionState:
        """Kick off execution. Raises if one's already running for this device."""
        device_id = plan.device_id
        with self._lock:
            cur = self._active.get(device_id)
            if cur and cur.status == ExecutionStatus.RUNNING:
                raise RuntimeError(
                    f"Another execution is already running on {device_id} "
                    f"(execution_id={cur.execution_id})")

            # Refuse plans with compile-time errors
            if plan.has_errors():
                state = ExecutionState.new(plan)
                state.status = ExecutionStatus.FAILED
                state.error = "Plan contains validation errors — refusing to run."
                self._active[device_id] = state
                return state

            state = ExecutionState.new(plan)
            state.status = ExecutionStatus.RUNNING
            state.started_at = time.time()
            state.message = "Starting…"
            self._active[device_id] = state

            stop = threading.Event()
            self._stop_flags[device_id] = stop

            t = threading.Thread(
                target=self._run,
                args=(state, device, stop, on_iteration),
                name=f"nlp-exec-{device_id[:8]}",
                daemon=True,
            )
            self._threads[device_id] = t
            t.start()
            return state

    def stop(self, device_id: str, reason: str = "user requested") -> bool:
        flag = self._stop_flags.get(device_id)
        if not flag:
            return False
        flag.set()
        state = self._active.get(device_id)
        if state and state.status == ExecutionStatus.RUNNING:
            state.message = f"Stopping ({reason})…"
        return True

    # ── Queries ───────────────────────────────────────────

    def get(self, device_id: str) -> ExecutionState | None:
        return self._active.get(device_id)

    def history(self, device_id: str) -> list[ExecutionState]:
        return list(self._history.get(device_id, deque()))

    def all_running(self) -> list[ExecutionState]:
        return [s for s in self._active.values()
                if s.status == ExecutionStatus.RUNNING]

    # ── Internal runner ───────────────────────────────────

    def _run(self, state: ExecutionState, device,
             stop: threading.Event, on_iteration) -> None:
        plan = state.plan
        try:
            for idx, step in enumerate(plan.steps):
                if stop.is_set():
                    self._stop_remaining(plan, idx)
                    state.status = ExecutionStatus.STOPPED
                    state.message = "Stopped by user"
                    break

                state.current_step = idx
                step.status = StepStatus.RUNNING
                step.started_at = time.time()
                state.message = step.description or step.command

                # Pre-check step: "_battery_precheck"
                if step.command == "_battery_precheck":
                    result = self._handle_precheck(step, device, plan)
                    if result == "abort":
                        state.status = ExecutionStatus.STOPPED
                        state.message = "Battery too low — aborting per pre-check"
                        break
                    step.status = StepStatus.OK
                    step.result = {"success": True, "message": "precheck ok"}
                    step.ended_at = time.time()
                    if step.expected_end_pos:
                        state.traveled_path.append(list(step.expected_end_pos))
                    continue

                # Tell the twin (if any) that we're about to dispatch this
                # command — so its predictor can step the physics model in
                # parallel with the real device. Kept as a soft import so
                # the executor stays independent of the twin package.
                try:
                    from omnix.digital_twin import REGISTRY as _twin_reg
                    _twin_reg.forward_command(device.id, step.command, step.params)
                except Exception:
                    pass

                # Dispatch the command
                try:
                    res = device.execute_command(step.command, step.params)
                    if not isinstance(res, dict):
                        res = {"success": True, "message": str(res)}
                    step.result = res
                    if res.get("success", True):
                        step.status = StepStatus.OK
                    else:
                        step.status = StepStatus.FAILED
                except Exception as e:
                    step.status = StepStatus.FAILED
                    step.result = {"success": False, "message": f"exception: {e}"}

                # Record the step's expected end position in the traveled path
                # so the 3D viewer can draw what was actually executed even
                # before the device telemetry catches up.
                if step.expected_end_pos:
                    state.traveled_path.append(list(step.expected_end_pos))

                # Wait for the step's expected duration (plus any dwell),
                # respecting the stop flag at small intervals.
                total_wait = step.expected_duration_s + step.dwell_s
                waited = 0.0
                slice_s = 0.1
                while waited < total_wait and not stop.is_set():
                    time.sleep(min(slice_s, total_wait - waited))
                    waited += slice_s

                step.ended_at = time.time()

                # If a step failed, abort the rest — don't keep marching
                # on with undefined state.
                if step.status == StepStatus.FAILED:
                    self._stop_remaining(plan, idx + 1)
                    state.status = ExecutionStatus.FAILED
                    state.error = step.result.get("message", "Step failed")
                    state.message = f"Step {idx + 1} failed: {state.error}"
                    break

                # Stop requested DURING the wait? Mark remaining as skipped.
                if stop.is_set():
                    self._stop_remaining(plan, idx + 1)
                    state.status = ExecutionStatus.STOPPED
                    state.message = "Stopped by user"
                    break
            else:
                # Loop completed normally
                state.current_step = len(plan.steps)
                state.status = ExecutionStatus.COMPLETED
                state.message = "Plan completed"
        except Exception as e:
            state.status = ExecutionStatus.FAILED
            state.error = f"executor error: {e}"
            state.message = state.error
        finally:
            state.ended_at = time.time()
            # Record an iteration if the caller provided a hook
            if on_iteration is not None:
                try:
                    on_iteration(state)
                except Exception:
                    pass
            self._archive(state)

    def _handle_precheck(self, step, device, plan) -> str:
        """Return 'abort' if the pre-check wants to stop the plan, else 'ok'."""
        min_pct = float(step.params.get("min_pct", 0))
        try:
            tele = device.get_telemetry() or {}
        except Exception:
            tele = {}
        batt = tele.get("battery_pct",
                        tele.get("battery", 100.0))
        if float(batt) < min_pct:
            # Future: honour `on_fail` ("return_home" → issue return command).
            # Simple path today: abort.
            return "abort"
        return "ok"

    def _stop_remaining(self, plan, from_idx: int) -> None:
        for s in plan.steps[from_idx:]:
            if s.status == StepStatus.PENDING:
                s.status = StepStatus.SKIPPED

    def _archive(self, state: ExecutionState) -> None:
        with self._lock:
            hist = self._history.setdefault(state.device_id,
                                             deque(maxlen=self._history_size))
            hist.appendleft(state)
            # Clear active slot; keep in _active for 1 more GET so the UI
            # can catch the final status, then rely on history.
            self._stop_flags.pop(state.device_id, None)
            self._threads.pop(state.device_id, None)


# Module-level registry — server_simple.py wires routes to this
REGISTRY = ExecutorRegistry()


# ── Iteration-log bridge ────────────────────────────────────────────

def iteration_from_state(state: ExecutionState) -> dict:
    """Convert a finished ExecutionState into an iteration dict suitable
    for workspace_store.append_iteration().

    This is how NLP executions feed into the "lab notebook" — each run is
    a logged iteration with metrics and trajectory, just like a scenario.
    """
    ok = sum(1 for s in state.plan.steps if s.status == StepStatus.OK)
    fail = sum(1 for s in state.plan.steps if s.status == StepStatus.FAILED)
    skip = sum(1 for s in state.plan.steps if s.status == StepStatus.SKIPPED)
    total = max(1, len(state.plan.steps))
    success_rate = ok / total
    elapsed = (state.ended_at or time.time()) - (state.started_at or time.time())

    trajectory = []
    for i, p in enumerate(state.traveled_path):
        trajectory.append({
            "t": round(elapsed * i / max(1, len(state.traveled_path)), 3),
            "pos": list(p),
        })

    return {
        "scenario": "nlp_plan",
        "scenario_display_name": f"NLP · “{state.plan.text[:40]}”",
        "scenario_icon": "💬",
        "duration_s": round(elapsed, 2),
        "params": {"text": state.plan.text, "step_count": total},
        "metrics": {
            "success_rate": round(success_rate, 3),
            "steps_ok": ok, "steps_failed": fail, "steps_skipped": skip,
            "overall": round(success_rate, 3),
        },
        "trajectory": trajectory,
        "reference": [],
        "note": "",
        "physics_after": {"confidence": 0.0, "fit_error": 0.0,
                           "samples": 0, "params": {}, "last_updated": time.time()},
        "timestamp": state.started_at or time.time(),
    }
