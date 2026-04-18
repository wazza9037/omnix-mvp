"""
OMNIX Simulated Smart Light Device

Simulates an RGB smart light bulb with:
- On/Off control
- Brightness (0-100%)
- Color (RGB hex)
- Color temperature (warm/cool)
- Effects (pulse, rainbow, breathe)
- Scheduling (simulated)
- Energy monitoring
"""

import time
import random
import math
from .base import OmnixDevice, DeviceCapability


class SimulatedSmartLight(OmnixDevice):
    def __init__(self, name: str = "OMNIX Light L1"):
        super().__init__(name=name, device_type="smart_light")

        self.is_on = False
        self.brightness = 100          # 0-100%
        self.color = "FFFFFF"          # Hex RGB
        self.color_temp = 4000         # Kelvin (2700=warm, 6500=cool)
        self.effect = "none"           # none, pulse, rainbow, breathe, candle
        self.power_usage = 0.0         # Watts
        self.total_energy = 0.0        # Wh consumed
        self.on_time = 0.0             # Seconds the light has been on
        self.last_update = time.time()

        self._register_capabilities()

    def _register_capabilities(self):
        self.register_capability(DeviceCapability(
            name="toggle",
            description="Turn the light on or off",
            parameters={"state": {"type": "select", "options": ["on", "off"]}},
            category="power"
        ))
        self.register_capability(DeviceCapability(
            name="set_brightness",
            description="Set brightness level",
            parameters={"brightness": {"type": "number", "min": 0, "max": 100, "default": 100, "unit": "%"}},
            category="settings"
        ))
        self.register_capability(DeviceCapability(
            name="set_color",
            description="Set the light color (hex RGB)",
            parameters={"color": {"type": "color", "default": "FFFFFF"}},
            category="settings"
        ))
        self.register_capability(DeviceCapability(
            name="set_temperature",
            description="Set color temperature (warm to cool)",
            parameters={"kelvin": {"type": "number", "min": 2700, "max": 6500, "default": 4000, "unit": "K"}},
            category="settings"
        ))
        self.register_capability(DeviceCapability(
            name="set_effect",
            description="Apply a lighting effect",
            parameters={
                "effect": {"type": "select", "options": ["none", "pulse", "rainbow", "breathe", "candle"]}
            },
            category="effects"
        ))
        self.register_capability(DeviceCapability(
            name="set_scene",
            description="Apply a preset scene",
            parameters={
                "scene": {"type": "select", "options": ["daylight", "sunset", "movie", "focus", "party", "relax"]}
            },
            category="presets"
        ))

    def _get_scene(self, name: str) -> dict:
        scenes = {
            "daylight":  {"color": "FFFFFF", "brightness": 100, "color_temp": 5500, "effect": "none"},
            "sunset":    {"color": "FF6B35", "brightness": 70,  "color_temp": 2700, "effect": "none"},
            "movie":     {"color": "1A1A2E", "brightness": 20,  "color_temp": 3000, "effect": "none"},
            "focus":     {"color": "E8F4FD", "brightness": 90,  "color_temp": 5000, "effect": "none"},
            "party":     {"color": "FF00FF", "brightness": 100, "color_temp": 4000, "effect": "rainbow"},
            "relax":     {"color": "FFD700", "brightness": 40,  "color_temp": 2700, "effect": "breathe"},
        }
        return scenes.get(name, scenes["daylight"])

    def _update_energy(self):
        now = time.time()
        elapsed = now - self.last_update
        self.last_update = now

        if self.is_on:
            # Simulate power usage based on brightness
            self.power_usage = 12 * (self.brightness / 100)  # Max 12W LED
            self.total_energy += self.power_usage * (elapsed / 3600)  # Wh
            self.on_time += elapsed
        else:
            self.power_usage = 0.3  # Standby power

    def _get_current_color(self) -> str:
        """Get the current display color (may differ from set color if effect is active)."""
        if not self.is_on:
            return "000000"

        if self.effect == "rainbow":
            # Cycle through hues
            hue = (time.time() * 30) % 360
            return self._hue_to_hex(hue)
        elif self.effect == "pulse":
            # Pulse brightness
            factor = (math.sin(time.time() * 3) + 1) / 2
            return self._adjust_brightness_hex(self.color, factor)
        elif self.effect == "breathe":
            factor = (math.sin(time.time() * 1.5) + 1) / 2
            return self._adjust_brightness_hex(self.color, 0.3 + factor * 0.7)
        elif self.effect == "candle":
            flicker = random.uniform(0.7, 1.0)
            return self._adjust_brightness_hex("FF9900", flicker)

        return self.color

    def _hue_to_hex(self, hue: float) -> str:
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(hue / 360, 1.0, 1.0)
        return f"{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"

    def _adjust_brightness_hex(self, hex_color: str, factor: float) -> str:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        r = int(r * factor)
        g = int(g * factor)
        b = int(b * factor)
        return f"{r:02X}{g:02X}{b:02X}"

    def get_telemetry(self) -> dict:
        self._update_energy()
        return {
            "is_on": self.is_on,
            "brightness": self.brightness,
            "color": self.color,
            "display_color": self._get_current_color(),
            "color_temp": self.color_temp,
            "effect": self.effect,
            "power_usage": round(self.power_usage, 2),
            "total_energy_wh": round(self.total_energy, 2),
            "on_time_hours": round(self.on_time / 3600, 2),
        }

    def execute_command(self, command: str, params: dict = None) -> dict:
        params = params or {}

        if command == "toggle":
            state = params.get("state", "on" if not self.is_on else "off")
            self.is_on = (state == "on")
            self.log_event("power", f"Light turned {'on' if self.is_on else 'off'}")
            return {"success": True, "message": f"Light turned {state}"}

        elif command == "set_brightness":
            self.brightness = max(0, min(100, params.get("brightness", 100)))
            if self.brightness > 0 and not self.is_on:
                self.is_on = True
            self.log_event("settings", f"Brightness set to {self.brightness}%")
            return {"success": True, "message": f"Brightness set to {self.brightness}%"}

        elif command == "set_color":
            color = params.get("color", "FFFFFF").replace("#", "").upper()
            if len(color) == 6:
                self.color = color
                if not self.is_on:
                    self.is_on = True
                self.log_event("settings", f"Color set to #{color}")
                return {"success": True, "message": f"Color set to #{color}"}
            return {"success": False, "message": "Invalid color format. Use 6-digit hex (e.g., FF0000)"}

        elif command == "set_temperature":
            kelvin = max(2700, min(6500, params.get("kelvin", 4000)))
            self.color_temp = kelvin
            # Convert temp to approximate color
            if kelvin <= 3500:
                self.color = "FFB347"
            elif kelvin <= 4500:
                self.color = "FFEFD5"
            else:
                self.color = "F0F8FF"
            self.log_event("settings", f"Color temp set to {kelvin}K")
            return {"success": True, "message": f"Color temperature set to {kelvin}K"}

        elif command == "set_effect":
            effect = params.get("effect", "none")
            if effect in ["none", "pulse", "rainbow", "breathe", "candle"]:
                self.effect = effect
                if effect != "none" and not self.is_on:
                    self.is_on = True
                self.log_event("effects", f"Effect set to '{effect}'")
                return {"success": True, "message": f"Effect: {effect}"}
            return {"success": False, "message": f"Unknown effect: {effect}"}

        elif command == "set_scene":
            scene_name = params.get("scene", "daylight")
            scene = self._get_scene(scene_name)
            self.color = scene["color"]
            self.brightness = scene["brightness"]
            self.color_temp = scene["color_temp"]
            self.effect = scene["effect"]
            self.is_on = True
            self.log_event("preset", f"Scene applied: {scene_name}")
            return {"success": True, "message": f"Scene '{scene_name}' applied"}

        return {"success": False, "message": f"Unknown command: {command}"}
