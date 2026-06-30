"""Tests for express.renderer.framebuffer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from express.config import Config
from express.renderer.framebuffer import FramebufferCapture, FramebufferSnapshot


class TestFramebufferSnapshot:
    """Test FramebufferSnapshot dataclass."""

    def test_basic(self):
        snap = FramebufferSnapshot(
            data_url="data:image/png;base64,abc",
            raw_bytes=b"\x89PNG",
            width=320,
            height=180,
            method="fbgrab",
        )
        assert snap.width == 320
        assert snap.height == 180
        assert snap.method == "fbgrab"


class TestFramebufferCaptureInit:
    """Test FramebufferCapture initialization."""

    def test_default_target_size(self):
        fc = FramebufferCapture(Config())
        assert fc.target_width == 320
        assert fc.target_height == 180


class TestFramebufferCaptureMethods:
    """Test framebuffer capture method resolution."""

    def test_fbgrab_method(self):
        fc = FramebufferCapture(Config(capture_method="fbgrab"))
        assert fc.config.capture_method == "fbgrab"

    def test_fb0_method(self):
        fc = FramebufferCapture(Config(capture_method="fb0"))
        assert fc.config.capture_method == "fb0"

    def test_screenshot_method(self):
        fc = FramebufferCapture(Config(capture_method="screenshot"))
        assert fc.config.capture_method == "screenshot"

    def test_xvfb_method(self):
        fc = FramebufferCapture(Config(capture_method="xvfb"))
        assert fc.config.capture_method == "xvfb"

    def test_invalid_method(self):
        fc = FramebufferCapture(Config(capture_method="invalid"))
        assert fc.config.capture_method == "invalid"


class TestFramebufferProcessPNG:
    """Test PNG processing and downsampling."""

    def test_process_png_creates_data_url(self):
        fc = FramebufferCapture(Config())

        # Create a minimal PNG in memory
        from PIL import Image
        import io
        img = Image.new("RGB", (640, 480), (255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        raw_png = buf.getvalue()

        snap = fc._process_png(raw_png, "test")
        assert snap.data_url.startswith("data:image/png;base64,")
        assert snap.width == 320
        assert snap.height == 180
        assert snap.method == "test"


class TestFramebufferCaptureBase64:
    """Test capture_base64 convenience method."""

    def test_returns_data_url(self):
        fc = FramebufferCapture(Config())

        # Mock capture to return a known snapshot
        snap = FramebufferSnapshot(
            data_url="data:image/png;base64,test123",
            raw_bytes=b"test",
            width=320,
            height=180,
            method="test",
        )
        with patch.object(fc, 'capture', return_value=snap):
            result = fc.capture_base64()
            assert result == "data:image/png;base64,test123"


class TestFramebufferCaptureXvfb:
    """Test Xvfb capture method."""

    def test_capture_xvfb_success(self):
        fc = FramebufferCapture(Config(capture_method="xvfb"))

        # Create a minimal PNG
        from PIL import Image
        import io
        img = Image.new("RGB", (320, 180), (255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        raw_png = buf.getvalue()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = raw_png

        with patch("express.renderer.framebuffer.subprocess.run", return_value=mock_result):
            snap = fc._capture_xvfb()

        assert snap.method == "xvfb"
        assert snap.width == 320
        assert snap.height == 180
        assert snap.data_url.startswith("data:image/png;base64,")

    def test_capture_xvfb_import_not_found(self):
        fc = FramebufferCapture(Config(capture_method="xvfb"))

        # Mock both the import failure AND the fb0 fallback
        with patch("express.renderer.framebuffer.subprocess.run", side_effect=FileNotFoundError()):
            with patch("express.renderer.framebuffer.Path.exists", return_value=False):
                with pytest.raises(FileNotFoundError):
                    fc._capture_xvfb()

    def test_capture_xvfb_timeout(self):
        fc = FramebufferCapture(Config(capture_method="xvfb"))
        import subprocess as sp

        with patch("express.renderer.framebuffer.subprocess.run", side_effect=sp.TimeoutExpired("import", 5)):
            with pytest.raises(sp.TimeoutExpired):
                fc._capture_xvfb()

    def test_capture_xvfb_display_error(self):
        fc = FramebufferCapture(Config(capture_method="xvfb"))

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = b"Cannot open display"

        with patch("express.renderer.framebuffer.subprocess.run", return_value=mock_result):
            with pytest.raises(Exception):  # CalledProcessError
                fc._capture_xvfb()
