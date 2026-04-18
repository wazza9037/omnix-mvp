"""
OMNIX Connector Manager — lifecycle + registry + VPE mapping.

The manager holds:
  - the known connector classes (code-level registry)
  - the active connector instances (runtime)
  - the VPE-category → connector-id mapping (registry.json)

It's the single place the server and the frontend talk to when asking
"what connectors can this scanned device use?" or "start a Tello
connector with this config".
"""

import os
import json
import time
import threading
from typing import Dict, List, Optional, Type

from connectors.base import ConnectorBase, ConnectorMeta

# Optional: use omnix logging if available; fall back to stdlib logging.
try:
    from omnix.logging_setup import get_logger
    from omnix.config import settings as _omnix_settings
    from omnix.models import ConnectorState
    _log = get_logger("omnix.connector.manager")
    _TICK_S = _omnix_settings.connector_tick_seconds
except Exception:  # pragma: no cover
    import logging
    import enum
    _log = logging.getLogger("omnix.connector.manager")
    _omnix_settings = None
    class ConnectorState(str, enum.Enum):
        DISCONNECTED = "disconnected"; CONNECTING = "connecting"
        CONNECTED = "connected"; DEGRADED = "degraded"
        ERROR = "error"; RECONNECTING = "reconnecting"
    _TICK_S = 0.5


