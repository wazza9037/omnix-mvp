"""
OMNIX MAVLink Connector — Tier 2 (open protocol).

MAVLink is the dominant open protocol for small UAVs / UGVs / USVs:
  - ArduPilot (Copter / Plane / Rover / Sub)
  - PX4 Autopilot (Holybro Pixhawk / Kakute / etc.)
  - Parrot, Hex, Kakute, CUAV, ModalAI…

Real transport options:
  - udp:   udpin:0.0.0.0:14540   (SITL, most PX4 setups)
  - udp:   udpout:192.168.4.1:14550
  - tcp:   tcp:127.0.0.1:5760    (ArduPilot SITL)
  - serial: /dev/ttyUSB0:57600   (telemetry radio)

Requires `pymavlink` for real hardware.  Ships with a complete simulated
MAVLink endpoint so the UI can be developed and demoed with no drone.
"""

import math
import random
import threading
import time

from devices.base import DeviceCapability
from connectors.base import (
    ConnectorBase, ConnectorMeta, ConnectorDevice,
    ConfigField, SimulatedBackendMixin,
)

try:
    from pymavlink import mavutil  # type: ignore
    _HAS_MAVLINK = True
except ImportError:
    _HAS_MAVLINK = False


# ───────────────────────────────────────────────────────────
#  Simulated MAVLink vehicle
# ───────────────────────────────────────────────────────────

class _SimMavlink:
    """A pretend PX4 quadcopter that tracks position, attitude, battery.

    Mimics the subset of MAVLink state that the OMNIX dashboard consumes,
    so the rest of the pipeline behaves identically to a real vehicle.
    """

    def __init__(self, frame_type: str = "quad"):
        self.frame_type = frame_type
        self.boot = time.time()
        self.armed = False
        self.mode = "STABILIZE"
        self.battery_v = 16.6
        self.battery_pct = 100.0
        self.lat = 37.7749        # SF by default
        self.lon = -122.4194
        self.rel_alt = 0.0
        self.home_alt = 20.0
        # NED velocity (m/s)
        self.vn = self.ve = self.vd = 0.0
        # Attitude (rad)
        self.roll = self.pitch = 0.0
        self.yaw = 0.0
        # Target setpoint
        self._target = None
        self._target_speed = 3.0

    def arm(self, armed: bool):
        self.armed = armed
        return True

    def set_mode(self, mode: str):
        self.mode = mode

    def takeoff(self, alt: float):
        self.armed = True
        self.mode = "GUIDED"
        self._target = (self.lat, self.lon, float(alt))

    def land(self):
        self.mode = "LAND"
        self._target = (self.lat, self.lon, 0.0)

    def rtl(self):
        self.mode = "RTL"
        self._target = (self.lat, self.lon, 20.0)

    def goto(self, lat: float, lon: float, alt: float):
        self.mode = "GUIDED"
        self._target = (float(lat), float(lon), float(alt))

    def move_ned(self, dn: float, de: float, dd: float):
        """Offset position by (north, east, down) meters."""
        # 1° lat ≈ 111km; lon scales by cos(lat)
        dlat = dn / 111000.0
        dlon = de / (111000.0 * max(0.01, math.cos(math.radians(self.lat))))
        new_lat = self.lat + dlat
        new_lon = self.lon + dlon
        new_alt = max(0.0, self.rel_alt - dd)
        self.goto(new_lat, new_lon, new_alt)

    def tick(self, dt: float = 0.5):
        # Step toward target if any
        if self._target is not None:
            tlat, tlon, talt = self._target
            # Horizontal distance (m)
            dlat = (tlat - self.lat) * 111000.0
            dlon = (tlon - self.lon) * 111000.0 * max(0.01, math.cos(math.radians(self.lat)))
            dalt = talt - self.rel_alt
            horiz = math.hypot(dlat, dlon)
            step = self._target_speed * dt
            if horiz > step:
                frac = step / horiz
                self.lat += (tlat - self.lat) * frac
                self.lon += (tlon - self.lon) * frac
            else:
                self.lat, self.lon = tlat, tlon
            if abs(dalt) > step:
                self.rel_alt += step * (1 if dalt > 0 else -1)
            else:
                self.rel_alt = talt
            # Velocities derived from movement
            self.vn = (tlat - self.lat) * 111000.0 / dt
            self.ve = (tlon - self.lon) * 111000.0 / dt
            self.vd = -(talt - self.rel_alt) / dt
            # Heading points toward target
            if horiz > 0.5:
                self.yaw = math.atan2(dlon, dlat)
            # Auto-disarm on land
            if self.mode == "LAND" and self.rel_alt <= 0.05:
                self.armed = False
                self._target = None
                self.mode = "STABILIZE"

        # Battery drain proportional to activity
        if self.armed:
            drain = 0.02 + abs(self.vd) * 0.005 + math.hypot(self.vn, self.ve) * 0.002
            self.battery_pct = max(0.0, self.battery_pct - drain)
            self.battery_v = 15.0 + (self.battery_pct / 100.0) * 1.8
        # Small attitude jitter
        self.roll = math.sin(time.time()) * 0.05
        self.pitch = math.cos(time.time() * 1.3) * 0.05

    def telemetry(self) -> dict:
        return {
            "armed": self.armed, "mode": self.mode,
            "battery_v": round(self.battery_v, 2),
            "battery_pct": round(self.battery_pct, 1),
            "gps": {"lat": round(self.lat, 6), "lon": round(self.lon, 6)},
            "altitude_rel_m": round(self.rel_alt, 2),
            "altitude_msl_m": round(self.home_alt + self.rel_alt, 2),
            "attitude": {"roll_deg": round(math.degrees(self.roll), 2),
                         "pitch_deg": round(math.degrees(self.pitch), 2),
                         "yaw_deg": round(math.degrees(self.yaw) % 360, 2)},
            "velocity_ned": {"vn": round(self.vn, 2), "ve": round(self.ve, 2), "vd": round(self.vd, 2)},
            "uptime_s": int(time.time() - self.boot),
            "simulated": True,
        }


