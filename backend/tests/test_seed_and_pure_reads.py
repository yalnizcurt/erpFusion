"""Phase 0 fixtures are explicit and status/list reads never change data."""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.projects import list_projects
from app.cli.__main__ import main, require_development
from app.config import Settings
from app.models import (
    AdminAuditEvent,
    Artifact,
    ArtifactVersion,
    AuditEntry,
    Base,
    ERPAssetVersion,
    ERPProfile,
    ERPProfileVersion,
    GateStatus,
    IntegrationPattern,
    IntegrationPatternVersion,
    PatternBaseline,
    Project,
    PromptVersion,
    VersionState,
)
from app.services.erp_registry import load_development_fixtures, read_fixture_manifest
from app.services.packages import sha256
from app.services.workflow import WorkflowEngine


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def counts(db: AsyncSession) -> dict[str, int]:
    result = {}
    for model in (
        ERPProfile,
        ERPProfileVersion,
        ERPAssetVersion,
        IntegrationPattern,
        IntegrationPatternVersion,
        PatternBaseline,
        PromptVersion,
        Project,
        Artifact,
        AdminAuditEvent,
        AuditEntry,
    ):
        result[model.__tablename__] = (
            await db.execute(select(func.count()).select_from(model))
        ).scalar_one()
    return result


@pytest.mark.asyncio
async def test_fixture_loading_is_explicit_idempotent_and_audited(db_session: AsyncSession) -> None:
    manifest = read_fixture_manifest()
    first = await load_development_fixtures(db_session, manifest=manifest, app_env="development")
    assert first.profiles_created == 5
    assert first.prompts_created == 6
    assert first.projects_created == 0
    before = await counts(db_session)
    second = await load_development_fixtures(db_session, manifest=manifest, app_env="development")
    assert second.profiles_created == 0
    assert second.prompts_created == 0
    assert second.projects_created == 0
    assert second.profiles_skipped == first.profiles_created
    assert await counts(db_session) == before
    events = (await db_session.execute(select(AdminAuditEvent))).scalars().all()
    assert events
    assert all(entry.details["manifest_checksum"] == first.manifest_checksum for entry in events)
    profiles = (await db_session.execute(select(ERPProfile))).scalars().all()
    assert {profile.key for profile in profiles if profile.status == "PUBLISHED"} == {
        "oracle-fusion-cloud"
    }


@pytest.mark.asyncio
async def test_sample_requests_are_opt_in_and_never_duplicated(db_session: AsyncSession) -> None:
    manifest = read_fixture_manifest()
    await load_development_fixtures(db_session, manifest=manifest, app_env="development")
    first = await load_development_fixtures(
        db_session,
        manifest=manifest,
        app_env="development",
        include_sample_projects=True,
    )
    assert first.projects_created == 1
    project = (await db_session.execute(select(Project))).scalar_one()
    assert len(project.artifacts) == 7
    schema = project.erp_schema_context
    assert {"from": "AP_INVOICES_ALL.VENDOR_ID", "to": "POZ_SUPPLIERS.VENDOR_ID"} in schema[
        "foreign_keys"
    ]
    assert {"from": "POZ_SUPPLIERS.PARTY_ID", "to": "HZ_PARTIES.PARTY_ID"} in schema["foreign_keys"]
    before = await counts(db_session)
    second = await load_development_fixtures(
        db_session,
        manifest=manifest,
        app_env="development",
        include_sample_projects=True,
    )
    assert second.projects_created == 0
    assert second.projects_skipped == 1
    assert await counts(db_session) == before


