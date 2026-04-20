#!/usr/bin/env python3
"""
OMNIX End-to-End Integration Test Suite

Starts the server in-process and hits every major endpoint.
Run with: python3 tests/test_e2e.py
"""

import json
import os
import sys
import time
import threading
import unittest
import urllib.request
import urllib.error
import io
import base64

# Ensure the backend package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = "http://localhost:8765"
_server_thread = None
_server_started = threading.Event()


def _start_server():
    """Start the OMNIX server in a background thread using subprocess."""
    import subprocess
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.Popen(
        [sys.executable, "server_simple.py"],
        cwd=backend_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _server_started.set()
    proc.wait()


# ─── Helpers ────────────────────────────────────────────────────────

def get(path, expect_status=200):
    """GET request, return parsed JSON."""
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as r:
            data = json.loads(r.read().decode())
            assert r.status == expect_status, f"Expected {expect_status}, got {r.status}"
            return data
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return json.loads(body)
        except Exception:
            raise AssertionError(f"GET {path} failed: {e.code} {body[:200]}")


def post(path, body=None, expect_status=None):
    """POST JSON, return parsed JSON."""
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read().decode())
            if expect_status is not None:
                assert r.status == expect_status, f"Expected {expect_status}, got {r.status}"
            return result
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return json.loads(body)
        except Exception:
            raise AssertionError(f"POST {path} failed: {e.code} {body[:200]}")


def get_device_id(device_type):
    """Get the first device ID of a given type."""
    devices = get("/api/devices")
    for did, d in devices.items():
        if d["device_type"] == device_type:
            return did
    raise AssertionError(f"No device of type {device_type}")


def make_test_image(w, h, color=(128, 128, 128)):
    """Create a base64-encoded PNG test image."""
    # Simple BMP-to-PNG via raw bytes (no PIL dependency)
    # Use a minimal valid PNG
    import struct
    import zlib

    def create_png(width, height, r, g, b):
        """Create a minimal PNG image."""
        raw_data = b""
        for _ in range(height):
            raw_data += b"\x00"  # filter byte
            raw_data += bytes([r, g, b]) * width
        compressed = zlib.compress(raw_data)

        def chunk(chunk_type, data):
            c = chunk_type + data
            crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
            return struct.pack(">I", len(data)) + c + crc

        png = b"\x89PNG\r\n\x1a\n"
        png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        png += chunk(b"IDAT", compressed)
        png += chunk(b"IEND", b"")
        return png

    png_bytes = create_png(w, h, *color)
    return base64.b64encode(png_bytes).decode()


# ─── Test Cases ─────────────────────────────────────────────────────

class TestHealthAndBasics(unittest.TestCase):
    """Step 1: Server boot and basic endpoints."""

    def test_healthz(self):
        data = get("/healthz")
        self.assertEqual(data["status"], "healthy")
        self.assertIn("version", data)
        self.assertGreater(data["device_count"], 0)

    def test_main_page_loads(self):
        with urllib.request.urlopen(BASE + "/", timeout=5) as r:
            html = r.read().decode()
            self.assertIn("<!DOCTYPE html>", html)
            self.assertIn("OMNIX", html)

    def test_metrics(self):
        data = get("/api/metrics")
        self.assertIsInstance(data, dict)


class TestDevices(unittest.TestCase):
    """Step 2a: Device endpoints."""

    def test_list_devices(self):
        devices = get("/api/devices")
        self.assertGreater(len(devices), 0)
        for did, d in devices.items():
            self.assertIn("device_type", d)
            self.assertIn("name", d)

    def test_telemetry(self):
        devices = get("/api/devices")
        did = list(devices.keys())[0]
        telemetry = get("/api/telemetry")
        self.assertIn(did, telemetry)

    def test_events(self):
        did = get_device_id("drone")
        events = get(f"/api/events/{did}")
        self.assertIsInstance(events, (list, dict))


class TestTemplates(unittest.TestCase):
    """Step 2b: Templates."""

    def test_list_templates(self):
        templates = get("/api/templates")
        self.assertEqual(len(templates), 10)
        for t in templates:
            self.assertIn("template_id", t)
            self.assertIn("device_type", t)

    def test_instantiate_template(self):
        templates = get("/api/templates")
        tid = templates[0]["template_id"]
        result = post("/api/templates/instantiate", {"template_id": tid})
        self.assertIn("device", result)
        self.assertIn("id", result["device"])


