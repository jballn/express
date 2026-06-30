"""Tests for express.llm.prompts."""

from __future__ import annotations

from express.llm.prompts import (
    CODE_GENERATION_SYSTEM,
    SELF_HEAL_SYSTEM,
    SYSTEM_PROMPT_SNIPPET,
)


class TestPrompts:
    """Test that prompts contain required content."""

    def test_system_prompt_has_resolution(self):
        assert "320x180" in SYSTEM_PROMPT_SNIPPET

    def test_system_prompt_has_palette(self):
        assert "Pico-8" in SYSTEM_PROMPT_SNIPPET
        assert "16-color" in SYSTEM_PROMPT_SNIPPET

    def test_system_prompt_has_gfx_api(self):
        assert "gfx.print" in SYSTEM_PROMPT_SNIPPET
        assert "gfx.rect" in SYSTEM_PROMPT_SNIPPET
        assert "gfx.sprite" in SYSTEM_PROMPT_SNIPPET

    def test_system_prompt_has_input_api(self):
        assert "input.action_down" in SYSTEM_PROMPT_SNIPPET
        assert "input.action_pressed" in SYSTEM_PROMPT_SNIPPET

    def test_system_prompt_has_effect_api(self):
        assert "effect.hitstop" in SYSTEM_PROMPT_SNIPPET
        assert "effect.screen_shake" in SYSTEM_PROMPT_SNIPPET
        assert "effect.flash" in SYSTEM_PROMPT_SNIPPET

    def test_system_prompt_has_usagi_api(self):
        assert "usagi.random" in SYSTEM_PROMPT_SNIPPET
        assert "usagi.save" in SYSTEM_PROMPT_SNIPPET
        assert "usagi.load" in SYSTEM_PROMPT_SNIPPET

    def test_code_generation_includes_state_rule(self):
        assert "State.*" in CODE_GENERATION_SYSTEM
        assert "hot-reloads" in CODE_GENERATION_SYSTEM

    def test_self_heal_includes_evaluation_criteria(self):
        assert "is_valid" in SELF_HEAL_SYSTEM
        assert "issues" in SELF_HEAL_SYSTEM
        assert "code" in SELF_HEAL_SYSTEM

    def test_code_generation_requires_table_return(self):
        assert "_init" in CODE_GENERATION_SYSTEM
        assert "_update" in CODE_GENERATION_SYSTEM
        assert "_draw" in CODE_GENERATION_SYSTEM
