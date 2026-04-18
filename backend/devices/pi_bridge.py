"""
OMNIX Raspberry Pi Bridge — Connect real hardware to OMNIX.

This module provides:
  1. PiGPIOController — read/write GPIO pins (motors, LEDs, relays, servos)
  2. PiCameraFeed    — stream camera frames (for VPE analysis)
  3. PiSensorReader  — read common sensors (distance, temp, IMU)
  4. PiDevice        — full OmnixDevice implementation for any Pi-based robot

Architecture:
  Pi running pi_agent.py  ──HTTP──>  OMNIX server (server_simple.py)
       ↑ GPIO/I2C/SPI                      ↓
    motors, sensors                  Dashboard / Motion 3D

Two modes:
  A) Local mode  — Pi runs OMNIX server + controls hardware directly
  B) Remote mode — Pi runs pi_agent.py → connects to OMNIX server on another machine

GPIO access uses RPi.GPIO when available, falls back to simulation mode
so you can develop/test without actual Pi hardware.
"""

import time
import threading
import json
from .base import OmnixDevice, DeviceCapability

# ── GPIO Abstraction (real or simulated) ──

_GPIO_AVAILABLE = False
_gpio = None

try:
    import RPi.GPIO as GPIO
    _GPIO_AVAILABLE = True
    _gpio = GPIO
except ImportError:
    pass


class SimulatedGPIO:
    """Drop-in replacement when RPi.GPIO isn't available."""
    BCM = "BCM"
    BOARD = "BOARD"
    OUT = "OUT"
    IN = "IN"
    HIGH = 1
    LOW = 0
    PUD_UP = "PUD_UP"
    PUD_DOWN = "PUD_DOWN"

    _pins = {}
    _mode = None

    @classmethod
    def setmode(cls, mode):
        cls._mode = mode

    @classmethod
    def setup(cls, pin, direction, pull_up_down=None):
        cls._pins[pin] = {"direction": direction, "value": 0, "pwm": None}

    @classmethod
    def output(cls, pin, value):
        if pin in cls._pins:
            cls._pins[pin]["value"] = value

    @classmethod
    def input(cls, pin):
        return cls._pins.get(pin, {}).get("value", 0)

    @classmethod
    def cleanup(cls):
        cls._pins.clear()

    @classmethod
    def setwarnings(cls, flag):
        pass


class SimulatedPWM:
    def __init__(self, pin, freq):
        self.pin = pin
        self.freq = freq
        self.duty = 0
        self.running = False

    def start(self, duty):
        self.duty = duty
        self.running = True

    def ChangeDutyCycle(self, duty):
        self.duty = duty

    def ChangeFrequency(self, freq):
        self.freq = freq

    def stop(self):
        self.running = False


if not _GPIO_AVAILABLE:
    _gpio = SimulatedGPIO


# ═══════════════════════════════════════════
#  GPIO CONTROLLER
# ═══════════════════════════════════════════

