"""Tests for express.config."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from express.config import Config


class TestConfigDefaults:
    """Test default configuration values."""

    def test_llm_endpoint_default(self):
        assert Config().llm_endpoint == "http://localhost:58008/v1"

    def test_canvas_resolution(self):
        c = Config()
        assert c.canvas_width == 320
        assert c.canvas_height == 180

    def test_palette_size(self):
        assert Config().palette_size == 16

    def test_render_timeout(self):
        assert Config().render_timeout == 30.0

    def test_render_wait_ms(self):
        assert Config().render_wait_ms == 500

    def test_capture_method_default(self):
        assert Config().capture_method == "xvfb"


class TestConfigEnvVars:
    """Test environment variable overrides via keyword arguments."""

    def test_llm_endpoint_from_env(self, monkeypatch):
        monkeypatch.setenv("EXPRESS_LLM_ENDPOINT", "http://test:1234/v1")
        c = Config(llm_endpoint="http://test:1234/v1")
        assert c.llm_endpoint == "http://test:1234/v1"

    def test_capture_method_from_env(self, monkeypatch):
        monkeypatch.setenv("EXPRESS_CAPTURE_METHOD", "fb0")
        c = Config(capture_method="fb0")
        assert c.capture_method == "fb0"


class TestConfigHelpers:
    """Test configuration helper methods."""

    def test_llm_chat_url(self):
        c = Config()
        assert c.llm_chat_url == "http://localhost:58008/v1/chat/completions"

    def test_llm_chat_url_no_trailing(self):
        c = Config(llm_endpoint="http://localhost:58008/v1/")
        assert c.llm_chat_url == "http://localhost:58008/v1/chat/completions"

    def test_ensure_workspace(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("EXPRESS_USAGI_WORKSPACE", str(workspace))
        c = Config()
        c.ensure_workspace()
        assert workspace.exists()
        assert workspace.is_dir()

    def test_ensure_skeleton_creates_main(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("EXPRESS_USAGI_WORKSPACE", str(workspace))
        c = Config()
        c.ensure_skeleton()
        assert (workspace / "main.lua").exists()

    def test_skeleton_main_content(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("EXPRESS_USAGI_WORKSPACE", str(workspace))
        c = Config()
        c.ensure_skeleton()
        content = (workspace / "main.lua").read_text()
        assert "State = State or {}" in content
        assert "llm_output.lua" in content
        assert "pcall" in content

    def test_llm_output_lua_path(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("EXPRESS_USAGI_WORKSPACE", str(workspace))
        c = Config()
        assert c.llm_output_lua == workspace / "llm_output.lua"


class TestConfigSingleton:
    """Test that config() returns a singleton instance."""

    def test_singleton(self):
        from express.config import config as singleton
        assert isinstance(singleton, Config)
