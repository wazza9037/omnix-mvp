"""
Pre-built mission templates for the behavior tree system.

Each template is a function that returns a BehaviorTree definition dict
(JSON-serializable). The visual editor loads these and the user can
customize them before execution.

Templates:
  1. Patrol & Return    — fly waypoints in a loop, return home
  2. Search & Report    — systematic area scan, log findings
  3. Sentry Mode        — hover in place, monitor telemetry, alert on anomalies
  4. Pick & Place Cycle — robot arm: pick from A, place at B, repeat
  5. Follow Path        — follow a sequence of GPS/coordinate waypoints
  6. Emergency Response — check battery, assess, land or return home
"""

from __future__ import annotations


def _patrol_and_return() -> dict:
    """Patrol waypoints in a loop, then return to start."""
    return {
        "name": "Patrol & Return",
        "description": "Fly a patrol loop through waypoints, then return to home position. Checks battery before each lap.",
        "icon": "🔄",
        "device_types": ["drone", "ground_robot"],
        "root": {
            "type": "Sequence", "node_id": "patrol-root", "name": "Patrol Mission",
            "category": "composite", "properties": {}, "x": 400, "y": 50,
            "children": [
                {
                    "type": "CheckBattery", "node_id": "patrol-bat", "name": "Battery OK?",
                    "category": "condition", "properties": {"min_pct": 30},
                    "children": [], "x": 100, "y": 150,
                },
                {
                    "type": "ExecuteCommand", "node_id": "patrol-takeoff", "name": "Take Off",
                    "category": "action",
                    "properties": {"command": "takeoff", "params": {"altitude": 5}, "duration_s": 2.0},
                    "children": [], "x": 250, "y": 150,
                },
                {
                    "type": "Repeat", "node_id": "patrol-loop", "name": "Patrol 3 Laps",
                    "category": "decorator", "properties": {"count": 3},
                    "x": 400, "y": 150,
                    "children": [{
                        "type": "Sequence", "node_id": "patrol-lap", "name": "One Lap",
                        "category": "composite", "properties": {}, "x": 400, "y": 250,
                        "children": [
                            {
                                "type": "ExecuteCommand", "node_id": "patrol-wp1",
                                "name": "Waypoint 1", "category": "action",
                                "properties": {"command": "move_to", "params": {"x": 10, "y": 0, "z": 5}, "duration_s": 3.0},
                                "children": [], "x": 200, "y": 350,
                            },
                            {
                                "type": "ExecuteCommand", "node_id": "patrol-wp2",
                                "name": "Waypoint 2", "category": "action",
                                "properties": {"command": "move_to", "params": {"x": 10, "y": 10, "z": 5}, "duration_s": 3.0},
                                "children": [], "x": 350, "y": 350,
                            },
                            {
                                "type": "ExecuteCommand", "node_id": "patrol-wp3",
                                "name": "Waypoint 3", "category": "action",
                                "properties": {"command": "move_to", "params": {"x": 0, "y": 10, "z": 5}, "duration_s": 3.0},
                                "children": [], "x": 500, "y": 350,
                            },
                            {
                                "type": "Log", "node_id": "patrol-log",
                                "name": "Log Lap", "category": "action",
                                "properties": {"message": "Lap completed", "level": "info"},
                                "children": [], "x": 650, "y": 350,
                            },
                        ],
                    }],
                },
                {
                    "type": "ExecuteCommand", "node_id": "patrol-home", "name": "Return Home",
                    "category": "action",
                    "properties": {"command": "move_to", "params": {"x": 0, "y": 0, "z": 5}, "duration_s": 3.0},
                    "children": [], "x": 550, "y": 150,
                },
                {
                    "type": "ExecuteCommand", "node_id": "patrol-land", "name": "Land",
                    "category": "action",
                    "properties": {"command": "land", "params": {}, "duration_s": 2.0},
                    "children": [], "x": 700, "y": 150,
                },
            ],
        },
    }