class TestConnectors(unittest.TestCase):
    """Step 2c: Connectors."""

    def test_connector_classes(self):
        classes = get("/api/connectors/classes")
        self.assertGreaterEqual(len(classes), 6)

    def test_connector_instances(self):
        instances = get("/api/connectors/instances")
        self.assertIsInstance(instances, list)


class TestMarketplace(unittest.TestCase):
    """Step 2d: Marketplace."""

    def test_marketplace_items(self):
        data = get("/api/marketplace")
        self.assertIn("items", data)
        self.assertGreater(len(data["items"]), 0)

    def test_marketplace_featured(self):
        data = get("/api/marketplace/featured")
        self.assertIsInstance(data, (list, dict))
        if isinstance(data, list):
            self.assertGreater(len(data), 0)


class TestNLP(unittest.TestCase):
    """Step 2e + Step 4: NLP command pipeline."""

    def test_compile_drone_command(self):
        did = get_device_id("drone")
        result = post("/api/nlp/compile", {
            "text": "take off and fly forward 5 meters",
            "device_id": did,
        })
        self.assertIn("steps", result)
        self.assertEqual(len(result["steps"]), 2)
        self.assertEqual(result["steps"][0]["command"], "takeoff")
        self.assertEqual(result["steps"][1]["command"], "move")

    def test_compile_arm_pick(self):
        did = get_device_id("robot_arm")
        result = post("/api/nlp/compile", {
            "text": "pick up the object",
            "device_id": did,
        })
        self.assertIn("steps", result)
        self.assertGreater(len(result["steps"]), 0)

    def test_compile_arm_pick_with_coords(self):
        did = get_device_id("robot_arm")
        result = post("/api/nlp/compile", {
            "text": "pick up the object at position 0.3 0 0.2",
            "device_id": did,
        })
        self.assertIn("steps", result)
        self.assertGreater(len(result["steps"]), 0)

    def test_compile_arm_move_to(self):
        did = get_device_id("robot_arm")
        result = post("/api/nlp/compile", {
            "text": "move to position 0.5 0 0.3",
            "device_id": did,
        })
        self.assertIn("steps", result)
        self.assertGreater(len(result["steps"]), 0)

    def test_execute_plan(self):
        did = get_device_id("drone")
        plan = post("/api/nlp/compile", {
            "text": "take off",
            "device_id": did,
        })
        result = post("/api/nlp/execute", {"plan": plan})
        self.assertIn("execution_id", result)

    def test_emergency_stop(self):
        did = get_device_id("drone")
        result = post("/api/nlp/stop", {"device_id": did})
        self.assertIn("ok", result)


class TestBehaviorTrees(unittest.TestCase):
    """Step 2f: Behavior trees."""

    def test_bt_templates(self):
        templates = get("/api/bt/templates")
        self.assertGreater(len(templates), 0)


class TestDigitalTwin(unittest.TestCase):
    """Step 2g: Digital Twin."""

    def test_create_twin(self):
        did = get_device_id("drone")
        result = post("/api/twin/create", {"device_id": did})
        self.assertTrue(result.get("ok"))
        self.assertIn("twin", result)

    def test_twin_sessions(self):
        sessions = get("/api/twin/sessions")
        self.assertIsInstance(sessions, (list, dict))


class TestSensors(unittest.TestCase):
    """Step 2h: Sensors."""

    def test_sensor_data(self):
        did = get_device_id("drone")
        data = get(f"/api/sensors/{did}")
        self.assertIn("sensors", data)
        self.assertGreater(len(data["sensors"]), 0)
        for sensor in data["sensors"]:
            self.assertIn("id", sensor)
            self.assertIn("current_value", sensor)


class TestVideo(unittest.TestCase):
    """Step 2i: Video."""

    def test_video_sources(self):
        data = get("/api/video/sources")
        # Response is either a list directly or a dict with "sources" key
        if isinstance(data, dict):
            self.assertIn("sources", data)
            self.assertIsInstance(data["sources"], list)
        else:
            self.assertIsInstance(data, list)


class TestPlugins(unittest.TestCase):
    """Step 2j: Plugins."""

    def test_list_plugins(self):
        plugins = get("/api/plugins")
        self.assertGreaterEqual(len(plugins), 3)


class TestOTA(unittest.TestCase):
    """Step 2k: OTA Firmware."""

    def test_firmware_list(self):
        data = get("/api/ota/firmware")
        self.assertIn("firmware", data)

    def test_builder_status(self):
        data = get("/api/ota/builder/status")
        self.assertIsInstance(data, dict)


