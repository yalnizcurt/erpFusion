"""
erpFusion — LLM Provider Abstraction

Defines the abstract interface for LLM providers so Groq and Bedrock
(or any future provider) can be swapped without changing upstream code.
"""

import json
import logging
from abc import ABC, abstractmethod

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
    usage: dict  # input_tokens, output_tokens
    raw_response: dict | None = None


class LLMProvider(ABC):
    """Abstract base for all LLM providers."""

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a text response from the LLM."""
        ...

    async def generate_json(self, request: LLMRequest) -> dict:
        """Generate a response and parse it as JSON."""
        response = await self.generate(request)
        content = response.content.strip()

        # Strip markdown code fences if present
        if content.startswith("```"):
            lines = content.split("\n")
            # Remove first line (```json or ```) and last line (```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            content = "\n".join(lines)

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM JSON response: {e}\nContent: {content[:500]}")
            raise ValueError(f"LLM did not return valid JSON: {e}") from e
