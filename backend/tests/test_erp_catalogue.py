"""The explicit ERP catalogue importer creates only audited drafts."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.cli.erp_catalogue import import_catalogue, read_catalogue
from app.models import AdminAuditEvent, Base, ERPProfile, ERPProfileVersion


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_catalogue_recognizes_existing_legacy_keys_without_duplicate_profiles(db_session):
    catalogue = read_catalogue()
    family = next(item for item in catalogue.families if item.legacy_keys)
    existing = ERPProfile(
        key=family.legacy_keys[0], name="Existing governed ERP", vendor=family.vendor,
        configuration={"preserve": True},
    )
    db_session.add(existing)
    await db_session.flush()
    result = await import_catalogue(db_session, catalogue=catalogue, actor="operator")
    assert family.key in result["skipped_existing"]
    assert len(result["created"]) == 21
    assert await db_session.scalar(select(ERPProfile).where(ERPProfile.key == family.key)) is None
    assert existing.configuration == {"preserve": True}


@pytest.mark.asyncio
async def test_import_is_idempotent_audited_and_preserves_existing_oracle(
    db_session: AsyncSession,
) -> None:
    oracle = ERPProfile(
        key="oracle-fusion-cloud",
        name="Locally governed Oracle",
        display_name="Locally governed Oracle",
        vendor="Oracle",
        status="PUBLISHED",
        active=True,
        configuration={"local": "keep"},
        created_by="admin",
        updated_by="admin",
    )
    db_session.add(oracle)
    await db_session.flush()
    oracle_version = ERPProfileVersion(
        profile_id=oracle.id,
        version=7,
        status="PUBLISHED",
        supported_artifact_types=["LOCAL"],
        configuration={"local_version": "keep"},
        published_at=None,
        created_by="admin",
        updated_by="admin",
    )
    db_session.add(oracle_version)
    await db_session.flush()

    catalogue = read_catalogue()
    first = await import_catalogue(db_session, catalogue=catalogue, actor="operator")
    assert len(catalogue.families) == 22
    assert len({family.key for family in catalogue.families}) == 22
    assert len(first["created"]) == 21
    assert first["skipped_existing"] == ["oracle-fusion-cloud"]
    assert await db_session.scalar(select(func.count()).select_from(ERPProfile)) == 22
    assert await db_session.scalar(select(func.count()).select_from(ERPProfileVersion)) == 22

    created_profiles = (
        await db_session.scalars(select(ERPProfile).where(ERPProfile.id != oracle.id))
    ).all()
    assert all(profile.status == "DRAFT" for profile in created_profiles)
    assert all(profile.configuration["catalogue"]["capabilities"] for profile in created_profiles)
    oracle_after = await db_session.get(ERPProfile, oracle.id)
    version_after = await db_session.get(ERPProfileVersion, oracle_version.id)
    assert (
        oracle_after.key,
        oracle_after.name,
        oracle_after.status,
        oracle_after.configuration,
    ) == ("oracle-fusion-cloud", "Locally governed Oracle", "PUBLISHED", {"local": "keep"})
    assert (version_after.version, version_after.status, version_after.configuration) == (
        7,
        "PUBLISHED",
        {"local_version": "keep"},
    )

    fusion = next(family for family in catalogue.families if family.key == "oracle-fusion-cloud")
    assert fusion.configuration["execution_target"]["kind"] == "FUSION_PUBLISHER_REPORT_EXTRACTION"
    assert fusion.configuration["external_database_package_adapter"]["adapter"] == "oracle_plsql"
    assert (
        fusion.configuration["external_database_package_adapter"]["execution_target"]
        == "EXTERNAL_ORACLE_DATABASE"
    )

    before = (
        await db_session.scalar(select(func.count()).select_from(ERPProfile)),
        await db_session.scalar(select(func.count()).select_from(ERPProfileVersion)),
        await db_session.scalar(select(func.count()).select_from(AdminAuditEvent)),
    )
    second = await import_catalogue(db_session, catalogue=catalogue, actor="operator")
    after = (
        await db_session.scalar(select(func.count()).select_from(ERPProfile)),
        await db_session.scalar(select(func.count()).select_from(ERPProfileVersion)),
        await db_session.scalar(select(func.count()).select_from(AdminAuditEvent)),
    )
    assert second["created"] == []
    assert len(second["skipped_existing"]) == 22
    assert after == before
    events = (await db_session.scalars(select(AdminAuditEvent))).all()
    assert len(events) == 21
    assert all(event.action == "ERP_CATALOGUE_DRAFT_IMPORTED" for event in events)
    assert all(event.actor == "operator" for event in events)
    assert all(
        event.details["catalogue_checksum"] == first["catalogue_checksum"] for event in events
    )


@pytest.mark.asyncio
async def test_dry_run_does_not_write(db_session: AsyncSession) -> None:
    report = await import_catalogue(
        db_session, catalogue=read_catalogue(), actor="operator", dry_run=True
    )
    assert report["dry_run"] is True
    assert len(report["created"]) == 22
    assert report["skipped_existing"] == []
    assert await db_session.scalar(select(func.count()).select_from(ERPProfile)) == 0
    assert await db_session.scalar(select(func.count()).select_from(ERPProfileVersion)) == 0
    assert await db_session.scalar(select(func.count()).select_from(AdminAuditEvent)) == 0
