"""
Fleet Task Scheduler — Priority queue for fleet missions and maintenance.
"""

import time
import uuid
import threading
import heapq


class FleetTask:
    """A scheduled fleet task."""

    STATUS_PENDING = "pending"
    STATUS_ASSIGNED = "assigned"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    PRIORITY_LOW = 3
    PRIORITY_NORMAL = 2
    PRIORITY_HIGH = 1
    PRIORITY_CRITICAL = 0

    def __init__(self, name: str, task_type: str, command: str,
                 params: dict = None, priority: int = 2,
                 device_id: str = None, required_capabilities: list = None,
                 scheduled_at: float = None):
        self.id = f"task-{uuid.uuid4().hex[:8]}"
        self.name = name
        self.task_type = task_type  # "mission", "maintenance", "command"
        self.command = command
        self.params = params or {}
        self.priority = priority
        self.device_id = device_id  # None = auto-assign
        self.required_capabilities = required_capabilities or []
        self.status = self.STATUS_PENDING
        self.created_at = time.time()
        self.scheduled_at = scheduled_at or time.time()
        self.started_at = None
        self.completed_at = None
        self.result = None
        self.error = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "task_type": self.task_type,
            "command": self.command,
            "params": self.params,
            "priority": self.priority,
            "priority_label": {0: "critical", 1: "high", 2: "normal", 3: "low"}.get(self.priority, "normal"),
            "device_id": self.device_id,
            "required_capabilities": self.required_capabilities,
            "status": self.status,
            "created_at": self.created_at,
            "scheduled_at": self.scheduled_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.result,
            "error": self.error,
        }

    def __lt__(self, other):
        """Priority queue ordering: lower priority number = higher priority."""
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.scheduled_at < other.scheduled_at


class MaintenanceReminder:
    """A maintenance reminder based on uptime hours."""

    def __init__(self, device_id: str, device_name: str, reason: str,
                 due_at: float = None):
        self.id = f"maint-{uuid.uuid4().hex[:8]}"
        self.device_id = device_id
        self.device_name = device_name
        self.reason = reason
        self.due_at = due_at or time.time()
        self.dismissed = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "reason": self.reason,
            "due_at": self.due_at,
            "dismissed": self.dismissed,
        }


