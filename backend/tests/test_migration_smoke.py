"""Migration checks in disposable SQLite/PostgreSQL databases, never production.

Set TEST_POSTGRES_URL to a dedicated database whose name ends in _test.
Its role needs CREATEDB; each test creates and drops only a generated database.
No application .env credentials are used or printed by these fixtures.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal

import pytest
import pytest_asyncio
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.models import Base

BACKEND = Path(__file__).resolve().parents[1]


@pytest_asyncio.fixture
async def migration_database() -> AsyncIterator[URL]:
    value = os.environ.get("TEST_POSTGRES_URL")
    if not value:
        pytest.skip("TEST_POSTGRES_URL is not configured; PostgreSQL evidence is unavailable")
    connection_url = make_url(value)
    if connection_url.get_backend_name() != "postgresql":
        pytest.fail("TEST_POSTGRES_URL must use PostgreSQL")
    if not connection_url.database or not connection_url.database.endswith("_test"):
        pytest.fail("Refusing migration tests: the fixture database name must end in _test")
    connection_url = connection_url.set(drivername="postgresql+asyncpg")
    control = create_async_engine(connection_url, isolation_level="AUTOCOMMIT")
    name = f"erpfusion_migration_{uuid.uuid4().hex}"
    created = False
    try:
        async with control.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
            created = True
        yield connection_url.set(database=name)
    finally:
        if created:
            async with control.connect() as connection:
                await connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await control.dispose()


def migrate(
    database: URL, revision: str, direction: Literal["upgrade", "downgrade"] = "upgrade"
) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": database.render_as_string(hide_password=False),
            "APP_ENV": "test",
            "DEBUG": "false",
            "LLM_PROVIDER": "mock",
            "DEMO_MODE": "true",
            "GROQ_API_KEY": "",
            "ERP_ADMIN_API_KEY": "",
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", direction, revision],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, "Alembic migration failed in the disposable fixture"


def expected_head() -> str:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    revision = ScriptDirectory.from_config(config).get_current_head()
    assert revision is not None
    return revision


async def assert_head_and_columns(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == expected_head()
        actual = await connection.run_sync(
            lambda conn: {
                table: {column["name"] for column in inspect(conn).get_columns(table)}
                for table in inspect(conn).get_table_names()
            }
        )
        protected: list[str] = list(
            (
                await connection.execute(
                    text("""
                SELECT relname FROM pg_class
                WHERE relnamespace = 'public'::regnamespace
                  AND relrowsecurity AND relforcerowsecurity
            """)
                )
            )
            .scalars()
            .all()
        )
        assert {
            "clients",
            "erp_installations",
            "erp_environments",
            "projects",
            "artifacts",
            "artifact_versions",
            "validation_results",
            "generation_runs",
            "audit_entries",
            "feedback_guidance",
            "admin_audit_events",
            "client_memberships",
            "platform_role_assignments",
            "execution_attempts",
            "capability_qualifications",
            "simulated_artifacts",
            "integration_patterns",
            "integration_pattern_versions",
            "pattern_baselines",
        } <= set(protected)
    for table in Base.metadata.sorted_tables:
        assert table.name in actual, f"Migration omitted model table {table.name}"
        assert set(table.columns.keys()) <= actual[table.name], f"Missing columns in {table.name}"


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_fresh_postgresql_migrations_are_idempotent(migration_database: URL) -> None:
    migrate(migration_database, "head")
    migrate(migration_database, "head")
    engine = create_async_engine(migration_database)
    try:
        await assert_head_and_columns(engine)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_row_security_migration_rollback_preserves_existing_clients(
    migration_database: URL,
) -> None:
    migrate(migration_database, "head")
    engine = create_async_engine(migration_database)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("""
                INSERT INTO clients (id, client_key, display_name, status, created_at, updated_at)
                VALUES ('rollback-client', 'rollback-client', 'Preserved Client',
                        'ACTIVE', now(), now())
            """)
            )
        migrate(migration_database, "20261002_01", direction="downgrade")
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT display_name FROM clients WHERE id = 'rollback-client'")
                )
                == "Preserved Client"
            )
        migrate(migration_database, "head")
        await assert_head_and_columns(engine)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_postgresql_legacy_upgrade_preserves_explicit_bindings(
    migration_database: URL,
) -> None:
    migrate(migration_database, "20260929_01")
    engine = create_async_engine(migration_database)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("""
                INSERT INTO erp_profiles
                  (id, key, name, vendor, active, configuration, created_at, updated_at)
                VALUES ('fixture-profile', 'fixture-platform', 'Fixture ERP', 'Fixture Vendor',
                        true, '{}'::json, now(), now())
            """)
            )
            await connection.execute(
                text("""
                INSERT INTO projects
                  (id, name, business_requirement, erp_schema_context, status,
                   erp_profile_id, created_at, updated_at)
                VALUES ('fixture-request', 'Fixture Integration', 'Preserve this requirement',
                        '{}'::json, 'ACTIVE', 'fixture-profile', now(), now())
            """)
            )
            await connection.execute(
                text("""
                INSERT INTO erp_stage_prompts
                  (id, profile_id, stage, version, system_prompt, created_at, updated_at)
                VALUES ('fixture-prompt', 'fixture-profile', 'CONTEXT_ANALYSIS', 1,
                        'Preserve fixture instructions', now(), now())
            """)
            )
        migrate(migration_database, "head")
        await assert_head_and_columns(engine)
        async with engine.connect() as connection:
            project = (
                await connection.execute(
                    text("""
                SELECT p.business_requirement, p.erp_profile_id,
                       v.profile_id, v.version, p.client_id
                FROM projects p
                JOIN erp_profile_versions v ON v.id = p.erp_profile_version_id
                WHERE p.id = 'fixture-request'
            """)
                )
            ).one()
            assert project == (
                "Preserve this requirement",
                "fixture-profile",
                "fixture-profile",
                1,
                None,
            )
            prompts = (
                await connection.execute(
                    text("""
                SELECT content, version FROM prompt_versions
                WHERE name = 'CONTEXT_ANALYSIS instructions'
            """)
                )
            ).all()
            assert prompts == [("Preserve fixture instructions", 1)]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_pattern_migration_preserves_legacy_rows_and_downgrades(
    tmp_path: Path,
) -> None:
    database = URL.create("sqlite+aiosqlite", database=str(tmp_path / "migration.sqlite"))
    migrate(database, "20261005_01")
    engine = create_async_engine(database)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("""
                INSERT INTO erp_profiles
                  (id, key, name, vendor, active, configuration, created_at, updated_at)
                VALUES ('preserved-product', 'preserved-product', 'Preserved Product',
                        'Fixture', true, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """)
            )
            await connection.execute(
                text("""
                INSERT INTO projects
                  (id, name, business_requirement, erp_schema_context, status,
                   erp_profile_id, project_type, requirement_version,
                   schema_context_version, workflow_revision, workflow_status,
                   created_at, updated_at, last_activity_at)
                VALUES ('preserved-project', 'Preserved Project', 'Preserved requirement',
                        '{}', 'ACTIVE', 'preserved-product', 'CUSTOM', 1, 1, 0, 'DRAFT',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """)
            )
        migrate(database, "head")
        migrate(database, "head")
        async with engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT version_num FROM alembic_version"))
                == expected_head()
            )
            assert (
                await connection.execute(
                    text("""
                SELECT business_requirement, integration_pattern_version_id
                FROM projects WHERE id = 'preserved-project'
            """)
                )
            ).one() == ("Preserved requirement", None)
            actual = await connection.run_sync(
                lambda conn: {
                    name: set(column["name"] for column in inspect(conn).get_columns(name))
                    for name in inspect(conn).get_table_names()
                }
            )
            for table in Base.metadata.sorted_tables:
                assert set(table.columns.keys()) <= actual[table.name]
        migrate(database, "20261005_01", direction="downgrade")
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("""
                SELECT business_requirement FROM projects WHERE id = 'preserved-project'
            """)
                )
                == "Preserved requirement"
            )
            assert "integration_patterns" not in await connection.run_sync(
                lambda conn: inspect(conn).get_table_names()
            )
        migrate(database, "head")
    finally:
        await engine.dispose()
