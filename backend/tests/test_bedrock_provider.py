"""Bedrock contract checks use SDK stubs; no credentials or live AWS access required."""

import asyncio
from threading import Event

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.llm.base import LLMRequest
from app.services.llm.bedrock import BedrockProvider, BedrockProviderError, _runtime_client
from app.services.llm.factory import ProviderConfigurationError, get_llm_provider

boto3 = pytest.importorskip("boto3")
Stubber = pytest.importorskip("botocore.stub").Stubber


def settings(**overrides):
    return Settings(_env_file=None, **({
        "app_env": "test", "llm_provider": "bedrock", "demo_mode": False,
    } | overrides))


def production_settings(**overrides):
    return settings(**({
        "app_env": "production",
        "bedrock_endpoint_url": "https://vpce-012345abcdef.bedrock-runtime.us-east-1.vpce.amazonaws.com",
        "bedrock_retention_approved": True,
        "bedrock_residency_approved": True,
        "bedrock_invocation_logging_disabled": True,
    } | overrides))


def request(**overrides):
    return LLMRequest(**({"system_prompt": "system", "user_prompt": "private input"} | overrides))


def response(**overrides):
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": '{"ok": true}'}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 12, "outputTokens": 8, "totalTokens": 20},
        "metrics": {"latencyMs": 10},
        "ResponseMetadata": {"RequestId": "safe-request-id", "HTTPStatusCode": 200},
    } | overrides


def stub_client():
    # Synthetic test credentials keep the SDK from inspecting the user's IAM session.
    return boto3.client("bedrock-runtime", region_name="us-east-1",
                        aws_access_key_id="fixture", aws_secret_access_key="fixture")


@pytest.mark.asyncio
async def test_converse_contract_and_content_free_receipt():
    client = stub_client()
    expected = {
        "modelId": "amazon.nova-pro-v1:0",
        "messages": [{"role": "user", "content": [{"text": "private input"}]}],
        "system": [{"text": "system\nReturn a single valid JSON object without markdown fences."}],
        "inferenceConfig": {"maxTokens": 5000, "temperature": 0.2},
    }
    with Stubber(client) as stub:
        stub.add_response("converse", response(), expected)
        result = await BedrockProvider(settings(), client=client).generate(request())
        stub.assert_no_pending_responses()
    assert result.content == '{"ok": true}'
    assert result.model == expected["modelId"]
    assert result.usage == {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20}
    assert result.raw_response["request_id"] == "safe-request-id"
    assert result.raw_response["inference_config"] == expected["inferenceConfig"]
    assert "private input" not in str(result.raw_response)
    assert result.content not in str(result.raw_response)


@pytest.mark.asyncio
async def test_shared_json_validation_remains_in_use():
    client = stub_client()
    with Stubber(client) as stub:
        stub.add_response("converse", response())
        result = await BedrockProvider(settings(), client=client).generate_json(request())
        assert result == {"ok": True}


@pytest.mark.parametrize("aws_code,safe_code", [
    ("AccessDeniedException", "BEDROCK_ACCESS_DENIED"),
    ("ThrottlingException", "BEDROCK_THROTTLED"),
    ("ValidationException", "BEDROCK_REQUEST_REJECTED"),
    ("ModelTimeoutException", "BEDROCK_TIMEOUT"),
])
@pytest.mark.asyncio
async def test_provider_errors_do_not_leak_bodies(aws_code, safe_code, caplog):
    client = stub_client()
    with Stubber(client) as stub:
        stub.add_client_error("converse", service_error_code=aws_code,
                              service_message="CONFIDENTIAL_PROVIDER_BODY")
        with pytest.raises(BedrockProviderError, match=safe_code) as error:
            await BedrockProvider(settings(), client=client).generate(request())
    assert "CONFIDENTIAL" not in str(error.value)
    assert "CONFIDENTIAL" not in caplog.text


