"""
Shared pytest fixtures for the OMNIX test suite.

Adds the backend/ directory to sys.path so tests can import domain
modules (workspace_store, connectors, etc.) directly, without requiring
the project to be pip-installed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class _FakeDevice:
    """Minimal stand-in for OmnixDevice used in workspace tests."""

    def __init__(self, did: str = "fake-1", name: str = "Bench Rover",
                 device_type: str = "ground_robot"):
        self.id = did
        self.name = name
        self.device_type = device_type
        self._caps: list = []

    def get_capabilities(self):
        return self._caps


@pytest.fixture
def fake_drone():
    return _FakeDevice(did="d1", name="Drone-1", device_type="drone")


@pytest.fixture
def fake_rover():
    return _FakeDevice(did="r1", name="Rover-1", device_type="ground_robot")


@pytest.fixture
def fake_arm():
    return _FakeDevice(did="a1", name="Arm-1", device_type="robot_arm")


@pytest.fixture
def fresh_workspace_store():
    """A brand-new WorkspaceStore each test."""
    from workspace_store import WorkspaceStore
    return WorkspaceStore()


@pytest.fixture
def fresh_device_registry():
    """A plain dict used as the devices registry for ConnectorManager tests."""
    return {}