@pytest.mark.asyncio
async def test_publisher_seed_adds_separate_intelligence_and_preserves_legacy_projects(
    db_session: AsyncSession,
) -> None:
    await load_development_fixtures(
        db_session,
        manifest=read_fixture_manifest(),
        app_env="development",
        include_sample_projects=True,
    )
    project = (await db_session.scalars(select(Project))).one()
    profile = await db_session.get(ERPProfile, project.erp_profile_id)
    legacy = await db_session.get(ERPProfileVersion, project.erp_profile_version_id)
    assert legacy.status == "PUBLISHED"
    assert {"SQL", "PKS", "PKB"} <= set(legacy.supported_artifact_types)
    historical = [profile, legacy, project, *project.artifacts]
    historical.extend(
        await db_session.scalars(
            select(PromptVersion).where(PromptVersion.profile_version_id == legacy.id)
        )
    )
    snapshots = []
    for record in historical:
        await db_session.refresh(record)
        snapshots.append(
            copy.deepcopy(
                {column.name: getattr(record, column.name) for column in record.__table__.columns}
            )
        )
    manifest = read_fixture_manifest("oracle-publisher-harness-v1")
    first = await load_development_fixtures(
        db_session, manifest=manifest, app_env="development"
    )
    assert first.profiles_created == first.projects_created == 0
    assert first.profiles_skipped == 1 and first.prompts_created == 4
    versions = list(
        await db_session.scalars(
            select(ERPProfileVersion)
            .where(ERPProfileVersion.profile_id == profile.id)
            .order_by(ERPProfileVersion.version)
        )
    )
    assert len(versions) == 2 and versions[0].id == legacy.id
    publisher = versions[1]
    assert publisher.status == "PUBLISHED" and publisher.version == 2
    assert publisher.configuration == manifest.profiles[0].profile_version.configuration
    assert publisher.supported_artifact_types == ["CONTEXT_ANALYSIS", "FDD", "TDD", "PUBLISHER"]
    pattern = (await db_session.scalars(select(IntegrationPattern))).one()
    pattern_version = (await db_session.scalars(select(IntegrationPatternVersion))).one()
    assert pattern.erp_profile_id == profile.id and pattern.key == "publisher-outbound"
    assert pattern_version.pattern_id == pattern.id
    assert pattern_version.profile_version_id == publisher.id
    assert pattern_version.status == "PUBLISHED" and pattern_version.version == 1
    assert pattern_version.deliverable_type == "PUBLISHER_SOURCE"
    reference = (await db_session.scalars(select(PatternBaseline))).one()
    baseline = await db_session.get(ERPAssetVersion, reference.asset_version_id)
    assert reference.pattern_version_id == pattern_version.id
    assert baseline.profile_version_id == publisher.id and baseline.version == 1
    assert baseline.status == "PUBLISHED" and baseline.asset_kind == "PACKAGE"
    assert baseline.checksum == sha256(baseline.text_content.encode())
    assert json.loads(baseline.text_content) == manifest.profiles[0].integration_patterns[0][
        "baseline"
    ]["content"]
    prompts = list(
        await db_session.scalars(
            select(PromptVersion).where(PromptVersion.profile_version_id == publisher.id)
        )
    )
    assert all(prompt.status == "PUBLISHED" for prompt in prompts)
    assert {prompt.name: prompt.content for prompt in prompts} == {
        prompt.name: prompt.content for prompt in manifest.profiles[0].profile_version.prompts
    }
    before = await counts(db_session)
    second = await load_development_fixtures(
        db_session, manifest=manifest, app_env="development"
    )
    assert second.profiles_created == second.prompts_created == second.projects_created == 0
    assert await counts(db_session) == before
    for record, snapshot in zip(historical, snapshots, strict=True):
        await db_session.refresh(record)
        assert {
            column.name: getattr(record, column.name) for column in record.__table__.columns
        } == snapshot


@pytest.mark.asyncio
async def test_existing_admin_configuration_and_retirement_are_preserved(
    db_session: AsyncSession,
) -> None:
    manifest = read_fixture_manifest()
    await load_development_fixtures(db_session, manifest=manifest, app_env="development")
    profile = (
        await db_session.execute(select(ERPProfile).where(ERPProfile.key == "oracle-fusion-cloud"))
    ).scalar_one()
    version = (
        await db_session.execute(
            select(ERPProfileVersion).where(ERPProfileVersion.profile_id == profile.id)
        )
    ).scalar_one()
    prompt = (
        await db_session.execute(
            select(PromptVersion).where(PromptVersion.profile_version_id == version.id).limit(1)
        )
    ).scalar_one()
    profile.active = False
    profile.status = "RETIRED"
    profile.updated_by = "authenticated-admin"
    version.status = "RETIRED"
    version.configuration = {"administrator_setting": True}
    prompt.status = "RETIRED"
    prompt.content = "Administrator revision must survive fixture reruns"
    await db_session.flush()
    before = await counts(db_session)
    report = await load_development_fixtures(
        db_session,
        manifest=manifest,
        app_env="development",
        include_sample_projects=True,
    )
    assert report.profiles_created == 0
    assert report.projects_created == 0
    assert await counts(db_session) == before
    await db_session.refresh(profile)
    await db_session.refresh(version)
    await db_session.refresh(prompt)
    assert profile.active is False
    assert profile.status == "RETIRED"
    assert version.configuration == {"administrator_setting": True}
    assert version.status == prompt.status == "RETIRED"
    assert prompt.content == "Administrator revision must survive fixture reruns"