class TestSwarm(unittest.TestCase):
    """Step 2l: Swarm."""

    def test_swarm_groups(self):
        data = get("/api/swarm/groups")
        self.assertIn("groups", data)

    def test_swarm_formations(self):
        data = get("/api/swarm/formations")
        self.assertIsInstance(data, (list, dict))

    def test_swarm_missions(self):
        data = get("/api/swarm/missions")
        self.assertIsInstance(data, (list, dict))


class TestFleet(unittest.TestCase):
    """Step 2m: Fleet Management."""

    def test_fleet_overview(self):
        data = get("/api/fleet/overview")
        self.assertIn("total_devices", data)
        self.assertGreater(data["total_devices"], 0)
        self.assertIn("health_score", data)

    def test_fleet_devices(self):
        data = get("/api/fleet/devices")
        self.assertIn("devices", data)

    def test_fleet_locations(self):
        data = get("/api/fleet/locations")
        self.assertIn("locations", data)

    def test_fleet_analytics(self):
        data = get("/api/fleet/analytics")
        self.assertIsInstance(data, dict)

    def test_fleet_alerts(self):
        data = get("/api/fleet/alerts")
        self.assertIsInstance(data, dict)


class TestAI(unittest.TestCase):
    """Step 2n: AI Models."""

    def test_ai_models(self):
        data = get("/api/ai/models")
        self.assertIn("models", data)
        self.assertGreater(len(data["models"]), 0)


class TestEnvironments(unittest.TestCase):
    """Step 2o: Environments."""

    def test_environment_list(self):
        data = get("/api/environments")
        self.assertIn("environments", data)
        self.assertGreater(len(data["environments"]), 0)


class TestCollab(unittest.TestCase):
    """Step 2p: Collaboration."""

    def test_create_session(self):
        result = post("/api/collab/create", {"name": "Test Session"})
        self.assertIn("session_id", result)
        self.assertIn("share_code", result)

    def test_list_sessions(self):
        data = get("/api/collab/sessions")
        self.assertIsInstance(data, (list, dict))


class TestAuth(unittest.TestCase):
    """Step 2q: Authentication."""

    def test_register_and_login(self):
        username = f"testuser_{int(time.time())}"
        reg = post("/api/auth/register", {
            "username": username,
            "password": "TestPass123!",
            "email": f"{username}@test.com",
        })
        self.assertIn("user", reg)
        self.assertIn("access_token", reg)

        login = post("/api/auth/login", {
            "username": username,
            "password": "TestPass123!",
        })
        self.assertIn("user", login)
        self.assertIn("access_token", login)

    def test_guest_token(self):
        data = get("/api/auth/guest")
        self.assertIn("access_token", data)


class TestVPE(unittest.TestCase):
    """Step 3: VPE scanning pipeline."""

    def test_analyze_wide_image(self):
        """Wide image should classify as fixed-wing or elongated type."""
        b64 = make_test_image(400, 100, (200, 200, 200))
        result = post("/api/vpe/analyze", {"image": b64})
        self.assertIn("classification", result)
        self.assertIn("mesh_params", result)
        cls = result["classification"]
        self.assertIn("device_type", cls)
        self.assertIn("confidence", cls)
        self.assertGreater(cls["confidence"], 0)
        # Mesh should have primitives
        prims = result["mesh_params"].get("primitives", [])
        self.assertGreater(len(prims), 0)

    def test_analyze_square_image(self):
        """Square image should classify differently from wide."""
        b64 = make_test_image(200, 200, (100, 150, 200))
        result = post("/api/vpe/analyze", {"image": b64})
        cls = result["classification"]
        self.assertIn("device_type", cls)

    def test_classifications_vary(self):
        """Different aspect ratios should produce different classifications."""
        wide = post("/api/vpe/analyze", {"image": make_test_image(400, 100)})
        square = post("/api/vpe/analyze", {"image": make_test_image(200, 200)})
        wide_type = wide["classification"]["device_type"]
        square_type = square["classification"]["device_type"]
        self.assertNotEqual(wide_type, square_type,
                            "Wide and square images should classify differently")

    def test_mesh_params_vary(self):
        """Different classifications should produce different mesh params."""
        wide = post("/api/vpe/analyze", {"image": make_test_image(400, 100)})
        square = post("/api/vpe/analyze", {"image": make_test_image(200, 200)})
        wide_mesh = wide["mesh_params"]["device_type"]
        square_mesh = square["mesh_params"]["device_type"]
        self.assertNotEqual(wide_mesh, square_mesh)


