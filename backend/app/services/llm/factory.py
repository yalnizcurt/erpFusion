"""
erpFusion — LLM Provider Factory

Returns the configured LLM provider based on the LLM_PROVIDER setting.
If Groq is configured with a key, it returns GroqProvider.
If no key is configured yet, it gracefully falls back to MockERPProvider.
"""

import logging
from app.config import get_settings
from app.services.llm.base import LLMProvider

logger = logging.getLogger("erpfusion.llm.factory")


def get_llm_provider() -> LLMProvider:
    """Factory: return the configured LLM provider."""
    settings = get_settings()

    match settings.llm_provider.lower():
        case "groq":
            if settings.groq_api_key and settings.groq_api_key != "your_groq_api_key_here":
                from app.services.llm.groq import GroqProvider
                logger.info(f"Using live GroqProvider with model: {settings.groq_model}")
                return GroqProvider()
            else:
                logger.info("GROQ_API_KEY not configured. Falling back to MockERPProvider for demo mode.")
                from app.services.llm.mock import MockERPProvider
                return MockERPProvider()

        case "bedrock":
            raise NotImplementedError("Bedrock provider is planned for production deployment")

        case "mock":
            from app.services.llm.mock import MockERPProvider
            return MockERPProvider()

        case _:
            raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")
