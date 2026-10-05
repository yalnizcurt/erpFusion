"""Phase 1 identity, client isolation, and onboarding contracts."""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings
from app.main import create_app
from app.models import (
    AdminAuditEvent,
    Artifact,
    ArtifactVersion,
    AuditEntry,
    Base,
    Client,
    ERPProfile,
    ERPProfileVersion,
    FeedbackGuidance,
    GateStatus,
    Project,
    PromptVersion,
    VersionState,
)
from app.security.access import get_authorized_project
from app.security.identity import Identity
from app.services.prompt_compiler import PromptCompiler


@pytest_asyncio.fixture
async def ownership_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


def ownership_settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        auth_mode="development",
        database_url="sqlite+aiosqlite:///:memory:",
        llm_provider="mock",
        artifact_storage_path=str(tmp_path),
        dev_identity_user_id="platform-user",
        dev_identity_roles=["platform_admin"],
    )


async def _seed_profile(engine: AsyncEngine) -> str:
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        profile = ERPProfile(
            key="demo-phase1",
            name="Demo ERP",
            display_name="Demo ERP",
            vendor="Demo",
            product_version="1",
            active=True,
            status="PUBLISHED",
            configuration={"workflow": {"stages": []}},
        )
        session.add(profile)
        await session.flush()
        version = ERPProfileVersion(
            profile_id=profile.id,
            version=1,
            status="PUBLISHED",
            supported_artifact_types=[],
            configuration={"workflow": {"stages": []}},
            created_by="fixture",
            updated_by="fixture",
        )
        session.add(version)
        await session.commit()
        return profile.id


@pytest.mark.asyncio
async def test_client_installation_environment_and_project_isolation(ownership_engine, tmp_path):
    profile_id = await _seed_profile(ownership_engine)
    session_factory = async_sessionmaker(ownership_engine, expire_on_commit=False)

    async def session_dependency() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app = create_app(
        settings=ownership_settings(tmp_path),
        engine=ownership_engine,
        session_dependency=session_dependency,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"X-Dev-User-Id": "platform-user", "X-Dev-Roles": "platform_admin"}
        created = await client.post(
            "/api/clients",
            headers=headers,
            json={"client_key": "client-a", "display_name": "Client A"},
        )
        assert created.status_code == 201, created.text
        client_a = created.json()
        client_id = client_a["id"]

        membership = await client.post(
            f"/api/clients/{client_id}/memberships",
            headers=headers,
            json={"subject_id": "user-a", "role": "CLIENT_ADMIN"},
        )
        assert membership.status_code == 201, membership.text

        installation = await client.post(
            f"/api/clients/{client_id}/installations",
            headers={"X-Dev-User-Id": "user-a", "X-Dev-Roles": ""},
            json={
                "installation_key": "demo-1",
                "display_name": "Demo installation",
                "erp_profile_id": profile_id,
            },
        )
        assert installation.status_code == 201, installation.text
        installation_id = installation.json()["id"]
        environment = await client.post(
            f"/api/clients/{client_id}/installations/{installation_id}/environments",
            headers={"X-Dev-User-Id": "user-a", "X-Dev-Roles": ""},
            json={
                "environment_key": "sandbox",
                "display_name": "Sandbox",
                "environment_type": "SANDBOX",
            },
        )
        assert environment.status_code == 201, environment.text

        version_id = None
        async with session_factory() as session:
            from sqlalchemy import select

            version_id = (await session.execute(select(ERPProfileVersion.id))).scalar_one()
        project = await client.post(
            "/api/projects",
            headers={"X-Dev-User-Id": "user-a", "X-Dev-Roles": ""},
            json={
                "name": "Client A request",
                "business_requirement": "A sufficiently detailed requirement for isolation.",
                "erp_schema_context": {"entities": []},
                "client_id": client_id,
                "erp_installation_id": installation_id,
                "erp_environment_id": environment.json()["id"],
                "erp_profile_version_id": version_id,
            },
        )
        assert project.status_code == 201, project.text
        project_id = project.json()["id"]

        foreign = await client.get(
            f"/api/projects/{project_id}",
            headers={"X-Dev-User-Id": "user-b", "X-Dev-Roles": ""},
        )
        assert foreign.status_code == 404
        own = await client.get(
            f"/api/projects/{project_id}",
            headers={"X-Dev-User-Id": "user-a", "X-Dev-Roles": ""},
        )
        assert own.status_code == 200
        listed = await client.get(
            "/api/projects?limit=1&search=Client%20A",
            headers={"X-Dev-User-Id": "user-a", "X-Dev-Roles": ""},
        )
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert [item["id"] for item in listed.json()["projects"]] == [project_id]
        assert listed.json()["next_offset"] is None
        for field in ["name", "business_requirement", "erp_schema_context"]:
            invalid_update = await client.patch(
                f"/api/projects/{project_id}", headers=headers, json={field: None}
            )
            assert invalid_update.status_code == 422, field
        archived = await client.delete(f"/api/projects/{project_id}", headers=headers)
        assert archived.status_code == 204
        assert (await client.get(f"/api/projects/{project_id}", headers=headers)).status_code == 200
        assert (
            await client.patch(
                f"/api/projects/{project_id}",
                headers=headers,
                json={"name": "Cannot modify archive"},
            )
        ).status_code == 409
        async with session_factory() as session:
            retained = await session.get(Project, project_id)
            assert retained.archived_at is not None
            events = (await session.execute(select(AdminAuditEvent))).scalars().all()
            assert {
                "CLIENT_CREATED",
                "MEMBERSHIP_ASSIGNED",
                "INSTALLATION_CREATED",
                "ENVIRONMENT_CREATED",
                "REQUEST_CREATED",
                "REQUEST_ARCHIVED",
            } <= {item.action for item in events}
            assert all(item.actor_subject_id for item in events)
            assert all(item.client_id == client_id for item in events)


