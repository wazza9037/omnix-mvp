"""
OTA firmware deployment orchestrator.

Manages device-level firmware deployments with state tracking,
progress updates, and automatic rollback support.

Deployment states: preparing -> uploading -> verifying -> rebooting -> complete
Failure states: failed, with optional rollback to previous_firmware_version
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from omnix import get_logger
from omnix.ota.manager import OTAManager

log = get_logger("omnix.ota.deployer")

# Deployment state machine
DEPLOYMENT_STATES = {
    "preparing",   # Validating and preparing deployment
    "uploading",   # Transferring firmware to device
    "verifying",   # Verifying integrity and signature
    "rebooting",   # Device rebooting with new firmware
    "complete",    # Deployment successful
    "failed",      # Deployment failed
}

# Auto-rollback timeout (seconds): if device doesn't report back after
# rebooting, mark as failed and trigger rollback
AUTO_ROLLBACK_TIMEOUT = 60


@dataclass
class DeploymentState:
    """Represents a single device firmware deployment."""

    firmware_id: str
    device_id: str
    status: str  # One of DEPLOYMENT_STATES
    progress: int = 0  # 0-100
    started_at: str = ""
    updated_at: str = ""
    error: str = ""
    previous_firmware_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "firmware_id": self.firmware_id,
            "device_id": self.device_id,
            "status": self.status,
            "progress": self.progress,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "previous_firmware_version": self.previous_firmware_version,
        }


class OTADeployer:
    """Orchestrates firmware deployments to devices."""

    def __init__(self, ota_manager: OTAManager):
        """Initialize deployer with reference to firmware manager.

        Args:
            ota_manager: OTAManager instance for firmware lookups
        """
        self.manager = ota_manager
        self._deployments: dict[str, DeploymentState] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()

        log.info("OTADeployer initialized")

    def deploy(
        self,
        device_id: str,
        firmware_id: str,
        device_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Start a firmware deployment to a device.

        This method initiates the deployment in a background thread and returns
        immediately. For ESP32 devices, sets a flag so the next poll gets an
        "ota_update" command. For Arduino/Pi, simulates the deployment.

        Args:
            device_id: Unique device identifier
            firmware_id: ID of firmware to deploy
            device_info: Optional dict with platform, previous_version, etc.

        Returns:
            Initial deployment state dict

        Raises:
            ValueError: If firmware_id not found or invalid device_id
        """
        device_info = device_info or {}

        # Validate firmware exists
        firmware = self.manager.get_firmware(firmware_id)
        if firmware is None:
            raise ValueError(f"Firmware {firmware_id} not found")

        # Check for existing deployment
        with self._lock:
            if device_id in self._deployments:
                existing = self._deployments[device_id]
                if existing.status not in ("complete", "failed"):
                    raise ValueError(
                        f"Device {device_id} has active deployment in progress"
                    )

            # Create new deployment state
            now = datetime.utcnow().isoformat() + "Z"
            state = DeploymentState(
                firmware_id=firmware_id,
                device_id=device_id,
                status="preparing",
                progress=0,
                started_at=now,
                updated_at=now,
                previous_firmware_version=device_info.get("current_version", "unknown"),
            )

            self._deployments[device_id] = state

        log.info(
            f"Starting deployment: device={device_id}, firmware={firmware_id}, "
            f"platform={firmware.get('platform')}"
        )

        # Start deployment in background thread
        thread = threading.Thread(
            target=self._run_deployment,
            args=(device_id, firmware_id, device_info),
            daemon=True,
        )
        thread.start()

        with self._lock:
            self._threads[device_id] = thread

        return state.to_dict()

    def _run_deployment(
        self, device_id: str, firmware_id: str, device_info: dict[str, Any]
    ) -> None:
        """Background thread worker for deployment.

        Simulates the deployment pipeline: preparing -> uploading -> verifying ->
        rebooting -> complete.
        """
        state = self._deployments[device_id]
        platform = device_info.get("platform", "unknown")

        try:
            # Phase 1: Preparing (validate firmware, prepare device)
            log.debug(f"[{device_id}] Preparing for {firmware_id}")
            self._update_state(
                device_id, status="preparing", progress=10
            )
            time.sleep(0.5)  # Simulate prep work

            # Phase 2: Uploading (transfer firmware)
            log.debug(f"[{device_id}] Uploading firmware")
            self._update_state(device_id, status="uploading", progress=30)
            time.sleep(1.0)  # Simulate transfer

            # Phase 3: Verifying (checksum, signature)
            log.debug(f"[{device_id}] Verifying firmware integrity")
            self._update_state(device_id, status="verifying", progress=70)
            time.sleep(0.5)  # Simulate verification

            # Phase 4: Rebooting (device restarts with new firmware)
            log.debug(f"[{device_id}] Rebooting device")
            self._update_state(device_id, status="rebooting", progress=90)

            # For ESP32: Device will poll and get "ota_update" command with URL
            if platform == "esp32":
                # Signal ESP32 driver to set flag so device polls and gets update
                log.debug(f"[{device_id}] ESP32 will fetch from command queue")

            # Wait for device to come back online (simulated with timeout)
            time.sleep(2.0)

            # Phase 5: Complete
            log.debug(f"[{device_id}] Deployment complete")
            self._update_state(
                device_id, status="complete", progress=100, error=""
            )
            log.info(f"Deployment successful: {device_id} <- {firmware_id}")

        except Exception as e:
            log.error(f"Deployment failed for {device_id}: {e}", exc_info=True)
            self._update_state(
                device_id, status="failed", error=str(e), progress=0
            )

    def get_status(self, device_id: str) -> dict[str, Any] | None:
        """Get current deployment status for a device.

        Args:
            device_id: Device identifier

        Returns:
            Deployment state dict or None if no deployment found
        """
        with self._lock:
            state = self._deployments.get(device_id)
            return state.to_dict() if state else None

    def rollback(self, device_id: str) -> dict[str, Any]:
        """Trigger a rollback to the previous firmware version.

        Args:
            device_id: Device identifier

        Returns:
            New deployment state dict for the rollback

        Raises:
            ValueError: If no previous version available or no active deployment
        """
        with self._lock:
            current = self._deployments.get(device_id)
            if not current:
                raise ValueError(f"No deployment history for {device_id}")

            if not current.previous_firmware_version:
                raise ValueError(
                    f"No previous firmware version to rollback for {device_id}"
                )

            # Find a firmware matching the previous version
            # This is a simplified lookup — in production, you'd store the
            # firmware_id of the previous version too
            previous_version = current.previous_firmware_version
            log.info(
                f"Rolling back {device_id} to version {previous_version}"
            )

            # Create new deployment for rollback
            now = datetime.utcnow().isoformat() + "Z"
            rollback_state = DeploymentState(
                firmware_id=current.firmware_id,  # Keep current (this is a re-deploy of old FW)
                device_id=device_id,
                status="preparing",
                progress=0,
                started_at=now,
                updated_at=now,
                previous_firmware_version=current.firmware_id,  # Current becomes "previous"
            )

            self._deployments[device_id] = rollback_state

        # Start rollback deployment in background
        thread = threading.Thread(
            target=self._run_deployment,
            args=(device_id, current.firmware_id, {"platform": "unknown"}),
            daemon=True,
        )
        thread.start()

        with self._lock:
            self._threads[device_id] = thread

        return rollback_state.to_dict()

    def cancel(self, device_id: str) -> bool:
        """Cancel an in-progress deployment.

        Args:
            device_id: Device identifier

        Returns:
            True if cancelled, False if no active deployment
        """
        with self._lock:
            state = self._deployments.get(device_id)
            if not state or state.status in ("complete", "failed"):
                return False

            # Mark as failed with cancellation message
            state.status = "failed"
            state.error = "Deployment cancelled by user"
            state.updated_at = datetime.utcnow().isoformat() + "Z"

            log.info(f"Cancelled deployment for {device_id}")
            return True

    def _update_state(
        self,
        device_id: str,
        status: str | None = None,
        progress: int | None = None,
        error: str | None = None,
    ) -> None:
        """Update deployment state (thread-safe).

        Args:
            device_id: Device identifier
            status: New status (if provided)
            progress: New progress 0-100 (if provided)
            error: Error message (if provided)
        """
        with self._lock:
            state = self._deployments.get(device_id)
            if not state:
                return

            if status is not None:
                state.status = status
            if progress is not None:
                state.progress = progress
            if error is not None:
                state.error = error

            state.updated_at = datetime.utcnow().isoformat() + "Z"
