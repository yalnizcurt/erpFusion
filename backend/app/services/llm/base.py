"""
HighStudio — LLM Provider Abstraction

Defines the abstract interface for LLM providers so Groq and Bedrock
(or any future provider) can be swapped without changing upstream code.
"""

import json
import logging
import math
import re
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger("erpfusion.llm")


class LLMRequest(BaseModel):
    """Request to send to an LLM provider."""

    system_prompt: str
    user_prompt: str
    temperature: float = 0.2
    max_tokens: int = 16384
    response_format: str = "json_object"


class LLMResponse(BaseModel):
    """Response from an LLM provider."""

    content: str
    model: str
    usage: dict[str, int]  # input_tokens, output_tokens
    raw_response: dict[str, Any] | None = None


def safe_provider_receipt(receipt: Any) -> dict[str, Any]:
    """Keep receipt metadata and typed budgets; discard provider output fields."""
    if not isinstance(receipt, dict):
        return {}
    safe: dict[str, Any] = {}
    for key in (
        "provider", "api", "request_id", "model", "model_id", "region",
        "finish_reason", "stop_reason",
    ):
        value = receipt.get(key)
        if (
            isinstance(value, str)
            and len(value) <= 128
            and re.fullmatch(r"[A-Za-z0-9_.:/-]*", value)
        ):
            safe[key] = value
    usage: Any = receipt.get("usage")
    if isinstance(usage, dict):
        usage_fields: dict[str, int] = {}
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = usage.get(key)
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and 0 <= value <= 1_000_000_000
            ):
                usage_fields[key] = value
        if usage_fields:
            safe["usage"] = usage_fields
    inference: Any = receipt.get("inference_config")
    if isinstance(inference, dict):
        inference_fields: dict[str, Any] = {}
        value = inference.get("temperature")
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and 0 <= value <= 2
        ):
            inference_fields["temperature"] = value
        for key in ("max_tokens", "maxTokens"):
            value = inference.get(key)
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and 1 <= value <= 128_000
            ):
                inference_fields[key] = value
        response_format = inference.get("response_format")
        if response_format in ({"type": "json_object"}, {"type": "text"}):
            inference_fields["response_format"] = response_format
        if inference_fields:
            safe["inference_config"] = inference_fields
    return safe


class LLMProvider(ABC):
    """Abstract base for all LLM providers."""

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a text response from the LLM."""
        ...

    async def generate_json(self, request: LLMRequest) -> dict[str, Any]:
        """Generate a response and parse it as JSON."""
        response = await self.generate(request)
        content = response.content.strip()

        # Strip markdown code fences if present
        if content.startswith("```"):
            lines = content.split("\n")
            # Remove first line (```json or ```) and last line (```)
            lines = [line for line in lines if not line.strip().startswith("```")]
            content = "\n".join(lines)

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error("LLM output is invalid JSON; line=%d column=%d", e.lineno, e.colno)
            raise ValueError(
                "LLM_OUTPUT_INVALID_JSON: the provider output could not be parsed."
            ) from None
        if not isinstance(parsed, dict):
            logger.error("LLM output does not match the required object structure")
            raise ValueError("LLM_OUTPUT_INVALID_STRUCTURE: expected a JSON object.")
        return parsed
