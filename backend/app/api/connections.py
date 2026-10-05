"""Scoped connection onboarding and non-mutating Fusion permission probes."""

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.models import ERPEnvironment, ERPInstallation
from app.models.connection import ConnectionVerification, ERPConnection
from app.schemas.connections import (
    ConnectionConfigure,
    ConnectionCredentials,
    ConnectionResponse,
    VerificationResponse,
)
from app.security.access import ensure_client_access, resolved_identity
from app.security.identity import Identity, get_current_identity
from app.services.erp_connections import (
    ConnectionError,
    probe_connection,
    validate_destination,
    write_credentials,
)
from app.services.ownership_audit import actor_subject, record_ownership_event


class _RedactedValidationRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        handler = super().get_route_handler()

        async def redacted(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                # FastAPI's default validation response includes submitted input,
                # which could echo passwords or an accidentally credentialed URL.
                raise HTTPException(422, "Invalid connection input") from None

        return redacted


router = APIRouter(
    prefix="/api/clients/{client_id}/installations/{installation_id}"
    "/environments/{environment_id}/connection",
    tags=["ERP connections"],
    route_class=_RedactedValidationRoute,
)


async def authorized_environment(
    client_id: str,
    installation_id: str,
    environment_id: str,
    db: AsyncSession,
    identity: Identity,
    *,
    roles: list[str] | None = None,
    lock: bool = False,
) -> ERPEnvironment:
    try:
        await ensure_client_access(db, identity, client_id, allowed_roles=roles)
    except HTTPException as exc:
        if exc.status_code == 403 and not roles:
            raise HTTPException(404, "ERP environment not found") from None
        raise
    query = (
        select(ERPEnvironment)
        .join(ERPInstallation, ERPInstallation.id == ERPEnvironment.installation_id)
        .where(
            ERPEnvironment.id == environment_id,
            ERPEnvironment.client_id == client_id,
            ERPEnvironment.installation_id == installation_id,
            ERPEnvironment.status == "ACTIVE",
            ERPEnvironment.archived_at.is_(None),
            ERPInstallation.client_id == client_id,
            ERPInstallation.status == "ACTIVE",
            ERPInstallation.archived_at.is_(None),
        )
    )
    if lock:
        query = query.with_for_update()
    environment = (await db.execute(query)).scalar_one_or_none()
    if environment is None:
        raise HTTPException(404, "ERP environment not found")
    return environment


async def get_connection(
    db: AsyncSession,
    client_id: str,
    installation_id: str,
    environment_id: str,
) -> ERPConnection:
    connection = (
        await db.execute(
            select(ERPConnection).where(
                ERPConnection.client_id == client_id,
                ERPConnection.installation_id == installation_id,
                ERPConnection.environment_id == environment_id,
            )
        )
    ).scalar_one_or_none()
    if connection is None:
        raise HTTPException(404, "Connection not configured")
    return connection


def verification_response(
    verification: ConnectionVerification,
    connection: ERPConnection,
) -> VerificationResponse:
    expires = verification.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return VerificationResponse(
        id=verification.id,
        configuration_version=verification.configuration_version,
        **verification.checks,
        diagnostic_code=verification.diagnostic_code,
        checked_at=verification.checked_at,
        expires_at=verification.expires_at,
        latency_ms=verification.latency_ms,
        current=(
            verification.configuration_version == connection.configuration_version
            and verification.secret_version == connection.secret_version
            and expires > datetime.now(UTC)
        ),
    )


async def connection_response(db: AsyncSession, connection: ERPConnection) -> ConnectionResponse:
    verification = (
        await db.execute(
            select(ConnectionVerification)
            .where(
                ConnectionVerification.connection_id == connection.id,
                ConnectionVerification.client_id == connection.client_id,
            )
            .order_by(ConnectionVerification.checked_at.desc(), ConnectionVerification.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return ConnectionResponse(
        **{field: getattr(connection, field) for field in ConnectionConfigure.model_fields},
        id=connection.id,
        client_id=connection.client_id,
        installation_id=connection.installation_id,
        environment_id=connection.environment_id,
        configuration_version=connection.configuration_version,
        configured=bool(connection.secret_ref and connection.secret_version),
        last_verification=verification_response(verification, connection) if verification else None,
    )


@router.get("", response_model=ConnectionResponse)
async def read_connection(
    client_id: str,
    installation_id: str,
    environment_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> ConnectionResponse:
    await authorized_environment(
        client_id, installation_id, environment_id, db, resolved_identity(identity)
    )
    return await connection_response(
        db, await get_connection(db, client_id, installation_id, environment_id)
    )


@router.put("", response_model=ConnectionResponse)
async def configure_connection(
    client_id: str,
    installation_id: str,
    environment_id: str,
    body: ConnectionConfigure,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
) -> ConnectionResponse:
    actor = resolved_identity(identity)
    await authorized_environment(
        client_id, installation_id, environment_id, db, actor, roles=["CLIENT_ADMIN"], lock=True
    )
    try:
        if body.adapter == "oracle_fusion_publisher":
            validate_destination(body, settings)
    except ConnectionError as exc:
        raise HTTPException(422, str(exc)) from None
    connection = (
        await db.execute(
            select(ERPConnection).where(
                ERPConnection.environment_id == environment_id,
                ERPConnection.client_id == client_id,
                ERPConnection.installation_id == installation_id,
            )
        )
    ).scalar_one_or_none()
    if connection is None:
        connection = ERPConnection(
            client_id=client_id,
            installation_id=installation_id,
            environment_id=environment_id,
            **body.model_dump(),
        )
        db.add(connection)
    else:
        connection.configuration_version += 1
        for field, value in body.model_dump().items():
            setattr(connection, field, value)
        # Credentials were approved for the old configuration. Re-onboard before reuse.
        connection.secret_ref = connection.secret_version = None
    await db.flush()
    await record_ownership_event(
        db,
        actor,
        "CONNECTION_CONFIGURED",
        "ERPConnection",
        connection.id,
        client_id=client_id,
        details={"configuration_version": connection.configuration_version},
    )
    return await connection_response(db, connection)


@router.put("/credentials", response_model=ConnectionResponse)
async def replace_credentials(
    client_id: str,
    installation_id: str,
    environment_id: str,
    body: ConnectionCredentials,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
) -> ConnectionResponse:
    actor = resolved_identity(identity)
    await authorized_environment(
        client_id, installation_id, environment_id, db, actor, roles=["CLIENT_ADMIN"], lock=True
    )
    connection = await get_connection(db, client_id, installation_id, environment_id)
    if connection.adapter != "oracle_fusion_publisher":
        raise HTTPException(409, "connection_adapter_not_implemented")
    try:
        reference, version = await write_credentials(connection, body, settings)
    except ConnectionError as exc:
        raise HTTPException(503, str(exc)) from None
    connection.secret_ref, connection.secret_version = reference, version
    connection.configuration_version += 1
    await db.flush()
    await record_ownership_event(
        db,
        actor,
        "CONNECTION_CREDENTIALS_REPLACED",
        "ERPConnection",
        connection.id,
        client_id=client_id,
        details={"configuration_version": connection.configuration_version},
    )
    return await connection_response(db, connection)


@router.post("/ping", response_model=VerificationResponse)
async def ping_connection(
    client_id: str,
    installation_id: str,
    environment_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
) -> VerificationResponse:
    actor = resolved_identity(identity)
    await authorized_environment(
        client_id,
        installation_id,
        environment_id,
        db,
        actor,
        roles=["CLIENT_ADMIN", "TESTER"],
        lock=True,
    )
    connection = await get_connection(db, client_id, installation_id, environment_id)
    if connection.adapter != "oracle_fusion_publisher":
        raise HTTPException(409, "connection_adapter_not_implemented")
    subject_id = await actor_subject(db, actor) or actor.user_id
    since = datetime.now(UTC) - timedelta(minutes=1)
    rate_query = (
        select(func.count())
        .select_from(ConnectionVerification)
        .where(
            ConnectionVerification.connection_id == connection.id,
            ConnectionVerification.client_id == client_id,
            ConnectionVerification.checked_at >= since,
        )
    )
    total = (await db.execute(rate_query)).scalar_one()
    user_total = (
        await db.execute(rate_query.where(ConnectionVerification.actor_subject_id == subject_id))
    ).scalar_one()
    if total >= 20 or user_total >= 5:
        raise HTTPException(429, "connection_probe_rate_limited", headers={"Retry-After": "60"})
    started, checked_at = time.monotonic(), datetime.now(UTC)
    checks, code = await probe_connection(connection, settings)
    verification = ConnectionVerification(
        client_id=client_id,
        connection_id=connection.id,
        actor_subject_id=subject_id,
        configuration_version=connection.configuration_version,
        secret_version=connection.secret_version,
        checked_at=checked_at,
        expires_at=checked_at + timedelta(seconds=getattr(settings, "erp_probe_ttl_seconds", 300)),
        latency_ms=int((time.monotonic() - started) * 1000),
        checks=checks,
        diagnostic_code=code,
    )
    db.add(verification)
    await db.flush()
    await record_ownership_event(
        db,
        actor,
        "CONNECTION_CHECKED",
        "ConnectionVerification",
        verification.id,
        client_id=client_id,
        details={
            "connection_id": connection.id,
            "configuration_version": connection.configuration_version,
            "diagnostic_code": code,
        },
    )
    return verification_response(verification, connection)
