"""
OMNIX Plugin Loader — discovers and loads plugins from disk.

The loader scans a `plugins/` directory for subdirectories containing
an `omnix_plugin.py` file. Each plugin is validated, imported, and
instantiated. The resulting OmnixPlugin instances are handed to the
PluginRegistry.

Discovery rules:
  - Each plugin lives in its own subdirectory under plugins/
  - The subdirectory must contain an omnix_plugin.py file
  - omnix_plugin.py must define exactly one OmnixPlugin subclass
  - Directories starting with '_' or '.' are skipped (templates, hidden)

Hot-reload:
  - Call reload_plugin(name) to unload and re-import a single plugin
  - Call discover() again to pick up newly added plugins
  - Python's importlib.reload() is used to refresh the module
"""

import os
import sys
import importlib
import importlib.util
from typing import List, Optional, Tuple

from .base import OmnixPlugin
from .validator import PluginValidator

try:
    from omnix.logging_setup import get_logger
    _log = get_logger("omnix.plugins.loader")
except Exception:
    import logging
    _log = logging.getLogger("omnix.plugins.loader")


class PluginLoader:
    """Discovers and loads plugins from a directory."""

    def __init__(self, plugins_dir: str, validator: PluginValidator = None):
        self.plugins_dir = os.path.abspath(plugins_dir)
        self.validator = validator or PluginValidator()

        # module_name → module object (for reload support)
        self._modules = {}

    def discover(self) -> List[OmnixPlugin]:
        """Scan the plugins directory and return instantiated plugins.

        Skips directories starting with '_' or '.'.
        Validates each plugin before importing.
        Returns a list of OmnixPlugin instances (not yet loaded via on_load).
        """
        plugins = []

        if not os.path.isdir(self.plugins_dir):
            _log.warning("plugins directory not found: %s", self.plugins_dir)
            return plugins

        for entry in sorted(os.listdir(self.plugins_dir)):
            # Skip templates, hidden dirs, and non-directories
            if entry.startswith("_") or entry.startswith("."):
                continue
            plugin_dir = os.path.join(self.plugins_dir, entry)
            if not os.path.isdir(plugin_dir):
                continue

            plugin_file = os.path.join(plugin_dir, "omnix_plugin.py")
            if not os.path.isfile(plugin_file):
                continue

            plugin = self.load_from_dir(plugin_dir)
            if plugin:
                plugins.append(plugin)

        _log.info("discovered %d plugins in %s", len(plugins), self.plugins_dir)
        return plugins

    def load_from_dir(self, plugin_dir: str) -> Optional[OmnixPlugin]:
        """Load a single plugin from its directory.

        1. Validate the plugin structure
        2. Import the module
        3. Find the OmnixPlugin subclass
        4. Instantiate it
        """
        dirname = os.path.basename(plugin_dir)

        # Validate first
        is_valid, errors = self.validator.validate(plugin_dir)
        for err in errors:
            level = "warning" if err.level == "warning" else "error"
            getattr(_log, level)("plugin %s: %s", dirname, err.message)

        if not is_valid:
            _log.error("plugin %s failed validation, skipping", dirname)
            return None

        # Import the module
        module_name = f"omnix_plugin_{dirname}"
        plugin_file = os.path.join(plugin_dir, "omnix_plugin.py")

        try:
            # Add plugin dir to path so relative imports work
            if plugin_dir not in sys.path:
                sys.path.insert(0, plugin_dir)

            spec = importlib.util.spec_from_file_location(module_name, plugin_file)
            if not spec or not spec.loader:
                _log.error("cannot create module spec for %s", dirname)
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            self._modules[dirname] = module

        except Exception as e:
            _log.exception("failed to import plugin %s", dirname)
            return None

        # Find the OmnixPlugin subclass
        plugin_class = self._find_plugin_class(module)
        if not plugin_class:
            _log.error("no OmnixPlugin subclass found in %s", dirname)
            return None

        # Instantiate
        try:
            instance = plugin_class()
            instance._plugin_dir = plugin_dir

            # Validate meta at runtime
            if instance.meta:
                meta_errors = self.validator.validate_meta(instance.meta)
                for err in meta_errors:
                    level = "warning" if err.level == "warning" else "error"
                    getattr(_log, level)("plugin %s meta: %s", dirname, err.message)

                    if err.level == "error":
                        return None

            return instance

        except Exception as e:
            _log.exception("failed to instantiate plugin %s", dirname)
            return None

    def reload_module(self, name: str) -> Optional[OmnixPlugin]:
        """Reload a plugin's module and return a fresh instance.

        Used for hot-reload: the old instance should be unloaded from
        the registry before calling this.
        """
        module = self._modules.get(name)
        plugin_dir = os.path.join(self.plugins_dir, name)

        if not module:
            # Not previously loaded — try fresh load
            return self.load_from_dir(plugin_dir)

        # Re-validate
        is_valid, errors = self.validator.validate(plugin_dir)
        if not is_valid:
            _log.error("plugin %s failed validation on reload", name)
            return None

        try:
            module = importlib.reload(module)
            self._modules[name] = module
        except Exception as e:
            _log.exception("failed to reload module for %s", name)
            return None

        plugin_class = self._find_plugin_class(module)
        if not plugin_class:
            return None

        try:
            instance = plugin_class()
            instance._plugin_dir = plugin_dir
            return instance
        except Exception as e:
            _log.exception("failed to re-instantiate plugin %s", name)
            return None

    def list_available(self) -> List[dict]:
        """List available plugin directories (whether loaded or not)."""
        available = []
        if not os.path.isdir(self.plugins_dir):
            return available

        for entry in sorted(os.listdir(self.plugins_dir)):
            if entry.startswith("_") or entry.startswith("."):
                continue
            plugin_dir = os.path.join(self.plugins_dir, entry)
            if not os.path.isdir(plugin_dir):
                continue
            plugin_file = os.path.join(plugin_dir, "omnix_plugin.py")
            available.append({
                "name": entry,
                "dir": plugin_dir,
                "has_plugin_file": os.path.isfile(plugin_file),
                "has_readme": os.path.isfile(os.path.join(plugin_dir, "README.md")),
            })
        return available

    # ── Internal helpers ──────────────────────────────────

    def _find_plugin_class(self, module) -> Optional[type]:
        """Find the first OmnixPlugin subclass in a module."""
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type)
                    and issubclass(attr, OmnixPlugin)
                    and attr is not OmnixPlugin):
                return attr
        return None
