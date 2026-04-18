"""
OMNIX SDK — Build OMNIX-compatible devices in minutes.

This SDK lets any device maker (or hobbyist) make their hardware
controllable via the OMNIX platform. Just subclass OmnixDevice,
define your capabilities, and connect to the server.

Example usage:

    from omnix_sdk import OmnixDeviceSDK, DeviceCapability

    class MyRobot(OmnixDeviceSDK):
        def __init__(self):
            super().__init__(
                name="My Cool Robot",
                device_type="custom_robot",
                server_url="ws://localhost:8765/ws"
            )
            self.register_capability(DeviceCapability(
                name="dance",
                description="Make the robot dance",
                parameters={"style": {"type": "select", "options": ["salsa", "robot", "moonwalk"]}},
                category="fun"
            ))

        def get_telemetry(self):
            return {"mood": "happy", "battery": 95}

        def execute_command(self, command, params=None):
            if command == "dance":
                return {"success": True, "message": f"Dancing {params.get('style', 'robot')} style!"}
            return {"success": False, "message": f"Unknown: {command}"}

    # Run it
    robot = MyRobot()
    robot.connect()
"""

import json
import time
import uuid
import asyncio
import threading
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable

try:
    import websockets
except ImportError:
    print("Install websockets: pip install websockets")
    raise


@dataclass
class DeviceCapability:
    """Define what your device can do."""
    name: str
    description: str
    parameters: dict = field(default_factory=dict)
    category: str = "general"


class OmnixDeviceSDK:
    """
    Base class for creating OMNIX-compatible devices.

    Subclass this, define capabilities, implement get_telemetry()
    and execute_command(), then call connect().
    """

    def __init__(self, name: str, device_type: str, server_url: str = "ws://localhost:8765/ws"):
        self.id = str(uuid.uuid4())[:8]
        self.name = name
        self.device_type = device_type
        self.server_url = server_url
        self._capabilities: list[DeviceCapability] = []
        self._ws = None
        self._running = False
        self._telemetry_interval = 1.0  # seconds

    def register_capability(self, cap: DeviceCapability):
        """Register a command your device supports."""
        self._capabilities.append(cap)

    def get_telemetry(self) -> dict:
        """Override this — return your device's current state."""
        return {}

    def execute_command(self, command: str, params: dict = None) -> dict:
        """Override this — handle commands from the OMNIX app."""
        return {"success": False, "message": f"Not implemented: {command}"}

    def get_info(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "device_type": self.device_type,
            "connected": True,
            "capabilities": [asdict(c) for c in self._capabilities],
            "telemetry": self.get_telemetry(),
        }

    async def _run_async(self):
        """Main async loop: connect to OMNIX server and handle messages."""
        print(f"\n[OMNIX SDK] Connecting '{self.name}' to {self.server_url}...")

        async with websockets.connect(self.server_url) as ws:
            self._ws = ws
            self._running = True
            print(f"[OMNIX SDK] Connected! Device ID: {self.id}")

            # Register with server
            await ws.send(json.dumps({
                "type": "register_device",
                "device": self.get_info()
            }))

            # Start telemetry sender
            async def send_telemetry():
                while self._running:
                    try:
                        await ws.send(json.dumps({
                            "type": "device_telemetry",
                            "device_id": self.id,
                            "telemetry": self.get_telemetry()
                        }))
                    except Exception:
                        break
                    await asyncio.sleep(self._telemetry_interval)

            telemetry_task = asyncio.create_task(send_telemetry())

            # Listen for commands
            try:
                async for message in ws:
                    msg = json.loads(message)
                    if msg.get("type") == "command" and msg.get("device_id") == self.id:
                        result = self.execute_command(
                            msg["command"],
                            msg.get("params", {})
                        )
                        await ws.send(json.dumps({
                            "type": "command_result",
                            "device_id": self.id,
                            "command": msg["command"],
                            **result
                        }))
            except websockets.exceptions.ConnectionClosed:
                print(f"[OMNIX SDK] Disconnected from server")
            finally:
                self._running = False
                telemetry_task.cancel()

    def connect(self):
        """Connect to the OMNIX server (blocking)."""
        try:
            asyncio.run(self._run_async())
        except KeyboardInterrupt:
            print(f"\n[OMNIX SDK] '{self.name}' shutting down.")
            self._running = False

    def connect_background(self):
        """Connect in a background thread (non-blocking)."""
        thread = threading.Thread(target=self.connect, daemon=True)
        thread.start()
        return thread


# ---- Example: Custom Device ----

if __name__ == "__main__":
    class MyRobot(OmnixDeviceSDK):
        def __init__(self):
            super().__init__(
                name="My Custom Robot",
                device_type="custom_robot",
                server_url="ws://localhost:8765/ws"
            )
            self.mood = "happy"
            self.battery = 100

            self.register_capability(DeviceCapability(
                name="dance",
                description="Make the robot dance",
                parameters={
                    "style": {"type": "select", "options": ["salsa", "robot", "moonwalk"]}
                },
                category="fun"
            ))
            self.register_capability(DeviceCapability(
                name="speak",
                description="Say something",
                parameters={
                    "message": {"type": "text", "default": "Hello!"}
                },
                category="communication"
            ))

        def get_telemetry(self):
            return {
                "mood": self.mood,
                "battery": self.battery,
                "uptime": time.time()
            }

        def execute_command(self, command, params=None):
            params = params or {}
            if command == "dance":
                style = params.get("style", "robot")
                self.mood = "ecstatic"
                self.battery -= 5
                return {"success": True, "message": f"Dancing {style} style!"}
            elif command == "speak":
                msg = params.get("message", "Hello!")
                return {"success": True, "message": f'Robot says: "{msg}"'}
            return {"success": False, "message": f"Unknown: {command}"}

    print("Starting example robot device...")
    print("Make sure the OMNIX server is running first!")
    robot = MyRobot()
    robot.connect()