@pytest.mark.asyncio
async def test_timeout_does_not_block_event_loop():
    release = Event()
    started = Event()

    class BlockingClient:
        def converse(self, **kwargs):
            started.set()
            release.wait(1)
            return response()

    task = asyncio.create_task(BedrockProvider(
        settings(bedrock_timeout_seconds=0.02), client=BlockingClient()
    ).generate(request()))
    try:
        await asyncio.sleep(0.005)
        assert not task.done()
        with pytest.raises(BedrockProviderError, match="BEDROCK_TIMEOUT"):
            await task
        assert started.is_set()
    finally:
        release.set()


@pytest.mark.parametrize("overrides,code", [
    ({"bedrock_model_id": "global.amazon.nova-pro-v1:0"}, "BEDROCK_MODEL_UNSUPPORTED"),
    ({"bedrock_model_id": "us.amazon.nova-pro-v1:0"}, "BEDROCK_MODEL_UNSUPPORTED"),
    ({"bedrock_region": "us-west-2"}, "BEDROCK_REGION_UNSUPPORTED"),
    ({"bedrock_endpoint_url": "https://attacker.example"}, "BEDROCK_ENDPOINT_INVALID"),
    ({"bedrock_endpoint_url": "http://bedrock-runtime.us-east-1.amazonaws.com"},
     "BEDROCK_ENDPOINT_INVALID"),
    ({"bedrock_endpoint_url": "https://bedrock-runtime.us-west-2.amazonaws.com"},
     "BEDROCK_ENDPOINT_INVALID"),
    ({"bedrock_endpoint_url": "https://bedrock-runtime.us-east-1.amazonaws.com/?x=secret"},
     "BEDROCK_ENDPOINT_INVALID"),
    ({"bedrock_endpoint_url": "https://user:secret@bedrock-runtime.us-east-1.amazonaws.com"},
     "BEDROCK_ENDPOINT_INVALID"),
])
def test_unapproved_destinations_and_profiles_fail_closed(overrides, code):
    configured = settings(**overrides)
    assert code in configured.configuration_issues()
    with pytest.raises(ProviderConfigurationError, match=code):
        get_llm_provider(configured)


@pytest.mark.parametrize("overrides,code", [
    ({"bedrock_endpoint_url": ""}, "BEDROCK_PRIVATE_ENDPOINT_REQUIRED"),
    ({"bedrock_endpoint_url": "https://bedrock-runtime.us-east-1.amazonaws.com"},
     "BEDROCK_PRIVATE_ENDPOINT_REQUIRED"),
    ({"bedrock_retention_approved": False}, "BEDROCK_RETENTION_APPROVAL_REQUIRED"),
    ({"bedrock_residency_approved": False}, "BEDROCK_RESIDENCY_APPROVAL_REQUIRED"),
    ({"bedrock_invocation_logging_disabled": False}, "BEDROCK_INVOCATION_LOGGING_MUST_BE_DISABLED"),
    ({"llm_provider": "groq", "groq_api_key": "fixture-key"}, "BEDROCK_PROVIDER_REQUIRED"),
])
def test_production_requires_explicit_privacy_and_network_approval(overrides, code):
    configured = production_settings(**overrides)
    assert code in configured.configuration_issues()
    with pytest.raises(ProviderConfigurationError, match=code):
        get_llm_provider(configured)


def test_factory_constructs_approved_provider_without_copying_credentials():
    assert isinstance(get_llm_provider(production_settings()), BedrockProvider)


def test_sdk_uses_iam_chain_verified_tls_pinned_endpoint_and_bounded_retries(monkeypatch):
    calls = []
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: calls.append((args, kwargs)))
    configured = production_settings(
        aws_access_key_id="DO_NOT_COPY", aws_secret_access_key="SECRET"
    )
    _runtime_client(configured)
    args, kwargs = calls[0]
    assert args == ("bedrock-runtime",)
    assert kwargs["verify"] is True
    assert kwargs["region_name"] == "us-east-1"
    assert kwargs["endpoint_url"] == configured.bedrock_endpoint_url
    assert not {"aws_access_key_id", "aws_secret_access_key", "aws_session_token"} & kwargs.keys()
    assert kwargs["config"].retries == {"mode": "standard", "total_max_attempts": 2}
    assert kwargs["config"].ignore_configured_endpoint_urls is True
    assert kwargs["config"].proxies == {}


