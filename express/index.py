"""Express MCP Server — Navigational Entry Point.

This module provides flat, minimal-context imports so builders and
maintainers can work with small slices of the codebase without loading
everything into context.

Usage:
    # Configuration only (no LLM, no engine deps)
    from express.index import config

    # LLM layer only (no engine, no framebuffer)
    from express.index import LLMClient, CODE_GENERATION_SYSTEM

    # Renderer only (no LLM, no MCP)
    from express.index import EngineManager, FramebufferCapture

    # Self-heal only
    from express.index import ExpressionEvaluator

    # Full tool (all layers)
    from express.index import render_expression

    # MCP server entry
    from express.index import create_server

All imports are eager so you can explore any module in isolation.
"""

from __future__ import annotations

# Configuration (zero dependencies)
from express.config import Config, config

# LLM layer
from express.llm.client import LLMClient, LLMResponse
from express.llm.prompts import (
    CODE_GENERATION_SYSTEM,
    SELF_HEAL_SYSTEM,
    SYSTEM_PROMPT_SNIPPET,
)

# Renderer layer
from express.renderer.engine import EngineManager, EngineOutput
from express.renderer.framebuffer import FramebufferCapture, FramebufferSnapshot

# Self-heal layer
from express.self_heal.evaluator import ExpressionEvaluator, EvaluationResult

# Tool layer
from express.tools.render_expression import render_expression

# MCP server
from express.mcp_server import create_server, main

__all__ = [
    # Config
    "Config",
    "config",
    # LLM
    "LLMClient",
    "LLMResponse",
    "CODE_GENERATION_SYSTEM",
    "SELF_HEAL_SYSTEM",
    "SYSTEM_PROMPT_SNIPPET",
    # Renderer
    "EngineManager",
    "EngineOutput",
    "FramebufferCapture",
    "FramebufferSnapshot",
    # Self-heal
    "ExpressionEvaluator",
    "EvaluationResult",
    # Tool
    "render_expression",
    # MCP server
    "create_server",
    "main",
]
