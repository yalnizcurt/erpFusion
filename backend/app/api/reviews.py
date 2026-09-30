"""
erpFusion — Review API Routes

Human review endpoints: approve, request changes, and reject artifact versions.
These are the review gates described in the problem statement (Gates 1–6).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Artifact, ArtifactVersion, FeedbackGuidance
from app.schemas import ArtifactVersionResponse, ReviewRequest
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
    version = await _get_version_or_404(artifact_id, version_number, db)
    workflow = WorkflowEngine(db)

    try:
        match body.decision.upper():
            case "APPROVED":
                await workflow.approve(
                    version=version,
                    reviewer=body.reviewer,
                    comments=body.comments,
                )
            case "REQUEST_CHANGES":
                if not body.comments:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Comments are required when requesting changes.",
                    )
                await workflow.request_changes(
                    version=version,
                    reviewer=body.reviewer,
                    comments=body.comments,
                )
                artifact = await db.get(Artifact, version.artifact_id)
                db.add(FeedbackGuidance(
                    project_id=artifact.project_id,
                    scope="PROJECT",
                    stage=artifact.artifact_type,
                    content=body.comments.strip(),
                    status="APPROVED",
                    version=1,
                    created_by=body.reviewer,
                ))
            case "REJECTED":
                await workflow.reject(
                    version=version,
                    reviewer=body.reviewer,
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
    artifact_id: str, version_number: int, db: AsyncSession
) -> ArtifactVersion:
    """Fetch a version or raise 404. Also validates the artifact exists."""
    # Verify artifact exists
    result = await db.execute(select(Artifact).where(Artifact.id == artifact_id))
    artifact = result.scalar_one_or_none()
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact {artifact_id} not found",
        )

    # Fetch version
    result = await db.execute(
        select(ArtifactVersion).where(
            ArtifactVersion.artifact_id == artifact_id,
            ArtifactVersion.version_number == version_number,
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version_number} of artifact {artifact_id} not found",
        )
    return version
