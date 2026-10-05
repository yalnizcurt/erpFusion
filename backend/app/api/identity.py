"""Read-only authenticated identity and available client capabilities."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Client, ClientMembership, IdentitySubject
from app.schemas.identity import (
    ClientPermissions,
    CurrentIdentityResponse,
    IdentityCapabilities,
    IdentityClientResponse,
)
from app.security.identity import Identity, get_current_identity

router = APIRouter(prefix="/api/identity", tags=["Identity"])

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "CLIENT_ADMIN": frozenset(
        {
            "manage_environment",
            "create_request",
            "review_functional",
            "review_technical",
            "test",
        }
    ),
    "CONSULTANT": frozenset({"create_request"}),
    "FUNCTIONAL_REVIEWER": frozenset({"review_functional"}),
    "TECHNICAL_REVIEWER": frozenset({"review_technical"}),
    "TESTER": frozenset({"test"}),
}


def membership_permissions(memberships: list[ClientMembership]) -> ClientPermissions:
    """Combine active roles; metadata permissions do not grant runtime capabilities."""
    granted: set[str] = set()
    for membership in memberships:
        granted.update(ROLE_PERMISSIONS.get(membership.role.upper(), frozenset()))
    return ClientPermissions(**{name: name in granted for name in ClientPermissions.model_fields})


@router.get("/me", response_model=CurrentIdentityResponse)
async def current_identity(
    identity: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
) -> CurrentIdentityResponse:
    """Expose permissions without provisioning subjects or updating login metadata."""
    memberships = (
        (
            await db.execute(
                select(ClientMembership)
                .join(
                    IdentitySubject,
                    IdentitySubject.id == ClientMembership.subject_id,
                )
                .where(
                    IdentitySubject.issuer == identity.issuer,
                    IdentitySubject.subject == identity.user_id,
                    IdentitySubject.status == "ACTIVE",
                    ClientMembership.status == "ACTIVE",
                )
            )
        )
        .scalars()
        .all()
    )
    by_client: dict[str, list[ClientMembership]] = {}
    for membership in memberships:
        by_client.setdefault(membership.client_id, []).append(membership)
    query = select(Client).where(Client.status == "ACTIVE", Client.archived_at.is_(None))
    if not identity.is_platform_admin:
        query = query.where(Client.id.in_(by_client))
    clients = (await db.execute(query.order_by(Client.display_name))).scalars().all()
    return CurrentIdentityResponse(
        user_id=identity.user_id,
        provider=identity.provider,
        is_fixture=identity.is_fixture,
        platform_roles=sorted(identity.roles),
        capabilities=IdentityCapabilities(
            manage_clients=identity.is_platform_admin,
            configure_erp=identity.can_configure_erp,
            publish_erp=identity.can_publish_erp,
        ),
        clients=[
            IdentityClientResponse(
                id=client.id,
                display_name=client.display_name,
                roles=sorted({membership.role for membership in by_client.get(client.id, [])}),
                permissions=(
                    ClientPermissions(**{name: True for name in ClientPermissions.model_fields})
                    if identity.is_platform_admin
                    else membership_permissions(by_client.get(client.id, []))
                ),
            )
            for client in clients
        ],
    )
