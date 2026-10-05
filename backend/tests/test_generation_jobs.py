"""Durable generation queue claims and stale worker completions."""

import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.generation import process_generation_run
from app.config import Settings
from app.main import create_app
from app.models import (
    Artifact,
    ArtifactVersion,
    Base,
    Client,
    ClientMembership,
    ERPEnvironment,
    ERPInstallation,
    ERPProfile,
    ERPProfileVersion,
    GenerationRun,
    IdentitySubject,
    Project,
    PromptVersion,
    VersionState,
)
from app.security.identity import Identity, get_current_identity
from app.services.project_revisions import revise_inputs, snapshot_inputs
from app.services.workflow import WorkflowEngine


@pytest_asyncio.fixture
async def generation_app(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        subject = IdentitySubject(issuer="https://fixture.test", subject="operator")
        client = Client(client_key="jobs-client", display_name="Jobs Client")
        profile = ERPProfile(
            key="jobs-erp", name="Jobs ERP", display_name="Jobs ERP", vendor="Fixture", active=True
        )
        session.add_all([subject, client, profile])
        await session.flush()
        session.add(
            ClientMembership(client_id=client.id, subject_id=subject.id, role="CLIENT_ADMIN")
        )
        profile_version = ERPProfileVersion(
            profile_id=profile.id,
            version=1,
            status="PUBLISHED",
            supported_artifact_types=["FDD"],
            configuration={
                "workflow": {
                    "stages": [
                        {
                            "type": "FDD",
                            "depends_on": [],
                            "adapter": "generic_json",
                            "task": "Build a functional design.",
                        }
                    ]
                },
                "validation": {"schema_conformity": False},
            },
        )
        session.add(profile_version)
        await session.flush()
        session.add(
            PromptVersion(
                scope="STAGE",
                profile_version_id=profile_version.id,
                name="Functional design",
                stage="FDD",
                content="Produce a functional design from the supplied requirement.",
                version=1,
                status="PUBLISHED",
                variables=[],
            )
        )
        installation = ERPInstallation(
            client_id=client.id,
            erp_profile_id=profile.id,
            installation_key="primary",
            display_name="Primary ERP",
        )
        session.add(installation)
        await session.flush()
        environment = ERPEnvironment(
            client_id=client.id,
            installation_id=installation.id,
            environment_key="sandbox",
            display_name="Sandbox",
        )
        session.add(environment)
        await session.flush()
        project = Project(
            name="Supplier integration",
            business_requirement="Map supplier records to the outbound feed.",
            erp_schema_context={"entities": []},
            erp_profile_id=profile.id,
            erp_profile_version_id=profile_version.id,
            client_id=client.id,
            erp_installation_id=installation.id,
            erp_environment_id=environment.id,
            created_by_subject_id=subject.id,
        )
        session.add(project)
        await session.flush()
        await snapshot_inputs(session, project, subject.id)
        for artifact in await WorkflowEngine(session).initialize_project_artifacts(project):
            artifact.client_id = client.id
        await session.commit()

    actor = Identity(
        user_id="operator",
        issuer="https://fixture.test",
        subject_id=subject.id,
    )

    async def session_dependency():
        async with factory() as session:
            yield session
            await session.commit()

    settings = Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        database_url="sqlite+aiosqlite:///:memory:",
        llm_provider="mock",
        artifact_storage_path=str(tmp_path),
    )
    application = create_app(
        settings=settings, engine=engine, session_dependency=session_dependency
    )
    application.dependency_overrides[get_current_identity] = lambda: actor
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as http:
        yield http, factory, project.id, client.id, subject.id, settings
    await engine.dispose()


class ResultProvider:
    model = "fixture-model"

    def __init__(self, result=None, error=None):
        self.result = result or {"design": "fixture output"}
        self.error = error
        self.calls = 0

    async def generate_json(self, _request):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class BlockingProvider(ResultProvider):
    def __init__(self):
        super().__init__({"design": "old input result"})
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate_json(self, request):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return self.result


async def enqueue(http, project_id):
    response = await http.post(f"/api/projects/{project_id}/generate", json={"stage": "FDD"})
    assert response.status_code == 202, response.text
    return response.json()


