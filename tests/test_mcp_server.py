"""Tests for MCP server tool registration and handling."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from express.mcp_server import app, RENDER_LUA_TOOL, handle_tool_call, handle_list_tools


class TestToolRegistration:
    """Test that tools are properly registered."""

    def test_tool_name(self):
        assert RENDER_LUA_TOOL.name == "render_lua"

    def test_tool_description(self):
        assert "Lua code" in RENDER_LUA_TOOL.description or "lua" in RENDER_LUA_TOOL.description.lower()

    def test_tool_input_schema(self):
        schema = RENDER_LUA_TOOL.inputSchema
        assert schema["type"] == "object"
        assert "lua_code" in schema["properties"]
        assert "lua_code" in schema["required"]


class TestListToolsHandler:
    """Test the list_tools handler."""

    @pytest.mark.asyncio
    async def test_list_tools_returns_render_lua(self):
        tools = await handle_list_tools()
        assert len(tools) == 1
        assert tools[0].name == "render_lua"


class TestToolCallHandler:
    """Test the tool call handler."""

    @pytest.mark.asyncio
    async def test_render_lua_success(self):
        """Test successful render_lua call."""
        with patch("express.mcp_server.render_lua") as mock_render:
            mock_render.return_value = {
                "success": True,
                "code": "return {}",
                "issues": [],
                "console_output": "",
                "duration_seconds": 0.1,
                "framebuffer_url": None,
                "fb0_written": False,
                "fb0_size": 0,
            }

            result = await handle_tool_call("render_lua", {"lua_code": "return {}"})
            assert len(result) == 1
            assert result[0].type == "text"
            output = json.loads(result[0].text)
            assert output["success"] is True

    @pytest.mark.asyncio
    async def test_render_lua_missing_code(self):
        """Test render_lua with missing lua_code."""
        result = await handle_tool_call("render_lua", {})
        assert len(result) == 1
        assert result[0].type == "text"
        assert "required" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_render_lua_empty_code(self):
        """Test render_lua with empty lua_code."""
        result = await handle_tool_call("render_lua", {"lua_code": ""})
        assert len(result) == 1
        assert result[0].type == "text"
        assert "required" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        """Test calling an unknown tool."""
        result = await handle_tool_call("unknown_tool", {})
        assert len(result) == 1
        assert result[0].type == "text"
        assert "unknown" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_render_lua_error(self):
        """Test render_lua with exception."""
        with patch("express.mcp_server.render_lua") as mock_render:
            mock_render.side_effect = RuntimeError("Test error")
            result = await handle_tool_call("render_lua", {"lua_code": "return {}"})
            assert len(result) == 1
            assert result[0].type == "text"
            assert "Test error" in result[0].text


class TestServerLifecycle:
    """Test server lifecycle methods."""

    def test_server_name(self):
        assert app.name == "express"

    def test_server_version(self):
        assert app.version == "0.1.0"

    def test_initialization_options(self):
        options = app.create_initialization_options()
        assert options.server_name == "express"
        assert options.server_version == "0.1.0"