class PiGPIOController:
    """
    High-level GPIO controller for motors, LEDs, servos, and relays.

    Usage:
        gpio = PiGPIOController()
        gpio.setup_motor("left", forward_pin=17, backward_pin=27, pwm_pin=22)
        gpio.setup_motor("right", forward_pin=23, backward_pin=24, pwm_pin=25)
        gpio.set_motor("left", speed=0.8, direction="forward")
        gpio.setup_servo("pan", pin=18, min_angle=0, max_angle=180)
        gpio.set_servo("pan", angle=90)
    """

    def __init__(self, mode="BCM"):
        self.is_real = _GPIO_AVAILABLE
        self.motors = {}
        self.servos = {}
        self.leds = {}
        self.relays = {}
        self._pwm_objects = {}

        _gpio.setwarnings(False)
        _gpio.setmode(_gpio.BCM if mode == "BCM" else _gpio.BOARD)

    def setup_motor(self, name: str, forward_pin: int, backward_pin: int,
                    pwm_pin: int = None, pwm_freq: int = 1000):
        """Configure a DC motor with direction + optional PWM speed control."""
        _gpio.setup(forward_pin, _gpio.OUT)
        _gpio.setup(backward_pin, _gpio.OUT)

        motor = {
            "forward_pin": forward_pin,
            "backward_pin": backward_pin,
            "pwm_pin": pwm_pin,
            "speed": 0,
            "direction": "stopped",
        }

        if pwm_pin:
            _gpio.setup(pwm_pin, _gpio.OUT)
            if self.is_real:
                pwm = _gpio.PWM(pwm_pin, pwm_freq)
            else:
                pwm = SimulatedPWM(pwm_pin, pwm_freq)
            pwm.start(0)
            self._pwm_objects[name] = pwm

        self.motors[name] = motor

    def set_motor(self, name: str, speed: float = 0, direction: str = "forward"):
        """
        Set motor speed and direction.
        speed: 0.0 to 1.0
        direction: "forward", "backward", "stopped"
        """
        if name not in self.motors:
            return False

        motor = self.motors[name]
        speed = max(0, min(1, speed))

        if direction == "forward":
            _gpio.output(motor["forward_pin"], _gpio.HIGH)
            _gpio.output(motor["backward_pin"], _gpio.LOW)
        elif direction == "backward":
            _gpio.output(motor["forward_pin"], _gpio.LOW)
            _gpio.output(motor["backward_pin"], _gpio.HIGH)
        else:
            _gpio.output(motor["forward_pin"], _gpio.LOW)
            _gpio.output(motor["backward_pin"], _gpio.LOW)
            speed = 0

        if name in self._pwm_objects:
            self._pwm_objects[name].ChangeDutyCycle(speed * 100)

        motor["speed"] = speed
        motor["direction"] = direction
        return True

    def setup_servo(self, name: str, pin: int, min_angle: int = 0,
                    max_angle: int = 180, freq: int = 50):
        """Configure a servo motor."""
        _gpio.setup(pin, _gpio.OUT)
        if self.is_real:
            pwm = _gpio.PWM(pin, freq)
        else:
            pwm = SimulatedPWM(pin, freq)
        pwm.start(0)
        self._pwm_objects[f"servo_{name}"] = pwm
        self.servos[name] = {
            "pin": pin, "min_angle": min_angle, "max_angle": max_angle,
            "current_angle": 90, "freq": freq,
        }

    def set_servo(self, name: str, angle: float):
        """Set servo to specific angle."""
        if name not in self.servos:
            return False
        servo = self.servos[name]
        angle = max(servo["min_angle"], min(servo["max_angle"], angle))
        # Map angle to duty cycle (typically 2.5% to 12.5% for 0-180 degrees)
        duty = 2.5 + (angle / 180.0) * 10.0
        self._pwm_objects[f"servo_{name}"].ChangeDutyCycle(duty)
        servo["current_angle"] = angle
        return True

    def setup_led(self, name: str, pin: int, pwm: bool = False, freq: int = 1000):
        """Configure an LED (digital or PWM dimmable)."""
        _gpio.setup(pin, _gpio.OUT)
        led = {"pin": pin, "pwm": pwm, "brightness": 0, "on": False}
        if pwm:
            if self.is_real:
                p = _gpio.PWM(pin, freq)
            else:
                p = SimulatedPWM(pin, freq)
            p.start(0)
            self._pwm_objects[f"led_{name}"] = p
        self.leds[name] = led

    def set_led(self, name: str, on: bool = True, brightness: float = 1.0):
        """Control LED state and brightness."""
        if name not in self.leds:
            return False
        led = self.leds[name]
        led["on"] = on
        led["brightness"] = max(0, min(1, brightness))
        if led["pwm"]:
            self._pwm_objects[f"led_{name}"].ChangeDutyCycle(brightness * 100 if on else 0)
        else:
            _gpio.output(led["pin"], _gpio.HIGH if on else _gpio.LOW)
        return True

    def setup_relay(self, name: str, pin: int, active_low: bool = False):
        """Configure a relay."""
        _gpio.setup(pin, _gpio.OUT)
        _gpio.output(pin, _gpio.HIGH if active_low else _gpio.LOW)
        self.relays[name] = {"pin": pin, "active_low": active_low, "on": False}

    def set_relay(self, name: str, on: bool):
        if name not in self.relays:
            return False
        relay = self.relays[name]
        relay["on"] = on
        if relay["active_low"]:
            _gpio.output(relay["pin"], _gpio.LOW if on else _gpio.HIGH)
        else:
            _gpio.output(relay["pin"], _gpio.HIGH if on else _gpio.LOW)
        return True

    def read_digital(self, pin: int) -> int:
        return _gpio.input(pin)

    def get_state(self) -> dict:
        """Return full hardware state for telemetry."""
        return {
            "gpio_mode": "real" if self.is_real else "simulated",
            "motors": {n: {"speed": m["speed"], "direction": m["direction"]} for n, m in self.motors.items()},
            "servos": {n: {"angle": s["current_angle"]} for n, s in self.servos.items()},
            "leds": {n: {"on": l["on"], "brightness": l["brightness"]} for n, l in self.leds.items()},
            "relays": {n: {"on": r["on"]} for n, r in self.relays.items()},
        }

    def cleanup(self):
        for pwm in self._pwm_objects.values():
            pwm.stop()
        _gpio.cleanup()


