"""Tests for express.llm.prompts."""

from __future__ import annotations

from express.llm.prompts import (
    CODE_GENERATION_SYSTEM,
    SYSTEM_PROMPT_SNIPPET,
)


class TestPrompts:
    """Test prompt content and structure."""

    def test_system_prompt_has_resolution(self):
        assert "320x180" in SYSTEM_PROMPT_SNIPPET

    def test_system_prompt_has_palette(self):
        assert "Pico-8" in SYSTEM_PROMPT_SNIPPET

    def test_system_prompt_has_gfx_api(self):
        assert "gfx" in SYSTEM_PROMPT_SNIPPET

    def test_system_prompt_has_input_api(self):
        assert "input" in SYSTEM_PROMPT_SNIPPET

    def test_system_prompt_has_effect_api(self):
        assert "effect" in SYSTEM_PROMPT_SNIPPET

    def test_code_generation_includes_state_rule(self):
        assert "State.*" in CODE_GENERATION_SYSTEM

    def test_code_generation_requires_table_return(self):
        assert "_init" in CODE_GENERATION_SYSTEM
        assert "_update" in CODE_GENERATION_SYSTEM
        assert "_draw" in CODE_GENERATION_SYSTEM