@pytest.mark.asyncio
async def test_fixture_loading_skips_existing_profile_even_if_version_missing(
    db_session: AsyncSession,
) -> None:
    profile = ERPProfile(
        key="oracle-fusion-cloud",
        name="Managed Oracle",
        vendor="Oracle",
        status="DRAFT",
        active=True,
    )
    db_session.add(profile)
    await db_session.flush()
    report = await load_development_fixtures(
        db_session, manifest=read_fixture_manifest(), app_env="development"
    )
    assert report.profiles_skipped == 1
    assert report.prompts_created == 0
    versions = (
        (
            await db_session.execute(
                select(ERPProfileVersion).where(ERPProfileVersion.profile_id == profile.id)
            )
        )
        .scalars()
        .all()
    )
    assert versions == []
    assert profile.status == "DRAFT"
    assert profile.name == "Managed Oracle"


@pytest.mark.asyncio
async def test_fixtures_reject_production_before_database_access(db_session: AsyncSession) -> None:
    before = await counts(db_session)
    with pytest.raises(ValueError, match="disabled outside"):
        await load_development_fixtures(
            db_session, manifest=read_fixture_manifest(), app_env="production"
        )
    assert await counts(db_session) == before


@pytest.mark.asyncio
async def test_empty_project_list_does_not_load_fixtures(db_session: AsyncSession) -> None:
    before = await counts(db_session)
    response = await list_projects(db=db_session)
    assert response.total == 0
    assert response.projects == []
    assert await counts(db_session) == before


@pytest.mark.asyncio
async def test_workflow_reads_do_not_write_or_unlock_stale_descendants(
    db_session: AsyncSession,
) -> None:
    await load_development_fixtures(
        db_session,
        manifest=read_fixture_manifest(),
        app_env="development",
        include_sample_projects=True,
    )
    project = (await db_session.execute(select(Project))).scalar_one()
    workflow = WorkflowEngine(db_session)
    artifacts = {artifact.artifact_type: artifact for artifact in project.artifacts}
    artifacts["CONTEXT_ANALYSIS"].gate_status = GateStatus.PENDING_REVIEW
    for stage in ("FDD", "TDD", "SQL"):
        artifact = artifacts[stage]
        artifact.gate_status = GateStatus.APPROVED
        artifact.current_version = 1
        db_session.add(
            ArtifactVersion(
                artifact_id=artifact.id,
                version_number=1,
                state=VersionState.APPROVED,
                content={"historical": True},
                generated_at=datetime.now(UTC),
            )
        )
    artifacts["PKS"].gate_status = GateStatus.GENERATING
    await db_session.commit()
    before = await counts(db_session)
    statements: list[str] = []

    def capture(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(db_session.bind.sync_engine, "before_cursor_execute", capture)
    try:
        first = await workflow.get_workflow_status(project)
        second = await workflow.get_workflow_status(project)
        assert first == second
        actual = {stage["stage"]: stage for stage in first["stages"]}
        assert actual["FDD"]["gate_status"] == "INVALIDATED"
        assert actual["TDD"]["gate_status"] == "INVALIDATED"
        assert actual["PKS"]["gate_status"] == "INVALIDATED"
        assert actual["TDD"]["can_generate"] is False
        assert await workflow.can_generate(project.id, "PKS") is False
        assert await workflow.can_generate(project.id, "TDD") is False
        assert not db_session.dirty
        assert not db_session.new
        await db_session.commit()
    finally:
        event.remove(db_session.bind.sync_engine, "before_cursor_execute", capture)
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    assert await counts(db_session) == before
    persisted = (await db_session.execute(select(ArtifactVersion))).scalars().all()
    assert all(version.state == VersionState.APPROVED for version in persisted)
    assert artifacts["FDD"].gate_status == GateStatus.APPROVED
    assert artifacts["PKS"].gate_status == GateStatus.GENERATING


@pytest.mark.parametrize("name", ["../development-v1", "Development", "", "fixture.json", "x/y"])
def test_fixture_manifest_rejects_path_traversal(name: str) -> None:
    with pytest.raises(ValueError, match="identifier"):
        read_fixture_manifest(name)


def test_development_command_rejects_non_development_environment() -> None:
    with pytest.raises(ValueError, match="APP_ENV"):
        require_development(Settings(_env_file=None, app_env="production"))


def test_command_errors_do_not_print_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import app.cli.__main__ as cli

    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: (_ for _ in ()).throw(ValueError("credential-that-must-not-appear")),
    )
    assert main(["seed"]) == 2
    assert "credential-that-must-not-appear" not in capsys.readouterr().err


