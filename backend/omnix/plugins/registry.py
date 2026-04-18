"""
OMNIX Plugin Registry — tracks loaded plugins and their registrations.

The registry is the runtime state of the plugin system. It knows which
plugins are loaded, what connectors/sensors/commands they registered,
and handles hot-reload (unload → reload without server restart).
"""

import time
import threading
from typing import Dict, List, Optional, Type

from .base import OmnixPlugin, PluginMeta

try:
    from omnix.logging_setup import get_logger
    _log = get_logger("omnix.plugins.registry")
except Exception:
    import logging
    _log = logging.getLogger("omnix.plugins.registry")


class PluginRegistry:
    """Tracks all loaded plugins and provides lookup/reload."""

    def __init__(self):
        # plugin_name → OmnixPlugin instance
        self._plugins: Dict[str, OmnixPlugin] = {}
        self._lock = threading.Lock()

        # Callbacks set by the server to wire plugins into the platform.
        # These are called when a plugin registers a connector/sensor/etc.
        self._on_register_connector = None   # fn(connector_class)
        self._on_unregister_connector = None # fn(connector_id)
        self._on_register_sensor = None      # fn(sensor_spec_dict)
        self._on_unregister_sensor = None    # fn(device_id, sensor_id)

    # ── Platform integration hooks ────────────────────────

    def set_connector_hooks(self, register_fn, unregister_fn):
        """Set callbacks for connector registration/unregistration.

        Called by the server at startup to wire the plugin registry
        into the ConnectorManager.
        """
        self._on_register_connector = register_fn
        self._on_unregister_connector = unregister_fn

    def set_sensor_hooks(self, register_fn, unregister_fn):
        """Set callbacks for sensor registration/unregistration."""
        self._on_register_sensor = register_fn
        self._on_unregister_sensor = unregister_fn

    # ── Plugin lifecycle ──────────────────────────────────

    def load_plugin(self, plugin: OmnixPlugin) -> bool:
        """Load a plugin instance and call its on_load().

        Returns True on success. On failure, stores the error in the
        plugin instance and returns False.
        """
        if not plugin.meta:
            plugin._error = "Plugin has no meta attribute"
            _log.error("cannot load plugin without meta: %s", plugin)
            return False

        name = plugin.meta.name
        with self._lock:
            # If already loaded, unload first (hot-reload)
            if name in self._plugins:
                self._unload_locked(name)

        try:
            plugin.on_load()
            plugin._loaded = True
            plugin._error = None
        except Exception as e:
            plugin._error = f"on_load() failed: {e}"
            _log.exception("plugin %s on_load() failed", name)
            return False

        # Wire up registrations
        self._apply_registrations(plugin)

        with self._lock:
            self._plugins[name] = plugin

        _log.info("plugin loaded: %s v%s (%d connectors, %d sensors, %d commands)",
                  name, plugin.meta.version,
                  len(plugin._registered_connectors),
                  len(plugin._registered_sensors),
                  len(plugin._registered_commands))
        return True

    def unload_plugin(self, name: str) -> bool:
        """Unload a plugin by name. Calls on_unload() and removes registrations."""
        with self._lock:
            return self._unload_locked(name)

    def _unload_locked(self, name: str) -> bool:
        """Internal unload — caller must hold self._lock."""
        plugin = self._plugins.pop(name, None)
        if not plugin:
            return False

        # Remove platform registrations
        self._remove_registrations(plugin)

        # Call plugin's cleanup hook
        try:
            plugin.on_unload()
        except Exception as e:
            _log.exception("plugin %s on_unload() failed", name)

        plugin._loaded = False
        _log.info("plugin unloaded: %s", name)
        return True

    def reload_plugin(self, name: str, new_instance: OmnixPlugin) -> bool:
        """Hot-reload: unload the old instance, load the new one.

        This is the core of hot-reload — the server can call this
        after re-importing the plugin module.
        """
        self.unload_plugin(name)
        return self.load_plugin(new_instance)

    def reload_all(self, loader) -> Dict[str, bool]:
        """Reload all plugins using the given loader.

        Returns {plugin_name: success} for each plugin.
        """
        results = {}

        # Get current plugin names
        with self._lock:
            current_names = list(self._plugins.keys())

        # Unload all
        for name in current_names:
            self.unload_plugin(name)

        # Re-discover and load
        plugins = loader.discover()
        for plugin in plugins:
            name = plugin.meta.name if plugin.meta else "unknown"
            results[name] = self.load_plugin(plugin)

        return results

    # ── Enable/disable ────────────────────────────────────

    def enable_plugin(self, name: str) -> bool:
        """Enable a loaded plugin."""
        plugin = self._plugins.get(name)
        if not plugin:
            return False
        if plugin._enabled:
            return True

        plugin._enabled = True
        self._apply_registrations(plugin)
        _log.info("plugin enabled: %s", name)
        return True

    def disable_plugin(self, name: str) -> bool:
        """Disable a loaded plugin (unregisters without unloading)."""
        plugin = self._plugins.get(name)
        if not plugin:
            return False
        if not plugin._enabled:
            return True

        self._remove_registrations(plugin)
        plugin._enabled = False
        _log.info("plugin disabled: %s", name)
        return True

    # ── Queries ───────────────────────────────────────────

    def get_plugin(self, name: str) -> Optional[OmnixPlugin]:
        return self._plugins.get(name)

    def list_plugins(self) -> List[dict]:
        """Return info for all loaded plugins."""
        return [p.get_info() for p in self._plugins.values()]

    def get_plugin_names(self) -> List[str]:
        return list(self._plugins.keys())

    def get_all_commands(self) -> List[dict]:
        """Return all custom commands from all enabled plugins."""
        commands = []
        for plugin in self._plugins.values():
            if not plugin._enabled:
                continue
            for cmd in plugin._registered_commands:
                commands.append({
                    **{k: v for k, v in cmd.items() if k != "handler"},
                    "plugin": plugin.meta.name,
                })
        return commands

    def find_command_handler(self, command_name: str):
        """Find the handler function for a custom plugin command."""
        for plugin in self._plugins.values():
            if not plugin._enabled:
                continue
            for cmd in plugin._registered_commands:
                if cmd["name"] == command_name:
                    return cmd["handler"]
        return None

    # ── Internal ──────────────────────────────────────────

    def _apply_registrations(self, plugin: OmnixPlugin) -> None:
        """Wire plugin's registrations into the platform."""
        # Connectors
        if self._on_register_connector:
            for cls in plugin._registered_connectors:
                try:
                    self._on_register_connector(cls)
                except Exception as e:
                    _log.exception("failed to register connector from %s: %s",
                                   plugin.meta.name, e)

        # Sensors
        if self._on_register_sensor:
            for spec in plugin._registered_sensors:
                try:
                    self._on_register_sensor(spec)
                except Exception as e:
                    _log.exception("failed to register sensor from %s: %s",
                                   plugin.meta.name, e)

    def _remove_registrations(self, plugin: OmnixPlugin) -> None:
        """Remove plugin's registrations from the platform."""
        # Connectors
        if self._on_unregister_connector:
            for cls in plugin._registered_connectors:
                try:
                    meta = getattr(cls, "meta", None)
                    if meta:
                        self._on_unregister_connector(meta.connector_id)
                except Exception as e:
                    _log.exception("failed to unregister connector from %s: %s",
                                   plugin.meta.name, e)

        # Sensors
        if self._on_unregister_sensor:
            for spec in plugin._registered_sensors:
                try:
                    self._on_unregister_sensor(spec["device_id"], spec["sensor_id"])
                except Exception as e:
                    _log.exception("failed to unregister sensor from %s: %s",
                                   plugin.meta.name, e)
