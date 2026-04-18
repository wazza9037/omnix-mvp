"""
OMNIX Alert Manager — configurable thresholds per sensor.

Alert types:
  - above: triggers when value > threshold
  - below: triggers when value < threshold
  - range: triggers when value outside [min, max]
  - rate_of_change: triggers when value changes by X in Y seconds

Alert states: triggered → acknowledged → cleared
"""

import time
import uuid
import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AlertRule:
    """Configuration for a sensor alert."""
    id: str
    device_id: str
    sensor_id: str
    alert_type: str          # above | below | range | rate_of_change
    threshold: Optional[float] = None    # for above/below
    range_min: Optional[float] = None    # for range type
    range_max: Optional[float] = None    # for range type
    rate_delta: Optional[float] = None   # for rate_of_change (value change)
    rate_window: Optional[float] = None  # for rate_of_change (seconds)
    actions: list = field(default_factory=lambda: ["visual", "log"])
    enabled: bool = True
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "device_id": self.device_id,
            "sensor_id": self.sensor_id,
            "alert_type": self.alert_type,
            "threshold": self.threshold,
            "range_min": self.range_min,
            "range_max": self.range_max,
            "rate_delta": self.rate_delta,
            "rate_window": self.rate_window,
            "actions": self.actions,
            "enabled": self.enabled,
            "created_at": self.created_at,
        }

    @staticmethod
    def from_dict(d: dict) -> "AlertRule":
        return AlertRule(
            id=d.get("id", str(uuid.uuid4())[:8]),
            device_id=d["device_id"],
            sensor_id=d["sensor_id"],
            alert_type=d["alert_type"],
            threshold=d.get("threshold"),
            range_min=d.get("range_min"),
            range_max=d.get("range_max"),
            rate_delta=d.get("rate_delta"),
            rate_window=d.get("rate_window"),
            actions=d.get("actions", ["visual", "log"]),
            enabled=d.get("enabled", True),
        )


@dataclass
class Alert:
    """An active alert instance."""
    id: str
    rule_id: str
    device_id: str
    sensor_id: str
    sensor_name: str
    alert_type: str
    message: str
    value: float
    threshold_info: str
    state: str = "triggered"    # triggered | acknowledged | cleared
    triggered_at: float = field(default_factory=time.time)
    acknowledged_at: Optional[float] = None
    cleared_at: Optional[float] = None
    severity: str = "warning"   # info | warning | critical

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "device_id": self.device_id,
            "sensor_id": self.sensor_id,
            "sensor_name": self.sensor_name,
            "alert_type": self.alert_type,
            "message": self.message,
            "value": round(self.value, 4),
            "threshold_info": self.threshold_info,
            "state": self.state,
            "triggered_at": self.triggered_at,
            "acknowledged_at": self.acknowledged_at,
            "cleared_at": self.cleared_at,
            "severity": self.severity,
        }