def test_explicit_development_init_and_seed_work_end_to_end(tmp_path: Path) -> None:
    from app.cli.__main__ import initialize_development_database, seed_database

    database_file = tmp_path / "explicit-development.sqlite"
    settings = Settings(
        _env_file=None,
        app_env="development",
        database_url=f"sqlite+aiosqlite:///{database_file}",
        llm_provider="mock",
        demo_mode=True,
    )
    initialization = initialize_development_database(settings, legacy_sqlite=False)
    assert initialization == {"schema": "alembic-head", "fixtures": "not-loaded"}

    async def verify_and_seed() -> None:
        engine = create_async_engine(settings.database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                assert (await counts(session))["erp_profiles"] == 0
                assert (await list_projects(db=session)).total == 0
        finally:
            await engine.dispose()
        first = await seed_database(
            settings, manifest_name="development-v1", include_sample_projects=True
        )
        second = await seed_database(
            settings, manifest_name="development-v1", include_sample_projects=True
        )
        assert first["profiles_created"] == 5
        assert first["projects_created"] == 1
        assert second["profiles_created"] == second["projects_created"] == 0
        assert first["manifest_checksum"] == second["manifest_checksum"]

    asyncio.run(verify_and_seed())


@pytest.mark.asyncio
async def test_legacy_upgrade_preserves_lifecycle_and_exact_binding() -> None:
    from app.dev_sqlite_migrations import migrate_legacy_sqlite

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("""
                CREATE TABLE erp_profiles (
                    id TEXT PRIMARY KEY, name TEXT, active BOOLEAN, status TEXT,
                    display_name TEXT, created_by TEXT, updated_by TEXT
                )
            """)
            await connection.exec_driver_sql("""
                CREATE TABLE erp_profile_versions (
                    id TEXT PRIMARY KEY, profile_id TEXT, version INTEGER, status TEXT
                )
            """)
            await connection.exec_driver_sql("""
                CREATE TABLE projects (
                    id TEXT PRIMARY KEY, name TEXT, erp_profile_id TEXT,
                    erp_profile_version_id TEXT
                )
            """)
            await connection.exec_driver_sql("""
                INSERT INTO erp_profiles VALUES ('p', 'Demo ERP', 1, 'DRAFT', '', 'admin', 'admin')
            """)
            await connection.exec_driver_sql("""
                INSERT INTO erp_profile_versions VALUES
                    ('v1', 'p', 1, 'PUBLISHED'), ('v2', 'p', 2, 'PUBLISHED')
            """)
            await connection.exec_driver_sql("""
                INSERT INTO projects VALUES
                    ('exact', 'Known request', NULL, 'v1'),
                    ('unknown', 'Demo ERP request', NULL, NULL),
                    ('profile-only', 'Known profile', 'p', NULL)
            """)
            await connection.run_sync(migrate_legacy_sqlite)
            await connection.run_sync(migrate_legacy_sqlite)
            rows = (
                await connection.exec_driver_sql(
                    "SELECT id, erp_profile_id, erp_profile_version_id FROM projects ORDER BY id"
                )
            ).all()
            assert rows == [
                ("exact", "p", "v1"),
                ("profile-only", "p", None),
                ("unknown", None, None),
            ]
            lifecycle = (
                await connection.exec_driver_sql("SELECT status FROM erp_profiles")
            ).scalar_one()
            assert lifecycle == "DRAFT"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_prompt_upgrade_preserves_all_versions_and_statuses() -> None:
    from app.dev_sqlite_migrations import migrate_legacy_sqlite

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("""
                CREATE TABLE erp_stage_prompts (
                    id TEXT PRIMARY KEY, profile_id TEXT, profile_version_id TEXT,
                    stage TEXT, version INTEGER, system_prompt TEXT, status TEXT,
                    created_at TEXT, updated_at TEXT
                )
            """)
            await connection.exec_driver_sql(
                "CREATE TABLE erp_profile_versions (id TEXT PRIMARY KEY)"
            )
            await connection.exec_driver_sql("""
                CREATE TABLE prompt_versions (
                    id TEXT PRIMARY KEY, scope TEXT, profile_version_id TEXT, name TEXT,
                    stage TEXT, content TEXT, version INTEGER, status TEXT, variables TEXT,
                    created_by TEXT, updated_by TEXT, created_at TEXT, updated_at TEXT
                )
            """)
            await connection.exec_driver_sql("""
                INSERT INTO erp_stage_prompts VALUES
                    ('old1', 'profile', 'v1', 'FDD', 1, 'Historical prompt',
                     'RETIRED', 'date', 'date'),
                    ('old2', 'profile', 'v1', 'FDD', 2, 'Current draft', 'DRAFT', 'date', 'date')
            """)
            await connection.run_sync(migrate_legacy_sqlite)
            await connection.run_sync(migrate_legacy_sqlite)
            rows = (
                await connection.exec_driver_sql(
                    "SELECT version, content, status FROM prompt_versions ORDER BY version"
                )
            ).all()
            assert rows == [(1, "Historical prompt", "RETIRED"), (2, "Current draft", "DRAFT")]
    finally:
        await engine.dispose()