class TestSimulation(unittest.TestCase):
    """Step 6: Simulation runner."""

    def test_list_scenarios(self):
        scenarios = get("/api/simulation/scenarios")
        self.assertGreaterEqual(len(scenarios), 5)

    def test_run_hover(self):
        did = get_device_id("drone")
        # Ensure workspace exists
        get(f"/api/workspaces/{did}")
        result = post(f"/api/workspaces/{did}/iterations", {
            "scenario": "hover",
            "params": {"altitude_m": 5.0},
        })
        self.assertIn("metrics", result)
        self.assertIn("trajectory", result)
        self.assertGreater(len(result["trajectory"]), 0)
        # Check metrics contain expected fields
        metrics = result["metrics"]
        self.assertIn("tracking_score", metrics)
        self.assertIn("stability", metrics)
        self.assertIn("overall", metrics)


class TestWorkspaces(unittest.TestCase):
    """Step 7: Workspace/tab system."""

    def test_workspace_list(self):
        workspaces = get("/api/workspaces")
        self.assertIsInstance(workspaces, list)

    def test_workspace_per_device(self):
        """Each device should get its own workspace."""
        drone = get_device_id("drone")
        arm = get_device_id("robot_arm")
        ws_drone = get(f"/api/workspaces/{drone}")
        ws_arm = get(f"/api/workspaces/{arm}")
        self.assertNotEqual(
            ws_drone.get("workspace_id"),
            ws_arm.get("workspace_id"),
        )

    def test_workspace_has_device_info(self):
        did = get_device_id("drone")
        ws = get(f"/api/workspaces/{did}")
        self.assertIn("workspace_id", ws)
        self.assertIn("device_id", ws)


class TestMovements(unittest.TestCase):
    """Movement presets."""

    def test_presets_list(self):
        presets = get("/api/movements/presets")
        self.assertIsInstance(presets, list)
        self.assertGreater(len(presets), 0)

    def test_presets_by_device_type(self):
        presets = get("/api/movements/presets?device_type=drone")
        self.assertIsInstance(presets, list)
        for p in presets:
            self.assertIn("name", p)


class TestParts(unittest.TestCase):
    """Parts library."""

    def test_parts_list(self):
        parts = get("/api/parts")
        self.assertIsInstance(parts, (list, dict))


class TestMeshGeneration(unittest.TestCase):
    """Step 5: 3D model generation for all categories."""

    def test_all_categories_generate_mesh(self):
        """Every mesh generator category should produce primitives."""
        from vpe.mesh_generator import generate_mesh

        categories = [
            "drone", "ground_robot", "robot_arm", "humanoid", "legged",
            "home_robot", "service_robot", "warehouse", "medical",
            "smart_light", "smart_device", "marine", "space", "extreme",
        ]
        for cat in categories:
            cls = {"device_category": cat, "device_type": f"test_{cat}"}
            img = {
                "geometry": {"estimated_dimensions_cm": [20, 20, 10]},
                "color_profile": {
                    "estimated_material": "plastic",
                    "dominant_colors": [{"hex": "#888888"}],
                },
                "structural": {"components": []},
            }
            physics = {"mass_kg": 1.0, "center_of_mass": [0, 0, 0]}
            mesh = generate_mesh(cls, img, physics)
            prims = mesh.get("primitives", [])
            self.assertGreater(
                len(prims), 0,
                f"Category '{cat}' produced no primitives",
            )
            # Every primitive should have a type
            for p in prims:
                self.assertIn("type", p, f"Primitive missing 'type' in {cat}")


# ─── Runner ─────────────────────────────────────────────────────────

def main():
    # Check if server is already running
    try:
        urllib.request.urlopen(BASE + "/healthz", timeout=2)
        print("Server already running at", BASE)
    except Exception:
        print("Starting server in background...")
        t = threading.Thread(target=_start_server, daemon=True)
        t.start()
        _server_started.wait(timeout=15)
        # Give the server a moment to bind
        for _ in range(20):
            try:
                urllib.request.urlopen(BASE + "/healthz", timeout=2)
                break
            except Exception:
                time.sleep(0.5)
        else:
            print("ERROR: Server failed to start")
            sys.exit(1)
        print("Server started successfully")

    print()
    print("=" * 70)
    print("  OMNIX End-to-End Test Suite")
    print("=" * 70)
    print()

    # Run all tests
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print()
    print("=" * 70)
    total = result.testsRun
    failures = len(result.failures) + len(result.errors)
    passed = total - failures
    print(f"  Results: {passed}/{total} passed, {failures} failed")
    print("=" * 70)

    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
