"""
Fleet Manager — Tracks ALL devices globally with health scoring and alerts.
"""

import time
import threading
import uuid


class FleetAlert:
    """A fleet-level alert."""

    SEVERITY_INFO = "info"
    SEVERITY_WARNING = "warning"
    SEVERITY_CRITICAL = "critical"

    def __init__(self, alert_type: str, severity: str, message: str,
                 device_id: str = None, details: dict = None):
        self.id = f"alert-{uuid.uuid4().hex[:8]}"
        self.alert_type = alert_type
        self.severity = severity
        self.message = message
        self.device_id = device_id
        self.details = details or {}
        self.created_at = time.time()
        self.acknowledged = False
        self.acknowledged_at = None

    def to_dict(self):
        return {
            "id": self.id,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "message": self.message,
            "device_id": self.device_id,
            "details": self.details,
            "created_at": self.created_at,
            "acknowledged": self.acknowledged,
            "acknowledged_at": self.acknowledged_at,
        }


class FleetEvent:
    """A fleet activity event."""

    def __init__(self, event_type: str, message: str, device_id: str = None,
                 severity: str = "info", details: dict = None):
        self.id = f"evt-{uuid.uuid4().hex[:8]}"
        self.event_type = event_type
        self.message = message
        self.device_id = device_id
        self.severity = severity
        self.details = details or {}
        self.created_at = time.time()

    def to_dict(self):
        return {
            "id": self.id,
            "event_type": self.event_type,
            "message": self.message,
            "device_id": self.device_id,
            "severity": self.severity,
            "details": self.details,
            "created_at": self.created_at,
        }