async def run_job(factory, run_id, provider, settings):
    async with factory() as session:
        return await process_generation_run(session, run_id, settings=settings, provider=provider)


@pytest.mark.asyncio
async def test_job_is_queued_then_worker_completes_artifact(generation_app):
    http, factory, project_id, _, _, settings = generation_app
    queued = await enqueue(http, project_id)
    assert queued["status"] == "QUEUED"

    result = await run_job(factory, queued["id"], ResultProvider(), settings)
    assert result["status"] == "COMPLETED"
    assert result["artifact_version_id"]
    async with factory() as session:
        version = await session.get(ArtifactVersion, result["artifact_version_id"])
        artifact = await session.scalar(select(Artifact).where(Artifact.project_id == project_id))
        assert version.state == VersionState.PENDING_HUMAN_REVIEW
        assert version.content == {"design": "fixture output"}
        assert artifact.current_version == 1


@pytest.mark.asyncio
async def test_workflow_api_exposes_unresolved_assessment_blockers(generation_app):
    http, factory, project_id, _, _, settings = generation_app
    queued = await enqueue(http, project_id)
    await run_job(
        factory, queued["id"], ResultProvider({"missing_information": ["Schema"]}), settings
    )
    response = await http.get(f"/api/projects/{project_id}/workflow")
    assert response.status_code == 200
    assert response.json()["stages"][0]["approval_blockers"] == ["Schema"]


@pytest.mark.asyncio
async def test_slow_stale_result_does_not_replace_or_unlock_new_queued_job(generation_app):
    http, factory, project_id, _, subject_id, settings = generation_app
    first = await enqueue(http, project_id)
    provider = BlockingProvider()
    worker = asyncio.create_task(run_job(factory, first["id"], provider, settings))
    await asyncio.wait_for(provider.started.wait(), timeout=2)

    async with factory() as session:
        project = await session.get(Project, project_id)
        await revise_inputs(
            session,
            project,
            subject_id,
            requirement="Use the revised supplier identifier in the outbound feed.",
            expected_requirement_version=1,
        )
        await session.commit()

    second = await enqueue(http, project_id)
    assert second["status"] == "QUEUED"
    provider.release.set()
    stale = await asyncio.wait_for(worker, timeout=2)

    assert stale["status"] == "STALE"
    async with factory() as session:
        old_run = await session.get(GenerationRun, first["id"])
        new_run = await session.get(GenerationRun, second["id"])
        artifact = await session.scalar(select(Artifact).where(Artifact.project_id == project_id))
        versions = list(
            (
                await session.scalars(
                    select(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact.id)
                )
            ).all()
        )
        assert old_run.status == "STALE"
        assert new_run.status == "QUEUED"
        assert new_run.resolved_context["requirement"].startswith("Use the revised")
        assert artifact.gate_status.value == "GENERATING"
        assert artifact.current_version == 0
        assert versions == []


@pytest.mark.asyncio
async def test_duplicate_claim_invokes_provider_once(generation_app):
    http, factory, project_id, _, _, settings = generation_app
    queued = await enqueue(http, project_id)
    provider = BlockingProvider()
    first_claim = asyncio.create_task(run_job(factory, queued["id"], provider, settings))
    await asyncio.wait_for(provider.started.wait(), timeout=2)
    duplicate_claim = await run_job(factory, queued["id"], provider, settings)
    assert duplicate_claim["status"] == "RUNNING"
    provider.release.set()
    completed = await asyncio.wait_for(first_claim, timeout=2)
    assert completed["status"] == "COMPLETED"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_provider_failure_records_safe_error_and_releases_gate(generation_app):
    http, factory, project_id, _, _, settings = generation_app
    queued = await enqueue(http, project_id)
    result = await run_job(
        factory,
        queued["id"],
        ResultProvider(error=RuntimeError("SECRET provider payload")),
        settings,
    )
    assert result["status"] == "FAILED"
    assert result["error_code"] == "GENERATION_FAILED"
    assert "SECRET" not in str(result)
    async with factory() as session:
        artifact = await session.scalar(select(Artifact).where(Artifact.project_id == project_id))
        run = await session.get(GenerationRun, queued["id"])
        assert artifact.gate_status.value == "LOCKED"
        assert run.error_code == "GENERATION_FAILED"
