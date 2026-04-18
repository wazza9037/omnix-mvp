"""
OMNIX DJI Tello Connector — Tier 2 (open protocol, real hardware).

The Tello (both original and EDU) speaks a plain-text UDP protocol. No
authentication, no SDK install, no mobile app in the loop. It's the
best first "real hardware" connector you can build because a $99 drone
just works.

Protocol summary (DJI Tello SDK 2.0):
  - Commands: UDP to 192.168.10.1:8889  (ASCII, 'takeoff', 'up 40', 'cw 90' …)
  - Replies:  UDP back to our port 8889 ('ok' / 'error')
  - State:    Tello pushes telemetry on UDP :8890 every 100ms when
              connected (JSON-like key=value; e.g. "mid:-1;bat:78;…")
  - Video:    UDP :11111 (H.264) — not handled here

Typical pairing:
  1. Power on the Tello
  2. Join the Tello_XXXXXX Wi-Fi from the computer running OMNIX
  3. Click Connect — the connector sends 'command' to enter SDK mode
  4. The drone is registered; /api/devices picks it up

If 'simulate' is selected, a local in-process Tello emulator is used
so the connector, dashboard, and 3D viewer can all be exercised without
owning a drone.
"""

import math
import random
import socket
import threading
import time

from devices.base import DeviceCapability
from connectors.base import (
    ConnectorBase, ConnectorMeta, ConnectorDevice,
    ConfigField, SimulatedBackendMixin,
)


TELLO_IP_DEFAULT = "192.168.10.1"
TELLO_CMD_PORT_DEFAULT = 8889
TELLO_STATE_PORT_DEFAULT = 8890


# ───────────────────────────────────────────────────────────
#  Simulated Tello
# ───────────────────────────────────────────────────────────

class _SimTello:
    def __init__(self):
        self.boot = time.time()
        self.flying = False
        self.battery = 87
        self.height_cm = 0
        self.pos = [0.0, 0.0, 0.0]   # x, y, z in cm
        self.yaw = 0.0
        self.pitch = 0.0
        self.roll = 0.0
        self.vel = [0.0, 0.0, 0.0]
        self.baro = 101.3
        self.tof_cm = 10
        self.photos = 0

    def _drain(self, amount=0.01):
        self.battery = max(0, self.battery - amount)

    def handle(self, cmd: str) -> str:
        parts = cmd.strip().split()
        if not parts:
            return "error"
        op = parts[0].lower()

        if op == "command":
            return "ok"

        if op == "takeoff":
            if self.battery < 5:
                return "error Low battery"
            self.flying = True
            self.height_cm = 80
            self.pos[2] = 80
            self._drain(0.5)
            return "ok"
        if op == "land":
            self.flying = False
            self.height_cm = 0
            self.pos[2] = 0
            self._drain(0.3)
            return "ok"
        if op == "emergency":
            self.flying = False
            self.height_cm = 0
            self.pos[2] = 0
            return "ok"

        if op == "streamon" or op == "streamoff":
            return "ok"

        # Movement: up/down/left/right/forward/back <cm>
        if op in ("up", "down", "left", "right", "forward", "back"):
            if not self.flying:
                return "error Not flying"
            try:
                d = int(parts[1])
            except (IndexError, ValueError):
                return "error Bad distance"
            fwd = math.radians(self.yaw)
            if op == "up":       self.pos[2] += d; self.height_cm += d
            elif op == "down":   self.pos[2] -= d; self.height_cm = max(0, self.height_cm - d)
            elif op == "forward": self.pos[0] += d * math.cos(fwd); self.pos[1] += d * math.sin(fwd)
            elif op == "back":    self.pos[0] -= d * math.cos(fwd); self.pos[1] -= d * math.sin(fwd)
            elif op == "left":    self.pos[0] += d * math.cos(fwd + math.pi/2); self.pos[1] += d * math.sin(fwd + math.pi/2)
            elif op == "right":   self.pos[0] += d * math.cos(fwd - math.pi/2); self.pos[1] += d * math.sin(fwd - math.pi/2)
            self._drain(0.2)
            return "ok"

        # Rotation: cw/ccw <deg>
        if op == "cw":
            try: self.yaw = (self.yaw + int(parts[1])) % 360
            except: return "error Bad angle"
            self._drain(0.1); return "ok"
        if op == "ccw":
            try: self.yaw = (self.yaw - int(parts[1])) % 360
            except: return "error Bad angle"
            self._drain(0.1); return "ok"

        # Flips
        if op == "flip":
            try: d = parts[1][0].lower()
            except: return "error Bad direction"
            if d in ("f", "b", "l", "r"):
                self._drain(1.0); return "ok"
            return "error Bad flip direction"

        # Speed setting
        if op == "speed":
            return "ok"

        # Queries
        if op == "battery?": return str(int(self.battery))
        if op == "speed?":   return "30"
        if op == "time?":    return str(int(time.time() - self.boot))
        if op == "height?":  return f"{self.height_cm}dm"
        if op == "tof?":     return f"{self.tof_cm}cm"

        return f"error Unknown command: {cmd}"

    def state_frame(self) -> str:
        # Build a Tello-style state string: key:value;key:value;...
        self.tof_cm = max(5, min(600, self.tof_cm + random.randint(-3, 3)))
        keys = {
            "pitch": int(self.pitch), "roll": int(self.roll), "yaw": int(self.yaw),
            "vgx": int(self.vel[0]), "vgy": int(self.vel[1]), "vgz": int(self.vel[2]),
            "templ": 60, "temph": 62, "tof": self.tof_cm,
            "h": self.height_cm, "bat": int(self.battery),
            "baro": round(self.baro, 2),
            "time": int(time.time() - self.boot),
            "agx": 0, "agy": 0, "agz": -1000,
            "x": int(self.pos[0]), "y": int(self.pos[1]), "z": int(self.pos[2]),
            "flying": 1 if self.flying else 0,
        }
        return ";".join(f"{k}:{v}" for k, v in keys.items()) + ";\r\n"


