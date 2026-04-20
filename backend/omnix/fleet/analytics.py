"""
Fleet Analytics — Uptime, mission success, battery trends, activity heatmap.
"""

import time
import threading
import random
import math


class FleetAnalytics:
    """Tracks and computes fleet-level analytics."""

    def __init__(self):
        self._lock = threading.Lock()
        # Per-device tracking
        self._uptime_log: dict[str, list] = {}       # device_id → [(ts, online_bool)]
        self._mission_log: dict[str, list] = {}       # device_id → [(ts, success_bool, name)]
        self._battery_log: dict[str, list] = {}       # device_id → [(ts, level)]
        self._distance_log: dict[str, float] = {}     # device_id → total_distance
        self._command_count: dict[str, int] = {}       # device_id → count
        self._last_position: dict[str, dict] = {}      # device_id → {x,y,z}
        self._activity_log: list[dict] = []            # [{ts, device_id, event}]
        self._max_log_entries = 2000
        self._initialized_devices: set = set()

    def _ensure_device(self, device_id: str):
        """Initialize tracking for a device if not yet done."""
        if device_id not in self._initialized_devices:
            self._uptime_log.setdefault(device_id, [])
            self._mission_log.setdefault(device_id, [])
            self._battery_log.setdefault(device_id, [])
            self._distance_log.setdefault(device_id, 0.0)
            self._command_count.setdefault(device_id, 0)
            self._initialized_devices.add(device_id)

    def record_telemetry(self, device_id: str, telemetry: dict):
        """Record a telemetry snapshot for analytics."""
        with self._lock:
            self._ensure_device(device_id)
            now = time.time()

            # Battery
            battery = telemetry.get("battery", telemetry.get("battery_pct"))
            if battery is not None:
                self._battery_log[device_id].append((now, battery))
                if len(self._battery_log[device_id]) > self._max_log_entries:
                    self._battery_log[device_id] = self._battery_log[device_id][-self._max_log_entries:]

            # Uptime (online if we're getting telemetry)
            status = telemetry.get("status", "online")
            is_online = status not in ("offline", "disconnected", "error")
            self._uptime_log[device_id].append((now, is_online))
            if len(self._uptime_log[device_id]) > self._max_log_entries:
                self._uptime_log[device_id] = self._uptime_log[device_id][-self._max_log_entries:]

            # Distance tracking
            pos = telemetry.get("position")
            if pos and isinstance(pos, dict):
                last = self._last_position.get(device_id)
                if last:
                    dx = pos.get("x", 0) - last.get("x", 0)
                    dy = pos.get("y", 0) - last.get("y", 0)
                    dz = pos.get("z", 0) - last.get("z", 0)
                    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
                    if dist < 100:  # sanity check
                        self._distance_log[device_id] += dist
                self._last_position[device_id] = dict(pos)

    def record_command(self, device_id: str):
        """Record that a command was sent to a device."""
        with self._lock:
            self._ensure_device(device_id)
            self._command_count[device_id] = self._command_count.get(device_id, 0) + 1
            self._activity_log.append({
                "ts": time.time(), "device_id": device_id, "event": "command"
            })
            if len(self._activity_log) > self._max_log_entries:
                self._activity_log = self._activity_log[-self._max_log_entries:]

    def record_mission(self, device_id: str, success: bool, mission_name: str = ""):
        """Record a mission completion."""
        with self._lock:
            self._ensure_device(device_id)
            self._mission_log[device_id].append((time.time(), success, mission_name))
            if len(self._mission_log[device_id]) > 500:
                self._mission_log[device_id] = self._mission_log[device_id][-500:]

    def get_device_analytics(self, device_id: str) -> dict:
        """Get analytics for a single device."""
        self._ensure_device(device_id)

        uptime = self._calc_uptime(device_id)
        missions = self._mission_log.get(device_id, [])
        total_missions = len(missions)
        successful = sum(1 for _, s, _ in missions if s)
        success_rate = round(successful / total_missions * 100, 1) if total_missions > 0 else 100.0

        battery_history = [
            {"ts": ts, "level": lvl}
            for ts, lvl in (self._battery_log.get(device_id, [])[-100:])
        ]

        mission_history = [
            {"ts": ts, "success": s, "name": n}
            for ts, s, n in (self._mission_log.get(device_id, [])[-20:])
        ]

        return {
            "device_id": device_id,
            "uptime_pct": uptime,
            "mission_success_rate": success_rate,
            "total_missions": total_missions,
            "successful_missions": successful,
            "failed_missions": total_missions - successful,
            "total_distance": round(self._distance_log.get(device_id, 0), 2),
            "command_count": self._command_count.get(device_id, 0),
            "battery_history": battery_history,
            "mission_history": mission_history,
        }

    def get_fleet_analytics(self, device_ids: list[str]) -> dict:
        """Get aggregated fleet-level analytics."""
        device_stats = []
        total_distance = 0
        total_commands = 0
        all_missions = 0
        all_successful = 0
        uptimes = []

        for did in device_ids:
            stats = self.get_device_analytics(did)
            device_stats.append(stats)
            total_distance += stats["total_distance"]
            total_commands += stats["command_count"]
            all_missions += stats["total_missions"]
            all_successful += stats["successful_missions"]
            uptimes.append(stats["uptime_pct"])

        avg_uptime = round(sum(uptimes) / len(uptimes), 1) if uptimes else 100.0
        mission_success_rate = (round(all_successful / all_missions * 100, 1)
                                if all_missions > 0 else 100.0)

        # Top 5 most active by command count
        top_active = sorted(device_stats, key=lambda d: d["command_count"], reverse=True)[:5]

        # Uptime leaderboard
        uptime_board = sorted(device_stats, key=lambda d: d["uptime_pct"], reverse=True)[:5]

        # Battery distribution
        battery_dist = self._battery_distribution(device_ids)

        # Activity heatmap (hourly for last 24h)
        heatmap = self._activity_heatmap()

        # Fleet utilization over time
        utilization = self._fleet_utilization(device_ids)

        return {
            "fleet_total_distance": round(total_distance, 2),
            "fleet_total_commands": total_commands,
            "fleet_avg_uptime": avg_uptime,
            "fleet_mission_success_rate": mission_success_rate,
            "fleet_total_missions": all_missions,
            "fleet_successful_missions": all_successful,
            "fleet_failed_missions": all_missions - all_successful,
            "top_active_devices": [
                {"device_id": d["device_id"], "command_count": d["command_count"]}
                for d in top_active
            ],
            "uptime_leaderboard": [
                {"device_id": d["device_id"], "uptime_pct": d["uptime_pct"]}
                for d in uptime_board
            ],
            "battery_distribution": battery_dist,
            "activity_heatmap": heatmap,
            "utilization": utilization,
            "device_analytics": {d["device_id"]: d for d in device_stats},
        }

    def _calc_uptime(self, device_id: str) -> float:
        """Calculate uptime percentage from log."""
        logs = self._uptime_log.get(device_id, [])
        if not logs:
            return 100.0
        online = sum(1 for _, ok in logs if ok)
        return round(online / len(logs) * 100, 1)

    def _battery_distribution(self, device_ids: list[str]) -> dict:
        """Get battery level distribution across fleet."""
        buckets = {"critical": 0, "low": 0, "medium": 0, "good": 0, "full": 0}
        for did in device_ids:
            logs = self._battery_log.get(did, [])
            if logs:
                level = logs[-1][1]
                if level < 10:
                    buckets["critical"] += 1
                elif level < 20:
                    buckets["low"] += 1
                elif level < 50:
                    buckets["medium"] += 1
                elif level < 80:
                    buckets["good"] += 1
                else:
                    buckets["full"] += 1
        return buckets

    def _activity_heatmap(self) -> list[dict]:
        """Generate hourly activity counts for last 24h."""
        now = time.time()
        hours = []
        for h in range(24):
            start = now - (24 - h) * 3600
            end = start + 3600
            count = sum(
                1 for entry in self._activity_log
                if start <= entry["ts"] < end
            )
            hours.append({"hour": h, "count": count})
        return hours

    def _fleet_utilization(self, device_ids: list[str]) -> list[dict]:
        """Fleet utilization (% of devices active) over last 24h in 1h buckets."""
        now = time.time()
        total = len(device_ids) or 1
        buckets = []
        for h in range(24):
            start = now - (24 - h) * 3600
            end = start + 3600
            active = set()
            for entry in self._activity_log:
                if start <= entry["ts"] < end:
                    active.add(entry["device_id"])
            pct = round(len(active) / total * 100, 1)
            buckets.append({"hour": h, "active_devices": len(active), "utilization_pct": pct})
        return buckets

    def seed_demo_data(self, device_ids: list[str]):
        """Seed analytics with simulated historical data for demo purposes."""
        now = time.time()
        for did in device_ids:
            self._ensure_device(did)
            # Simulate 24h of data
            for i in range(288):  # every 5 min
                ts = now - (288 - i) * 300
                # Uptime (95% online)
                online = random.random() < 0.95
                self._uptime_log[did].append((ts, online))
                # Battery (draining slowly from ~100)
                bat = max(15, 100 - i * 0.25 + random.uniform(-3, 3))
                self._battery_log[did].append((ts, round(bat, 1)))
                # Activity
                if random.random() < 0.3:
                    self._activity_log.append({"ts": ts, "device_id": did, "event": "command"})
                    self._command_count[did] = self._command_count.get(did, 0) + 1

            # Simulated missions
            for _ in range(random.randint(3, 12)):
                ts = now - random.uniform(0, 86400)
                success = random.random() < 0.85
                name = random.choice(["patrol", "delivery", "inspection", "survey", "pickup"])
                self._mission_log[did].append((ts, success, name))

            # Distance
            self._distance_log[did] = round(random.uniform(50, 500), 2)
