"""Tests for express.self_heal.evaluator."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from express.config import Config
from express.renderer.engine import EngineOutput
from express.self_heal.evaluator import ExpressionEvaluator, EvaluationResult


class TestEvaluationResult:
    """Test EvaluationResult dataclass."""

    def test_valid_result(self):
        result = EvaluationResult(
            is_valid=True,
            issues=[],
            corrected_code="return {}",
            raw_response=None,
        )
        assert result.is_valid is True
        assert result.issues == []


class TestEvaluatorConsoleAnalysis:
    """Test console log analysis."""

    def test_no_stderr(self):
        issues = ExpressionEvaluator._analyze_console_logs("")
        assert issues == []

    def test_no_stderr_whitespace(self):
        issues = ExpressionEvaluator._analyze_console_logs("   \n  ")
        assert issues == []

    def test_lua_runtime_error(self):
        stderr = "lua: main.lua:42: attempt to index a nil value"
        issues = ExpressionEvaluator._analyze_console_logs(stderr)
        assert any("nil value" in i for i in issues)

    def test_nil_index(self):
        stderr = "main.lua:10: attempt to index a nil value (local 'state')"
        issues = ExpressionEvaluator._analyze_console_logs(stderr)
        assert any("nil value" in i for i in issues)

    def test_nil_call(self):
        stderr = "main.lua:20: attempt to call a nil value"
        issues = ExpressionEvaluator._analyze_console_logs(stderr)
        assert any("nil value" in i for i in issues)

    def test_type_mismatch(self):
        stderr = "main.lua:15: attempt to call a string value"
        issues = ExpressionEvaluator._analyze_console_logs(stderr)
        assert any("Type mismatch" in i for i in issues)

    def test_bad_argument(self):
        stderr = "bad argument #1 to 'rect' (number expected)"
        issues = ExpressionEvaluator._analyze_console_logs(stderr)
        assert any("Bad argument" in i for i in issues)

    def test_syntax_error(self):
        stderr = "main.lua:5: unexpected symbol near '<eof>'"
        issues = ExpressionEvaluator._analyze_console_logs(stderr)
        assert any("Syntax error" in i for i in issues)

    def test_multiple_issues(self):
        stderr = "main.lua:5: unexpected symbol\nmain.lua:10: attempt to index a nil value"
        issues = ExpressionEvaluator._analyze_console_logs(stderr)
        assert len(issues) >= 2


class TestEvaluatorExtractLuaCode:
    """Test Lua code extraction from LLM responses."""

    def test_lua_code_block(self):
        text = """Here's your code:

```lua
function _init()
    State = {}
end

function _update()
    State.x = State.x + 1
end

function _draw()
    gfx.print("Hello", 10, 10, 15)
end
```

That should work!"""
        result = ExpressionEvaluator._extract_lua_code(text)
        assert "function _init()" in result
        assert "gfx.print" in result

    def test_generic_code_block(self):
        text = "```\nfunction _init() end\n```"
        result = ExpressionEvaluator._extract_lua_code(text)
        assert "function _init()" in result

    def test_plain_text_fallback(self):
        text = "function _init() end\nfunction _update() end\nfunction _draw() end"
        result = ExpressionEvaluator._extract_lua_code(text)
        assert result == text.strip()


class TestEvaluatorExtractJSON:
    """Test JSON extraction from LLM responses."""

    def test_plain_json(self):
        text = '{"is_valid": true, "issues": []}'
        result = ExpressionEvaluator._extract_json(text)
        assert '"is_valid": true' in result

    def test_json_in_code_block(self):
        text = "```\n{\"is_valid\": false, \"issues\": [\"error\"]}\n```"
        result = ExpressionEvaluator._extract_json(text)
        assert '"is_valid": false' in result

    def test_json_in_markdown(self):
        text = "Here's the result:\n```json\n{\"is_valid\": true}\n```\nDone!"
        result = ExpressionEvaluator._extract_json(text)
        assert '"is_valid": true' in result


class TestEvaluatorParseResponse:
    """Test evaluation response parsing."""

    def test_valid_json_response(self):
        evaluator = ExpressionEvaluator(Config())
        mock_response = MagicMock()
        mock_response.text = '{"is_valid": true, "issues": [], "code": "return {}"}'

        result = evaluator._parse_evaluation_response(mock_response, "old code", [])
        assert result.is_valid is True
        assert result.issues == []
        assert result.corrected_code == "return {}"

    def test_invalid_json_response(self):
        evaluator = ExpressionEvaluator(Config())
        mock_response = MagicMock()
        mock_response.text = "I'm not sure what to do here"

        result = evaluator._parse_evaluation_response(mock_response, "old code", [])
        assert result.is_valid is False
        assert any("LLD did not return valid JSON" in i or "LLM did not return valid JSON" in i for i in result.issues)

    def test_issues_from_list(self):
        evaluator = ExpressionEvaluator(Config())
        mock_response = MagicMock()
        mock_response.text = '{"is_valid": false, "issues": ["clipped", "wrong color"], "code": "fixed"}'

        result = evaluator._parse_evaluation_response(mock_response, "old code", ["crash"])
        assert result.is_valid is False
        assert "crash" in result.issues
        assert "clipped" in result.issues

    def test_issues_from_string(self):
        evaluator = ExpressionEvaluator(Config())
        mock_response = MagicMock()
        mock_response.text = '{"is_valid": false, "issues": "single issue", "code": "fixed"}'

        result = evaluator._parse_evaluation_response(mock_response, "old code", [])
        assert "single issue" in result.issues

    def test_duplicate_issues_removed(self):
        evaluator = ExpressionEvaluator(Config())
        mock_response = MagicMock()
        mock_response.text = '{"is_valid": false, "issues": ["crash"], "code": "fixed"}'

        result = evaluator._parse_evaluation_response(mock_response, "old code", ["crash"])
        assert result.issues.count("crash") == 1
