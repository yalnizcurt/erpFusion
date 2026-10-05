"""Tenant and project ownership checks shared by API routes."""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Client, ClientMembership, IdentitySubject, Project
from app.security.identity import Identity, identity_for_direct_call


def resolved_identity(identity: object) -> Identity:
    """Convert direct-call ``Depends`` sentinels to the explicit test fixture."""
    return identity if isinstance(identity, Identity) else identity_for_direct_call()


async def identity_client_ids(db: AsyncSession, identity: Identity) -> set[str]:
    """Return only active memberships for this exact issuer and subject."""
    client_ids = (
        set(identity.client_ids)
        if identity.is_fixture and identity.fixture_allow_claimed_clients
        else set()
    )
    result = await db.execute(
        select(ClientMembership.client_id)
        .join(IdentitySubject, IdentitySubject.id == ClientMembership.subject_id)
        .join(Client, Client.id == ClientMembership.client_id)
        .where(
            IdentitySubject.subject == identity.user_id,
            IdentitySubject.issuer == identity.issuer,
            IdentitySubject.status == "ACTIVE",
            ClientMembership.status == "ACTIVE",
            Client.status == "ACTIVE",
            Client.archived_at.is_(None),
        )
    )
    client_ids.update(result.scalars().all())
    return client_ids


async def ensure_client_access(
    db: AsyncSession,
    identity: Identity,
    client_id: str,
    *,
    allowed_roles: Iterable[str] | None = None,
) -> None:
    """Require an active membership and optionally a client-scoped role."""
    roles = {str(getattr(role, "value", role)).upper() for role in (allowed_roles or ())}
    client = (
        await db.execute(
            select(Client).where(
                Client.id == client_id,
                Client.status == "ACTIVE",
                Client.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Client access denied")
    if identity.is_platform_admin:
        return
    result = await db.execute(
        select(ClientMembership)
        .join(IdentitySubject, IdentitySubject.id == ClientMembership.subject_id)
        .where(
            ClientMembership.client_id == client_id,
            IdentitySubject.subject == identity.user_id,
            IdentitySubject.issuer == identity.issuer,
            IdentitySubject.status == "ACTIVE",
            ClientMembership.status == "ACTIVE",
        )
    )
    memberships = result.scalars().all()
    fixture_access = (
        identity.is_fixture
        and identity.fixture_allow_claimed_clients
        and client_id in identity.client_ids
        and not roles
    )
    if not memberships and not fixture_access:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Client access denied")
    if roles and not any(membership.role.upper() in roles for membership in memberships):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Client role required")


async def get_authorized_project(
    project_id: str,
    db: AsyncSession,
    identity: object,
    *,
    allow_legacy_fixture: bool = True,
) -> Project:
    """Fetch a project only when its ownership is visible to the identity.

    A 404 is returned for another client and for quarantined unmapped legacy
    rows to avoid turning object IDs into a cross-client existence oracle.
    """
    actor = resolved_identity(identity)
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.client_id is None:
        if allow_legacy_fixture and actor.can_access_unowned_legacy_data:
            return project
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        await ensure_client_access(db, actor, project.client_id)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
            ) from exc
        raise
    return project