# ═══════════════════════════════════════════
#  CAMERA FEED
# ═══════════════════════════════════════════

class PiCameraFeed:
    """
    Camera access for VPE integration.

    Supports:
      - Pi Camera Module (via picamera2)
      - USB webcam (via OpenCV)
      - Simulated (returns test frames)
    """

    def __init__(self, source="auto", resolution=(640, 480)):
        self.resolution = resolution
        self.source = source
        self._camera = None
        self._running = False
        self._frame = None
        self._lock = threading.Lock()
        self._init_camera()

    def _init_camera(self):
        if self.source == "auto" or self.source == "picamera":
            try:
                from picamera2 import Picamera2
                self._camera = Picamera2()
                self._camera.configure(self._camera.create_still_configuration(
                    main={"size": self.resolution}
                ))
                self.source = "picamera"
                return
            except (ImportError, Exception):
                pass

        if self.source == "auto" or self.source == "usb":
            try:
                import cv2
                self._camera = cv2.VideoCapture(0)
                if self._camera.isOpened():
                    self._camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
                    self._camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
                    self.source = "usb"
                    return
                else:
                    self._camera = None
            except ImportError:
                pass

        # Fallback: simulated
        self.source = "simulated"

    def capture_frame(self) -> bytes:
        """Capture a single frame as JPEG bytes."""
        if self.source == "picamera" and self._camera:
            import io
            stream = io.BytesIO()
            self._camera.start()
            self._camera.capture_file(stream, format='jpeg')
            self._camera.stop()
            return stream.getvalue()

        elif self.source == "usb" and self._camera:
            import cv2
            ret, frame = self._camera.read()
            if ret:
                _, buf = cv2.imencode('.jpg', frame)
                return buf.tobytes()

        # Simulated: return a minimal test JPEG
        return self._simulated_frame()

    def capture_for_vpe(self) -> str:
        """Capture frame as base64 for VPE analysis."""
        import base64
        jpeg_bytes = self.capture_frame()
        return "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode()

    def _simulated_frame(self) -> bytes:
        """Generate a simple test frame when no camera is available."""
        # Create minimal valid JPEG (2x2 grey pixels)
        # This is a minimal JFIF header + scan data
        import struct, zlib
        w, h = 64, 64
        # Use PNG since we can easily generate it
        def raw():
            for y in range(h):
                yield b'\x00'
                for x in range(w):
                    r = int(128 + 50 * ((x + y) % 4 == 0))
                    yield bytes([r, r, r])
        header = b'\x89PNG\r\n\x1a\n'
        ihdr_data = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
        ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data)
        ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc & 0xffffffff)
        raw_bytes = b''.join(raw())
        compressed = zlib.compress(raw_bytes)
        idat_crc = zlib.crc32(b'IDAT' + compressed)
        idat = struct.pack('>I', len(compressed)) + b'IDAT' + compressed + struct.pack('>I', idat_crc & 0xffffffff)
        iend_crc = zlib.crc32(b'IEND')
        iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc & 0xffffffff)
        return header + ihdr + idat + iend

    def close(self):
        if self.source == "usb" and self._camera:
            self._camera.release()
        elif self.source == "picamera" and self._camera:
            self._camera.close()


# ═══════════════════════════════════════════
#  SENSOR READER
# ═══════════════════════════════════════════

