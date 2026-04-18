"""
OMNIX Sensor Simulator — generates realistic sensor data for demo mode.

Each sensor type has a characteristic data pattern:
  - Temperature: sinusoidal 20-30°C with noise
  - Distance: sonar ping pattern 10-200cm
  - Light: 0-1024 with day/night cycle
  - Humidity: 40-80% slow drift
  - IMU accel: 6-axis with gravity + vibration
  - IMU gyro: angular velocity with drift
  - Voltage: battery discharge curve
  - Pressure: barometric with weather pattern
  - Encoder: incremental ticks
  - Force/torque: load patterns at end effector
  - GPS: lat/lon drift around a point
  - Compass: heading with magnetic deviation
  - Barometer: altitude from pressure
  - Airspeed: pitot tube simulation
"""

import math
import random
import time
from typing import Optional

from omnix.sensors.registry import SensorRegistry


class SensorSimulator:
    """Generates realistic simulated sensor data and pushes to a SensorRegistry."""

    def __init__(self, registry: SensorRegistry):
        self.registry = registry
        self._start_time = time.time()
        # Per-sensor state for stateful simulations
        self._state: dict[str, dict] = {}

    def _get_state(self, key: str, defaults: Optional[dict] = None) -> dict:
        """Get or create per-sensor simulation state."""
        if key not in self._state:
            self._state[key] = defaults or {}
        return self._state[key]

    def tick(self, device_id: str, timestamp: Optional[float] = None):
        """Generate and push one round of readings for all sensors on a device."""
        ts = timestamp or time.time()
        elapsed = ts - self._start_time
        sensors = self.registry.get_device_sensors(device_id)

        for s in sensors:
            sid = s["id"]
            stype = s["sensor_type"]
            rmin = s["range_min"]
            rmax = s["range_max"]
            key = f"{device_id}:{sid}"

            value = self._generate(stype, rmin, rmax, elapsed, key)
            self.registry.push_reading(device_id, sid, value, ts)

    def _generate(self, sensor_type: str, rmin: float, rmax: float,
                  elapsed: float, key: str) -> float:
        """Generate a realistic value for the given sensor type."""
        gen = getattr(self, f"_gen_{sensor_type}", None)
        if gen:
            return gen(rmin, rmax, elapsed, key)
        return self._gen_default(rmin, rmax, elapsed, key)

    # ── Temperature: sinusoidal with noise ─────────────────

    def _gen_temperature(self, rmin, rmax, t, key):
        mid = (rmin + rmax) / 2
        amp = (rmax - rmin) / 4
        # Slow sinusoidal drift + faster noise
        base = mid + amp * math.sin(t * 0.05)
        noise = random.gauss(0, amp * 0.1)
        return max(rmin, min(rmax, base + noise))

    # ── Distance: sonar ping with object movement ──────────

    def _gen_distance(self, rmin, rmax, t, key):
        state = self._get_state(key, {"target": (rmin + rmax) / 2, "next_change": t + 3})
        if t >= state["next_change"]:
            state["target"] = random.uniform(rmin * 1.2, rmax * 0.8)
            state["next_change"] = t + random.uniform(2, 8)
        # Smoothly approach target with noise
        current = state.get("current", state["target"])
        current += (state["target"] - current) * 0.1
        noise = random.gauss(0, 1.5)
        state["current"] = current
        return max(rmin, min(rmax, current + noise))

    # ── Light: day/night cycle ─────────────────────────────

    def _gen_light(self, rmin, rmax, t, key):
        # 60-second day/night cycle for demo
        cycle = (math.sin(t * 0.1) + 1) / 2  # 0..1
        base = rmin + cycle * (rmax - rmin)
        # Occasional cloud shadows
        if random.random() < 0.02:
            state = self._get_state(key, {})
            state["cloud"] = t + random.uniform(1, 3)
        state = self._get_state(key, {})
        if state.get("cloud") and t < state["cloud"]:
            base *= 0.4
        noise = random.gauss(0, (rmax - rmin) * 0.02)
        return max(rmin, min(rmax, base + noise))

    # ── Humidity: slow drift ───────────────────────────────

    def _gen_humidity(self, rmin, rmax, t, key):
        state = self._get_state(key, {"value": (rmin + rmax) / 2})
        # Random walk with mean reversion
        mid = (rmin + rmax) / 2
        drift = random.gauss(0, 0.3)
        reversion = (mid - state["value"]) * 0.01
        state["value"] += drift + reversion
        return max(rmin, min(rmax, state["value"]))

    # ── Pressure: barometric with weather ──────────────────

    def _gen_pressure(self, rmin, rmax, t, key):
        mid = (rmin + rmax) / 2
        # Slow weather pattern
        weather = math.sin(t * 0.02) * (rmax - rmin) * 0.15
        noise = random.gauss(0, 0.5)
        return max(rmin, min(rmax, mid + weather + noise))

    # ── IMU Accelerometer: gravity + vibration ─────────────

    def _gen_imu_accel(self, rmin, rmax, t, key):
        # Gravity component (~9.81) + vibration noise
        state = self._get_state(key, {"axis": random.choice(["x", "y", "z"])})
        axis = state["axis"]
        if axis == "z":
            base = 9.81  # gravity on Z
        else:
            base = 0.0
        vibration = random.gauss(0, 0.3)
        tilt = math.sin(t * 0.3 + hash(key) % 100) * 0.5
        return max(rmin, min(rmax, base + vibration + tilt))

    # ── IMU Gyroscope: angular velocity with drift ─────────

    def _gen_imu_gyro(self, rmin, rmax, t, key):
        state = self._get_state(key, {"drift": 0})
        state["drift"] += random.gauss(0, 0.01)
        state["drift"] *= 0.99  # decay
        noise = random.gauss(0, 2.0)
        movement = math.sin(t * 0.5 + hash(key) % 50) * 5
        return max(rmin, min(rmax, state["drift"] + noise + movement))

    # ── Voltage: battery discharge curve ───────────────────

    def _gen_voltage(self, rmin, rmax, t, key):
        state = self._get_state(key, {"charge": 1.0})
        # Slow discharge with load spikes
        state["charge"] -= 0.0001 + random.uniform(0, 0.0002)
        if state["charge"] < 0.1:
            state["charge"] = 1.0  # Simulate recharge
        # Battery discharge is not linear — cubic curve
        v = rmin + (rmax - rmin) * (state["charge"] ** 0.3)
        noise = random.gauss(0, 0.02)
        return max(rmin, min(rmax, v + noise))

    # ── Current: load pattern ──────────────────────────────

    def _gen_current(self, rmin, rmax, t, key):
        base = (rmin + rmax) / 3
        # Periodic load spikes (motor activity)
        spike = 0
        if math.sin(t * 0.8) > 0.7:
            spike = (rmax - rmin) * 0.4
        noise = random.gauss(0, 0.1)
        return max(rmin, min(rmax, base + spike + noise))

    # ── Gas: ambient with spikes ───────────────────────────

    def _gen_gas(self, rmin, rmax, t, key):
        base = rmin + (rmax - rmin) * 0.1
        # Occasional gas events
        state = self._get_state(key, {"event": 0})
        if random.random() < 0.005:
            state["event"] = t + random.uniform(2, 5)
        if t < state.get("event", 0):
            base += (rmax - rmin) * 0.5 * math.exp(-(state["event"] - t))
        noise = random.gauss(0, (rmax - rmin) * 0.02)
        return max(rmin, min(rmax, base + noise))

    # ── Sound: ambient with events ─────────────────────────

    def _gen_sound(self, rmin, rmax, t, key):
        base = rmin + (rmax - rmin) * 0.3
        # Motor noise correlates with time
        motor = abs(math.sin(t * 1.2)) * (rmax - rmin) * 0.2
        noise = random.gauss(0, 3)
        return max(rmin, min(rmax, base + motor + noise))

    # ── Encoder: incremental ticks ─────────────────────────

    def _gen_encoder(self, rmin, rmax, t, key):
        state = self._get_state(key, {"ticks": 0})
        # Speed varies sinusoidally
        speed = 50 + 40 * math.sin(t * 0.3)
        state["ticks"] += speed * 0.5  # 500ms tick rate equivalent
        if state["ticks"] > rmax:
            state["ticks"] = rmin
        return state["ticks"]

    # ── Force: load at end effector ────────────────────────

    def _gen_force(self, rmin, rmax, t, key):
        state = self._get_state(key, {"gripping": False, "next": t + 5})
        if t >= state["next"]:
            state["gripping"] = not state["gripping"]
            state["next"] = t + random.uniform(3, 8)
        base = 0.5 if not state["gripping"] else (rmax * 0.6)
        noise = random.gauss(0, 0.5)
        return max(rmin, min(rmax, base + noise))

    # ── GPS: lat/lon drift around a point ──────────────────

    def _gen_gps(self, rmin, rmax, t, key):
        state = self._get_state(key, {"base": (rmin + rmax) / 2})
        # Small random walk
        state["base"] += random.gauss(0, 0.00001)
        noise = random.gauss(0, 0.000005)
        return state["base"] + noise

    # ── Compass: heading with magnetic deviation ───────────

    def _gen_compass(self, rmin, rmax, t, key):
        state = self._get_state(key, {"heading": random.uniform(0, 360)})
        # Slow turning + noise
        state["heading"] += random.gauss(0, 0.5)
        state["heading"] %= 360
        deviation = math.sin(t * 0.1) * 3  # magnetic deviation
        return (state["heading"] + deviation) % 360

    # ── Barometer: altitude from pressure ──────────────────

    def _gen_barometer(self, rmin, rmax, t, key):
        state = self._get_state(key, {"alt": (rmin + rmax) / 2})
        # Simulated altitude changes
        target_alt = (rmin + rmax) / 2 + math.sin(t * 0.1) * (rmax - rmin) * 0.3
        state["alt"] += (target_alt - state["alt"]) * 0.05
        noise = random.gauss(0, 0.2)
        return max(rmin, min(rmax, state["alt"] + noise))

    # ── Airspeed: pitot tube ───────────────────────────────

    def _gen_airspeed(self, rmin, rmax, t, key):
        base = (rmin + rmax) / 3
        # Gusts and throttle
        throttle = (math.sin(t * 0.2) + 1) / 2
        speed = base + throttle * (rmax - base) * 0.6
        gust = random.gauss(0, 1.5)
        return max(rmin, min(rmax, speed + gust))

    # ── Line sensor: binary-ish on/off line ────────────────

    def _gen_line_sensor(self, rmin, rmax, t, key):
        # Oscillates between on-line (high) and off-line (low)
        on_line = math.sin(t * 0.8 + hash(key) % 10) > 0
        base = rmax * 0.85 if on_line else rmin + (rmax - rmin) * 0.1
        noise = random.gauss(0, (rmax - rmin) * 0.05)
        return max(rmin, min(rmax, base + noise))

    # ── Color: RGB as packed value ─────────────────────────

    def _gen_color(self, rmin, rmax, t, key):
        r = int(128 + 127 * math.sin(t * 0.3))
        g = int(128 + 127 * math.sin(t * 0.3 + 2.094))
        b = int(128 + 127 * math.sin(t * 0.3 + 4.189))
        return r * 65536 + g * 256 + b

    # ── Default: sinusoidal ────────────────────────────────

    def _gen_default(self, rmin, rmax, t, key):
        mid = (rmin + rmax) / 2
        amp = (rmax - rmin) / 4
        freq = 0.1 + (hash(key) % 100) * 0.002
        return mid + amp * math.sin(t * freq) + random.gauss(0, amp * 0.05)


