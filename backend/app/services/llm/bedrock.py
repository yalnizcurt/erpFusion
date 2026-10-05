"""Regional Bedrock Converse using workload IAM and content-free provider receipts."""

import asyncio
import logging
import math
import re
from contextlib import closing
from importlib import import_module
from typing import Any

from app.config import Settings, get_settings
from app.services.llm.base import LLMProvider, LLMRequest, LLMResponse

logger = logging.getLogger("erpfusion.llm.bedrock")


class BedrockProviderError(RuntimeError):
    """Safe provider failure; never contains SDK response bodies or customer content."""


def _runtime_client(settings: Settings) -> Any:
    try:
        boto3 = import_module("boto3")
        sdk_config = import_module("botocore.config").Config
    except ImportError:
        raise BedrockProviderError("BEDROCK_DEPENDENCY_MISSING") from None
    # SDK debug output includes prompts and signed requests.
    for name in ("boto3", "botocore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    return boto3.client(
        "bedrock-runtime",
        region_name=settings.bedrock_region,
        endpoint_url=(settings.bedrock_endpoint_url or
                      f"https://bedrock-runtime.{settings.bedrock_region}.amazonaws.com"),
        verify=True,
        config=sdk_config(
            connect_timeout=settings.bedrock_connect_timeout_seconds,
            read_timeout=settings.bedrock_timeout_seconds / settings.bedrock_max_attempts,
            retries={"mode": "standard", "total_max_attempts": settings.bedrock_max_attempts},
            ignore_configured_endpoint_urls=True,
            proxies={},
        ),
    )


def _error_code(error: Exception) -> str:
    response = getattr(error, "response", {})
    if isinstance(response, dict) and isinstance(response.get("Error"), dict):
        code = response["Error"].get("Code")
        if not isinstance(code, str):
            return "BEDROCK_UNAVAILABLE"
        return {
            "AccessDeniedException": "BEDROCK_ACCESS_DENIED",
            "ResourceNotFoundException": "BEDROCK_MODEL_UNAVAILABLE",
            "ModelNotReadyException": "BEDROCK_MODEL_NOT_READY",
            "ThrottlingException": "BEDROCK_THROTTLED",
            "ServiceQuotaExceededException": "BEDROCK_QUOTA_EXCEEDED",
            "ValidationException": "BEDROCK_REQUEST_REJECTED",
            "ModelTimeoutException": "BEDROCK_TIMEOUT",
        }.get(code, "BEDROCK_UNAVAILABLE")
    if type(error).__name__ in {"ReadTimeoutError", "ConnectTimeoutError"}:
        return "BEDROCK_TIMEOUT"
    if type(error).__name__ in {"NoCredentialsError", "PartialCredentialsError"}:
        return "BEDROCK_IAM_CREDENTIALS_UNAVAILABLE"
    return "BEDROCK_UNAVAILABLE"


class BedrockProvider(LLMProvider):
    def __init__(self, settings: Settings | None = None, *, client: Any = None) -> None:
        self.settings = settings or get_settings()
        issues = self.settings.bedrock_configuration_issues()
        if issues:
            raise BedrockProviderError("; ".join(issues))
        if self.settings.is_production and self.settings.demo_mode:
            raise BedrockProviderError("DEMO_MODE_FORBIDDEN")
        self.model = self.settings.bedrock_model_id
        self._client = client

    def _converse(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._client is not None:
            return self._client.converse(**payload)
        with closing(_runtime_client(self.settings)) as client:
            return client.converse(**payload)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if (
            not request.user_prompt.strip()
            or not 1 <= request.max_tokens <= 128000
            or request.response_format not in {"json_object", "text"}
            or not math.isfinite(request.temperature)
            or not 0 <= request.temperature <= 1
        ):
            raise BedrockProviderError("BEDROCK_REQUEST_INVALID")
        system = request.system_prompt
        if request.response_format == "json_object":
            system += "\nReturn a single valid JSON object without markdown fences."
        try:
            input_bytes = len(system.encode("utf-8")) + len(request.user_prompt.encode("utf-8"))
        except UnicodeError:
            raise BedrockProviderError("BEDROCK_REQUEST_INVALID") from None
        if input_bytes > self.settings.bedrock_max_input_bytes:
            raise BedrockProviderError("BEDROCK_INPUT_TOO_LARGE")
        inference = {
            "maxTokens": min(request.max_tokens, self.settings.bedrock_max_tokens),
            "temperature": request.temperature,
        }
        payload: dict[str, Any] = {
            "modelId": self.model,
            "messages": [{"role": "user", "content": [{"text": request.user_prompt}]}],
            "inferenceConfig": inference,
        }
        if system:
            payload["system"] = [{"text": system}]
        try:
            # ponytail: timed-out threads finish under SDK limits; use a worker process
            # if hard cancellation of credential lookup or network I/O becomes required.
            response = await asyncio.wait_for(
                asyncio.to_thread(self._converse, payload),
                timeout=self.settings.bedrock_timeout_seconds,
            )
        except BedrockProviderError:
            raise
        except TimeoutError:
            logger.warning("Bedrock invocation failed code=BEDROCK_TIMEOUT")
            raise BedrockProviderError("BEDROCK_TIMEOUT") from None
        except Exception as error:
            code = _error_code(error)
            logger.warning("Bedrock invocation failed code=%s", code)
            raise BedrockProviderError(code) from None
        try:
            stop_reason = response["stopReason"]
            if stop_reason == "max_tokens":
                raise BedrockProviderError("BEDROCK_OUTPUT_TRUNCATED")
            if stop_reason not in {"end_turn", "stop_sequence"}:
                raise BedrockProviderError("BEDROCK_OUTPUT_REJECTED")
            message = response["output"]["message"]
            blocks = message["content"]
            if message["role"] != "assistant" or not isinstance(blocks, list) or not blocks:
                raise ValueError
            if any(not isinstance(block, dict) or set(block) != {"text"} for block in blocks):
                raise ValueError
            if any(not isinstance(block["text"], str) for block in blocks):
                raise ValueError
            content = "".join(block["text"] for block in blocks)
            if not content.strip() or len(content.encode("utf-8")) > 1048576:
                raise ValueError
            usage = {
                "input_tokens": response["usage"]["inputTokens"],
                "output_tokens": response["usage"]["outputTokens"],
                "total_tokens": response["usage"]["totalTokens"],
            }
            if any(type(value) is not int or value < 0 for value in usage.values()):
                raise ValueError
            request_id = response.get("ResponseMetadata", {}).get("RequestId", "")
            if not isinstance(request_id, str) or not re.fullmatch(
                r"[A-Za-z0-9-]{1,128}", request_id
            ):
                request_id = ""
        except BedrockProviderError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError):
            raise BedrockProviderError("BEDROCK_RESPONSE_INVALID") from None
        return LLMResponse(
            content=content,
            model=self.model,
            usage=usage,
            raw_response={
                "provider": "bedrock", "api": "converse", "region": self.settings.bedrock_region,
                "model_id": self.model, "request_id": request_id, "stop_reason": stop_reason,
                "usage": usage, "inference_config": inference,
            },
        )
