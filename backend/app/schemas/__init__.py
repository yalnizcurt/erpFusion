"""
HighStudio — Pydantic Schemas for API Request/Response

Defines all request bodies, response models, and shared types
used by the FastAPI route handlers.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_serializer, field_validator

from app.schemas.identity import (
    ClientCreate,
    ClientMembershipCreate,
    ClientMembershipResponse,
    ClientResponse,
    ClientUpdate,
    ERPEnvironmentCreate,
    ERPEnvironmentResponse,
    ERPInstallationCreate,
    ERPInstallationResponse,
    IdentitySubjectResponse,
    PlatformRoleAssignmentCreate,
)
from app.services.llm.base import safe_provider_receipt

__all__ = [
    "ClientCreate",
    "ClientMembershipCreate",
    "ClientMembershipResponse",
    "ClientResponse",
    "ClientUpdate",
    "ERPEnvironmentCreate",
    "ERPEnvironmentResponse",
    "ERPInstallationCreate",
    "ERPInstallationResponse",
    "IdentitySubjectResponse",
    "PlatformRoleAssignmentCreate",
]

# ══════════════════════════════════════════════════════════════
# Project Schemas
# ══════════════════════════════════════════════════════════════


class ProjectCreate(BaseModel):
    """Request body for creating a new project."""

    name: str = Field(..., min_length=1, max_length=255, examples=["Customer Extraction"])
    description: str | None = Field(
        None, examples=["Extract active customer records for the finance data hub"]
    )
    business_requirement: str = Field(
        "",
        max_length=500000,
        examples=["Extract active customer records including name, number, and sites..."],
    )
    erp_schema_context: dict = Field(
        default_factory=dict,
        examples=[
            {
                "entities": [
                    {
                        "table": "CUSTOMER_PARTIES",
                        "columns": [
                            {"name": "PARTY_ID", "type": "INTEGER", "pk": True},
                            {"name": "PARTY_NAME", "type": "STRING"},
                        ],
                    }
                ]
            }
        ],
    )
    fdd_template_path: str | None = Field(None, examples=["templates/fdd_template.docx"])
    tdd_template_path: str | None = Field(None, examples=["templates/tdd_template.docx"])
    erp_profile_id: str | None = None
    erp_profile_version_id: str | None = None
    integration_pattern_version_id: str | None = None
    client_id: str | None = None
    erp_installation_id: str | None = None
    erp_environment_id: str | None = None
    project_type: Literal["STANDARD", "CUSTOM"] = "CUSTOM"
    due_date: date | None = None


class ProjectUpdate(BaseModel):
    """Request body for updating a project."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    business_requirement: str | None = Field(None, max_length=500000)
    erp_schema_context: dict | None = None
    fdd_template_path: str | None = None
    tdd_template_path: str | None = None
    erp_profile_id: str | None = None
    erp_profile_version_id: str | None = None
    integration_pattern_version_id: str | None = None
    expected_integration_pattern_version_id: str | None = None
    client_id: str | None = None
    erp_installation_id: str | None = None
    erp_environment_id: str | None = None
    project_type: Literal["STANDARD", "CUSTOM"] | None = None
    due_date: date | None = None
    expected_requirement_version: int | None = None
    expected_schema_context_version: int | None = None
    expected_erp_profile_version_id: str | None = None

    @field_validator("name", "business_requirement", "erp_schema_context", "project_type")
    @classmethod
    def required_fields_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("This field cannot be null")
        return value


class ProjectResponse(BaseModel):
    """Response model for a project."""

    id: str
    name: str
    description: str | None
    business_requirement: str
    erp_schema_context: dict
    fdd_template_path: str | None
    tdd_template_path: str | None
    erp_profile_id: str | None = None
    erp_profile_version_id: str | None = None
    integration_pattern_version_id: str | None = None
    integration_pattern_name: str | None = None
    integration_pattern_version: int | None = None
    client_id: str | None = None
    erp_installation_id: str | None = None
    erp_environment_id: str | None = None
    created_by_subject_id: str | None = None
    project_type: str = "CUSTOM"
    due_date: date | None = None
    last_activity_at: datetime | None = None
    requirement_version: int = 1
    schema_context_version: int = 1
    workflow_revision: int = 0
    workflow_status: str = "DRAFT"
    client_name: str | None = None
    erp_name: str | None = None
    erp_version: int | None = None
    current_stage: str | None = None
    package_available: bool = False
    package_kind: Literal["candidate", "release"] | None = None
    package_download_url: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    """Response model for listing projects."""

    projects: list[ProjectResponse]
    total: int
    next_offset: int | None = None
    summary: dict[str, int] = Field(default_factory=dict)


class ERPProfileCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=255)
    vendor: str = Field(..., min_length=1, max_length=255)
    product_version: str | None = Field(None, max_length=128)
    description: str | None = None
    configuration: dict = Field(default_factory=dict)


class StagePromptCreate(BaseModel):
    stage: str = Field(..., min_length=1, max_length=80)
    system_prompt: str = Field(..., min_length=1)


# ══════════════════════════════════════════════════════════════
# Artifact Schemas
# ══════════════════════════════════════════════════════════════


class ArtifactResponse(BaseModel):
    """Response model for an artifact."""

    id: str
    project_id: str
    artifact_type: str
    current_version: int
    gate_status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ArtifactVersionResponse(BaseModel):
    """Response model for an artifact version."""

    id: str
    artifact_id: str
    version_number: int
    state: str
    content: dict
    file_path: str | None
    parent_version_id: str | None
    ai_model_version: str | None
    generation_run_id: str | None = None
    input_context_snapshot: dict | None = None
    generated_at: datetime
    reviewer: str | None
    reviewed_at: datetime | None
    review_comments: str | None

    model_config = {"from_attributes": True}

    @field_serializer("input_context_snapshot")
    def sanitize_provider_receipts(self, value):
        if not isinstance(value, dict) or "provider_receipts" not in value:
            return value
        snapshot = value.copy()
        receipts = value["provider_receipts"]
        snapshot["provider_receipts"] = (
            [safe_provider_receipt(receipt) for receipt in receipts]
            if isinstance(receipts, list)
            else []
        )
        return snapshot


# ══════════════════════════════════════════════════════════════
# Workflow / Stage Schemas
# ══════════════════════════════════════════════════════════════


class StageStatusResponse(BaseModel):
    """Status of a single workflow stage."""

    stage: str
    gate_status: str
    current_version: int
    artifact_id: str | None = None
    label: str | None = None
    can_generate: bool = False
    depends_on: list[str] = Field(default_factory=list)
    review_role: str = "TECHNICAL_REVIEWER"
    approval_blockers: list[str] = Field(default_factory=list)


class WorkflowStatusResponse(BaseModel):
    """Full workflow status for a project."""

    project_id: str
    project_name: str
    current_stage: str | None
    stages: list[StageStatusResponse]


class GenerateRequest(BaseModel):
    """Request body for triggering AI generation of a specific stage."""

    stage: str = Field(
        ...,
        examples=["CONTEXT_ANALYSIS"],
        description="Artifact type to generate",
    )
    execution_attempt_id: str | None = Field(default=None, max_length=36)


# ══════════════════════════════════════════════════════════════
# Review Schemas
# ══════════════════════════════════════════════════════════════


class ReviewRequest(BaseModel):
    """Request body for a human review action."""

    decision: str = Field(
        ...,
        examples=["APPROVED", "REQUEST_CHANGES", "REJECTED"],
        description="Review decision",
    )
    reviewer: str | None = Field(
        None,
        min_length=1,
        examples=["john.doe"],
        description="Identifier of the human reviewer",
    )
    comments: str | None = Field(
        None,
        examples=["Looks good, approved for next stage."],
        description="Optional reviewer comments",
    )


# ══════════════════════════════════════════════════════════════
# Validation Schemas
# ══════════════════════════════════════════════════════════════


class ValidationCheckResponse(BaseModel):
    """A single validation check result."""

    name: str
    status: str  # PASS | WARN | FAIL
    message: str
    details: dict | None = None


class ValidationResultResponse(BaseModel):
    """Response model for validation results."""

    id: str
    category: str
    status: str
    checks: list[dict]
    validated_at: datetime

    model_config = {"from_attributes": True}


# ══════════════════════════════════════════════════════════════
# Audit Schemas
# ══════════════════════════════════════════════════════════════


class AuditEntryResponse(BaseModel):
    """Response model for an audit trail entry."""

    id: str
    action: str
    actor: str
    comments: str | None
    metadata_: dict | None = Field(None, alias="metadata")
    timestamp: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}