# ── Template sensor sets ──────────────────────────────────

def register_drone_sensors(registry: SensorRegistry, device_id: str):
    """Register sensor channels for a drone."""
    sensors = [
        ("baro_alt", "Altitude (Baro)", "barometer", 0, 400, "m"),
        ("gps_lat", "GPS Latitude", "gps", -90, 90, "°"),
        ("gps_lon", "GPS Longitude", "gps", -180, 180, "°"),
        ("accel_x", "Accel X", "imu_accel", -20, 20, "m/s²"),
        ("accel_y", "Accel Y", "imu_accel", -20, 20, "m/s²"),
        ("accel_z", "Accel Z", "imu_accel", -20, 20, "m/s²"),
        ("gyro_x", "Gyro X", "imu_gyro", -250, 250, "°/s"),
        ("gyro_y", "Gyro Y", "imu_gyro", -250, 250, "°/s"),
        ("gyro_z", "Gyro Z", "imu_gyro", -250, 250, "°/s"),
        ("batt_v", "Battery Voltage", "voltage", 10.0, 16.8, "V"),
        ("compass", "Compass Heading", "compass", 0, 360, "°"),
        ("airspeed", "Air Speed", "airspeed", 0, 30, "m/s"),
    ]
    for sid, name, stype, rmin, rmax, unit in sensors:
        registry.register(device_id, sid, name, stype, rmin, rmax, unit)


