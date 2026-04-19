"""
OMNIX Arduino Serial Connector — Tier 1 (DIY).

Opens a USB serial port to an Arduino (or any microcontroller that speaks
a simple line-based protocol) and translates OMNIX commands into
newline-terminated text frames.

OMNIX ↔ Arduino wire protocol (v1, line-based JSON):
    OMNIX  →  MCU:  {"c":"drive","p":{"speed":60,"dir":"forward"}}\n
    MCU    →  OMNIX:  {"t":{"speed":60,"dist":12.3,"batt":87}}\n
    MCU    →  OMNIX:  {"ok":true,"m":"moving"}\n
    MCU    →  OMNIX:  {"err":"motor stalled"}\n

Small footprint on the MCU side (see `firmware/arduino_omnix.ino`):
  - ArduinoJson for parsing (or manual if memory-tight)
  - 115200 baud default
  - Telemetry pushed every 200ms

If pyserial isn't installed or no port is configured, falls back to a
simulated Arduino that behaves identically over an in-process queue.
"""

import json
import math
import queue
import random
import threading
import time

from devices.base import DeviceCapability
from connectors.base import (
    ConnectorBase, ConnectorMeta, ConnectorDevice,
    ConfigField, SimulatedBackendMixin,
)

try:
    import serial  # type: ignore
    _HAS_PYSERIAL = True
except ImportError:
    _HAS_PYSERIAL = False


# ───────────────────────────────────────────────────────────
#  Simulated Arduino (in-process queues)
# ───────────────────────────────────────────────────────────

class _SimArduino:
    """Mirrors the firmware's behavior over a fake "wire"."""

    def __init__(self, board_type: str):
        self.board_type = board_type   # rover | arm | lights
        self.boot_ts = time.time()
        self.tele = {
            "batt": 95.0,
            "temp_c": 28.0,
        }
        if board_type == "rover":
            self.tele.update({"speed": 0, "dist_cm": 0, "heading": 0, "bumper": False})
            self._pos = [0.0, 0.0]
            self._heading = 0.0
        elif board_type == "arm":
            self.tele.update({"j0": 0, "j1": 45, "j2": -30, "j3": 0, "gripper": 50})
        elif board_type == "lights":
            self.tele.update({"on": False, "brightness": 0, "color": "000000", "effect": "none"})

    def write_line(self, line: str) -> list:
        """Process a command frame; returns a list of response frames."""
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return [json.dumps({"err": "bad json"})]

        cmd = msg.get("c")
        p = msg.get("p", {})
        resp = []

        if cmd == "drive" and self.board_type == "rover":
            speed = float(p.get("speed", 50))
            d = p.get("dir", "stop")
            if d == "forward":
                self._pos[0] += speed * 0.01 * math.cos(math.radians(self._heading))
                self._pos[1] += speed * 0.01 * math.sin(math.radians(self._heading))
                self.tele["speed"] = speed
            elif d == "backward":
                self._pos[0] -= speed * 0.01 * math.cos(math.radians(self._heading))
                self._pos[1] -= speed * 0.01 * math.sin(math.radians(self._heading))
                self.tele["speed"] = -speed
            elif d == "left":
                self._heading = (self._heading + 15) % 360
            elif d == "right":
                self._heading = (self._heading - 15) % 360
            else:
                self.tele["speed"] = 0
            self.tele["heading"] = round(self._heading, 1)
            self.tele["dist_cm"] = round(math.hypot(*self._pos) * 100, 1)
            resp.append(json.dumps({"ok": True, "m": f"drive {d} {speed}"}))

        elif cmd == "move_joint" and self.board_type == "arm":
            j = p.get("joint", "j0")
            a = float(p.get("angle", 0))
            if j in ("j0", "j1", "j2", "j3", "gripper"):
                self.tele[j] = max(-180, min(180, a))
                resp.append(json.dumps({"ok": True, "m": f"{j} -> {a}"}))
            else:
                resp.append(json.dumps({"err": f"bad joint {j}"}))

        elif cmd == "toggle" and self.board_type == "lights":
            self.tele["on"] = p.get("state", "on") == "on"
            self.tele["brightness"] = 100 if self.tele["on"] else 0
            resp.append(json.dumps({"ok": True, "m": "on" if self.tele["on"] else "off"}))

        elif cmd == "set_color" and self.board_type == "lights":
            self.tele["color"] = p.get("color", "FFFFFF")
            resp.append(json.dumps({"ok": True, "m": f"color #{self.tele['color']}"}))

        elif cmd == "set_brightness" and self.board_type == "lights":
            self.tele["brightness"] = int(p.get("brightness", 50))
            resp.append(json.dumps({"ok": True, "m": f"brightness {self.tele['brightness']}"}))

        elif cmd == "emergency_stop":
            if self.board_type == "rover":
                self.tele["speed"] = 0
            resp.append(json.dumps({"ok": True, "m": "stopped"}))

        elif cmd == "ping":
            resp.append(json.dumps({"ok": True, "m": "pong",
                                    "uptime": round(time.time() - self.boot_ts, 1)}))

        else:
            resp.append(json.dumps({"err": f"unknown command {cmd}"}))

        return resp

    def push_telemetry(self) -> str:
        # Simulate passive changes
        self.tele["batt"] = max(0.0, self.tele["batt"] - 0.02)
        self.tele["temp_c"] = 28 + math.sin(time.time() / 5) + random.uniform(-0.3, 0.3)
        if self.board_type == "rover":
            # Bumper occasionally trips
            self.tele["bumper"] = random.random() < 0.03
        return json.dumps({"t": {k: round(v, 2) if isinstance(v, float) else v
                                 for k, v in self.tele.items()}})


