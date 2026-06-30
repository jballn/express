"""Tests for MCP server tool registration and handling."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from express.mcp_server import app, RENDER_EXPRESSION_TOOL, handle_tool_call, handle_list_tools


class TestToolRegistration:
    """Test that tools are properly registered."""

    def test_tool_name(self):
        assert RENDER_EXPRESSION_TOOL.name == "render_expression"

    def test_tool_description(self):
        assert "natural language" in RENDER_EXPRESSION_TOOL.description.lower()

    def test_tool_input_schema(self):
        schema = RENDER_EXPRESSION_TOOL.inputSchema
        assert schema["type"] == "object"
        assert "user_intent" in schema["properties"]
        assert "user_intent" in schema["required"]

    def test_tool_registered_in_server(self):
        # Tools are cached when list_tools is called via MCP protocol
        # Verify handler is registered
        from mcp.types import ListToolsRequest
        assert ListToolsRequest in app.request_handlers


class TestListToolsHandler:
    """Test the list_tools handler."""

    @pytest.mark.asyncio
    async def test_list_tools_returns_render_expression(self):
        tools = await handle_list_tools()
        assert len(tools) == 2
        assert tools[0].name == "render_expression"
        assert tools[1].name == "render_lua"


class TestToolCallHandler:
    """Test the tool call handler."""

    @pytest.mark.asyncio
    async def test_render_expression_success(self):
        """Test successful render_expression call."""
        with patch("express.mcp_server.render_expression") as mock_render:
            mock_render.return_value = {
                "success": True,
                "code": "return {}",
                "issues": [],
                "console_output": "",
                "duration_seconds": 0.1,
                "heal_passes": 0,
            }

            result = await handle_tool_call("render_expression", {"user_intent": "test"})
            assert len(result) == 1
            assert result[0].type == "text"
            output = json.loads(result[0].text)
            assert output["success"] is True

    @pytest.mark.asyncio
    async def test_render_expression_missing_intent(self):
        """Test render_expression with missing user_intent."""
        result = await handle_tool_call("render_expression", {})
        assert len(result) == 1
        assert result[0].type == "text"
        assert "required" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_render_expression_empty_intent(self):
        """Test render_expression with empty user_intent."""
        result = await handle_tool_call("render_expression", {"user_intent": ""})
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
    async def test_render_expression_error(self):
        """Test render_expression with exception."""
        with patch("express.mcp_server.render_expression") as mock_render:
            mock_render.side_effect = RuntimeError("Test error")
            result = await handle_tool_call("render_expression", {"user_intent": "test"})
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
