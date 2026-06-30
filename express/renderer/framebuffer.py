"""Framebuffer capture for screen analysis.

Supports multiple capture methods:
- fbgrab: uses the fbgrab utility (preferred, captures DRM framebuffer)
- fb0: reads /dev/fb0 directly
- screenshot: uses a screenshot utility (scrot, grim, etc.)
"""

from __future__ import annotations

import base64
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from express.config import Config

logger = logging.getLogger(__name__)


@dataclass
class FramebufferSnapshot:
    """A captured frame from the display."""

    data_url: str
    """Base64-encoded PNG as data URL."""
    raw_bytes: bytes
    """Raw PNG bytes."""
    width: int
    """Downsampled width."""
    height: int
    """Downsampled height."""
    method: str
    """Capture method used."""


class FramebufferCapture:
    """Captures screenshots from the Linux framebuffer/DRM."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.target_width = config.canvas_width
        self.target_height = config.canvas_height

    def capture(self) -> FramebufferSnapshot:
        """Capture the current screen and return a downsampled snapshot.

        Uses the configured capture method to grab the framebuffer,
        then downsamples to 320x180.
        """
        method = self.config.capture_method

        if method == "fbgrab":
            return self._capture_fbgrab()
        elif method == "fb0":
            return self._capture_fb0()
        elif method == "screenshot":
            return self._capture_screenshot()
        elif method == "xvfb":
            return self._capture_xvfb()
        else:
            raise ValueError(f"Unknown capture method: {method}")

    def capture_base64(self) -> str:
        """Capture and return just the base64 data URL string."""
        snapshot = self.capture()
        return snapshot.data_url

    def write_to_framebuffer(self, snapshot: FramebufferSnapshot) -> None:
        """Write a captured frame to the physical framebuffer for display.

        Converts the captured PNG (which may be from Xvfb, fbgrab, or fb0)
        into raw framebuffer data and writes it to /dev/fb0.

        Args:
            snapshot: A FramebufferSnapshot containing the frame data
        """
        fb_path = self.config.framebuffer
        if not fb_path.exists():
            raise FileNotFoundError(f"Framebuffer not found: {fb_path}")

        from PIL import Image
        import io

        # Decode the PNG from raw_bytes
        img = Image.open(io.BytesIO(snapshot.raw_bytes))

        # Convert to 16-bit RGB565 (standard for Linux framebuffer)
        img = img.convert("RGB")
        rgb565_data = bytearray()
        for y in range(self.target_height):
            for x in range(self.target_width):
                r, g, b = img.getpixel((x, y))
                # Convert to RGB565
                r5 = (r >> 3) & 0x1F
                g6 = (g >> 2) & 0x3F
                b5 = (b >> 3) & 0x1F
                pixel = (r5 << 11) | (g6 << 5) | b5
                rgb565_data.extend(pixel.to_bytes(2, byteorder='little'))

        # Write to framebuffer
        with open(fb_path, "wb") as f:
            f.write(rgb565_data)

        logger.info("Wrote %dx%d frame to %s (%d bytes)",
                    self.target_width, self.target_height, fb_path, len(rgb565_data))

    def _capture_fbgrab(self) -> FramebufferSnapshot:
        """Capture using fbgrab utility."""
        try:
            result = subprocess.run(
                ["fbgrab", "-stdout"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                raise subprocess.CalledProcessError(result.returncode, "fbgrab")
            raw_png = result.stdout
        except FileNotFoundError:
            logger.warning("fbgrab not found, falling back to fb0 read")
            return self._capture_fb0()
        except subprocess.TimeoutExpired:
            logger.error("fbgrab timed out")
            raise

        return self._process_png(raw_png, "fbgrab")

    def _capture_fb0(self) -> FramebufferSnapshot:
        """Capture by reading /dev/fb0 directly."""
        fb_path = self.config.framebuffer
        if not fb_path.exists():
            raise FileNotFoundError(f"Framebuffer not found: {fb_path}")

        # Read raw framebuffer
        with open(fb_path, "rb") as f:
            raw_fb = f.read()

        # Convert raw framebuffer to PNG using Pillow
        from PIL import Image

        # Try to determine resolution from framebuffer size
        # Common console modes: 320x200 (8bpp), 640x480 (32bpp)
        stride_options = [
            (320, 200, 1),   # 320x200 @ 8bpp
            (640, 480, 4),   # 640x480 @ 32bpp
            (800, 600, 4),   # 800x600 @ 32bpp
        ]

        img = None
        for w, h, bpp in stride_options:
            if len(raw_fb) >= w * h * bpp:
                stride = w * bpp
                # Handle different pixel formats
                if bpp == 1:
                    img = Image.frombuffer(
                        "RGB", (w, h), raw_fb, "raw", "BGR", stride, 1
                    )
                elif bpp == 4:
                    img = Image.frombuffer(
                        "RGBA", (w, h), raw_fb, "raw", "RGBA", stride, 1
                    )
                if img:
                    break

        if img is None:
            raise ValueError(
                f"Cannot parse framebuffer: {len(raw_fb)} bytes, "
                "expected one of {w*h*bpp} for common resolutions"
            )

        # Convert to PNG
        import io
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
        raw_png = buf.getvalue()

        return self._process_png(raw_png, "fb0")

    def _capture_screenshot(self) -> FramebufferSnapshot:
        """Capture using a screenshot utility (scrot/grim/xwd)."""
        tools = ["scrot", "grim", "xwd"]
        for tool in tools:
            try:
                result = subprocess.run(
                    [tool, "-"],
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    raw_png = result.stdout
                    return self._process_png(raw_png, tool)
            except FileNotFoundError:
                continue
            except subprocess.TimeoutExpired:
                continue

        raise RuntimeError(
            "No screenshot utility available. Install scrot, grim, or xwd."
        )

    def _capture_xvfb(self) -> FramebufferSnapshot:
        """Capture from an Xvfb virtual display using ImageMagick import.

        This is the recommended capture method for headless Usagi runs
        where the engine renders into an Xvfb framebuffer instead of
        directly to /dev/fb0 or a DRM card.
        """
        display = f":{self.config.xvfb_display}"
        try:
            result = subprocess.run(
                ["import", "-window", "root", "-depth", "8", "-delay", "0", "-"],
                env={"DISPLAY": display},
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                raise subprocess.CalledProcessError(
                    result.returncode, "import", result.stderr
                )
            raw_png = result.stdout
        except FileNotFoundError:
            logger.warning("ImageMagick 'import' not found, falling back to fb0")
            return self._capture_fb0()
        except subprocess.TimeoutExpired:
            logger.error("import timed out on display %s", display)
            raise

        return self._process_png(raw_png, "xvfb")

    def _process_png(self, raw_png: bytes, method: str) -> FramebufferSnapshot:
        """Downsample PNG to target resolution and encode as data URL."""
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(raw_png))

        # Downsample to target resolution
        img = img.resize(
            (self.target_width, self.target_height),
            Image.LANCZOS,
        )

        # Re-encode as PNG
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        raw_compressed = buf.getvalue()

        # Create data URL
        b64 = base64.b64encode(raw_compressed).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"

        return FramebufferSnapshot(
            data_url=data_url,
            raw_bytes=raw_compressed,
            width=self.target_width,
            height=self.target_height,
            method=method,
        )