class FleetScheduler:
    """Schedules and manages fleet tasks with priority queue."""

    # Maintenance threshold: every 100 hours of uptime
    MAINTENANCE_INTERVAL_HOURS = 100

    def __init__(self):
        self._lock = threading.Lock()
        self.tasks: dict[str, FleetTask] = {}
        self._queue: list[FleetTask] = []  # Priority heap
        self.maintenance_reminders: list[MaintenanceReminder] = []
        self._uptime_hours: dict[str, float] = {}
        self._last_maintenance: dict[str, float] = {}

    def schedule_task(self, name: str, task_type: str, command: str,
                      params: dict = None, priority: int = 2,
                      device_id: str = None,
                      required_capabilities: list = None,
                      scheduled_at: float = None) -> dict:
        """Schedule a new task."""
        with self._lock:
            task = FleetTask(
                name=name, task_type=task_type, command=command,
                params=params, priority=priority, device_id=device_id,
                required_capabilities=required_capabilities,
                scheduled_at=scheduled_at,
            )
            self.tasks[task.id] = task
            heapq.heappush(self._queue, task)
            return task.to_dict()

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending/assigned task."""
        with self._lock:
            task = self.tasks.get(task_id)
            if not task or task.status not in (FleetTask.STATUS_PENDING, FleetTask.STATUS_ASSIGNED):
                return False
            task.status = FleetTask.STATUS_CANCELLED
            return True

    def assign_task(self, task_id: str, device_id: str) -> dict | None:
        """Manually assign a task to a device."""
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return None
            task.device_id = device_id
            task.status = FleetTask.STATUS_ASSIGNED
            return task.to_dict()

    def start_task(self, task_id: str) -> dict | None:
        """Mark a task as running."""
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return None
            task.status = FleetTask.STATUS_RUNNING
            task.started_at = time.time()
            return task.to_dict()

    def complete_task(self, task_id: str, result: dict = None) -> dict | None:
        """Mark a task as completed."""
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return None
            task.status = FleetTask.STATUS_COMPLETED
            task.completed_at = time.time()
            task.result = result
            return task.to_dict()

    def fail_task(self, task_id: str, error: str = None) -> dict | None:
        """Mark a task as failed."""
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return None
            task.status = FleetTask.STATUS_FAILED
            task.completed_at = time.time()
            task.error = error
            return task.to_dict()

    def auto_assign(self, devices: dict) -> list[dict]:
        """Auto-assign pending tasks to available devices based on capability matching."""
        with self._lock:
            assigned = []
            # Rebuild queue of pending tasks
            pending = [t for t in self._queue
                       if t.status == FleetTask.STATUS_PENDING and t.device_id is None]

            # Find available devices (online, not currently running a task)
            busy_devices = {t.device_id for t in self.tasks.values()
                           if t.status == FleetTask.STATUS_RUNNING and t.device_id}

            for task in sorted(pending):
                for did, dev in devices.items():
                    if did in busy_devices:
                        continue
                    # Check capabilities
                    if task.required_capabilities:
                        caps = (list(dev.get_capabilities().keys())
                                if hasattr(dev, "get_capabilities") else [])
                        if not all(c in caps for c in task.required_capabilities):
                            continue
                    # Assign
                    task.device_id = did
                    task.status = FleetTask.STATUS_ASSIGNED
                    busy_devices.add(did)
                    assigned.append(task.to_dict())
                    break

            return assigned

    def get_task(self, task_id: str) -> dict | None:
        task = self.tasks.get(task_id)
        return task.to_dict() if task else None

    def list_tasks(self, status: str = None, device_id: str = None,
                   limit: int = 50) -> list[dict]:
        """List tasks with optional filtering."""
        tasks = list(self.tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        if device_id:
            tasks = [t for t in tasks if t.device_id == device_id]
        # Sort by priority then scheduled time
        tasks.sort(key=lambda t: (t.priority, t.scheduled_at))
        return [t.to_dict() for t in tasks[:limit]]

    def get_queue_summary(self) -> dict:
        """Get a summary of the task queue state."""
        pending = sum(1 for t in self.tasks.values() if t.status == FleetTask.STATUS_PENDING)
        assigned = sum(1 for t in self.tasks.values() if t.status == FleetTask.STATUS_ASSIGNED)
        running = sum(1 for t in self.tasks.values() if t.status == FleetTask.STATUS_RUNNING)
        completed = sum(1 for t in self.tasks.values() if t.status == FleetTask.STATUS_COMPLETED)
        failed = sum(1 for t in self.tasks.values() if t.status == FleetTask.STATUS_FAILED)

        return {
            "pending": pending,
            "assigned": assigned,
            "running": running,
            "completed": completed,
            "failed": failed,
            "total": len(self.tasks),
        }

    def check_maintenance(self, devices: dict) -> list[dict]:
        """Check if any devices are due for maintenance."""
        reminders = []
        now = time.time()
        for did, dev in devices.items():
            uptime_h = self._uptime_hours.get(did, 0)
            last_maint = self._last_maintenance.get(did, 0)
            hours_since = uptime_h - last_maint

            if hours_since >= self.MAINTENANCE_INTERVAL_HOURS:
                name = getattr(dev, "name", did)
                reminder = MaintenanceReminder(
                    did, name,
                    f"Scheduled maintenance due ({int(hours_since)}h since last)",
                    due_at=now,
                )
                self.maintenance_reminders.append(reminder)
                reminders.append(reminder.to_dict())
                self._last_maintenance[did] = uptime_h

        return reminders

    def update_uptime(self, device_id: str, hours: float):
        """Update tracked uptime hours for a device."""
        self._uptime_hours[device_id] = hours

    def seed_demo_tasks(self, device_ids: list[str]):
        """Seed some demo tasks for the dashboard."""
        import random

        demo_tasks = [
            ("Perimeter Patrol", "mission", "patrol", {"waypoints": 4}, 2),
            ("Battery Check", "maintenance", "diagnostic", {"check": "battery"}, 3),
            ("Inventory Scan", "mission", "scan", {"area": "warehouse-b"}, 2),
            ("Emergency Recall", "command", "return_home", {}, 0),
            ("Calibration Run", "maintenance", "calibrate", {"sensors": ["imu", "gps"]}, 1),
            ("Delivery Route A", "mission", "deliver", {"destination": "office-3"}, 2),
            ("Firmware Update", "maintenance", "ota_update", {"version": "2.1.0"}, 1),
            ("Survey Grid", "mission", "survey", {"grid_size": 10}, 2),
        ]

        for name, ttype, cmd, params, priority in demo_tasks:
            did = random.choice(device_ids) if device_ids else None
            status_choice = random.choice(["pending", "pending", "completed", "running"])
            task = FleetTask(name, ttype, cmd, params, priority, did)
            task.status = status_choice
            if status_choice == "completed":
                task.started_at = time.time() - random.uniform(600, 3600)
                task.completed_at = time.time() - random.uniform(0, 600)
                task.result = {"success": True}
            elif status_choice == "running":
                task.started_at = time.time() - random.uniform(0, 300)
            self.tasks[task.id] = task