class PiSensorReader:
    """
    Read common sensors connected to the Pi.

    Supported sensors (auto-detected):
      - HC-SR04 ultrasonic distance
      - DHT11/DHT22 temperature + humidity
      - MPU6050 IMU (accelerometer + gyroscope)
      - Simulated fallback for all
    """

    def __init__(self):
        self._sensors = {}
        self._simulated_state = {
            "distance_cm": 100.0,
            "temperature_c": 22.5,
            "humidity_pct": 45.0,
            "accel": {"x": 0.0, "y": 0.0, "z": 9.81},
            "gyro": {"x": 0.0, "y": 0.0, "z": 0.0},
        }

    def setup_ultrasonic(self, name: str, trigger_pin: int, echo_pin: int):
        """Configure HC-SR04 ultrasonic distance sensor."""
        _gpio.setup(trigger_pin, _gpio.OUT)
        _gpio.setup(echo_pin, _gpio.IN)
        self._sensors[name] = {
            "type": "ultrasonic",
            "trigger": trigger_pin,
            "echo": echo_pin,
        }

    def setup_dht(self, name: str, pin: int, sensor_type: str = "DHT22"):
        self._sensors[name] = {"type": "dht", "pin": pin, "sensor": sensor_type}

    def setup_imu(self, name: str, address: int = 0x68):
        self._sensors[name] = {"type": "imu", "address": address}

    def read(self, name: str) -> dict:
        """Read a sensor value."""
        if name not in self._sensors:
            return {"error": f"Sensor '{name}' not configured"}

        sensor = self._sensors[name]

        if _GPIO_AVAILABLE:
            return self._read_real(name, sensor)
        else:
            return self._read_simulated(name, sensor)

    def _read_real(self, name: str, sensor: dict) -> dict:
        stype = sensor["type"]

        if stype == "ultrasonic":
            return self._read_ultrasonic(sensor)
        elif stype == "dht":
            return self._read_dht(sensor)
        elif stype == "imu":
            return self._read_imu(sensor)

        return {"error": "Unknown sensor type"}

    def _read_ultrasonic(self, sensor: dict) -> dict:
        """Read HC-SR04 distance."""
        try:
            trig = sensor["trigger"]
            echo = sensor["echo"]

            _gpio.output(trig, _gpio.LOW)
            time.sleep(0.00002)
            _gpio.output(trig, _gpio.HIGH)
            time.sleep(0.00001)
            _gpio.output(trig, _gpio.LOW)

            timeout = time.time() + 0.1
            while _gpio.input(echo) == 0 and time.time() < timeout:
                pulse_start = time.time()
            while _gpio.input(echo) == 1 and time.time() < timeout:
                pulse_end = time.time()

            distance = (pulse_end - pulse_start) * 17150
            return {"distance_cm": round(distance, 1)}
        except Exception as e:
            return {"error": str(e)}

    def _read_dht(self, sensor: dict) -> dict:
        try:
            import adafruit_dht
            import board
            pin = getattr(board, f"D{sensor['pin']}")
            dht = adafruit_dht.DHT22(pin) if sensor["sensor"] == "DHT22" else adafruit_dht.DHT11(pin)
            return {"temperature_c": dht.temperature, "humidity_pct": dht.humidity}
        except Exception:
            return self._read_simulated("dht", sensor)

    def _read_imu(self, sensor: dict) -> dict:
        try:
            import smbus
            bus = smbus.SMBus(1)
            addr = sensor["address"]
            bus.write_byte_data(addr, 0x6B, 0)  # Wake MPU6050
            raw = bus.read_i2c_block_data(addr, 0x3B, 14)

            def to_signed(h, l):
                v = (h << 8) | l
                return v - 65536 if v > 32767 else v

            ax = to_signed(raw[0], raw[1]) / 16384.0 * 9.81
            ay = to_signed(raw[2], raw[3]) / 16384.0 * 9.81
            az = to_signed(raw[4], raw[5]) / 16384.0 * 9.81
            gx = to_signed(raw[8], raw[9]) / 131.0
            gy = to_signed(raw[10], raw[11]) / 131.0
            gz = to_signed(raw[12], raw[13]) / 131.0

            return {
                "accel": {"x": round(ax, 3), "y": round(ay, 3), "z": round(az, 3)},
                "gyro": {"x": round(gx, 2), "y": round(gy, 2), "z": round(gz, 2)},
            }
        except Exception:
            return self._read_simulated("imu", sensor)

    def _read_simulated(self, name: str, sensor: dict) -> dict:
        """Return simulated sensor data with slight variations."""
        import random
        stype = sensor["type"]
        if stype == "ultrasonic":
            d = self._simulated_state["distance_cm"] + random.uniform(-2, 2)
            return {"distance_cm": round(max(2, d), 1)}
        elif stype == "dht":
            return {
                "temperature_c": round(self._simulated_state["temperature_c"] + random.uniform(-0.5, 0.5), 1),
                "humidity_pct": round(self._simulated_state["humidity_pct"] + random.uniform(-1, 1), 1),
            }
        elif stype == "imu":
            return {
                "accel": {k: round(v + random.uniform(-0.05, 0.05), 3) for k, v in self._simulated_state["accel"].items()},
                "gyro": {k: round(v + random.uniform(-0.2, 0.2), 2) for k, v in self._simulated_state["gyro"].items()},
            }
        return {}

    def read_all(self) -> dict:
        """Read all configured sensors."""
        return {name: self.read(name) for name in self._sensors}


# ═══════════════════════════════════════════
#  PI DEVICE — Full OmnixDevice for any Pi robot
# ═══════════════════════════════════════════

