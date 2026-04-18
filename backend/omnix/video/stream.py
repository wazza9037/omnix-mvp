"""
OMNIX Video Stream Manager — handles multiple video sources.

Supported sources:
  - Tello UDP H264 stream (port 11111, decoded to JPEG frames)
  - Raspberry Pi camera via MJPEG over HTTP (proxy)
  - USB webcam via OpenCV VideoCapture (local)
  - Simulated camera feed (synthetic frames for demo mode)

Each source runs in its own thread and produces JPEG frames that are
served over MJPEG (multipart/x-mixed-replace) to the browser.
"""

import io
import struct
import subprocess
import threading
import time
import socket
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable

from omnix.video.simulator import SimulatedCamera


class SourceType(Enum):
    TELLO = "tello"
    PI_CAMERA = "pi_camera"
    USB_WEBCAM = "usb_webcam"
    SIMULATED = "simulated"


@dataclass
class VideoConfig:
    """Per-source video configuration."""
    target_fps: int = 15
    width: int = 640
    height: int = 480
    jpeg_quality: int = 70
    overlay_telemetry: bool = True
    overlay_detection: bool = False


@dataclass
class VideoSource:
    """Represents a single video feed tied to a device."""
    device_id: str
    source_type: SourceType
    config: VideoConfig = field(default_factory=VideoConfig)
    label: str = ""
    # Internal state
    _running: bool = field(default=False, repr=False)
    _thread: Optional[threading.Thread] = field(default=None, repr=False)
    _frame: Optional[bytes] = field(default=None, repr=False)
    _frame_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _frame_count: int = field(default=0, repr=False)
    _fps_actual: float = field(default=0.0, repr=False)
    _last_frame_time: float = field(default=0.0, repr=False)
    _recording: bool = field(default=False, repr=False)
    _recorded_frames: list = field(default_factory=list, repr=False)
    # Source-specific
    _sim_camera: Optional[SimulatedCamera] = field(default=None, repr=False)
    _telemetry_fn: Optional[Callable] = field(default=None, repr=False)
    # External connection details
    _uri: str = field(default="", repr=False)

    def get_frame(self) -> Optional[bytes]:
        """Return the latest JPEG frame (thread-safe)."""
        with self._frame_lock:
            return self._frame

    def set_frame(self, jpeg_bytes: bytes):
        """Store a new JPEG frame (thread-safe)."""
        now = time.time()
        with self._frame_lock:
            self._frame = jpeg_bytes
            self._frame_count += 1
            if self._last_frame_time > 0:
                dt = now - self._last_frame_time
                if dt > 0:
                    # Exponential moving average of FPS
                    instant_fps = 1.0 / dt
                    self._fps_actual = 0.7 * self._fps_actual + 0.3 * instant_fps
            self._last_frame_time = now
            if self._recording:
                self._recorded_frames.append(jpeg_bytes)

    def info(self) -> dict:
        """JSON-serialisable source info."""
        return {
            "device_id": self.device_id,
            "source_type": self.source_type.value,
            "label": self.label,
            "running": self._running,
            "fps_target": self.config.target_fps,
            "fps_actual": round(self._fps_actual, 1),
            "resolution": f"{self.config.width}x{self.config.height}",
            "frame_count": self._frame_count,
            "recording": self._recording,
        }


