"""
erpFusion — Models Package

Re-exports all ORM models and the Base for Alembic discovery.
"""

from app.models.audit import AuditEntry
from app.models.artifact import Artifact
from app.models.base import (
    ArtifactType,
    AuditAction,
    Base,
    GateStatus,
    ProjectStatus,
    ValidationCategory,
    ValidationStatus,
    VersionState,
)
from app.models.project import Project
from app.models.erp_profile import ERPProfile, ERPProfileVersion, ERPStagePrompt
from app.models.erp_assets import (
    AdminAuditEvent, ERPAssetVersion, FeedbackGuidance, GenerationRun, PromptVersion,
)
from app.models.validation import ValidationResult
from app.models.version import ArtifactVersion

__all__ = [
    # Base
    "Base",
    # Models
    "Project",
    "ERPProfile",
    "ERPProfileVersion",
    "ERPStagePrompt",
    "PromptVersion",
    "ERPAssetVersion",
    "FeedbackGuidance",
    "GenerationRun",
    "AdminAuditEvent",
    "Artifact",
    "ArtifactVersion",
    "AuditEntry",
    "ValidationResult",
    # Enums
    "ProjectStatus",
    "ArtifactType",
    "GateStatus",
    "VersionState",
    "AuditAction",
    "ValidationCategory",
    "ValidationStatus",
]
