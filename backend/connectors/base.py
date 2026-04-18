"""
OMNIX Connector Base — the universal adapter interface.

A connector is the bridge between OMNIX's abstract protocol and a specific
hardware or middleware system. Every robot integration in OMNIX is a
connector: Raspberry Pi, Arduino, ESP32, MAVLink drones, DJI Tello,
ROS2 bridge, and so on.

Connector tiers
---------------
  1. DIY / open hardware         (Pi, Arduino, ESP32) - you ship the agent
  2. Open-standard robots        (MAVLink, ROS2, Tello) - public protocol
  3. Proprietary consumer/pro    (DJI, Spot, UR) - vendor SDK, auth needed

A connector, once started, produces one or more OmnixDevice instances that
are registered with the server's main device registry. From that point on
they behave like any other OMNIX device — same dashboard, same telemetry,
same movement presets.

Required interface:
    meta (classvar: ConnectorMeta)   - static description of the connector
    connect()     -> bool            - establish transport, create devices
    disconnect()                     - tear down, stop background threads
    tick()                           - optional periodic work (polling etc.)
    get_devices() -> list[OmnixDevice]
    is_connected()
    get_status()  -> dict            - for /api/connectors/instances

Connectors should be resilient: transport failure should mark the
connector as disconnected but must not raise out of connect() once devices
have been produced. Use self._error to surface problems to the UI.
"""

import time
import uuid
import threading
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any, Callable

# Import the existing OmnixDevice interface so connector devices are
# indistinguishable from simulated ones at the server level.
from devices.base import OmnixDevice, DeviceCapability

# Import the shared state machine enum + settings. Kept as a defensive
# try/except so the connectors can still be imported if omnix/ is broken.
try:
    from omnix.models import ConnectorState
    from omnix.config import settings as _omnix_settings
    from omnix.logging_setup import get_logger
    _log = get_logger("omnix.connector")
except Exception:  # pragma: no cover - defensive
    import enum
    class ConnectorState(str, enum.Enum):
        DISCONNECTED = "disconnected"; CONNECTING = "connecting"
        CONNECTED = "connected"; DEGRADED = "degraded"
        ERROR = "error"; RECONNECTING = "reconnecting"
    _omnix_settings = None
    import logging as _logging
    _log = _logging.getLogger("omnix.connector")


# ───────────────────────────────────────────────────────────
#  Connector metadata
# ───────────────────────────────────────────────────────────

@dataclass
class ConfigField:
    """One input field in the connector's setup form."""
    key: str
    label: str
    type: str = "text"                 # text | number | select | password | bool
    default: Any = ""
    required: bool = False
    placeholder: str = ""
    options: list = field(default_factory=list)   # for type=select
    help: str = ""


@dataclass
class ConnectorMeta:
    """Static description of a connector implementation.

    The registry + UI use this to render setup flows. It's separate from
    a running instance's state.
    """
    connector_id: str                  # stable identifier, e.g. "tello"
    display_name: str                  # "DJI Tello (UDP)"
    tier: int                          # 1, 2 or 3
    description: str                   # short UI blurb
    vpe_categories: List[str]          # VPE categories this can handle
    required_packages: List[str] = field(default_factory=list)
    config_schema: List[ConfigField] = field(default_factory=list)
    setup_steps: List[str] = field(default_factory=list)
    supports_simulation: bool = False  # can run with no hardware?
    docs_url: str = ""
    icon: str = "🔌"
    vendor: str = ""                   # "Raspberry Pi Foundation", "DJI", etc.

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ───────────────────────────────────────────────────────────
#  ConnectorDevice — a thin OmnixDevice that delegates to the connector
# ───────────────────────────────────────────────────────────

