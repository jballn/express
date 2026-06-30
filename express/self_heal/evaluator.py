"""Expression evaluator for self-healing.

Analyzes rendered frames and console logs to detect issues,
then requests corrected Lua code from the LLM.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from express.config import Config
from express.llm.client import LLMClient, LLMResponse
from express.llm.prompts import SELF_HEAL_SYSTEM
from express.renderer.engine import EngineOutput
from express.renderer.framebuffer import FramebufferCapture

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    """Result of evaluating a rendered expression."""

    is_valid: bool
    """Whether the output is valid and matches the intent."""
    issues: list[str]
    """List of detected issues (empty if valid)."""
    corrected_code: str
    """Corrected Lua code (may be same as input if valid)."""
    raw_response: LLMResponse | None
    """Raw LLM response for debugging."""


class ExpressionEvaluator:
    """Evaluates rendered expressions and triggers self-healing.

    Usage:
        evaluator = ExpressionEvaluator(config)
        result = evaluator.evaluate(
            original_code="...",
            engine_output=engine_output,
            user_intent="show a bouncing ball",
            framebuffer=framebuffer_capture,
        )
        if not result.is_valid:
            corrected_code = result.corrected_code
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self._client: Optional[LLMClient] = None

    @property
    def llm(self) -> LLMClient:
        """Lazy-init the LLM client."""
        if self._client is None:
            self._client = LLMClient(self.config)
        return self._client

    def evaluate(
        self,
        original_code: str,
        engine_output: EngineOutput,
        user_intent: str,
        framebuffer: FramebufferCapture,
    ) -> EvaluationResult:
        """Evaluate a rendered expression for correctness.

        1. Capture framebuffer screenshot
        2. Analyze console logs for errors
        3. Send to LLM for visual evaluation
        4. Return evaluation result

        Args:
            original_code: The Lua code that was rendered
            engine_output: Captured stdout/stderr from Usagi
            user_intent: The original user request
            framebuffer: FramebufferCapture instance

        Returns:
            EvaluationResult with validity, issues, and corrected code
        """
        # Step 1: Capture the framebuffer
        try:
            snapshot = framebuffer.capture()
        except Exception as e:
            logger.warning("Framebuffer capture failed: %s", e)
            # Fall back: evaluate based on console logs only
            return self._evaluate_console_only(
                original_code, engine_output, user_intent
            )

        # Step 2: Analyze console logs
        console_issues = self._analyze_console_logs(engine_output.stderr)

        # Step 3: Send to LLM for visual evaluation
        try:
            response = self._send_for_evaluation(
                snapshot.data_url,
                engine_output.stderr,
                user_intent,
                original_code,
            )
        except Exception as e:
            logger.error("LLM evaluation failed: %s", e)
            return self._evaluate_console_only(
                original_code, engine_output, user_intent
            )

        # Step 4: Parse response
        return self._parse_evaluation_response(
            response, original_code, console_issues
        )

    def _evaluate_console_only(
        self,
        original_code: str,
        engine_output: EngineOutput,
        user_intent: str,
    ) -> EvaluationResult:
        """Fallback: evaluate based on console logs when framebuffer capture fails."""
        issues = self._analyze_console_logs(engine_output.stderr)

        if not issues:
            # No errors detected, assume valid
            return EvaluationResult(
                is_valid=True,
                issues=[],
                corrected_code=original_code,
                raw_response=None,
            )

        # Has console errors — try to get corrected code
        try:
            response = self.llm.text_completion(
                SELF_HEAL_SYSTEM,
                (
                    f"Console errors detected:\n{engine_output.stderr}\n\n"
                    f"Original code:\n{original_code}\n\n"
                    f"User intent: {user_intent}\n\n"
                    f"Provide corrected Lua code that fixes these errors."
                ),
            )
            corrected = self._extract_lua_code(response.text)
            return EvaluationResult(
                is_valid=False,
                issues=issues,
                corrected_code=corrected,
                raw_response=response,
            )
        except Exception as e:
            logger.error("Console-only correction failed: %s", e)
            return EvaluationResult(
                is_valid=False,
                issues=issues + [f"Correction failed: {e}"],
                corrected_code=original_code,
                raw_response=None,
            )

    def _send_for_evaluation(
        self,
        image_data_url: str,
        console_logs: str,
        user_intent: str,
        original_code: str,
    ) -> LLMResponse:
        """Send frame + logs to LLM for visual evaluation."""
        return self.llm.evaluate_expression(
            system_prompt=SELF_HEAL_SYSTEM,
            image_data_url=image_data_url,
            console_logs=console_logs,
            user_message=user_intent,
        )

    def _parse_evaluation_response(
        self,
        response: LLMResponse,
        original_code: str,
        console_issues: list[str],
    ) -> EvaluationResult:
        """Parse the LLM's evaluation JSON response."""
        issues = list(console_issues)  # copy

        try:
            # Try to parse JSON from the response
            json_text = self._extract_json(response.text)
            data = json.loads(json_text)
        except (json.JSONDecodeError, TypeError):
            # Fallback: treat as text response
            return EvaluationResult(
                is_valid=False,
                issues=["LLM did not return valid JSON"],
                corrected_code=original_code,
                raw_response=response,
            )

        is_valid = data.get("is_valid", False)
        issues_list = data.get("issues", [])
        corrected = data.get("code", original_code)

        if isinstance(issues_list, list):
            issues.extend(issues_list)
        elif isinstance(issues_list, str) and issues_list:
            issues.append(issues_list)

        # Remove duplicates while preserving order
        seen = set()
        unique_issues = []
        for issue in issues:
            if issue not in seen:
                seen.add(issue)
                unique_issues.append(issue)

        return EvaluationResult(
            is_valid=is_valid,
            issues=unique_issues,
            corrected_code=corrected,
            raw_response=response,
        )

    @staticmethod
    def _analyze_console_logs(stderr: str) -> list[str]:
        """Parse Usagi console output for error indicators.

        Returns a list of issue descriptions.
        """
        issues = []

        if not stderr:
            return issues

        # Check for Lua runtime errors
        lua_error_patterns = [
            (r"lua:.*:[0-9]+:", "Lua runtime error at line"),
            (r"attempt to index a nil value", "nil value reference"),
            (r"attempt to call a nil value", "nil value call"),
            (r"attempt to call a string value", "Type mismatch: string called as function"),
            (r"bad argument #", "Bad argument passed to function"),
            (r"stack overflow", "Stack overflow detected"),
            (r"out of memory", "Out of memory error"),
            (r"PCERROR", "Parse error in Lua code"),
            (r"unexpected symbol", "Syntax error in Lua code"),
            (r"unexpected token", "Unexpected token in Lua code"),
        ]

        for pattern, description in lua_error_patterns:
            if re.search(pattern, stderr):
                issues.append(description)

        # Check for rendering issues
        render_patterns = [
            (r"shader.*compile.*error", "Shader compilation error"),
            (r"texture.*fail|texture.*not.*found", "Texture loading failure"),
            (r"cannot open.*sprites", "Sprite asset missing"),
        ]

        for pattern, description in render_patterns:
            if re.search(pattern, stderr, re.IGNORECASE):
                issues.append(description)

        return issues

    @staticmethod
    def _extract_lua_code(text: str) -> str:
        """Extract Lua code from LLM response text."""
        # Try to extract code from markdown code blocks
        lua_block = re.search(r"```[lL]ua\n(.*?)```", text, re.DOTALL)
        if lua_block:
            return lua_block.group(1).strip()

        # Try generic code blocks
        code_block = re.search(r"```\n(.*?)```", text, re.DOTALL)
        if code_block:
            return code_block.group(1).strip()

        # Return the full text as-is
        return text.strip()

    @staticmethod
    def _extract_json(text: str) -> str:
        """Extract JSON from LLM response text."""
        # Try to find JSON object in the text
        json_match = re.search(r"\{[^{}]*" + r"(?:\{[^{}]*\}[^{}]*)" + r"*\}", text, re.DOTALL)
        if json_match:
            return json_match.group(0)

        # Try to find a JSON block
        json_block = re.search(r"```\s*(?:json)?\n(.*?)```", text, re.DOTALL)
        if json_block:
            return json_block.group(1).strip()

        return text.strip()