class ConnectorManager:
    """Manages all OMNIX connectors at runtime."""

    def __init__(self, device_registry: dict, registry_json_path: str = None):
        # Reference to the server's global `devices` dict — connectors
        # add their produced devices here so they appear in the main
        # /api/devices listing automatically.
        self._device_registry = device_registry

        # connector_id → class
        self._classes: Dict[str, Type[ConnectorBase]] = {}

        # instance_id → instance
        self._instances: Dict[str, ConnectorBase] = {}

        # Mapping loaded from registry.json
        default_registry = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "connectors", "registry.json",
        )
        self._registry_path = registry_json_path or default_registry
        self._mapping = self._load_registry()

        self._tick_thread = None
        self._stop_ticking = threading.Event()

    # ─── Class registry ─────────────────────────────────────

    def register(self, cls: Type[ConnectorBase]):
        """Register a connector class. Called at server startup."""
        meta = getattr(cls, "meta", None)
        if not meta or not isinstance(meta, ConnectorMeta):
            raise ValueError(f"{cls.__name__} has no ConnectorMeta")
        if meta.connector_id in self._classes:
            # Silently replace — useful for hot-reload development
            pass
        self._classes[meta.connector_id] = cls

    def list_classes(self) -> List[dict]:
        """Return metadata for every registered connector class."""
        return [cls.meta.to_dict() for cls in self._classes.values()]

    def get_class(self, connector_id: str) -> Optional[Type[ConnectorBase]]:
        return self._classes.get(connector_id)

    # ─── VPE → connector mapping ────────────────────────────

    def _load_registry(self) -> dict:
        try:
            with open(self._registry_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"mappings": [], "default_connectors": []}
        except Exception as e:
            print(f"[connector_manager] failed to load registry: {e}")
            return {"mappings": [], "default_connectors": []}

    def reload_registry(self):
        self._mapping = self._load_registry()

    def suggest_for_vpe(self, device_category: str, device_type: str = "") -> List[dict]:
        """For a VPE result, return ordered connector suggestions.

        Each suggestion is:
          {connector_id, score, hint, meta}
        Higher score = better match. Callers should show the top 3.
        """
        cat = (device_category or "").lower()
        dtype = (device_type or "").lower()

        hits = []
        for m in self._mapping.get("mappings", []):
            match = m.get("match", {})
            ok = True
            if "device_category" in match and match["device_category"] != cat:
                ok = False
            if ok and "device_type_contains" in match:
                if match["device_type_contains"] not in dtype:
                    ok = False
            if ok and "device_type" in match and match["device_type"] != dtype:
                ok = False
            if not ok:
                continue
            for conn in m.get("connectors", []):
                cid = conn.get("id")
                cls = self._classes.get(cid)
                if not cls:
                    continue
                hits.append({
                    "connector_id": cid,
                    "score": conn.get("score", 5),
                    "hint": conn.get("hint", ""),
                    "meta": cls.meta.to_dict(),
                })

        # Always tack on defaults if nothing matched
        if not hits:
            for cid in self._mapping.get("default_connectors", []):
                cls = self._classes.get(cid)
                if cls:
                    hits.append({
                        "connector_id": cid,
                        "score": 1,
                        "hint": "Generic fallback — works with DIY builds.",
                        "meta": cls.meta.to_dict(),
                    })

        # De-dupe by connector_id, keep highest score
        seen = {}
        for h in hits:
            cid = h["connector_id"]
            if cid not in seen or h["score"] > seen[cid]["score"]:
                seen[cid] = h
        return sorted(seen.values(), key=lambda x: -x["score"])

    def get_raw_mapping(self) -> dict:
        return self._mapping

    # ─── Instance lifecycle ─────────────────────────────────

    def start_instance(self, connector_id: str, config: dict = None) -> dict:
        """Create, connect, and register a connector instance.

        Returns a dict with either {ok: True, instance, devices, status}
        or {ok: False, error}.
        """
        cls = self._classes.get(connector_id)
        if not cls:
            return {"ok": False, "error": f"Unknown connector '{connector_id}'"}

        try:
            inst = cls(config or {})
        except Exception as e:
            return {"ok": False, "error": f"Instantiation failed: {e}"}

        try:
            ok = inst.connect()
        except Exception as e:
            inst._mark_connected(False, f"connect() raised: {e}")
            ok = False

        if not ok:
            return {
                "ok": False,
                "error": inst._error or "connect() returned False",
                "status": inst.get_status(),
            }

        self._instances[inst.instance_id] = inst
        # Register the connector's devices into the main registry
        for dev in inst.get_devices():
            self._device_registry[dev.id] = dev

        self._ensure_tick_thread()
        return {
            "ok": True,
            "status": inst.get_status(),
            "devices": [d.get_info() for d in inst.get_devices()],
        }

    def stop_instance(self, instance_id: str) -> dict:
        inst = self._instances.pop(instance_id, None)
        if not inst:
            return {"ok": False, "error": "Unknown instance"}
        # Remove devices from main registry
        for dev in inst.get_devices():
            self._device_registry.pop(dev.id, None)
        try:
            inst.disconnect()
        except Exception as e:
            return {"ok": False, "error": f"disconnect() raised: {e}"}
        return {"ok": True}

    def list_instances(self) -> List[dict]:
        return [i.get_status() for i in self._instances.values()]

    def get_instance(self, instance_id: str) -> Optional[ConnectorBase]:
        return self._instances.get(instance_id)

    # ─── Tick loop ──────────────────────────────────────────

    def _ensure_tick_thread(self):
        if self._tick_thread and self._tick_thread.is_alive():
            return
        self._stop_ticking.clear()
        self._tick_thread = threading.Thread(
            target=self._tick_loop, daemon=True, name="connector-tick"
        )
        self._tick_thread.start()

    def _tick_loop(self):
        while not self._stop_ticking.is_set():
            for inst in list(self._instances.values()):
                try:
                    # Check heartbeat health first so a stale connection
                    # gets flipped to DEGRADED before the next tick.
                    inst.check_heartbeat_health()
                    # If the connector is in ERROR/RECONNECTING and its
                    # backoff window has elapsed, try to reconnect.
                    if inst._state in (ConnectorState.ERROR,
                                       ConnectorState.RECONNECTING):
                        inst.attempt_reconnect()
                    # Normal tick work (polling, state integration, etc.)
                    if inst._state in (ConnectorState.CONNECTED,
                                       ConnectorState.DEGRADED):
                        inst.tick()
                except Exception as e:
                    _log.exception("tick() raised on %s", inst.instance_id,
                                   extra={"instance_id": inst.instance_id})
                    inst._error = f"tick() raised: {e}"
                    try:
                        inst._transition(ConnectorState.ERROR, str(e))
                    except Exception:
                        pass
            self._stop_ticking.wait(_TICK_S)

    def shutdown(self):
        self._stop_ticking.set()
        for iid in list(self._instances.keys()):
            self.stop_instance(iid)
