"""
HighStudio — Groq LLM Provider

Implements the LLM provider interface using Groq's OpenAI-compatible API.
Uses httpx for async HTTP calls to avoid additional SDK dependencies.
"""

import asyncio
import logging
import re
from typing import Any

import httpx

from app.config import Settings, get_settings, secret_is_configured
from app.services.llm.base import LLMProvider, LLMRequest, LLMResponse

logger = logging.getLogger("erpfusion.llm.groq")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqProviderError(RuntimeError):
    """Safe provider failure; never contains provider bodies or generated content."""


class GroqProvider(LLMProvider):
    """Groq Cloud API provider using OpenAI-compatible endpoint."""

    def __init__(self, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        self.api_key = settings.groq_api_key
        self.model = settings.groq_model
        if not secret_is_configured(self.api_key):
            raise ValueError("GROQ_API_KEY_MISSING: configure a live provider credential.")

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Send a chat completion request to Groq."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
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
            effective_payload = payload

            async def post(body: dict[str, Any]) -> httpx.Response:
                nonlocal effective_payload
                effective_payload = body
                try:
                    return await client.post(GROQ_API_URL, json=body, headers=headers)
                except httpx.TimeoutException:
                    raise GroqProviderError("GROQ_TIMEOUT") from None
                except httpx.HTTPError:
                    raise GroqProviderError("GROQ_UNAVAILABLE") from None

            resp = await post(payload)

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
                resp = await post(payload)

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
                    fallback_payload = {
                        key: value for key, value in payload.items() if key != "response_format"
                    }
                    fallback_payload["temperature"] = 0.0
                    logger.warning(
                        "Groq constrained JSON generation failed; retrying once in JSON-prompt mode"
                    )
                    resp = await post(fallback_payload)

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
                        resp = await post(payload)

            if resp.status_code != 200:
                # Provider error bodies may echo customer inputs or credentials.
                code = {
                    401: "GROQ_AUTHENTICATION_FAILED",
                    403: "GROQ_ACCESS_DENIED",
                    404: "GROQ_MODEL_UNAVAILABLE",
                    413: "GROQ_TOKEN_BUDGET_EXCEEDED",
                    429: "GROQ_THROTTLED",
                }.get(resp.status_code, "GROQ_UNAVAILABLE")
                logger.warning("Groq invocation failed code=%s", code)
                raise GroqProviderError(f"{code}: HTTP {resp.status_code}")

            try:
                data = resp.json()
                choice = data["choices"][0]
                message = choice["message"]
                finish_reason = choice["finish_reason"]
                content = message["content"]
                if finish_reason in {"length", "max_tokens"}:
                    raise GroqProviderError("GROQ_OUTPUT_TRUNCATED")
                if finish_reason != "stop":
                    raise GroqProviderError("GROQ_OUTPUT_REJECTED")
                if (
                    not isinstance(content, str)
                    or not content.strip()
                    or len(content.encode("utf-8")) > 1048576
                ):
                    raise ValueError
                usage_data = data["usage"]
                usage = {
                    "input_tokens": usage_data["prompt_tokens"],
                    "output_tokens": usage_data["completion_tokens"],
                    "total_tokens": usage_data["total_tokens"],
                }
                if any(type(value) is not int or value < 0 for value in usage.values()):
                    raise ValueError
                model = data.get("model", self.model)
                if not isinstance(model, str) or not model:
                    raise ValueError
                request_id = resp.headers.get("x-request-id", data.get("id", ""))
                if not isinstance(request_id, str) or not re.fullmatch(
                    r"[A-Za-z0-9_-]{1,128}", request_id
                ):
                    request_id = ""
            except GroqProviderError:
                raise
            except (KeyError, IndexError, TypeError, ValueError, AttributeError, UnicodeError):
                raise GroqProviderError("GROQ_RESPONSE_INVALID") from None

        inference_config = {
            key: effective_payload[key]
            for key in ("temperature", "max_tokens", "response_format")
            if key in effective_payload
        }

        return LLMResponse(
            content=content,
            model=model,
            usage=usage,
            raw_response={
                "provider": "groq",
                "api": "chat.completions",
                "request_id": request_id,
                "model": model,
                "finish_reason": finish_reason,
                "usage": usage,
                "inference_config": inference_config,
            },
        )
