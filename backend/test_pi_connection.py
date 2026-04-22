#!/usr/bin/env python3
"""
OMNIX Pi Connection Test — Simulates a Pi agent connecting to the server.

Run this WITHOUT a real Raspberry Pi to verify the full pipeline:
  1. Ping the server
  2. Register a fake Pi device
  3. Send telemetry
  4. Queue a command from the "dashboard" side
  5. Poll for the command from the "Pi" side
  6. Report command result
  7. Verify the device appears in /api/devices
  8. Deregister

Usage:
    python test_pi_connection.py                    # Test against localhost:8765
    python test_pi_connection.py --server 192.168.1.100:8765  # Remote server
"""

import argparse
import json
import sys
import time
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def c(color, text):
    return f"{color}{text}{Colors.RESET}"


passed = 0
failed = 0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  {c(Colors.GREEN, 'PASS')}  {name}")
    else:
        failed += 1
        print(f"  {c(Colors.RED, 'FAIL')}  {name}")
        if detail:
            print(f"        {c(Colors.YELLOW, detail)}")


def post(url, data):
    body = json.dumps(data).encode("utf-8")
    req = Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {"error": str(e)}
        return e.code, body
    except URLError as e:
        return 0, {"error": str(e)}
    except Exception as e:
        return 0, {"error": str(e)}


