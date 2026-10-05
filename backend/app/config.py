"""
HighStudio Backend — Application Configuration

Loads settings from environment variables / .env file using Pydantic BaseSettings.
"""

import re
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, TypeAdapter, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        hide_input_in_errors=True,
    )

    # ── Database ──────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/erpfusion",
        repr=False,
    )
    database_ssl_ca_file: str = ""

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_async_database_url(cls, value: str) -> str:
        """Render provides PostgreSQL URLs without an async SQLAlchemy driver name."""
        if not isinstance(value, str):
            raise ValueError("DATABASE_URL must be a string")
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    # ── LLM Provider ─────────────────────────────────────────
    llm_provider: str = "groq"  # Local compatibility; deployed environments require Bedrock.
    groq_api_key: str = Field(default="", repr=False)
    groq_model: str = "openai/gpt-oss-120b"

    # AWS storage uses the SDK credential chain (the deployed IAM role).
    aws_region: str = "us-east-1"
    # Compatibility for existing local .env files; never passed to the SDK.
    aws_access_key_id: str = Field(default="", repr=False)
    aws_secret_access_key: str = Field(default="", repr=False)

    # Only reviewed direct regional models; inference profiles are not accepted.
    bedrock_model_id: str = "amazon.nova-pro-v1:0"
    bedrock_region: str = "us-east-1"
    bedrock_api: Literal["converse"] = "converse"
    bedrock_endpoint_url: str = ""
    # Deprecated compatibility setting; pinned ERP requests supply the temperature.
    bedrock_temperature: float = Field(default=0.2, ge=0.00001, le=1)
    bedrock_max_tokens: int = Field(default=5000, ge=1, le=5000)
    bedrock_max_input_bytes: int = Field(default=262144, ge=1, le=1048576)
    bedrock_timeout_seconds: float = Field(default=120, gt=0, le=300)
    bedrock_connect_timeout_seconds: float = Field(default=5, gt=0, le=15)
    bedrock_max_attempts: int = Field(default=2, ge=1, le=3)
    # Deployment attestations after account/model/API review, not an API ZDR switch.
    bedrock_retention_approved: bool = False
    bedrock_residency_approved: bool = False
    bedrock_invocation_logging_disabled: bool = False

    # Operation-scoped ERP connections use allowlisted hosts and secret references.
    erp_allowed_hosts: list[str] = Field(default_factory=list)
    erp_secret_prefix: str = ""
    erp_secret_kms_key_id: str = ""
    erp_connection_timeout_seconds: float = Field(default=10, gt=0, le=60)
    erp_probe_ttl_seconds: int = Field(default=300, ge=1, le=3600)
    erp_max_response_bytes: int = Field(default=8388608, ge=1, le=16777216)

    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        adapter = TypeAdapter(list[str])
        if isinstance(v, str):
            return adapter.validate_json(v)
        return adapter.validate_python(v)

    # ── Application ───────────────────────────────────────────
    app_env: Literal["development", "test", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    demo_mode: bool = False
    execution_simulator_enabled: bool = False

    # Identity is explicit in non-production environments and must be backed
    # by a verified OIDC adapter before staging/production can become ready.
    auth_mode: Literal["development", "oidc"] = "development"
    dev_identity_user_id: str = "development-fixture"
    dev_identity_roles: list[str] = ["platform_admin"]
    dev_identity_client_ids: list[str] = []
    dev_identity_allow_claimed_clients: bool = False
    dev_identity_allow_legacy_data: bool = False
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_audience_claim: Literal["aud", "client_id"] = "aud"
    oidc_token_use: Literal["", "access", "id"] = ""
    oidc_jwks_url: str = ""
    oidc_algorithms: list[str] = ["RS256", "ES256"]
    oidc_clock_skew_seconds: int = Field(default=30, ge=0, le=60)
    oidc_jwks_cache_seconds: int = Field(default=300, ge=30, le=3600)
    oidc_http_timeout_seconds: float = Field(default=5, gt=0, le=15)
    oidc_introspection_url: str = ""
    oidc_introspection_client_id: str = ""
    oidc_introspection_client_secret: str = Field(default="", repr=False)

    @field_validator("oidc_algorithms")
    @classmethod
    def require_asymmetric_algorithms(cls, value: list[str]) -> list[str]:
        allowed = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "EdDSA"}
        if not value or any(algorithm not in allowed for algorithm in value):
            raise ValueError("OIDC algorithms must be explicitly supported asymmetric algorithms")
        return list(dict.fromkeys(value))

    @field_validator("app_env", "llm_provider", "auth_mode", mode="before")
    @classmethod
    def normalize_lowercase(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Application environment and provider must be strings")
        return value.strip().lower()

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("LOG_LEVEL must be a string")
        return value.strip().upper()

    # ── Artifact Storage ──────────────────────────────────────
    artifact_storage_path: str = "./artifacts"
    requirement_scan_command: list[str] = []
    requirement_scan_timeout_seconds: float = Field(default=30, gt=0, le=60)
    artifact_storage_backend: Literal["local", "s3"] = "local"
    artifact_s3_bucket: str = ""
    erp_admin_api_key: str = Field(default="", repr=False)

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def is_production(self) -> bool:
        return self.app_env in {"staging", "production"}

    def configuration_issues(self) -> tuple[str, ...]:
        """Return safe readiness codes; never include credentials or configuration values."""
        issues: list[str] = []
        if self.demo_mode and self.is_production:
            issues.append("DEMO_MODE_FORBIDDEN")
        if self.execution_simulator_enabled and self.is_production:
            issues.append("EXECUTION_SIMULATOR_FORBIDDEN")
        if self.llm_provider == "mock":
            if not self.demo_mode or self.is_production:
                issues.append("MOCK_PROVIDER_FORBIDDEN")
        elif self.llm_provider == "groq":
            if not secret_is_configured(self.groq_api_key):
                issues.append("GROQ_API_KEY_MISSING")
            if not self.groq_model.strip():
                issues.append("GROQ_MODEL_MISSING")
        elif self.llm_provider == "bedrock":
            issues.extend(self.bedrock_configuration_issues())
        else:
            issues.append("LLM_PROVIDER_UNSUPPORTED")

        if self.artifact_storage_backend == "s3" and (
            not self.artifact_s3_bucket.strip() or not self.aws_region.strip()
        ):
            issues.append("S3_STORAGE_CONFIGURATION_REQUIRED")

        if self.is_production:
            if self.llm_provider != "bedrock":
                issues.append("BEDROCK_PROVIDER_REQUIRED")
            if self.auth_mode != "oidc" or self.oidc_configuration_issues():
                issues.append("OIDC_CONFIGURATION_REQUIRED")
            if not self.database_url.startswith("postgresql+asyncpg://"):
                issues.append("POSTGRESQL_REQUIRED")
            if not self.cors_origins or any(
                not _production_origin(origin) for origin in self.cors_origins
            ):
                issues.append("CORS_ORIGIN_INSECURE")
        return tuple(issues)

    def bedrock_configuration_issues(self) -> tuple[str, ...]:
        """Check the reviewed model, destination and deployment approvals without AWS calls."""
        issues: list[str] = []
        if self.bedrock_model_id != "amazon.nova-pro-v1:0":
            issues.append("BEDROCK_MODEL_UNSUPPORTED")
        # AWS regional availability reviewed 2026-10-02. Keep this list deliberate.
        if self.bedrock_region not in {
            "us-east-1", "eu-west-2", "ap-southeast-2", "ap-southeast-3", "me-central-1",
        }:
            issues.append("BEDROCK_REGION_UNSUPPORTED")
        if self.bedrock_endpoint_url and not _bedrock_endpoint(
            self.bedrock_endpoint_url, self.bedrock_region
        ):
            issues.append("BEDROCK_ENDPOINT_INVALID")
        if self.is_production:
            if not _bedrock_endpoint(
                self.bedrock_endpoint_url, self.bedrock_region, private=True
            ):
                issues.append("BEDROCK_PRIVATE_ENDPOINT_REQUIRED")
            if not self.bedrock_retention_approved:
                issues.append("BEDROCK_RETENTION_APPROVAL_REQUIRED")
            if not self.bedrock_residency_approved:
                issues.append("BEDROCK_RESIDENCY_APPROVAL_REQUIRED")
            if not self.bedrock_invocation_logging_disabled:
                issues.append("BEDROCK_INVOCATION_LOGGING_MUST_BE_DISABLED")
        return tuple(issues)

    def oidc_configuration_issues(self) -> tuple[str, ...]:
        """Validate pinned provider locations without contacting the provider."""
        issues: list[str] = []
        if not _https_provider_url(self.oidc_issuer) or not self.oidc_audience.strip():
            issues.append("OIDC_ISSUER_AUDIENCE_REQUIRED")
        if not _https_provider_url(self.oidc_jwks_url):
            issues.append("OIDC_JWKS_REQUIRED")
        if any(
            (
                self.oidc_introspection_url,
                self.oidc_introspection_client_id,
                self.oidc_introspection_client_secret,
            )
        ) and (
            not _https_provider_url(self.oidc_introspection_url)
            or not self.oidc_introspection_client_id.strip()
            or not secret_is_configured(self.oidc_introspection_client_secret)
        ):
            issues.append("OIDC_INTROSPECTION_INCOMPLETE")
        return tuple(issues)


def _bedrock_endpoint(value: str, region: str, *, private: bool = False) -> bool:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname or ""
        private_host = bool(re.fullmatch(
            rf"vpce-[0-9a-f]+(?:-[a-z0-9-]+)?\.bedrock-runtime\.{re.escape(region)}"
            r"\.vpce\.amazonaws\.com", hostname,
        ))
        approved_host = private_host or (
            not private and hostname == f"bedrock-runtime.{region}.amazonaws.com"
        )
        return (
            parsed.scheme == "https" and approved_host and parsed.port in {None, 443}
            and parsed.username is None and parsed.password is None
            and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment
        )
    except ValueError:
        return False


def _https_provider_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
            and (parsed.port is None or 1 <= parsed.port <= 65535)
        )
    except ValueError:
        return False


def secret_is_configured(value: str) -> bool:
    """Reject empty/sample secrets without imposing vendor-specific token formats."""
    normalized = value.strip().lower()
    return bool(normalized) and not normalized.startswith(
        ("your_", "replace_", "changeme", "change_me", "gsk_your_", "example_")
    )


def _production_origin(origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
        # Accessing port also validates its syntax and range.
        port = parsed.port
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and "*" not in origin
            and parsed.path == ""
            and not parsed.query
            and not parsed.fragment
            and (port is None or 1 <= port <= 65535)
        )
    except ValueError:
        return False


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
