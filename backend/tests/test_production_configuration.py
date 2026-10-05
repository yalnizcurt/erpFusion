"""Fail-closed provider settings and operational logging privacy regressions."""

import logging

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.core.logging import OperationalLogFilter, configure_logging, redact_text
from app.database import create_database_engine
from app.services.llm.base import LLMProvider, LLMRequest, LLMResponse
from app.services.llm.factory import ProviderConfigurationError, get_llm_provider
from app.services.llm.groq import GroqProvider
from app.services.llm.mock import MockERPProvider


def settings(**overrides):
    defaults = {
        "app_env": "test",
        "database_url": "sqlite+aiosqlite:///:memory:",
        "llm_provider": "mock",
        "demo_mode": True,
        "groq_api_key": "",
    }
    return Settings(_env_file=None, **(defaults | overrides))


@pytest.mark.parametrize("app_env", ["development", "test", "staging", "production"])
def test_missing_live_key_never_silently_uses_mock(app_env):
    configured = settings(app_env=app_env, llm_provider="groq", groq_api_key="", demo_mode=False)
    assert "GROQ_API_KEY_MISSING" in configured.configuration_issues()
    code = "BEDROCK_PROVIDER_REQUIRED" if configured.is_production else "GROQ_API_KEY_MISSING"
    with pytest.raises(ProviderConfigurationError, match=code):
        get_llm_provider(configured)


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_mock_is_forbidden_in_deployed_environments(app_env):
    configured = settings(app_env=app_env)
    assert "MOCK_PROVIDER_FORBIDDEN" in configured.configuration_issues()
    with pytest.raises(ProviderConfigurationError, match="MOCK_PROVIDER_FORBIDDEN"):
        get_llm_provider(configured)


def test_mock_requires_explicit_demo_flag():
    with pytest.raises(ProviderConfigurationError, match="MOCK_PROVIDER_FORBIDDEN"):
        get_llm_provider(settings(demo_mode=False))
    assert isinstance(get_llm_provider(settings()), MockERPProvider)


@pytest.mark.parametrize(
    "provider,code",
    [
        ("unknown", "LLM_PROVIDER_UNSUPPORTED"),
    ],
)
def test_unimplemented_provider_fails_with_safe_code(provider, code):
    with pytest.raises(ProviderConfigurationError, match=code):
        get_llm_provider(settings(llm_provider=provider))


def test_production_configuration_requires_secure_origins_database_and_oidc():
    configured = settings(
        app_env="production",
        llm_provider="groq",
        demo_mode=False,
        groq_api_key="test-live-key",
        erp_admin_api_key="short",
    )
    assert {"POSTGRESQL_REQUIRED", "OIDC_CONFIGURATION_REQUIRED", "CORS_ORIGIN_INSECURE"}.issubset(
        configured.configuration_issues()
    )
    valid = settings(
        app_env="production",
        llm_provider="bedrock",
        demo_mode=False,
        bedrock_endpoint_url="https://vpce-012345abcdef.bedrock-runtime.us-east-1.vpce.amazonaws.com",
        bedrock_retention_approved=True,
        bedrock_residency_approved=True,
        bedrock_invocation_logging_disabled=True,
        erp_admin_api_key="a" * 40,
        database_url="postgresql://user:password@localhost/test_db",
        cors_origins=["https://portal.example.test"],
        auth_mode="oidc",
        oidc_issuer="https://identity.example.test",
        oidc_audience="erpfusion",
        oidc_jwks_url="https://identity.example.test/.well-known/jwks.json",
    )
    assert valid.configuration_issues() == ()


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "http://portal.example.test",
        "https://portal.example.test/path",
        "https://portal.example.test?token=secret",
        "https://user:secret@portal.example.test",
    ],
)
def test_production_cors_rejects_non_origins(origin):
    assert (
        "CORS_ORIGIN_INSECURE"
        in settings(app_env="production", cors_origins=[origin]).configuration_issues()
    )


def test_settings_representation_does_not_expose_secrets():
    configured = settings(
        groq_api_key="fixture-groq-secret",
        erp_admin_api_key="fixture-admin-secret",
        database_url="postgresql://user:fixture-db-secret@localhost/test_db",
    )
    assert "fixture-groq-secret" not in repr(configured)
    assert "fixture-admin-secret" not in repr(configured)
    assert "fixture-db-secret" not in repr(configured)


@pytest.mark.parametrize("field", ["app_env", "llm_provider", "log_level", "database_url"])
def test_invalid_setting_types_raise_safe_validation_error(field):
    with pytest.raises(ValidationError) as error:
        settings(**{field: 42})
    assert "input_value" not in str(error.value)


def test_json_cors_configuration_rejects_non_list_values():
    with pytest.raises(ValidationError):
        settings(cors_origins='{"origin": "https://portal.example.test"}')


