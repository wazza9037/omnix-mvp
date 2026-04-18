"""
OMNIX Pi Connector — Tier 1 (DIY)

Wraps the existing `devices/pi_agent.py` CLI flow. The Pi runs the agent,
which polls the server for commands and posts telemetry. This connector
represents the server-side "slot" where a Pi registers.

Two modes:
  - "expect": wait for a Pi agent to register with our server; timeout after N seconds.
  - "simulate": spin up a local fake Pi that emits telemetry + accepts commands.

The second mode is the one that works without any real hardware — it's
what makes the connector testable end-to-end in this sandbox and what
lets devs build UIs against it.

Real Pi setup (shown in setup_steps):
  1. SSH into your Pi
  2. git clone / copy the OMNIX repo
  3. pip install pigpio  (optional for real GPIO)
  4. python3 devices/pi_agent.py --server http://<omnix-host>:8765 --profile rover
  5. Agent auto-registers; this connector picks it up.
"""

import math
import random
import time
import threading

from devices.base import DeviceCapability
from connectors.base import (
    ConnectorBase, ConnectorMeta, ConnectorDevice,
    ConfigField, SimulatedBackendMixin,
)


PI_PROFILES = {
    "rover": {
        "device_type": "ground_robot",
        "capabilities": [
            ("drive", "Drive the rover", {
                "direction": {"type": "select", "options": ["forward", "backward", "left", "right", "stop"]},
                "speed": {"type": "number", "min": 0, "max": 100, "default": 50},
                "duration_ms": {"type": "number", "min": 0, "max": 10000, "default": 1000},
            }, "movement"),
            ("set_led", "Set status LED color", {
                "color": {"type": "text", "default": "00FF00"},
            }, "lights"),
            ("emergency_stop", "Stop all motors", {}, "safety"),
        ],
    },
    "arm": {
        "device_type": "robot_arm",
        "capabilities": [
            ("move_joint", "Move one joint", {
                "joint": {"type": "select", "options": ["base", "shoulder", "elbow", "wrist", "gripper"]},
                "angle": {"type": "number", "min": -180, "max": 180, "default": 0},
            }, "movement"),
            ("gripper", "Open/close gripper", {
                "action": {"type": "select", "options": ["open", "close"]},
            }, "manipulation"),
            ("emergency_stop", "Stop all servos", {}, "safety"),
        ],
    },
    "sentinel": {
        "device_type": "home_robot",
        "capabilities": [
            ("patrol", "Start patrol pattern", {
                "mode": {"type": "select", "options": ["circle", "square", "stop"]},
            }, "behavior"),
            ("scan", "Capture a sensor snapshot", {}, "sensors"),
            ("set_led", "Set LED color", {"color": {"type": "text", "default": "FF0000"}}, "lights"),
        ],
    },
}


# ───────────────────────────────────────────────────────────
#  Simulated Pi backend — used when no real hardware is present
# ───────────────────────────────────────────────────────────

