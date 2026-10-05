"""Typed request/response contracts for client onboarding and ownership."""

from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.base import (
    ClientRole,
    ClientStatus,
    EnvironmentStatus,
    EnvironmentType,
    IdentityStatus,
    InstallationStatus,
    MembershipStatus,
    PlatformRole,
)


def validate_public_configuration(value: dict[str, Any]) -> dict[str, Any]:
    """Installation metadata cannot serve as an unencrypted credential store."""
    sensitive = {
        "password",
        "secret",
        "token",
        "apikey",
        "accesskey",
        "privatekey",
        "credential",
        "authorization",
        "cookie",
    }

    def check(item: Any, depth: int = 0) -> None:
        if depth > 20:
            raise ValueError("Configuration nesting exceeds the supported limit")
        if isinstance(item, dict):
            for key, child in item.items():
                normalized = "".join(
                    character for character in str(key).lower() if character.isalnum()
                )
                reference = normalized.endswith(("reference", "ref"))
                if any(marker in normalized for marker in sensitive) and not reference:
                    raise ValueError("Use a credential reference instead of credential values")
                check(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                check(child, depth + 1)
        elif isinstance(item, str) and "://" in item:
            try:
                parsed = urlsplit(item)
                if parsed.username is not None or parsed.password is not None:
                    raise ValueError("Configuration URLs cannot contain credentials")
                if parsed.query or parsed.fragment:
                    raise ValueError("Configuration URLs cannot contain query strings or fragments")
            except ValueError as exc:
                raise ValueError("Configuration URLs must be safe public metadata") from exc

    check(value)
    return value


class IdentitySubjectResponse(BaseModel):
    """Safe identity projection; provider tokens and claims are never returned."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    issuer: str
    subject: str
    email: str | None = None
    display_name: str | None = None
    status: IdentityStatus
    last_authenticated_at: datetime | None = None


class IdentityCapabilities(BaseModel):
    manage_clients: bool
    configure_erp: bool
    publish_erp: bool


class ClientPermissions(BaseModel):
    manage_environment: bool = False
    create_request: bool = False
    review_functional: bool = False
    review_technical: bool = False
    test: bool = False


class IdentityClientResponse(BaseModel):
    id: str
    display_name: str
    roles: list[str]
    permissions: ClientPermissions


class CurrentIdentityResponse(BaseModel):
    """Read-only authorization capabilities; never returns provider token claims."""

    user_id: str
    provider: str
    is_fixture: bool
    platform_roles: list[str]
    capabilities: IdentityCapabilities
    clients: list[IdentityClientResponse]


class ClientCreate(BaseModel):
    """Create a client boundary from an authenticated platform action."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    client_key: str = Field(..., min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    display_name: str = Field(..., min_length=1, max_length=255)
    legal_name: str | None = Field(None, max_length=255)
    description: str | None = None


class ClientUpdate(BaseModel):
    """Mutable client administration fields; archival is an explicit command."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    display_name: str | None = Field(None, min_length=1, max_length=255)
    legal_name: str | None = Field(None, max_length=255)
    description: str | None = None


class ClientResponse(BaseModel):
    """Client projection for authorized queues and onboarding screens."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    client_key: str
    display_name: str
    legal_name: str | None = None
    description: str | None = None
    status: ClientStatus
    created_by_subject_id: str | None = None
    updated_by_subject_id: str | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ClientMembershipCreate(BaseModel):
    """Assign one client role to a stable authenticated subject."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subject_id: str = Field(..., min_length=1, max_length=255)
    role: ClientRole
    permissions: dict[str, Any] = Field(default_factory=dict)


class ClientMembershipResponse(BaseModel):
    """Client membership projection without identity-provider credentials."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    subject_id: str
    role: ClientRole
    status: MembershipStatus
    permissions: dict[str, Any]
    created_by_subject_id: str | None = None
    created_at: datetime
    updated_at: datetime


class PlatformRoleAssignmentCreate(BaseModel):
    """Assign a platform role separately from client-scoped membership."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subject_id: str = Field(..., min_length=1, max_length=255)
    role: PlatformRole


class ERPInstallationCreate(BaseModel):
    """Create a client installation for a published ERP profile."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    erp_profile_id: str = Field(..., min_length=1, max_length=36)
    installation_key: str = Field(
        ..., min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]*$"
    )
    display_name: str = Field(..., min_length=1, max_length=255)
    edition: str | None = Field(None, max_length=128)
    product_version: str | None = Field(None, max_length=128)
    external_tenant_reference: str | None = Field(None, max_length=255)
    configuration: dict[str, Any] = Field(default_factory=dict)

    @field_validator("configuration")
    @classmethod
    def secret_free_configuration(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_public_configuration(value)


class ERPInstallationResponse(BaseModel):
    """Installation projection; connection secrets are referenced indirectly."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    erp_profile_id: str
    installation_key: str
    display_name: str
    edition: str | None = None
    product_version: str | None = None
    external_tenant_reference: str | None = None
    status: InstallationStatus
    configuration: dict[str, Any]
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ERPEnvironmentCreate(BaseModel):
    """Create a named environment under one client installation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    environment_key: str = Field(
        ..., min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]*$"
    )
    display_name: str = Field(..., min_length=1, max_length=255)
    environment_type: EnvironmentType = EnvironmentType.SANDBOX
    custody: Literal["UNVERIFIED", "ERPFUSION_MANAGED", "CUSTOMER"] = "UNVERIFIED"
    execution_mode: Literal["ASSISTED", "SIMULATED", "REMOTE"] = "ASSISTED"
    endpoint_url: str | None = Field(None, max_length=1024)
    configuration: dict[str, Any] = Field(default_factory=dict)

    @field_validator("configuration")
    @classmethod
    def secret_free_configuration(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_public_configuration(value)

    @field_validator("endpoint_url")
    @classmethod
    def safe_endpoint_url(cls, value: str | None) -> str | None:
        if not value:
            return None
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"https", "http"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or (parsed.port is not None and not 1 <= parsed.port <= 65535)
            ):
                raise ValueError(
                    "Endpoint must be an HTTP(S) URL without credentials or query values"
                )
        except ValueError as exc:
            raise ValueError(
                "Endpoint must be an HTTP(S) URL without credentials or query values"
            ) from exc
        return value


class ERPEnvironmentResponse(BaseModel):
    """Environment projection with no credential material."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    installation_id: str
    environment_key: str
    display_name: str
    environment_type: EnvironmentType
    custody: str
    execution_mode: str
    status: EnvironmentStatus
    endpoint_url: str | None = None
    configuration: dict[str, Any]
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
