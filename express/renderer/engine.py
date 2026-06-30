"""Usagi Engine process management.

Handles launching, controlling, and monitoring the Usagi binary.
Manages the workspace, writes Lua payloads, and captures output.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from express.config import Config

logger = logging.getLogger(__name__)


@dataclass
class EngineOutput:
    """Captured output from a Usagi process run."""

    stdout: str
    """Standard output from the process."""
    stderr: str
    """Standard error (including Lua stack traces)."""
    return_code: int
    """Process exit code."""
    success: bool
    """Whether the process completed without crashing."""
    duration_seconds: float
    """Wall-clock time of the run."""


class EngineManager:
    """Manages the Usagi Engine process lifecycle.

    Usage:
        mgr = EngineManager(config)
        mgr.prepare_workspace()
        output = mgr.run_with_code(lua_code)
        print(output.stdout)
        print(output.stderr)
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self._process: Optional[subprocess.Popen[bytes]] = None
        self._xvfb_process: Optional[subprocess.Popen[bytes]] = None
        self._xvfb_started: bool = False

    def start_xvfb(self) -> None:
        """Start an Xvfb virtual display for headless rendering.

        Only starts if not already running. Stores PID for cleanup.
        If Xvfb is already running on the target display, uses it
        without starting a new instance.
        """
        if self._xvfb_started and self._xvfb_process is not None:
            # Check if still alive
            if self._xvfb_process.poll() is None:
                return
            self._xvfb_started = False

        display = f":{self.config.xvfb_display}"
        screen = self.config.xvfb_screen
        pid_file = self.config.xvfb_pid_file

        # Check if Xvfb is already running on this display
        display_socket = Path(f"/tmp/.X11-unix/X{self.config.xvfb_display}")
        if display_socket.exists():
            logger.info("Xvfb already running on display %s", display)
            self._xvfb_started = False  # Don't track external Xvfb
            return

        logger.info("Starting Xvfb on display %s (%s)", display, screen)
        self._xvfb_process = subprocess.Popen(
            args=[
                "Xvfb",
                display,
                "-screen",
                "0",
                screen,
                "-nolisten",
                "tcp",
                "-noreset",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Write PID file for external tracking
        pid_file.write_text(str(self._xvfb_process.pid))

        # Brief wait to let Xvfb initialize
        time.sleep(0.5)

        if self._xvfb_process.poll() is not None:
            stderr = self._xvfb_process.stderr.read().decode("utf-8", errors="replace")  # type: ignore[union-attr]
            raise RuntimeError(f"Xvfb failed to start: {stderr}")

        self._xvfb_started = True
        logger.info("Xvfb started (PID %d)", self._xvfb_process.pid)

    def stop_xvfb(self) -> None:
        """Stop the Xvfb virtual display if we started it."""
        if not self._xvfb_started or self._xvfb_process is None:
            return

        logger.info("Stopping Xvfb (PID %d)", self._xvfb_process.pid)
        self._xvfb_process.terminate()
        try:
            self._xvfb_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._xvfb_process.kill()
            self._xvfb_process.wait()

        self._xvfb_started = False
        self._xvfb_process = None

        # Clean up PID file
        pid_file = self.config.xvfb_pid_file
        if pid_file.exists():
            pid_file.unlink()

        logger.info("Xvfb stopped")

    def __enter__(self) -> EngineManager:
        return self

    def __exit__(self, *args: object) -> None:
        self.stop_xvfb()

    def prepare_workspace(self) -> None:
        """Set up the Usagi workspace with skeleton files."""
        self.config.ensure_workspace()
        self.config.ensure_skeleton()
        logger.info("Usagi workspace ready at %s", self.config.usagi_workspace)

    def run_with_code(self, lua_code: str, timeout: float | None = None) -> EngineOutput:
        """Write Lua code to the workspace payload file, run Usagi, capture output.

        If capture_method is 'xvfb', starts Xvfb, runs Usagi with
        RAYLIB_BACKEND=window pointing at the virtual display, then
        captures the frame via ImageMagick import.

        Args:
            lua_code: Complete Lua script returning {_init, _update, _draw}
            timeout: Override default render timeout

        Returns:
            EngineOutput with stdout, stderr, and success status
        """
        timeout = timeout or self.config.render_timeout

        # Write the dynamic payload
        self.config.payload_lua.write_text(lua_code, encoding="utf-8")
        logger.debug("Wrote %d bytes to payload file", len(lua_code))

        # Ensure workspace has required assets
        self._ensure_assets()

        # Launch Usagi in DRM mode
        env = self._build_env()
        start_time = time.monotonic()

        try:
            proc = subprocess.Popen(
                args=[
                    str(self.config.usagi_bin),
                    "run",
                    str(self.config.usagi_workspace),
                ],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.config.usagi_workspace),
            )
            self._process = proc

            # Wait for completion with timeout
            try:
                stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout_bytes, stderr_bytes = proc.communicate()
                return EngineOutput(
                    stdout=stdout_bytes.decode("utf-8", errors="replace"),
                    stderr=stderr_bytes.decode("utf-8", errors="replace"),
                    return_code=-1,
                    success=False,
                    duration_seconds=time.monotonic() - start_time,
                )

            duration = time.monotonic() - start_time
            success = proc.returncode == 0

            return EngineOutput(
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                return_code=proc.returncode or 0,
                success=success,
                duration_seconds=duration,
            )

        except FileNotFoundError:
            logger.error("Usagi binary not found: %s", self.config.usagi_bin)
            return EngineOutput(
                stdout="",
                stderr=f"Usagi binary not found: {self.config.usagi_bin}",
                return_code=-1,
                success=False,
                duration_seconds=time.monotonic() - start_time,
            )

    def run_headless(self, lua_code: str, timeout: float | None = None) -> EngineOutput:
        """Run Usagi in headless mode via Xvfb.

        Starts Xvfb on the configured display, sets RAYLIB_BACKEND=window,
        runs Usagi, then captures the frame via ImageMagick import.

        Uses context manager semantics: Xvfb is started before the run
        and stopped after (even on error/timeout).
        """
        timeout = timeout or self.config.render_timeout

        with self:
            self.start_xvfb()

            env = self._build_env(headless=True)
            self.config.payload_lua.write_text(lua_code, encoding="utf-8")
            self._ensure_assets()

            start_time = time.monotonic()
            try:
                proc = subprocess.Popen(
                    args=[
                        str(self.config.usagi_bin),
                        "run",
                        str(self.config.usagi_workspace),
                    ],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(self.config.usagi_workspace),
                )
                try:
                    stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    stdout_bytes, stderr_bytes = proc.communicate()
                    return EngineOutput(
                        stdout=stdout_bytes.decode("utf-8", errors="replace"),
                        stderr=stderr_bytes.decode("utf-8", errors="replace"),
                        return_code=-1,
                        success=False,
                        duration_seconds=time.monotonic() - start_time,
                    )

                return EngineOutput(
                    stdout=stdout_bytes.decode("utf-8", errors="replace"),
                    stderr=stderr_bytes.decode("utf-8", errors="replace"),
                    return_code=proc.returncode or 0,
                    success=proc.returncode == 0,
                    duration_seconds=time.monotonic() - start_time,
                )
            except FileNotFoundError:
                return EngineOutput(
                    stdout="",
                    stderr=f"Usagi binary not found: {self.config.usagi_bin}",
                    return_code=-1,
                    success=False,
                    duration_seconds=time.monotonic() - start_time,
                )

    def _build_env(self, headless: bool = False) -> dict[str, str]:
        """Build environment variables for the Usagi process."""
        env = os.environ.copy()
        env["RAYLIB_BACKEND"] = "drm" if not headless else "window"
        env["FRAMEBUFFER"] = str(self.config.framebuffer)
        env["USAGI_WORKSPACE"] = str(self.config.usagi_workspace)
        if headless:
            env["DISPLAY"] = f":{self.config.xvfb_display}"
        return env

    def _ensure_assets(self) -> None:
        """Create minimal required assets in the workspace."""
        workspace = self.config.usagi_workspace
        workspace.mkdir(parents=True, exist_ok=True)

        # Create sprites.png (16x16 white pixel, the minimal sprite sheet)
        sprites_path = workspace / "sprites.png"
        if not sprites_path.exists():
            from PIL import Image
            img = Image.new("RGBA", (16, 16), (255, 255, 255, 255))
            img.save(str(sprites_path))

        # Create palette.png (16 colors, 1px tall)
        palette_path = workspace / "palette.png"
        if not palette_path.exists():
            # Pico-8 palette as 16x1 PNG
            from PIL import Image
            import struct
            pico8_colors = [
                (0, 0, 0, 255),       # 0: black
                (16, 16, 16, 255),    # 1: dark gray
                (68, 53, 132, 255),   # 2: purple
                (129, 56, 169, 255),  # 3: magenta
                (130, 40, 96, 255),   # 4: dark magenta
                (208, 36, 96, 255),   # 5: red
                (240, 132, 72, 255),  # 6: orange
                (248, 176, 76, 255),  # 7: yellow
                (128, 176, 60, 255),  # 8: green
                (72, 176, 92, 255),   # 9: teal
                (40, 168, 136, 255),  # 10: cyan
                (76, 140, 184, 255),  # 11: blue
                (40, 80, 140, 255),   # 12: dark blue
                (104, 72, 140, 255),  # 13: lavender
                (156, 152, 152, 255), # 14: light gray
                (248, 248, 248, 255), # 15: white
            ]
            img = Image.new("RGBA", (16, 1), color=(255, 255, 255, 255))
            pixels = img.load()
            for i, (r, g, b, a) in enumerate(pico8_colors):
                pixels[i, 0] = (r, g, b, a)
            img.save(str(palette_path))

        # Create _config.lua
        config_path = workspace / "_config.lua"
        if not config_path.exists():
            config_path.write_text(
                "-- Pico-8 style config\n"
                "_config = {\n"
                "    game_id = \"express.default\",\n"
                "    title = \"Express\",\n"
                "    width = 320,\n"
                "    height = 180,\n"
                "}\n",
                encoding="utf-8",
            )

        logger.debug("Minimal assets created in workspace")
