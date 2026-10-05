"""Groq provider checks use mocked HTTP; no network or live credentials."""

import json
from datetime import UTC, datetime

import httpx
import pytest

from app.config import Settings
from app.schemas import ArtifactVersionResponse
from app.services.llm.base import LLMRequest
from app.services.llm.groq import GroqProvider, GroqProviderError


def provider(monkeypatch, handler):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.services.llm.groq.httpx.AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )
    return GroqProvider(Settings(_env_file=None, app_env="test", groq_api_key="fixture-key"))


def response(**overrides):
    return {
        "id": "fixture-request",
        "model": "openai/gpt-oss-120b",
        "choices": [{
            "message": {
                "role": "assistant",
                "content": '{"ok": true}',
                "reasoning": "PRIVATE_REASONING_FIXTURE",
            },
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
    } | overrides


@pytest.mark.asyncio
async def test_receipt_keeps_only_safe_metadata(monkeypatch):
    def handle(request):
        return httpx.Response(200, json=response(), headers={"x-request-id": "safe-id"})

    llm = provider(monkeypatch, handle)
    result = await llm.generate(
        LLMRequest(system_prompt="private system", user_prompt="private input")
    )

    assert result.content == '{"ok": true}'
    assert result.raw_response == {
        "provider": "groq",
        "api": "chat.completions",
        "request_id": "safe-id",
        "model": "openai/gpt-oss-120b",
        "finish_reason": "stop",
        "usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
        "inference_config": {
            "temperature": 0.2,
            "max_tokens": 16384,
            "response_format": {"type": "json_object"},
        },
    }
    assert "PRIVATE_REASONING_FIXTURE" not in str(result.raw_response)
    assert "private input" not in str(result.raw_response)


@pytest.mark.asyncio
async def test_json_fallback_receipt_records_effective_parameters(monkeypatch):
    calls = []

    def handle(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(400, json={"error": {"code": "failed_generation"}})
        return httpx.Response(200, json=response())

    llm = provider(monkeypatch, handle)
    result = await llm.generate(LLMRequest(system_prompt="s", user_prompt="u"))

    assert len(calls) == 2
    assert "response_format" not in calls[1]
    assert result.raw_response["inference_config"] == {"temperature": 0.0, "max_tokens": 16384}


@pytest.mark.parametrize("finish_reason,content,code", [
    ("length", "partial", "GROQ_OUTPUT_TRUNCATED"),
    ("stop", [{"type": "text", "text": "structured"}], "GROQ_RESPONSE_INVALID"),
    ("tool_calls", "", "GROQ_OUTPUT_REJECTED"),
])
@pytest.mark.asyncio
async def test_truncated_and_nontext_outputs_fail_safely(monkeypatch, finish_reason, content, code):
    body = response(choices=[{"message": {"role": "assistant", "content": content},
                             "finish_reason": finish_reason}])
    llm = provider(monkeypatch, lambda request: httpx.Response(200, json=body))

    with pytest.raises(GroqProviderError, match=code):
        await llm.generate(LLMRequest(system_prompt="s", user_prompt="u"))


@pytest.mark.asyncio
async def test_http_failure_code_does_not_include_provider_body(monkeypatch, caplog):
    llm = provider(
        monkeypatch,
        lambda request: httpx.Response(401, json={"error": {"message": "PRIVATE_BODY"}}),
    )

    with pytest.raises(GroqProviderError, match="GROQ_AUTHENTICATION_FAILED") as error:
        await llm.generate(LLMRequest(system_prompt="s", user_prompt="u"))
    assert "PRIVATE_BODY" not in str(error.value)
    assert "PRIVATE_BODY" not in caplog.text


def test_version_serialization_removes_historical_provider_output():
    snapshot = {
        "input_bindings": {"source": "kept"},
        "provider_receipts": [{
            "provider": "groq",
            "api": "chat.completions",
            "request_id": "safe-id",
            "model": "openai/gpt-oss-120b",
            "finish_reason": "stop",
            "usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
            "inference_config": {"temperature": 0.2, "max_tokens": 100},
            "choices": [{"message": {"reasoning": "PRIVATE_REASONING", "content": "secret"}}],
        }],
    }
    version = ArtifactVersionResponse(
        id="version-id", artifact_id="artifact-id", version_number=1, state="APPROVED",
        content={}, file_path=None, parent_version_id=None, ai_model_version="model",
        input_context_snapshot=snapshot, generated_at=datetime.now(UTC), reviewer=None,
        reviewed_at=None, review_comments=None,
    )

    serialized = version.model_dump()["input_context_snapshot"]
    assert serialized["input_bindings"] == {"source": "kept"}
    receipt = serialized["provider_receipts"][0]
    assert receipt["request_id"] == "safe-id"
    assert receipt["usage"]["total_tokens"] == 20
    assert receipt["inference_config"] == {"temperature": 0.2, "max_tokens": 100}
    assert "choices" not in receipt
    assert "PRIVATE_REASONING" not in str(serialized)
    assert "choices" in snapshot["provider_receipts"][0]
