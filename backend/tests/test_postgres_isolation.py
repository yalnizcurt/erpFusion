"""Exercise RLS with a real non-owner PostgreSQL runtime role.

These tests reuse only the generated database fixture. The privileged fixture
role creates a temporary runtime role; no application credential is read.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.config import Settings
from app.models import (
    AdminAuditEvent,
    Artifact,
    ArtifactVersion,
    AuditEntry,
    Client,
    ClientMembership,
    ERPAssetVersion,
    ERPInstallation,
    ERPProfile,
    ERPProfileVersion,
    FeedbackGuidance,
    IdentitySubject,
    IntegrationPattern,
    IntegrationPatternVersion,
    PatternBaseline,
    PlatformRoleAssignment,
    ValidationResult,
)
from app.security.tenant_context import apply_tenant_context, assert_runtime_role
from app.services.execution import subject_identity
from tests.test_migration_smoke import migrate, migration_database  # noqa: F401

pytestmark = pytest.mark.postgres


async def _seed_before_row_security(engine: AsyncEngine) -> None:
    # These three records use revision01 columns; current ORM models include
    # columns added only after RLS. Historical mismatches must precede its FKs.
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all([
            AdminAuditEvent(
                id="registry-audit", actor="fixture", action="PROFILE_CREATED",
                entity_type="ERPProfile", entity_id="fixture-profile",
            ),
            IdentitySubject(id="subject-a", issuer="https://fixture.example", subject="user-a"),
            IdentitySubject(id="subject-b", issuer="https://fixture.example", subject="user-b"),
            Client(id="client-a", client_key="client-a", display_name="Client A"),
            Client(id="client-b", client_key="client-b", display_name="Client B"),
            ERPProfile(id="fixture-profile", key="fixture-erp", name="Fixture ERP", vendor="Test"),
        ])
        await session.flush()
        session.add_all([
            ClientMembership(
                id="membership-a", client_id="client-a", subject_id="subject-a", role="CONSULTANT",
            ),
            ClientMembership(
                id="membership-b", client_id="client-b", subject_id="subject-b", role="CONSULTANT",
            ),
            PlatformRoleAssignment(
                id="role-a", subject_id="subject-a", role="ERP_CONFIGURATOR",
            ),
            PlatformRoleAssignment(id="role-b", subject_id="subject-b", role="PLATFORM_ADMIN"),
        ])
        await session.flush()
        for suffix in ("a", "b"):
            session.add(ERPInstallation(
                id=f"installation-{suffix}", client_id=f"client-{suffix}",
                erp_profile_id="fixture-profile", installation_key="primary",
                display_name=f"Client {suffix} ERP",
            ))
        await session.flush()
        for suffix in ("a", "b"):
            await session.execute(text("""
                INSERT INTO erp_environments (id, client_id, installation_id, environment_key,
                    display_name, configuration, created_at, updated_at)
                VALUES (:id, :client, :installation, 'sandbox', :name, '{}', now(), now())
            """), {
                "id": f"environment-{suffix}", "client": f"client-{suffix}",
                "installation": f"installation-{suffix}", "name": f"Client {suffix} sandbox",
            })
        await session.flush()
        session.add(ERPProfileVersion(
            id="fixture-profile-version", profile_id="fixture-profile", version=1,
        ))
        await session.flush()
        for suffix, client_id in (("a", "client-a"), ("b", "client-b"), ("legacy", None)):
            await session.execute(text("""
                INSERT INTO projects (id, name, business_requirement, erp_schema_context,
                    client_id, erp_profile_id, erp_profile_version_id, status,
                    created_at, updated_at)
                VALUES (:id, :name, 'A preserved client requirement', '{}', :client,
                    'fixture-profile', 'fixture-profile-version', 'ACTIVE', now(), now())
            """), {"id": f"project-{suffix}", "name": f"Request {suffix}", "client": client_id})
            session.add(Artifact(
                id=f"artifact-{suffix}", project_id=f"project-{suffix}", client_id=client_id,
                artifact_type="FDD",
            ))
            await session.execute(text("""
                INSERT INTO generation_runs (id, project_id, client_id, profile_version_id,
                    artifact_type, model, resolved_context, provenance, status, created_at)
                VALUES (:id, :project, :client, 'fixture-profile-version',
                    'FDD', 'fixture', '{}', '{}', 'COMPLETED', now())
            """), {
                "id": f"generation-{suffix}", "project": f"project-{suffix}", "client": client_id,
            })
            await session.flush()
            session.add(ArtifactVersion(
                id=f"version-{suffix}", artifact_id=f"artifact-{suffix}", client_id=client_id,
                version_number=1, content={"client": suffix},
            ))
            await session.flush()
            session.add_all([
                ValidationResult(
                    id=f"validation-{suffix}", artifact_version_id=f"version-{suffix}",
                    client_id=client_id, category="DOCUMENT", status="PASS", checks=[],
                ),
                AuditEntry(
                    id=f"audit-{suffix}", artifact_version_id=f"version-{suffix}",
                    project_id=f"project-{suffix}", client_id=client_id,
                    action="CREATED", actor="fixture",
                ),
                FeedbackGuidance(
                    id=f"feedback-{suffix}", project_id=f"project-{suffix}", client_id=client_id,
                    scope="PROJECT", content=f"Scoped feedback {suffix}",
                ),
                AdminAuditEvent(
                    id=f"admin-audit-{suffix}", client_id=client_id, actor="fixture",
                    action="fixture", entity_type="client", entity_id=client_id or "legacy",
                ),
            ])
        # Existing inconsistent rows are preserved for reviewed reconciliation,
        # but must never become visible because the copied child client matches.
        session.add(Artifact(
            id="artifact-mismatch", project_id="project-b", client_id="client-a",
            artifact_type="FDD",
        ))
        session.add(ArtifactVersion(
            id="version-mismatch", artifact_id="artifact-b", client_id="client-a",
            version_number=2,
        ))
        session.add_all([
            FeedbackGuidance(id="guidance-global", scope="GLOBAL", content="Approved common rule"),
            FeedbackGuidance(
                id="guidance-erp", scope="ERP", profile_id="fixture-profile",
                content="Approved ERP rule",
            ),
            FeedbackGuidance(
                id="guidance-draft", scope="GLOBAL", content="Unapproved", status="DRAFT",
            ),
        ])
        await session.commit()


@pytest_asyncio.fixture
async def isolated_runtime(
    migration_database: URL,  # noqa: F811 - imported pytest fixture
) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    migrate(migration_database, "20261002_01")
    owner = create_async_engine(migration_database)
    await _seed_before_row_security(owner)
    migrate(migration_database, "head")
    role = f"erpfusion_runtime_{uuid.uuid4().hex}"
    password = secrets.token_hex(32)
    runtime = None
    created = False
    try:
        async with owner.begin() as connection:
            await connection.execute(text(
                f'CREATE ROLE "{role}" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                f"NOINHERIT NOBYPASSRLS PASSWORD '{password}'"
            ))
            created = True
            await connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
            await connection.execute(text(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}"'
            ))
        runtime = create_async_engine(
            migration_database.set(username=role, password=password), pool_size=1, max_overflow=0,
        )
        yield owner, runtime
    finally:
        if runtime is not None:
            await runtime.dispose()
        if created:
            async with owner.begin() as connection:
                await connection.execute(text(f'DROP OWNED BY "{role}"'))
                await connection.execute(text(f'DROP ROLE "{role}"'))
        await owner.dispose()


@pytest.mark.asyncio
async def test_non_owner_role_filters_entire_artifact_history(isolated_runtime) -> None:
    _owner, runtime = isolated_runtime
    factory = async_sessionmaker(runtime)
    async with factory() as session:
        await assert_runtime_role(session)
        await apply_tenant_context(session, client_ids=["client-a"])
        for table, expected in (
            ("clients", ["client-a"]),
            ("erp_installations", ["installation-a"]),
            ("erp_environments", ["environment-a"]),
            ("client_memberships", ["membership-a"]),
            ("projects", ["project-a"]),
            ("artifacts", ["artifact-a"]),
            ("artifact_versions", ["version-a"]),
            ("validation_results", ["validation-a"]),
            ("generation_runs", ["generation-a"]),
            ("audit_entries", ["audit-a"]),
            ("admin_audit_events", ["admin-audit-a"]),
            ("feedback_guidance", ["feedback-a", "guidance-erp", "guidance-global"]),
        ):
            actual = (await session.execute(text(f"SELECT id FROM {table} ORDER BY id"))).scalars()
            assert list(actual) == expected, table


@pytest.mark.asyncio
async def test_cross_client_and_nullable_child_writes_are_rejected(isolated_runtime) -> None:
    _owner, runtime = isolated_runtime
    factory = async_sessionmaker(runtime)
    for parent, child_client in (("project-b", "client-a"), ("project-a", None)):
        async with factory() as session:
            await apply_tenant_context(session, client_ids=["client-a"])
            with pytest.raises(DBAPIError):
                await session.execute(text("""
                    INSERT INTO artifacts (id, project_id, client_id, artifact_type,
                        current_version, gate_status, created_at, updated_at)
                    VALUES ('forbidden-child', :parent, :client, 'FDD', 0, 'LOCKED', now(), now())
                """), {"parent": parent, "client": child_client})
            await session.rollback()
    async with factory() as session:
        await apply_tenant_context(session, client_ids=["client-a"])
        session.add(Artifact(
            id="allowed-artifact", project_id="project-a", client_id="client-a",
            artifact_type="TDD",
        ))
        await session.flush()
        await session.rollback()
    async with factory() as session:
        await apply_tenant_context(session, client_ids=["client-a"])
        result = await session.execute(text("DELETE FROM projects WHERE id = 'project-b'"))
        assert result.rowcount == 0
        with pytest.raises(DBAPIError):
            await session.execute(text("UPDATE projects SET client_id = 'client-b' "
                                       "WHERE id = 'project-a'"))
        await session.rollback()


@pytest.mark.asyncio
async def test_pool_reuse_resets_context_and_commit_reapplies_session_context(
    isolated_runtime,
) -> None:
    _owner, runtime = isolated_runtime
    factory = async_sessionmaker(runtime)
    async with factory() as first:
        await apply_tenant_context(first, client_ids=["client-a"])
        assert await first.scalar(text("SELECT id FROM projects")) == "project-a"
        await first.commit()
        assert await first.scalar(text("SELECT id FROM projects")) == "project-a"
    async with factory() as second:
        assert await second.scalar(text("SELECT count(*) FROM projects")) == 0
        assert await second.scalar(text("SELECT count(*) FROM client_memberships")) == 0
        assert await second.scalar(text("SELECT count(*) FROM platform_role_assignments")) == 0
        await apply_tenant_context(second, client_ids=["client-b"])
        assert await second.scalar(text("SELECT id FROM projects")) == "project-b"
        await second.rollback()
    async with runtime.connect() as raw_connection:
        assert await raw_connection.scalar(text("SELECT count(*) FROM projects")) == 0


@pytest.mark.asyncio
async def test_erp_admin_cannot_read_client_rows_or_unapproved_client_feedback(
    isolated_runtime,
) -> None:
    owner, runtime = isolated_runtime
    factory = async_sessionmaker(runtime)
    async with factory() as session:
        await apply_tenant_context(session, client_ids=[], is_erp_admin=True)
        assert await session.scalar(text("SELECT count(*) FROM projects")) == 0
        guidance = (await session.execute(text(
            "SELECT id FROM feedback_guidance ORDER BY id"
        ))).scalars().all()
        assert guidance == ["guidance-draft", "guidance-erp", "guidance-global"]
        assert await session.scalar(text("SELECT id FROM admin_audit_events")) == "registry-audit"
        await apply_tenant_context(session, client_ids=[], is_platform_admin=True)
        assert await session.scalar(text("SELECT count(*) FROM projects")) == 2
    async with async_sessionmaker(owner)() as session:
        with pytest.raises(RuntimeError, match="must not own tables"):
            await assert_runtime_role(session)


@pytest.mark.asyncio
async def test_subject_bootstrap_cannot_grant_itself_administrator_roles(isolated_runtime) -> None:
    _owner, runtime = isolated_runtime
    factory = async_sessionmaker(runtime)
    async with factory() as session:
        await apply_tenant_context(session, client_ids=[], subject_id="subject-a")
        assert await session.scalar(text("SELECT id FROM client_memberships")) == "membership-a"
        assert await session.scalar(text("SELECT id FROM platform_role_assignments")) == "role-a"
        assert await session.scalar(text("SELECT count(*) FROM projects")) == 0
        await apply_tenant_context(session, client_ids=["client-a"], subject_id="subject-a")
        result = await session.execute(text(
            "UPDATE platform_role_assignments SET role = 'PLATFORM_ADMIN' WHERE id = 'role-a'"
        ))
        assert result.rowcount == 0
        with pytest.raises(DBAPIError):
            session.add(ClientMembership(
                id="escalation", client_id="client-a", subject_id="subject-a", role="CLIENT_ADMIN",
            ))
            await session.flush()
        await session.rollback()


@pytest.mark.asyncio
async def test_client_administration_requires_the_client_admin_membership(isolated_runtime) -> None:
    _owner, runtime = isolated_runtime
    factory = async_sessionmaker(runtime)
    async with factory() as reviewer:
        await apply_tenant_context(reviewer, client_ids=["client-a"], subject_id="subject-a")
        for table in ("erp_installations", "erp_environments"):
            result = await reviewer.execute(text(
                f"UPDATE {table} SET display_name = 'forbidden' WHERE client_id = 'client-a'"
            ))
            assert result.rowcount == 0
    async with factory() as client_admin:
        await apply_tenant_context(
            client_admin, client_ids=["client-a"], client_admin_ids=["client-a"],
            subject_id="subject-a",
        )
        for table in ("erp_installations", "erp_environments"):
            result = await client_admin.execute(text(
                f"UPDATE {table} SET display_name = 'updated' WHERE client_id = 'client-a'"
            ))
            assert result.rowcount == 1
        client_admin.add(ClientMembership(
            id="allowed-member", client_id="client-a", subject_id="subject-b",
            role="FUNCTIONAL_REVIEWER",
        ))
        await client_admin.flush()
        with pytest.raises(DBAPIError):
            client_admin.add(ClientMembership(
                id="cross-client-member", client_id="client-b", subject_id="subject-a",
                role="CLIENT_ADMIN",
            ))
            await client_admin.flush()
        await client_admin.rollback()


@pytest.mark.asyncio
async def test_platform_administration_audits_allow_platform_admin_only(isolated_runtime) -> None:
    _owner, runtime = isolated_runtime
    factory = async_sessionmaker(runtime)
    for action in ("FIRST_ADMIN_BOOTSTRAPPED", "PLATFORM_ROLE_ASSIGNED", "PLATFORM_ROLE_REVOKED"):
        async with factory() as platform_admin:
            await apply_tenant_context(
                platform_admin, client_ids=[], subject_id="subject-b", is_platform_admin=True,
            )
            platform_admin.add(AdminAuditEvent(
                id=f"audit-{action}", actor="fixture-admin", actor_subject_id="subject-b",
                action=action, entity_type="PlatformRoleAssignment", entity_id="role-b",
            ))
            await platform_admin.commit()
    async with factory() as erp_admin:
        await apply_tenant_context(erp_admin, client_ids=[], is_erp_admin=True)
        assert await erp_admin.scalar(text("SELECT id FROM admin_audit_events")) == "registry-audit"
        with pytest.raises(DBAPIError):
            erp_admin.add(AdminAuditEvent(
                id="forbidden-platform-audit", actor="fixture-erp-admin",
                action="PLATFORM_ROLE_ASSIGNED", entity_type="PlatformRoleAssignment",
                entity_id="role-a",
            ))
            await erp_admin.flush()
        await erp_admin.rollback()


@pytest.mark.asyncio
async def test_pattern_rls_preserves_published_contracts_and_baselines(isolated_runtime) -> None:
    _owner, runtime = isolated_runtime
    factory = async_sessionmaker(runtime, expire_on_commit=False)
    async with factory() as admin:
        await apply_tenant_context(admin, client_ids=[], is_erp_admin=True)
        admin.add(IntegrationPattern(
            id="pattern", erp_profile_id="fixture-profile", key="fixture-pattern",
            name="Fixture pattern", created_by="fixture",
        ))
        for name in ("published", "draft", "spare"):
            admin.add(ERPAssetVersion(
                id=f"baseline-{name}", asset_id=f"baseline-{name}",
                profile_version_id="fixture-profile-version", asset_kind="PACKAGE",
                name=f"Baseline {name}", version=1, status="PUBLISHED",
            ))
        await admin.flush()
        for version, name in enumerate(("published", "draft"), start=1):
            admin.add(IntegrationPatternVersion(
                id=f"pattern-{name}", pattern_id="pattern",
                profile_version_id="fixture-profile-version", version=version,
                runtime_type="FILE_BASED", direction="OUTBOUND", deliverable_type="CSV",
                qualification_strategy="FILE_EXCHANGE", delivery_method="FILE_EXCHANGE",
                created_by="fixture",
            ))
        await admin.flush()
        admin.add_all([
            PatternBaseline(
                pattern_version_id=f"pattern-{name}", asset_version_id=f"baseline-{name}",
            )
            for name in ("published", "draft")
        ])
        await admin.flush()
        await admin.execute(text(
            "UPDATE integration_pattern_versions SET status = 'PUBLISHED', published_at = now() "
            "WHERE id = 'pattern-published'"
        ))
        await admin.commit()
    async with factory() as client:
        await apply_tenant_context(client, client_ids=["client-a"], subject_id="subject-a")
        assert await client.scalar(text("SELECT id FROM integration_patterns")) == "pattern"
        assert list(await client.scalars(text(
            "SELECT id FROM integration_pattern_versions ORDER BY id"
        ))) == ["pattern-published"]
        assert list(await client.scalars(text(
            "SELECT asset_version_id FROM pattern_baselines ORDER BY asset_version_id"
        ))) == ["baseline-published"]
        result = await client.execute(text(
            "UPDATE integration_pattern_versions SET runtime_type = 'API_INTEGRATION'"
        ))
        assert result.rowcount == 0
    async with factory() as admin:
        await apply_tenant_context(admin, client_ids=[], is_erp_admin=True)
        assert await admin.scalar(text("SELECT count(*) FROM integration_pattern_versions")) == 2
        for assignment in ("runtime_type = 'API_INTEGRATION'", "status = 'DRAFT'"):
            with pytest.raises(DBAPIError, match="Published pattern contracts are immutable"):
                async with admin.begin_nested():
                    await admin.execute(text(
                        f"UPDATE integration_pattern_versions SET {assignment} "
                        "WHERE id = 'pattern-published'"
                    ))
        for statement in (
            "UPDATE pattern_baselines SET asset_version_id = 'baseline-spare'",
            "DELETE FROM pattern_baselines",
        ):
            result = await admin.execute(text(
                statement + " WHERE pattern_version_id = 'pattern-published'"
            ))
            assert result.rowcount == 0
        for statement in (
            "INSERT INTO pattern_baselines (pattern_version_id, asset_version_id) "
            "VALUES ('pattern-published', 'baseline-spare')",
            "UPDATE pattern_baselines SET pattern_version_id = 'pattern-published' "
            "WHERE pattern_version_id = 'pattern-draft'",
        ):
            with pytest.raises(DBAPIError, match="row-level security"):
                async with admin.begin_nested():
                    await admin.execute(text(statement))
        result = await admin.execute(text(
            "UPDATE integration_pattern_versions SET status = 'RETIRED' "
            "WHERE id = 'pattern-published'"
        ))
        assert result.rowcount == 1
        assert list(await admin.scalars(text(
            "SELECT asset_version_id FROM pattern_baselines ORDER BY asset_version_id"
        ))) == ["baseline-draft", "baseline-published"]


@pytest.mark.asyncio
async def test_execution_worker_rechecks_subject_roles_without_expanding_client_scope(
    isolated_runtime,
) -> None:
    owner, runtime = isolated_runtime
    settings = Settings(_env_file=None, app_env="test", auth_mode="oidc")
    async with async_sessionmaker(runtime)() as reviewer:
        await apply_tenant_context(reviewer, client_ids=["client-a"], subject_id="subject-a")
        original = reviewer.info["erpfusion_tenant_context"]
        authority = await subject_identity(reviewer, "subject-b", settings)
        assert authority.roles == frozenset({"platform_admin"})
        assert authority.subject_id == "subject-b"
        assert reviewer.info["erpfusion_tenant_context"] == original
        with pytest.raises(HTTPException, match="execution_actor_inactive"):
            await subject_identity(reviewer, "missing-subject", settings)
        assert reviewer.info["erpfusion_tenant_context"] == original
        await reviewer.commit()
        assert list(await reviewer.scalars(text("SELECT id FROM projects"))) == ["project-a"]
        assert list(await reviewer.scalars(text(
            "SELECT subject_id FROM platform_role_assignments"
        ))) == ["subject-a"]
    async with async_sessionmaker(runtime)() as worker:
        await apply_tenant_context(
            worker, client_ids=["client-a"], client_admin_ids=["client-a"],
            is_execution_worker=True,
        )
        original = worker.info["erpfusion_tenant_context"]
        assert await worker.scalar(text("SELECT count(*) FROM platform_role_assignments")) == 0
        for subject, role in (("subject-a", "erp_configurator"), ("subject-b", "platform_admin")):
            actor = await subject_identity(worker, subject, settings)
            assert actor.roles == frozenset({role})
            assert actor.subject_id == subject
            await worker.commit()
            context = worker.info["erpfusion_tenant_context"]
            assert context == original
            assert context.subject_id is None
            assert context.client_ids == context.client_admin_ids == ("client-a",)
            assert context.is_execution_worker
            assert not context.is_platform_admin and not context.is_erp_admin
            assert list(await worker.scalars(text("SELECT id FROM projects"))) == ["project-a"]
            assert await worker.scalar(text("SELECT count(*) FROM platform_role_assignments")) == 0
        async with async_sessionmaker(owner)() as admin:
            await apply_tenant_context(admin, client_ids=[], is_platform_admin=True)
            await admin.execute(text(
                "UPDATE platform_role_assignments SET status = 'REVOKED' WHERE id = 'role-b'"
            ))
            await admin.commit()
        assert not (await subject_identity(worker, "subject-b", settings)).roles
        result = await worker.execute(text(
            "UPDATE projects SET name = 'forbidden' WHERE id = 'project-b'"
        ))
        assert result.rowcount == 0
