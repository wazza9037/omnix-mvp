"""
OMNIX Plugin Template — LED Controller Example
================================================

This is a starter template for building OMNIX plugins. It demonstrates
how to create a plugin that registers a connector, sensor channels,
custom commands, and a dashboard view.

This example implements a simple LED controller that uses GPIO pins
(simulated by default). Replace the LED-specific code with your own
hardware integration.

Getting started:
    1. Copy this directory: cp -r _template/ my_plugin/
    2. Rename the class and update the PluginMeta
    3. Implement your connector in a separate file or inline
    4. Run: python omnix_cli.py plugin validate my_plugin
    5. Restart the server — your plugin loads automatically

File structure:
    my_plugin/
    ├── omnix_plugin.py     ← this file (required)
    ├── README.md           ← documentation (recommended)
    └── ...                 ← any other files your plugin needs
"""

import time
import random
import threading
from dataclasses import field

# Import the plugin SDK
from omnix.plugins import OmnixPlugin, PluginMeta

# Import the connector base classes so we can register a hardware adapter
from connectors.base import ConnectorBase, ConnectorMeta, ConnectorDevice
from connectors.base import ConfigField, SimulatedBackendMixin
from devices.base import DeviceCapability


# ── LED Connector ─────────────────────────────────────────
# This is the hardware adapter. It bridges OMNIX's universal protocol
# to your specific hardware. In this example, we simulate GPIO-based
# LED control.

class LEDConnector(SimulatedBackendMixin, ConnectorBase):
    """Controls LEDs via GPIO pins (simulated)."""

    meta = ConnectorMeta(
        connector_id="led_controller",
        display_name="LED Controller (GPIO)",
        tier=1,
        description="Control LEDs via GPIO pins on Raspberry Pi or Arduino.",
        vpe_categories=["smart_light", "custom"],
        config_schema=[
            ConfigField("pin_count", "Number of LEDs", type="number", default=3),
            ConfigField("mode", "Mode", type="select",
                        options=["simulate", "gpio"],
                        default="simulate",
                        help="Use 'simulate' for testing without hardware"),
        ],
        supports_simulation=True,
        icon="💡",
    )

    def __init__(self, config=None, **kwargs):
        super().__init__(config, **kwargs)
        self._led_states = {}    # pin → {on: bool, brightness: int, color: str}
        self._pin_count = 3

    def connect(self) -> bool:
        self._pin_count = int(self.config.get("pin_count", 3))
        mode = self.config.get("mode", "simulate")
        self._use_simulation = (mode == "simulate")

        # Initialize LED states
        for i in range(self._pin_count):
            self._led_states[i] = {
                "on": False,
                "brightness": 100,
                "color": "#ffffff",
            }

        # Build capabilities
        capabilities = [
            DeviceCapability(
                name="led_on",
                description="Turn an LED on",
                parameters=[
                    {"name": "pin", "type": "number", "min": 0,
                     "max": self._pin_count - 1},
                ],
                category="control",
            ),
            DeviceCapability(
                name="led_off",
                description="Turn an LED off",
                parameters=[
                    {"name": "pin", "type": "number", "min": 0,
                     "max": self._pin_count - 1},
                ],
                category="control",
            ),
            DeviceCapability(
                name="set_brightness",
                description="Set LED brightness (0-100)",
                parameters=[
                    {"name": "pin", "type": "number"},
                    {"name": "brightness", "type": "number", "min": 0, "max": 100},
                ],
                category="control",
            ),
            DeviceCapability(
                name="set_color",
                description="Set LED color (hex)",
                parameters=[
                    {"name": "pin", "type": "number"},
                    {"name": "color", "type": "text"},
                ],
                category="control",
            ),
            DeviceCapability(
                name="all_on",
                description="Turn all LEDs on",
                parameters=[],
                category="control",
            ),
            DeviceCapability(
                name="all_off",
                description="Turn all LEDs off",
                parameters=[],
                category="control",
            ),
        ]

        # Create the OMNIX device
        dev = ConnectorDevice(
            name=self.config.get("name", "LED Strip"),
            device_type="smart_light",
            capabilities=capabilities,
            command_handler=self._handle_command,
            telemetry_provider=self._get_telemetry,
            source_connector=self,
        )
        self._devices.append(dev)
        self._mark_connected(True)
        return True

    def _handle_command(self, command: str, params: dict) -> dict:
        pin = int(params.get("pin", 0))

        if command == "led_on":
            self._led_states.setdefault(pin, {})["on"] = True
            return {"success": True, "message": f"LED {pin} on"}

        elif command == "led_off":
            self._led_states.setdefault(pin, {})["on"] = False
            return {"success": True, "message": f"LED {pin} off"}

        elif command == "set_brightness":
            brightness = int(params.get("brightness", 100))
            self._led_states.setdefault(pin, {})["brightness"] = brightness
            return {"success": True, "message": f"LED {pin} brightness={brightness}"}

        elif command == "set_color":
            color = params.get("color", "#ffffff")
            self._led_states.setdefault(pin, {})["color"] = color
            return {"success": True, "message": f"LED {pin} color={color}"}

        elif command == "all_on":
            for p in self._led_states:
                self._led_states[p]["on"] = True
            return {"success": True, "message": "All LEDs on"}

        elif command == "all_off":
            for p in self._led_states:
                self._led_states[p]["on"] = False
            return {"success": True, "message": "All LEDs off"}

        return {"success": False, "message": f"Unknown command: {command}"}

    def _get_telemetry(self) -> dict:
        active = sum(1 for s in self._led_states.values() if s.get("on"))
        return {
            "led_count": self._pin_count,
            "active_count": active,
            "leds": dict(self._led_states),
            "mode": "simulated" if self._use_simulation else "gpio",
        }

    def tick(self):
        # In simulation mode we might add ambient effects here
        self.mark_heartbeat()


# ── Plugin Class ──────────────────────────────────────────
# This is the main entry point. The OMNIX plugin system discovers this
# class, reads its metadata, and calls on_load() to set everything up.

class LEDControllerPlugin(OmnixPlugin):
    """LED Controller plugin — demonstrates the OMNIX Plugin SDK."""

    meta = PluginMeta(
        name="led_controller",
        version="1.0.0",
        author="OMNIX Team",
        description="Control LEDs via GPIO pins. Supports brightness, "
                    "color, and individual pin addressing.",
        device_types=["smart_light"],
        capabilities=["led_control", "brightness", "color"],
        icon="💡",
        tags=["lighting", "gpio", "raspberry-pi", "arduino"],
    )

    def on_load(self):
        """Register the LED connector and a custom command."""
        # Register the connector — it will appear in the connector list
        self.register_connector(LEDConnector)

        # Register a custom command that works across all LED devices
        self.register_command(
            name="led_party_mode",
            handler=self._party_mode,
            description="Cycle all LEDs through rainbow colors",
            device_types=["smart_light"],
        )

    def on_unload(self):
        """Clean up when the plugin is unloaded."""
        pass  # Nothing to clean up in this example

    def _party_mode(self, device_id: str, params: dict) -> dict:
        """Custom command: cycle LEDs through colors."""
        return {
            "success": True,
            "message": "Party mode activated! LEDs cycling through rainbow.",
        }
