"""
OMNIX Plugin Base — the class every plugin author extends.

A plugin is a self-contained extension that can register connectors,
sensors, commands, and dashboard views with the OMNIX platform. Plugins
live in the `plugins/` directory and are discovered automatically by
the PluginLoader.

Lifecycle:
    1. PluginLoader discovers the plugin directory
    2. PluginValidator checks structure and metadata
    3. Plugin class is instantiated
    4. on_load() is called — register connectors, sensors, commands, views
    5. Platform runs; plugin's connectors/sensors are live
    6. on_unload() is called on shutdown or hot-reload

Example:
    from omnix.plugins import OmnixPlugin, PluginMeta

    class MyPlugin(OmnixPlugin):
        meta = PluginMeta(
            name="my_plugin",
            version="1.0.0",
            author="Your Name",
            description="Does something cool",
            device_types=["custom_device"],
            capabilities=["control", "telemetry"],
        )

        def on_load(self):
            self.register_connector(MyConnectorClass)

        def on_unload(self):
            pass  # cleanup if needed
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any, Type, Callable


@dataclass
class PluginMeta:
    """Static metadata describing a plugin.

    This is read by the loader and displayed in the plugin management UI.
    Every plugin must set this as a class attribute.
    """
    name: str                              # unique identifier, e.g. "servo_controller"
    version: str                           # semver, e.g. "1.0.0"
    author: str = "Unknown"
    description: str = ""
    device_types: List[str] = field(default_factory=list)   # what device types this adds
    capabilities: List[str] = field(default_factory=list)   # what it can do
    omnix_version: str = ">=0.3.0"         # minimum OMNIX version required
    license: str = "MIT"
    homepage: str = ""
    icon: str = "🔌"
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class OmnixPlugin:
    """Base class for all OMNIX plugins.

    Subclass this and implement on_load() to register your connectors,
    sensors, commands, and views. The plugin system calls these methods
    at the appropriate lifecycle points.
    """

    meta: PluginMeta = None

    def __init__(self):
        # Filled by the plugin system after instantiation
        self._plugin_dir: str = ""

        # Registrations made by this plugin — tracked so we can
        # cleanly unload everything on hot-reload.
        self._registered_connectors: List[Type] = []
        self._registered_sensors: List[dict] = []
        self._registered_commands: List[dict] = []
        self._registered_views: List[dict] = []

        self._loaded = False
        self._enabled = True
        self._error: Optional[str] = None

    # ── Lifecycle hooks (override these) ──────────────────

    def on_load(self) -> None:
        """Called when the plugin is loaded.

        Override this to register connectors, sensors, commands, and views.
        This is the main entry point for your plugin.
        """
        pass

    def on_unload(self) -> None:
        """Called when the plugin is unloaded (shutdown or hot-reload).

        Override this to clean up resources, close connections, etc.
        """
        pass

    # ── Registration helpers ──────────────────────────────

    def register_connector(self, connector_class: Type) -> None:
        """Register a ConnectorBase subclass with the platform.

        The connector will appear in the connector list and can be
        started/stopped through the UI or API.

        Args:
            connector_class: A subclass of ConnectorBase with a valid meta.
        """
        self._registered_connectors.append(connector_class)

    def register_sensor(self, device_id: str, sensor_id: str,
                        name: str, sensor_type: str = "custom",
                        range_min: float = 0.0, range_max: float = 100.0,
                        unit: str = "") -> None:
        """Register a sensor channel with the platform.

        The sensor will appear in the sensor dashboard and receive
        readings pushed by the plugin's connector or background task.

        Args:
            device_id:   ID of the device this sensor belongs to.
            sensor_id:   Unique sensor ID within the device.
            name:        Human-readable sensor name.
            sensor_type: One of SENSOR_TYPES (temperature, distance, etc.)
            range_min:   Minimum expected value.
            range_max:   Maximum expected value.
            unit:        Unit label (e.g. "°C", "cm").
        """
        self._registered_sensors.append({
            "device_id": device_id,
            "sensor_id": sensor_id,
            "name": name,
            "sensor_type": sensor_type,
            "range_min": range_min,
            "range_max": range_max,
            "unit": unit,
        })

    def register_command(self, name: str, handler: Callable,
                         description: str = "",
                         device_types: List[str] = None) -> None:
        """Register a custom command that can be invoked via the API.

        Custom commands extend the platform's vocabulary beyond the
        built-in device commands. They appear in the command palette
        and can be called via POST /api/command.

        Args:
            name:         Command name (e.g. "calibrate_servo").
            handler:      Callable(device_id, params) -> dict.
            description:  What this command does.
            device_types: Which device types support this command (None = all).
        """
        self._registered_commands.append({
            "name": name,
            "handler": handler,
            "description": description,
            "device_types": device_types or [],
        })

    def register_view(self, name: str, html_file: str = "",
                      route: str = "", description: str = "",
                      icon: str = "📊") -> None:
        """Register a custom dashboard view/widget.

        Plugins can add their own dashboard panels. The view is served
        as an HTML file from the plugin's directory.

        Args:
            name:        Display name for the view tab.
            html_file:   Path to the HTML file (relative to plugin dir).
            route:       URL route to serve the view at (auto-generated if empty).
            description: Short description for the UI.
            icon:        Emoji icon for the tab.
        """
        if not route:
            safe_name = self.meta.name if self.meta else "plugin"
            route = f"/plugins/{safe_name}/{name.lower().replace(' ', '-')}"
        self._registered_views.append({
            "name": name,
            "html_file": html_file,
            "route": route,
            "description": description,
            "icon": icon,
        })

    # ── Introspection ─────────────────────────────────────

    def get_info(self) -> dict:
        """Return full plugin info for the API/UI."""
        return {
            "meta": self.meta.to_dict() if self.meta else {},
            "loaded": self._loaded,
            "enabled": self._enabled,
            "error": self._error,
            "plugin_dir": self._plugin_dir,
            "connectors": [
                {
                    "connector_id": getattr(c, "meta", {}).connector_id
                    if hasattr(getattr(c, "meta", None), "connector_id") else c.__name__,
                    "display_name": getattr(c, "meta", {}).display_name
                    if hasattr(getattr(c, "meta", None), "display_name") else c.__name__,
                }
                for c in self._registered_connectors
            ],
            "sensors": self._registered_sensors,
            "commands": [
                {"name": cmd["name"], "description": cmd["description"],
                 "device_types": cmd["device_types"]}
                for cmd in self._registered_commands
            ],
            "views": self._registered_views,
        }

    def __repr__(self):
        name = self.meta.name if self.meta else self.__class__.__name__
        ver = self.meta.version if self.meta else "?"
        return f"<OmnixPlugin {name}@{ver}>"