def _search_and_report() -> dict:
    """Systematic area search with logging."""
    return {
        "name": "Search & Report",
        "description": "Systematically scan an area in a grid pattern, logging observations at each point.",
        "icon": "🔍",
        "device_types": ["drone", "ground_robot"],
        "root": {
            "type": "Sequence", "node_id": "search-root", "name": "Search Mission",
            "category": "composite", "properties": {}, "x": 350, "y": 50,
            "children": [
                {
                    "type": "Log", "node_id": "search-start", "name": "Start Search",
                    "category": "action",
                    "properties": {"message": "Beginning area search", "level": "info"},
                    "children": [], "x": 100, "y": 150,
                },
                {
                    "type": "SetVariable", "node_id": "search-init", "name": "Init Counter",
                    "category": "action",
                    "properties": {"variable": "points_scanned", "value": 0},
                    "children": [], "x": 250, "y": 150,
                },
                {
                    "type": "ExecuteCommand", "node_id": "search-takeoff", "name": "Take Off",
                    "category": "action",
                    "properties": {"command": "takeoff", "params": {"altitude": 8}, "duration_s": 2.0},
                    "children": [], "x": 400, "y": 150,
                },
                {
                    "type": "Sequence", "node_id": "search-grid", "name": "Grid Scan",
                    "category": "composite", "properties": {}, "x": 350, "y": 260,
                    "children": [
                        {
                            "type": "ExecuteCommand", "node_id": "search-p1", "name": "Scan Point 1",
                            "category": "action",
                            "properties": {"command": "move_to", "params": {"x": -10, "y": -10, "z": 8}, "duration_s": 3.0},
                            "children": [], "x": 100, "y": 360,
                        },
                        {
                            "type": "Wait", "node_id": "search-hover1", "name": "Observe",
                            "category": "action",
                            "properties": {"duration_s": 2.0},
                            "children": [], "x": 250, "y": 360,
                        },
                        {
                            "type": "ExecuteCommand", "node_id": "search-p2", "name": "Scan Point 2",
                            "category": "action",
                            "properties": {"command": "move_to", "params": {"x": 10, "y": -10, "z": 8}, "duration_s": 3.0},
                            "children": [], "x": 400, "y": 360,
                        },
                        {
                            "type": "ExecuteCommand", "node_id": "search-p3", "name": "Scan Point 3",
                            "category": "action",
                            "properties": {"command": "move_to", "params": {"x": 10, "y": 10, "z": 8}, "duration_s": 3.0},
                            "children": [], "x": 550, "y": 360,
                        },
                    ],
                },
                {
                    "type": "Log", "node_id": "search-done", "name": "Report Complete",
                    "category": "action",
                    "properties": {"message": "Search complete — area scanned", "level": "info"},
                    "children": [], "x": 550, "y": 150,
                },
                {
                    "type": "ExecuteCommand", "node_id": "search-land", "name": "Land",
                    "category": "action",
                    "properties": {"command": "land", "params": {}, "duration_s": 2.0},
                    "children": [], "x": 700, "y": 150,
                },
            ],
        },
    }


def _sentry_mode() -> dict:
    """Hover and monitor, alert on anomalies."""
    return {
        "name": "Sentry Mode",
        "description": "Hover at a fixed position and continuously monitor telemetry. Alert if battery drops or anomaly detected.",
        "icon": "👁️",
        "device_types": ["drone"],
        "root": {
            "type": "Sequence", "node_id": "sentry-root", "name": "Sentry Mission",
            "category": "composite", "properties": {}, "x": 300, "y": 50,
            "children": [
                {
                    "type": "ExecuteCommand", "node_id": "sentry-takeoff", "name": "Take Off",
                    "category": "action",
                    "properties": {"command": "takeoff", "params": {"altitude": 10}, "duration_s": 2.0},
                    "children": [], "x": 100, "y": 150,
                },
                {
                    "type": "ExecuteCommand", "node_id": "sentry-pos", "name": "Move to Post",
                    "category": "action",
                    "properties": {"command": "move_to", "params": {"x": 5, "y": 5, "z": 10}, "duration_s": 3.0},
                    "children": [], "x": 250, "y": 150,
                },
                {
                    "type": "Repeat", "node_id": "sentry-loop", "name": "Monitor Loop",
                    "category": "decorator", "properties": {"count": 20},
                    "x": 400, "y": 150,
                    "children": [{
                        "type": "Selector", "node_id": "sentry-check", "name": "Check Status",
                        "category": "composite", "properties": {}, "x": 400, "y": 250,
                        "children": [
                            {
                                "type": "Sequence", "node_id": "sentry-ok", "name": "All OK",
                                "category": "composite", "properties": {}, "x": 300, "y": 350,
                                "children": [
                                    {
                                        "type": "CheckBattery", "node_id": "sentry-bat",
                                        "name": "Battery > 20%", "category": "condition",
                                        "properties": {"min_pct": 20},
                                        "children": [], "x": 250, "y": 450,
                                    },
                                    {
                                        "type": "Wait", "node_id": "sentry-wait",
                                        "name": "Hold Position", "category": "action",
                                        "properties": {"duration_s": 3.0},
                                        "children": [], "x": 400, "y": 450,
                                    },
                                ],
                            },
                            {
                                "type": "Sequence", "node_id": "sentry-abort", "name": "Low Battery",
                                "category": "composite", "properties": {}, "x": 550, "y": 350,
                                "children": [
                                    {
                                        "type": "Log", "node_id": "sentry-alert",
                                        "name": "Alert!", "category": "action",
                                        "properties": {"message": "Low battery — returning!", "level": "warning"},
                                        "children": [], "x": 550, "y": 450,
                                    },
                                    {
                                        "type": "EmitEvent", "node_id": "sentry-evt",
                                        "name": "Emit Alert", "category": "action",
                                        "properties": {"event": "low_battery_alert", "data": {}},
                                        "children": [], "x": 700, "y": 450,
                                    },
                                ],
                            },
                        ],
                    }],
                },
                {
                    "type": "ExecuteCommand", "node_id": "sentry-land", "name": "Land",
                    "category": "action",
                    "properties": {"command": "land", "params": {}, "duration_s": 2.0},
                    "children": [], "x": 550, "y": 150,
                },
            ],
        },
    }