# ───────────────────────────────────────────────────────────
#  MAVLink connector (real + simulated)
# ───────────────────────────────────────────────────────────

class MavlinkConnector(SimulatedBackendMixin, ConnectorBase):
    """Tier 2 — PX4 / ArduPilot drones / rovers / subs / planes via MAVLink."""

    meta = ConnectorMeta(
        connector_id="mavlink",
        display_name="MAVLink (PX4 / ArduPilot)",
        tier=2,
        description="Any MAVLink-speaking vehicle: PX4, ArduPilot Copter/Plane/Rover/Sub. Serial, UDP, or TCP.",
        vpe_categories=["drone", "marine", "ground_robot", "extreme"],
        required_packages=["pymavlink"],
        supports_simulation=True,
        icon="🛩️",
        vendor="MAVLink Developer Working Group",
        docs_url="https://mavlink.io/",
        config_schema=[
            ConfigField(
                key="name", label="Display name", type="text",
                default="MAVLink Drone", placeholder="Pixhawk Copter",
            ),
            ConfigField(
                key="frame_type", label="Frame type", type="select",
                default="quad", options=["quad", "hex", "oct", "plane", "rover", "sub"],
                help="Used for the 3D model + which capabilities to expose.",
            ),
            ConfigField(
                key="mode", label="Mode", type="select",
                default="simulate", options=["simulate", "real"],
                help="'simulate' runs a local MAVLink vehicle model. 'real' requires pymavlink + a link string.",
            ),
            ConfigField(
                key="link", label="Connection string", type="text",
                default="udpin:0.0.0.0:14540",
                placeholder="udpin:0.0.0.0:14540 | tcp:127.0.0.1:5760 | /dev/ttyUSB0:57600",
                help="pymavlink-style URL. Most PX4 SITL setups: udpin:0.0.0.0:14540",
            ),
            ConfigField(
                key="source_system", label="Source system id", type="number",
                default=255,
            ),
        ],
        setup_steps=[
            "Install pymavlink on the OMNIX host: `pip install pymavlink`.",
            "Ensure your vehicle is streaming MAVLink — PX4 / ArduPilot are configured this way by default.",
            "Common links: PX4 SITL → udpin:0.0.0.0:14540, ArduPilot SITL → tcp:127.0.0.1:5760, telemetry radio → /dev/ttyUSB0:57600.",
            "Pick 'real' mode, fill in the connection string, click Connect.",
            "Takeoff via Movement presets; watch position, battery, mode in telemetry.",
            "No hardware? Keep mode on 'simulate' to develop against a virtual vehicle.",
        ],
    )

    def connect(self) -> bool:
        name = self.config.get("name", "MAVLink Drone")
        frame = self.config.get("frame_type", "quad")
        mode = self.config.get("mode", "simulate")
        self._tele: dict = {"status": "connecting"}
        self._tele_lock = threading.Lock()
        self._stop = threading.Event()

        device_type = {
            "quad": "drone", "hex": "drone", "oct": "drone", "plane": "drone",
            "rover": "ground_robot", "sub": "marine",
        }.get(frame, "drone")

        caps = self._capabilities_for(frame)

        if mode == "simulate":
            self._use_simulation = True
            self._sim = _SimMavlink(frame)
            self._update_tele()
        else:
            if not _HAS_MAVLINK:
                self._mark_connected(False,
                    "pymavlink not installed. Run `pip install pymavlink` and retry, "
                    "or use simulate mode.")
                return False
            link = self.config.get("link", "udpin:0.0.0.0:14540")
            try:
                self._mav = mavutil.mavlink_connection(
                    link, source_system=int(self.config.get("source_system", 255))
                )
                # Wait for heartbeat
                hb = self._mav.wait_heartbeat(timeout=5)
                if hb is None:
                    self._mark_connected(False,
                        f"No heartbeat from {link}. Is the vehicle running and the link correct?")
                    return False
            except Exception as e:
                self._mark_connected(False, f"MAVLink connect failed: {e}")
                return False
            self._use_simulation = False
            self._reader = threading.Thread(
                target=self._real_reader_loop, daemon=True, name="mav-reader")
            self._reader.start()

        def handler(c, p): return self._run_command(c, p)
        def tele():
            with self._tele_lock:
                return dict(self._tele)

        dev = ConnectorDevice(
            name=name, device_type=device_type, capabilities=caps,
            command_handler=handler, telemetry_provider=tele,
            source_connector=self,
        )
        self._devices.append(dev)
        self._mark_connected(True)
        return True

    def disconnect(self):
        self._stop.set()
        if not self._use_simulation and hasattr(self, "_mav"):
            try: self._mav.close()
            except Exception as e:
                # MAVLink close may fail if already disconnected; silently ignore
                pass
        self._devices.clear()
        self._mark_connected(False)

    def tick(self):
        if self._use_simulation:
            self._sim.tick(dt=0.5)
            self._update_tele()

    def _update_tele(self):
        with self._tele_lock:
            self._tele = self._sim.telemetry()

    # ── Capability set per frame ───────────────────────────

    def _capabilities_for(self, frame: str):
        common = [
            DeviceCapability("arm", "Arm motors", {"arm": {"type": "bool", "default": True}}, "safety"),
            DeviceCapability("set_mode", "Change flight mode",
                {"mode": {"type": "select", "options": ["STABILIZE", "GUIDED", "LOITER", "RTL", "LAND", "AUTO", "MANUAL"]}},
                "mode"),
            DeviceCapability("emergency_stop", "Kill switch", {}, "safety"),
        ]
        if frame in ("quad", "hex", "oct"):
            return common + [
                DeviceCapability("takeoff", "Takeoff to altitude",
                    {"altitude_m": {"type": "number", "min": 2, "max": 120, "default": 10}},
                    "flight"),
                DeviceCapability("land", "Land at current location", {}, "flight"),
                DeviceCapability("return_home", "RTL", {}, "flight"),
                DeviceCapability("goto", "Go to lat/lon/alt",
                    {"lat": {"type": "number"}, "lon": {"type": "number"},
                     "altitude_m": {"type": "number", "min": 2, "max": 120, "default": 15}},
                    "movement"),
                DeviceCapability("move_offset", "Move NED meters",
                    {"north_m": {"type": "number", "default": 0},
                     "east_m": {"type": "number", "default": 0},
                     "down_m": {"type": "number", "default": 0}},
                    "movement"),
            ]
        if frame == "plane":
            return common + [
                DeviceCapability("goto", "Go to waypoint",
                    {"lat": {"type": "number"}, "lon": {"type": "number"},
                     "altitude_m": {"type": "number", "min": 30, "max": 400, "default": 80}},
                    "movement"),
                DeviceCapability("return_home", "RTL", {}, "flight"),
            ]
        if frame == "rover":
            return common + [
                DeviceCapability("goto", "Drive to lat/lon",
                    {"lat": {"type": "number"}, "lon": {"type": "number"}},
                    "movement"),
            ]
        if frame == "sub":
            return common + [
                DeviceCapability("dive", "Descend to depth",
                    {"depth_m": {"type": "number", "min": 0, "max": 100, "default": 5}},
                    "movement"),
                DeviceCapability("surface", "Return to surface", {}, "movement"),
            ]
        return common

    # ── Command execution ──────────────────────────────────

    def _run_command(self, cmd: str, params: dict) -> dict:
        p = params or {}
        if self._use_simulation:
            if cmd == "arm":
                self._sim.arm(bool(p.get("arm", True)))
                return {"success": True, "message": "armed" if self._sim.armed else "disarmed"}
            if cmd == "set_mode":
                self._sim.set_mode(p.get("mode", "STABILIZE"))
                return {"success": True, "message": f"mode → {self._sim.mode}"}
            if cmd == "takeoff":
                self._sim.takeoff(float(p.get("altitude_m", 10)))
                return {"success": True, "message": f"takeoff to {p.get('altitude_m', 10)}m"}
            if cmd == "land":
                self._sim.land()
                return {"success": True, "message": "landing"}
            if cmd == "return_home":
                self._sim.rtl()
                return {"success": True, "message": "RTL"}
            if cmd == "goto":
                self._sim.goto(p.get("lat", self._sim.lat), p.get("lon", self._sim.lon),
                               float(p.get("altitude_m", 15)))
                return {"success": True, "message": "goto engaged"}
            if cmd == "move_offset":
                self._sim.move_ned(float(p.get("north_m", 0)),
                                   float(p.get("east_m", 0)),
                                   float(p.get("down_m", 0)))
                return {"success": True, "message": "offset applied"}
            if cmd == "dive":
                self._sim.rel_alt = -float(p.get("depth_m", 5))
                return {"success": True, "message": "diving"}
            if cmd == "surface":
                self._sim.rel_alt = 0
                return {"success": True, "message": "surfacing"}
            if cmd == "emergency_stop":
                self._sim.armed = False
                self._sim._target = None
                return {"success": True, "message": "disarmed"}
            return {"success": False, "message": f"unknown command {cmd}"}

        # Real MAVLink
        m = self._mav
        try:
            if cmd == "arm":
                arm = bool(p.get("arm", True))
                m.mav.command_long_send(
                    m.target_system, m.target_component,
                    mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                    0, 1 if arm else 0, 0, 0, 0, 0, 0, 0,
                )
                return {"success": True, "message": "armed" if arm else "disarmed"}
            if cmd == "set_mode":
                mode = p.get("mode", "STABILIZE")
                mid = m.mode_mapping().get(mode)
                if mid is None:
                    return {"success": False, "message": f"Unknown mode {mode}"}
                m.set_mode(mid)
                return {"success": True, "message": f"mode → {mode}"}
            if cmd == "takeoff":
                alt = float(p.get("altitude_m", 10))
                m.mav.command_long_send(
                    m.target_system, m.target_component,
                    mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                    0, 0, 0, 0, 0, 0, 0, alt,
                )
                return {"success": True, "message": f"takeoff {alt}m"}
            if cmd == "land":
                m.mav.command_long_send(
                    m.target_system, m.target_component,
                    mavutil.mavlink.MAV_CMD_NAV_LAND,
                    0, 0, 0, 0, 0, 0, 0, 0,
                )
                return {"success": True, "message": "land"}
            if cmd == "return_home":
                m.mav.command_long_send(
                    m.target_system, m.target_component,
                    mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH,
                    0, 0, 0, 0, 0, 0, 0, 0,
                )
                return {"success": True, "message": "RTL"}
            if cmd == "goto":
                lat = float(p.get("lat", 0))
                lon = float(p.get("lon", 0))
                alt = float(p.get("altitude_m", 15))
                m.mav.set_position_target_global_int_send(
                    0, m.target_system, m.target_component,
                    mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
                    0b0000111111111000,
                    int(lat * 1e7), int(lon * 1e7), alt,
                    0, 0, 0, 0, 0, 0, 0, 0,
                )
                return {"success": True, "message": "goto"}
            if cmd == "emergency_stop":
                m.mav.command_long_send(
                    m.target_system, m.target_component,
                    mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                    0, 0, 0, 0, 0, 0, 0, 0,
                )
                return {"success": True, "message": "disarmed"}
            return {"success": False, "message": f"unsupported command {cmd}"}
        except Exception as e:
            return {"success": False, "message": f"mavlink error: {e}"}

    def _real_reader_loop(self):
        # Pull messages; update self._tele with whatever we recognize.
        m = self._mav
        state = {"battery_pct": 100.0, "battery_v": 16.0,
                 "lat": 0, "lon": 0, "rel_alt": 0,
                 "attitude": {}, "vn": 0, "ve": 0, "vd": 0,
                 "mode": "?", "armed": False}
        while not self._stop.is_set():
            try:
                msg = m.recv_match(blocking=True, timeout=1)
            except Exception:
                continue
            if msg is None:
                continue
            t = msg.get_type()
            if t == "HEARTBEAT":
                state["armed"] = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                mm = m.mode_mapping()
                rev = {v: k for k, v in mm.items()} if mm else {}
                state["mode"] = rev.get(msg.custom_mode, str(msg.custom_mode))
            elif t == "GLOBAL_POSITION_INT":
                state["lat"] = msg.lat / 1e7
                state["lon"] = msg.lon / 1e7
                state["rel_alt"] = msg.relative_alt / 1000.0
                state["vn"] = msg.vx / 100.0
                state["ve"] = msg.vy / 100.0
                state["vd"] = msg.vz / 100.0
            elif t == "ATTITUDE":
                state["attitude"] = {
                    "roll_deg": math.degrees(msg.roll),
                    "pitch_deg": math.degrees(msg.pitch),
                    "yaw_deg": math.degrees(msg.yaw) % 360,
                }
            elif t == "SYS_STATUS":
                if msg.battery_remaining >= 0:
                    state["battery_pct"] = float(msg.battery_remaining)
                if msg.voltage_battery > 0:
                    state["battery_v"] = msg.voltage_battery / 1000.0
            # Publish snapshot
            with self._tele_lock:
                self._tele = {
                    "armed": state["armed"], "mode": state["mode"],
                    "battery_v": round(state["battery_v"], 2),
                    "battery_pct": round(state["battery_pct"], 1),
                    "gps": {"lat": round(state["lat"], 6), "lon": round(state["lon"], 6)},
                    "altitude_rel_m": round(state["rel_alt"], 2),
                    "attitude": state["attitude"],
                    "velocity_ned": {"vn": round(state["vn"], 2),
                                     "ve": round(state["ve"], 2),
                                     "vd": round(state["vd"], 2)},
                    "_ts": time.time(),
                }
