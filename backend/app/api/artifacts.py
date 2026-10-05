"""
HighStudio — Artifact API Routes

Endpoints for viewing artifacts, their version history, and validation results.
Also provides the workflow status endpoint.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Artifact, ArtifactVersion, AuditEntry, Project, ValidationResult
from app.schemas import (
    ArtifactResponse,
    ArtifactVersionResponse,
    AuditEntryResponse,
    ValidationResultResponse,
    WorkflowStatusResponse,
)
from app.security.access import get_authorized_project
from app.security.identity import Identity, get_current_identity
from app.services.workflow import WorkflowEngine

router = APIRouter(prefix="/api", tags=["Artifacts"])


# ══════════════════════════════════════════════════════════════
# Workflow Status
# ══════════════════════════════════════════════════════════════


@router.get(
    "/projects/{project_id}/workflow",
    response_model=WorkflowStatusResponse,
    summary="Get workflow status for a project",
)
async def get_workflow_status(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> WorkflowStatusResponse:
    """
    Returns the full workflow status showing each stage's gate status,
    current version, and which stage is currently active.
    """
    project = await _get_project_or_404(project_id, db, identity)
    workflow = WorkflowEngine(db)
    status_data = await workflow.get_workflow_status(project)
    return WorkflowStatusResponse(**status_data)


# ══════════════════════════════════════════════════════════════
# Artifacts
# ══════════════════════════════════════════════════════════════


@router.get(
    "/projects/{project_id}/artifacts",
    response_model=list[ArtifactResponse],
    summary="List all artifacts for a project",
)
async def list_artifacts(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> list[ArtifactResponse]:
    """List all artifacts for a project with their current gate status."""
    project = await _get_project_or_404(project_id, db, identity)

    result = await db.execute(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.client_id == project.client_id)
        .order_by(Artifact.created_at)
    )
    artifacts = list(result.scalars().all())
    return [ArtifactResponse.model_validate(a) for a in artifacts]


@router.get(
    "/artifacts/{artifact_id}",
    response_model=ArtifactResponse,
    summary="Get artifact details",
)
async def get_artifact(
    artifact_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> ArtifactResponse:
    """Get a single artifact by ID."""
    artifact = await _get_artifact_or_404(artifact_id, db, identity)
    return ArtifactResponse.model_validate(artifact)


# ══════════════════════════════════════════════════════════════
# Artifact Versions
# ══════════════════════════════════════════════════════════════


@router.get(
    "/artifacts/{artifact_id}/versions",
    response_model=list[ArtifactVersionResponse],
    summary="Get version history for an artifact",
)
async def list_versions(
    artifact_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> list[ArtifactVersionResponse]:
    """List all versions of an artifact, ordered by version number."""
    artifact = await _get_artifact_or_404(artifact_id, db, identity)

    result = await db.execute(
        select(ArtifactVersion)
        .where(
            ArtifactVersion.artifact_id == artifact_id,
            ArtifactVersion.client_id == artifact.client_id,
        )
        .order_by(ArtifactVersion.version_number.desc())
    )
    versions = list(result.scalars().all())
    return [ArtifactVersionResponse.model_validate(v) for v in versions]


@router.get(
    "/artifacts/{artifact_id}/versions/{version_number}",
    response_model=ArtifactVersionResponse,
    summary="Get a specific artifact version",
)
async def get_version(
    artifact_id: str,
    version_number: int,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> ArtifactVersionResponse:
    """Get a specific version of an artifact by version number."""
    version = await _get_version_or_404(artifact_id, version_number, db, identity)
    return ArtifactVersionResponse.model_validate(version)


# ══════════════════════════════════════════════════════════════
# Validation Results
# ══════════════════════════════════════════════════════════════


@router.get(
    "/artifacts/{artifact_id}/versions/{version_number}/validations",
    response_model=list[ValidationResultResponse],
    summary="Get validation results for an artifact version",
)
async def get_validations(
    artifact_id: str,
    version_number: int,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> list[ValidationResultResponse]:
    """Get all validation results for a specific artifact version."""
    version = await _get_version_or_404(artifact_id, version_number, db, identity)

    result = await db.execute(
        select(ValidationResult)
        .where(
            ValidationResult.artifact_version_id == version.id,
            ValidationResult.client_id == version.client_id,
        )
        .order_by(ValidationResult.validated_at)
    )
    validations = list(result.scalars().all())
    return [ValidationResultResponse.model_validate(v) for v in validations]


# ══════════════════════════════════════════════════════════════
# Audit Trail
# ══════════════════════════════════════════════════════════════


@router.get(
    "/artifacts/{artifact_id}/versions/{version_number}/audit",
    response_model=list[AuditEntryResponse],
    summary="Get audit trail for an artifact version",
)
async def get_audit_trail(
    artifact_id: str,
    version_number: int,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> list[AuditEntryResponse]:
    """Get the audit trail for a specific artifact version."""
    version = await _get_version_or_404(artifact_id, version_number, db, identity)

    result = await db.execute(
        select(AuditEntry)
        .join(Artifact, Artifact.id == version.artifact_id)
        .where(
            AuditEntry.artifact_version_id == version.id,
            AuditEntry.client_id == version.client_id,
            AuditEntry.project_id == Artifact.project_id,
        )
        .order_by(AuditEntry.timestamp)
    )
    entries = list(result.scalars().all())
    return [AuditEntryResponse.model_validate(e) for e in entries]


@router.get(
    "/projects/{project_id}/audit",
    response_model=list[AuditEntryResponse],
    summary="Get full audit trail for a project",
)
async def get_project_audit_trail(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> list[AuditEntryResponse]:
    """Get the complete audit trail for a project across all artifacts."""
    project = await _get_project_or_404(project_id, db, identity)

    result = await db.execute(
        select(AuditEntry)
        .join(ArtifactVersion, ArtifactVersion.id == AuditEntry.artifact_version_id)
        .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
        .where(
            AuditEntry.project_id == project_id,
            Artifact.project_id == project_id,
            AuditEntry.client_id == project.client_id,
            Artifact.client_id == project.client_id,
            ArtifactVersion.client_id == project.client_id,
        )
        .order_by(AuditEntry.timestamp)
    )
    entries = list(result.scalars().all())
    return [AuditEntryResponse.model_validate(e) for e in entries]


@router.get(
    "/artifacts/{artifact_id}/diff",
    summary="Get diff between two artifact versions",
)
async def get_version_diff(
    artifact_id: str,
    v1: int,
    v2: int,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
):
    """Compute line diff between two versions of an artifact."""
    import difflib
    import json

    ver1 = await _get_version_or_404(artifact_id, v1, db, identity)
    ver2 = await _get_version_or_404(artifact_id, v2, db, identity)

    str1 = json.dumps(ver1.content, indent=2).splitlines(keepends=True)
    str2 = json.dumps(ver2.content, indent=2).splitlines(keepends=True)

    diff = list(difflib.unified_diff(str1, str2, fromfile=f"v{v1}", tofile=f"v{v2}"))

    return {
        "artifact_id": artifact_id,
        "v1": v1,
        "v2": v2,
        "diff_text": "".join(diff),
        "changes_count": len(
            [
                line
                for line in diff
                if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
            ]
        ),
    }


# ── Helpers ───────────────────────────────────────────────────


async def _get_project_or_404(
    project_id: str, db: AsyncSession, identity: object | None = None
) -> Project:
    return await get_authorized_project(project_id, db, identity)


async def _get_artifact_or_404(
    artifact_id: str, db: AsyncSession, identity: object | None = None
) -> Artifact:
    result = await db.execute(select(Artifact).where(Artifact.id == artifact_id))
    artifact = result.scalar_one_or_none()
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact {artifact_id} not found",
        )
    project = await get_authorized_project(artifact.project_id, db, identity)
    if artifact.client_id != project.client_id:
        raise HTTPException(404, "Artifact not found")
    return artifact


async def _get_version_or_404(
    artifact_id: str,
    version_number: int,
    db: AsyncSession,
    identity: object | None = None,
) -> ArtifactVersion:
    artifact = await _get_artifact_or_404(artifact_id, db, identity)
    result = await db.execute(
        select(ArtifactVersion).where(
            ArtifactVersion.artifact_id == artifact_id,
            ArtifactVersion.version_number == version_number,
        )
    )
    version = result.scalar_one_or_none()
    if version is None or version.client_id != artifact.client_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version_number} of artifact {artifact_id} not found",
        )
    return version
