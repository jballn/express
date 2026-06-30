"""Express — Natural language to visual expression via LLM + Usagi Engine.

Minimal-context entry point for importing individual subsystems:

    from express import config, llm, renderer, tools

Each submodule exposes only the symbols needed for its layer,
keeping builder context windows small and focused.
"""

from __future__ import annotations

# ── Configuration ──────────────────────────────────────────────────────

from express.config import Config, config

# ── LLM Layer ──────────────────────────────────────────────────────────

from express.llm.client import LLMClient, LLMResponse
from express.llm.prompts import (
    CODE_GENERATION_SYSTEM,
    SYSTEM_PROMPT_SNIPPET,
)

# ── Renderer Layer ─────────────────────────────────────────────────────

from express.renderer.engine import EngineManager, EngineOutput
from express.renderer.framebuffer import FramebufferCapture

# ── MCP Tools ──────────────────────────────────────────────────────────

from express.tools.render_lua import render_lua

# ── MCP Server ─────────────────────────────────────────────────────────

from express.mcp_server import app as mcp_app, main as mcp_main

__all__ = [
    # Config
    "Config",
    "config",
    # LLM
    "LLMClient",
    "LLMResponse",
    "CODE_GENERATION_SYSTEM",
    "SYSTEM_PROMPT_SNIPPET",
    # Renderer
    "EngineManager",
    "EngineOutput",
    "FramebufferCapture",
    # Tools
    "render_lua",
    # MCP
    "mcp_app",
    "mcp_main",
]
