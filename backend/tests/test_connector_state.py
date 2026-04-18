"""Connector state machine + reconnect backoff."""

from __future__ import annotations

import time
import pytest

from connectors.base import ConnectorBase, ConnectorMeta, ConfigField
from omnix.models import ConnectorState


class _FlakyConnector(ConnectorBase):
    """Test double: connect() succeeds only after N attempts."""
    meta = ConnectorMeta(
        connector_id="flaky",
        display_name="Flaky Test",
        tier=1,
        description="Pass on the Nth attempt.",
        vpe_categories=["test"],
    )

    def __init__(self, *a, fail_first=2, **kw):
        super().__init__(*a, **kw)
        self.fail_first = fail_first
        self.connect_calls = 0

    def connect(self) -> bool:
        self.connect_calls += 1
        if self.connect_calls <= self.fail_first:
            self._mark_connected(False, f"simulated failure #{self.connect_calls}")
            return False
        self._mark_connected(True)
        return True


class TestStateMachine:
    def test_initial_state_is_disconnected(self):
        c = _FlakyConnector({})
        assert c._state == ConnectorState.DISCONNECTED

    def test_successful_connect_transitions_to_connected(self):
        c = _FlakyConnector({}, fail_first=0)
        assert c.connect() is True
        assert c._state == ConnectorState.CONNECTED
        assert c._connected is True

    def test_failed_connect_transitions_to_error(self):
        c = _FlakyConnector({}, fail_first=1)
        assert c.connect() is False
        assert c._state == ConnectorState.ERROR

    def test_status_dict_includes_state(self):
        c = _FlakyConnector({}, fail_first=0)
        c.connect()
        s = c.get_status()
        assert s["state"] == "connected"


class TestBackoff:
    def test_reconnect_delay_grows_exponentially(self):
        c = _FlakyConnector({}, fail_first=10)
        c.connect()   # attempt 0 fails → state=ERROR
        d0 = c.next_reconnect_delay()
        c._reconnect_attempts = 1
        d1 = c.next_reconnect_delay()
        c._reconnect_attempts = 3
        d3 = c.next_reconnect_delay()
        assert d1 >= d0
        assert d3 >= d1

    def test_reconnect_delay_capped(self):
        c = _FlakyConnector({})
        c._reconnect_attempts = 100
        delay = c.next_reconnect_delay()
        assert delay <= 30.0   # default cap

    def test_attempt_reconnect_respects_skip_until(self):
        c = _FlakyConnector({}, fail_first=10)
        c._skip_tick_until = time.time() + 60
        assert c.attempt_reconnect() is False
        # connect() should NOT have been called
        assert c.connect_calls == 0


class TestHeartbeat:
    def test_mark_heartbeat_moves_degraded_back_to_connected(self):
        c = _FlakyConnector({}, fail_first=0)
        c.connect()
        c._transition(ConnectorState.DEGRADED, "missed hb")
        assert c._state == ConnectorState.DEGRADED
        c.mark_heartbeat()
        assert c._state == ConnectorState.CONNECTED

    def test_check_heartbeat_flips_to_degraded(self):
        c = _FlakyConnector({}, fail_first=0)
        c.connect()
        # Pretend last heartbeat was an hour ago
        c._last_heartbeat = time.time() - 3600
        c.check_heartbeat_health()
        assert c._state == ConnectorState.DEGRADED

    def test_check_heartbeat_noop_when_no_heartbeat_recorded(self):
        c = _FlakyConnector({}, fail_first=0)
        c.connect()
        # Never called mark_heartbeat
        c.check_heartbeat_health()
        # Should stay connected — we only flip to degraded AFTER seeing at least one hb
        assert c._state == ConnectorState.CONNECTED