def register_rover_sensors(registry: SensorRegistry, device_id: str):
    """Register sensor channels for a ground rover."""
    sensors = [
        ("us_front", "Ultrasonic Front", "distance", 2, 400, "cm"),
        ("ir_left", "IR Distance Left", "distance", 2, 80, "cm"),
        ("ir_right", "IR Distance Right", "distance", 2, 80, "cm"),
        ("line", "Line Sensor", "line_sensor", 0, 1024, "raw"),
        ("enc_left", "Wheel Encoder L", "encoder", 0, 65535, "ticks"),
        ("enc_right", "Wheel Encoder R", "encoder", 0, 65535, "ticks"),
        ("accel_x", "Accel X", "imu_accel", -16, 16, "m/s²"),
        ("accel_y", "Accel Y", "imu_accel", -16, 16, "m/s²"),
        ("accel_z", "Accel Z", "imu_accel", -16, 16, "m/s²"),
        ("gyro_z", "Gyro Z (Yaw)", "imu_gyro", -250, 250, "°/s"),
        ("batt_v", "Battery", "voltage", 6.0, 12.6, "V"),
    ]
    for sid, name, stype, rmin, rmax, unit in sensors:
        registry.register(device_id, sid, name, stype, rmin, rmax, unit)


def register_arm_sensors(registry: SensorRegistry, device_id: str):
    """Register sensor channels for a robot arm."""
    sensors = [
        ("enc_j0", "Joint 0 Encoder", "encoder", -180, 180, "°"),
        ("enc_j1", "Joint 1 Encoder", "encoder", -180, 180, "°"),
        ("enc_j2", "Joint 2 Encoder", "encoder", -180, 180, "°"),
        ("enc_j3", "Joint 3 Encoder", "encoder", -180, 180, "°"),
        ("enc_j4", "Joint 4 Encoder", "encoder", -180, 180, "°"),
        ("enc_j5", "Joint 5 Encoder", "encoder", -180, 180, "°"),
        ("force_x", "Force X (EE)", "force", -50, 50, "N"),
        ("force_z", "Force Z (EE)", "force", -50, 50, "N"),
        ("torque", "Torque (EE)", "force", -10, 10, "Nm"),
        ("temp_m1", "Motor 1 Temp", "temperature", 20, 80, "°C"),
        ("temp_m2", "Motor 2 Temp", "temperature", 20, 80, "°C"),
        ("temp_m3", "Motor 3 Temp", "temperature", 20, 80, "°C"),
    ]
    for sid, name, stype, rmin, rmax, unit in sensors:
        registry.register(device_id, sid, name, stype, rmin, rmax, unit)


