"""
OMNIX Plugin SDK — let the community build connectors and extensions.

This package provides the plugin infrastructure:
  - base.py      : OmnixPlugin base class for plugin authors
  - loader.py    : PluginLoader that discovers plugins on disk
  - registry.py  : PluginRegistry tracking loaded plugins at runtime
  - validator.py : Validates plugin structure before loading
"""

from .base import OmnixPlugin, PluginMeta
from .loader import PluginLoader
from .registry import PluginRegistry
from .validator import PluginValidator

__all__ = [
    "OmnixPlugin",
    "PluginMeta",
    "PluginLoader",
    "PluginRegistry",
    "PluginValidator",
]
