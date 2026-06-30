"""OpenAI-compatible API client for the Express MCP server.

Handles structured JSON generation and vision-based evaluation via
any OpenAI-compatible endpoint (llama.cpp server, Ollama, vLLM, etc.).
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from express.config import Config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMResponse:
    """Structured response from the LLM."""

    text: str
    """The assistant's text content."""
    reasoning: str | None = None
    """Optional reasoning/thinking steps (if the model supports it)."""
    raw: dict[str, Any] = field(repr=False, default_factory=dict)
    """The full raw API response for debugging."""


class LLMClient:
    """HTTP client for OpenAI-compatible chat completion endpoints.

    Usage:
        client = LLMClient(config)
        response = await client.generate_text(system_prompt, user_message)
        response = await client.generate_vision(system_prompt, image_data_url, user_message)
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self._client = httpx.Client(
            base_url=config.llm_endpoint.rstrip("/"),
            timeout=httpx.Timeout(60.0, connect=10.0),
            headers={"Content-Type": "application/json"},
        )

    def text_completion(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
    ) -> LLMResponse:
        """Send a text-only completion request and return structured response."""
        payload = self._build_payload(system_prompt, user_message, temperature)
        resp = self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return self._parse_response(data)

    def vision_completion(
        self,
        system_prompt: str,
        image_data_url: str,
        user_message: str,
        temperature: float = 0.3,
    ) -> LLMResponse:
        """Send a vision (image + text) completion request."""
        payload = self._build_vision_payload(
            system_prompt, image_data_url, user_message, temperature
        )
        resp = self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return self._parse_response(data)

    def generate_code(
        self,
        system_prompt: str,
        user_intent: str,
        temperature: float = 0.3,
    ) -> LLMResponse:
        """Generate Lua code from a user intent with structured JSON output.

        The model returns a JSON object with:
          - "reasoning": explanation of approach
          - "code": raw Lua code string
        """
        user_message = json.dumps({
            "type": "code_generation",
            "user_intent": user_intent,
        }, indent=2)
        return self.text_completion(system_prompt, user_message, temperature)

    def evaluate_expression(
        self,
        system_prompt: str,
        image_data_url: str,
        console_logs: str,
        user_message: str = "",
        temperature: float = 0.3,
    ) -> LLMResponse:
        """Evaluate a rendered frame via vision + console logs.

        Returns JSON with:
          - "is_valid": bool
          - "issues": array of issue descriptions
          - "code": corrected Lua code (if issues found, else same as input)
        """
        console_section = f"--- Console Logs ---\n{console_logs}\n" if console_logs else ""
        user_content = (
            f"{console_section}\n--- User Intent ---\n{user_message}\n"
        )
        payload = self._build_vision_payload(
            system_prompt,
            image_data_url,
            user_content,
            temperature,
            response_format=True,
        )
        resp = self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return self._parse_response(data)

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ── Private helpers ──────────────────────────────────────────────

    def _build_payload(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float,
    ) -> dict[str, Any]:
        return {
            "model": self.config.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": temperature,
            "max_tokens": 4096,
        }

    def _build_vision_payload(
        self,
        system_prompt: str,
        image_data_url: str,
        user_message: str,
        temperature: float,
        response_format: bool = False,
    ) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                    {"type": "text", "text": user_message},
                ],
            },
        ]
        payload: dict[str, Any] = {
            "model": self.config.llm_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 4096,
        }
        if response_format:
            payload["response_format"] = {"type": "json_object"}
        return payload

    @staticmethod
    def _parse_response(data: dict[str, Any]) -> LLMResponse:
        """Parse the API response into a structured LLMResponse."""
        choices = data.get("choices", [])
        if not choices:
            return LLMResponse(text="", raw=data)
        message = choices[0].get("message", {})
        text = message.get("content", "")
        reasoning = message.get("reasoning") or message.get("reasoning_content")
        return LLMResponse(text=text, reasoning=reasoning or None, raw=data)
