"""Express MCP Server — Navigational Entry Point.

This module provides flat, minimal-context imports so builders and
maintainers can work with small slices of the codebase without loading
everything into context.

Usage:
    # Configuration only (no engine deps)
    from express.index import config

    # Renderer only (no MCP)
    from express.index import EngineManager, FramebufferCapture

    # MCP server entry
    from express.index import create_server

All imports are eager so you can explore any module in isolation.
"""

from __future__ import annotations

# Configuration (zero dependencies)
from express.config import Config, config

# Renderer layer
from express.renderer.engine import EngineManager, EngineOutput
from express.renderer.framebuffer import FramebufferCapture, FramebufferSnapshot

# Tool layer
from express.tools.render_lua import render_lua

# MCP server
from express.mcp_server import create_server, main

__all__ = [
    # Config
    "Config",
    "config",
    # Renderer
    "EngineManager",
    "EngineOutput",
    "FramebufferCapture",
    "FramebufferSnapshot",
    # Tool
    "render_lua",
    # MCP server
    "create_server",
    "main",
]