def _pick_and_place() -> dict:
    """Robot arm pick & place cycle."""
    return {
        "name": "Pick & Place Cycle",
        "description": "Robot arm picks objects from position A and places them at position B. Repeats for a batch of items.",
        "icon": "🦾",
        "device_types": ["robot_arm"],
        "root": {
            "type": "Repeat", "node_id": "pp-root", "name": "Pick & Place ×5",
            "category": "decorator", "properties": {"count": 5},
            "x": 350, "y": 50,
            "children": [{
                "type": "Sequence", "node_id": "pp-cycle", "name": "One Cycle",
                "category": "composite", "properties": {}, "x": 350, "y": 150,
                "children": [
                    {
                        "type": "ExecuteCommand", "node_id": "pp-open1", "name": "Open Gripper",
                        "category": "action",
                        "properties": {"command": "set_gripper", "params": {"open": True}, "duration_s": 0.5},
                        "children": [], "x": 50, "y": 250,
                    },
                    {
                        "type": "ExecuteCommand", "node_id": "pp-move-pick", "name": "Move to Pick",
                        "category": "action",
                        "properties": {"command": "move_joint", "params": {"joint": "base", "angle": -45}, "duration_s": 1.5},
                        "children": [], "x": 200, "y": 250,
                    },
                    {
                        "type": "ExecuteCommand", "node_id": "pp-close", "name": "Close Gripper",
                        "category": "action",
                        "properties": {"command": "set_gripper", "params": {"open": False}, "duration_s": 0.5},
                        "children": [], "x": 350, "y": 250,
                    },
                    {
                        "type": "ExecuteCommand", "node_id": "pp-move-place", "name": "Move to Place",
                        "category": "action",
                        "properties": {"command": "move_joint", "params": {"joint": "base", "angle": 45}, "duration_s": 1.5},
                        "children": [], "x": 500, "y": 250,
                    },
                    {
                        "type": "ExecuteCommand", "node_id": "pp-open2", "name": "Release",
                        "category": "action",
                        "properties": {"command": "set_gripper", "params": {"open": True}, "duration_s": 0.5},
                        "children": [], "x": 650, "y": 250,
                    },
                    {
                        "type": "Log", "node_id": "pp-log", "name": "Log Cycle",
                        "category": "action",
                        "properties": {"message": "Pick & place cycle done", "level": "info"},
                        "children": [], "x": 800, "y": 250,
                    },
                ],
            }],
        },
    }


def _follow_path() -> dict:
    """Follow a sequence of waypoints."""
    return {
        "name": "Follow Path",
        "description": "Navigate through a series of coordinate waypoints in order. Useful for predefined routes and surveys.",
        "icon": "📍",
        "device_types": ["drone", "ground_robot"],
        "root": {
            "type": "Sequence", "node_id": "fp-root", "name": "Follow Path",
            "category": "composite", "properties": {}, "x": 350, "y": 50,
            "children": [
                {
                    "type": "ExecuteCommand", "node_id": "fp-start", "name": "Take Off",
                    "category": "action",
                    "properties": {"command": "takeoff", "params": {"altitude": 3}, "duration_s": 2.0},
                    "children": [], "x": 50, "y": 150,
                },
                {
                    "type": "ExecuteCommand", "node_id": "fp-wp1", "name": "WP 1 (0,5,3)",
                    "category": "action",
                    "properties": {"command": "move_to", "params": {"x": 0, "y": 5, "z": 3}, "duration_s": 2.0},
                    "children": [], "x": 180, "y": 150,
                },
                {
                    "type": "ExecuteCommand", "node_id": "fp-wp2", "name": "WP 2 (5,5,3)",
                    "category": "action",
                    "properties": {"command": "move_to", "params": {"x": 5, "y": 5, "z": 3}, "duration_s": 2.0},
                    "children": [], "x": 310, "y": 150,
                },
                {
                    "type": "ExecuteCommand", "node_id": "fp-wp3", "name": "WP 3 (5,0,3)",
                    "category": "action",
                    "properties": {"command": "move_to", "params": {"x": 5, "y": 0, "z": 3}, "duration_s": 2.0},
                    "children": [], "x": 440, "y": 150,
                },
                {
                    "type": "ExecuteCommand", "node_id": "fp-wp4", "name": "WP 4 (0,0,3)",
                    "category": "action",
                    "properties": {"command": "move_to", "params": {"x": 0, "y": 0, "z": 3}, "duration_s": 2.0},
                    "children": [], "x": 570, "y": 150,
                },
                {
                    "type": "ExecuteCommand", "node_id": "fp-land", "name": "Land",
                    "category": "action",
                    "properties": {"command": "land", "params": {}, "duration_s": 2.0},
                    "children": [], "x": 700, "y": 150,
                },
            ],
        },
    }


