"""Authenticated platform role management after the explicit first-admin bootstrap."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.clients import _flush_unique, _platform_admin
from app.config import Settings, get_settings
from app.database import get_db
from app.models import IdentitySubject, PlatformRoleAssignment
from app.schemas.identity import PlatformRoleAssignmentCreate
from app.security.identity import Identity, get_current_identity
from app.services.ownership_audit import actor_subject, record_ownership_event

router = APIRouter(prefix="/api/identity/platform-roles", tags=["Identity Administration"])


@router.get("")
async def list_platform_roles(
    identity: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, str]]:
    _platform_admin(identity)
    rows = (
        (
            await db.execute(
                select(PlatformRoleAssignment)
                .order_by(PlatformRoleAssignment.created_at, PlatformRoleAssignment.id)
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    return [
        {"id": item.id, "subject_id": item.subject_id, "role": item.role, "status": item.status}
        for item in rows
    ]


@router.delete("/{assignment_id}", status_code=204)
async def revoke_platform_role(
    assignment_id: str,
    identity: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
) -> None:
    actor = _platform_admin(identity)
    # Lock the administrator set before checking its size; concurrent revocations
    # must not remove the last administrator.
    admins = (
        (
            await db.execute(
                select(PlatformRoleAssignment)
                .join(IdentitySubject, IdentitySubject.id == PlatformRoleAssignment.subject_id)
                .where(
                    PlatformRoleAssignment.role == "PLATFORM_ADMIN",
                    PlatformRoleAssignment.status == "ACTIVE",
                    IdentitySubject.status == "ACTIVE",
                    IdentitySubject.issuer == actor.issuer,
                )
                .order_by(PlatformRoleAssignment.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    assignment = await db.get(PlatformRoleAssignment, assignment_id)
    if assignment is None:
        raise HTTPException(404, "Platform role not found")
    if assignment in admins and len(admins) <= 1:
        raise HTTPException(409, "The last platform administrator cannot be revoked")
    assignment.status = "REVOKED"
    await record_ownership_event(
        db, actor, "PLATFORM_ROLE_REVOKED", "PlatformRoleAssignment", assignment.id
    )


@router.post("", status_code=201)
async def assign_platform_role(
    body: PlatformRoleAssignmentCreate,
    identity: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    actor = _platform_admin(identity)
    issuer = "development" if actor.is_fixture else settings.oidc_issuer
    subject = (
        await db.execute(
            select(IdentitySubject).where(
                IdentitySubject.issuer == issuer, IdentitySubject.subject == body.subject_id
            )
        )
    ).scalar_one_or_none()
    if subject is None:
        subject = IdentitySubject(issuer=issuer, subject=body.subject_id)
        db.add(subject)
        await _flush_unique(db, "Identity was provisioned concurrently; retry")
    if subject.status != "ACTIVE":
        raise HTTPException(409, "Cannot assign a suspended identity")
    assignment = (
        await db.execute(
            select(PlatformRoleAssignment).where(
                PlatformRoleAssignment.subject_id == subject.id,
                PlatformRoleAssignment.role == body.role.value,
            )
        )
    ).scalar_one_or_none()
    if assignment is None:
        assignment = PlatformRoleAssignment(
            subject_id=subject.id,
            role=body.role.value,
            created_by_subject_id=await actor_subject(db, actor),
        )
        db.add(assignment)
    assignment.status = "ACTIVE"
    await _flush_unique(db, "Role was assigned concurrently; retry")
    await record_ownership_event(
        db,
        actor,
        "PLATFORM_ROLE_ASSIGNED",
        "PlatformRoleAssignment",
        assignment.id,
        details={"subject_id": subject.id, "role": body.role.value},
    )
    return {
        "id": assignment.id,
        "subject_id": subject.id,
        "role": assignment.role,
        "status": assignment.status,
    }
