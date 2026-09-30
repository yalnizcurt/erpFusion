"""
erpFusion — Groq LLM Provider

Implements the LLM provider interface using Groq's OpenAI-compatible API.
Uses httpx for async HTTP calls to avoid additional SDK dependencies.
"""

import logging
import asyncio
import re

import httpx

from app.config import get_settings
from app.services.llm.base import LLMProvider, LLMRequest, LLMResponse

logger = logging.getLogger("erpfusion.llm.groq")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider(LLMProvider):
    """Groq Cloud API provider using OpenAI-compatible endpoint."""

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.groq_api_key
        self.model = settings.groq_model
        if not self.api_key or self.api_key == "your_groq_api_key_here":
            logger.warning("GROQ_API_KEY not set — LLM calls will fail")

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Send a chat completion request to Groq."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}

        logger.info(f"Groq request: model={self.model}, temp={request.temperature}")

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(GROQ_API_URL, json=payload, headers=headers)

            # Groq may reject an otherwise valid request when the account's
            # token-per-minute bucket is temporarily full. Honor its retry
            # hint once so the generation route can finish without creating a
            # failed artifact revision for a transient provider throttle.
            if resp.status_code == 429:
                retry_after = resp.headers.get("retry-after")
                if retry_after is not None:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = 5.0
                else:
                    match = re.search(r"try again in ([0-9.]+)s", resp.text, re.IGNORECASE)
                    delay = float(match.group(1)) if match else 5.0
                delay = min(max(delay, 0.5), 30.0)
                logger.warning("Groq rate limit reached; retrying once after %.1fs", delay)
                await asyncio.sleep(delay)
                resp = await client.post(GROQ_API_URL, json=payload, headers=headers)

            # Some Groq model/runtime combinations return a 400 when the
            # constrained JSON decoder cannot complete an otherwise valid
            # generation. Retry once without decoder constraints; the shared
            # generate_json layer still parses and rejects invalid JSON before
            # any artifact can be stored or reviewed.
            if resp.status_code == 400:
                try:
                    error = resp.json().get("error", {})
                    detail = str(error.get("message") or "")
                    code = str(error.get("code") or "")
                except (ValueError, AttributeError):
                    detail, code = "", ""
                if code == "failed_generation" or "Failed to generate JSON" in detail:
                    fallback_payload = {key: value for key, value in payload.items() if key != "response_format"}
                    fallback_payload["temperature"] = 0.0
                    logger.warning("Groq constrained JSON generation failed; retrying once in JSON-prompt mode")
                    resp = await client.post(GROQ_API_URL, json=fallback_payload, headers=headers)

            # On lower TPM tiers Groq can return 413 when input tokens plus
            # the requested completion budget exceed the minute allowance.
            # Retry once with a smaller completion budget, preserving the
            # complete prompt and leaving a small margin for estimation.
            if resp.status_code == 413:
                detail = resp.text
                limits = re.search(r"Limit\s+(\d+),\s*Requested\s+(\d+)", detail, re.IGNORECASE)
                current_budget = int(payload["max_tokens"])
                if limits:
                    limit, requested = (int(value) for value in limits.groups())
                    estimated_input = max(0, requested - current_budget)
                    smaller_budget = min(current_budget - 1, limit - estimated_input - 256)
                    if smaller_budget >= 1024:
                        payload["max_tokens"] = smaller_budget
                        logger.warning(
                            "Groq token budget exceeded; retrying once with max_tokens=%s",
                            smaller_budget,
                        )
                        resp = await client.post(GROQ_API_URL, json=payload, headers=headers)

            if resp.status_code != 200:
                try:
                    error = resp.json().get("error", {})
                    detail = str(error.get("message") or error.get("code") or "")
                except (ValueError, AttributeError):
                    detail = ""
                detail = re.sub(r"org_[A-Za-z0-9]+", "[redacted]", detail)
                detail = re.sub(r"(?i)Bearer\s+\S+", "Bearer [redacted]", detail)
                logger.error("Groq API returned HTTP %s: %s", resp.status_code, detail[:500])
                raise RuntimeError(
                    f"Groq API returned HTTP {resp.status_code}; check provider limits or configuration."
                )

            data = resp.json()

        choice = data["choices"][0]
        usage = data.get("usage", {})

        return LLMResponse(
            content=choice["message"]["content"],
            model=data.get("model", self.model),
            usage={
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            },
            raw_response=data,
        )
