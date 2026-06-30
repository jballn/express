"""Tests for express.tools.render_expression."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from express.config import Config
from express.tools.render_expression import render_expression


class TestRenderExpressionIntegration:
    """Integration-level tests for render_expression tool."""

    @patch("express.tools.render_expression.EngineManager")
    @patch("express.tools.render_expression.FramebufferCapture")
    @patch("express.tools.render_expression.ExpressionEvaluator")
    @patch("express.tools.render_expression.LLMClient")
    def test_successful_render(
        self,
        mock_llm_cls,
        mock_evaluator_cls,
        mock_fb_cls,
        mock_engine_cls,
    ):
        """Test a successful render with no issues."""
        # Setup mocks
        mock_engine = MagicMock()
        mock_engine_cls.return_value = mock_engine

        mock_fb = MagicMock()
        mock_fb_cls.return_value = mock_fb

        mock_eval = MagicMock()
        mock_evaluator_cls.return_value = mock_eval

        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        # Mock LLM code generation response
        mock_llm_response = MagicMock()
        mock_llm_response.text = '```lua\nreturn {_init=function() end}\n```'
        mock_llm.generate_code.return_value = mock_llm_response

        # Mock engine run
        mock_engine_output = MagicMock()
        mock_engine_output.success = True
        mock_engine_output.stderr = ""
        mock_engine.run_headless.return_value = mock_engine_output

        # Mock framebuffer capture
        mock_snapshot = MagicMock()
        mock_snapshot.data_url = "data:image/png;base64,abc"
        mock_fb.capture.return_value = mock_snapshot
        mock_fb.capture_base64.return_value = "data:image/png;base64,abc"

        # Mock evaluator result
        mock_eval_result = MagicMock()
        mock_eval_result.is_valid = True
        mock_eval_result.issues = []
        mock_eval_result.corrected_code = "return {_init=function() end}"
        mock_eval.evaluate.return_value = mock_eval_result

        # Call the tool
        result = render_expression("draw a red circle")

        assert result["success"] is True
        assert result["heal_passes"] == 0
        assert result["code"] == "return {_init=function() end}"

    @patch("express.tools.render_expression.EngineManager")
    @patch("express.tools.render_expression.FramebufferCapture")
    @patch("express.tools.render_expression.ExpressionEvaluator")
    @patch("express.tools.render_expression.LLMClient")
    def test_crash_then_heal(
        self,
        mock_llm_cls,
        mock_eval_cls,
        mock_fb_cls,
        mock_engine_cls,
    ):
        """Test that crashes trigger self-healing."""
        mock_engine = MagicMock()
        mock_engine_cls.return_value = mock_engine

        mock_fb = MagicMock()
        mock_fb_cls.return_value = mock_fb

        mock_eval_cls.return_value = MagicMock()
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        # First run crashes
        crash_output = MagicMock()
        crash_output.success = False
        crash_output.stderr = "lua: main.lua:5: attempt to index nil"
        crash_output2 = MagicMock()
        crash_output2.success = True
        crash_output2.stderr = ""

        mock_engine.run_headless.side_effect = [crash_output, crash_output2]

        # LLM generates corrected code
        mock_llm_response = MagicMock()
        mock_llm_response.text = '```lua\nfunction _init() State = {} end\n```'
        mock_llm.generate_code.return_value = mock_llm_response
        mock_llm.text_completion.return_value = mock_llm_response

        # Second pass evaluation
        mock_eval_result = MagicMock()
        mock_eval_result.is_valid = True
        mock_eval_result.issues = []
        mock_eval_result.corrected_code = "fixed code"
        mock_eval_cls.return_value.evaluate.return_value = mock_eval_result

        mock_fb.capture.return_value = MagicMock(data_url="data:image/png;base64,x")
        mock_fb.capture_base64.return_value = "data:image/png;base64,x"

        result = render_expression("draw a circle")

        assert result["success"] is True
        assert result["heal_passes"] == 1
        assert mock_engine.run_headless.call_count == 2

    @patch("express.tools.render_expression.LLMClient")
    def test_llm_generation_failure(self, mock_llm_cls):
        """Test when LLM fails to generate code."""
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        # LLM returns empty/no code
        mock_llm_response = MagicMock()
        mock_llm_response.text = "I'm sorry, I can't generate code for that"
        mock_llm.generate_code.return_value = mock_llm_response

        result = render_expression("draw a circle")

        assert result["success"] is False
        assert any("Failed to generate" in i for i in result["issues"])


class TestExtractLuaCode:
    """Test Lua code extraction helper."""

    def test_lua_block(self):
        from express.tools.render_expression import _extract_lua_code
        text = '```lua\nfunction _init() end\n```'
        assert "function _init() end" in _extract_lua_code(text)

    def test_generic_block(self):
        from express.tools.render_expression import _extract_lua_code
        text = "```\nfunction _init() end\n```"
        assert "function _init() end" in _extract_lua_code(text)

    def test_no_code_block(self):
        from express.tools.render_expression import _extract_lua_code
        text = "function _init() end"
        assert _extract_lua_code(text) == "function _init() end"

    def test_prose_response(self):
        from express.tools.render_expression import _extract_lua_code
        text = "I'm sorry, I can't generate code for that"
        assert _extract_lua_code(text) is None

    def test_generic_block_with_code(self):
        from express.tools.render_expression import _extract_lua_code
        text = "```lua\nfunction _init() end\n```"
        assert "function _init() end" in _extract_lua_code(text)
