"""Phase 1 identity and explicit client ownership model contracts."""

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import (
    Base,
    Client,
    ClientMembership,
    ERPEnvironment,
    ERPInstallation,
    ERPProfile,
    IdentitySubject,
    PlatformRoleAssignment,
    Project,
    ProjectStatus,
)
from app.schemas.identity import ClientCreate, ClientMembershipCreate, ERPEnvironmentCreate


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_client_membership_and_platform_role_are_separate(db_session: AsyncSession) -> None:
    subject = IdentitySubject(
        issuer="https://id.example.test",
        subject="subject-123",
        email="reviewer@example.test",
        display_name="Reviewer",
    )
    client = Client(client_key="client-a", display_name="Client A")
    db_session.add_all([subject, client])
    await db_session.flush()

    db_session.add(
        ClientMembership(
            client_id=client.id,
            subject_id=subject.id,
            role="FUNCTIONAL_REVIEWER",
            permissions={"review": True},
            created_by_subject_id=subject.id,
        )
    )
    db_session.add(
        PlatformRoleAssignment(
            subject_id=subject.id,
            role="ERP_CONFIGURATOR",
            created_by_subject_id=subject.id,
        )
    )
    await db_session.commit()

    membership = (
        await db_session.execute(
            select(ClientMembership).where(ClientMembership.client_id == client.id)
        )
    ).scalar_one()
    platform_role = (
        await db_session.execute(
            select(PlatformRoleAssignment).where(PlatformRoleAssignment.subject_id == subject.id)
        )
    ).scalar_one()
    assert membership.client_id == client.id
    assert membership.subject_id == subject.id
    assert platform_role.role == "ERP_CONFIGURATOR"
    assert membership.client is client
    assert membership.subject is subject


@pytest.mark.asyncio
async def test_environment_composite_ownership_cannot_cross_client(
    db_session: AsyncSession,
) -> None:
    profile = ERPProfile(
        key="demo-erp",
        name="Demo ERP",
        display_name="Demo ERP",
        vendor="Demo Vendor",
        active=True,
    )
    first = Client(client_key="client-a", display_name="Client A")
    second = Client(client_key="client-b", display_name="Client B")
    db_session.add_all([profile, first, second])
    await db_session.flush()
    installation = ERPInstallation(
        client_id=first.id,
        erp_profile_id=profile.id,
        installation_key="primary",
        display_name="Client A primary ERP",
    )
    db_session.add(installation)
    await db_session.flush()
    environment = ERPEnvironment(
        client_id=first.id,
        installation_id=installation.id,
        environment_key="sandbox",
        display_name="Client A sandbox",
        environment_type="SANDBOX",
    )
    db_session.add(environment)
    await db_session.commit()

    assert environment.client_id == first.id
    installation_row = await db_session.get(ERPInstallation, installation.id)
    assert installation_row is not None
    assert installation_row.client_id == first.id

    request = Project(
        name="Client A request",
        business_requirement="An explicitly owned request",
        erp_schema_context={},
        status=ProjectStatus.ACTIVE,
        client_id=first.id,
        erp_installation_id=installation.id,
        erp_environment_id=environment.id,
    )
    db_session.add(request)
    await db_session.commit()
    assert request.client_id == first.id
    assert request.erp_installation_id == installation.id
    assert request.erp_environment_id == environment.id

    # The composite database constraint is intentionally exercised directly;
    # a mismatched client cannot point to this installation on PostgreSQL.
    invalid = ERPEnvironment(
        client_id=second.id,
        installation_id=installation.id,
        environment_key="cross-client",
        display_name="Invalid cross-client environment",
    )
    db_session.add(invalid)
    with pytest.raises(Exception):
        await db_session.commit()
    await db_session.rollback()


def test_onboarding_schemas_validate_stable_keys_and_roles() -> None:
    client = ClientCreate(client_key="client-a", display_name="Client A")
    membership = ClientMembershipCreate(subject_id="subject-123", role="TESTER")
    environment = ERPEnvironmentCreate(environment_key="sandbox", display_name="Sandbox")
    assert client.client_key == "client-a"
    assert membership.role.value == "TESTER"
    assert environment.environment_type.value == "SANDBOX"

    with pytest.raises(ValueError):
        ClientCreate(client_key="Client A", display_name="Client A")