def test_production_provider_rejects_demo_mode_even_with_live_key():
    with pytest.raises(ProviderConfigurationError, match="DEMO_MODE_FORBIDDEN"):
        get_llm_provider(
            settings(app_env="production", llm_provider="groq", groq_api_key="fixture-key")
        )


def test_provider_uses_injected_settings():
    provider = get_llm_provider(
        settings(llm_provider="groq", groq_api_key="fixture-key", groq_model="fixture-model")
    )
    assert isinstance(provider, GroqProvider)
    assert provider.model == "fixture-model"


@pytest.mark.asyncio
async def test_memory_sqlite_engine_is_constructed_without_unsupported_pool_options():
    engine = create_database_engine(settings())
    assert not engine.echo
    await engine.dispose()


def test_operational_log_filter_redacts_secrets_and_suppresses_exception_values():
    record = logging.LogRecord(
        "test",
        logging.ERROR,
        __file__,
        1,
        "Request failed Authorization=Bearer fixture-secret",
        (),
        None,
    )
    secret_error = ValueError("private customer requirements and fixture-secret")
    record.exc_info = (ValueError, secret_error, None)
    assert OperationalLogFilter(("fixture-secret",)).filter(record)
    assert "fixture-secret" not in record.getMessage()
    assert "private customer requirements" not in record.getMessage()
    assert "exception_type=ValueError" in record.getMessage()
    assert record.exc_info is None


def test_log_redaction_handles_credentials_and_customer_content():
    result = redact_text(
        "postgresql://user:db-secret@localhost/db password='password-secret' "
        "user_prompt=private customer requirements"
    )
    assert "db-secret" not in result
    assert "password-secret" not in result
    assert "private customer requirements" not in result


def test_log_redaction_handles_quoted_content_keys():
    assert "private fixture" not in redact_text('{"user_prompt": "private fixture"}')


def test_reconfiguring_logging_retains_previous_secret_redaction():
    configure_logging(settings(groq_api_key="earlier-fixture-secret"))
    configure_logging(settings(groq_api_key="later-fixture-secret"))
    for handler in logging.getLogger().handlers:
        filters = [item for item in handler.filters if isinstance(item, OperationalLogFilter)]
        assert len(filters) == 1
        record = logging.LogRecord(
            "test",
            logging.INFO,
            __file__,
            1,
            "earlier-fixture-secret later-fixture-secret",
            (),
            None,
        )
        filters[0].filter(record)
        assert "fixture-secret" not in record.getMessage()


def test_logging_configuration_covers_handlers_that_do_not_propagate():
    logger = logging.getLogger("fixture.non_propagating")
    handler = logging.NullHandler()
    logger.addHandler(handler)
    logger.propagate = False
    try:
        configure_logging(settings(groq_api_key="fixture-isolated-secret"))
        record = logging.LogRecord(
            logger.name, logging.INFO, __file__, 1, "fixture-isolated-secret", (), None
        )
        assert handler.filter(record)
        assert record.getMessage() == "[redacted]"
    finally:
        logger.removeHandler(handler)
        logger.propagate = True


class FixedOutputProvider(LLMProvider):
    def __init__(self, content: str):
        self.content = content

    async def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(content=self.content, model="test", usage={})


@pytest.mark.asyncio
async def test_json_parse_error_does_not_log_customer_content(caplog):
    caplog.set_level(logging.ERROR)
    provider = FixedOutputProvider('{"customer": "CONFIDENTIAL_FIXTURE_MARKER"')
    with pytest.raises(ValueError, match="LLM_OUTPUT_INVALID_JSON") as error:
        await provider.generate_json(LLMRequest(system_prompt="test", user_prompt="test"))
    assert "CONFIDENTIAL_FIXTURE_MARKER" not in caplog.text
    assert "CONFIDENTIAL_FIXTURE_MARKER" not in str(error.value)


@pytest.mark.asyncio
async def test_non_object_json_is_rejected():
    with pytest.raises(ValueError, match="LLM_OUTPUT_INVALID_STRUCTURE"):
        await FixedOutputProvider("[]").generate_json(
            LLMRequest(system_prompt="test", user_prompt="test")
        )


@pytest.mark.asyncio
async def test_provider_error_body_is_not_logged(monkeypatch, caplog):
    def respond(request):
        return httpx.Response(401, json={"error": {"message": "CONFIDENTIAL_PROVIDER_FIXTURE"}})

    transport = httpx.MockTransport(respond)
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.services.llm.groq.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    with pytest.raises(RuntimeError, match="HTTP 401"):
        await GroqProvider(settings(llm_provider="groq", groq_api_key="test-key")).generate(
            LLMRequest(system_prompt="test", user_prompt="test")
        )
    assert "CONFIDENTIAL_PROVIDER_FIXTURE" not in caplog.text
