"""
HighStudio — Models Package

Re-exports all ORM models and the Base for Alembic discovery.
"""

from app.models.artifact import Artifact
from app.models.audit import AuditEntry
from app.models.base import (
    ArtifactType,
    AuditAction,
    Base,
    ClientRole,
    ClientStatus,
    EnvironmentStatus,
    EnvironmentType,
    GateStatus,
    IdentityStatus,
    InstallationStatus,
    MembershipStatus,
    PlatformRole,
    ProjectStatus,
    ValidationCategory,
    ValidationStatus,
    VersionState,
)
from app.models.connection import ConnectionVerification, ERPConnection
from app.models.engineering import (
    PackageCandidate,
    PackageRelease,
    ProjectInputRevision,
    RequirementDocument,
    SandboxEvidence,
)
from app.models.erp_assets import (
    AdminAuditEvent,
    ERPAssetVersion,
    FeedbackGuidance,
    GenerationRun,
    PromptVersion,
)
from app.models.erp_profile import ERPProfile, ERPProfileVersion, ERPStagePrompt
from app.models.execution import CapabilityQualification, ExecutionAttempt, SimulatedArtifact
from app.models.identity import (
    Client,
    ClientMembership,
    ERPEnvironment,
    ERPInstallation,
    IdentitySubject,
    PlatformRoleAssignment,
)
from app.models.integration_pattern import (
    IntegrationPattern,
    IntegrationPatternVersion,
    PatternBaseline,
)
from app.models.project import Project
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
    "IdentitySubject",
    "Client",
    "ClientMembership",
    "PlatformRoleAssignment",
    "ERPInstallation",
    "ERPEnvironment",
    "Artifact",
    "ArtifactVersion",
    "AuditEntry",
    "ValidationResult",
    "ProjectInputRevision",
    "RequirementDocument",
    "PackageCandidate",
    "SandboxEvidence",
    "PackageRelease",
    "ERPConnection",
    "ConnectionVerification",
    "CapabilityQualification",
    "ExecutionAttempt",
    "SimulatedArtifact",
    "IntegrationPattern",
    "IntegrationPatternVersion",
    "PatternBaseline",
    # Enums
    "ProjectStatus",
    "ArtifactType",
    "GateStatus",
    "VersionState",
    "AuditAction",
    "ValidationCategory",
    "ValidationStatus",
    "IdentityStatus",
    "ClientStatus",
    "MembershipStatus",
    "ClientRole",
    "PlatformRole",
    "InstallationStatus",
    "EnvironmentType",
    "EnvironmentStatus",
]
