"""Main MCP tool: render_expression.

Orchestrates the full visual expression lifecycle:
1. Generate Lua code from user intent via LLM
2. Write code to Usagi workspace
3. Run Usagi Engine
4. Capture framebuffer screenshot
5. Self-heal if issues detected
6. Return result with clean code
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from express.config import config
from express.llm.client import LLMClient
from express.llm.prompts import CODE_GENERATION_SYSTEM
from express.renderer.engine import EngineManager, EngineOutput
from express.renderer.framebuffer import FramebufferCapture
from express.self_heal.evaluator import ExpressionEvaluator

logger = logging.getLogger(__name__)


@dataclass
class RenderResult:
    """Result of a render_expression tool call."""

    success: bool
    """Whether the expression rendered successfully."""
    code: str
    """The final Lua code that was rendered."""
    issues: list[str]
    """Any issues encountered during rendering."""
    console_output: str
    """Console output from the Usagi process."""
    duration_seconds: float
    """Total wall-clock time."""
    heal_passes: int
    """Number of self-heal passes performed."""
    framebuffer_url: str | None = None
    """Base64 data URL of the final framebuffer (for debugging)."""


def render_expression(user_intent: str) -> dict[str, Any]:
    """MCP tool: render a visual expression from natural language.

    This is the main entry point for the render_expression MCP tool.
    It orchestrates the full pipeline: LLM code generation → Usagi execution
    → framebuffer capture → self-healing → result.

    Args:
        user_intent: Natural language description of the visual expression

    Returns:
        JSON-serializable dict with success status, code, and metadata
    """
    start_time = time.monotonic()
    issues: list[str] = []
    console_output = ""
    framebuffer_url: str | None = None
    heal_passes = 0

    # ── Phase 1: Prepare ───────────────────────────────────────────
    logger.info("render_expression called: %s", user_intent[:80])

    engine = EngineManager(config)
    engine.prepare_workspace()

    framebuffer = FramebufferCapture(config)
    evaluator = ExpressionEvaluator(config)

    # ── Phase 2: Code Generation ───────────────────────────────────
    current_code = _generate_code(user_intent)
    if current_code is None:
        return _error_result(
            f"Failed to generate code: LLM did not return valid Lua code",
            duration=time.monotonic() - start_time,
        )

    # ── Phase 3: Execute & Self-Heal Loop ──────────────────────────
    for pass_num in range(config.max_heal_passes + 1):
        logger.info("Render pass %d/%d", pass_num + 1, config.max_heal_passes + 1)

        # Run Usagi
        engine_output = engine.run_headless(current_code)
        console_output = engine_output.stderr

        if engine_output.success:
            # Process ran without errors — check if it matches intent
            result = evaluator.evaluate(
                original_code=current_code,
                engine_output=engine_output,
                user_intent=user_intent,
                framebuffer=framebuffer,
            )
            framebuffer_url = framebuffer.capture_base64()

            if result.is_valid:
                # Success! Write the captured frame to the physical framebuffer
                # so it displays on the real screen (not just Xvfb)
                try:
                    snapshot = framebuffer.capture()
                    framebuffer.write_to_framebuffer(snapshot)
                    logger.info("Frame written to %s", config.framebuffer)
                except Exception as e:
                    logger.warning("Failed to write to framebuffer: %s", e)

                logger.info("Expression valid after %d pass(es)", pass_num + 1)
                return RenderResult(
                    success=True,
                    code=result.corrected_code,
                    issues=[],
                    console_output=console_output,
                    duration_seconds=time.monotonic() - start_time,
                    heal_passes=pass_num,
                    framebuffer_url=framebuffer_url,
                ).__dict__

            # Has issues — try to heal
            if pass_num < config.max_heal_passes:
                current_code = result.corrected_code
                issues.extend(result.issues)
                heal_passes += 1
                logger.warning("Issues found, healing: %s", result.issues[:3])
                continue
            else:
                issues.extend(result.issues)
                break
        else:
            # Process crashed — try to fix
            if pass_num < config.max_heal_passes:
                current_code = _try_fix_from_errors(
                    current_code, engine_output.stderr, user_intent
                )
                issues.append(f"Crash on pass {pass_num + 1}: {engine_output.stderr[:200]}")
                heal_passes += 1
                continue
            else:
                issues.append(f"Final crash: {engine_output.stderr[:200]}")
                break

    # ── Return final result ────────────────────────────────────────
    return RenderResult(
        success=False,
        code=current_code,
        issues=issues,
        console_output=console_output,
        duration_seconds=time.monotonic() - start_time,
        heal_passes=heal_passes,
        framebuffer_url=framebuffer_url,
    ).__dict__


def _generate_code(user_intent: str) -> str | None:
    """Generate Lua code from user intent via LLM."""
    client = LLMClient(config)
    try:
        response = client.generate_code(
            system_prompt=CODE_GENERATION_SYSTEM,
            user_intent=user_intent,
        )
    except Exception as e:
        logger.error("LLM code generation failed: %s", e)
        return None

    # Extract Lua code from response
    code = _extract_lua_code(response.text)
    if code:
        logger.info("Generated %d bytes of Lua code", len(code))
        return code

    logger.error("LLM did not return valid Lua code: %s", response.text[:200])
    return None


def _try_fix_from_errors(
    current_code: str, stderr: str, user_intent: str
) -> str:
    """Attempt to fix code based on error messages."""
    client = LLMClient(config)
    try:
        response = client.text_completion(
            system_prompt=CODE_GENERATION_SYSTEM,
            user_message=(
                f"Previous code crashed with errors:\n{stderr}\n\n"
                f"Original intent: {user_intent}\n\n"
                f"Previous code:\n{current_code}\n\n"
                f"Fix the errors and return corrected Lua code."
            ),
        )
        return _extract_lua_code(response.text) or current_code
    except Exception as e:
        logger.error("Self-heal failed: %s", e)
        return current_code


def _extract_lua_code(text: str) -> str | None:
    """Extract Lua code from LLM response. Returns None if text looks like prose/refusal."""
    # Try Lua code block
    match = re.search(r"```[lL]ua\n(.*?)```", text, re.DOTALL)
    if match:
        candidate = match.group(1).strip()
        if candidate and _looks_like_code(candidate):
            return candidate

    # Try generic code block
    match = re.search(r"```\n(.*?)```", text, re.DOTALL)
    if match:
        candidate = match.group(1).strip()
        if candidate and _looks_like_code(candidate):
            return candidate

    # No code block found — check if raw text looks like code
    stripped = text.strip()
    if stripped and _looks_like_code(stripped):
        return stripped

    return None


def _looks_like_code(text: str) -> bool:
    """Heuristic: does this text look like executable code vs. prose?"""
    lua_indicators = [
        r"\bfunction\b", r"\bend\b", r"\blocal\b", r"\bif\b", r"\bthen\b",
        r"\bfor\b", r"\bwhile\b", r"\breturn\b", r"\bdo\b", r"\bthen\b",
        r"_init\b", r"_update\b", r"_draw\b", r"p\.fill\b", r"p\.rect\b",
        r"p\.circ\b", r"p\.line\b", r"p\.print\b", r"p\.spr\b",
    ]
    prose_indicators = [
        r"\bi'm\s", r"\bi can't\b", r"\bcannot\b", r"\bI'm sorry\b",
        r"\bhere's\b", r"\blet me\b", r"\bsure\b", r"\bhere is\b",
        r"\bI can\b", r"\byou can\b", r"\btry this\b", r"\bplease\b",
    ]
    prose_score = sum(1 for pat in prose_indicators if re.search(pat, text, re.IGNORECASE))
    code_score = sum(1 for pat in lua_indicators if re.search(pat, text, re.IGNORECASE))
    return code_score > prose_score and code_score >= 1


def _error_result(error_msg: str, *, duration: float) -> dict[str, Any]:
    """Return an error result dict."""
    return {
        "success": False,
        "code": "",
        "issues": [error_msg],
        "console_output": "",
        "duration_seconds": round(duration, 3),
        "heal_passes": 0,
    }
