# OMNIX Plugin SDK Guide

Build connectors, sensors, commands, and dashboard views for the OMNIX platform — without touching core code.

## Overview

The OMNIX Plugin SDK lets you extend the platform with custom hardware integrations, sensor channels, commands, and UI views. Plugins are self-contained directories that the platform discovers and loads automatically.

### What can a plugin do?

| Registration | Method | Description |
|---|---|---|
| **Connector** | `register_connector()` | Hardware adapter (serial, WiFi, I2C, etc.) |
| **Sensor** | `register_sensor()` | Telemetry channel (temperature, GPS, etc.) |
| **Command** | `register_command()` | Custom API command |
| **View** | `register_view()` | Dashboard widget or page |

## Architecture

```
plugins/
├── _template/              ← starter template (skip on scan)
│   ├── omnix_plugin.py
│   └── README.md
├── servo_controller/       ← your plugin
│   ├── omnix_plugin.py     ← entry point (required)
│   ├── README.md           ← documentation (recommended)
│   └── ...                 ← supporting files
└── weather_station/
    └── omnix_plugin.py

backend/omnix/plugins/
├── __init__.py             ← public API
├── base.py                 ← OmnixPlugin base class + PluginMeta
├── loader.py               ← discovers plugins on disk
├── registry.py             ← tracks loaded plugins at runtime
└── validator.py            ← validates structure before loading
```

### Lifecycle

1. **Discovery** — `PluginLoader` scans `plugins/` for subdirectories with `omnix_plugin.py`
2. **Validation** — `PluginValidator` checks structure, metadata, and dangerous patterns
3. **Import** — Module is loaded via `importlib`; the `OmnixPlugin` subclass is found
4. **Instantiation** — Plugin class is created; `PluginMeta` is validated
5. **Loading** — `on_load()` is called; connectors/sensors/commands are registered
6. **Running** — Plugin's connectors appear in the UI; sensors push data; commands are callable
7. **Unloading** — `on_unload()` is called on shutdown or hot-reload; registrations removed

### Hot Reload

Plugins can be reloaded without restarting the server:

- **API**: `POST /api/plugins/reload`
- **UI**: Click the reload button in the Plugins sidebar section
- **Process**: unload all → re-discover → re-validate → re-import → re-load

## Tutorial: Creating Your First Plugin

### Step 1: Scaffold

```bash
python omnix_cli.py plugin create my_sensor
```

This copies the `_template/` directory to `plugins/my_sensor/`.

### Step 2: Define metadata

Edit `plugins/my_sensor/omnix_plugin.py`:

```python
from omnix.plugins import OmnixPlugin, PluginMeta

class MySensorPlugin(OmnixPlugin):
    meta = PluginMeta(
        name="my_sensor",
        version="1.0.0",
        author="Your Name",
        description="Reads data from my custom sensor",
        device_types=["custom"],
        capabilities=["temperature"],
        icon="🌡️",
        tags=["sensor", "i2c"],
    )
```

### Step 3: Create a connector

```python
from connectors.base import (
    ConnectorBase, ConnectorMeta, ConnectorDevice,
    ConfigField, SimulatedBackendMixin,
)
from devices.base import DeviceCapability

class MySensorConnector(SimulatedBackendMixin, ConnectorBase):
    meta = ConnectorMeta(
        connector_id="my_sensor",
        display_name="My Custom Sensor",
        tier=1,
        description="Reads temperature from a custom I2C sensor",
        vpe_categories=["custom"],
        config_schema=[
            ConfigField("mode", "Mode", type="select",
                        options=["simulate", "i2c"], default="simulate"),
            ConfigField("address", "I2C Address", type="text", default="0x48"),
        ],
        supports_simulation=True,
        icon="🌡️",
    )

    def connect(self) -> bool:
        self._use_simulation = (self.config.get("mode") == "simulate")
        self._temperature = 22.0

        capabilities = [
            DeviceCapability(
                name="read_temp",
                description="Read current temperature",
                parameters=[],
                category="telemetry",
            ),
        ]

        dev = ConnectorDevice(
            name="My Sensor",
            device_type="custom",
            capabilities=capabilities,
            command_handler=self._handle_command,
            telemetry_provider=lambda: {"temperature": self._temperature},
            source_connector=self,
        )
        self._devices.append(dev)
        self._mark_connected(True)
        return True

    def _handle_command(self, command, params):
        if command == "read_temp":
            return {"success": True, "temperature": self._temperature}
        return {"success": False, "message": f"Unknown: {command}"}

    def tick(self):
        if self._use_simulation:
            import random
            self._temperature += random.gauss(0, 0.1)
        self.mark_heartbeat()
```

### Step 4: Register in on_load()

```python
class MySensorPlugin(OmnixPlugin):
    # ... meta ...

    def on_load(self):
        self.register_connector(MySensorConnector)

    def on_unload(self):
        pass
```

### Step 5: Validate and run

```bash
# Validate the plugin structure
python omnix_cli.py plugin validate my_sensor

# Start the server — plugin loads automatically
cd backend && python server_simple.py
```