class PiDevice(OmnixDevice):
    """
    A real Raspberry Pi-based device that plugs into OMNIX.

    Usage:
        device = PiDevice("My Rover", device_type="ground_robot")
        device.gpio.setup_motor("left", 17, 27, 22)
        device.gpio.setup_motor("right", 23, 24, 25)
        device.sensors.setup_ultrasonic("front", 5, 6)
        device.camera = PiCameraFeed()
        # Now register with OMNIX server
    """

    def __init__(self, name: str, device_type: str = "ground_robot"):
        super().__init__(name, device_type)
        self.gpio = PiGPIOController()
        self.sensors = PiSensorReader()
        self.camera = None  # Set up separately if needed

        self._setup_capabilities()

    def _setup_capabilities(self):
        """Register standard capabilities based on configured hardware."""
        self.register_capability(DeviceCapability(
            name="set_motor",
            description="Control a motor's speed and direction",
            parameters={
                "name": {"type": "string", "description": "Motor name"},
                "speed": {"type": "float", "min": 0, "max": 1, "default": 0.5},
                "direction": {"type": "string", "options": ["forward", "backward", "stopped"]},
            },
            category="movement",
        ))
        self.register_capability(DeviceCapability(
            name="set_servo",
            description="Set servo angle",
            parameters={
                "name": {"type": "string"},
                "angle": {"type": "float", "min": 0, "max": 180, "default": 90},
            },
            category="movement",
        ))
        self.register_capability(DeviceCapability(
            name="set_led",
            description="Control LED",
            parameters={
                "name": {"type": "string"},
                "on": {"type": "bool", "default": True},
                "brightness": {"type": "float", "min": 0, "max": 1, "default": 1},
            },
            category="settings",
        ))
        self.register_capability(DeviceCapability(
            name="set_relay",
            description="Toggle relay",
            parameters={"name": {"type": "string"}, "on": {"type": "bool"}},
            category="settings",
        ))
        self.register_capability(DeviceCapability(
            name="read_sensor",
            description="Read a sensor value",
            parameters={"name": {"type": "string"}},
            category="sensors",
        ))
        self.register_capability(DeviceCapability(
            name="read_all_sensors",
            description="Read all configured sensors",
            category="sensors",
        ))
        self.register_capability(DeviceCapability(
            name="capture_photo",
            description="Take a photo with the camera (for VPE analysis)",
            category="sensors",
        ))
        self.register_capability(DeviceCapability(
            name="stop_all",
            description="Emergency stop — all motors off",
            category="safety",
        ))

    def execute_command(self, command: str, params: dict = None) -> dict:
        params = params or {}

        if command == "set_motor":
            ok = self.gpio.set_motor(
                params.get("name", ""),
                speed=params.get("speed", 0.5),
                direction=params.get("direction", "forward"),
            )
            self.log_event("motor", f"{params.get('name')}: {params.get('direction')} @ {params.get('speed')}")
            return {"success": ok, "message": "Motor updated" if ok else "Motor not found"}

        elif command == "set_servo":
            ok = self.gpio.set_servo(params.get("name", ""), params.get("angle", 90))
            return {"success": ok, "message": "Servo set" if ok else "Servo not found"}

        elif command == "set_led":
            ok = self.gpio.set_led(params.get("name", ""), params.get("on", True), params.get("brightness", 1))
            return {"success": ok}

        elif command == "set_relay":
            ok = self.gpio.set_relay(params.get("name", ""), params.get("on", True))
            return {"success": ok}

        elif command == "read_sensor":
            data = self.sensors.read(params.get("name", ""))
            return {"success": True, "data": data}

        elif command == "read_all_sensors":
            data = self.sensors.read_all()
            return {"success": True, "data": data}

        elif command == "capture_photo":
            if self.camera:
                b64 = self.camera.capture_for_vpe()
                return {"success": True, "data": {"image": b64}}
            return {"success": False, "message": "No camera configured"}

        elif command == "stop_all":
            for name in self.gpio.motors:
                self.gpio.set_motor(name, 0, "stopped")
            self.log_event("safety", "Emergency stop — all motors off")
            return {"success": True, "message": "All motors stopped"}

        return {"success": False, "message": f"Unknown command: {command}"}

    def get_telemetry(self) -> dict:
        """Return current state of all hardware."""
        telemetry = {
            "gpio": self.gpio.get_state(),
            "sensors": self.sensors.read_all(),
            "camera": self.camera.source if self.camera else "none",
            "position": self._estimate_position(),
        }
        return telemetry

    def _estimate_position(self) -> dict:
        """Estimate position from motor state (simple dead reckoning)."""
        # In a real implementation, this would integrate IMU data
        # For now, return a default position
        return {"x": 0, "y": 0, "z": 0}

    def cleanup(self):
        self.gpio.cleanup()
        if self.camera:
            self.camera.close()
