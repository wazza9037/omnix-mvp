"""
OMNIX Pi Agent — Runs on Raspberry Pi, connects to remote OMNIX server.

This script runs on the Pi hardware and:
  1. Configures local GPIO, sensors, camera based on a device profile
  2. Registers with the OMNIX server over HTTP
  3. Sends telemetry at regular intervals
  4. Receives and executes commands from the server
  5. Supports VPE camera capture for device scanning

Usage:
    python pi_agent.py                          # Default rover, localhost:8765
    python pi_agent.py --server 192.168.1.100   # Remote server
    python pi_agent.py --profile rover           # Specific profile
    python pi_agent.py --profile custom --config my_robot.json

Profiles:
    rover     — 2-motor differential drive + ultrasonic + camera
    arm       — 3-servo robotic arm + gripper servo
    sentinel  — Pan/tilt camera mount + PIR sensor + LED
    custom    — Load from JSON config file
"""

import argparse
import json
import time
import threading
import sys
import os

# Add parent dir so we can import from devices package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from devices.pi_bridge import PiDevice, PiCameraFeed

# HTTP client using only stdlib
from urllib.request import urlopen, Request
from urllib.error import URLError


# ═══════════════════════════════════════════
#  DEVICE PROFILES — pre-built configurations
# ═══════════════════════════════════════════

PROFILES = {
    "rover": {
        "name": "OMNIX Rover",
        "device_type": "ground_robot",
        "motors": {
            "left":  {"forward_pin": 17, "backward_pin": 27, "pwm_pin": 22},
            "right": {"forward_pin": 23, "backward_pin": 24, "pwm_pin": 25},
        },
        "sensors": {
            "front_distance": {"type": "ultrasonic", "trigger_pin": 5, "echo_pin": 6},
            "environment":    {"type": "dht", "pin": 4, "sensor_type": "DHT22"},
            "imu":            {"type": "imu", "address": 104},  # 0x68
        },
        "leds": {
            "headlight": {"pin": 12, "pwm": True},
            "status":    {"pin": 16, "pwm": False},
        },
        "camera": {"enabled": True, "resolution": [640, 480]},
        "description": "Two-wheel differential drive rover with distance sensor, camera, and IMU",
    },

    "arm": {
        "name": "OMNIX Arm",
        "device_type": "robot_arm",
        "servos": {
            "base":     {"pin": 18, "min_angle": 0, "max_angle": 180},
            "shoulder": {"pin": 19, "min_angle": 15, "max_angle": 165},
            "elbow":    {"pin": 20, "min_angle": 0, "max_angle": 135},
            "gripper":  {"pin": 21, "min_angle": 30, "max_angle": 120},
        },
        "sensors": {
            "load": {"type": "ultrasonic", "trigger_pin": 5, "echo_pin": 6},
        },
        "camera": {"enabled": True, "resolution": [640, 480]},
        "description": "3-DOF robotic arm with gripper, load sensor, and camera",
    },

    "sentinel": {
        "name": "OMNIX Sentinel",
        "device_type": "smart_device",
        "servos": {
            "pan":  {"pin": 18, "min_angle": 0, "max_angle": 180},
            "tilt": {"pin": 19, "min_angle": 30, "max_angle": 150},
        },
        "sensors": {
            "distance": {"type": "ultrasonic", "trigger_pin": 5, "echo_pin": 6},
            "environment": {"type": "dht", "pin": 4, "sensor_type": "DHT22"},
        },
        "leds": {
            "ir_flood":  {"pin": 12, "pwm": True},
            "indicator": {"pin": 16, "pwm": False},
        },
        "relays": {
            "alarm": {"pin": 26, "active_low": False},
        },
        "camera": {"enabled": True, "resolution": [1280, 720]},
        "description": "Pan/tilt security camera with environmental monitoring",
    },
}


# ═══════════════════════════════════════════
#  PI AGENT — Connects Pi hardware to OMNIX
# ═══════════════════════════════════════════