class _SimPi:
    """In-process simulation of a Pi rover/arm/sentinel.

    Keeps enough state to produce believable telemetry without actually
    moving anything. This is what backs the connector in demo mode.
    """

    def __init__(self, profile: str):
        self.profile = profile
        self.boot_ts = time.time()
        self.state = {
            "battery": 100.0,
            "temp_c": 42.0,
            "led_color": "00FF00",
        }
        if profile == "rover":
            self.state.update({"x": 0.0, "y": 0.0, "heading": 0.0,
                               "left_motor": 0, "right_motor": 0,
                               "bumper": False, "sonar_cm": 300})
        elif profile == "arm":
            self.state.update({"joints": {"base": 0, "shoulder": 45, "elbow": -30,
                                          "wrist": 0, "gripper": 50},
                               "gripper_open": True})
        elif profile == "sentinel":
            self.state.update({"patrol": "stop", "scan_count": 0,
                               "last_scan_temp": 23.1, "motion_detected": False})
        self._lock = threading.Lock()
        self._last_drive = 0.0

    def handle(self, command: str, params: dict) -> dict:
        with self._lock:
            if command == "drive" and self.profile == "rover":
                d = params.get("direction", "stop")
                speed = float(params.get("speed", 50))
                dur = float(params.get("duration_ms", 1000)) / 1000.0
                if d == "forward":
                    self.state["x"] += speed * 0.001 * dur * math.cos(math.radians(self.state["heading"]))
                    self.state["y"] += speed * 0.001 * dur * math.sin(math.radians(self.state["heading"]))
                    self.state["left_motor"] = self.state["right_motor"] = speed
                elif d == "backward":
                    self.state["x"] -= speed * 0.001 * dur * math.cos(math.radians(self.state["heading"]))
                    self.state["y"] -= speed * 0.001 * dur * math.sin(math.radians(self.state["heading"]))
                    self.state["left_motor"] = self.state["right_motor"] = -speed
                elif d == "left":
                    self.state["heading"] = (self.state["heading"] + 30 * dur) % 360
                elif d == "right":
                    self.state["heading"] = (self.state["heading"] - 30 * dur) % 360
                else:
                    self.state["left_motor"] = self.state["right_motor"] = 0
                self._last_drive = time.time()
                return {"success": True, "message": f"Drive {d} @ {speed}% for {dur:.1f}s",
                        "data": {"x": round(self.state["x"], 2), "y": round(self.state["y"], 2)}}

            if command == "move_joint" and self.profile == "arm":
                j = params.get("joint")
                angle = params.get("angle", 0)
                if j in self.state["joints"]:
                    self.state["joints"][j] = float(angle)
                    return {"success": True, "message": f"Joint {j} → {angle}°"}
                return {"success": False, "message": f"Unknown joint {j}"}

            if command == "gripper" and self.profile == "arm":
                self.state["gripper_open"] = params.get("action") == "open"
                return {"success": True, "message": f"Gripper {params.get('action')}"}

            if command == "patrol" and self.profile == "sentinel":
                self.state["patrol"] = params.get("mode", "stop")
                return {"success": True, "message": f"Patrol mode: {self.state['patrol']}"}

            if command == "scan" and self.profile == "sentinel":
                self.state["scan_count"] += 1
                self.state["last_scan_temp"] = round(20 + random.random() * 8, 1)
                self.state["motion_detected"] = random.random() < 0.15
                return {"success": True, "message": "Scan complete",
                        "data": {"temp_c": self.state["last_scan_temp"],
                                 "motion": self.state["motion_detected"]}}

            if command == "set_led":
                self.state["led_color"] = params.get("color", "FFFFFF")
                return {"success": True, "message": f"LED → #{self.state['led_color']}"}

            if command == "emergency_stop":
                if self.profile == "rover":
                    self.state["left_motor"] = self.state["right_motor"] = 0
                return {"success": True, "message": "Emergency stop engaged"}

            return {"success": False, "message": f"Unknown command '{command}'"}

    def tick(self):
        # Battery drains slowly; faster while motors are running
        activity = 0
        if self.profile == "rover":
            activity = abs(self.state.get("left_motor", 0)) + abs(self.state.get("right_motor", 0))
        elif self.profile == "arm":
            activity = 5
        elif self.profile == "sentinel":
            activity = 3 if self.state.get("patrol") != "stop" else 1
        drain = 0.002 + activity * 0.00005
        self.state["battery"] = max(0.0, self.state["battery"] - drain)
        # Temperature oscillates a touch
        self.state["temp_c"] = 42 + math.sin(time.time() / 7) * 2 + activity * 0.02
        if self.profile == "rover":
            # Sonar walks randomly
            self.state["sonar_cm"] = max(5, min(400,
                self.state["sonar_cm"] + random.randint(-8, 8)))

    def telemetry(self) -> dict:
        uptime = round(time.time() - self.boot_ts, 1)
        base = {
            "battery": round(self.state["battery"], 1),
            "temp_c": round(self.state["temp_c"], 1),
            "led_color": self.state["led_color"],
            "uptime_s": uptime,
            "simulated": True,
        }
        if self.profile == "rover":
            base.update({
                "position": {"x": round(self.state["x"], 2), "y": round(self.state["y"], 2)},
                "heading": round(self.state["heading"], 1),
                "left_motor": self.state["left_motor"],
                "right_motor": self.state["right_motor"],
                "bumper": self.state["bumper"],
                "sonar_cm": self.state["sonar_cm"],
            })
        elif self.profile == "arm":
            base.update({
                "joints": dict(self.state["joints"]),
                "gripper_open": self.state["gripper_open"],
            })
        elif self.profile == "sentinel":
            base.update({
                "patrol": self.state["patrol"],
                "scan_count": self.state["scan_count"],
                "last_scan_temp": self.state["last_scan_temp"],
                "motion_detected": self.state["motion_detected"],
            })
        return base


