"""
Synchronization primitives for multi-robot coordination.

These primitives coordinate timing across multiple robots in a group:

  - Barrier:      all robots wait until every member reaches a checkpoint
  - Countdown:    synchronized start (3, 2, 1, go!)
  - Heartbeat:    detect if a robot falls out of sync / disconnects
  - ReFormation:  if a robot disconnects, remaining robots close the gap
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SyncState(str, Enum):
    WAITING = "waiting"
    READY = "ready"
    TRIGGERED = "triggered"
    EXPIRED = "expired"


# ── Barrier ─────────────────────────────────────────────────────────

class Barrier:
    """
    All robots wait until every member reaches the checkpoint.
    Once all have arrived, the barrier releases and returns True.
    """

    def __init__(self, group_id: str, label: str, expected_ids: list[str],
                 timeout: float = 60.0):
        self.id = f"barrier-{group_id}-{int(time.time())}"
        self.group_id = group_id
        self.label = label
        self.expected: set[str] = set(expected_ids)
        self.arrived: set[str] = set()
        self.timeout = timeout
        self.created_at = time.time()
        self.released_at: float | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> SyncState:
        if self.released_at is not None:
            return SyncState.TRIGGERED
        if time.time() - self.created_at > self.timeout:
            return SyncState.EXPIRED
        if self.arrived >= self.expected:
            return SyncState.READY
        return SyncState.WAITING

    def arrive(self, device_id: str) -> bool:
        """A robot signals it has reached the checkpoint.
        Returns True if this arrival triggered the barrier release."""
        with self._lock:
            self.arrived.add(device_id)
            if self.arrived >= self.expected and self.released_at is None:
                self.released_at = time.time()
                return True
        return False

    @property
    def progress(self) -> float:
        if not self.expected:
            return 1.0
        return len(self.arrived) / len(self.expected)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "barrier",
            "group_id": self.group_id,
            "label": self.label,
            "state": self.state.value,
            "expected": sorted(self.expected),
            "arrived": sorted(self.arrived),
            "missing": sorted(self.expected - self.arrived),
            "progress": round(self.progress, 2),
            "created_at": self.created_at,
            "released_at": self.released_at,
        }


# ── Countdown ───────────────────────────────────────────────────────

class Countdown:
    """
    Synchronized start: counts down from N seconds, then triggers.
    All robots should begin their action at the trigger time.
    """

    def __init__(self, group_id: str, seconds: int = 3, label: str = "Launch"):
        self.id = f"countdown-{group_id}-{int(time.time())}"
        self.group_id = group_id
        self.label = label
        self.total_seconds = seconds
        self.started_at: float | None = None
        self.trigger_at: float | None = None

    def start(self) -> float:
        """Begin the countdown. Returns the trigger timestamp."""
        self.started_at = time.time()
        self.trigger_at = self.started_at + self.total_seconds
        return self.trigger_at

    @property
    def remaining(self) -> float:
        if self.trigger_at is None:
            return float(self.total_seconds)
        r = self.trigger_at - time.time()
        return max(0.0, r)

    @property
    def state(self) -> SyncState:
        if self.started_at is None:
            return SyncState.WAITING
        if time.time() >= self.trigger_at:
            return SyncState.TRIGGERED
        return SyncState.READY  # counting down

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "countdown",
            "group_id": self.group_id,
            "label": self.label,
            "state": self.state.value,
            "total_seconds": self.total_seconds,
            "remaining": round(self.remaining, 1),
            "started_at": self.started_at,
            "trigger_at": self.trigger_at,
        }


# ── Heartbeat ───────────────────────────────────────────────────────

class Heartbeat:
    """
    Monitors liveness of all robots in a group.
    If a robot misses heartbeats beyond the timeout, it's flagged as lost.
    """

    def __init__(self, group_id: str, device_ids: list[str],
                 interval: float = 2.0, timeout: float = 10.0):
        self.group_id = group_id
        self.interval = interval
        self.timeout = timeout
        now = time.time()
        self.last_seen: dict[str, float] = {did: now for did in device_ids}
        self._lock = threading.Lock()

    def pulse(self, device_id: str) -> None:
        """Record a heartbeat from a device."""
        with self._lock:
            self.last_seen[device_id] = time.time()

    def add_device(self, device_id: str) -> None:
        with self._lock:
            self.last_seen[device_id] = time.time()

    def remove_device(self, device_id: str) -> None:
        with self._lock:
            self.last_seen.pop(device_id, None)

    def check(self) -> dict[str, bool]:
        """Return {device_id: is_alive} for all tracked devices."""
        now = time.time()
        with self._lock:
            return {
                did: (now - ts) < self.timeout
                for did, ts in self.last_seen.items()
            }

    def lost_devices(self) -> list[str]:
        """Return list of device IDs that have gone silent."""
        return [did for did, alive in self.check().items() if not alive]

    def to_dict(self) -> dict:
        health = self.check()
        return {
            "type": "heartbeat",
            "group_id": self.group_id,
            "interval": self.interval,
            "timeout": self.timeout,
            "devices": {
                did: {
                    "alive": health[did],
                    "last_seen": self.last_seen.get(did, 0),
                    "age": round(time.time() - self.last_seen.get(did, 0), 1),
                }
                for did in self.last_seen
            },
            "lost": self.lost_devices(),
        }


# ── ReFormation ─────────────────────────────────────────────────────

class ReFormation:
    """
    When a robot disconnects, the remaining robots close the gap
    by recomputing the formation with count - 1.
    """

    def __init__(self, group_id: str):
        self.group_id = group_id
        self.events: list[dict] = []

    def on_device_lost(self, device_id: str, remaining_count: int) -> dict:
        """Record a device loss and signal that reformation is needed."""
        event = {
            "type": "reformation",
            "group_id": self.group_id,
            "lost_device": device_id,
            "remaining_count": remaining_count,
            "timestamp": time.time(),
            "action": "recompute_formation",
        }
        self.events.append(event)
        return event

    def to_dict(self) -> dict:
        return {
            "type": "reformation",
            "group_id": self.group_id,
            "events": self.events[-10:],  # last 10
        }


# ── SyncManager ─────────────────────────────────────────────────────

class SyncManager:
    """
    Process-wide manager for all sync primitives across all groups.
    """

    def __init__(self):
        self.barriers: dict[str, Barrier] = {}
        self.countdowns: dict[str, Countdown] = {}
        self.heartbeats: dict[str, Heartbeat] = {}      # group_id → heartbeat
        self.reformations: dict[str, ReFormation] = {}   # group_id → reformation
        self._lock = threading.Lock()

    # ── barriers ──

    def create_barrier(self, group_id: str, label: str,
                       device_ids: list[str], timeout: float = 60.0) -> Barrier:
        b = Barrier(group_id, label, device_ids, timeout)
        with self._lock:
            self.barriers[b.id] = b
        return b

    def arrive_barrier(self, barrier_id: str, device_id: str) -> dict:
        b = self.barriers.get(barrier_id)
        if b is None:
            return {"ok": False, "error": "barrier not found"}
        released = b.arrive(device_id)
        return {"ok": True, "released": released, **b.to_dict()}

    # ── countdowns ──

    def create_countdown(self, group_id: str, seconds: int = 3,
                         label: str = "Launch") -> Countdown:
        c = Countdown(group_id, seconds, label)
        with self._lock:
            self.countdowns[c.id] = c
        return c

    def start_countdown(self, countdown_id: str) -> dict:
        c = self.countdowns.get(countdown_id)
        if c is None:
            return {"ok": False, "error": "countdown not found"}
        trigger = c.start()
        return {"ok": True, "trigger_at": trigger, **c.to_dict()}

    # ── heartbeats ──

    def ensure_heartbeat(self, group_id: str, device_ids: list[str]) -> Heartbeat:
        if group_id not in self.heartbeats:
            self.heartbeats[group_id] = Heartbeat(group_id, device_ids)
        return self.heartbeats[group_id]

    def pulse(self, group_id: str, device_id: str) -> None:
        hb = self.heartbeats.get(group_id)
        if hb:
            hb.pulse(device_id)

    # ── reformation ──

    def ensure_reformation(self, group_id: str) -> ReFormation:
        if group_id not in self.reformations:
            self.reformations[group_id] = ReFormation(group_id)
        return self.reformations[group_id]

    # ── cleanup ──

    def cleanup_expired(self) -> int:
        """Remove expired barriers and triggered countdowns. Returns count removed."""
        removed = 0
        with self._lock:
            to_remove = [
                bid for bid, b in self.barriers.items()
                if b.state in (SyncState.EXPIRED, SyncState.TRIGGERED)
                and (b.released_at or b.created_at) < time.time() - 300
            ]
            for bid in to_remove:
                del self.barriers[bid]
                removed += 1

            to_remove_c = [
                cid for cid, c in self.countdowns.items()
                if c.state == SyncState.TRIGGERED
                and c.trigger_at < time.time() - 300
            ]
            for cid in to_remove_c:
                del self.countdowns[cid]
                removed += 1
        return removed

    def get_group_sync(self, group_id: str) -> dict:
        """Return all sync state for a group."""
        barriers = [b.to_dict() for b in self.barriers.values() if b.group_id == group_id]
        countdowns = [c.to_dict() for c in self.countdowns.values() if c.group_id == group_id]
        hb = self.heartbeats.get(group_id)
        rf = self.reformations.get(group_id)
        return {
            "barriers": barriers,
            "countdowns": countdowns,
            "heartbeat": hb.to_dict() if hb else None,
            "reformation": rf.to_dict() if rf else None,
        }
