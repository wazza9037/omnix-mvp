"""
OMNIX Natural Language Robot Programming.

Public pipeline:

    from omnix.nlp import compile_plan, plan_and_validate, REGISTRY

    plan = compile_plan("take off and hover at 5 meters", device)
    plan_and_validate(plan, device_type=device.device_type,
                      telemetry=device.get_telemetry(),
                      capability_names=[c['name'] for c in device.get_capabilities()])
    state = REGISTRY.start(plan, device)   # runs on a daemon thread
"""

from .models import (
    ExecutionPlan, PlanStep, ValidationIssue, IssueSeverity,
    ExecutionState, ExecutionStatus, StepStatus,
)
from .compiler import (
    compile_plan, compile_to_plan, llm_available,
)
from .planner import plan_and_validate
from .executor import REGISTRY, iteration_from_state
from .patterns import list_capabilities_for_device

__all__ = [
    "ExecutionPlan", "PlanStep", "ValidationIssue", "IssueSeverity",
    "ExecutionState", "ExecutionStatus", "StepStatus",
    "compile_plan", "compile_to_plan", "llm_available",
    "plan_and_validate",
    "REGISTRY", "iteration_from_state",
    "list_capabilities_for_device",
]
