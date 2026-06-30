"""Tests for express.renderer.engine."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest

from express.config import Config
from express.renderer.engine import EngineManager, EngineOutput


class TestEngineOutput:
    """Test EngineOutput dataclass."""

    def test_success(self):
        out = EngineOutput(
            stdout="hello",
            stderr="",
            return_code=0,
            success=True,
            duration_seconds=1.5,
        )
        assert out.success is True

    def test_failure(self):
        out = EngineOutput(
            stdout="",
            stderr="error",
            return_code=1,
            success=False,
            duration_seconds=0.5,
        )
        assert out.success is False


class TestEngineManagerInit:
    """Test EngineManager initialization."""

    def test_default_paths(self):
        mgr = EngineManager(Config())
        assert mgr.config.usagi_bin is not None

    def test_xvfb_not_started_by_default(self):
        mgr = EngineManager(Config())
        assert mgr._xvfb_started is False
        assert mgr._xvfb_process is None

    def test_context_manager(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("EXPRESS_USAGI_WORKSPACE", str(workspace))
        mgr = EngineManager(Config())
        with mgr:
            assert True  # context manager works


class TestEngineManagerWorkspace:
    """Test workspace preparation."""

    def test_prepare_creates_workspace(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("EXPRESS_USAGI_WORKSPACE", str(workspace))
        mgr = EngineManager(Config())
        mgr.prepare_workspace()
        assert workspace.exists()
        assert (workspace / "main.lua").exists()


class TestEngineManagerAssets:
    """Test asset creation."""

    def test_creates_sprites(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("EXPRESS_USAGI_WORKSPACE", str(workspace))
        mgr = EngineManager(Config())
        mgr._ensure_assets()
        assert (workspace / "sprites.png").exists()

    def test_creates_palette(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("EXPRESS_USAGI_WORKSPACE", str(workspace))
        mgr = EngineManager(Config())
        mgr._ensure_assets()
        assert (workspace / "palette.png").exists()

    def test_creates_config(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("EXPRESS_USAGI_WORKSPACE", str(workspace))
        mgr = EngineManager(Config())
        mgr._ensure_assets()
        config_content = (workspace / "_config.lua").read_text()
        assert "width" in config_content
        assert "height" in config_content

    def test_does_not_overwrite_existing(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "sprites.png").write_bytes(b"existing")
        monkeypatch.setenv("EXPRESS_USAGI_WORKSPACE", str(workspace))
        mgr = EngineManager(Config())
        mgr._ensure_assets()
        assert (workspace / "sprites.png").read_bytes() == b"existing"


class TestEngineManagerBuildEnv:
    """Test environment variable building."""

    def test_drm_env(self):
        mgr = EngineManager(Config())
        env = mgr._build_env(headless=False)
        assert env["RAYLIB_BACKEND"] == "drm"

    def test_window_env(self):
        mgr = EngineManager(Config())
        env = mgr._build_env(headless=True)
        assert env["RAYLIB_BACKEND"] == "window"


class TestEngineManagerRunHeadless:
    """Test headless run (mocked subprocess + Xvfb)."""

    def test_run_success(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("EXPRESS_USAGI_WORKSPACE", str(workspace))
        mgr = EngineManager(Config())
        mgr._ensure_assets()

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b"stdout\n", b"stderr\n")
        mock_proc.returncode = 0
        mock_proc.kill = MagicMock()
        mock_proc.kill.return_value = None

        call_count = [0]
        def popen_side_effect(*args, **kwargs):
            call_count[0] += 1
            # Skip Xvfb (mocked via start_xvfb), return Usagi proc
            if call_count[0] == 1:
                return mock_proc
            raise AssertionError("Unexpected Popen call")

        with patch.object(mgr, "start_xvfb"):
            with patch.object(mgr, "stop_xvfb"):
                with patch("express.renderer.engine.subprocess.Popen", side_effect=popen_side_effect):
                    result = mgr.run_headless("return {}", timeout=5)

        assert result.success is True
        assert "stdout" in result.stdout
        assert "stderr" in result.stderr

    def test_run_timeout(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("EXPRESS_USAGI_WORKSPACE", str(workspace))
        mgr = EngineManager(Config())
        mgr._ensure_assets()

        import subprocess as sp

        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = [
            sp.TimeoutExpired("cmd", 5),
            (b"", b"Runtime error"),
        ]
        mock_proc.kill = MagicMock()
        mock_proc.kill.return_value = None

        call_count = [0]
        def popen_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_proc
            raise AssertionError("Unexpected Popen call")

        with patch.object(mgr, "start_xvfb"):
            with patch.object(mgr, "stop_xvfb"):
                with patch("express.renderer.engine.subprocess.Popen", side_effect=popen_side_effect):
                    result = mgr.run_headless("return {}", timeout=5)

        assert result.success is False

    def test_run_binary_not_found(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("EXPRESS_USAGI_WORKSPACE", str(workspace))
        mgr = EngineManager(Config(
            usagi_bin=Path("/nonexistent/usagi")
        ))
        mgr._ensure_assets()

        with patch.object(mgr, "start_xvfb"):
            with patch.object(mgr, "stop_xvfb"):
                with patch("express.renderer.engine.subprocess.Popen") as mock_popen:
                    mock_popen.side_effect = FileNotFoundError()
                    result = mgr.run_headless("return {}", timeout=5)

        assert result.success is False
        assert "not found" in result.stderr


class TestEngineManagerXvfb:
    """Test Xvfb process management."""

    def test_start_xvfb(self, tmp_path, monkeypatch):
        pid_file = tmp_path / "xvfb.pid"
        monkeypatch.setenv("EXPRESS_XVFB_PID_FILE", str(pid_file))
        mgr = EngineManager(Config())

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 9999

        with patch("express.renderer.engine.subprocess.Popen", return_value=mock_proc):
            with patch("express.renderer.engine.Path.exists", return_value=False):
                mgr.start_xvfb()

        assert mgr._xvfb_started is True
        assert mgr._xvfb_process is mock_proc
        assert pid_file.exists()
        assert pid_file.read_text().strip() == "9999"

    def test_start_xvfb_already_running(self, tmp_path, monkeypatch):
        mgr = EngineManager(Config())
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 9999
        mgr._xvfb_process = mock_proc
        mgr._xvfb_started = True

        # Should not start a new one
        with patch("express.renderer.engine.subprocess.Popen") as mock_popen:
            mgr.start_xvfb()
        mock_popen.assert_not_called()

    def test_stop_xvfb(self, tmp_path, monkeypatch):
        pid_file = tmp_path / "xvfb.pid"
        monkeypatch.setenv("EXPRESS_XVFB_PID_FILE", str(pid_file))
        pid_file.write_text("9999")
        mgr = EngineManager(Config())

        mock_proc = MagicMock()
        mock_proc.pid = 9999
        mgr._xvfb_process = mock_proc
        mgr._xvfb_started = True

        mgr.stop_xvfb()

        mock_proc.terminate.assert_called_once()
        assert mgr._xvfb_started is False
        assert mgr._xvfb_process is None
        assert not pid_file.exists()

    def test_stop_xvfb_not_started(self):
        mgr = EngineManager(Config())
        # Should not raise
        mgr.stop_xvfb()

    def test_xvfb_start_failure(self, tmp_path, monkeypatch):
        pid_file = tmp_path / "xvfb.pid"
        monkeypatch.setenv("EXPRESS_XVFB_PID_FILE", str(pid_file))
        mgr = EngineManager(Config())

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # exited immediately
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = b"Xvfb failed"

        # Ensure the X11 socket check doesn't short-circuit (Xvfb may be
        # running on the host system, causing an early return before Popen).
        monkeypatch.setattr("pathlib.Path.exists", lambda self: False)

        with patch("express.renderer.engine.subprocess.Popen", return_value=mock_proc):
            with pytest.raises(RuntimeError, match="Xvfb failed"):
                mgr.start_xvfb()

        assert mgr._xvfb_started is False
