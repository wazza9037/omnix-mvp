"""
OMNIX Server — The brain of the universal control platform.

This WebSocket server:
1. Manages all connected devices (real or simulated)
2. Broadcasts device telemetry to all connected clients
3. Routes commands from the UI to the correct device
4. Also serves the frontend UI as a static HTTP page

Run with: python server.py
Then open: http://localhost:8765
"""

import asyncio
import json
import time
import os
import mimetypes
from http import HTTPStatus

try:
    import websockets
    from websockets.http import Headers
except ImportError:
    print("\n[OMNIX] Missing dependency. Install it with:")
    print("  pip install websockets")
    print()
    raise SystemExit(1)

# Import simulated devices
from devices.drone import SimulatedDrone
from devices.robot_arm import SimulatedRobotArm
from devices.smart_light import SimulatedSmartLight

# Import environment system
from omnix.environments.registry import get_registry as get_env_registry


class OmnixServer:
    def __init__(self, host="0.0.0.0", port=8765):
        self.host = host
        self.port = port
        self.devices = {}          # id -> OmnixDevice
        self.clients = set()       # Connected WebSocket clients
        self.telemetry_interval = 0.5  # seconds between telemetry broadcasts

    def add_device(self, device):
        """Register a device with the server."""
        self.devices[device.id] = device
        print(f"  [+] {device.device_type}: {device.name} (id: {device.id})")

    def remove_device(self, device_id):
        """Remove a device."""
        if device_id in self.devices:
            device = self.devices.pop(device_id)
            print(f"  [-] Removed: {device.name}")

    async def broadcast(self, message: dict):
        """Send a message to all connected UI clients."""
        if self.clients:
            data = json.dumps(message)
            await asyncio.gather(
                *[client.send(data) for client in self.clients],
                return_exceptions=True
            )

    async def handle_message(self, websocket, message: str):
        """Process an incoming message from a UI client."""
        try:
            msg = json.loads(message)
        except json.JSONDecodeError:
            await websocket.send(json.dumps({
                "type": "error", "message": "Invalid JSON"
            }))
            return

        msg_type = msg.get("type")

        if msg_type == "get_devices":
            # Return all device info
            devices_info = {did: d.get_info() for did, d in self.devices.items()}
            await websocket.send(json.dumps({
                "type": "devices_list",
                "devices": devices_info,
                "server_time": time.time()
            }))

        elif msg_type == "command":
            # Execute a command on a device
            device_id = msg.get("device_id")
            command = msg.get("command")
            params = msg.get("params", {})

            if device_id not in self.devices:
                await websocket.send(json.dumps({
                    "type": "command_result",
                    "device_id": device_id,
                    "success": False,
                    "message": f"Device not found: {device_id}"
                }))
                return

            device = self.devices[device_id]
            result = device.execute_command(command, params)

            # Send result back to the requesting client
            await websocket.send(json.dumps({
                "type": "command_result",
                "device_id": device_id,
                "command": command,
                **result
            }))

            # Also broadcast updated telemetry to all clients
            await self.broadcast({
                "type": "telemetry_update",
                "device_id": device_id,
                "telemetry": device.get_telemetry(),
                "timestamp": time.time()
            })

        elif msg_type == "get_event_log":
            device_id = msg.get("device_id")
            if device_id in self.devices:
                await websocket.send(json.dumps({
                    "type": "event_log",
                    "device_id": device_id,
                    "events": self.devices[device_id].get_event_log()
                }))

        elif msg_type == "add_device":
            # Dynamically add a new simulated device
            dtype = msg.get("device_type", "smart_light")
            name = msg.get("name", f"New {dtype}")
            device_map = {
                "drone": SimulatedDrone,
                "robot_arm": SimulatedRobotArm,
                "smart_light": SimulatedSmartLight,
            }
            if dtype in device_map:
                device = device_map[dtype](name=name)
                self.add_device(device)
                await self.broadcast({
                    "type": "device_added",
                    "device": device.get_info()
                })

        elif msg_type == "remove_device":
            device_id = msg.get("device_id")
            if device_id in self.devices:
                self.remove_device(device_id)
                await self.broadcast({
                    "type": "device_removed",
                    "device_id": device_id
                })

        elif msg_type == "ping":
            await websocket.send(json.dumps({"type": "pong", "time": time.time()}))

        # ─── Environment API (via WebSocket) ───

        elif msg_type == "get_environments":
            registry = get_env_registry()
            await websocket.send(json.dumps({
                "type": "environments_list",
                "environments": registry.list_environments(),
            }))

        elif msg_type == "get_environment":
            env_id = msg.get("environment_id")
            registry = get_env_registry()
            env = registry.get_environment(env_id)
            if env:
                await websocket.send(json.dumps({
                    "type": "environment_data",
                    "environment": env,
                }))
            else:
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": f"Environment not found: {env_id}",
                }))

        elif msg_type == "create_custom_environment":
            registry = get_env_registry()
            env = registry.create_custom(msg.get("data", {}))
            await websocket.send(json.dumps({
                "type": "environment_created",
                "environment": env,
            }))

        elif msg_type == "update_custom_environment":
            env_id = msg.get("environment_id")
            registry = get_env_registry()
            env = registry.update_custom(env_id, msg.get("updates", {}))
            if env:
                await websocket.send(json.dumps({
                    "type": "environment_updated",
                    "environment": env,
                }))
            else:
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": f"Custom environment not found: {env_id}",
                }))

        elif msg_type == "delete_custom_environment":
            env_id = msg.get("environment_id")
            registry = get_env_registry()
            ok = registry.delete_custom(env_id)
            await websocket.send(json.dumps({
                "type": "environment_deleted" if ok else "error",
                "environment_id": env_id,
                "message": "" if ok else f"Not found: {env_id}",
            }))

        elif msg_type == "set_workspace_environment":
            # Associate an environment with a workspace (broadcast to all)
            workspace_id = msg.get("workspace_id")
            env_id = msg.get("environment_id")
            registry = get_env_registry()
            env = registry.get_environment(env_id)
            if env:
                await self.broadcast({
                    "type": "workspace_environment_set",
                    "workspace_id": workspace_id,
                    "environment_id": env_id,
                    "environment": env,
                })
            else:
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": f"Environment not found: {env_id}",
                }))

    async def telemetry_loop(self):
        """Periodically broadcast telemetry from all devices."""
        while True:
            if self.clients and self.devices:
                telemetry = {}
                for did, device in self.devices.items():
                    telemetry[did] = device.get_telemetry()

                await self.broadcast({
                    "type": "telemetry_bulk",
                    "telemetry": telemetry,
                    "timestamp": time.time()
                })

            await asyncio.sleep(self.telemetry_interval)

    async def handler(self, websocket):
        """Handle a new WebSocket connection."""
        self.clients.add(websocket)
        client_id = id(websocket)
        print(f"  [>] Client connected (total: {len(self.clients)})")

        try:
            # Send initial device list
            devices_info = {did: d.get_info() for did, d in self.devices.items()}
            await websocket.send(json.dumps({
                "type": "devices_list",
                "devices": devices_info,
                "server_time": time.time()
            }))

            # Handle messages
            async for message in websocket:
                await self.handle_message(websocket, message)

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            print(f"  [<] Client disconnected (total: {len(self.clients)})")

    async def run(self):
        """Start the OMNIX server."""
        print()
        print("=" * 55)
        print("    OMNIX Universal Robotics Control Server")
        print("=" * 55)
        print()
        print(f"  WebSocket: ws://localhost:{self.port}/ws")
        print(f"  Dashboard: http://localhost:{self.port}")
        print()
        print("  Registered devices:")
        for did, d in self.devices.items():
            print(f"    [{d.device_type}] {d.name} (id: {did})")
        print()
        print("  Waiting for connections...")
        print()

        # HTTP handler to serve the frontend
        frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")

        async def process_request(path, request_headers):
            """Serve static files and REST API for non-WebSocket requests."""
            if path == "/ws":
                return None  # Let WebSocket handler take over

            # ─── REST API routes for environments ───
            if path == "/api/environments":
                registry = get_env_registry()
                body = json.dumps({"environments": registry.list_environments()}).encode()
                return (HTTPStatus.OK, [("Content-Type", "application/json"),
                                         ("Access-Control-Allow-Origin", "*")], body)

            if path.startswith("/api/environments/") and not path.endswith("/custom"):
                env_id = path.split("/api/environments/")[1].strip("/")
                registry = get_env_registry()
                env = registry.get_environment(env_id)
                if env:
                    body = json.dumps({"environment": env}).encode()
                    return (HTTPStatus.OK, [("Content-Type", "application/json"),
                                             ("Access-Control-Allow-Origin", "*")], body)
                return (HTTPStatus.NOT_FOUND, [("Content-Type", "application/json")],
                        json.dumps({"error": f"Environment not found: {env_id}"}).encode())

            # Map paths to files
            if path == "/" or path == "":
                filepath = os.path.join(frontend_dir, "index.html")
            else:
                filepath = os.path.join(frontend_dir, path.lstrip("/"))

            # Security: prevent path traversal
            filepath = os.path.realpath(filepath)
            if not filepath.startswith(os.path.realpath(frontend_dir)):
                return (HTTPStatus.FORBIDDEN, [], b"Forbidden")

            if os.path.isfile(filepath):
                content_type = mimetypes.guess_type(filepath)[0] or "application/octet-stream"
                with open(filepath, "rb") as f:
                    body = f.read()
                return (HTTPStatus.OK, [("Content-Type", content_type)], body)

            # Default: serve index.html (SPA fallback)
            index_path = os.path.join(frontend_dir, "index.html")
            if os.path.isfile(index_path):
                with open(index_path, "rb") as f:
                    body = f.read()
                return (HTTPStatus.OK, [("Content-Type", "text/html")], body)

            return (HTTPStatus.NOT_FOUND, [], b"Not Found")

        # Start WebSocket server with HTTP handler
        server = await websockets.serve(
            self.handler,
            self.host,
            self.port,
            process_request=process_request,
        )

        # Start telemetry broadcast loop
        telemetry_task = asyncio.create_task(self.telemetry_loop())

        await server.wait_closed()


def main():
    server = OmnixServer(port=8765)

    # Register simulated devices
    server.add_device(SimulatedDrone("SkyHawk Drone"))
    server.add_device(SimulatedRobotArm("Workshop Arm R1"))
    server.add_device(SimulatedSmartLight("Living Room Light"))
    server.add_device(SimulatedSmartLight("Desk Lamp"))

    # Run
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