class VideoStreamManager:
    """
    Central manager for all video sources.

    Usage:
        mgr = VideoStreamManager()
        mgr.add_simulated("drone-1", "drone", telemetry_fn)
        mgr.start("drone-1")
        frame = mgr.get_frame("drone-1")  # latest JPEG
    """

    def __init__(self):
        self._sources: dict[str, VideoSource] = {}
        self._lock = threading.Lock()

    # ── Source registration ────────────────────────────────

    def add_simulated(self, device_id: str, device_type: str,
                      telemetry_fn: Optional[Callable] = None,
                      config: Optional[VideoConfig] = None) -> VideoSource:
        """Add a simulated camera for a device."""
        cfg = config or VideoConfig(target_fps=15)
        src = VideoSource(
            device_id=device_id,
            source_type=SourceType.SIMULATED,
            config=cfg,
            label=f"Simulated ({device_type})",
        )
        src._sim_camera = SimulatedCamera(device_type, cfg.width, cfg.height)
        src._telemetry_fn = telemetry_fn
        with self._lock:
            self._sources[device_id] = src
        return src

    def add_tello(self, device_id: str, udp_port: int = 11111,
                  config: Optional[VideoConfig] = None,
                  simulated: bool = False,
                  telemetry_fn: Optional[Callable] = None) -> VideoSource:
        """Add a Tello video source (real H264 UDP or simulated)."""
        if simulated:
            return self.add_simulated(device_id, "drone", telemetry_fn, config)

        cfg = config or VideoConfig(target_fps=30)
        src = VideoSource(
            device_id=device_id,
            source_type=SourceType.TELLO,
            config=cfg,
            label="Tello Camera",
            _uri=str(udp_port),
        )
        src._telemetry_fn = telemetry_fn
        with self._lock:
            self._sources[device_id] = src
        return src

    def add_pi_camera(self, device_id: str, mjpeg_url: str,
                      config: Optional[VideoConfig] = None) -> VideoSource:
        """Add a Raspberry Pi MJPEG stream (OMNIX proxies it)."""
        cfg = config or VideoConfig(target_fps=15)
        src = VideoSource(
            device_id=device_id,
            source_type=SourceType.PI_CAMERA,
            config=cfg,
            label="Pi Camera",
            _uri=mjpeg_url,
        )
        with self._lock:
            self._sources[device_id] = src
        return src

    def add_usb_webcam(self, device_id: str, camera_index: int = 0,
                       config: Optional[VideoConfig] = None) -> VideoSource:
        """Add a local USB webcam via OpenCV."""
        cfg = config or VideoConfig(target_fps=30)
        src = VideoSource(
            device_id=device_id,
            source_type=SourceType.USB_WEBCAM,
            config=cfg,
            label=f"USB Camera #{camera_index}",
            _uri=str(camera_index),
        )
        with self._lock:
            self._sources[device_id] = src
        return src

    # ── Lifecycle ──────────────────────────────────────────

    def start(self, device_id: str) -> bool:
        """Start capturing frames for a source."""
        src = self._sources.get(device_id)
        if not src or src._running:
            return False

        src._running = True
        target = {
            SourceType.SIMULATED: self._run_simulated,
            SourceType.TELLO: self._run_tello,
            SourceType.PI_CAMERA: self._run_pi_camera,
            SourceType.USB_WEBCAM: self._run_usb_webcam,
        }[src.source_type]

        src._thread = threading.Thread(
            target=target, args=(src,), daemon=True,
            name=f"video-{device_id[:8]}")
        src._thread.start()
        return True

    def stop(self, device_id: str):
        """Stop capturing frames for a source."""
        src = self._sources.get(device_id)
        if src:
            src._running = False

    def stop_all(self):
        """Stop all video sources."""
        for src in self._sources.values():
            src._running = False

    def remove(self, device_id: str):
        """Stop and remove a source."""
        self.stop(device_id)
        with self._lock:
            self._sources.pop(device_id, None)

    # ── Frame access ──────────────────────────────────────

    def get_frame(self, device_id: str) -> Optional[bytes]:
        """Get the latest JPEG frame for a device."""
        src = self._sources.get(device_id)
        return src.get_frame() if src else None

    def get_source(self, device_id: str) -> Optional[VideoSource]:
        return self._sources.get(device_id)

    def list_sources(self) -> list[dict]:
        """List all registered video sources."""
        return [src.info() for src in self._sources.values()]

    def configure(self, device_id: str, **kwargs) -> bool:
        """Update configuration for a source."""
        src = self._sources.get(device_id)
        if not src:
            return False
        cfg = src.config
        if "target_fps" in kwargs:
            cfg.target_fps = int(kwargs["target_fps"])
        if "width" in kwargs:
            cfg.width = int(kwargs["width"])
        if "height" in kwargs:
            cfg.height = int(kwargs["height"])
        if "jpeg_quality" in kwargs:
            cfg.jpeg_quality = int(kwargs["jpeg_quality"])
        if "overlay_telemetry" in kwargs:
            cfg.overlay_telemetry = bool(kwargs["overlay_telemetry"])
        if "overlay_detection" in kwargs:
            cfg.overlay_detection = bool(kwargs["overlay_detection"])
        # If simulated, update the SimulatedCamera dimensions
        if src._sim_camera:
            src._sim_camera.width = cfg.width
            src._sim_camera.height = cfg.height
        return True

    # ── Recording ─────────────────────────────────────────

    def start_recording(self, device_id: str) -> bool:
        src = self._sources.get(device_id)
        if not src or not src._running:
            return False
        src._recorded_frames = []
        src._recording = True
        return True

    def stop_recording(self, device_id: str) -> list[bytes]:
        """Stop recording and return captured frames."""
        src = self._sources.get(device_id)
        if not src:
            return []
        src._recording = False
        frames = src._recorded_frames
        src._recorded_frames = []
        return frames

    # ── Capture threads ───────────────────────────────────

    def _run_simulated(self, src: VideoSource):
        """Generate synthetic frames from SimulatedCamera."""
        from omnix.video.processor import FrameProcessor
        processor = FrameProcessor()

        while src._running:
            t0 = time.time()
            telemetry = src._telemetry_fn() if src._telemetry_fn else {}

            # Generate raw frame from simulator
            raw_frame = src._sim_camera.render_frame(telemetry)

            # Process (overlay + compress)
            jpeg = processor.process_frame(
                raw_frame, src.config.width, src.config.height,
                telemetry=telemetry if src.config.overlay_telemetry else None,
                quality=src.config.jpeg_quality,
            )
            src.set_frame(jpeg)

            # Frame rate control
            elapsed = time.time() - t0
            target_dt = 1.0 / max(1, src.config.target_fps)
            if elapsed < target_dt:
                time.sleep(target_dt - elapsed)

    def _run_tello(self, src: VideoSource):
        """
        Receive H264 video from Tello UDP port 11111.
        Decode via ffmpeg subprocess → raw RGB → JPEG.
        Falls back to simulated if ffmpeg unavailable.
        """
        from omnix.video.processor import FrameProcessor
        processor = FrameProcessor()
        udp_port = int(src._uri)
        w, h = src.config.width, src.config.height

        # Try ffmpeg-based decode
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("", udp_port))
            sock.settimeout(2.0)

            # Use ffmpeg to decode H264 from UDP to raw frames
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-i", f"udp://0.0.0.0:{udp_port}",
                "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s", f"{w}x{h}",
                "-r", str(src.config.target_fps),
                "pipe:1"
            ]
            sock.close()  # ffmpeg will bind to the port

            proc = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            frame_size = w * h * 3

            while src._running and proc.poll() is None:
                raw = proc.stdout.read(frame_size)
                if len(raw) < frame_size:
                    continue
                jpeg = processor.raw_rgb_to_jpeg(raw, w, h, src.config.jpeg_quality)
                src.set_frame(jpeg)

            proc.terminate()
        except (FileNotFoundError, OSError):
            # ffmpeg not available — fall back to simulated
            src._sim_camera = SimulatedCamera("drone", w, h)
            self._run_simulated(src)

    def _run_pi_camera(self, src: VideoSource):
        """Proxy an MJPEG stream from a Raspberry Pi."""
        mjpeg_url = src._uri
        buf = b""

        while src._running:
            try:
                req = urllib.request.Request(mjpeg_url)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    while src._running:
                        chunk = resp.read(4096)
                        if not chunk:
                            break
                        buf += chunk
                        # Find JPEG boundaries
                        while True:
                            start = buf.find(b"\xff\xd8")
                            end = buf.find(b"\xff\xd9", start + 2) if start >= 0 else -1
                            if start < 0 or end < 0:
                                break
                            jpeg = buf[start:end + 2]
                            buf = buf[end + 2:]
                            src.set_frame(jpeg)
            except Exception:
                time.sleep(1.0)  # Retry after connection failure

    def _run_usb_webcam(self, src: VideoSource):
        """Capture frames from a USB webcam via OpenCV."""
        from omnix.video.processor import FrameProcessor
        processor = FrameProcessor()

        try:
            import cv2
            cap = cv2.VideoCapture(int(src._uri))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, src.config.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, src.config.height)

            while src._running:
                t0 = time.time()
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.1)
                    continue
                # OpenCV gives BGR — convert to RGB then JPEG
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                jpeg = processor.raw_rgb_to_jpeg(
                    rgb.tobytes(), src.config.width, src.config.height,
                    src.config.jpeg_quality)
                src.set_frame(jpeg)

                elapsed = time.time() - t0
                target_dt = 1.0 / max(1, src.config.target_fps)
                if elapsed < target_dt:
                    time.sleep(target_dt - elapsed)
            cap.release()
        except ImportError:
            # OpenCV not installed — fall back to simulated
            src._sim_camera = SimulatedCamera("drone", src.config.width, src.config.height)
            self._run_simulated(src)