@pytest.mark.asyncio
async def test_unowned_legacy_project_is_quarantined_for_real_identity(ownership_engine):
    session_factory = async_sessionmaker(ownership_engine, expire_on_commit=False)
    async with session_factory() as session:
        project = Project(
            name="Legacy", business_requirement="Legacy requirement", erp_schema_context={}
        )
        session.add(project)
        await session.commit()
        with pytest.raises(Exception) as error:
            await get_authorized_project(
                project.id,
                session,
                Identity(user_id="oidc-user", provider="oidc", is_fixture=False),
            )
        assert getattr(error.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_client_roles_review_identity_and_resource_id_isolation(ownership_engine, tmp_path):
    profile_id = await _seed_profile(ownership_engine)
    factory = async_sessionmaker(ownership_engine, expire_on_commit=False)

    async def sessions():
        async with factory() as db:
            try:
                yield db
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    app = create_app(
        settings=ownership_settings(tmp_path), engine=ownership_engine, session_dependency=sessions
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        admin = {"X-Dev-User-Id": "platform-user", "X-Dev-Roles": "platform_admin"}
        owner = await http.post(
            "/api/clients",
            headers=admin,
            json={"client_key": "role-client", "display_name": "Role client"},
        )
        assert owner.status_code == 201, owner.text
        client_id = owner.json()["id"]
        for user, role in [("consultant", "CONSULTANT"), ("functional", "FUNCTIONAL_REVIEWER")]:
            assigned = await http.post(
                f"/api/clients/{client_id}/memberships",
                headers=admin,
                json={"subject_id": user, "role": role},
            )
            assert assigned.status_code == 201, assigned.text
        consultant = {"X-Dev-User-Id": "consultant", "X-Dev-Roles": ""}
        reviewer = {"X-Dev-User-Id": "functional", "X-Dev-Roles": ""}
        outsider = {"X-Dev-User-Id": "unassigned", "X-Dev-Roles": ""}
        config_editor = {"X-Dev-User-Id": "editor", "X-Dev-Roles": "platform_erp_configurator"}
        install_body = {
            "installation_key": "demo",
            "display_name": "Demo",
            "erp_profile_id": profile_id,
        }
        assert (
            await http.post(
                f"/api/clients/{client_id}/installations", headers=consultant, json=install_body
            )
        ).status_code == 403
        assert (
            await http.post(
                "/api/clients",
                headers=config_editor,
                json={"client_key": "unauthorized", "display_name": "No"},
            )
        ).status_code == 403
        assert (
            await http.post(
                f"/api/erp-profiles/{profile_id}/versions/1/publish", headers=config_editor
            )
        ).status_code == 403
        installed = await http.post(
            f"/api/clients/{client_id}/installations", headers=admin, json=install_body
        )
        assert installed.status_code == 201, installed.text
        assert (
            await http.post(
                f"/api/clients/{client_id}/installations", headers=admin, json=install_body
            )
        ).status_code == 409
        env = await http.post(
            f"/api/clients/{client_id}/installations/{installed.json()['id']}/environments",
            headers=admin,
            json={"environment_key": "sandbox", "display_name": "Sandbox"},
        )
        assert env.status_code == 201, env.text
        async with factory() as db:
            profile_version_id = (await db.execute(select(ERPProfileVersion.id))).scalar_one()
        request_body = {
            "name": "Reviewed request",
            "business_requirement": "Review this detailed request.",
            "erp_schema_context": {},
            "client_id": client_id,
            "erp_installation_id": installed.json()["id"],
            "erp_environment_id": env.json()["id"],
            "erp_profile_version_id": profile_version_id,
        }
        created = await http.post("/api/projects", headers=consultant, json=request_body)
        assert created.status_code == 201, created.text
        project_id = created.json()["id"]
        async with factory() as db:
            artifact = Artifact(
                project_id=project_id,
                client_id=client_id,
                artifact_type="CONTEXT_ANALYSIS",
                current_version=1,
                gate_status=GateStatus.PENDING_REVIEW,
            )
            db.add(artifact)
            await db.flush()
            version = ArtifactVersion(
                artifact_id=artifact.id,
                client_id=client_id,
                version_number=1,
                state=VersionState.PENDING_HUMAN_REVIEW,
                content={"summary": "Reviewed fixture"},
            )
            db.add(version)
            await db.commit()
            artifact_id = artifact.id
        review_path = f"/api/reviews/artifacts/{artifact_id}/versions/1/review"
        assert (
            await http.post(review_path, headers=consultant, json={"decision": "APPROVED"})
        ).status_code == 403
        assert (
            await http.post(
                review_path,
                headers=reviewer,
                json={"decision": "APPROVED", "reviewer": "someone-else"},
            )
        ).status_code == 403
        approved = await http.post(review_path, headers=reviewer, json={"decision": "APPROVED"})
        assert approved.status_code == 200, approved.text
        assert approved.json()["reviewer"] == "functional"
        for path in [
            f"/api/projects/{project_id}",
            f"/api/projects/{project_id}/artifacts",
            f"/api/projects/{project_id}/workflow",
            f"/api/projects/{project_id}/traceability",
            f"/api/projects/{project_id}/feedback",
            f"/api/artifacts/{artifact_id}",
            f"/api/artifacts/{artifact_id}/versions",
            f"/api/artifacts/{artifact_id}/versions/1",
        ]:
            assert (await http.get(path, headers=outsider)).status_code == 404, path
        assert (await http.get("/api/projects", headers=outsider)).json()["total"] == 0
        assert (
            await http.post(
                f"/api/projects/{project_id}/generate",
                headers=reviewer,
                json={"stage": "CONTEXT_ANALYSIS"},
            )
        ).status_code == 403
        async with factory() as db:
            record = (await db.execute(select(ArtifactVersion))).scalar_one()
            assert record.reviewer_subject_id
            audits = (await db.execute(select(AuditEntry))).scalars().all()
            assert audits and all(item.client_id == client_id for item in audits)
            assert all(item.actor_subject_id == record.reviewer_subject_id for item in audits)


@pytest.mark.asyncio
async def test_malformed_child_records_and_feedback_are_quarantined(ownership_engine, tmp_path):
    """Defense in depth also protects reads of unreconciled legacy child records."""
    profile_id = await _seed_profile(ownership_engine)
    factory = async_sessionmaker(ownership_engine, expire_on_commit=False)

    async def sessions():
        async with factory() as db:
            try:
                yield db
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async with factory() as db:
        own = Client(client_key="own", display_name="Own client")
        other = Client(client_key="other", display_name="Other client")
        db.add_all([own, other])
        await db.flush()
        profile = (await db.execute(select(ERPProfileVersion))).scalar_one()
        profile.configuration = {
            "workflow": {"stages": [{"type": "CONTEXT_ANALYSIS", "review_role": "TESTER"}]}
        }
        project = Project(
            name="Scoped request",
            client_id=own.id,
            erp_profile_id=profile_id,
            erp_profile_version_id=profile.id,
            business_requirement="Identify the scoped invoice mappings.",
            erp_schema_context={},
        )
        db.add(project)
        await db.flush()
        good = Artifact(project_id=project.id, client_id=own.id, artifact_type="CONTEXT_ANALYSIS")
        bad = Artifact(project_id=project.id, client_id=other.id, artifact_type="FOREIGN_STAGE")
        db.add_all([good, bad])
        await db.flush()
        good_version = ArtifactVersion(
            artifact_id=good.id, client_id=own.id, version_number=1, content={"safe": True}
        )
        bad_version = ArtifactVersion(
            artifact_id=good.id,
            client_id=other.id,
            version_number=2,
            content={"foreign": "private"},
        )
        guidance = FeedbackGuidance(
            project_id=project.id,
            client_id=own.id,
            scope="PROJECT",
            content="SCOPED_INVOICE_GUIDANCE for invoice mappings",
            stage="CONTEXT_ANALYSIS",
        )
        shared = FeedbackGuidance(
            profile_id=profile_id, scope="ERP", content="SHARED_INVOICE_GUIDANCE"
        )
        db.add_all(
            [
                good_version,
                bad_version,
                guidance,
                shared,
                FeedbackGuidance(
                    project_id=project.id,
                    client_id=other.id,
                    scope="PROJECT",
                    content="FOREIGN_PROJECT_GUIDANCE",
                ),
                FeedbackGuidance(
                    project_id=project.id,
                    client_id=other.id,
                    profile_id=profile_id,
                    scope="ERP",
                    content="MALFORMED_SHARED_GUIDANCE",
                ),
                PromptVersion(
                    profile_version_id=profile.id,
                    scope="STAGE",
                    stage="CONTEXT_ANALYSIS",
                    name="Scoped analysis",
                    content="Analyze invoice mappings",
                    version=1,
                    status="PUBLISHED",
                    variables=[],
                ),
            ]
        )
        await db.flush()
        db.add_all(
            [
                AdminAuditEvent(
                    actor="foreign-client-reviewer",
                    client_id=other.id,
                    action="FEEDBACK_PROMOTED",
                    entity_type="FeedbackGuidance",
                    entity_id=shared.id,
                    details={"source_feedback_id": "PRIVATE_CLIENT_SOURCE"},
                ),
                AdminAuditEvent(
                    actor="registry-publisher",
                    action="PROFILE_PUBLISHED",
                    entity_type="ERPProfile",
                    entity_id=profile_id,
                    details={},
                ),
            ]
        )
        await db.commit()
        compiled = await PromptCompiler(db).compile(project, "CONTEXT_ANALYSIS", "Analyze", {})
        assert "SCOPED_INVOICE_GUIDANCE" in compiled.system_prompt
        assert "FOREIGN_PROJECT_GUIDANCE" not in compiled.system_prompt
        assert "MALFORMED_SHARED_GUIDANCE" not in compiled.system_prompt
        project_id, good_id, bad_id, guidance_id = project.id, good.id, bad.id, guidance.id

    app = create_app(
        settings=ownership_settings(tmp_path), engine=ownership_engine, session_dependency=sessions
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        admin = {"X-Dev-User-Id": "platform-user", "X-Dev-Roles": "platform_admin"}
        editor = {"X-Dev-User-Id": "editor", "X-Dev-Roles": "platform_erp_configurator"}
        artifact_list = await http.get(f"/api/projects/{project_id}/artifacts", headers=admin)
        assert [item["id"] for item in artifact_list.json()] == [good_id]
        version_list = await http.get(f"/api/artifacts/{good_id}/versions", headers=admin)
        assert [item["version_number"] for item in version_list.json()] == [1]
        for path in [f"/api/artifacts/{bad_id}", f"/api/artifacts/{good_id}/versions/2"]:
            assert (await http.get(path, headers=admin)).status_code == 404
        review = await http.post(
            f"/api/reviews/artifacts/{good_id}/versions/2/review",
            headers=admin,
            json={"decision": "APPROVED"},
        )
        assert review.status_code == 404
        feedback = await http.get(f"/api/projects/{project_id}/feedback", headers=admin)
        assert [item["id"] for item in feedback.json()] == [guidance_id]
        promotion = await http.post(
            f"/api/projects/{project_id}/feedback/{guidance_id}/promote",
            headers=editor,
            json={"scope": "ERP", "profile_id": profile_id},
        )
        assert promotion.status_code == 403
        registry_audit = await http.get(
            f"/api/erp-profiles/{profile_id}/versions/1/audit", headers=editor
        )
        assert registry_audit.status_code == 200
        assert [item["actor"] for item in registry_audit.json()] == ["registry-publisher"]
        workflow = await http.get(f"/api/projects/{project_id}/workflow", headers=admin)
        assert workflow.json()["stages"][0]["review_role"] == "TESTER"


@pytest.mark.asyncio
@pytest.mark.parametrize("unusable_identity", ["suspended", "foreign_issuer"])
async def test_last_usable_platform_admin_cannot_be_revoked(
    ownership_engine, tmp_path, unusable_identity
):
    from app.models import IdentitySubject, PlatformRoleAssignment

    factory = async_sessionmaker(ownership_engine, expire_on_commit=False)

    async def sessions():
        async with factory() as db:
            try:
                yield db
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async with factory() as db:
        active = IdentitySubject(issuer="development", subject="platform-user")
        suspended = IdentitySubject(
            issuer="old-provider" if unusable_identity == "foreign_issuer" else "development",
            subject="disabled",
            status="ACTIVE" if unusable_identity == "foreign_issuer" else "SUSPENDED",
        )
        db.add_all([active, suspended])
        await db.flush()
        assignment = PlatformRoleAssignment(subject_id=active.id, role="PLATFORM_ADMIN")
        db.add_all(
            [
                assignment,
                PlatformRoleAssignment(subject_id=suspended.id, role="PLATFORM_ADMIN"),
            ]
        )
        await db.commit()
        assignment_id = assignment.id
    app = create_app(
        settings=ownership_settings(tmp_path), engine=ownership_engine, session_dependency=sessions
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        result = await http.delete(
            f"/api/identity/platform-roles/{assignment_id}",
            headers={"X-Dev-User-Id": "platform-user", "X-Dev-Roles": "platform_admin"},
        )
        assert result.status_code == 409
    async with factory() as db:
        assert (await db.get(PlatformRoleAssignment, assignment_id)).status == "ACTIVE"