def get(url):
    try:
        with urlopen(url, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {"error": str(e)}
        return e.code, body
    except URLError as e:
        return 0, {"error": str(e)}
    except Exception as e:
        return 0, {"error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Test Pi connection to OMNIX server")
    parser.add_argument("--server", default="http://localhost:8765",
                        help="OMNIX server URL (default: http://localhost:8765)")
    args = parser.parse_args()

    base = args.server.rstrip("/")
    if not base.startswith("http"):
        base = f"http://{base}"

    print()
    print(f"{Colors.BOLD}{'=' * 55}")
    print("  OMNIX Pi Connection Test")
    print(f"{'=' * 55}{Colors.RESET}")
    print(f"  Server: {base}")
    print()

    # ── Step 1: Ping ──
    print(f"{Colors.CYAN}Step 1: Ping server{Colors.RESET}")
    status, resp = get(f"{base}/api/pi/ping")
    test("Server reachable", status == 200,
         f"Got status {status}: {resp.get('error', '')}" if status != 200 else "")
    if status != 200:
        print(f"\n  {c(Colors.RED, 'FATAL: Cannot reach server. Is it running?')}")
        print(f"  Start it with: cd backend && python server_simple.py\n")
        sys.exit(1)
    test("Ping returns server info", resp.get("status") == "ok")
    print()

    # ── Step 2: Health check (no auth needed) ──
    print(f"{Colors.CYAN}Step 2: Health check (public route){Colors.RESET}")
    status, resp = get(f"{base}/api/health")
    test("Health endpoint accessible", status == 200)
    test("Server reports healthy", resp.get("status") == "healthy")
    print()

    # ── Step 3: Register Pi device ──
    print(f"{Colors.CYAN}Step 3: Register Pi agent (no auth required){Colors.RESET}")
    reg_payload = {
        "name": "Test Pi Rover",
        "device_type": "ground_robot",
        "capabilities": ["drive", "stop", "set_led", "read_sensor"],
        "hardware": {
            "gpio_mode": "simulated",
            "motors": ["left", "right"],
            "servos": [],
            "leds": ["headlight", "status"],
            "relays": [],
            "sensors": ["front_distance", "environment"],
            "camera": "simulated",
        },
        "description": "Test rover for connection validation",
    }
    status, resp = post(f"{base}/api/pi/register", reg_payload)
    test("Registration succeeds (no 401)", status == 200,
         f"Got {status}: {resp}" if status != 200 else "")
    if status == 401:
        print(f"\n  {c(Colors.RED, 'AUTH ERROR: Pi endpoints are being blocked by authentication!')}")
        print(f"  Fix: Add /api/pi/ to PUBLIC_PREFIXES in omnix/auth/middleware.py\n")
        sys.exit(1)

    agent_id = resp.get("agent_id", "")
    device_id = resp.get("device_id", "")
    test("Got agent_id", bool(agent_id), f"Response: {resp}")
    test("Got device_id", bool(device_id))
    print(f"        Agent ID:  {agent_id}")
    print(f"        Device ID: {device_id}")
    print()

    # ── Step 4: Verify device appears in /api/devices ──
    print(f"{Colors.CYAN}Step 4: Device appears in dashboard device list{Colors.RESET}")
    status, devs = get(f"{base}/api/devices")
    test("/api/devices accessible", status == 200)
    test("Pi device in device list", device_id in devs,
         f"Device {device_id} not found in: {list(devs.keys())}" if device_id not in devs else "")
    if device_id in devs:
        pi_entry = devs[device_id]
        test("Device marked as Pi", pi_entry.get("is_pi") is True)
        test("Device name correct", pi_entry.get("name") == "Test Pi Rover")
    print()

    # ── Step 5: Verify device in /api/pi/agents ──
    print(f"{Colors.CYAN}Step 5: Device appears in Pi agents list{Colors.RESET}")
    status, agents = get(f"{base}/api/pi/agents")
    test("/api/pi/agents accessible", status == 200)
    test("Agent in list", any(a.get("agent_id") == agent_id for a in agents))
    print()

    # ── Step 6: Send telemetry ──
    print(f"{Colors.CYAN}Step 6: Send telemetry (Pi → Server){Colors.RESET}")
    tele_payload = {
        "device_id": device_id,
        "telemetry": {
            "gpio": {"motors": {"left": {"speed": 0, "direction": "stopped"},
                                "right": {"speed": 0, "direction": "stopped"}}},
            "sensors": {"front_distance": {"distance_cm": 42.5},
                        "environment": {"temperature_c": 23.1, "humidity_pct": 55.0}},
            "camera": "simulated",
        },
        "timestamp": time.time(),
    }
    status, resp = post(f"{base}/api/pi/telemetry/{agent_id}", tele_payload)
    test("Telemetry accepted", status == 200 and resp.get("success"))
    print()

    # ── Step 7: Queue a command (Dashboard → Pi) ──
    print(f"{Colors.CYAN}Step 7: Queue command via /api/command (dashboard path){Colors.RESET}")
    status, resp = post(f"{base}/api/command", {
        "device_id": device_id,
        "command": "drive",
        "params": {"direction": "forward", "speed": 0.5},
    })
    test("/api/command routes to Pi agent", status == 200,
         f"Got {status}: {resp}" if status != 200 else "")
    test("Command queued successfully", resp.get("queued") or resp.get("success"))
    cmd_id_dashboard = resp.get("command_id", "")
    print()

    # Also test the direct Pi send-command endpoint
    print(f"{Colors.CYAN}Step 8: Queue command via /api/pi/send-command{Colors.RESET}")
    status, resp = post(f"{base}/api/pi/send-command", {
        "agent_id": agent_id,
        "command": "stop",
        "params": {},
    })
    test("Direct Pi command accepted", status == 200 and resp.get("success"))
    cmd_id_direct = resp.get("command_id", "")
    print()

    # ── Step 9: Pi polls for commands ──
    print(f"{Colors.CYAN}Step 9: Pi polls for pending commands{Colors.RESET}")
    status, resp = get(f"{base}/api/pi/commands/{agent_id}")
    test("Command poll succeeds", status == 200)
    commands = resp.get("commands", [])
    test("Commands received", len(commands) >= 2,
         f"Expected 2+ commands, got {len(commands)}: {commands}")
    if commands:
        cmd_names = [c.get("command") for c in commands]
        test("Drive command present", "drive" in cmd_names)
        test("Stop command present", "stop" in cmd_names)
    print()

    # ── Step 10: Report result back ──
    print(f"{Colors.CYAN}Step 10: Report command result (Pi → Server){Colors.RESET}")
    status, resp = post(f"{base}/api/pi/command-result/{agent_id}", {
        "command_id": cmd_id_dashboard,
        "result": {"success": True, "message": "Drove forward 0.5m"},
    })
    test("Command result accepted", status == 200 and resp.get("success"))
    print()

    # ── Step 11: Verify commands are cleared after poll ──
    print(f"{Colors.CYAN}Step 11: Command queue cleared after poll{Colors.RESET}")
    status, resp = get(f"{base}/api/pi/commands/{agent_id}")
    commands = resp.get("commands", [])
    test("Queue empty after poll", len(commands) == 0,
         f"Still has {len(commands)} commands" if commands else "")
    print()

    # ── Step 12: Deregister ──
    print(f"{Colors.CYAN}Step 12: Deregister Pi agent{Colors.RESET}")
    status, resp = post(f"{base}/api/pi/deregister/{agent_id}", {})
    test("Deregistration succeeds", status == 200 and resp.get("success"))

    # Verify gone
    status, devs = get(f"{base}/api/devices")
    test("Device removed from /api/devices", device_id not in devs)
    print()

    # ── Summary ──
    total = passed + failed
    print(f"{'=' * 55}")
    if failed == 0:
        print(f"  {c(Colors.GREEN, f'ALL {total} TESTS PASSED')} — Pi connectivity is working!")
    else:
        print(f"  {c(Colors.RED, f'{failed} FAILED')} / {total} tests")
        print(f"  Fix the issues above and re-run this script.")
    print(f"{'=' * 55}")
    print()

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
