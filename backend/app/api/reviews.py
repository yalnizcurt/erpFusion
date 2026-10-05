"""
HighStudio — Review API Routes

Human review endpoints: approve, request changes, and reject artifact versions.
These are the review gates described in the problem statement (Gates 1–6).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import ensure_project_mutation
from app.database import get_db
from app.models import Artifact, ArtifactVersion, ERPProfileVersion, FeedbackGuidance
from app.schemas import ArtifactVersionResponse, ReviewRequest
from app.security.access import get_authorized_project, resolved_identity
from app.security.identity import Identity, get_current_identity
from app.services.ownership_audit import actor_subject
from app.services.project_revisions import lock_project
from app.services.workflow import WorkflowEngine, WorkflowError

router = APIRouter(prefix="/api/reviews", tags=["Reviews"])


@router.post(
    "/artifacts/{artifact_id}/versions/{version_number}/review",
    response_model=ArtifactVersionResponse,
    summary="Submit a human review decision",
)
async def submit_review(
    artifact_id: str,
    version_number: int,
    body: ReviewRequest,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> ArtifactVersionResponse:
    """
    Submit a human review decision for an artifact version.

    Allowed decisions:
    - APPROVED: Approve the artifact, unlocking downstream stages.
    - REQUEST_CHANGES: Request changes with mandatory comments.
    - REJECTED: Reject the artifact outright.

    This is the core human-in-the-loop gate. No downstream stage
    may proceed until this gate is explicitly passed.
    """
    version = await _get_version_or_404(artifact_id, version_number, db, identity)
    actor = resolved_identity(identity)
    artifact = await db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(404, "Artifact not found")
    project = await get_authorized_project(artifact.project_id, db, actor)
    await lock_project(db, project)
    await db.refresh(version)
    await db.refresh(artifact)
    profile = await db.get(ERPProfileVersion, project.erp_profile_version_id)
    stage = (
        WorkflowEngine.configured_stage_map(profile.configuration).get(artifact.artifact_type, {})
        if profile is not None
        else {}
    )
    review_role = WorkflowEngine.configured_review_role(artifact.artifact_type, stage)
    if review_role not in {"FUNCTIONAL_REVIEWER", "TECHNICAL_REVIEWER", "TESTER"}:
        raise HTTPException(409, "Configure a supported client review role for this stage")
    await ensure_project_mutation(db, actor, project, allowed_roles=["CLIENT_ADMIN", review_role])
    if actor.provider != "direct-test" and body.reviewer and body.reviewer.strip() != actor.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated identity must submit the review.",
        )
    reviewer_id = (
        body.reviewer.strip()
        if actor.provider == "direct-test" and body.reviewer
        else actor.user_id
    )
    version.reviewer_subject_id = await actor_subject(db, actor)
    workflow = WorkflowEngine(db, actor_subject_id=version.reviewer_subject_id)

    try:
        match body.decision.upper():
            case "APPROVED":
                await workflow.approve(
                    version=version,
                    reviewer=reviewer_id,
                    comments=body.comments,
                )
            case "REQUEST_CHANGES":
                if not body.comments or not body.comments.strip():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Comments are required when requesting changes.",
                    )
                await workflow.request_changes(
                    version=version,
                    reviewer=reviewer_id,
                    comments=body.comments,
                )
                db.add(
                    FeedbackGuidance(
                        project_id=artifact.project_id,
                        client_id=project.client_id,
                        scope="PROJECT",
                        stage=artifact.artifact_type,
                        content=body.comments.strip(),
                        status="APPROVED",
                        version=1,
                        created_by=reviewer_id,
                    )
                )
            case "REJECTED":
                await workflow.reject(
                    version=version,
                    reviewer=reviewer_id,
                    comments=body.comments,
                )
            case _:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Invalid decision: {body.decision}. "
                        f"Must be APPROVED, REQUEST_CHANGES, or REJECTED."
                    ),
                )
    except WorkflowError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    # Re-fetch to get updated state
    await db.refresh(version)
    return ArtifactVersionResponse.model_validate(version)


# ── Helpers ───────────────────────────────────────────────────


async def _get_version_or_404(
    artifact_id: str,
    version_number: int,
    db: AsyncSession,
    identity: object | None = None,
) -> ArtifactVersion:
    """Fetch a version or raise 404. Also validates the artifact exists."""
    # Verify artifact exists
    artifact_result = await db.execute(select(Artifact).where(Artifact.id == artifact_id))
    artifact = artifact_result.scalar_one_or_none()
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact {artifact_id} not found",
        )
    project = await get_authorized_project(artifact.project_id, db, identity)
    if artifact.client_id != project.client_id:
        raise HTTPException(404, "Artifact not found")

    # Fetch version
    version_result = await db.execute(
        select(ArtifactVersion).where(
            ArtifactVersion.artifact_id == artifact_id,
            ArtifactVersion.version_number == version_number,
        )
    )
    version = version_result.scalar_one_or_none()
    if version is None or version.client_id != artifact.client_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version_number} of artifact {artifact_id} not found",
        )
    return version
