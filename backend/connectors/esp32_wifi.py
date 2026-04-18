"""
OMNIX ESP32 Wi-Fi Connector — Tier 1 (DIY).

The ESP32 flashes with a small OMNIX sketch (see
`firmware/esp32_omnix.ino`) and connects to this server over HTTP the
same way the Pi agent does:

  ESP32 → POST /api/esp32/register   {name, board_type, caps, mac}
  server → returns {agent_id, device_id}
  ESP32 → GET  /api/esp32/commands/<id>   (poll, ~500ms)
  ESP32 → POST /api/esp32/telemetry/<id>  {tele}
  ESP32 → POST /api/esp32/deregister/<id>

This connector file is the client-side slot: when a user starts it in
OMNIX, it provides a device record whose commands are queued for the
ESP32 agent to pull. If no ESP32 ever registers, it stays in "waiting"
state and, optionally, runs a simulated ESP32 locally so the UI works.
"""

import math
import random
import threading
import time
import uuid

from devices.base import DeviceCapability
from connectors.base import (
    ConnectorBase, ConnectorMeta, ConnectorDevice,
    ConfigField, SimulatedBackendMixin,
)


# Module-level registry shared between connector and the HTTP handlers
# in server_simple.py. The server writes into these dicts when an ESP32
# registers / posts telemetry; the connector reads them.
_ESP32_AGENTS: dict = {}           # agent_id → {name, caps, last_seen, ...}
_ESP32_COMMAND_QUEUES: dict = {}   # agent_id → list[command dict]
_ESP32_TELEMETRY: dict = {}        # agent_id → {tele, ts}


def _server_hooks():
    """Exposes the registries for server_simple.py to read/write."""
    return _ESP32_AGENTS, _ESP32_COMMAND_QUEUES, _ESP32_TELEMETRY


# ───────────────────────────────────────────────────────────
#  Simulated ESP32 (used when mode=simulate or when we want demo data)
# ───────────────────────────────────────────────────────────

class _SimEsp32:
    def __init__(self, board_type: str):
        self.board_type = board_type
        self.boot_ts = time.time()
        self.fw_version = "1.0.0"
        self.fw_version_code = 1
        self.ota_status = "idle"     # idle | checking | downloading | flashing | rebooting | error
        self.ota_progress = 0
        self.state = {
            "rssi_dbm": -52,          # Wi-Fi signal
            "heap_free_kb": 180,
            "temp_c": 34.0,
            "uptime_s": 0,
        }
        if board_type == "lights":
            self.state.update({"on": False, "r": 0, "g": 0, "b": 0, "brightness": 0})
        elif board_type == "rover":
            self.state.update({"motor_l": 0, "motor_r": 0, "sonar_cm": 200})
        elif board_type == "sensor":
            self.state.update({"temp_sensor_c": 22.5, "humidity": 45, "motion": False})

    def handle(self, cmd: str, params: dict) -> dict:
        if cmd == "set_color" and self.board_type == "lights":
            c = params.get("color", "FFFFFF").lstrip("#")
            self.state["r"] = int(c[0:2], 16) if len(c) >= 6 else 0
            self.state["g"] = int(c[2:4], 16) if len(c) >= 6 else 0
            self.state["b"] = int(c[4:6], 16) if len(c) >= 6 else 0
            return {"success": True, "message": f"color #{c}"}
        if cmd == "toggle" and self.board_type == "lights":
            self.state["on"] = params.get("state", "on") == "on"
            self.state["brightness"] = 100 if self.state["on"] else 0
            return {"success": True, "message": "on" if self.state["on"] else "off"}
        if cmd == "set_brightness" and self.board_type == "lights":
            self.state["brightness"] = int(params.get("brightness", 50))
            return {"success": True, "message": f"brightness {self.state['brightness']}"}
        if cmd == "drive" and self.board_type == "rover":
            speed = int(params.get("speed", 128))
            d = params.get("dir", "stop")
            if d == "forward": self.state["motor_l"] = self.state["motor_r"] = speed
            elif d == "backward": self.state["motor_l"] = self.state["motor_r"] = -speed
            elif d == "left": self.state["motor_l"], self.state["motor_r"] = -speed, speed
            elif d == "right": self.state["motor_l"], self.state["motor_r"] = speed, -speed
            else: self.state["motor_l"] = self.state["motor_r"] = 0
            return {"success": True, "message": f"drive {d} @ {speed}"}
        if cmd == "sample" and self.board_type == "sensor":
            self.state["temp_sensor_c"] = round(20 + random.random() * 10, 1)
            self.state["humidity"] = random.randint(30, 70)
            self.state["motion"] = random.random() < 0.15
            return {"success": True, "message": "sample",
                    "data": {"temp": self.state["temp_sensor_c"],
                             "humidity": self.state["humidity"]}}
        if cmd == "ota_update":
            # Simulate OTA update process
            self.ota_status = "downloading"
            self.ota_progress = 0
            self._ota_start_ts = time.time()
            return {"success": True, "message": "OTA update started"}
        if cmd == "get_firmware_version":
            return {"success": True, "message": self.fw_version,
                    "data": {"fw_version": self.fw_version, "fw_version_code": self.fw_version_code}}
        return {"success": False, "message": f"unknown command {cmd}"}

    def tick(self):
        self.state["uptime_s"] = int(time.time() - self.boot_ts)
        # Simulate OTA progress
        if self.ota_status == "downloading":
            elapsed = time.time() - getattr(self, "_ota_start_ts", time.time())
            self.ota_progress = min(60, int(elapsed * 20))
            if self.ota_progress >= 60:
                self.ota_status = "flashing"
        elif self.ota_status == "flashing":
            self.ota_progress = min(90, self.ota_progress + 5)
            if self.ota_progress >= 90:
                self.ota_status = "rebooting"
        elif self.ota_status == "rebooting":
            self.ota_progress = 100
            self.fw_version = "1.1.0"
            self.fw_version_code = 2
            self.ota_status = "idle"
            self.ota_progress = 0
        self.state["temp_c"] = 34 + math.sin(time.time() / 6) * 1.5
        # Wi-Fi RSSI drifts
        self.state["rssi_dbm"] = max(-85, min(-35, self.state["rssi_dbm"] + random.randint(-2, 2)))
        self.state["heap_free_kb"] = max(80, self.state["heap_free_kb"] + random.randint(-3, 3))
        if self.board_type == "rover":
            self.state["sonar_cm"] = max(10, min(400, self.state["sonar_cm"] + random.randint(-6, 6)))
        if self.board_type == "sensor":
            # Occasional motion trigger
            if random.random() < 0.02:
                self.state["motion"] = True

    def telemetry(self) -> dict:
        out = dict(self.state)
        out["_ts"] = time.time()
        out["simulated"] = True
        out["fw_version"] = self.fw_version
        out["fw_version_code"] = self.fw_version_code
        out["ota_status"] = self.ota_status
        out["ota_progress"] = self.ota_progress
        out["platform"] = "esp32"
        return out


