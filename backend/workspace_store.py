"""
OMNIX Workspace Store — one "lab notebook" per device.

A Workspace is the persistent context for a single robot inside OMNIX.
It's the thing that survives tab switches, stores notes, accumulates
simulation iterations, and holds the learned physics model that gets
refined each time you run a scenario against the device.

Shape of a workspace:
    {
      "workspace_id":   "ws-<8>"
      "device_id":      "<id of the OmnixDevice it wraps>"
      "name":           "My Tello"
      "created_at":     epoch
      "updated_at":     epoch
      "notes":          "free-form lab notes from the user"
      "tags":           ["outdoor", "gps"]
      "color":          "#00B4D8"      # tab color
      "connector_info": { "connector_id": "...", "config": {...} } | None
      "specs":          { summary info auto-derived + user-editable }
      "physics":        AdaptivePhysics.snapshot()   # learned params + confidence
      "world":          { gravity, friction, obstacles, bounds, ... }
      "iterations":     list[iteration dict]    # append-only
      "telemetry_window": deque of last ~100 snapshots
    }

Iterations are written by `simulation.runner.run_scenario(...)`, which
mutates `workspace["physics"]` through the adaptive model and then
appends a record with metrics/trajectory. Frontend reads from the
workspace to render charts and trend lines.
"""

import time
import uuid
import threading
from collections import deque
from typing import Dict, List, Optional, Any


DEFAULT_WORLD = {
    "gravity_m_s2": 9.81,
    "surface_friction": 0.7,
    "bounds_m": {"x": [-50, 50], "y": [-50, 50], "z": [0, 40]},
    "obstacles": [],        # [{x, y, z, r}] simple spheres for now
    "wind_m_s": 0.0,
    "target_points": [],    # waypoints the scenarios can reference
}