def register_default_sensors(registry: SensorRegistry, device_id: str):
    """Register basic sensor channels (temperature, distance, light) as defaults."""
    sensors = [
        ("temp", "Temperature", "temperature", 15, 45, "°C"),
        ("dist", "Distance", "distance", 2, 400, "cm"),
        ("light", "Ambient Light", "light", 0, 1024, "lux"),
    ]
    for sid, name, stype, rmin, rmax, unit in sensors:
        registry.register(device_id, sid, name, stype, rmin, rmax, unit)


def register_pi_sensors(registry: SensorRegistry, device_id: str):
    """Register sensor channels for a Raspberry Pi."""
    sensors = [
        ("cpu_temp", "CPU Temperature", "temperature", 30, 85, "°C"),
        ("gpio_a0", "GPIO Analog 0", "light", 0, 1024, "raw"),
        ("gpio_a1", "GPIO Analog 1", "custom", 0, 4096, "raw"),
        ("humidity", "Humidity (DHT)", "humidity", 20, 95, "%"),
    ]
    for sid, name, stype, rmin, rmax, unit in sensors:
        registry.register(device_id, sid, name, stype, rmin, rmax, unit)


def auto_register_sensors(registry: SensorRegistry, device_id: str,
                           device_type: str, template_id: Optional[str] = None):
    """Auto-register appropriate sensor channels based on device type or template."""
    # Template-specific registrations
    if template_id in ("quadcopter", "fixed_wing_uav"):
        register_drone_sensors(registry, device_id)
        return
    if template_id in ("two_wheel_rover", "warehouse_agv", "quadruped", "hexapod"):
        register_rover_sensors(registry, device_id)
        return
    if template_id in ("six_dof_arm", "gripper"):
        register_arm_sensors(registry, device_id)
        return
    if template_id == "humanoid":
        register_arm_sensors(registry, device_id)
        register_rover_sensors(registry, device_id)
        return
    if template_id == "rov":
        # ROV gets pressure + depth + IMU
        registry.register(device_id, "depth", "Depth", "pressure", 0, 300, "m")
        registry.register(device_id, "water_temp", "Water Temp", "temperature", 0, 35, "°C")
        registry.register(device_id, "accel_x", "Accel X", "imu_accel", -20, 20, "m/s²")
        registry.register(device_id, "accel_z", "Accel Z", "imu_accel", -20, 20, "m/s²")
        registry.register(device_id, "batt_v", "Battery", "voltage", 10, 50, "V")
        registry.register(device_id, "sonar", "Sonar", "distance", 0, 5000, "cm")
        return

    # Device-type fallbacks
    if device_type == "drone":
        register_drone_sensors(registry, device_id)
    elif device_type in ("ground_robot", "legged"):
        register_rover_sensors(registry, device_id)
    elif device_type == "robot_arm":
        register_arm_sensors(registry, device_id)
    else:
        register_default_sensors(registry, device_id)
