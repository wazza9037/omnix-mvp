"""
OTA (Over-the-Air) firmware update manager.

Handles storage, metadata tracking, and retrieval of firmware binaries
for different target platforms (ESP32, Arduino, Pi, etc.).

Firmware binaries are stored in firmware_store/ with metadata tracked in
firmware_store/metadata.json. Each entry includes checksums, compatibility
information, and version details.
"""

from __future__ import annotations

import json
import os
import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4
from datetime import datetime

from omnix import get_logger

log = get_logger("omnix.ota.manager")

# Supported target platforms
SUPPORTED_PLATFORMS = {"esp32", "arduino_uno", "arduino_mega", "rp2040", "esp8266"}


class OTAManager:
    """Manages firmware storage, versioning, and metadata."""

    def __init__(self, firmware_store_path: str | None = None):
        """Initialize OTAManager with a firmware store directory.

        Args:
            firmware_store_path: Path to firmware storage directory. If None,
                                uses firmware_store/ relative to backend/.
        """
        if firmware_store_path is None:
            # firmware_store/ sits next to backend/ (in the project root)
            backend_root = Path(__file__).resolve().parent.parent.parent
            firmware_store_path = backend_root.parent / "firmware_store"

        self.firmware_store = Path(firmware_store_path)
        self.metadata_file = self.firmware_store / "metadata.json"

        # Ensure directories exist
        self.firmware_store.mkdir(parents=True, exist_ok=True)

        # Load existing metadata or initialize empty
        self._metadata: dict[str, Any] = self._load_metadata()

        log.info(f"OTAManager initialized at {self.firmware_store}")

    def _load_metadata(self) -> dict[str, Any]:
        """Load metadata from disk. Returns empty dict if file doesn't exist."""
        if not self.metadata_file.exists():
            return {}

        try:
            with open(self.metadata_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            log.warning(f"Failed to load metadata: {e}. Starting fresh.")
            return {}

    def _save_metadata(self) -> None:
        """Persist metadata to disk."""
        try:
            with open(self.metadata_file, "w") as f:
                json.dump(self._metadata, f, indent=2)
        except IOError as e:
            log.error(f"Failed to save metadata: {e}")
            raise

    def _compute_checksum(self, data: bytes) -> str:
        """Compute SHA256 checksum of binary data."""
        return hashlib.sha256(data).hexdigest()

    def upload_firmware(
        self,
        name: str,
        version: str,
        platform: str,
        binary_data: bytes,
        description: str = "",
        compatible_devices: list[str] | None = None,
    ) -> dict[str, Any]:
        """Upload and register a new firmware binary.

        Args:
            name: Human-readable firmware name (e.g., "OMNIX ESP32 Standard")
            version: Semantic version string (e.g., "1.0.0")
            platform: Target platform (esp32, arduino_uno, arduino_mega, rp2040, esp8266)
            binary_data: Raw binary content
            description: Optional description
            compatible_devices: List of device types this firmware is compatible with

        Returns:
            Metadata dict for the uploaded firmware

        Raises:
            ValueError: If platform is unsupported or name/version are invalid
        """
        if not name or not name.strip():
            raise ValueError("Firmware name cannot be empty")
        if not version or not version.strip():
            raise ValueError("Firmware version cannot be empty")
        if platform not in SUPPORTED_PLATFORMS:
            raise ValueError(f"Unsupported platform: {platform}. Supported: {SUPPORTED_PLATFORMS}")

        # Generate firmware ID from UUID
        fw_id = uuid4().hex[:8]

        # Compute checksum
        checksum = self._compute_checksum(binary_data)

        # Create binary file
        binary_path = self.firmware_store / f"{fw_id}.bin"
        try:
            binary_path.write_bytes(binary_data)
        except IOError as e:
            log.error(f"Failed to write firmware binary: {e}")
            raise

        # Create metadata entry
        now = datetime.utcnow().isoformat() + "Z"
        metadata_entry = {
            "id": fw_id,
            "name": name.strip(),
            "version": version.strip(),
            "platform": platform,
            "file_size": len(binary_data),
            "checksum": checksum,
            "upload_date": now,
            "description": description.strip() if description else "",
            "compatible_devices": compatible_devices or [],
        }

        self._metadata[fw_id] = metadata_entry
        self._save_metadata()

        log.info(
            f"Uploaded firmware {fw_id}: {name} v{version} for {platform} "
            f"({len(binary_data)} bytes)"
        )

        return metadata_entry

    def list_firmware(self) -> list[dict[str, Any]]:
        """List all firmware entries sorted by upload date (newest first)."""
        entries = list(self._metadata.values())
        # Sort by upload_date descending (newest first)
        entries.sort(key=lambda x: x.get("upload_date", ""), reverse=True)
        return entries

    def get_firmware(self, firmware_id: str) -> dict[str, Any] | None:
        """Get metadata for a specific firmware entry.

        Args:
            firmware_id: The 8-character firmware ID

        Returns:
            Metadata dict or None if not found
        """
        return self._metadata.get(firmware_id)

    def get_firmware_binary(self, firmware_id: str) -> bytes | None:
        """Get the binary content of a firmware.

        Args:
            firmware_id: The 8-character firmware ID

        Returns:
            Binary data or None if not found
        """
        if firmware_id not in self._metadata:
            return None

        binary_path = self.firmware_store / f"{firmware_id}.bin"
        if not binary_path.exists():
            log.warning(f"Binary file missing for firmware {firmware_id}")
            return None

        try:
            return binary_path.read_bytes()
        except IOError as e:
            log.error(f"Failed to read firmware binary {firmware_id}: {e}")
            return None

    def delete_firmware(self, firmware_id: str) -> bool:
        """Delete a firmware entry and its binary.

        Args:
            firmware_id: The 8-character firmware ID

        Returns:
            True if deleted, False if not found
        """
        if firmware_id not in self._metadata:
            return False

        # Delete binary file if it exists
        binary_path = self.firmware_store / f"{firmware_id}.bin"
        try:
            if binary_path.exists():
                binary_path.unlink()
        except IOError as e:
            log.warning(f"Failed to delete binary file for {firmware_id}: {e}")

        # Remove metadata
        del self._metadata[firmware_id]
        self._save_metadata()

        log.info(f"Deleted firmware {firmware_id}")
        return True

    def get_compatible_firmware(
        self, device_type: str, platform: str | None = None
    ) -> list[dict[str, Any]]:
        """Get firmware entries compatible with a device type.

        Args:
            device_type: Device type name (e.g., "lights", "rover", "sensor")
            platform: Optional filter by platform

        Returns:
            List of compatible firmware entries sorted by upload date (newest first)
        """
        compatible = []

        for entry in self._metadata.values():
            # Check if device_type is in compatible_devices
            if device_type not in (entry.get("compatible_devices") or []):
                continue

            # Check platform filter if provided
            if platform and entry.get("platform") != platform:
                continue

            compatible.append(entry)

        # Sort by upload_date descending (newest first)
        compatible.sort(key=lambda x: x.get("upload_date", ""), reverse=True)
        return compatible

    def preload_existing_sketches(self) -> None:
        """Scan for and register existing Arduino sketches as source firmware.

        Reads sketches from connectors/firmware/ and registers them as
        source-type firmware entries (not compiled binaries).
        """
        sketches = [
            ("connectors/firmware/esp32_omnix.ino", "esp32"),
            ("connectors/firmware/esp32_omnix_ota.ino", "esp32"),
            ("connectors/firmware/arduino_omnix.ino", "arduino_uno"),
        ]

        # backend/ directory is two levels up from omnix/ota/
        backend_root = Path(__file__).resolve().parent.parent.parent

        for sketch_rel_path, platform in sketches:
            sketch_path = backend_root / sketch_rel_path

            if not sketch_path.exists():
                log.debug(f"Sketch not found: {sketch_path}")
                continue

            try:
                source_code = sketch_path.read_text(encoding="utf-8")
                # Extract version from comments if available
                version = "source"
                if "v" in sketch_path.name.lower():
                    # Try to extract version from filename
                    parts = sketch_path.stem.split("_")
                    for part in parts:
                        if part.startswith("v") and len(part) > 1:
                            version = part[1:]  # e.g., v1.0.0 -> 1.0.0
                            break

                # Register sketch entry (not a binary)
                sketch_stem = sketch_path.stem.replace(".", "_")
                sketch_id = f"src_{sketch_stem[:12]}"
                metadata_entry = {
                    "id": sketch_id,
                    "name": f"OMNIX {platform.title()} Source",
                    "version": version,
                    "platform": platform,
                    "file_size": len(source_code.encode()),
                    "checksum": self._compute_checksum(source_code.encode()),
                    "upload_date": datetime.utcnow().isoformat() + "Z",
                    "description": "Arduino sketch source (not compiled binary)",
                    "compatible_devices": ["all"],
                    "type": "source",
                    "sketch_path": str(sketch_rel_path),
                }

                self._metadata[sketch_id] = metadata_entry
                log.info(f"Registered sketch source: {sketch_id} from {sketch_rel_path}")

            except (IOError, UnicodeDecodeError) as e:
                log.warning(f"Failed to read sketch {sketch_path}: {e}")

        # Save metadata with sketches
        if any(fw_id.startswith("src_") for fw_id in self._metadata):
            self._save_metadata()
            log.info("Preloaded sketches saved to metadata")
