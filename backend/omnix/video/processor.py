"""
OMNIX Frame Processor — resize, compress, overlay, snapshot, and record.

Works with pure-Python PIL/Pillow when available, falls back to a minimal
JPEG encoder using stdlib only (struct + zlib for BMP, or raw PPM piped
through ImageMagick/ffmpeg if available).

Pipeline per frame:
  1. Resize/crop to target resolution
  2. Optional telemetry overlay (battery, altitude, speed in corner)
  3. Optional object detection overlay (bounding box stub)
  4. JPEG compress at configurable quality
  5. Snapshot capture (save single frame as PNG)
"""

import io
import os
import struct
import time
import zlib
from typing import Optional


# ── Try to import PIL for high-quality image processing ──
_HAS_PIL = False
try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
except ImportError:
    pass


class FrameProcessor:
    """Stateless frame processing pipeline."""

    def process_frame(self, raw_bytes: bytes, width: int, height: int,
                      telemetry: Optional[dict] = None,
                      detection_boxes: Optional[list] = None,
                      quality: int = 70) -> bytes:
        """
        Process a raw RGB frame → JPEG bytes.

        Args:
            raw_bytes: Raw RGB pixel data (width * height * 3 bytes)
            width, height: Frame dimensions
            telemetry: Optional dict to overlay (battery, altitude, etc.)
            detection_boxes: Optional list of {"label", "x", "y", "w", "h", "confidence"}
            quality: JPEG quality 1-100
        Returns:
            JPEG-encoded bytes
        """
        if _HAS_PIL:
            return self._process_pil(raw_bytes, width, height,
                                     telemetry, detection_boxes, quality)
        else:
            return self._process_fallback(raw_bytes, width, height, quality)

    def raw_rgb_to_jpeg(self, raw_bytes: bytes, width: int, height: int,
                        quality: int = 70) -> bytes:
        """Convert raw RGB bytes to JPEG (no overlays)."""
        if _HAS_PIL:
            img = Image.frombytes("RGB", (width, height), raw_bytes)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            return buf.getvalue()
        return self._process_fallback(raw_bytes, width, height, quality)

    def snapshot(self, jpeg_bytes: bytes, save_path: str) -> str:
        """Save a JPEG frame as a PNG file. Returns the file path."""
        if _HAS_PIL:
            img = Image.open(io.BytesIO(jpeg_bytes))
            img.save(save_path, format="PNG")
        else:
            # Just save the JPEG directly if no PIL
            save_path = save_path.rsplit(".", 1)[0] + ".jpg"
            with open(save_path, "wb") as f:
                f.write(jpeg_bytes)
        return save_path

    # ── PIL-based processing ──────────────────────────────

    def _process_pil(self, raw_bytes: bytes, width: int, height: int,
                     telemetry: Optional[dict], detection_boxes: Optional[list],
                     quality: int) -> bytes:
        img = Image.frombytes("RGB", (width, height), raw_bytes)
        draw = ImageDraw.Draw(img)

        # Telemetry overlay (top-left corner)
        if telemetry:
            self._draw_telemetry_overlay(draw, telemetry, width, height)

        # Object detection overlay (stub for future ML)
        if detection_boxes:
            self._draw_detection_overlay(draw, detection_boxes)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()

    def _draw_telemetry_overlay(self, draw: "ImageDraw.Draw",
                                telemetry: dict, width: int, height: int):
        """Burn telemetry data into the frame corner."""
        lines = []
        if "battery" in telemetry:
            bat = telemetry["battery"]
            icon = "█" if bat > 50 else "▌" if bat > 20 else "▎"
            lines.append(f"BAT {icon} {bat:.0f}%")
        if "altitude_cm" in telemetry or "height_cm" in telemetry:
            alt = telemetry.get("altitude_cm", telemetry.get("height_cm", 0))
            lines.append(f"ALT {alt}cm")
        if "velocity" in telemetry:
            v = telemetry["velocity"]
            if isinstance(v, dict):
                speed = (v.get("x", 0)**2 + v.get("y", 0)**2 + v.get("z", 0)**2) ** 0.5
            else:
                speed = 0
            lines.append(f"SPD {speed:.1f}cm/s")
        if "position_cm" in telemetry:
            p = telemetry["position_cm"]
            if isinstance(p, dict):
                lines.append(f"POS ({p.get('x',0):.0f},{p.get('y',0):.0f},{p.get('z',0):.0f})")
        if "gps" in telemetry:
            g = telemetry["gps"]
            if isinstance(g, dict):
                lines.append(f"GPS {g.get('lat',0):.4f},{g.get('lon',0):.4f}")
        if "yaw" in telemetry:
            lines.append(f"YAW {telemetry['yaw']}°")

        if not lines:
            return

        # Semi-transparent background box
        font_size = max(10, height // 35)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", font_size)
        except (OSError, IOError):
            font = ImageFont.load_default()

        padding = 6
        line_h = font_size + 3
        box_w = max(len(l) for l in lines) * (font_size * 0.62) + padding * 2
        box_h = len(lines) * line_h + padding * 2
        x0, y0 = 8, 8

        # Draw background
        draw.rectangle([x0, y0, x0 + box_w, y0 + box_h],
                        fill=(0, 0, 0, 180))

        # Draw text
        for i, line in enumerate(lines):
            draw.text((x0 + padding, y0 + padding + i * line_h),
                      line, fill=(0, 255, 100), font=font)

    def _draw_detection_overlay(self, draw: "ImageDraw.Draw",
                                boxes: list):
        """Draw bounding boxes for object detection (stub)."""
        colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255),
                  (255, 255, 0), (255, 0, 255)]
        for i, box in enumerate(boxes):
            x, y, w, h = box["x"], box["y"], box["w"], box["h"]
            color = colors[i % len(colors)]
            draw.rectangle([x, y, x + w, y + h], outline=color, width=2)
            label = box.get("label", "?")
            conf = box.get("confidence", 0)
            draw.text((x + 2, y - 14), f"{label} {conf:.0%}", fill=color)

    # ── Fallback (no PIL) ─────────────────────────────────

    def _process_fallback(self, raw_bytes: bytes, width: int, height: int,
                          quality: int) -> bytes:
        """
        Minimal JPEG encoding without PIL.
        Creates a BMP in memory; if available, converts via external tool.
        Otherwise returns BMP (browsers can display it, though less efficiently).
        """
        # Build a BMP from raw RGB
        bmp = self._rgb_to_bmp(raw_bytes, width, height)

        # Try to convert to JPEG via subprocess
        try:
            import subprocess
            proc = subprocess.run(
                ["convert", "bmp:-", f"-quality", str(quality), "jpeg:-"],
                input=bmp, capture_output=True, timeout=2)
            if proc.returncode == 0 and len(proc.stdout) > 0:
                return proc.stdout
        except (FileNotFoundError, Exception):
            pass

        # Return BMP as fallback (browsers handle it)
        return bmp

    def _rgb_to_bmp(self, raw: bytes, w: int, h: int) -> bytes:
        """Convert raw RGB to BMP format."""
        row_size = (w * 3 + 3) & ~3  # BMP rows are 4-byte aligned
        pixel_size = row_size * h
        file_size = 54 + pixel_size

        # BMP header
        header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, 54)
        # DIB header (BITMAPINFOHEADER)
        dib = struct.pack("<IiiHHIIiiII", 40, w, -h, 1, 24, 0,
                          pixel_size, 2835, 2835, 0, 0)

        # Convert RGB to BGR row-padded
        rows = []
        pad = b"\x00" * (row_size - w * 3)
        for y_idx in range(h):
            offset = y_idx * w * 3
            row = bytearray()
            for x_idx in range(w):
                px = offset + x_idx * 3
                if px + 2 < len(raw):
                    r, g, b = raw[px], raw[px + 1], raw[px + 2]
                else:
                    r, g, b = 0, 0, 0
                row.extend([b, g, r])
            row.extend(pad)
            rows.append(bytes(row))

        return header + dib + b"".join(rows)
