"""Scoped reviewer feedback and explicit human promotion to reusable ERP guidance."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import require_erp_admin
from app.database import get_db
from app.models import AdminAuditEvent, FeedbackGuidance, Project

router = APIRouter(prefix="/api", tags=["Feedback Guidance"])


@router.get("/projects/{project_id}/feedback")
async def project_feedback(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FeedbackGuidance).where(FeedbackGuidance.project_id == project_id)
                              .order_by(FeedbackGuidance.created_at.desc()))
    return [_json(x) for x in result.scalars()]


@router.post("/projects/{project_id}/feedback/{feedback_id}/promote")
async def promote_feedback(
    project_id: str, feedback_id: str, body: dict,
    actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db),
):
    source = await db.get(FeedbackGuidance, feedback_id)
    project = await db.get(Project, project_id)
    if source is None or project is None or source.project_id != project_id:
        raise HTTPException(404, "Project feedback not found")
    if source.status != "APPROVED" or source.scope != "PROJECT":
        raise HTTPException(409, "Only active project guidance can be promoted")
    target_scope = str(body.get("scope", "ERP")).upper()
    if target_scope not in {"ERP", "GLOBAL"}:
        raise HTTPException(400, "Reusable feedback may be promoted to ERP or GLOBAL scope")
    profile_id = body.get("profile_id") if target_scope == "ERP" else None
    if target_scope == "ERP" and profile_id != project.erp_profile_id:
        raise HTTPException(400, "Feedback can only be promoted to the ERP profile pinned to this request")
    promoted = FeedbackGuidance(
        profile_id=profile_id, scope=target_scope, stage=source.stage, content=source.content,
        status="APPROVED", version=1, created_by=actor,
    )
    source.status = "PROMOTED"
    db.add(promoted)
    await db.flush()
    db.add(AdminAuditEvent(actor=actor, action="FEEDBACK_PROMOTED", entity_type="FeedbackGuidance",
                           entity_id=promoted.id, details={"source_feedback_id": source.id, "profile_id": profile_id,
                                                           "scope": target_scope}))
    await db.flush()
    return _json(promoted)


@router.post("/projects/{project_id}/feedback/{feedback_id}/ignore")
async def ignore_feedback(
    project_id: str, feedback_id: str,
    actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db),
):
    item = await db.get(FeedbackGuidance, feedback_id)
    if item is None or item.project_id != project_id:
        raise HTTPException(404, "Project feedback not found")
    item.status = "IGNORED"
    db.add(AdminAuditEvent(actor=actor, action="FEEDBACK_IGNORED", entity_type="FeedbackGuidance",
                           entity_id=item.id, details={"project_id": project_id}))
    await db.flush()
    return _json(item)


def _json(x: FeedbackGuidance):
    return {"id": x.id, "project_id": x.project_id, "profile_id": x.profile_id, "scope": x.scope,
            "stage": x.stage, "content": x.content, "status": x.status, "version": x.version,
            "created_by": x.created_by, "created_at": x.created_at}
