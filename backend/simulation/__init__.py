"""OMNIX simulation — adaptive physics + scenarios + runner.

See:
  physics.py    — AdaptivePhysics: per-device-type learned parameters.
  scenarios.py  — Library of test scenarios per device type.
  runner.py     — Orchestrates a scenario run, records an iteration.
"""

from .physics import AdaptivePhysics, make_physics
from .scenarios import SCENARIOS, list_scenarios, get_scenario
from .runner import run_scenario

__all__ = [
    "AdaptivePhysics", "make_physics",
    "SCENARIOS", "list_scenarios", "get_scenario",
    "run_scenario",
]