class PiAgent:
    """
    Agent that runs on the Pi, connects to OMNIX server.

    Flow:
      1. Build PiDevice from profile config
      2. POST /api/pi/register — send device info to server
      3. Loop: POST /api/pi/telemetry — send sensor data
      4. Loop: GET  /api/pi/commands/{id} — check for pending commands
      5. Execute commands locally on GPIO hardware
    """

    def __init__(self, server_url: str, profile: dict):
        self.server_url = server_url.rstrip("/")
        self.profile = profile
        self.device = None
        self.agent_id = None
        self.running = False
        self.telemetry_interval = 1.0  # seconds
        self.command_poll_interval = 0.5

        self._build_device()

    def _build_device(self):
        """Configure PiDevice from profile dict."""
        p = self.profile
        self.device = PiDevice(p["name"], p.get("device_type", "ground_robot"))

        # Motors
        for name, cfg in p.get("motors", {}).items():
            self.device.gpio.setup_motor(
                name,
                forward_pin=cfg["forward_pin"],
                backward_pin=cfg["backward_pin"],
                pwm_pin=cfg.get("pwm_pin"),
                pwm_freq=cfg.get("pwm_freq", 1000),
            )

        # Servos
        for name, cfg in p.get("servos", {}).items():
            self.device.gpio.setup_servo(
                name,
                pin=cfg["pin"],
                min_angle=cfg.get("min_angle", 0),
                max_angle=cfg.get("max_angle", 180),
            )

        # LEDs
        for name, cfg in p.get("leds", {}).items():
            self.device.gpio.setup_led(name, cfg["pin"], pwm=cfg.get("pwm", False))

        # Relays
        for name, cfg in p.get("relays", {}).items():
            self.device.gpio.setup_relay(name, cfg["pin"], active_low=cfg.get("active_low", False))

        # Sensors
        for name, cfg in p.get("sensors", {}).items():
            if cfg["type"] == "ultrasonic":
                self.device.sensors.setup_ultrasonic(name, cfg["trigger_pin"], cfg["echo_pin"])
            elif cfg["type"] == "dht":
                self.device.sensors.setup_dht(name, cfg.get("pin", 4), cfg.get("sensor_type", "DHT22"))
            elif cfg["type"] == "imu":
                self.device.sensors.setup_imu(name, cfg.get("address", 0x68))

        # Camera
        cam_cfg = p.get("camera", {})
        if cam_cfg.get("enabled", False):
            res = tuple(cam_cfg.get("resolution", [640, 480]))
            self.device.camera = PiCameraFeed(resolution=res)

        print(f"  Device built: {self.device.name} ({self.device.device_type})")
        print(f"    Motors:  {list(self.device.gpio.motors.keys())}")
        print(f"    Servos:  {list(self.device.gpio.servos.keys())}")
        print(f"    LEDs:    {list(self.device.gpio.leds.keys())}")
        print(f"    Relays:  {list(self.device.gpio.relays.keys())}")
        print(f"    Sensors: {list(self.device.sensors._sensors.keys())}")
        print(f"    Camera:  {self.device.camera.source if self.device.camera else 'none'}")

    # ── HTTP Helpers ──

    def _post(self, path: str, data: dict) -> dict:
        """POST JSON to server, return parsed response."""
        url = f"{self.server_url}{path}"
        body = json.dumps(data).encode("utf-8")
        req = Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode())
        except URLError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": str(e)}

    def _get(self, path: str) -> dict:
        """GET from server, return parsed response."""
        url = f"{self.server_url}{path}"
        try:
            with urlopen(url, timeout=5) as resp:
                return json.loads(resp.read().decode())
        except URLError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": str(e)}

    # ── Registration ──

    def register(self) -> bool:
        """Register this device with the OMNIX server."""
        print(f"\n  Registering with {self.server_url}...")

        payload = {
            "name": self.device.name,
            "device_type": self.device.device_type,
            "capabilities": self.device.get_capabilities(),
            "hardware": {
                "gpio_mode": "real" if self.device.gpio.is_real else "simulated",
                "motors": list(self.device.gpio.motors.keys()),
                "servos": list(self.device.gpio.servos.keys()),
                "leds": list(self.device.gpio.leds.keys()),
                "relays": list(self.device.gpio.relays.keys()),
                "sensors": list(self.device.sensors._sensors.keys()),
                "camera": self.device.camera.source if self.device.camera else "none",
            },
            "description": self.profile.get("description", ""),
        }

        result = self._post("/api/pi/register", payload)

        if "error" in result:
            print(f"  Registration FAILED: {result['error']}")
            return False

        self.agent_id = result.get("agent_id")
        self.device.id = result.get("device_id", self.device.id)
        print(f"  Registered! Agent ID: {self.agent_id}, Device ID: {self.device.id}")
        return True

    # ── Telemetry Loop ──

    def _telemetry_loop(self):
        """Send telemetry to server at regular intervals."""
        while self.running:
            try:
                telemetry = self.device.get_telemetry()
                self._post(f"/api/pi/telemetry/{self.agent_id}", {
                    "device_id": self.device.id,
                    "telemetry": telemetry,
                    "timestamp": time.time(),
                })
            except Exception as e:
                print(f"  Telemetry error: {e}")
            time.sleep(self.telemetry_interval)

    # ── Command Poll Loop ──

    def _command_loop(self):
        """Poll server for pending commands and execute them."""
        while self.running:
            try:
                result = self._get(f"/api/pi/commands/{self.agent_id}")

                if "error" not in result and result.get("commands"):
                    for cmd in result["commands"]:
                        self._execute_remote_command(cmd)

            except Exception as e:
                print(f"  Command poll error: {e}")
            time.sleep(self.command_poll_interval)

    def _execute_remote_command(self, cmd: dict):
        """Execute a command received from the server."""
        command = cmd.get("command", "")
        params = cmd.get("params", {})
        cmd_id = cmd.get("id", "")

        print(f"  Executing: {command} {params}")
        result = self.device.execute_command(command, params)

        # Report result back to server
        self._post(f"/api/pi/command-result/{self.agent_id}", {
            "command_id": cmd_id,
            "result": result,
        })

    # ── High-Level Controls ──

    def drive(self, left_speed: float, right_speed: float,
              left_dir: str = "forward", right_dir: str = "forward"):
        """Convenience: drive a 2-motor rover."""
        self.device.execute_command("set_motor", {
            "name": "left", "speed": left_speed, "direction": left_dir,
        })
        self.device.execute_command("set_motor", {
            "name": "right", "speed": right_speed, "direction": right_dir,
        })

    def stop(self):
        """Emergency stop all motors."""
        self.device.execute_command("stop_all")

    def scan_with_vpe(self) -> dict:
        """Capture photo and send to OMNIX VPE for analysis."""
        if not self.device.camera:
            return {"error": "No camera configured"}

        image_b64 = self.device.camera.capture_for_vpe()
        result = self._post("/api/vpe/analyze", {"image": image_b64})
        return result

    # ── Main Run Loop ──

    def run(self):
        """Start the agent: register, then run telemetry + command loops."""
        # Try to register, retry on failure
        retries = 0
        while retries < 10:
            if self.register():
                break
            retries += 1
            wait = min(2 ** retries, 30)
            print(f"  Retrying in {wait}s... ({retries}/10)")
            time.sleep(wait)
        else:
            print("  Failed to register after 10 attempts. Exiting.")
            return

        self.running = True

        # Start background loops
        telemetry_thread = threading.Thread(target=self._telemetry_loop, daemon=True)
        command_thread = threading.Thread(target=self._command_loop, daemon=True)
        telemetry_thread.start()
        command_thread.start()

        print(f"\n  Agent running! Sending telemetry every {self.telemetry_interval}s")
        print(f"  Polling commands every {self.command_poll_interval}s")
        print("  Press Ctrl+C to stop.\n")

        try:
            while self.running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n  Shutting down...")
            self.running = False
            self.device.cleanup()
            # Deregister
            self._post(f"/api/pi/deregister/{self.agent_id}", {})
            print("  Agent stopped.")


