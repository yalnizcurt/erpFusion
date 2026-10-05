"""Verified identity with server-owned roles and client authorization assignments."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.models import Client, ClientMembership, IdentitySubject, PlatformRoleAssignment
from app.security.oidc import (
    IdentityProviderUnavailableError,
    InvalidIdentityTokenError,
    get_oidc_verifier,
)
from app.security.tenant_context import apply_tenant_context, assert_runtime_role


class IdentityConfigurationError(RuntimeError):
    """Raised when an identity provider cannot be safely configured."""


@dataclass(frozen=True, slots=True)
class Identity:
    """The small, provider-neutral identity used by API authorization."""

    user_id: str
    roles: frozenset[str] = frozenset()
    client_ids: frozenset[str] = frozenset()
    provider: str = "oidc"
    is_fixture: bool = False
    issuer: str = ""
    subject_id: str | None = None
    client_admin_ids: frozenset[str] = frozenset()
    fixture_allow_claimed_clients: bool = False
    fixture_allow_legacy_data: bool = False

    @property
    def is_platform_admin(self) -> bool:
        return "platform_admin" in self.roles

    @property
    def can_configure_erp(self) -> bool:
        return bool(
            self.roles
            & {
                "platform_admin",
                "erp_configurator",
                "platform_erp_configurator",
            }
        )

    @property
    def can_publish_erp(self) -> bool:
        return bool(self.roles & {"platform_admin", "erp_publisher", "platform_erp_publisher"})

    @property
    def can_access_unowned_legacy_data(self) -> bool:
        """Only explicitly enabled fixtures can inspect unmapped legacy rows."""
        return self.is_fixture and self.fixture_allow_legacy_data


def _safe_list(value: str | list[str] | None, *, lowercase: bool = True) -> frozenset[str]:
    if value is None:
        return frozenset()
    values = value if isinstance(value, list) else value.split(",")
    return frozenset(
        item.strip().lower() if lowercase else item.strip()
        for item in values
        if item and item.strip()
    )


def identity_for_direct_call() -> Identity:
    """Compatibility identity for direct Python service tests.

    FastAPI always resolves ``get_current_identity`` before a route executes.
    Existing unit tests call route functions directly, so they receive a
    clearly marked fixture rather than a ``Depends`` sentinel.
    """
    return Identity(
        user_id="development-fixture",
        roles=frozenset({"platform_admin"}),
        provider="direct-test",
        is_fixture=True,
        issuer="development",
        fixture_allow_claimed_clients=True,
        fixture_allow_legacy_data=True,
    )


async def _apply_context(db: AsyncSession, identity: Identity) -> None:
    await apply_tenant_context(
        db,
        client_ids=identity.client_ids,
        is_platform_admin=identity.is_platform_admin,
        is_erp_admin=identity.can_configure_erp or identity.can_publish_erp,
        allow_unowned_legacy=identity.can_access_unowned_legacy_data,
        subject_id=identity.subject_id,
        client_admin_ids=identity.client_admin_ids,
    )


async def _resolve_active_clients(db: AsyncSession, actor: Identity) -> Identity:
    """Read memberships before narrowing context to active client boundaries."""
    memberships = (
        (
            await db.execute(
                select(
                    ClientMembership.client_id,
                    ClientMembership.role,
                ).where(
                    ClientMembership.subject_id == actor.subject_id,
                    ClientMembership.status == "ACTIVE",
                )
            )
        ).all()
        if actor.subject_id
        else []
    )
    candidates = {membership.client_id for membership in memberships} | set(actor.client_ids)
    admins = {
        membership.client_id for membership in memberships if membership.role == "CLIENT_ADMIN"
    }
    actor = replace(actor, client_ids=frozenset(candidates), client_admin_ids=frozenset(admins))
    await _apply_context(db, actor)
    active = (
        (
            await db.execute(
                select(Client.id).where(
                    Client.id.in_(candidates),
                    Client.status == "ACTIVE",
                    Client.archived_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    actor = replace(
        actor,
        client_ids=frozenset(active),
        client_admin_ids=frozenset(admins & set(active)),
    )
    await _apply_context(db, actor)
    return actor


async def get_current_identity(
    authorization: Annotated[str | None, Header()] = None,
    x_dev_user_id: Annotated[str | None, Header()] = None,
    x_dev_roles: Annotated[str | None, Header()] = None,
    x_dev_client_ids: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> Identity:
    """Resolve a request identity without trusting caller-supplied review names.

    Development identities are explicit fixtures; deployed environments use
    signature-verified tokens and authoritative server authorization records.
    """
    if settings.auth_mode == "development":
        if settings.is_production:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OIDC identity provider configuration is required.",
            )
        user_id = (
            settings.dev_identity_user_id if x_dev_user_id is None else x_dev_user_id
        ).strip()
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated development identity required.",
            )
        fixture_subject_id = (
            await db.execute(
                select(IdentitySubject.id).where(
                    IdentitySubject.issuer == "development",
                    IdentitySubject.subject == user_id,
                    IdentitySubject.status == "ACTIVE",
                )
            )
        ).scalar_one_or_none()
        fixture = Identity(
            user_id=user_id,
            roles=_safe_list(settings.dev_identity_roles if x_dev_roles is None else x_dev_roles),
            client_ids=(
                _safe_list(
                    settings.dev_identity_client_ids
                    if x_dev_client_ids is None
                    else x_dev_client_ids,
                    lowercase=False,
                )
                if settings.dev_identity_allow_claimed_clients
                else frozenset()
            ),
            provider="development-fixture",
            is_fixture=True,
            issuer="development",
            subject_id=fixture_subject_id,
            fixture_allow_claimed_clients=settings.dev_identity_allow_claimed_clients,
            fixture_allow_legacy_data=settings.dev_identity_allow_legacy_data,
        )
        await _apply_context(db, fixture)
        fixture = await _resolve_active_clients(db, fixture)
        db.info["authenticated_identity"] = fixture
        return fixture

    if settings.auth_mode != "oidc" or settings.oidc_configuration_issues():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC identity provider configuration is incomplete.",
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = await get_oidc_verifier(settings).verify(authorization[7:].strip())
    except InvalidIdentityTokenError as exc:
        raise HTTPException(
            401,
            "Invalid or expired access token.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc
    except IdentityProviderUnavailableError as exc:
        raise HTTPException(503, "Identity provider is unavailable.") from exc
    if settings.is_production:
        try:
            await assert_runtime_role(db)
        except RuntimeError as exc:
            raise HTTPException(
                503, "Database authorization configuration is unavailable."
            ) from exc
    subject = (
        await db.execute(
            select(IdentitySubject.id).where(
                IdentitySubject.issuer == settings.oidc_issuer,
                IdentitySubject.subject == claims["sub"],
                IdentitySubject.status == "ACTIVE",
            )
        )
    ).scalar_one_or_none()
    if subject is None:
        raise HTTPException(403, "Identity is not active in this portal.")
    await apply_tenant_context(db, subject_id=subject, client_ids=())
    roles = (
        (
            await db.execute(
                select(PlatformRoleAssignment.role).where(
                    PlatformRoleAssignment.subject_id == subject,
                    PlatformRoleAssignment.status == "ACTIVE",
                )
            )
        )
        .scalars()
        .all()
    )
    actor = Identity(
        user_id=claims["sub"],
        issuer=settings.oidc_issuer,
        subject_id=subject,
        roles=_safe_list(list(roles)),
    )
    actor = await _resolve_active_clients(db, actor)
    db.info["authenticated_identity"] = actor
    return actor


async def require_authenticated_identity(
    identity: Identity = Depends(get_current_identity),
) -> Identity:
    """Named dependency for routes that require a verified identity."""
    return identity
