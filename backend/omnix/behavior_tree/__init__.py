"""
OMNIX Behavior Tree — visual mission planner engine.

Classical behavior tree with tick-based execution, blackboard shared state,
and JSON-serializable tree definitions. Integrates with the NLP executor
pipeline so action nodes can dispatch device commands through the standard
execute_command() path.

Public API:

    from omnix.behavior_tree import (
        BehaviorTree, TreeExecutor, Blackboard,
        TEMPLATE_LIBRARY,
        # Node types:
        Sequence, Selector, Parallel,
        Repeat, RetryUntilSuccess, Inverter, Timeout, ConditionGate,
        ExecuteCommand, NLPCommand, Wait, Log, SetVariable, EmitEvent,
        CheckBattery, CheckPosition, CheckTelemetry, CheckVariable,
        IsConnected, IsFlying, IsMoving,
    )
"""

from .nodes import (
    NodeStatus,
    # Composites
    Sequence, Selector, Parallel,
    # Decorators
    Repeat, RetryUntilSuccess, Inverter, Timeout, ConditionGate,
    # Actions
    ExecuteCommand, NLPCommand, Wait, Log, SetVariable, EmitEvent,
    # Conditions
    CheckBattery, CheckPosition, CheckTelemetry, CheckVariable,
    IsConnected, IsFlying, IsMoving,
)
from .blackboard import Blackboard
from .tree import BehaviorTree
from .executor import TreeExecutor
from .library import TEMPLATE_LIBRARY

__all__ = [
    "NodeStatus",
    "Sequence", "Selector", "Parallel",
    "Repeat", "RetryUntilSuccess", "Inverter", "Timeout", "ConditionGate",
    "ExecuteCommand", "NLPCommand", "Wait", "Log", "SetVariable", "EmitEvent",
    "CheckBattery", "CheckPosition", "CheckTelemetry", "CheckVariable",
    "IsConnected", "IsFlying", "IsMoving",
    "Blackboard", "BehaviorTree", "TreeExecutor", "TEMPLATE_LIBRARY",
]
