"""Strict onboarding input and credential-free connection output contracts."""

import re
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.schemas.identity import validate_public_configuration

CheckState = Literal["VERIFIED", "FAILED", "NOT_VERIFIED", "BLOCKED", "UNSUPPORTED"]


class ConnectionConfigure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    adapter: Literal["oracle_fusion_publisher", "metadata_only"] = "oracle_fusion_publisher"
    source_url: str = Field(max_length=1024)
    expected_tenant: str = Field(default="", max_length=255)
    approved_hosts: list[str] = Field(default_factory=list, max_length=20)
    report_path: str = Field(default="", max_length=1024)
    vendor_configuration: dict = Field(default_factory=dict)
    permitted_operations: list[Literal["PING", "RUN_REPORT"]] = Field(default=["PING"])

    @model_validator(mode="after")
    def adapter_contract(self):
        validate_public_configuration(self.vendor_configuration)
        if self.adapter == "oracle_fusion_publisher" and (
            not self.expected_tenant or not self.report_path or not self.approved_hosts
        ):
            raise ValueError("Publisher tenant, report and approved hosts are required")
        if self.adapter == "metadata_only" and self.permitted_operations:
            raise ValueError("Metadata-only connections have no executable operations")
        return self

    @field_validator("source_url")
    @classmethod
    def https_origin(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or any(ord(char) < 33 for char in value)
        ):
            raise ValueError("An HTTPS origin using port 443 is required")
        host = parsed.hostname
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host):
            raise ValueError("A DNS hostname is required")
        return f"https://{host}"

    @field_validator("approved_hosts")
    @classmethod
    def exact_hosts(cls, hosts: list[str]) -> list[str]:
        if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", h) for h in hosts):
            raise ValueError("Use exact lowercase DNS hostnames")
        return sorted(set(hosts))

    @field_validator("report_path")
    @classmethod
    def custom_report(cls, value: str) -> str:
        if not value:
            return value
        if (
            not value.startswith("/Custom/")
            or not value.endswith(".xdo")
            or any(part in ("", ".", "..") for part in value.split("/")[1:])
            or any(ord(char) < 32 for char in value)
            or "%" in value
            or "\\" in value
        ):
            raise ValueError("An approved absolute /Custom/...xdo report path is required")
        return value


class ConnectionCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: SecretStr = Field(min_length=1, max_length=255)
    password: SecretStr = Field(min_length=1, max_length=4096)


class VerificationResponse(BaseModel):
    id: str
    configuration_version: int
    network: CheckState
    authentication: CheckState
    tenant: CheckState
    permissions: CheckState
    report_execution: CheckState
    import_capability: CheckState = "UNSUPPORTED"
    diagnostic_code: str
    checked_at: datetime
    expires_at: datetime
    latency_ms: int
    current: bool


class ConnectionResponse(ConnectionConfigure):
    id: str
    client_id: str
    installation_id: str
    environment_id: str
    configuration_version: int
    configured: bool
    last_verification: VerificationResponse | None = None
