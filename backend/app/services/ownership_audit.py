"""Authenticated actors and audit events for ownership administration commands."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdminAuditEvent, IdentitySubject
from app.security.identity import Identity


async def actor_subject(db: AsyncSession, actor: Identity) -> str | None:
    """Resolve the issuer/subject pair; provision explicit development fixtures on writes."""
    if actor.provider == "direct-test":
        return None
    issuer = getattr(actor, "issuer", "") or ("development" if actor.is_fixture else actor.provider)
    result = await db.execute(
        select(IdentitySubject).where(
            IdentitySubject.issuer == issuer, IdentitySubject.subject == actor.user_id
        )
    )
    subject = result.scalar_one_or_none()
    if subject is None and actor.is_fixture:
        subject = IdentitySubject(issuer=issuer, subject=actor.user_id)
        db.add(subject)
        await db.flush()
    return subject.id if subject is not None else None


async def record_ownership_event(
    db: AsyncSession,
    actor: Identity,
    action: str,
    entity_type: str,
    entity_id: str,
    *,
    client_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Record identifiers and changed field names, never credentials or request content."""
    db.add(
        AdminAuditEvent(
            actor=actor.user_id,
            actor_subject_id=await actor_subject(db, actor),
            client_id=client_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        )
    )
    await db.flush()
