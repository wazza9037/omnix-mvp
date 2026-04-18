"""
NLP pipeline data model.

Every stage of the pipeline produces + consumes typed dataclasses, so the
frontend, tests, and future consumers (Digital Twin replay, Behavior Tree
composer) don't need to reverse-engineer dict shapes.

Stage outputs:

  compile()  →  ExecutionPlan        (raw commands, may have issues)
  plan()     →  ValidatedPlan        (ExecutionPlan + annotations + waypoints)
  execute()  →  ExecutionState       (live progress + per-step status)

Two intentional properties:

  1. ExecutionPlan is JSON-round-trippable. Digital Twin will persist /
     replay these against real hardware.
  2. PlanStep carries its `expected_path` waypoints so the frontend can
     visualize the trajectory before execution — the planner fills these
     in from the device's current state + a simple kinematic model.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"
    STOPPED = "stopped"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class IssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class ValidationIssue:
    severity: IssueSeverity
    code: str                # stable code, e.g. "altitude_cap"
    message: str
    step_index: int | None = None

    def to_dict(self) -> dict:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "step_index": self.step_index,
        }


@dataclass
class PlanStep:
    """One atomic unit of an execution plan.

    Each step corresponds to one call to `device.execute_command(...)`.
    The planner annotates `expected_start_pos`, `expected_end_pos`, and
    `expected_path` so the 3D viewer can preview the trajectory.
    """
    id: str
    command: str
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    # Annotations added by the planner
    expected_duration_s: float = 1.0
    expected_start_pos: list[float] | None = None
    expected_end_pos: list[float] | None = None
    expected_path: list[list[float]] = field(default_factory=list)
    # Wait after the step before moving on (used by "hover for 30s")
    dwell_s: float = 0.0
    # Status — populated by the executor
    status: StepStatus = StepStatus.PENDING
    started_at: float | None = None
    ended_at: float | None = None
    result: dict | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class ExecutionPlan:
    """A compiled plan, ready for validation + execution."""
    plan_id: str
    device_id: str
    text: str                              # original user input
    steps: list[PlanStep] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)
    estimated_duration_s: float = 0.0
    estimated_battery_pct: float = 0.0
    created_at: float = field(default_factory=time.time)
    # If the compiler couldn't parse parts of the input, list them here
    unparsed_fragments: list[str] = field(default_factory=list)

    @staticmethod
    def new(device_id: str, text: str) -> "ExecutionPlan":
        return ExecutionPlan(
            plan_id=f"plan-{uuid.uuid4().hex[:10]}",
            device_id=device_id,
            text=text,
        )

    def add_step(self, command: str, params: dict = None,
                 description: str = "", duration_s: float = 1.0,
                 dwell_s: float = 0.0) -> PlanStep:
        s = PlanStep(
            id=f"s-{len(self.steps) + 1:03d}",
            command=command, params=params or {},
            description=description or command,
            expected_duration_s=duration_s,
            dwell_s=dwell_s,
        )
        self.steps.append(s)
        return s

    def add_issue(self, severity: IssueSeverity, code: str, message: str,
                  step_index: int | None = None) -> None:
        self.issues.append(ValidationIssue(severity, code, message, step_index))

    def has_errors(self) -> bool:
        return any(i.severity == IssueSeverity.ERROR for i in self.issues)

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "device_id": self.device_id,
            "text": self.text,
            "steps": [s.to_dict() for s in self.steps],
            "issues": [i.to_dict() for i in self.issues],
            "estimated_duration_s": round(self.estimated_duration_s, 2),
            "estimated_battery_pct": round(self.estimated_battery_pct, 2),
            "created_at": self.created_at,
            "unparsed_fragments": list(self.unparsed_fragments),
        }

    @staticmethod
    def from_dict(d: dict) -> "ExecutionPlan":
        p = ExecutionPlan(
            plan_id=d.get("plan_id", f"plan-{uuid.uuid4().hex[:10]}"),
            device_id=d["device_id"],
            text=d.get("text", ""),
            estimated_duration_s=float(d.get("estimated_duration_s", 0.0)),
            estimated_battery_pct=float(d.get("estimated_battery_pct", 0.0)),
            created_at=float(d.get("created_at", time.time())),
            unparsed_fragments=list(d.get("unparsed_fragments", [])),
        )
        for i_d in d.get("issues", []):
            p.issues.append(ValidationIssue(
                severity=IssueSeverity(i_d["severity"]),
                code=i_d["code"], message=i_d["message"],
                step_index=i_d.get("step_index"),
            ))
        for s_d in d.get("steps", []):
            p.steps.append(PlanStep(
                id=s_d["id"], command=s_d["command"],
                params=dict(s_d.get("params", {})),
                description=s_d.get("description", ""),
                expected_duration_s=float(s_d.get("expected_duration_s", 1.0)),
                expected_start_pos=s_d.get("expected_start_pos"),
                expected_end_pos=s_d.get("expected_end_pos"),
                expected_path=[list(p) for p in s_d.get("expected_path", [])],
                dwell_s=float(s_d.get("dwell_s", 0.0)),
                status=StepStatus(s_d.get("status", "pending")),
                started_at=s_d.get("started_at"),
                ended_at=s_d.get("ended_at"),
                result=s_d.get("result"),
            ))
        return p


@dataclass
class ExecutionState:
    """Live state of a running plan — polled by the frontend."""
    execution_id: str
    device_id: str
    plan: ExecutionPlan
    status: ExecutionStatus = ExecutionStatus.PENDING
    current_step: int = 0                   # 0-indexed
    message: str = ""
    error: str | None = None
    started_at: float | None = None
    ended_at: float | None = None
    # Actual traveled path (waypoints observed from device telemetry during execution)
    traveled_path: list[list[float]] = field(default_factory=list)

    @staticmethod
    def new(plan: ExecutionPlan) -> "ExecutionState":
        return ExecutionState(
            execution_id=f"exec-{uuid.uuid4().hex[:10]}",
            device_id=plan.device_id,
            plan=plan,
        )

    def to_dict(self) -> dict:
        return {
            "execution_id": self.execution_id,
            "device_id": self.device_id,
            "plan": self.plan.to_dict(),
            "status": self.status.value,
            "current_step": self.current_step,
            "total_steps": len(self.plan.steps),
            "message": self.message,
            "error": self.error,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "elapsed_s": round((self.ended_at or time.time()) - self.started_at, 2)
                if self.started_at else 0.0,
            "traveled_path": [list(p) for p in self.traveled_path],
        }