class FleetManager:
    """Tracks all devices globally with health scoring and alerts."""

    # Alert thresholds
    BATTERY_WARNING = 20
    BATTERY_CRITICAL = 10
    OFFLINE_TIMEOUT_S = 300  # 5 minutes

    def __init__(self):
        self._lock = threading.Lock()
        self.alerts: list[FleetAlert] = []
        self.events: list[FleetEvent] = []
        self._last_seen: dict[str, float] = {}  # device_id → timestamp
        self._device_missions: dict[str, dict] = {}  # device_id → current mission info
        self._max_alerts = 500
        self._max_events = 1000

    def _emit_event(self, event_type: str, message: str, device_id: str = None,
                    severity: str = "info", details: dict = None):
        """Record a fleet event."""
        evt = FleetEvent(event_type, message, device_id, severity, details)
        self.events.append(evt)
        if len(self.events) > self._max_events:
            self.events = self.events[-self._max_events:]
        return evt

    def _emit_alert(self, alert_type: str, severity: str, message: str,
                    device_id: str = None, details: dict = None):
        """Create a fleet alert (deduplicates by type+device)."""
        # Don't duplicate active alerts
        for a in self.alerts:
            if (not a.acknowledged and a.alert_type == alert_type
                    and a.device_id == device_id):
                return a

        alert = FleetAlert(alert_type, severity, message, device_id, details)
        self.alerts.append(alert)
        if len(self.alerts) > self._max_alerts:
            self.alerts = self.alerts[-self._max_alerts:]

        self._emit_event("alert", message, device_id, severity,
                         {"alert_id": alert.id, "alert_type": alert_type})
        return alert

    def touch_device(self, device_id: str):
        """Mark a device as seen (updates last_seen timestamp)."""
        self._last_seen[device_id] = time.time()

    def set_device_mission(self, device_id: str, mission: dict = None):
        """Set or clear the current mission for a device."""
        if mission:
            self._device_missions[device_id] = mission
        else:
            self._device_missions.pop(device_id, None)

    def get_device_summary(self, device, workspace=None) -> dict:
        """Get a summary dict for a single device."""
        try:
            telemetry = device.get_telemetry()
        except Exception:
            telemetry = {}

        battery = telemetry.get("battery", telemetry.get("battery_pct", None))
        position = telemetry.get("position", {"x": 0, "y": 0, "z": 0})
        status = telemetry.get("status", getattr(device, "status", "unknown"))

        # Update last_seen
        self.touch_device(device.id)

        return {
            "id": device.id,
            "name": getattr(device, "name", device.id),
            "type": getattr(device, "device_type", "unknown"),
            "status": status,
            "battery": battery,
            "position": position,
            "speed": telemetry.get("speed", 0),
            "heading": telemetry.get("heading", 0),
            "signal_strength": telemetry.get("signal_strength", "unknown"),
            "current_mission": self._device_missions.get(device.id),
            "last_seen": self._last_seen.get(device.id, time.time()),
            "capabilities": (
                [c["name"] if isinstance(c, dict) else c
                 for c in device.get_capabilities()]
                if hasattr(device, "get_capabilities") else []
            ),
        }

    def get_fleet_overview(self, devices: dict, workspaces=None) -> dict:
        """Get fleet-wide statistics."""
        now = time.time()
        total = len(devices)
        online = 0
        offline = 0
        error_count = 0
        charging = 0
        batteries = []
        device_summaries = []

        for did, dev in devices.items():
            summary = self.get_device_summary(dev)
            device_summaries.append(summary)

            status = summary["status"]
            if status in ("online", "idle", "ready", "hovering", "flying", "moving"):
                online += 1
            elif status in ("error", "fault", "emergency"):
                error_count += 1
            elif status == "charging":
                charging += 1
                online += 1  # charging is still online
            else:
                offline += 1

            if summary["battery"] is not None:
                batteries.append(summary["battery"])

        avg_battery = round(sum(batteries) / len(batteries), 1) if batteries else 0
        health_score = self._calculate_health_score(
            total, online, offline, error_count, avg_battery
        )

        # Check for alerts
        self._check_alerts(device_summaries, now)

        active_alerts = [a for a in self.alerts if not a.acknowledged]

        return {
            "total_devices": total,
            "online": online,
            "offline": offline,
            "error": error_count,
            "charging": charging,
            "avg_battery": avg_battery,
            "health_score": health_score,
            "alerts": [a.to_dict() for a in active_alerts[-20:]],
            "alert_count": len(active_alerts),
            "timestamp": now,
        }

    def _calculate_health_score(self, total: int, online: int, offline: int,
                                errors: int, avg_battery: float) -> int:
        """Calculate fleet health 0-100."""
        if total == 0:
            return 100

        # Online ratio (50 points)
        online_score = (online / total) * 50

        # Error penalty (up to -30)
        error_penalty = min(errors / total * 30, 30) if total > 0 else 0

        # Battery score (30 points)
        battery_score = (avg_battery / 100) * 30

        # Offline penalty (up to -20)
        offline_penalty = min(offline / total * 20, 20) if total > 0 else 0

        score = online_score + battery_score - error_penalty - offline_penalty
        return max(0, min(100, round(score)))

    def _check_alerts(self, summaries: list, now: float):
        """Check all devices for alert conditions."""
        for s in summaries:
            did = s["id"]
            bat = s["battery"]
            status = s["status"]

            # Battery alerts
            if bat is not None:
                if bat < self.BATTERY_CRITICAL:
                    self._emit_alert(
                        "battery_critical", FleetAlert.SEVERITY_CRITICAL,
                        f"{s['name']} battery critically low ({bat}%)",
                        did, {"battery": bat}
                    )
                elif bat < self.BATTERY_WARNING:
                    self._emit_alert(
                        "battery_warning", FleetAlert.SEVERITY_WARNING,
                        f"{s['name']} battery low ({bat}%)",
                        did, {"battery": bat}
                    )

            # Offline alerts
            if status in ("offline", "disconnected", "error"):
                last_seen = self._last_seen.get(did, now)
                if now - last_seen > self.OFFLINE_TIMEOUT_S:
                    self._emit_alert(
                        "device_offline", FleetAlert.SEVERITY_WARNING,
                        f"{s['name']} offline for >{int((now - last_seen) / 60)}min",
                        did, {"offline_seconds": now - last_seen}
                    )

            # Error/fault alerts
            if status in ("error", "fault", "emergency"):
                self._emit_alert(
                    "device_error", FleetAlert.SEVERITY_CRITICAL,
                    f"{s['name']} in {status} state",
                    did, {"status": status}
                )

    def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge (dismiss) an alert."""
        for a in self.alerts:
            if a.id == alert_id:
                a.acknowledged = True
                a.acknowledged_at = time.time()
                return True
        return False

    def get_alerts(self, active_only: bool = True) -> list[dict]:
        """Get alerts, optionally filtered to active only."""
        alerts = self.alerts
        if active_only:
            alerts = [a for a in alerts if not a.acknowledged]
        return [a.to_dict() for a in alerts[-50:]]

    def get_events(self, device_id: str = None, event_type: str = None,
                   severity: str = None, limit: int = 50) -> list[dict]:
        """Get recent events with optional filters."""
        evts = self.events
        if device_id:
            evts = [e for e in evts if e.device_id == device_id]
        if event_type:
            evts = [e for e in evts if e.event_type == event_type]
        if severity:
            evts = [e for e in evts if e.severity == severity]
        return [e.to_dict() for e in evts[-limit:]]

    def record_event(self, event_type: str, message: str, device_id: str = None,
                     severity: str = "info", details: dict = None):
        """Public method to record a fleet event."""
        with self._lock:
            return self._emit_event(event_type, message, device_id, severity, details).to_dict()
