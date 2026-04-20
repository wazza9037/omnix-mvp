"""
OMNIX Environment Physics — per-environment physical properties.

Each environment specifies gravity, air/water resistance, surface friction,
optional wind zones, and lighting/atmosphere settings that affect both
simulation accuracy and visual rendering.
"""

from typing import Dict, List, Any, Optional


class WindZone:
    """A regional wind effect within an environment."""

    def __init__(
        self,
        *,
        position: List[float] = None,
        size: List[float] = None,
        direction: List[float] = None,
        strength: float = 1.0,
        turbulence: float = 0.0,
    ):
        self.position = position or [0, 0, 0]
        self.size = size or [10, 10, 10]
        self.direction = direction or [1, 0, 0]
        self.strength = strength
        self.turbulence = turbulence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "position": self.position,
            "size": self.size,
            "direction": self.direction,
            "strength": self.strength,
            "turbulence": self.turbulence,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "WindZone":
        return cls(**data)


class SurfaceZone:
    """A region with specific surface friction properties."""

    def __init__(
        self,
        *,
        position: List[float] = None,
        size: List[float] = None,
        friction: float = 0.7,
        surface_type: str = "concrete",
    ):
        self.position = position or [0, 0, 0]
        self.size = size or [10, 0.01, 10]
        self.friction = friction
        self.surface_type = surface_type

    def to_dict(self) -> Dict[str, Any]:
        return {
            "position": self.position,
            "size": self.size,
            "friction": self.friction,
            "surface_type": self.surface_type,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "SurfaceZone":
        return cls(**data)


# Pre-set surface friction values by type
SURFACE_FRICTION = {
    "concrete": 0.7,
    "carpet": 0.85,
    "grass": 0.55,
    "sand": 0.45,
    "ice": 0.1,
    "metal": 0.6,
    "wood": 0.65,
    "gravel": 0.5,
    "mars_regolith": 0.4,
    "underwater_sand": 0.3,
}


class EnvironmentPhysics:
    """Physics configuration for a simulation environment."""

    def __init__(
        self,
        *,
        gravity: float = 9.81,
        air_resistance: float = 0.01,
        water_resistance: float = 0.0,
        buoyancy: float = 0.0,
        default_surface_friction: float = 0.7,
        surface_type: str = "concrete",
        wind_zones: List[WindZone] = None,
        surface_zones: List[SurfaceZone] = None,
        temperature: float = 20.0,
        visibility: float = 100.0,
    ):
        self.gravity = gravity
        self.air_resistance = air_resistance
        self.water_resistance = water_resistance
        self.buoyancy = buoyancy
        self.default_surface_friction = default_surface_friction
        self.surface_type = surface_type
        self.wind_zones = wind_zones or []
        self.surface_zones = surface_zones or []
        self.temperature = temperature
        self.visibility = visibility

    def get_friction_at(self, x: float, z: float) -> float:
        """Get surface friction at a world position, checking surface zones first."""
        for zone in self.surface_zones:
            zx, _, zz = zone.position
            sx, _, sz = zone.size
            if (zx - sx / 2 <= x <= zx + sx / 2 and
                zz - sz / 2 <= z <= zz + sz / 2):
                return zone.friction
        return self.default_surface_friction

    def get_wind_at(self, x: float, y: float, z: float) -> List[float]:
        """Get wind vector at a position (sum of overlapping wind zones)."""
        wind = [0.0, 0.0, 0.0]
        for wz in self.wind_zones:
            wx, wy, wz_pos = wz.position
            sx, sy, sz = wz.size
            if (wx - sx / 2 <= x <= wx + sx / 2 and
                wy - sy / 2 <= y <= wy + sy / 2 and
                wz_pos - sz / 2 <= z <= wz_pos + sz / 2):
                wind[0] += wz.direction[0] * wz.strength
                wind[1] += wz.direction[1] * wz.strength
                wind[2] += wz.direction[2] * wz.strength
        return wind

    def get_effective_gravity(self) -> float:
        """Returns net downward acceleration accounting for buoyancy."""
        return max(0, self.gravity - self.buoyancy)

    def get_drag_coefficient(self) -> float:
        """Combined drag from air and water resistance."""
        return self.air_resistance + self.water_resistance

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gravity": self.gravity,
            "air_resistance": self.air_resistance,
            "water_resistance": self.water_resistance,
            "buoyancy": self.buoyancy,
            "default_surface_friction": self.default_surface_friction,
            "surface_type": self.surface_type,
            "wind_zones": [wz.to_dict() for wz in self.wind_zones],
            "surface_zones": [sz.to_dict() for sz in self.surface_zones],
            "temperature": self.temperature,
            "visibility": self.visibility,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "EnvironmentPhysics":
        wind_zones = [WindZone.from_dict(w) for w in data.get("wind_zones", [])]
        surface_zones = [SurfaceZone.from_dict(s) for s in data.get("surface_zones", [])]
        return cls(
            gravity=data.get("gravity", 9.81),
            air_resistance=data.get("air_resistance", 0.01),
            water_resistance=data.get("water_resistance", 0.0),
            buoyancy=data.get("buoyancy", 0.0),
            default_surface_friction=data.get("default_surface_friction", 0.7),
            surface_type=data.get("surface_type", "concrete"),
            wind_zones=wind_zones,
            surface_zones=surface_zones,
            temperature=data.get("temperature", 20.0),
            visibility=data.get("visibility", 100.0),
        )


# ── Pre-built physics configurations ──

EARTH_INDOOR = EnvironmentPhysics(
    gravity=9.81, air_resistance=0.005, surface_type="concrete",
    default_surface_friction=0.7, temperature=22.0, visibility=50.0,
)

EARTH_OUTDOOR = EnvironmentPhysics(
    gravity=9.81, air_resistance=0.015, surface_type="grass",
    default_surface_friction=0.55, temperature=18.0, visibility=200.0,
    wind_zones=[WindZone(position=[0, 5, 0], size=[100, 20, 100],
                         direction=[0.7, 0, 0.3], strength=2.5, turbulence=0.4)],
)

MARS_SURFACE = EnvironmentPhysics(
    gravity=3.721, air_resistance=0.001, surface_type="mars_regolith",
    default_surface_friction=0.4, temperature=-60.0, visibility=80.0,
    wind_zones=[WindZone(position=[0, 3, 0], size=[100, 10, 100],
                         direction=[1, 0, 0.2], strength=0.8, turbulence=0.6)],
)

UNDERWATER = EnvironmentPhysics(
    gravity=9.81, air_resistance=0.0, water_resistance=0.35,
    buoyancy=7.5, surface_type="underwater_sand",
    default_surface_friction=0.3, temperature=12.0, visibility=15.0,
)

FACTORY = EnvironmentPhysics(
    gravity=9.81, air_resistance=0.005, surface_type="concrete",
    default_surface_friction=0.7, temperature=25.0, visibility=40.0,
)

URBAN = EnvironmentPhysics(
    gravity=9.81, air_resistance=0.01, surface_type="concrete",
    default_surface_friction=0.7, temperature=20.0, visibility=150.0,
)

LAB = EnvironmentPhysics(
    gravity=9.81, air_resistance=0.003, surface_type="concrete",
    default_surface_friction=0.75, temperature=21.0, visibility=30.0,
)
