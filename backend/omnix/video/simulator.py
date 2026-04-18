"""
OMNIX Simulated Camera — generates synthetic video frames for demo mode.

Each device type gets a distinct visual style:
  - Drone:  top-down view with moving grid/terrain and position marker
  - Rover:  forward-facing view with horizon, ground texture, and obstacles
  - Arm:    workspace view showing the arm's reach envelope and joint positions
  - Generic: colour gradient with device info

All rendering uses PIL/Pillow when available, or falls back to raw RGB byte
painting (limited but functional).
"""

import io
import math
import struct
import time
from typing import Optional

# Try PIL for high-quality rendering
_HAS_PIL = False
try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
except ImportError:
    pass


class SimulatedCamera:
    """Generates synthetic camera frames for a device type."""

    def __init__(self, device_type: str, width: int = 640, height: int = 480):
        self.device_type = device_type.lower()
        self.width = width
        self.height = height
        self._frame_num = 0
        self._start_time = time.time()

    def render_frame(self, telemetry: Optional[dict] = None) -> bytes:
        """
        Render a synthetic frame as raw RGB bytes.

        Args:
            telemetry: Current device telemetry (position, battery, etc.)
        Returns:
            Raw RGB bytes (width * height * 3)
        """
        self._frame_num += 1
        t = telemetry or {}

        if _HAS_PIL:
            return self._render_pil(t)
        else:
            return self._render_raw(t)

    # ── PIL-based rendering (rich visuals) ────────────────

    def _render_pil(self, telemetry: dict) -> bytes:
        img = Image.new("RGB", (self.width, self.height), (20, 25, 35))
        draw = ImageDraw.Draw(img)

        renderer = {
            "drone": self._render_drone_pil,
            "ground_robot": self._render_rover_pil,
            "robot_arm": self._render_arm_pil,
            "home_robot": self._render_rover_pil,
        }.get(self.device_type, self._render_generic_pil)

        renderer(draw, img, telemetry)

        # Frame counter and timestamp in bottom-right
        self._draw_frame_info(draw)

        return img.tobytes()

    def _render_drone_pil(self, draw: "ImageDraw.Draw", img: "Image.Image",
                          telemetry: dict):
        """Top-down aerial view with grid that moves with drone position."""
        w, h = self.width, self.height

        # Get drone position for grid offset
        pos = telemetry.get("position_cm", {})
        if isinstance(pos, dict):
            dx = pos.get("x", 0)
            dy = pos.get("y", 0)
        else:
            dx, dy = 0, 0
        altitude = telemetry.get("height_cm", telemetry.get("altitude_cm", 100))
        flying = telemetry.get("flying", False)

        # Background — dark green terrain
        draw.rectangle([0, 0, w, h], fill=(25, 50, 30))

        # Grid lines — shift with position to create movement illusion
        grid_spacing = max(20, min(80, 4000 // max(altitude, 10)))
        offset_x = int(dx * 0.5) % grid_spacing
        offset_y = int(dy * 0.5) % grid_spacing

        grid_color = (40, 75, 45)
        for x in range(-grid_spacing, w + grid_spacing, grid_spacing):
            sx = x + offset_x
            draw.line([(sx, 0), (sx, h)], fill=grid_color, width=1)
        for y in range(-grid_spacing, h + grid_spacing, grid_spacing):
            sy = y + offset_y
            draw.line([(0, sy), (w, sy)], fill=grid_color, width=1)

        # Terrain features — scattered "trees" and "buildings"
        t_phase = self._frame_num * 0.01
        for i in range(12):
            fx = ((i * 137 + int(dx * 0.3)) % w)
            fy = ((i * 251 + int(dy * 0.3)) % h)
            size = 4 + (i % 5) * 3
            if i % 3 == 0:
                # Tree (green circle)
                draw.ellipse([fx-size, fy-size, fx+size, fy+size],
                             fill=(30, 90+i*5, 35))
            elif i % 3 == 1:
                # Building (grey rectangle)
                draw.rectangle([fx-size, fy-size, fx+size*2, fy+size*2],
                               fill=(80, 80, 85), outline=(60, 60, 65))
            else:
                # Road segment
                draw.rectangle([fx, fy-2, fx+size*4, fy+2],
                               fill=(70, 70, 70))

        # Drone shadow (grows smaller with altitude)
        cx, cy = w // 2, h // 2
        shadow_r = max(5, 40 - altitude // 10)
        draw.ellipse([cx-shadow_r, cy-shadow_r+5, cx+shadow_r, cy+shadow_r+5],
                     fill=(15, 30, 15, 100))

        # Drone crosshair
        ch_size = 30
        yaw = telemetry.get("yaw", 0)
        ch_color = (0, 255, 100) if flying else (255, 100, 50)
        draw.line([(cx-ch_size, cy), (cx+ch_size, cy)], fill=ch_color, width=2)
        draw.line([(cx, cy-ch_size), (cx, cy+ch_size)], fill=ch_color, width=2)
        draw.ellipse([cx-8, cy-8, cx+8, cy+8], outline=ch_color, width=2)

        # Compass indicator
        yaw_rad = math.radians(yaw)
        nx = cx + int(ch_size * math.sin(yaw_rad))
        ny = cy - int(ch_size * math.cos(yaw_rad))
        draw.line([(cx, cy), (nx, ny)], fill=(255, 50, 50), width=3)

        # Status text
        status = "FLYING" if flying else "GROUNDED"
        draw.text((10, h - 24), f"ALT:{altitude}cm  {status}",
                  fill=ch_color)

    def _render_rover_pil(self, draw: "ImageDraw.Draw", img: "Image.Image",
                          telemetry: dict):
        """Forward-facing view with horizon, ground, and obstacles."""
        w, h = self.width, self.height

        pos = telemetry.get("position", {})
        if isinstance(pos, dict):
            rx = pos.get("x", 0)
        else:
            rx = 0
        heading = telemetry.get("heading", 0)
        sonar = telemetry.get("sonar_cm", 200)

        # Sky gradient
        horizon_y = h * 2 // 5
        for y in range(horizon_y):
            ratio = y / horizon_y
            r = int(30 + ratio * 40)
            g = int(40 + ratio * 60)
            b = int(80 + ratio * 100)
            draw.line([(0, y), (w, y)], fill=(r, g, b))

        # Ground with perspective lines
        for y in range(horizon_y, h):
            ratio = (y - horizon_y) / (h - horizon_y)
            r = int(60 + ratio * 30)
            g = int(50 + ratio * 20)
            b = int(30 + ratio * 10)
            draw.line([(0, y), (w, y)], fill=(r, g, b))

        # Perspective grid on ground
        vanishing_x = w // 2 + int(heading * 2)
        for i in range(-6, 7):
            gx = vanishing_x + i * 100
            draw.line([(gx, horizon_y), (w//2 + i * 300, h)],
                      fill=(90, 80, 60), width=1)

        # Horizon cross-lines
        for y_off in range(0, h - horizon_y, 40):
            y = horizon_y + y_off
            draw.line([(0, y), (w, y)], fill=(80, 70, 50), width=1)

        # Obstacles (simulated based on sonar distance)
        if sonar < 150:
            obs_y = horizon_y + int((1.0 - sonar / 200.0) * (h - horizon_y) * 0.4)
            obs_w = max(20, int(80 * (150 - sonar) / 150))
            cx = w // 2 + int(30 * math.sin(self._frame_num * 0.05))
            draw.rectangle([cx - obs_w, obs_y - obs_w//2,
                            cx + obs_w, obs_y + obs_w//2],
                           fill=(120, 60, 40), outline=(180, 90, 60), width=2)
            draw.text((cx - 20, obs_y - obs_w//2 - 16),
                      f"OBSTACLE {sonar}cm", fill=(255, 80, 50))

        # HUD crosshair
        cx, cy = w // 2, horizon_y
        draw.line([(cx - 40, cy), (cx - 10, cy)], fill=(0, 255, 100), width=2)
        draw.line([(cx + 10, cy), (cx + 40, cy)], fill=(0, 255, 100), width=2)
        draw.line([(cx, cy - 20), (cx, cy - 5)], fill=(0, 255, 100), width=2)
        draw.line([(cx, cy + 5), (cx, cy + 20)], fill=(0, 255, 100), width=2)

        # Heading indicator
        draw.text((w//2 - 30, 8), f"HDG {heading}°",
                  fill=(0, 255, 100))

    def _render_arm_pil(self, draw: "ImageDraw.Draw", img: "Image.Image",
                        telemetry: dict):
        """Workspace view showing arm reach envelope and joint positions."""
        w, h = self.width, self.height

        # Background — workshop table
        draw.rectangle([0, 0, w, h], fill=(50, 45, 40))
        # Table grid
        for x in range(0, w, 30):
            draw.line([(x, 0), (x, h)], fill=(55, 50, 45), width=1)
        for y in range(0, h, 30):
            draw.line([(0, y), (w, y)], fill=(55, 50, 45), width=1)

        # Arm base (bottom center)
        base_x, base_y = w // 2, h - 40
        draw.ellipse([base_x-25, base_y-10, base_x+25, base_y+10],
                     fill=(100, 100, 110), outline=(150, 150, 160), width=2)

        # Get joint angles
        joints = telemetry.get("joints", {})
        base_angle = joints.get("base", 0) if isinstance(joints, dict) else 0
        shoulder_angle = joints.get("shoulder", 45) if isinstance(joints, dict) else 45
        elbow_angle = joints.get("elbow", -30) if isinstance(joints, dict) else -30
        wrist_angle = joints.get("wrist", 0) if isinstance(joints, dict) else 0
        gripper = telemetry.get("gripper_deg", 30)

        # Draw reach envelope (semi-transparent arc)
        reach = min(w, h) // 2 - 20
        draw.arc([base_x - reach, base_y - reach,
                  base_x + reach, base_y + reach],
                 start=180, end=360, fill=(60, 80, 60), width=1)

        # Draw arm segments
        seg_len = reach // 3
        # Shoulder
        a1 = math.radians(270 + base_angle + shoulder_angle * 0.5)
        j1_x = base_x + int(seg_len * math.cos(a1))
        j1_y = base_y + int(seg_len * math.sin(a1))
        draw.line([(base_x, base_y), (j1_x, j1_y)],
                  fill=(180, 180, 190), width=8)
        draw.ellipse([j1_x-6, j1_y-6, j1_x+6, j1_y+6],
                     fill=(200, 100, 50))

        # Elbow
        a2 = a1 + math.radians(elbow_angle * 0.5)
        j2_x = j1_x + int(seg_len * 0.8 * math.cos(a2))
        j2_y = j1_y + int(seg_len * 0.8 * math.sin(a2))
        draw.line([(j1_x, j1_y), (j2_x, j2_y)],
                  fill=(160, 160, 170), width=6)
        draw.ellipse([j2_x-5, j2_y-5, j2_x+5, j2_y+5],
                     fill=(200, 100, 50))

        # Wrist + gripper
        a3 = a2 + math.radians(wrist_angle * 0.3)
        j3_x = j2_x + int(seg_len * 0.5 * math.cos(a3))
        j3_y = j2_y + int(seg_len * 0.5 * math.sin(a3))
        draw.line([(j2_x, j2_y), (j3_x, j3_y)],
                  fill=(140, 140, 150), width=4)

        # Gripper jaws
        grip_open = max(3, int(gripper * 0.2))
        draw.line([(j3_x - grip_open, j3_y), (j3_x - grip_open, j3_y - 12)],
                  fill=(100, 200, 100), width=3)
        draw.line([(j3_x + grip_open, j3_y), (j3_x + grip_open, j3_y - 12)],
                  fill=(100, 200, 100), width=3)

        # Joint info
        draw.text((10, h - 24),
                  f"BASE:{base_angle}° SHOULDER:{shoulder_angle}° "
                  f"ELBOW:{elbow_angle}° GRIP:{gripper}°",
                  fill=(0, 200, 150))

    def _render_generic_pil(self, draw: "ImageDraw.Draw", img: "Image.Image",
                            telemetry: dict):
        """Generic colourful pattern for unknown device types."""
        w, h = self.width, self.height
        t = self._frame_num * 0.02

        # Animated gradient
        for y in range(0, h, 4):
            ratio = y / h
            r = int(30 + 50 * math.sin(t + ratio * 3))
            g = int(50 + 40 * math.cos(t * 0.7 + ratio * 2))
            b = int(80 + 60 * math.sin(t * 1.3 + ratio * 4))
            draw.rectangle([0, y, w, y + 4], fill=(max(0, r), max(0, g), max(0, b)))

        # Device type label
        draw.text((w // 2 - 60, h // 2 - 10),
                  f"OMNIX: {self.device_type.upper()}",
                  fill=(255, 255, 255))

        # Animated scanning line
        scan_y = int((self._frame_num * 3) % h)
        draw.line([(0, scan_y), (w, scan_y)], fill=(0, 255, 100), width=2)

    def _draw_frame_info(self, draw: "ImageDraw.Draw"):
        """Frame counter and timestamp overlay (bottom-right)."""
        elapsed = time.time() - self._start_time
        text = f"F:{self._frame_num}  T:{elapsed:.1f}s"
        draw.text((self.width - 160, self.height - 18),
                  text, fill=(120, 120, 130))

    # ── Fallback rendering (no PIL) ───────────────────────

    def _render_raw(self, telemetry: dict) -> bytes:
        """Generate raw RGB bytes without PIL (basic patterns only)."""
        w, h = self.width, self.height
        pixels = bytearray(w * h * 3)
        t = self._frame_num

        if self.device_type == "drone":
            self._raw_drone(pixels, w, h, t, telemetry)
        elif self.device_type in ("ground_robot", "home_robot"):
            self._raw_rover(pixels, w, h, t, telemetry)
        else:
            self._raw_generic(pixels, w, h, t)

        return bytes(pixels)

    def _raw_drone(self, px: bytearray, w: int, h: int,
                   t: int, telemetry: dict):
        """Simple top-down grid for drone (no PIL)."""
        grid = 40
        offset = (t * 2) % grid
        for y in range(h):
            for x in range(w):
                idx = (y * w + x) * 3
                gx = (x + offset) % grid
                gy = (y + offset) % grid
                if gx == 0 or gy == 0:
                    px[idx] = 40; px[idx+1] = 80; px[idx+2] = 45
                else:
                    px[idx] = 25; px[idx+1] = 50; px[idx+2] = 30
        # Center cross
        cx, cy = w // 2, h // 2
        for d in range(-20, 21):
            if 0 <= cx + d < w:
                idx = (cy * w + cx + d) * 3
                px[idx] = 0; px[idx+1] = 255; px[idx+2] = 100
            if 0 <= cy + d < h:
                idx = ((cy + d) * w + cx) * 3
                px[idx] = 0; px[idx+1] = 255; px[idx+2] = 100

    def _raw_rover(self, px: bytearray, w: int, h: int,
                   t: int, telemetry: dict):
        """Simple horizon view for rover (no PIL)."""
        horizon = h * 2 // 5
        for y in range(h):
            for x in range(w):
                idx = (y * w + x) * 3
                if y < horizon:
                    # Sky
                    ratio = y / horizon
                    px[idx] = int(30 + ratio * 40)
                    px[idx+1] = int(40 + ratio * 60)
                    px[idx+2] = int(80 + ratio * 100)
                else:
                    # Ground
                    ratio = (y - horizon) / (h - horizon)
                    px[idx] = int(60 + ratio * 30)
                    px[idx+1] = int(50 + ratio * 20)
                    px[idx+2] = int(30 + ratio * 10)

    def _raw_generic(self, px: bytearray, w: int, h: int, t: int):
        """Animated gradient for generic devices (no PIL)."""
        for y in range(h):
            ratio = y / h
            r = int(30 + 50 * math.sin(t * 0.02 + ratio * 3)) % 256
            g = int(50 + 40 * math.cos(t * 0.014 + ratio * 2)) % 256
            b = int(80 + 60 * math.sin(t * 0.026 + ratio * 4)) % 256
            for x in range(w):
                idx = (y * w + x) * 3
                px[idx] = max(0, r)
                px[idx+1] = max(0, g)
                px[idx+2] = max(0, b)
