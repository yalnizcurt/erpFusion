"""Typed, authorized client and ERP environment onboarding commands."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.models import (
    Client,
    ClientMembership,
    ERPEnvironment,
    ERPInstallation,
    ERPProfile,
    ERPProfileVersion,
    IdentitySubject,
)
from app.schemas.identity import (
    ClientCreate,
    ClientMembershipCreate,
    ClientMembershipResponse,
    ClientResponse,
    ClientUpdate,
    ERPEnvironmentCreate,
    ERPEnvironmentResponse,
    ERPInstallationCreate,
    ERPInstallationResponse,
)
from app.security.access import ensure_client_access, identity_client_ids, resolved_identity
from app.security.identity import Identity, get_current_identity
from app.services.ownership_audit import actor_subject, record_ownership_event

router = APIRouter(prefix="/api/clients", tags=["Clients"])


def _platform_admin(identity: object) -> Identity:
    actor = resolved_identity(identity)
    if not actor.is_platform_admin:
        raise HTTPException(403, "Platform administrator role required")
    return actor


async def _flush_unique(db: AsyncSession, message: str) -> None:
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, message) from exc


@router.get("", response_model=list[ClientResponse])
async def list_clients(
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    search: Annotated[str | None, Query(max_length=255)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ClientResponse]:
    actor = resolved_identity(identity)
    query = select(Client).where(Client.status == "ACTIVE", Client.archived_at.is_(None))
    if not actor.is_platform_admin:
        query = query.where(Client.id.in_(await identity_client_ids(db, actor)))
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Client.display_name.ilike(f"%{escaped}%", escape="\\"))
    result = await db.execute(
        query.order_by(Client.display_name, Client.id).limit(limit).offset(offset)
    )
    return [ClientResponse.model_validate(item) for item in result.scalars()]


@router.post("", response_model=ClientResponse, status_code=201)
async def create_client(
    body: ClientCreate,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> ClientResponse:
    actor = _platform_admin(identity)
    subject_id = await actor_subject(db, actor)
    client = Client(
        **body.model_dump(), created_by_subject_id=subject_id, updated_by_subject_id=subject_id
    )
    db.add(client)
    await _flush_unique(db, "Client key already exists")
    await record_ownership_event(
        db, actor, "CLIENT_CREATED", "Client", client.id, client_id=client.id
    )
    return ClientResponse.model_validate(client)


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> ClientResponse:
    return ClientResponse.model_validate(await _accessible_client(client_id, db, identity))


@router.patch("/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: str,
    body: ClientUpdate,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> ClientResponse:
    actor = resolved_identity(identity)
    client = await _accessible_client(client_id, db, actor, manage=True)
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if field == "display_name" and value is None:
            raise HTTPException(422, "Display name cannot be empty")
        setattr(client, field, value)
    client.updated_by_subject_id = await actor_subject(db, actor)
    await record_ownership_event(
        db,
        actor,
        "CLIENT_UPDATED",
        "Client",
        client.id,
        client_id=client.id,
        details={"fields": sorted(changes)},
    )
    return ClientResponse.model_validate(client)


@router.delete("/{client_id}", status_code=204)
async def archive_client(
    client_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> None:
    actor = _platform_admin(identity)
    client = await _accessible_client(client_id, db, actor)
    client.status = "ARCHIVED"
    client.archived_at = datetime.now(UTC)
    client.updated_by_subject_id = await actor_subject(db, actor)
    await record_ownership_event(
        db, actor, "CLIENT_ARCHIVED", "Client", client.id, client_id=client.id
    )


@router.get("/{client_id}/memberships", response_model=list[ClientMembershipResponse])
async def list_memberships(
    client_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> list[ClientMembershipResponse]:
    await _accessible_client(client_id, db, identity, manage=True)
    result = await db.execute(
        select(ClientMembership).where(ClientMembership.client_id == client_id)
    )
    return [ClientMembershipResponse.model_validate(item) for item in result.scalars()]


@router.post("/{client_id}/memberships", response_model=ClientMembershipResponse, status_code=201)
async def add_membership(
    client_id: str,
    body: ClientMembershipCreate,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
) -> ClientMembershipResponse:
    actor = resolved_identity(identity)
    await _accessible_client(client_id, db, actor, manage=True)
    issuer = "development" if actor.is_fixture else settings.oidc_issuer
    result = await db.execute(
        select(IdentitySubject).where(
            IdentitySubject.issuer == issuer, IdentitySubject.subject == body.subject_id
        )
    )
    subject = result.scalar_one_or_none()
    if subject is None:
        subject = IdentitySubject(issuer=issuer, subject=body.subject_id)
        db.add(subject)
        await _flush_unique(db, "Identity was provisioned concurrently; retry")
    if subject.status != "ACTIVE":
        raise HTTPException(409, "Cannot assign a suspended identity")
    existing = await db.execute(
        select(ClientMembership).where(
            ClientMembership.client_id == client_id,
            ClientMembership.subject_id == subject.id,
            ClientMembership.role == body.role.value,
        )
    )
    membership = existing.scalar_one_or_none()
    if membership is None:
        membership = ClientMembership(
            client_id=client_id,
            subject_id=subject.id,
            role=body.role.value,
            created_by_subject_id=await actor_subject(db, actor),
        )
        db.add(membership)
    membership.status = "ACTIVE"
    membership.permissions = body.permissions
    await _flush_unique(db, "Membership was assigned concurrently; retry")
    await record_ownership_event(
        db,
        actor,
        "MEMBERSHIP_ASSIGNED",
        "ClientMembership",
        membership.id,
        client_id=client_id,
        details={"subject_id": subject.id, "role": body.role.value},
    )
    return ClientMembershipResponse.model_validate(membership)


@router.delete("/{client_id}/memberships/{membership_id}", status_code=204)
async def revoke_membership(
    client_id: str,
    membership_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> None:
    actor = resolved_identity(identity)
    await _accessible_client(client_id, db, actor, manage=True)
    membership = await db.get(ClientMembership, membership_id)
    if membership is None or membership.client_id != client_id:
        raise HTTPException(404, "Membership not found")
    membership.status = "REVOKED"
    await record_ownership_event(
        db, actor, "MEMBERSHIP_REVOKED", "ClientMembership", membership.id, client_id=client_id
    )


@router.get("/{client_id}/installations", response_model=list[ERPInstallationResponse])
async def list_installations(
    client_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> list[ERPInstallationResponse]:
    await _accessible_client(client_id, db, identity)
    result = await db.execute(
        select(ERPInstallation)
        .where(
            ERPInstallation.client_id == client_id,
            ERPInstallation.archived_at.is_(None),
            ERPInstallation.status == "ACTIVE",
        )
        .order_by(ERPInstallation.display_name, ERPInstallation.id)
    )
    return [ERPInstallationResponse.model_validate(item) for item in result.scalars()]


@router.post("/{client_id}/installations", response_model=ERPInstallationResponse, status_code=201)
async def create_installation(
    client_id: str,
    body: ERPInstallationCreate,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> ERPInstallationResponse:
    actor = resolved_identity(identity)
    await _accessible_client(client_id, db, actor, manage=True)
    published = await db.execute(
        select(ERPProfileVersion.id)
        .join(ERPProfile)
        .where(
            ERPProfile.id == body.erp_profile_id,
            ERPProfile.active.is_(True),
            ERPProfileVersion.status == "PUBLISHED",
        )
        .limit(1)
    )
    if published.scalar_one_or_none() is None:
        raise HTTPException(409, "Select an ERP profile with a published version")
    subject_id = await actor_subject(db, actor)
    installation = ERPInstallation(
        client_id=client_id,
        **body.model_dump(),
        created_by_subject_id=subject_id,
        updated_by_subject_id=subject_id,
    )
    db.add(installation)
    await _flush_unique(db, "Installation key already exists")
    await record_ownership_event(
        db,
        actor,
        "INSTALLATION_CREATED",
        "ERPInstallation",
        installation.id,
        client_id=client_id,
        details={"erp_profile_id": body.erp_profile_id},
    )
    return ERPInstallationResponse.model_validate(installation)


@router.get(
    "/{client_id}/installations/{installation_id}/environments",
    response_model=list[ERPEnvironmentResponse],
)
async def list_environments(
    client_id: str,
    installation_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> list[ERPEnvironmentResponse]:
    await _accessible_client(client_id, db, identity)
    await _get_installation(installation_id, client_id, db)
    result = await db.execute(
        select(ERPEnvironment)
        .where(
            ERPEnvironment.installation_id == installation_id,
            ERPEnvironment.client_id == client_id,
            ERPEnvironment.archived_at.is_(None),
            ERPEnvironment.status == "ACTIVE",
        )
        .order_by(ERPEnvironment.display_name, ERPEnvironment.id)
    )
    return [ERPEnvironmentResponse.model_validate(item) for item in result.scalars()]


@router.post(
    "/{client_id}/installations/{installation_id}/environments",
    response_model=ERPEnvironmentResponse,
    status_code=201,
)
async def create_environment(
    client_id: str,
    installation_id: str,
    body: ERPEnvironmentCreate,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
) -> ERPEnvironmentResponse:
    actor = resolved_identity(identity)
    await _accessible_client(client_id, db, actor, manage=True)
    await _get_installation(installation_id, client_id, db)
    subject_id = await actor_subject(db, actor)
    if body.custody == "ERPFUSION_MANAGED" and not actor.is_platform_admin:
        raise HTTPException(403, "managed_environment_requires_platform_admin")
    if body.execution_mode == "SIMULATED":
        if settings.is_production or not settings.execution_simulator_enabled:
            raise HTTPException(409, "execution_simulator_disabled")
    environment = ERPEnvironment(
        client_id=client_id,
        installation_id=installation_id,
        **body.model_dump(),
        created_by_subject_id=subject_id,
        updated_by_subject_id=subject_id,
    )
    db.add(environment)
    await _flush_unique(db, "Environment key already exists")
    await record_ownership_event(
        db,
        actor,
        "ENVIRONMENT_CREATED",
        "ERPEnvironment",
        environment.id,
        client_id=client_id,
        details={
            "installation_id": installation_id,
            "environment_type": body.environment_type.value,
        },
    )
    return ERPEnvironmentResponse.model_validate(environment)


async def _accessible_client(
    client_id: str, db: AsyncSession, identity: object, *, manage: bool = False
) -> Client:
    actor = resolved_identity(identity)
    try:
        await ensure_client_access(
            db, actor, client_id, allowed_roles=["CLIENT_ADMIN"] if manage else None
        )
    except HTTPException as exc:
        if exc.status_code == 403:
            raise HTTPException(404 if not manage else 403, "Client access denied") from exc
        raise
    client = await db.get(Client, client_id)
    if client is None or client.status != "ACTIVE" or client.archived_at is not None:
        raise HTTPException(404, "Client not found")
    return client


async def _get_installation(
    installation_id: str, client_id: str, db: AsyncSession
) -> ERPInstallation:
    installation = await db.get(ERPInstallation, installation_id)
    if (
        installation is None
        or installation.client_id != client_id
        or installation.archived_at is not None
        or installation.status != "ACTIVE"
    ):
        raise HTTPException(404, "ERP installation not found")
    return installation