# ───────────────────────────────────────────────────────────
#  Connector
# ───────────────────────────────────────────────────────────

class TelloConnector(SimulatedBackendMixin, ConnectorBase):
    """Tier 2 — DJI Tello via the open Tello SDK over UDP."""

    meta = ConnectorMeta(
        connector_id="tello",
        display_name="DJI Tello",
        tier=2,
        description="DJI Tello / Tello EDU over UDP. No SDK install, no auth. Pair by joining the drone's Wi-Fi.",
        vpe_categories=["drone"],
        required_packages=[],
        supports_simulation=True,
        icon="🚁",
        vendor="DJI (Ryze Tech)",
        docs_url="https://dl-cdn.ryzerobotics.com/downloads/Tello/Tello%20SDK%202.0%20User%20Guide.pdf",
        config_schema=[
            ConfigField(
                key="name", label="Display name", type="text",
                default="Tello Drone", placeholder="Living Room Tello",
            ),
            ConfigField(
                key="mode", label="Mode", type="select",
                default="simulate", options=["simulate", "real"],
                help="'simulate' runs a local emulator. 'real' opens UDP to the Tello.",
            ),
            ConfigField(
                key="ip", label="Tello IP", type="text",
                default=TELLO_IP_DEFAULT,
                help="Only change if you have a custom network setup.",
            ),
            ConfigField(
                key="cmd_port", label="Command port", type="number",
                default=TELLO_CMD_PORT_DEFAULT,
            ),
            ConfigField(
                key="state_port", label="State port", type="number",
                default=TELLO_STATE_PORT_DEFAULT,
            ),
        ],
        setup_steps=[
            "Fully charge the Tello and power it on.",
            "On the computer running OMNIX, join the Wi-Fi named 'TELLO-XXXXXX' (no password).",
            "Pick 'real' mode above, leave IP/ports at defaults, click Connect.",
            "OMNIX sends 'command' to enter SDK mode; the drone is now controllable.",
            "First time? Try 'takeoff' via the Movement presets, then 'land'. Keep an eye on battery.",
            "For hands-off experimentation, leave mode on 'simulate' — a local Tello emulator will run.",
        ],
    )

    # ── Lifecycle ──────────────────────────────────────────

    def connect(self) -> bool:
        name = self.config.get("name", "Tello")
        mode = self.config.get("mode", "simulate")
        ip = self.config.get("ip", TELLO_IP_DEFAULT)
        cmd_port = int(self.config.get("cmd_port", TELLO_CMD_PORT_DEFAULT))
        state_port = int(self.config.get("state_port", TELLO_STATE_PORT_DEFAULT))

        self._tele: dict = {"status": "connecting"}
        self._tele_lock = threading.Lock()
        self._stop = threading.Event()
        self._last_ack = None

        caps = [
            DeviceCapability("takeoff", "Take off", {}, "flight"),
            DeviceCapability("land", "Land", {}, "flight"),
            DeviceCapability("emergency_stop", "Cut motors immediately", {}, "safety"),
            DeviceCapability("hover", "Stop in place", {}, "flight"),
            DeviceCapability("move", "Move in a direction",
                             {"direction": {"type": "select",
                                            "options": ["forward", "backward", "left", "right", "up", "down"]},
                              "distance_cm": {"type": "number", "min": 20, "max": 500, "default": 50}},
                             "movement"),
            DeviceCapability("rotate", "Rotate on yaw",
                             {"degrees": {"type": "number", "min": -360, "max": 360, "default": 90}},
                             "movement"),
            DeviceCapability("flip", "Flip mid-air",
                             {"direction": {"type": "select", "options": ["forward", "back", "left", "right"]}},
                             "tricks"),
            DeviceCapability("take_photo", "Capture a photo", {}, "camera"),
        ]

        if mode == "simulate":
            self._use_simulation = True
            self._sim = _SimTello()
            # Seed initial telemetry
            self._parse_state(self._sim.state_frame())
        else:
            self._use_simulation = False
            try:
                self._cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self._cmd_sock.bind(("", cmd_port))
                self._cmd_sock.settimeout(0.5)
                self._state_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self._state_sock.bind(("", state_port))
                self._state_sock.settimeout(0.5)
                self._tello_addr = (ip, cmd_port)
                # Enter SDK mode
                ack = self._send_raw("command")
                if ack != "ok":
                    self._mark_connected(False, f"Tello didn't enter SDK mode (got {ack!r}). "
                                                 f"Is your computer joined to the Tello's Wi-Fi?")
                    try: self._cmd_sock.close()
                    except: pass
                    try: self._state_sock.close()
                    except: pass
                    return False
                self._state_thread = threading.Thread(
                    target=self._state_loop, daemon=True, name="tello-state")
                self._state_thread.start()
            except Exception as e:
                self._mark_connected(False, f"Tello UDP setup failed: {e}")
                return False

        def handler(c, p): return self._run_command(c, p)
        def tele():
            with self._tele_lock:
                return dict(self._tele)

        dev = ConnectorDevice(
            name=name, device_type="drone", capabilities=caps,
            command_handler=handler, telemetry_provider=tele,
            source_connector=self,
        )
        self._devices.append(dev)
        self._mark_connected(True)
        return True

    def disconnect(self):
        self._stop.set()
        if not self._use_simulation:
            try: self._cmd_sock.close()
            except: pass
            try: self._state_sock.close()
            except: pass
        self._devices.clear()
        self._mark_connected(False)

    def tick(self):
        if self._use_simulation:
            # Emit a simulated state frame each tick
            self._parse_state(self._sim.state_frame())

    # ── Command translation ────────────────────────────────

    def _run_command(self, command: str, params: dict) -> dict:
        cmd = command
        p = params or {}

        if cmd == "takeoff":
            wire = "takeoff"
        elif cmd == "land":
            wire = "land"
        elif cmd == "emergency_stop":
            wire = "emergency"
        elif cmd == "hover":
            # Tello doesn't have an explicit hover command, but 'stop' is close
            wire = "stop"
        elif cmd == "move":
            d = p.get("direction", "forward")
            dist = int(p.get("distance_cm", 50))
            op_map = {
                "forward": "forward", "backward": "back",
                "left": "left", "right": "right",
                "up": "up", "down": "down",
            }
            if d not in op_map:
                return {"success": False, "message": f"Unknown direction {d}"}
            wire = f"{op_map[d]} {max(20, min(500, dist))}"
        elif cmd == "rotate":
            deg = int(p.get("degrees", 90))
            wire = f"cw {abs(deg)}" if deg >= 0 else f"ccw {abs(deg)}"
        elif cmd == "flip":
            d = p.get("direction", "forward")
            fmap = {"forward": "f", "back": "b", "left": "l", "right": "r"}
            if d not in fmap:
                return {"success": False, "message": f"Unknown flip {d}"}
            wire = f"flip {fmap[d]}"
        elif cmd == "take_photo":
            # Tello doesn't expose a photo command over SDK 2.0 text protocol,
            # so this is a pseudo-command: just increment a counter.
            if self._use_simulation: self._sim.photos += 1
            return {"success": True, "message": "Photo captured (pseudo-command)"}
        else:
            return {"success": False, "message": f"Unsupported command '{cmd}'"}

        result = self._send_raw(wire)
        if result == "ok":
            return {"success": True, "message": f"{cmd} → ok"}
        if result and result.startswith("error"):
            return {"success": False, "message": f"Tello: {result}"}
        if result is None:
            return {"success": False, "message": "No response from Tello (timeout)"}
        # Numeric query answers (battery?, tof?, etc.)
        return {"success": True, "message": result}

    def _send_raw(self, wire: str) -> str:
        """Send a raw SDK frame, return the first reply."""
        if self._use_simulation:
            reply = self._sim.handle(wire)
            self._last_ack = reply
            return reply
        try:
            self._cmd_sock.sendto(wire.encode("utf-8"), self._tello_addr)
        except Exception as e:
            return f"error send failed: {e}"
        try:
            data, _ = self._cmd_sock.recvfrom(1024)
            reply = data.decode("utf-8", errors="replace").strip()
            self._last_ack = reply
            return reply
        except socket.timeout:
            return None
        except Exception as e:
            return f"error recv failed: {e}"

    # ── Telemetry decoding ─────────────────────────────────

    def _state_loop(self):
        while not self._stop.is_set():
            try:
                data, _ = self._state_sock.recvfrom(1024)
                self._parse_state(data.decode("utf-8", errors="replace"))
            except socket.timeout:
                continue
            except Exception:
                time.sleep(0.1)

    def _parse_state(self, s: str):
        """Tello pushes 'mid:-1;x:0;y:0;...;' — parse into a dict."""
        frame = {}
        for part in s.strip().split(";"):
            if ":" not in part:
                continue
            k, _, v = part.partition(":")
            k, v = k.strip(), v.strip()
            if not k:
                continue
            # Cast to int/float where possible
            try:
                frame[k] = int(v)
            except ValueError:
                try:
                    frame[k] = float(v)
                except ValueError:
                    frame[k] = v
        if not frame:
            return
        # Map Tello keys → OMNIX-style telemetry
        with self._tele_lock:
            self._tele = {
                "battery": frame.get("bat", 0),
                "height_cm": frame.get("h", 0),
                "altitude_cm": frame.get("tof", 0),
                "pitch": frame.get("pitch", 0),
                "roll": frame.get("roll", 0),
                "yaw": frame.get("yaw", 0),
                "velocity": {
                    "x": frame.get("vgx", 0),
                    "y": frame.get("vgy", 0),
                    "z": frame.get("vgz", 0),
                },
                "position_cm": {
                    "x": frame.get("x", 0),
                    "y": frame.get("y", 0),
                    "z": frame.get("z", 0),
                },
                "temp_low_c": frame.get("templ", 0),
                "temp_high_c": frame.get("temph", 0),
                "baro_hpa": frame.get("baro", 0),
                "flying": bool(frame.get("flying", 0)),
                "uptime_s": frame.get("time", 0),
                "_ts": time.time(),
            }