# ───────────────────────────────────────────────────────────
#  Connector
# ───────────────────────────────────────────────────────────

class Esp32WifiConnector(SimulatedBackendMixin, ConnectorBase):
    """Tier 1 — ESP32 agent over Wi-Fi / HTTP."""

    meta = ConnectorMeta(
        connector_id="esp32_wifi",
        display_name="ESP32 (Wi-Fi Agent)",
        tier=1,
        description="ESP32/ESP8266/ESP32-S3 with the OMNIX sketch. Connects to OMNIX over Wi-Fi and registers itself.",
        vpe_categories=["smart_light", "smart_device", "ground_robot", "robot_arm",
                        "home_robot", "sensor", "legged", "drone"],
        required_packages=[],
        supports_simulation=True,
        icon="📡",
        vendor="Espressif",
        config_schema=[
            ConfigField(
                key="board_type", label="Sketch variant", type="select",
                default="lights", options=["lights", "rover", "sensor"], required=True,
                help="Which OMNIX sketch did you flash to the ESP32?",
            ),
            ConfigField(
                key="name", label="Display name", type="text",
                default="My ESP32", placeholder="Porch Light",
            ),
            ConfigField(
                key="mode", label="Mode", type="select",
                default="simulate", options=["simulate", "expect_agent"],
                help="'simulate' runs an in-process fake ESP32 (no hardware). 'expect_agent' waits for a real ESP32 to register.",
            ),
            ConfigField(
                key="expected_mac", label="ESP32 MAC (optional)", type="text",
                default="", placeholder="AA:BB:CC:DD:EE:FF",
                help="If set, this connector binds to the first ESP32 agent with this MAC.",
            ),
        ],
        setup_steps=[
            "Open `backend/connectors/firmware/esp32_omnix.ino` in Arduino IDE or PlatformIO.",
            "Install the ESP32 board package and the ArduinoJson library.",
            "At the top of the sketch, set WIFI_SSID, WIFI_PASS, OMNIX_URL, BOARD_TYPE.",
            "Flash to your ESP32 at 115200 baud.",
            "Power it up — the ESP32 joins Wi-Fi and registers itself.",
            "In OMNIX, pick 'expect_agent' mode and click Connect; the ESP32 appears in the main device list.",
        ],
    )

    def connect(self) -> bool:
        board = self.config.get("board_type", "lights")
        name = self.config.get("name", f"ESP32 {board}")
        mode = self.config.get("mode", "simulate")
        expected_mac = self.config.get("expected_mac", "").strip().upper()

        device_type = {
            "lights": "smart_light", "rover": "ground_robot", "sensor": "smart_device",
        }.get(board, "smart_device")

        caps = self._capabilities_for(board)
        self._latest_tele = {"status": "waiting"}
        self._tele_lock = threading.Lock()
        self._expected_mac = expected_mac
        self._bound_agent_id = None

        if mode == "simulate":
            self._use_simulation = True
            self._sim = _SimEsp32(board)
            # Also seed a fake entry in the shared registry so the agent
            # HTTP endpoints would see it if queried (harmless).
            fake_id = f"sim-{uuid.uuid4().hex[:6]}"
            self._bound_agent_id = fake_id
            _ESP32_AGENTS[fake_id] = {
                "name": name, "board_type": board, "mac": "SIM",
                "capabilities": [c.name for c in caps],
                "registered_at": time.time(), "simulated": True,
            }
            _ESP32_COMMAND_QUEUES[fake_id] = []
            _ESP32_TELEMETRY[fake_id] = {"telemetry": self._sim.telemetry(), "ts": time.time()}
        else:
            self._use_simulation = False
            # Real: try to bind immediately if a matching ESP32 already registered.
            self._try_bind()

        def handler(cmd, params):
            return self._send_command(cmd, params)

        def tele():
            with self._tele_lock:
                return dict(self._latest_tele)

        dev = ConnectorDevice(
            name=name, device_type=device_type, capabilities=caps,
            command_handler=handler, telemetry_provider=tele,
            source_connector=self,
        )
        self._devices.append(dev)
        self._mark_connected(True)
        return True

    def disconnect(self):
        if self._use_simulation and self._bound_agent_id:
            _ESP32_AGENTS.pop(self._bound_agent_id, None)
            _ESP32_COMMAND_QUEUES.pop(self._bound_agent_id, None)
            _ESP32_TELEMETRY.pop(self._bound_agent_id, None)
        self._devices.clear()
        self._mark_connected(False)

    def tick(self):
        if self._use_simulation and hasattr(self, "_sim"):
            self._sim.tick()
            with self._tele_lock:
                self._latest_tele = self._sim.telemetry()
            if self._bound_agent_id:
                _ESP32_TELEMETRY[self._bound_agent_id] = {
                    "telemetry": self._latest_tele, "ts": time.time()
                }
        else:
            # Real mode: keep trying to bind and pull latest telemetry
            if not self._bound_agent_id:
                self._try_bind()
            elif self._bound_agent_id in _ESP32_TELEMETRY:
                with self._tele_lock:
                    self._latest_tele = _ESP32_TELEMETRY[self._bound_agent_id].get("telemetry", {})

    def _try_bind(self):
        """Look for a registered ESP32 matching our filter (MAC or first free)."""
        for aid, info in _ESP32_AGENTS.items():
            if info.get("simulated"):
                continue
            if self._expected_mac and info.get("mac", "").upper() != self._expected_mac:
                continue
            # Claim it
            self._bound_agent_id = aid
            return

    def _send_command(self, cmd: str, params: dict) -> dict:
        if self._use_simulation:
            result = self._sim.handle(cmd, params)
            return result
        if not self._bound_agent_id:
            return {"success": False, "message": "No ESP32 agent registered yet."}
        _ESP32_COMMAND_QUEUES.setdefault(self._bound_agent_id, []).append({
            "id": uuid.uuid4().hex[:8],
            "command": cmd, "params": params, "ts": time.time(),
        })
        return {"success": True, "message": f"Queued '{cmd}' for ESP32"}

    def _capabilities_for(self, board: str):
        # OTA capability is shared across all board types
        ota_cap = DeviceCapability(
            name="ota_update", description="OTA firmware update",
            parameters={
                "firmware_id": {"type": "text", "help": "Firmware ID to deploy"},
            },
            category="firmware",
        )
        fw_version_cap = DeviceCapability(
            name="get_firmware_version", description="Get current firmware version",
            parameters={}, category="firmware",
        )

        if board == "lights":
            return [
                DeviceCapability(name="toggle", description="Power on/off",
                    parameters={"state": {"type": "select", "options": ["on", "off"]}},
                    category="power"),
                DeviceCapability(name="set_color", description="RGB color",
                    parameters={"color": {"type": "text", "default": "FFFFFF"}},
                    category="color"),
                DeviceCapability(name="set_brightness", description="Brightness 0-100",
                    parameters={"brightness": {"type": "number", "min": 0, "max": 100, "default": 70}},
                    category="brightness"),
                ota_cap, fw_version_cap,
            ]
        if board == "rover":
            return [
                DeviceCapability(name="drive", description="Drive",
                    parameters={
                        "dir": {"type": "select", "options": ["forward", "backward", "left", "right", "stop"]},
                        "speed": {"type": "number", "min": 0, "max": 255, "default": 150},
                    }, category="movement"),
                DeviceCapability(name="emergency_stop", description="Stop motors", parameters={}, category="safety"),
                ota_cap, fw_version_cap,
            ]
        if board == "sensor":
            return [
                DeviceCapability(name="sample", description="Capture a reading",
                    parameters={}, category="sensors"),
                ota_cap, fw_version_cap,
            ]
        return [ota_cap, fw_version_cap]
