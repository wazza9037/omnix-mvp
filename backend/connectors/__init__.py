"""OMNIX connectors — adapters from the OMNIX protocol to real hardware / middleware.

See `base.py` for the contract. See `registry.json` for the VPE → connector
mapping. Each module in this package is a single connector.
"""

from .base import (
    ConnectorBase,
    ConnectorMeta,
    ConnectorDevice,
    ConfigField,
    SimulatedBackendMixin,
)

# Pre-import all shipped connectors so they can be `register()`-ed by the
# server at startup. Each of these modules is self-contained and has
# graceful fallbacks when required packages aren't installed.
from . import pi as _pi                    # noqa
from . import arduino_serial as _ardser    # noqa
from . import esp32_wifi as _esp32         # noqa
from . import tello as _tello              # noqa
from . import mavlink as _mav              # noqa
from . import ros2_bridge as _ros2         # noqa

ALL_CONNECTORS = [
    _pi.PiConnector,
    _ardser.ArduinoSerialConnector,
    _esp32.Esp32WifiConnector,
    _tello.TelloConnector,
    _mav.MavlinkConnector,
    _ros2.Ros2BridgeConnector,
]

__all__ = [
    "ConnectorBase",
    "ConnectorMeta",
    "ConnectorDevice",
    "ConfigField",
    "SimulatedBackendMixin",
    "ALL_CONNECTORS",
]
