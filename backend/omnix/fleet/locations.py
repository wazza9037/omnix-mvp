"""
Location Manager — Organizes devices by physical location.
"""

import time
import uuid
import threading


class Location:
    """A physical location where devices operate."""

    def __init__(self, name: str, lat: float = 0.0, lng: float = 0.0,
                 address: str = "", description: str = "",
                 map_x: float = 0, map_y: float = 0):
        self.id = f"loc-{uuid.uuid4().hex[:8]}"
        self.name = name
        self.lat = lat
        self.lng = lng
        self.address = address
        self.description = description
        # 2D map position (for the canvas fleet view)
        self.map_x = map_x
        self.map_y = map_y
        self.device_ids: list[str] = []
        self.created_at = time.time()
        self.color = "#00B4D8"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "lat": self.lat,
            "lng": self.lng,
            "address": self.address,
            "description": self.description,
            "map_x": self.map_x,
            "map_y": self.map_y,
            "device_ids": list(self.device_ids),
            "device_count": len(self.device_ids),
            "created_at": self.created_at,
            "color": self.color,
        }


class LocationManager:
    """Manages locations and device-to-location assignment."""

    def __init__(self):
        self._lock = threading.Lock()
        self.locations: dict[str, Location] = {}
        self._device_location: dict[str, str] = {}  # device_id → location_id
        self._seed_demo_locations()

    def _seed_demo_locations(self):
        """Pre-built demo locations."""
        demos = [
            {
                "name": "Lab Alpha",
                "lat": 37.7749, "lng": -122.4194,
                "address": "Building A, Floor 2",
                "description": "Primary robotics R&D lab",
                "map_x": 200, "map_y": 180,
                "color": "#00B4D8",
            },
            {
                "name": "Warehouse B",
                "lat": 37.7850, "lng": -122.4094,
                "address": "South Campus, Warehouse District",
                "description": "Logistics and inventory robots",
                "map_x": 550, "map_y": 150,
                "color": "#f59e0b",
            },
            {
                "name": "Field Test Site",
                "lat": 37.7650, "lng": -122.4294,
                "address": "Outdoor Testing Grounds",
                "description": "Outdoor drone and rover testing area",
                "map_x": 350, "map_y": 380,
                "color": "#10b981",
            },
            {
                "name": "Office Floor 3",
                "lat": 37.7749, "lng": -122.4150,
                "address": "HQ Building, 3rd Floor",
                "description": "Office automation and smart devices",
                "map_x": 700, "map_y": 320,
                "color": "#8b5cf6",
            },
        ]
        for d in demos:
            loc = Location(
                name=d["name"], lat=d["lat"], lng=d["lng"],
                address=d["address"], description=d["description"],
                map_x=d["map_x"], map_y=d["map_y"],
            )
            loc.color = d["color"]
            self.locations[loc.id] = loc

    def list_locations(self) -> list[dict]:
        return [loc.to_dict() for loc in self.locations.values()]

    def get_location(self, location_id: str) -> dict | None:
        loc = self.locations.get(location_id)
        return loc.to_dict() if loc else None

    def create_location(self, name: str, lat: float = 0, lng: float = 0,
                        address: str = "", description: str = "",
                        map_x: float = 0, map_y: float = 0,
                        color: str = "#00B4D8") -> dict:
        """Create a new location."""
        with self._lock:
            loc = Location(name, lat, lng, address, description, map_x, map_y)
            loc.color = color
            self.locations[loc.id] = loc
            return loc.to_dict()

    def update_location(self, location_id: str, **kwargs) -> dict | None:
        """Update an existing location's properties."""
        with self._lock:
            loc = self.locations.get(location_id)
            if not loc:
                return None
            for key in ("name", "lat", "lng", "address", "description",
                        "map_x", "map_y", "color"):
                if key in kwargs:
                    setattr(loc, key, kwargs[key])
            return loc.to_dict()

    def assign_device(self, location_id: str, device_id: str) -> bool:
        """Assign a device to a location (removes from previous)."""
        with self._lock:
            loc = self.locations.get(location_id)
            if not loc:
                return False

            # Remove from previous location
            prev_loc_id = self._device_location.get(device_id)
            if prev_loc_id and prev_loc_id in self.locations:
                prev = self.locations[prev_loc_id]
                if device_id in prev.device_ids:
                    prev.device_ids.remove(device_id)

            # Assign to new
            if device_id not in loc.device_ids:
                loc.device_ids.append(device_id)
            self._device_location[device_id] = location_id
            return True

    def unassign_device(self, device_id: str) -> bool:
        """Remove a device from its current location."""
        with self._lock:
            loc_id = self._device_location.pop(device_id, None)
            if loc_id and loc_id in self.locations:
                loc = self.locations[loc_id]
                if device_id in loc.device_ids:
                    loc.device_ids.remove(device_id)
                return True
            return False

    def get_device_location(self, device_id: str) -> dict | None:
        """Get the location a device is assigned to."""
        loc_id = self._device_location.get(device_id)
        if loc_id and loc_id in self.locations:
            return self.locations[loc_id].to_dict()
        return None

    def get_devices_at_location(self, location_id: str) -> list[str]:
        """Get all device IDs at a location."""
        loc = self.locations.get(location_id)
        return list(loc.device_ids) if loc else []

    def auto_assign_devices(self, devices: dict):
        """Auto-assign devices to demo locations based on type (for initial setup)."""
        with self._lock:
            locs = list(self.locations.values())
            if not locs:
                return

            type_map = {
                "drone": 0,       # Lab Alpha
                "robot_arm": 1,   # Warehouse B
                "rover": 2,       # Field Test Site
                "smart_light": 3, # Office Floor 3
            }

            for did, dev in devices.items():
                if did in self._device_location:
                    continue  # Already assigned
                dtype = getattr(dev, "device_type", "unknown")
                idx = type_map.get(dtype, 0) % len(locs)
                loc = locs[idx]
                if did not in loc.device_ids:
                    loc.device_ids.append(did)
                self._device_location[did] = loc.id
