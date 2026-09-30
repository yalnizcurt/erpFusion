"""
erpFusion Backend — Application Configuration

Loads settings from environment variables / .env file using Pydantic BaseSettings.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Database ──────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/erpfusion"

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_async_database_url(cls, value: str) -> str:
        """Render provides PostgreSQL URLs without an async SQLAlchemy driver name."""
        if isinstance(value, str):
            if value.startswith("postgres://"):
                return value.replace("postgres://", "postgresql+asyncpg://", 1)
            if value.startswith("postgresql://"):
                return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    # ── LLM Provider ─────────────────────────────────────────
    llm_provider: str = "groq"  # "groq" | "bedrock"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    # AWS Bedrock (production)
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            import json

            return json.loads(v)
        return v

    # ── Application ───────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"

    # ── Artifact Storage ──────────────────────────────────────
    artifact_storage_path: str = "./artifacts"
    erp_admin_api_key: str = ""

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
