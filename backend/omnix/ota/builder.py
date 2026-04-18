"""
Arduino sketch compilation helper using arduino-cli.

Provides a simple interface to compile Arduino sketches to binaries.
Gracefully handles missing arduino-cli installation with appropriate errors.
"""

from __future__ import annotations

import subprocess
import shutil
from pathlib import Path
from typing import Any

from omnix import get_logger

log = get_logger("omnix.ota.builder")


class FirmwareBuilder:
    """Wrapper around arduino-cli for compiling sketches to firmware binaries."""

    def __init__(self):
        """Initialize builder and check for arduino-cli availability."""
        self._arduino_cli_available = shutil.which("arduino-cli") is not None
        if self._arduino_cli_available:
            log.info("arduino-cli found on PATH")
        else:
            log.debug("arduino-cli not found on PATH; compilation disabled")

    def is_available(self) -> bool:
        """Check if arduino-cli is installed and available.

        Returns:
            True if arduino-cli can be executed, False otherwise
        """
        return self._arduino_cli_available

    def compile(
        self,
        sketch_path: str,
        board_fqbn: str,
        output_dir: str | None = None,
    ) -> dict[str, Any]:
        """Compile an Arduino sketch to a firmware binary.

        Args:
            sketch_path: Path to .ino file (or directory containing it)
            board_fqbn: Arduino board FQBN (e.g., "esp32:esp32:esp32", "arduino:avr:uno")
            output_dir: Optional output directory for compiled binary.
                       If None, uses a temp directory.

        Returns:
            Dict with keys:
              - success (bool): Compilation succeeded
              - binary_path (str|None): Path to .bin or .hex file if successful
              - size (int|None): Binary size in bytes if successful
              - output (str): Compiler stdout
              - error (str|None): Error message if failed
        """
        if not self._arduino_cli_available:
            return {
                "success": False,
                "binary_path": None,
                "size": None,
                "output": "",
                "error": "arduino-cli not installed",
            }

        sketch_path_obj = Path(sketch_path)
        if not sketch_path_obj.exists():
            return {
                "success": False,
                "binary_path": None,
                "size": None,
                "output": "",
                "error": f"Sketch not found: {sketch_path}",
            }

        # Prepare output directory
        if output_dir is None:
            output_dir = str(sketch_path_obj.parent / "build")
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        try:
            # Run arduino-cli compile
            cmd = [
                "arduino-cli",
                "compile",
                "--board",
                board_fqbn,
                "--output-dir",
                str(output_path),
                str(sketch_path_obj),
            ]

            log.debug(f"Running: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,  # 2-minute timeout
            )

            output_text = result.stdout + result.stderr

            if result.returncode != 0:
                log.warning(f"Compilation failed for {sketch_path}:\n{output_text}")
                return {
                    "success": False,
                    "binary_path": None,
                    "size": None,
                    "output": output_text,
                    "error": f"Compilation failed with code {result.returncode}",
                }

            # Find compiled binary (could be .bin or .hex)
            binary_path = None
            binary_size = None

            for ext in [".bin", ".hex", ".elf"]:
                candidates = list(output_path.glob(f"*{ext}"))
                if candidates:
                    binary_path = str(candidates[0])
                    binary_size = candidates[0].stat().st_size
                    break

            if not binary_path:
                log.warning(f"No compiled binary found in {output_path}")
                return {
                    "success": False,
                    "binary_path": None,
                    "size": None,
                    "output": output_text,
                    "error": "No compiled binary produced",
                }

            log.info(
                f"Compiled {sketch_path} -> {binary_path} ({binary_size} bytes)"
            )

            return {
                "success": True,
                "binary_path": binary_path,
                "size": binary_size,
                "output": output_text,
                "error": None,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "binary_path": None,
                "size": None,
                "output": "",
                "error": "Compilation timeout (exceeded 120 seconds)",
            }
        except Exception as e:
            log.error(f"Compilation error: {e}", exc_info=True)
            return {
                "success": False,
                "binary_path": None,
                "size": None,
                "output": "",
                "error": str(e),
            }

    def list_boards(self) -> list[dict[str, str]]:
        """List all available Arduino boards.

        Returns:
            List of dicts with 'fqbn' and 'name' keys, or empty list if
            arduino-cli is not available
        """
        if not self._arduino_cli_available:
            log.debug("Skipping board list: arduino-cli not available")
            return []

        try:
            result = subprocess.run(
                ["arduino-cli", "board", "listall"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                log.warning(f"Failed to list boards: {result.stderr}")
                return []

            boards = []
            # Parse arduino-cli output (tab-separated FQBN and name)
            for line in result.stdout.strip().split("\n"):
                if not line or line.startswith("Board"):
                    continue  # Skip header

                parts = line.split()
                if len(parts) >= 2:
                    fqbn = parts[0]
                    name = " ".join(parts[1:])
                    boards.append({"fqbn": fqbn, "name": name})

            log.debug(f"Found {len(boards)} available boards")
            return boards

        except subprocess.TimeoutExpired:
            log.warning("Board listing timeout")
            return []
        except Exception as e:
            log.error(f"Error listing boards: {e}", exc_info=True)
            return []
