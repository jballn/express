"""Direct Lua rendering tool.

Takes Lua code, runs it through the Usagi engine on Xvfb,
captures the framebuffer, upscales to 1360x768, writes to /dev/fb0,
and returns the captured image as a base64 data URL.

This is a "pure language function" — the agent formulates the render,
the engine executes it, no review/healing steps.
"""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from express.config import config
from express.renderer.engine import EngineManager, EngineOutput

logger = logging.getLogger(__name__)


@dataclass
class RenderResult:
    """Result of a render_lua tool call."""

    success: bool
    code: str
    issues: list[str]
    console_output: str
    duration_seconds: float
    framebuffer_url: str | None = None
    fb0_written: bool = False
    fb0_size: int = 0


def render_lua(lua_code: str, display_width: int = 320, display_height: int = 180) -> dict[str, Any]:
    """Run Lua code through the Usagi engine and capture the result.

    Pipeline:
    1. Write Lua code to workspace
    2. Start Xvfb on virtual display
    3. Run Usagi with RAYLIB_BACKEND=window
    4. Capture Xvfb frame via ImageMagick import
    5. Upscale to 1360x768 and write to /dev/fb0
    6. Return captured image as base64 data URL

    Args:
        lua_code: Complete Lua script with _init, _update, _draw
        display_width: Xvfb display width (default 320)
        display_height: Xvfb display height (default 180)

    Returns:
        Dict with success status, code, issues, framebuffer image, etc.
    """
    start_time = time.monotonic()
    issues: list[str] = []
    console_output = ""
    framebuffer_url: str | None = None
    fb0_written = False
    fb0_size = 0

    # ── Prepare workspace ──────────────────────────────────────────
    logger.info("render_lua: preparing workspace")
    engine = EngineManager(config)
    engine.prepare_workspace()

    # ── Run Usagi on Xvfb ─────────────────────────────────────────
    logger.info("render_lua: running Usagi on Xvfb")
    # Override Xvfb resolution if needed
    if display_width != 320 or display_height != 180:
        config.xvfb_screen = f"{display_width}x{display_height}x24"

    with engine:
        output = engine.run_headless(lua_code, timeout=config.render_timeout)
        console_output = output.stderr

        if not output.success:
            issues.append(f"Usagi exited with code {output.return_code}")
            if output.stderr:
                issues.append(f"stderr: {output.stderr[:500]}")

    # ── Capture Xvfb frame ────────────────────────────────────────
    logger.info("render_lua: capturing Xvfb frame")
    capture_path = f"/tmp/express_capture_{int(start_time * 1000)}.png"
    framebuffer_url = _capture_xvfb_frame(capture_path, issues)

    # ── Upscale and write to /dev/fb0 ─────────────────────────────
    logger.info("render_lua: upscaling to 1360x768 and writing to /dev/fb0")
    fb0_written, fb0_size = _write_to_framebuffer(capture_path, issues)

    duration = time.monotonic() - start_time
    success = output.success and framebuffer_url is not None

    return RenderResult(
        success=success,
        code=lua_code,
        issues=issues,
        console_output=console_output,
        duration_seconds=round(duration, 3),
        framebuffer_url=framebuffer_url,
        fb0_written=fb0_written,
        fb0_size=fb0_size,
    ).__dict__


def _capture_xvfb_frame(capture_path: str, issues: list[str]) -> str | None:
    """Capture the Xvfb display and save as PNG.

    Returns base64 data URL of the captured frame, or None on failure.
    """
    display = f":{config.xvfb_display}"
    try:
        result = subprocess.run(
            ["import", "-display", display, "-window", "root", "-delay", "0", capture_path],
            env={"DISPLAY": display},
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            issues.append(f"import failed: {result.stderr[:200]}")
            return None

        # Verify we got a real image
        if not Path(capture_path).exists():
            issues.append("import reported success but no file created")
            return None

        # Convert to base64 data URL
        png_bytes = Path(capture_path).read_bytes()
        if len(png_bytes) < 100:
            issues.append(f"capture too small ({len(png_bytes)} bytes), likely empty")
            return None

        b64 = base64.b64encode(png_bytes).decode("ascii")
        return f"data:image/png;base64,{b64}"

    except FileNotFoundError:
        issues.append("ImageMagick 'import' not found")
        return None
    except subprocess.TimeoutExpired:
        issues.append("import timed out")
        return None
    except Exception as e:
        issues.append(f"capture error: {e}")
        return None


def _write_to_framebuffer(capture_path: str, issues: list[str]) -> tuple[bool, int]:
    """Upscale capture to 1360x768 RGBA and write to /dev/fb0.

    Returns (success, bytes_written).
    """
    try:
        # Use magick to: upscale to 1360x768, convert to RGBA 8-bit, output raw
        result = subprocess.run(
            [
                "magick", capture_path,
                "-resize", "1360x768!",
                "-depth", "8",
                "RGBA:-",
            ],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            issues.append(f"magick upscale failed: {result.stderr[:200]}")
            return False, 0

        raw_data = result.stdout
        expected = 1360 * 768 * 4  # RGBA 32-bit
        if len(raw_data) != expected:
            issues.append(f"magick output size mismatch: got {len(raw_data)}, expected {expected}")
            return False, 0

        # Write to framebuffer
        fb_path = Path("/dev/fb0")
        if not fb_path.exists():
            issues.append("/dev/fb0 not found")
            return False, 0

        with open(fb_path, "wb") as f:
            f.write(raw_data)

        return True, len(raw_data)

    except FileNotFoundError:
        issues.append("ImageMagick 'magick' not found")
        return False, 0
    except subprocess.TimeoutExpired:
        issues.append("magick upscale timed out")
        return False, 0
    except PermissionError:
        issues.append("Permission denied writing to /dev/fb0 (try running as root)")
        return False, 0
    except Exception as e:
        issues.append(f"framebuffer write error: {e}")
        return False, 0