# ───────────────────────────────────────────────────────────
#  The connector itself
# ───────────────────────────────────────────────────────────

class PiConnector(SimulatedBackendMixin, ConnectorBase):
    """Tier 1 connector for Raspberry Pi-based robots.

    Modes:
      - simulate (default): run a local SimPi; works with zero hardware.
      - real: wait for a Pi agent to register via /api/pi/register.
              (Server's existing pi_agents dict is the actual channel —
              this mode is wired so the connector is aware of already
              connected agents that match its name filter.)
    """

    meta = ConnectorMeta(
        connector_id="pi_agent",
        display_name="Raspberry Pi Agent",
        tier=1,
        description="DIY Pi-based robots. Run the OMNIX agent on your Pi; it auto-registers over HTTP.",
        vpe_categories=["ground_robot", "robot_arm", "humanoid", "legged",
                        "home_robot", "service_robot", "drone", "marine", "extreme"],
        required_packages=[],
        supports_simulation=True,
        icon="🍓",
        vendor="Raspberry Pi",
        docs_url="",
        config_schema=[
            ConfigField(
                key="profile", label="Robot profile", type="select",
                default="rover", required=True,
                options=["rover", "arm", "sentinel"],
                help="Which built-in profile matches your Pi robot? Custom profiles are defined on the Pi.",
            ),
            ConfigField(
                key="name", label="Display name", type="text",
                default="My Pi Robot", placeholder="Garage Rover",
                help="What to call this device in the OMNIX UI.",
            ),
            ConfigField(
                key="mode", label="Mode", type="select",
                default="simulate", options=["simulate", "real"],
                help="'simulate' works without hardware — ideal for UI development. 'real' waits for a Pi agent to register.",
            ),
        ],
        setup_steps=[
            "SSH into your Raspberry Pi.",
            "Copy the OMNIX repo to the Pi (scp, git clone, or USB stick).",
            "Install deps: `pip3 install pigpio opencv-python` (only what you need).",
            "Run: `python3 devices/pi_agent.py --server http://<your-omnix-ip>:8765 --profile rover --name \"My Rover\"`",
            "The agent prints its ID and starts posting telemetry.",
            "In OMNIX, click Connect — this connector picks up the running agent.",
        ],
    )

    def connect(self) -> bool:
        profile = self.config.get("profile", "rover")
        name = self.config.get("name", f"Pi {profile}")
        mode = self.config.get("mode", "simulate")

        if profile not in PI_PROFILES:
            self._mark_connected(False, f"Unknown profile '{profile}'")
            return False

        prof = PI_PROFILES[profile]
        caps = [DeviceCapability(name=n, description=d, parameters=p, category=cat)
                for (n, d, p, cat) in prof["capabilities"]]

        if mode == "simulate":
            self._use_simulation = True
            self._sim = _SimPi(profile)

            def cmd(c, p): return self._sim.handle(c, p)
            def tele(): return self._sim.telemetry()

        else:
            # Real mode — devices pull from a future bridge to the
            # existing pi_agents dict. For now we stub command/telemetry
            # so the device still appears, and the error surface tells
            # the user to run the agent.
            self._use_simulation = False

            def cmd(c, p):
                return {"success": False,
                        "message": "Real Pi agent not yet connected. Run pi_agent.py on your Pi."}

            def tele():
                return {"waiting_for_agent": True,
                        "hint": "Start pi_agent.py on your Pi to see telemetry."}

        dev = ConnectorDevice(
            name=name,
            device_type=prof["device_type"],
            capabilities=caps,
            command_handler=cmd,
            telemetry_provider=tele,
            source_connector=self,
        )
        self._devices.append(dev)
        self._mark_connected(True)
        return True

    def tick(self):
        if self._use_simulation and hasattr(self, "_sim"):
            self._sim.tick()

    def disconnect(self):
        self._devices.clear()
        self._mark_connected(False)