## API Reference

### PluginMeta

```python
@dataclass
class PluginMeta:
    name: str                    # unique identifier (required)
    version: str                 # semver string (required)
    author: str                  # plugin author
    description: str             # short description
    device_types: List[str]      # device types this plugin adds
    capabilities: List[str]      # what it can do
    omnix_version: str           # minimum OMNIX version
    license: str                 # license (default: "MIT")
    homepage: str                # project URL
    icon: str                    # emoji icon
    tags: List[str]              # searchable tags
```

### OmnixPlugin

```python
class OmnixPlugin:
    meta: PluginMeta = None      # set as class attribute

    def on_load(self) -> None:
        """Called when plugin is loaded. Register things here."""

    def on_unload(self) -> None:
        """Called on shutdown or hot-reload. Clean up here."""

    def register_connector(self, connector_class: Type[ConnectorBase]) -> None:
        """Register a hardware connector class."""

    def register_sensor(self, device_id, sensor_id, name,
                        sensor_type="custom", range_min=0.0,
                        range_max=100.0, unit="") -> None:
        """Register a sensor channel on a device."""

    def register_command(self, name, handler, description="",
                         device_types=None) -> None:
        """Register a custom command callable via the API.
        handler signature: fn(device_id: str, params: dict) -> dict"""

    def register_view(self, name, html_file="", route="",
                      description="", icon="📊") -> None:
        """Register a dashboard view served from the plugin directory."""
```

### ConnectorBase (recap)

Plugins register `ConnectorBase` subclasses. The key contract:

```python
class MyConnector(ConnectorBase):
    meta = ConnectorMeta(...)    # static metadata

    def connect(self) -> bool:   # open transport, create devices
    def disconnect(self):        # close transport
    def tick(self):              # periodic work (~500ms)
```

See `connectors/base.py` for the full interface, including `ConfigField`, `ConnectorDevice`, state machine helpers, and the `SimulatedBackendMixin`.

## REST API

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/plugins` | List all loaded plugins with metadata |
| POST | `/api/plugins/reload` | Hot-reload all plugins |
| POST | `/api/plugins/enable/<name>` | Enable a disabled plugin |
| POST | `/api/plugins/disable/<name>` | Disable a plugin (keeps loaded) |

## CLI Tool

```bash
python omnix_cli.py plugin list              # show installed plugins
python omnix_cli.py plugin create <name>     # scaffold from template
python omnix_cli.py plugin install <path>    # install from directory or zip
python omnix_cli.py plugin remove <name>     # uninstall
python omnix_cli.py plugin validate <name>   # check for errors
```

## Best Practices

### Do

- **Always set `supports_simulation=True`** and implement a simulated backend. This lets users try your plugin without hardware.
- **Use `ConfigField`** for all configuration. This auto-generates setup forms in the UI.
- **Call `self.mark_heartbeat()`** in your connector's `tick()` method. This keeps the health monitor happy.
- **Handle errors gracefully** in `connect()` — set `self._error` and return `False` instead of raising.
- **Include a README.md** with configuration docs and command reference.
- **Use semver** for your version string.

### Don't

- **Don't import `subprocess`, `os.system`, or `eval`** — the validator will reject your plugin.
- **Don't hold locks during I/O** — the tick loop runs on a shared thread.
- **Don't hardcode device IDs** — let OMNIX generate them via `ConnectorDevice`.
- **Don't modify global state** outside of the registration APIs.

### Common Patterns

**Simulation fallback:**
```python
class MyConnector(SimulatedBackendMixin, ConnectorBase):
    def connect(self):
        if self.config.get("mode") == "simulate":
            self._use_simulation = True
        else:
            # Try to open real hardware
            try:
                self._serial = serial.Serial(...)
            except:
                self._use_simulation = True  # graceful fallback
```

**Periodic sensor reads:**
```python
def tick(self):
    self._tick_counter += 1
    if self._tick_counter % 4 == 0:  # every ~2 seconds
        reading = self._read_sensor()
        self._latest_temp = reading
    self.mark_heartbeat()
```

**Custom command with validation:**
```python
def register_my_commands(self):
    self.register_command(
        name="calibrate",
        handler=self._calibrate,
        description="Run sensor calibration sequence",
        device_types=["custom"],
    )

def _calibrate(self, device_id, params):
    duration = params.get("duration", 10)
    if duration < 1 or duration > 60:
        return {"success": False, "message": "Duration must be 1-60 seconds"}
    # ... run calibration ...
    return {"success": True, "message": f"Calibrated in {duration}s"}
```

## Publishing to the Marketplace

Once your plugin is tested and documented:

1. Create a zip of your plugin directory
2. Include a README.md with setup instructions
3. Submit via the OMNIX Marketplace (coming soon)

For now, share plugins by distributing the directory or zip file:

```bash
# Package
cd plugins && zip -r my_plugin.zip my_plugin/

# Install on another machine
python omnix_cli.py plugin install my_plugin.zip
```