# ═══════════════════════════════════════════
#  CLI ENTRY POINT
# ═══════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="OMNIX Pi Agent")
    parser.add_argument("--server", default="http://localhost:8765",
                        help="OMNIX server URL (default: http://localhost:8765)")
    parser.add_argument("--profile", default="rover",
                        choices=list(PROFILES.keys()) + ["custom"],
                        help="Device profile to use (default: rover)")
    parser.add_argument("--config", default=None,
                        help="Custom JSON config file (with --profile custom)")
    parser.add_argument("--telemetry-interval", type=float, default=1.0,
                        help="Telemetry send interval in seconds (default: 1.0)")
    parser.add_argument("--name", default=None,
                        help="Override device name")

    args = parser.parse_args()

    print()
    print("=" * 55)
    print("    OMNIX Pi Agent")
    print("=" * 55)
    print()

    # Load profile
    if args.profile == "custom":
        if not args.config:
            print("  ERROR: --config required with --profile custom")
            sys.exit(1)
        with open(args.config) as f:
            profile = json.load(f)
        print(f"  Profile: custom ({args.config})")
    else:
        profile = PROFILES[args.profile].copy()
        print(f"  Profile: {args.profile}")

    if args.name:
        profile["name"] = args.name

    print(f"  Server:  {args.server}")
    print()

    # Build and run agent
    agent = PiAgent(args.server, profile)
    agent.telemetry_interval = args.telemetry_interval
    agent.run()


if __name__ == "__main__":
    main()
