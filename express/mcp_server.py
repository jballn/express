"""MCP server: Express — natural language to visual expression.

Registers the render_expression tool and handles JSON-RPC stdio transport
per the MCP specification.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import InitializedNotification, TextContent, Tool

from express.tools.render_expression import render_expression
from express.tools.render_lua import render_lua

logger = logging.getLogger("express.mcp")

# ── MCP Server Instance ────────────────────────────────────────────────

app = Server(
    name="express",
    version="0.1.0",
    instructions=(
        "Express is a visual expression engine. Use render_expression to "
        "generate 2D graphics from natural language descriptions."
    ),
)


# ── Tool Definitions ────────────────────────────────────────────────

RENDER_EXPRESSION_TOOL = Tool(
    name="render_expression",
    description=(
        "Render a visual expression from natural language. Takes a user intent "
        "string and returns the generated Lua code, framebuffer screenshot, "
        "and any issues encountered during rendering. Uses LLM code generation "
        "and self-healing loop."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "user_intent": {
                "type": "string",
                "description": (
                    "Natural language description of the visual expression "
                    "to render (e.g., 'draw a red circle in the center')\n"
                ),
            },
        },
        "required": ["user_intent"],
    },
)

RENDER_LUA_TOOL = Tool(
    name="render_lua",
    description=(
        "Run Lua code directly through the Usagi visual engine. "
        "The agent formulates the Lua code, the engine executes it on "
        "a virtual display, captures the frame, upscales to 1360x768, "
        "and writes to the physical framebuffer (/dev/fb0). "
        "Returns a base64 data URL of the captured frame. "
        "This is a pure language function — no LLM code generation, no healing loop. "
        "Use when you want direct control over the rendering."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "lua_code": {
                "type": "string",
                "description": (
                    "Complete Lua script with _init, _update, _draw functions. "
                    "Uses the Usagi (Pico-8-like) API: gfx.clear(), gfx.rect(), "
                    "gfx.rect_fill(), gfx.circ(), gfx.circ_fill(), gfx.line(), "
                    "gfx.print(), gfx.spr(). Color constants: gfx.COLOR_BLACK=1 "
                    "through gfx.COLOR_PEACH=16. "
                    "Example: function _draw() gfx.clear(gfx.COLOR_BLACK) "
                    "gfx.rect_fill(50, 30, 200, 120, gfx.COLOR_RED) end"
                ),
            },
            "display_width": {
                "type": "integer",
                "description": "Xvfb display width in pixels (default 320)",
                "default": 320,
            },
            "display_height": {
                "type": "integer",
                "description": "Xvfb display height in pixels (default 180)",
                "default": 180,
            },
        },
        "required": ["lua_code"],
    },
)


# ── MCP Protocol Handlers ──────────────────────────────────────────────


@app.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available tools."""
    logger.info("Listing tools")
    return [RENDER_EXPRESSION_TOOL, RENDER_LUA_TOOL]


@app.call_tool(validate_input=True)
async def handle_tool_call(
    name: str, arguments: dict[str, Any] | None = None
) -> list[Any]:
    """Handle tool execution requests."""
    arguments = arguments or {}
    logger.info("Tool call: %s with args: %s", name, json.dumps(arguments)[:200])

    try:
        if name == "render_expression":
            user_intent = arguments.get("user_intent", "")
            if not user_intent:
                return [
                    TextContent(
                        type="text",
                        text="Error: 'user_intent' is required and must be a non-empty string.",
                    )
                ]
            result = render_expression(user_intent)
            return [
                TextContent(
                    type="text",
                    text=json.dumps(result, indent=2),
                )
            ]
        elif name == "render_lua":
            lua_code = arguments.get("lua_code", "")
            if not lua_code:
                return [
                    TextContent(
                        type="text",
                        text="Error: 'lua_code' is required and must be a non-empty string.",
                    )
                ]
            display_width = arguments.get("display_width", 320)
            display_height = arguments.get("display_height", 180)
            result = render_lua(lua_code, display_width, display_height)
            return [
                TextContent(
                    type="text",
                    text=json.dumps(result, indent=2),
                )
            ]
        else:
            return [
                TextContent(
                    type="text",
                    text=f"Error: Unknown tool '{name}'.",
                )
            ]
    except Exception as e:
        logger.exception("Tool execution failed: %s", e)
        return [
            TextContent(
                type="text",
                text=f"Error: {e}",
            )
        ]


# ── Entry Point ────────────────────────────────────────────────────────


def main() -> None:
    """Start the MCP server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    logger.info("Starting Express MCP server (stdio)")

    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options(),
            )

    import asyncio

    asyncio.run(run())


if __name__ == "__main__":
    main()