# ───────────────────────────────────────────────────────────
#  The connector
# ───────────────────────────────────────────────────────────

class ArduinoSerialConnector(SimulatedBackendMixin, ConnectorBase):
    """Tier 1 — Arduino / Teensy / any MCU speaking the OMNIX serial protocol."""

    meta = ConnectorMeta(
        connector_id="arduino_serial",
        display_name="Arduino (USB Serial)",
        tier=1,
        description="Arduino / Teensy / RP2040 over USB serial. Flash the OMNIX firmware sketch, plug in, pick the port, done.",
        vpe_categories=["robot_arm", "ground_robot", "smart_light", "smart_device",
                        "home_robot", "legged"],
        required_packages=["pyserial"],
        supports_simulation=True,
        icon="🤖",
        vendor="Arduino",
        docs_url="",
        config_schema=[
            ConfigField(
                key="board_type", label="Firmware variant", type="select",
                default="rover", options=["rover", "arm", "lights"], required=True,
                help="Which OMNIX sketch did you flash? See firmware/arduino_omnix.ino.",
            ),
            ConfigField(
                key="name", label="Display name", type="text",
                default="Arduino Robot", placeholder="Workbench Arm",
            ),
            ConfigField(
                key="port", label="Serial port", type="text",
                default="", placeholder="/dev/ttyACM0 or COM3",
                help="Leave blank to force simulation mode. On Linux usually /dev/ttyACM0 or /dev/ttyUSB0; on macOS /dev/cu.usbmodem*; on Windows COM3/COM4.",
            ),
            ConfigField(
                key="baud", label="Baud rate", type="number",
                default=115200,
            ),
        ],
        setup_steps=[
            "Open Arduino IDE, load `backend/connectors/firmware/arduino_omnix.ino`.",
            "At the top of the sketch, set BOARD_TYPE to 'rover', 'arm', or 'lights'.",
            "Flash to your Arduino at 115200 baud.",
            "Plug the USB cable into the machine running OMNIX.",
            "Find the port: Linux `ls /dev/ttyACM*`, macOS `ls /dev/cu.usbmodem*`, Windows Device Manager.",
            "Fill in the port field above and click Connect.",
            "If you just want to try it without hardware, leave port blank — OMNIX will run a simulated Arduino.",
        ],
    )

    def connect(self) -> bool:
        board = self.config.get("board_type", "rover")
        name = self.config.get("name", f"Arduino {board}")
        port = self.config.get("port", "").strip()
        baud = int(self.config.get("baud", 115200))

        device_type = {
            "rover": "ground_robot", "arm": "robot_arm", "lights": "smart_light",
        }.get(board, "ground_robot")

        caps = self._capabilities_for(board)
        self._latest_tele: dict = {"status": "connecting"}
        self._tele_lock = threading.Lock()
        self._resp_queue: "queue.Queue[dict]" = queue.Queue()
        self._stop_reader = threading.Event()

        if port and _HAS_PYSERIAL:
            try:
                self._serial = serial.Serial(port, baud, timeout=0.1)
                time.sleep(0.3)   # Arduino reset on serial open
                self._use_simulation = False
                self._reader_thread = threading.Thread(
                    target=self._serial_read_loop, daemon=True,
                    name=f"ardser-read-{self.instance_id}",
                )
                self._reader_thread.start()
            except Exception as e:
                self._mark_connected(False, f"Failed to open {port}: {e}")
                return False
        else:
            if port and not _HAS_PYSERIAL:
                # User asked for real port but pyserial is missing
                self._mark_connected(False,
                    "pyserial not installed. Run `pip install pyserial` and restart, "
                    "or leave the port blank to use simulation.")
                return False
            # Simulated backend
            self._use_simulation = True
            self._sim = _SimArduino(board)
            # Seed initial telemetry
            self._ingest_frame(self._sim.push_telemetry())

        def handler(c, p):
            return self._send_command(c, p)

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
        self._stop_reader.set()
        if not self._use_simulation:
            try:
                self._serial.close()
            except Exception as e:
                # Serial may already be closed; silently ignore
                pass
        self._devices.clear()
        self._mark_connected(False)

    def tick(self):
        if self._use_simulation:
            # Stream fake telemetry at 4 Hz
            self._ingest_frame(self._sim.push_telemetry())

    # ── Protocol helpers ───────────────────────────────────

    def _send_command(self, command: str, params: dict) -> dict:
        frame = json.dumps({"c": command, "p": params or {}}) + "\n"
        if self._use_simulation:
            responses = self._sim.write_line(frame.strip())
            for r in responses:
                self._ingest_frame(r)
            # Return the most recent ok/err response
            for r in reversed(responses):
                d = json.loads(r)
                if "ok" in d or "err" in d:
                    if d.get("err"):
                        return {"success": False, "message": d["err"]}
                    return {"success": True, "message": d.get("m", "ok")}
            return {"success": True, "message": "sent"}
        # Real serial
        try:
            self._serial.write(frame.encode("utf-8"))
        except Exception as e:
            return {"success": False, "message": f"write failed: {e}"}
        # Wait briefly for a response
        try:
            resp = self._resp_queue.get(timeout=0.3)
            if resp.get("err"):
                return {"success": False, "message": resp["err"]}
            return {"success": True, "message": resp.get("m", "ok"),
                    "data": {k: v for k, v in resp.items() if k not in ("ok", "m", "err")}}
        except queue.Empty:
            return {"success": True, "message": "sent (no immediate ack)"}

    def _serial_read_loop(self):
        buf = b""
        while not self._stop_reader.is_set():
            try:
                chunk = self._serial.read(256)
            except Exception:
                time.sleep(0.1)
                continue
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    self._ingest_frame(line.decode("utf-8", errors="replace").strip())
                except Exception:
                    pass

    def _ingest_frame(self, line: str):
        if not line:
            return
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return
        if "t" in msg and isinstance(msg["t"], dict):
            with self._tele_lock:
                self._latest_tele = {**msg["t"], "_ts": time.time()}
        elif "ok" in msg or "err" in msg:
            try:
                self._resp_queue.put_nowait(msg)
            except queue.Full:
                pass

    # ── Per-board capability sets ──────────────────────────

    def _capabilities_for(self, board: str):
        if board == "rover":
            return [
                DeviceCapability(
                    name="drive", description="Drive the rover",
                    parameters={
                        "dir": {"type": "select", "options": ["forward", "backward", "left", "right", "stop"]},
                        "speed": {"type": "number", "min": 0, "max": 255, "default": 120},
                    }, category="movement"),
                DeviceCapability(name="emergency_stop", description="Stop motors", parameters={}, category="safety"),
                DeviceCapability(name="ping", description="Heartbeat check", parameters={}, category="diag"),
            ]
        if board == "arm":
            return [
                DeviceCapability(
                    name="move_joint", description="Move one joint",
                    parameters={
                        "joint": {"type": "select", "options": ["j0", "j1", "j2", "j3", "gripper"]},
                        "angle": {"type": "number", "min": -180, "max": 180, "default": 0},
                    }, category="movement"),
                DeviceCapability(name="emergency_stop", description="Kill all servos", parameters={}, category="safety"),
                DeviceCapability(name="ping", description="Heartbeat check", parameters={}, category="diag"),
            ]
        if board == "lights":
            return [
                DeviceCapability(
                    name="toggle", description="On/off",
                    parameters={"state": {"type": "select", "options": ["on", "off"]}},
                    category="power"),
                DeviceCapability(
                    name="set_color", description="Set RGB color",
                    parameters={"color": {"type": "text", "default": "FFFFFF"}},
                    category="color"),
                DeviceCapability(
                    name="set_brightness", description="Brightness 0-100",
                    parameters={"brightness": {"type": "number", "min": 0, "max": 100, "default": 60}},
                    category="brightness"),
            ]
        return []