class ConnectorDevice(OmnixDevice):
    """An OmnixDevice instance owned by a connector.

    The connector supplies `command_handler` and `telemetry_provider`
    callbacks; this class adapts them to the OmnixDevice interface so
    the rest of OMNIX (dashboard, movement system, event log) works
    without modification.
    """

    def __init__(self,
                 name: str,
                 device_type: str,
                 capabilities: List[DeviceCapability],
                 command_handler: Callable[[str, dict], dict],
                 telemetry_provider: Callable[[], dict],
                 source_connector: "ConnectorBase" = None,
                 custom_id: str = None):
        super().__init__(name, device_type)
        if custom_id:
            self.id = custom_id
        for cap in capabilities:
            self.register_capability(cap)
        self._command_handler = command_handler
        self._telemetry_provider = telemetry_provider
        self.source_connector = source_connector
        self._last_telemetry = {}
        self._last_telemetry_at = 0.0

    def execute_command(self, command: str, params: dict = None) -> dict:
        params = params or {}
        try:
            result = self._command_handler(command, params)
            if not isinstance(result, dict):
                result = {"success": True, "message": str(result)}
            self.log_event(command, result.get("message", ""))
            return result
        except Exception as e:
            msg = f"Connector error: {e}"
            self.log_event("error", msg)
            return {"success": False, "message": msg}

    def get_telemetry(self) -> dict:
        # Cache telemetry for 200ms — keeps polling cheap when the
        # dashboard hits this at 600ms intervals while animations / movement
        # executors may hit it more often.
        now = time.time()
        if now - self._last_telemetry_at < 0.2:
            return self._last_telemetry
        try:
            t = self._telemetry_provider() or {}
            self._last_telemetry = t
            self._last_telemetry_at = now
            return t
        except Exception as e:
            return {"error": f"telemetry failed: {e}"}


# ───────────────────────────────────────────────────────────
#  ConnectorBase
# ───────────────────────────────────────────────────────────

