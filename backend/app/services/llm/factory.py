"""
HighStudio — LLM Provider Factory

Returns the configured LLM provider based on the LLM_PROVIDER setting.
Mocks require explicit development/test configuration. Missing credentials fail closed.
"""

import logging

from app.config import Settings, get_settings, secret_is_configured
from app.services.llm.base import LLMProvider

logger = logging.getLogger("erpfusion.llm.factory")


class ProviderConfigurationError(ValueError):
    """A safe configuration failure that contains no credential values."""


def get_llm_provider(settings: Settings | None = None) -> LLMProvider:
    """Factory: return the configured LLM provider."""
    settings = settings or get_settings()

    if settings.is_production:
        if settings.llm_provider == "mock":
            raise ProviderConfigurationError("MOCK_PROVIDER_FORBIDDEN: mocks are development only.")
        if settings.demo_mode:
            raise ProviderConfigurationError("DEMO_MODE_FORBIDDEN: demo mode is development only.")
        if settings.llm_provider != "bedrock":
            raise ProviderConfigurationError(
                "BEDROCK_PROVIDER_REQUIRED: deployed environments require approved Bedrock."
            )

    match settings.llm_provider.lower():
        case "groq":
            if secret_is_configured(settings.groq_api_key):
                from app.services.llm.groq import GroqProvider

                logger.info("Using configured Groq provider")
                return GroqProvider(settings=settings)
            else:
                raise ProviderConfigurationError(
                    "GROQ_API_KEY_MISSING: configure a live provider "
                    "or explicit development demo mode."
                )

        case "bedrock":
            issues = settings.bedrock_configuration_issues()
            if issues:
                raise ProviderConfigurationError("; ".join(issues))
            from app.services.llm.bedrock import BedrockProvider

            return BedrockProvider(settings=settings)

        case "mock":
            if settings.is_production or not settings.demo_mode:
                raise ProviderConfigurationError(
                    "MOCK_PROVIDER_FORBIDDEN: mocks require explicit development/test demo mode."
                )
            from app.services.llm.mock import MockERPProvider

            return MockERPProvider()

        case _:
            raise ProviderConfigurationError(
                "LLM_PROVIDER_UNSUPPORTED: choose an installed provider."
            )