class AlertManager:
    """Manages alert rules and checks sensor values against them."""

    def __init__(self):
        self._lock = threading.Lock()
        # device_id → [AlertRule]
        self._rules: dict[str, list[AlertRule]] = {}
        # alert_id → Alert
        self._alerts: dict[str, Alert] = {}
        # For rate_of_change: device_id:sensor_id → (timestamp, value)
        self._rate_history: dict[str, list[tuple[float, float]]] = {}
        # Log entries
        self._log: list[dict] = []

    def add_rule(self, rule: AlertRule) -> AlertRule:
        """Add or update an alert rule."""
        with self._lock:
            if rule.device_id not in self._rules:
                self._rules[rule.device_id] = []
            # Replace existing rule with same ID
            self._rules[rule.device_id] = [
                r for r in self._rules[rule.device_id] if r.id != rule.id
            ]
            self._rules[rule.device_id].append(rule)
        return rule

    def remove_rule(self, device_id: str, rule_id: str) -> bool:
        """Remove an alert rule."""
        with self._lock:
            rules = self._rules.get(device_id, [])
            before = len(rules)
            self._rules[device_id] = [r for r in rules if r.id != rule_id]
            return len(self._rules[device_id]) < before

    def get_rules(self, device_id: str) -> list[dict]:
        """Get all alert rules for a device."""
        with self._lock:
            return [r.to_dict() for r in self._rules.get(device_id, [])]

    def check_sensor(self, device_id: str, sensor_id: str,
                     sensor_name: str, value: float,
                     timestamp: Optional[float] = None) -> list[Alert]:
        """Check a sensor value against all applicable rules.
        Returns newly triggered alerts."""
        ts = timestamp or time.time()
        new_alerts = []

        with self._lock:
            rules = [
                r for r in self._rules.get(device_id, [])
                if r.sensor_id == sensor_id and r.enabled
            ]

        for rule in rules:
            triggered = False
            threshold_info = ""

            if rule.alert_type == "above" and rule.threshold is not None:
                if value > rule.threshold:
                    triggered = True
                    threshold_info = f"> {rule.threshold}"

            elif rule.alert_type == "below" and rule.threshold is not None:
                if value < rule.threshold:
                    triggered = True
                    threshold_info = f"< {rule.threshold}"

            elif rule.alert_type == "range":
                rmin = rule.range_min if rule.range_min is not None else float("-inf")
                rmax = rule.range_max if rule.range_max is not None else float("inf")
                if value < rmin or value > rmax:
                    triggered = True
                    threshold_info = f"outside [{rmin}, {rmax}]"

            elif rule.alert_type == "rate_of_change":
                key = f"{device_id}:{sensor_id}"
                history = self._rate_history.get(key, [])
                history.append((ts, value))
                # Keep only entries within the window
                window = rule.rate_window or 10.0
                history = [(t, v) for t, v in history if ts - t <= window]
                self._rate_history[key] = history
                if len(history) >= 2:
                    oldest_val = history[0][1]
                    delta = abs(value - oldest_val)
                    if rule.rate_delta is not None and delta > rule.rate_delta:
                        triggered = True
                        threshold_info = f"Δ{delta:.2f} in {window}s (limit: {rule.rate_delta})"

            if triggered:
                # Check if this rule already has an active (non-cleared) alert
                existing = self._find_active_alert(rule.id)
                if existing:
                    # Update value but don't create duplicate
                    existing.value = value
                    continue

                severity = "critical" if rule.alert_type in ("above", "below") else "warning"
                alert = Alert(
                    id=f"alert-{uuid.uuid4().hex[:8]}",
                    rule_id=rule.id,
                    device_id=device_id,
                    sensor_id=sensor_id,
                    sensor_name=sensor_name,
                    alert_type=rule.alert_type,
                    message=f"{sensor_name} {threshold_info} (current: {value:.2f})",
                    value=value,
                    threshold_info=threshold_info,
                    triggered_at=ts,
                    severity=severity,
                )
                with self._lock:
                    self._alerts[alert.id] = alert
                new_alerts.append(alert)

                # Log entry
                self._log.append({
                    "timestamp": ts,
                    "alert_id": alert.id,
                    "sensor": sensor_name,
                    "message": alert.message,
                    "severity": severity,
                })
            else:
                # Auto-clear if condition no longer met
                existing = self._find_active_alert(rule.id)
                if existing and existing.state == "triggered":
                    existing.state = "cleared"
                    existing.cleared_at = ts

        return new_alerts

    def _find_active_alert(self, rule_id: str) -> Optional[Alert]:
        """Find a non-cleared alert for a given rule."""
        with self._lock:
            for alert in self._alerts.values():
                if alert.rule_id == rule_id and alert.state != "cleared":
                    return alert
        return None

    def acknowledge(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        with self._lock:
            alert = self._alerts.get(alert_id)
            if alert and alert.state == "triggered":
                alert.state = "acknowledged"
                alert.acknowledged_at = time.time()
                return True
        return False

    def get_alerts(self, device_id: Optional[str] = None,
                   state: Optional[str] = None) -> list[dict]:
        """Get alerts, optionally filtered by device and/or state."""
        with self._lock:
            alerts = list(self._alerts.values())
        if device_id:
            alerts = [a for a in alerts if a.device_id == device_id]
        if state:
            alerts = [a for a in alerts if a.state == state]
        # Sort by triggered_at descending
        alerts.sort(key=lambda a: a.triggered_at, reverse=True)
        return [a.to_dict() for a in alerts[:100]]

    def get_active_alerts(self, device_id: Optional[str] = None) -> list[dict]:
        """Get only triggered/acknowledged (non-cleared) alerts."""
        with self._lock:
            alerts = [
                a for a in self._alerts.values()
                if a.state in ("triggered", "acknowledged")
            ]
        if device_id:
            alerts = [a for a in alerts if a.device_id == device_id]
        alerts.sort(key=lambda a: a.triggered_at, reverse=True)
        return [a.to_dict() for a in alerts]

    def get_log(self, limit: int = 50) -> list[dict]:
        """Get recent alert log entries."""
        return self._log[-limit:]

    def clear_device(self, device_id: str):
        """Clear all alerts and rules for a device."""
        with self._lock:
            self._rules.pop(device_id, None)
            to_remove = [
                aid for aid, a in self._alerts.items()
                if a.device_id == device_id
            ]
            for aid in to_remove:
                del self._alerts[aid]