class WorkspaceStore:
    """In-memory workspace store (session-scoped).

    Thread-safe at the individual-workspace granularity — a coarse lock
    is fine here because writes happen at user-interaction rates.
    """

    def __init__(self):
        self._by_device: Dict[str, dict] = {}
        self._by_workspace: Dict[str, dict] = {}
        self._lock = threading.Lock()
        # Device-type → preferred tab accent color
        self._type_colors = {
            "drone": "#00B4D8",
            "robot_arm": "#F59E0B",
            "smart_light": "#FFD700",
            "ground_robot": "#10B981",
            "humanoid": "#A78BFA",
            "legged": "#22D3EE",
            "home_robot": "#F97316",
            "marine": "#3B82F6",
        }

    # ── Lifecycle ──────────────────────────────────────────

    def ensure(self, device) -> dict:
        """Return existing workspace for the device or create a fresh one.

        `device` is any OmnixDevice-like object with at minimum .id, .name,
        and .device_type. Capabilities, if present, are included in specs.
        """
        with self._lock:
            if device.id in self._by_device:
                # Sync the display name if the device was renamed
                ws = self._by_device[device.id]
                if ws["name"] != device.name:
                    ws["name"] = device.name
                    ws["updated_at"] = time.time()
                return ws

            wid = f"ws-{uuid.uuid4().hex[:8]}"
            ws = {
                "workspace_id": wid,
                "device_id": device.id,
                "name": device.name,
                "device_type": device.device_type,
                "created_at": time.time(),
                "updated_at": time.time(),
                "notes": "",
                "tags": [],
                "color": self._type_colors.get(device.device_type, "#00B4D8"),
                "connector_info": None,
                "specs": self._derive_specs(device),
                "physics": None,       # populated lazily by simulation module
                "world": dict(DEFAULT_WORLD),
                "iterations": [],
                "telemetry_window": deque(maxlen=120),
                # Custom-build state (populated for CustomRobotDevice devices
                # via the /api/workspaces/<id>/custom-build endpoints).
                "custom_build": None,
                "template_id": None,
            }
            self._by_device[device.id] = ws
            self._by_workspace[wid] = ws
            return ws

    def get_by_device(self, device_id: str) -> Optional[dict]:
        return self._by_device.get(device_id)

    def get(self, workspace_id: str) -> Optional[dict]:
        return self._by_workspace.get(workspace_id)

    def list_all(self) -> List[dict]:
        """Light-weight list suitable for the tab bar."""
        with self._lock:
            out = []
            for ws in self._by_device.values():
                last_iter = ws["iterations"][-1] if ws["iterations"] else None
                out.append({
                    "workspace_id": ws["workspace_id"],
                    "device_id": ws["device_id"],
                    "name": ws["name"],
                    "device_type": ws["device_type"],
                    "color": ws["color"],
                    "tags": list(ws["tags"]),
                    "iteration_count": len(ws["iterations"]),
                    "last_iteration_at": last_iter["timestamp"] if last_iter else None,
                    "best_score": self._best_score(ws),
                    "physics_confidence": (ws["physics"] or {}).get("confidence", 0.0),
                    "updated_at": ws["updated_at"],
                })
            return sorted(out, key=lambda x: -x["updated_at"])

    def drop(self, device_id: str):
        """Remove a workspace — e.g. when a device is hard-deleted."""
        with self._lock:
            ws = self._by_device.pop(device_id, None)
            if ws:
                self._by_workspace.pop(ws["workspace_id"], None)

    # ── Editable fields ────────────────────────────────────

    def update_meta(self, device_id: str,
                    name: str = None, notes: str = None,
                    tags: list = None, color: str = None,
                    connector_info: dict = None) -> Optional[dict]:
        ws = self._by_device.get(device_id)
        if not ws:
            return None
        with self._lock:
            if name is not None and name.strip():
                ws["name"] = name.strip()
            if notes is not None:
                ws["notes"] = notes
            if tags is not None:
                ws["tags"] = [str(t).strip() for t in tags if str(t).strip()]
            if color is not None and isinstance(color, str):
                ws["color"] = color
            if connector_info is not None:
                ws["connector_info"] = connector_info
            ws["updated_at"] = time.time()
            return ws

    def update_world(self, device_id: str, world_patch: dict) -> Optional[dict]:
        ws = self._by_device.get(device_id)
        if not ws:
            return None
        with self._lock:
            ws["world"].update(world_patch or {})
            ws["updated_at"] = time.time()
            return ws

    def set_custom_build(self, device_id: str, build_dict: dict,
                        template_id: str = None) -> Optional[dict]:
        """Store the full custom-build dict on a workspace.

        Pass the serialized CustomBuild — routes call this after the
        CustomRobotDevice has already absorbed it.
        """
        ws = self._by_device.get(device_id)
        if not ws:
            return None
        with self._lock:
            ws["custom_build"] = build_dict
            if template_id is not None:
                ws["template_id"] = template_id
            ws["updated_at"] = time.time()
            return ws

    def set_physics(self, device_id: str, physics_snapshot: dict) -> Optional[dict]:
        ws = self._by_device.get(device_id)
        if not ws:
            return None
        with self._lock:
            ws["physics"] = physics_snapshot
            ws["updated_at"] = time.time()
            return ws

    # ── Iteration management ───────────────────────────────

    def append_iteration(self, device_id: str, iteration: dict) -> Optional[dict]:
        ws = self._by_device.get(device_id)
        if not ws:
            return None
        with self._lock:
            # Assign a stable id + number if caller didn't
            if "id" not in iteration:
                iteration["id"] = f"iter-{uuid.uuid4().hex[:8]}"
            iteration["number"] = len(ws["iterations"]) + 1
            iteration["timestamp"] = iteration.get("timestamp", time.time())
            # Compute improvement_delta relative to previous iteration
            if ws["iterations"]:
                prev = ws["iterations"][-1]
                iteration["delta"] = {
                    k: round(iteration.get("metrics", {}).get(k, 0)
                             - prev.get("metrics", {}).get(k, 0), 4)
                    for k in iteration.get("metrics", {})
                }
            else:
                iteration["delta"] = {k: 0.0 for k in iteration.get("metrics", {})}
            ws["iterations"].append(iteration)
            ws["updated_at"] = time.time()
            return iteration

    def get_iteration(self, device_id: str, iteration_id: str) -> Optional[dict]:
        ws = self._by_device.get(device_id)
        if not ws:
            return None
        for it in ws["iterations"]:
            if it.get("id") == iteration_id:
                return it
        return None

    def update_iteration(self, device_id: str, iteration_id: str, patch: dict) -> Optional[dict]:
        it = self.get_iteration(device_id, iteration_id)
        if not it:
            return None
        with self._lock:
            for k in ("note", "tags"):
                if k in patch:
                    it[k] = patch[k]
            it["updated_at"] = time.time()
            return it

    def remove_iteration(self, device_id: str, iteration_id: str) -> bool:
        ws = self._by_device.get(device_id)
        if not ws:
            return False
        with self._lock:
            before = len(ws["iterations"])
            ws["iterations"] = [i for i in ws["iterations"] if i.get("id") != iteration_id]
            ws["updated_at"] = time.time()
            return len(ws["iterations"]) != before

    # ── Telemetry window (for live charts) ─────────────────

    def push_telemetry(self, device_id: str, telemetry: dict):
        ws = self._by_device.get(device_id)
        if not ws:
            return
        ws["telemetry_window"].append({"ts": time.time(), "data": telemetry})

    def get_telemetry_history(self, device_id: str) -> list:
        ws = self._by_device.get(device_id)
        if not ws:
            return []
        return list(ws["telemetry_window"])

    # ── Helpers ────────────────────────────────────────────

    def _derive_specs(self, device) -> dict:
        caps = []
        if hasattr(device, "get_capabilities"):
            try:
                caps = device.get_capabilities()
            except Exception:
                caps = []
        return {
            "capabilities": caps,
            "capability_count": len(caps),
            "notes": "",     # user can add spec overrides later
        }

    def _best_score(self, ws) -> Optional[float]:
        """Best overall score across all iterations (for tab-bar display)."""
        best = None
        for it in ws["iterations"]:
            s = (it.get("metrics") or {}).get("overall")
            if s is None:
                continue
            if best is None or s > best:
                best = s
        return best

    def serialize(self, ws: dict, include_telemetry: bool = False) -> dict:
        """JSON-safe version of a workspace."""
        out = {k: v for k, v in ws.items() if k != "telemetry_window"}
        if include_telemetry:
            out["telemetry_window"] = list(ws["telemetry_window"])
        return out
