# OMNIX Plugin Template

This is the official starter template for building OMNIX plugins.

## Quick Start

1. **Copy this template:**
   ```bash
   python omnix_cli.py plugin create my_awesome_plugin
   # or manually:
   cp -r plugins/_template/ plugins/my_awesome_plugin/
   ```

2. **Edit `omnix_plugin.py`:**
   - Update the `PluginMeta` with your plugin's info
   - Rename the plugin class
   - Implement your connector, sensors, or commands in `on_load()`

3. **Validate your plugin:**
   ```bash
   python omnix_cli.py plugin validate my_awesome_plugin
   ```

4. **Start the server** — your plugin loads automatically:
   ```bash
   python server_simple.py
   ```

## File Structure

```
my_plugin/
├── omnix_plugin.py     # Required: plugin entry point
├── README.md           # Recommended: documentation
└── ...                 # Optional: any supporting files
```

## What Can a Plugin Do?

| Registration          | Method                  | Description                          |
|-----------------------|-------------------------|--------------------------------------|
| **Connector**         | `register_connector()`  | Hardware adapter (serial, WiFi, etc) |
| **Sensor**            | `register_sensor()`     | Telemetry channel (temp, GPS, etc)   |
| **Command**           | `register_command()`    | Custom command for the API           |
| **View**              | `register_view()`       | Dashboard widget / page              |

## Example: Minimal Plugin

```python
from omnix.plugins import OmnixPlugin, PluginMeta

class MyPlugin(OmnixPlugin):
    meta = PluginMeta(
        name="my_plugin",
        version="1.0.0",
        author="Your Name",
        description="What it does",
    )

    def on_load(self):
        self.register_connector(MyConnectorClass)

    def on_unload(self):
        pass
```

## API Reference

See `docs/PLUGIN_GUIDE.md` for the full API reference and best practices.
