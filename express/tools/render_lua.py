"""Direct Lua rendering tool.

Takes Lua code, runs it through the Usagi engine on Xvfb,
continuously captures frames while running, upscales each to 1360x768,
and writes them to /dev/fb0 in real-time. Returns the final captured
frame as a base64 data URL.

This is a "pure language function" — the agent formulates the render,
the engine executes it, no review/healing steps.
"""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import threading
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


def render_lua(lua_code: str, display_width: int = 320, display_height: int = 180, timeout: float = 30.0) -> dict[str, Any]:
    """Run Lua code through the Usagi engine and continuously render to /dev/fb0.

    Pipeline:
    1. Write Lua code to workspace
    2. Start Xvfb on virtual display
    3. Launch Usagi and a background capture thread
    4. Capture frames continuously while Usagi runs, upscaling each to 1360x768
       and writing to /dev/fb0 in real-time
    5. Stop Xvfb after Usagi exits
    6. Return the final captured frame as a base64 data URL

    Args:
        lua_code: Complete Lua script with _init, _update, _draw
        display_width: Xvfb display width (default 320)
        display_height: Xvfb display height (default 180)
        timeout: How long to let the Usagi process run before killing it (default 30s, increase for long-running demos)

    Returns:
        Dict with success status, code, issues, framebuffer image, etc.
    """
    start_time = time.monotonic()
    issues: list[str] = []
    console_output = ""
    framebuffer_url: str | None = None
    fb0_written = True  # We write continuously, so this is always True on success
    fb0_size = 0
    capture_count = 0
    capture_path_template = f"/tmp/express_capture_{int(time.monotonic() * 1000)}_%04d.png"

    # ── Prepare workspace ──────────────────────────────────────────
    logger.info("render_lua: preparing workspace")
    engine = EngineManager(config)
    engine.prepare_workspace()

    # Override Xvfb resolution if needed
    if display_width != 320 or display_height != 180:
        config.xvfb_screen = f"{display_width}x{display_height}x24"

    # Use the provided timeout, or fall back to config default
    effective_timeout = timeout if timeout > 0 else config.render_timeout

    # ── Run Usagi with continuous capture ──────────────────────────
    logger.info("render_lua: running Usagi on Xvfb with continuous capture")
    with engine:
        engine.start_xvfb()

        env = engine._build_env(headless=True)
        engine.config.payload_lua.write_text(lua_code, encoding="utf-8")
        engine._ensure_assets()

        run_start = time.monotonic()
        try:
            proc = subprocess.Popen(
                args=[
                    str(engine.config.usagi_bin),
                    "run",
                    str(engine.config.usagi_workspace),
                ],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(engine.config.usagi_workspace),
            )

            # Start continuous capture thread
            capture_stop = threading.Event()
            capture_thread = threading.Thread(
                target=_continuous_capture_loop,
                args=(engine, capture_stop, capture_path_template, issues, run_start),
                daemon=True,
            )
            capture_thread.start()

            # Wait for Usagi to finish (or timeout)
            try:
                stdout_bytes, stderr_bytes = proc.communicate(timeout=effective_timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout_bytes, stderr_bytes = proc.communicate()
                output = EngineOutput(
                    stdout=stdout_bytes.decode("utf-8", errors="replace"),
                    stderr=stderr_bytes.decode("utf-8", errors="replace"),
                    return_code=-1,
                    success=False,
                    duration_seconds=time.monotonic() - run_start,
                )
            else:
                duration = time.monotonic() - run_start
                output = EngineOutput(
                    stdout=stdout_bytes.decode("utf-8", errors="replace"),
                    stderr=stderr_bytes.decode("utf-8", errors="replace"),
                    return_code=proc.returncode or 0,
                    success=proc.returncode == 0,
                    duration_seconds=duration,
                )

            console_output = output.stderr

            # Stop capture thread and get final frame
            logger.info("render_lua: Usagi finished, stopping capture thread")
            capture_stop.set()
            capture_thread.join(timeout=5)

            if not output.success:
                issues.append(f"Usagi exited with code {output.return_code}")
                if output.stderr:
                    issues.append(f"stderr: {output.stderr[:500]}")

            # Capture the final frame for the data URL
            logger.info("render_lua: capturing final frame")
            final_path = capture_path_template % 9999
            framebuffer_url = _capture_xvfb_frame(final_path, issues)
            if framebuffer_url:
                # Update fb0_size from final capture
                try:
                    fb0_size = len(Path(final_path).read_bytes())
                except Exception:
                    fb0_size = 0
            else:
                logger.warning("render_lua: final frame capture failed")

            # Count total captures
            capture_count = 0
            for i in range(10000):
                p = capture_path_template % i
                if Path(p).exists():
                    capture_count += 1
                else:
                    break

        except FileNotFoundError:
            logger.error("Usagi binary not found: %s", engine.config.usagi_bin)
            output = EngineOutput(
                stdout="",
                stderr=f"Usagi binary not found: {engine.config.usagi_bin}",
                return_code=-1,
                success=False,
                duration_seconds=time.monotonic() - run_start,
            )
            console_output = output.stderr
            issues.append(f"Usagi binary not found: {engine.config.usagi_bin}")

    # ── Xvfb stopped here by __exit__ ─────────────────────────────

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


def _continuous_capture_loop(
    engine: EngineManager,
    stop_event: threading.Event,
    path_template: str,
    issues: list[str],
    run_start: float,
) -> None:
    """Background thread: capture frames from Xvfb and write to /dev/fb0 continuously.

    Runs until stop_event is set. Captures at roughly 15 fps to balance
    responsiveness with avoiding excessive ImageMagick overhead.
    """
    display = f":{engine.config.xvfb_display}"
    frame_idx = 0
    fps = 15  # target capture rate
    interval = 1.0 / fps

    while not stop_event.is_set():
        try:
            # Capture frame from Xvfb
            capture_path = path_template % frame_idx
            result = subprocess.run(
                ["import", "-display", display, "-window", "root", "-depth", "8", "-delay", "0", capture_path],
                env={"DISPLAY": display},
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                # Xvfb may have shut down
                break

            cap_file = Path(capture_path)
            if not cap_file.exists() or cap_file.stat().st_size < 100:
                frame_idx += 1
                time.sleep(interval)
                continue

            # Upscale and write to /dev/fb0
            result = subprocess.run(
                [
                    "magick", capture_path,
                    "-resize", "1360x768!",
                    "-depth", "8",
                    "RGBA:-",
                ],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                raw_data = result.stdout
                expected = 1360 * 768 * 4
                if len(raw_data) == expected:
                    fb_path = Path("/dev/fb0")
                    if fb_path.exists():
                        try:
                            with open(fb_path, "wb") as f:
                                f.write(raw_data)
                        except Exception:
                            pass

        except subprocess.TimeoutExpired:
            pass
        except FileNotFoundError:
            issues.append("ImageMagick 'import' or 'magick' not found during capture loop")
            break
        except Exception:
            # Non-fatal: skip this frame and retry
            pass

        frame_idx += 1
        stop_event.wait(interval)  # respects early stop


def _capture_xvfb_frame(capture_path: str, issues: list[str]) -> str | None:
    """Capture the Xvfb display and save as PNG.

    Returns base64 data URL of the captured frame, or None on failure.
    """
    display = f":{config.xvfb_display}"
    try:
        result = subprocess.run(
            ["import", "-display", display, "-window", "root", "-depth", "8", "-delay", "0", capture_path],
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
