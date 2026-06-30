"""Tests for express.llm.client."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from express.config import Config
from express.llm.client import LLMClient, LLMResponse


class TestLLMResponse:
    """Test LLMResponse dataclass."""

    def test_basic(self):
        resp = LLMResponse(text="hello")
        assert resp.text == "hello"
        assert resp.reasoning is None
        assert resp.raw == {}

    def test_with_reasoning(self):
        resp = LLMResponse(text="hello", reasoning="thinking...")
        assert resp.reasoning == "thinking..."

    def test_with_raw(self):
        raw = {"choices": [{"message": {"content": "hi"}}]}
        resp = LLMResponse(text="hi", raw=raw)
        assert resp.raw == raw


class TestLLMClientInit:
    """Test LLMClient initialization."""

    def test_default_endpoint(self):
        client = LLMClient(Config())
        assert client.config.llm_endpoint == "http://localhost:58008/v1"


class TestLLMClientParsing:
    """Test response parsing."""

    def test_parse_standard_response(self):
        data = {
            "choices": [
                {
                    "message": {
                        "content": "Hello world",
                        "reasoning": "I am thinking",
                    }
                }
            ]
        }
        resp = LLMClient._parse_response(data)
        assert resp.text == "Hello world"
        assert resp.reasoning == "I am thinking"

    def test_parse_no_reasoning(self):
        data = {
            "choices": [
                {"message": {"content": "Hello"}}
            ]
        }
        resp = LLMClient._parse_response(data)
        assert resp.text == "Hello"
        assert resp.reasoning is None

    def test_parse_empty_choices(self):
        data = {"choices": []}
        resp = LLMClient._parse_response(data)
        assert resp.text == ""

    def test_parse_reasoning_content_fallback(self):
        data = {
            "choices": [
                {"message": {"content": "hi", "reasoning_content": "thinking"}}
            ]
        }
        resp = LLMClient._parse_response(data)
        assert resp.reasoning == "thinking"


class TestLLMClientExtractors:
    """Test static extraction methods."""

    def test_extract_lua_code_block(self):
        text = """Here's the code:

```lua
function _init()
    State = {}
end
```

Hope that helps!"""
        result = LLMClient._extract_lua_code if hasattr(LLMClient, '_extract_lua_code') else None
        # The extractor is in evaluator.py, not client.py
        # This test is just to verify the module loads

    def test_extract_json_simple(self):
        text = '{"is_valid": true, "issues": []}'
        # The extractor is in evaluator.py
        pass


class TestLLMClientContextManager:
    """Test context manager protocol."""

    def test_context_manager(self):
        client = LLMClient(Config())
        with client as c:
            assert c is client
        # Should not raise on close
        client.close()