@pytest.mark.parametrize("changes", [
    {"bedrock_max_tokens": 5001}, {"bedrock_temperature": 2},
    {"bedrock_api": "invoke_model"}, {"bedrock_max_input_bytes": 1048577},
    {"erp_connection_timeout_seconds": 0}, {"erp_max_response_bytes": -1},
])
def test_settings_have_typed_bounds(changes):
    with pytest.raises(ValidationError):
        settings(**changes)


@pytest.mark.asyncio
async def test_oversized_prompts_fail_before_provider_call():
    with pytest.raises(BedrockProviderError, match="BEDROCK_INPUT_TOO_LARGE"):
        provider = BedrockProvider(settings(bedrock_max_input_bytes=4), client=object())
        await provider.generate(request())


@pytest.mark.parametrize("stop,code", [
    ("max_tokens", "BEDROCK_OUTPUT_TRUNCATED"),
    ("content_filtered", "BEDROCK_OUTPUT_REJECTED"),
    ("tool_use", "BEDROCK_OUTPUT_REJECTED"),
])
@pytest.mark.asyncio
async def test_incomplete_or_untrusted_outputs_cannot_become_artifacts(stop, code):
    client = stub_client()
    with Stubber(client) as stub:
        stub.add_response("converse", response(stopReason=stop))
        with pytest.raises(BedrockProviderError, match=code):
            await BedrockProvider(settings(), client=client).generate(request())


@pytest.mark.parametrize("bad_response", [
    {},
    response(usage={"inputTokens": True, "outputTokens": 8, "totalTokens": 9}),
    response(output={"message": {"role": "assistant", "content": [{"toolUse": {}}]}}),
    response(output={"message": {"role": "assistant", "content": [{"text": 42}]}}),
])
@pytest.mark.asyncio
async def test_malformed_provider_responses_fail_with_safe_code(bad_response):
    class MalformedClient:
        def converse(self, **kwargs):
            return bad_response

    with pytest.raises(BedrockProviderError, match="BEDROCK_RESPONSE_INVALID"):
        await BedrockProvider(settings(), client=MalformedClient()).generate(request())


@pytest.mark.asyncio
async def test_text_output_preserves_text_and_effective_pinned_budget():
    client = stub_client()
    with Stubber(client) as stub:
        stub.add_response("converse", response(), {
            "modelId": "amazon.nova-pro-v1:0",
            "messages": [{"role": "user", "content": [{"text": "private input"}]}],
            "inferenceConfig": {"maxTokens": 40, "temperature": 0.2},
        })
        result = await BedrockProvider(settings(), client=client).generate(
            request(system_prompt="", response_format="text", max_tokens=40)
        )
        assert result.content == '{"ok": true}'
        assert result.raw_response["inference_config"]["maxTokens"] == 40


@pytest.mark.asyncio
async def test_converse_uses_request_temperature_within_provider_ceiling():
    client = stub_client()
    with Stubber(client) as stub:
        stub.add_response("converse", response(), {
            "modelId": "amazon.nova-pro-v1:0",
            "messages": [{"role": "user", "content": [{"text": "private input"}]}],
            "system": [{
                "text": "system\nReturn a single valid JSON object without markdown fences."
            }],
            "inferenceConfig": {"maxTokens": 5000, "temperature": 0.8},
        })
        result = await BedrockProvider(
            settings(bedrock_temperature=0.3), client=client
        ).generate(request(temperature=0.8))
        assert result.raw_response["inference_config"]["temperature"] == 0.8


@pytest.mark.parametrize("temperature", [-0.01, 1.01, float("nan")])
@pytest.mark.asyncio
async def test_invalid_request_temperature_is_rejected(temperature):
    with pytest.raises(BedrockProviderError, match="BEDROCK_REQUEST_INVALID"):
        await BedrockProvider(settings(), client=object()).generate(
            request(temperature=temperature)
        )