class ConnectorBase:
    """Abstract base for all connectors.

    Subclasses must:
      - set `meta: ConnectorMeta`
      - implement `connect()` and populate `self._devices`
      - implement `disconnect()` if they hold resources

    Subclasses may override `tick()` for polling-style work; the
    ConnectorManager calls it every ~500ms on a background thread.
    """

    meta: ConnectorMeta = None

    def __init__(self, config: dict = None, instance_id: str = None):
        self.config = dict(config or {})
        self.instance_id = instance_id or f"inst-{uuid.uuid4().hex[:6]}"
        self._devices: List[OmnixDevice] = []
        self._connected = False
        self._error: Optional[str] = None
        self._started_at: Optional[float] = None
        self._lock = threading.Lock()

        # State machine
        self._state: ConnectorState = ConnectorState.DISCONNECTED
        self._last_heartbeat: Optional[float] = None
        self._reconnect_attempts = 0
        # When non-None, tick() will skip until this time (for backoff)
        self._skip_tick_until: float = 0.0

    # ── Required overrides ─────────────────────────────────

    def connect(self) -> bool:
        """Open transport, discover/create devices, set _connected=True.

        Must set self._error on failure and return False. Must not raise.
        """
        raise NotImplementedError

    def disconnect(self) -> None:
        """Close transport, stop threads. Called by the manager."""
        self._connected = False

    # ── Optional overrides ─────────────────────────────────

    def tick(self) -> None:
        """Called periodically (~every 500ms) by the manager.

        Typical uses: send heartbeat, pull telemetry, reap dead sockets.
        """
        pass

    # ── Read-only helpers, do not override ─────────────────

    def get_devices(self) -> List[OmnixDevice]:
        return list(self._devices)

    def is_connected(self) -> bool:
        return self._connected

    def get_status(self) -> dict:
        return {
            "instance_id": self.instance_id,
            "connector_id": self.meta.connector_id if self.meta else "?",
            "display_name": self.meta.display_name if self.meta else "?",
            "tier": self.meta.tier if self.meta else 0,
            "state": self._state.value,
            "connected": self._connected,
            "device_ids": [d.id for d in self._devices],
            "device_count": len(self._devices),
            "error": self._error,
            "started_at": self._started_at,
            "uptime_s": round(time.time() - self._started_at, 1) if self._started_at else 0,
            "last_heartbeat": self._last_heartbeat,
            "reconnect_attempts": self._reconnect_attempts,
            "config": self._sanitize_config(),
        }

    def _sanitize_config(self) -> dict:
        safe = dict(self.config)
        for k in list(safe.keys()):
            kl = k.lower()
            if any(s in kl for s in ("password", "token", "secret", "api_key", "apikey")):
                if safe[k]:
                    safe[k] = "***"
        return safe

    # ── State machine helpers ──────────────────────────────

    def _transition(self, new_state: ConnectorState, error: str = None) -> None:
        """Move to a new state and log the transition.

        Emits a structured log line so state flow is observable without
        having to add prints to every connector.
        """
        with self._lock:
            if self._state == new_state:
                return
            _log.info("connector %s/%s: %s → %s%s",
                      self.meta.connector_id if self.meta else "?",
                      self.instance_id,
                      self._state.value, new_state.value,
                      f" ({error})" if error else "",
                      extra={
                          "connector_id": self.meta.connector_id if self.meta else None,
                          "instance_id": self.instance_id,
                          "from_state": self._state.value,
                          "to_state": new_state.value,
                          "error": error,
                      })
            self._state = new_state
            if error is not None:
                self._error = error
            # Reset retries on fresh success
            if new_state == ConnectorState.CONNECTED:
                self._reconnect_attempts = 0
                self._error = None

    def _mark_connected(self, value: bool = True, error: str = None):
        """Backward-compatible wrapper — sets connected flag + state.

        Preserved so existing connectors keep working; new code should
        prefer `_transition()` directly for richer state control.
        """
        with self._lock:
            self._connected = value
            self._error = error
            if value and not self._started_at:
                self._started_at = time.time()
        if value:
            self._transition(ConnectorState.CONNECTED)
        elif error:
            self._transition(ConnectorState.ERROR, error)
        else:
            self._transition(ConnectorState.DISCONNECTED)

    def mark_heartbeat(self) -> None:
        """Connectors call this when they see proof of life from upstream
        (a heartbeat frame, a telemetry frame, a successful ack). The
        manager uses this + config.connector_heartbeat_timeout to decide
        when to flip to DEGRADED."""
        self._last_heartbeat = time.time()
        if self._state == ConnectorState.DEGRADED:
            self._transition(ConnectorState.CONNECTED)

    def check_heartbeat_health(self) -> None:
        """Flip to DEGRADED if we haven't heard anything in too long.

        Called each tick by the manager.
        """
        if not self._connected or self._last_heartbeat is None:
            return
        timeout = 10.0
        if _omnix_settings is not None:
            timeout = _omnix_settings.connector_heartbeat_timeout
        if time.time() - self._last_heartbeat > timeout:
            if self._state != ConnectorState.DEGRADED:
                self._transition(ConnectorState.DEGRADED,
                                 f"no heartbeat for {timeout:.0f}s")

    def next_reconnect_delay(self) -> float:
        """Exponential backoff delay for the next reconnect attempt."""
        initial = 1.0
        cap = 30.0
        if _omnix_settings is not None:
            initial = _omnix_settings.connector_reconnect_initial_backoff
            cap = _omnix_settings.connector_reconnect_max_backoff
        delay = min(cap, initial * (2 ** min(8, self._reconnect_attempts)))
        return delay

    def attempt_reconnect(self) -> bool:
        """Try to re-establish the connection. Idempotent; safe to call
        from the manager's tick loop when the instance is in ERROR state.

        Subclasses usually don't override this — they override `connect()`.
        """
        now = time.time()
        if now < self._skip_tick_until:
            return False
        self._reconnect_attempts += 1
        self._transition(ConnectorState.RECONNECTING)
        try:
            ok = self.connect()
        except Exception as e:
            _log.exception("reconnect raised on %s", self.instance_id)
            ok = False
            self._transition(ConnectorState.ERROR, str(e))
        if ok:
            return True
        # Schedule next try
        delay = self.next_reconnect_delay()
        self._skip_tick_until = now + delay
        self._transition(ConnectorState.ERROR,
                         f"reconnect failed (attempt {self._reconnect_attempts}, "
                         f"next try in {delay:.1f}s)")
        return False


# ───────────────────────────────────────────────────────────
#  Simulated-hardware helper
# ───────────────────────────────────────────────────────────

class SimulatedBackendMixin:
    """Utility mixin for connectors that want an automatic simulated
    fallback when real hardware/libs are absent. Subclasses set
    `self._use_simulation` and call `_sim_tick()` from tick().
    """

    _use_simulation: bool = False

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._sim_state: Dict[str, Any] = {}

    def _sim_set(self, **kwargs):
        self._sim_state.update(kwargs)

    def _sim_tick(self):
        """Override for per-tick simulation updates."""
        pass
