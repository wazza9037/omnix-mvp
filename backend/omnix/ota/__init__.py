"""
OTA (Over-the-Air) Firmware Update System

Provides a complete firmware management and deployment pipeline for OMNIX devices:

  manager.OTAManager
    - Stores firmware binaries and metadata
    - Tracks versions, checksums, platform compatibility
    - Preloads existing Arduino sketches as source firmware

  deployer.OTADeployer
    - Orchestrates device-level firmware deployments
    - Manages deployment states and progress
    - Supports rollback to previous versions
    - Auto-rollback on device timeout

  builder.FirmwareBuilder
    - Compiles Arduino sketches using arduino-cli
    - Gracefully handles missing arduino-cli installation
    - Lists available Arduino boards
"""

from .manager import OTAManager
from .deployer import OTADeployer
from .builder import FirmwareBuilder

__all__ = [
    "OTAManager",
    "OTADeployer",
    "FirmwareBuilder",
]