def _emergency_response() -> dict:
    """Emergency assessment and safe landing."""
    return {
        "name": "Emergency Response",
        "description": "Assess device health, attempt recovery, or perform emergency landing. Uses selector for fallback logic.",
        "icon": "🚨",
        "device_types": ["drone", "ground_robot", "robot_arm"],
        "root": {
            "type": "Sequence", "node_id": "er-root", "name": "Emergency Response",
            "category": "composite", "properties": {}, "x": 350, "y": 50,
            "children": [
                {
                    "type": "Log", "node_id": "er-start", "name": "Emergency Started",
                    "category": "action",
                    "properties": {"message": "EMERGENCY: Initiating emergency response", "level": "warning"},
                    "children": [], "x": 100, "y": 150,
                },
                {
                    "type": "EmitEvent", "node_id": "er-evt", "name": "Emit Emergency",
                    "category": "action",
                    "properties": {"event": "emergency_triggered", "data": {"severity": "high"}},
                    "children": [], "x": 250, "y": 150,
                },
                {
                    "type": "Selector", "node_id": "er-assess", "name": "Assess & Respond",
                    "category": "composite", "properties": {}, "x": 450, "y": 150,
                    "children": [
                        {
                            "type": "Sequence", "node_id": "er-recover", "name": "Try Recovery",
                            "category": "composite", "properties": {}, "x": 300, "y": 260,
                            "children": [
                                {
                                    "type": "CheckBattery", "node_id": "er-bat",
                                    "name": "Battery > 10%", "category": "condition",
                                    "properties": {"min_pct": 10},
                                    "children": [], "x": 200, "y": 360,
                                },
                                {
                                    "type": "ExecuteCommand", "node_id": "er-home",
                                    "name": "Return Home", "category": "action",
                                    "properties": {"command": "move_to", "params": {"x": 0, "y": 0, "z": 3}, "duration_s": 5.0},
                                    "children": [], "x": 350, "y": 360,
                                },
                                {
                                    "type": "ExecuteCommand", "node_id": "er-land1",
                                    "name": "Land Safely", "category": "action",
                                    "properties": {"command": "land", "params": {}, "duration_s": 2.0},
                                    "children": [], "x": 500, "y": 360,
                                },
                            ],
                        },
                        {
                            "type": "Sequence", "node_id": "er-crash-land", "name": "Emergency Land",
                            "category": "composite", "properties": {}, "x": 600, "y": 260,
                            "children": [
                                {
                                    "type": "Log", "node_id": "er-crit",
                                    "name": "Critical!", "category": "action",
                                    "properties": {"message": "CRITICAL: Emergency landing NOW", "level": "error"},
                                    "children": [], "x": 600, "y": 360,
                                },
                                {
                                    "type": "ExecuteCommand", "node_id": "er-land2",
                                    "name": "Force Land", "category": "action",
                                    "properties": {"command": "land", "params": {"emergency": True}, "duration_s": 1.0},
                                    "children": [], "x": 750, "y": 360,
                                },
                            ],
                        },
                    ],
                },
                {
                    "type": "Log", "node_id": "er-done", "name": "Response Complete",
                    "category": "action",
                    "properties": {"message": "Emergency response complete", "level": "info"},
                    "children": [], "x": 600, "y": 150,
                },
            ],
        },
    }


# ── Template Library (public API) ────────────────────────

TEMPLATE_LIBRARY: list[dict] = [
    _patrol_and_return(),
    _search_and_report(),
    _sentry_mode(),
    _pick_and_place(),
    _follow_path(),
    _emergency_response(),
]


def get_template(name: str) -> dict | None:
    for t in TEMPLATE_LIBRARY:
        if t["name"] == name:
            return t
    return None


def list_templates(device_type: str | None = None) -> list[dict]:
    """Return template summaries, optionally filtered by device type."""
    result = []
    for t in TEMPLATE_LIBRARY:
        if device_type and device_type not in t.get("device_types", []):
            continue
        result.append({
            "name": t["name"],
            "description": t["description"],
            "icon": t["icon"],
            "device_types": t["device_types"],
        })
    return result
