"""Expired worker jobs release only the generation slot they still own."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.cli.generation_worker import expire_interrupted_run
from app.models import (
    Artifact,
    Base,
    Client,
    ERPProfile,
    ERPProfileVersion,
    GateStatus,
    GenerationRun,
    Project,
)
from app.services.workflow import WorkflowEngine


@pytest_asyncio.fixture
async def recovery_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        client = Client(client_key="worker-recovery", display_name="Worker Recovery")
        profile = ERPProfile(
            key="worker-recovery", name="Worker Recovery", vendor="Fixture", active=True
        )
        session.add_all([client, profile])
        await session.flush()
        profile_version = ERPProfileVersion(
            profile_id=profile.id,
            version=1,
            status="PUBLISHED",
            supported_artifact_types=["FDD"],
            configuration={"workflow": {"stages": [{"type": "FDD", "depends_on": []}]}},
        )
        session.add(profile_version)
        await session.flush()
        project = Project(
            name="Worker recovery fixture",
            business_requirement="Map supplier records to an outbound feed.",
            erp_schema_context={},
            client_id=client.id,
            erp_profile_id=profile.id,
            erp_profile_version_id=profile_version.id,
            workflow_status="GENERATING",
        )
        session.add(project)
        await session.flush()
        artifact = Artifact(
            project_id=project.id,
            client_id=client.id,
            artifact_type="FDD",
            current_version=0,
            gate_status=GateStatus.GENERATING,
        )
        session.add(artifact)
        await session.flush()
        await session.commit()
        yield factory, project.id, artifact.id, profile_version.id, client.id
    await engine.dispose()


async def add_run(
    session,
    *,
    project,
    artifact_id,
    profile_version_id,
    client_id,
    status="RUNNING",
    provenance=None,
):
    bindings = await WorkflowEngine(session).current_bindings(project.id, "FDD")
    run = GenerationRun(
        project_id=project.id,
        client_id=client_id,
        artifact_type="FDD",
        profile_version_id=profile_version_id,
        model="fixture-model",
        status=status,
        started_at=datetime.now(UTC) - timedelta(minutes=20),
        provenance=provenance
        or {
            "artifact_id": artifact_id,
            "artifact_previous_version": 0,
            "workflow_revision": project.workflow_revision,
            "input_bindings": bindings,
        },
    )
    session.add(run)
    await session.flush()
    return run, bindings


@pytest.mark.asyncio
async def test_expired_active_run_fails_and_releases_its_gate(recovery_db):
    factory, project_id, artifact_id, profile_version_id, client_id = recovery_db
    async with factory() as session:
        project = await session.get(Project, project_id)
        run, _ = await add_run(
            session,
            project=project,
            artifact_id=artifact_id,
            profile_version_id=profile_version_id,
            client_id=client_id,
        )
        run_id = run.id
        await session.commit()

    async with factory() as session:
        assert await expire_interrupted_run(
            session, run_id, datetime.now(UTC) - timedelta(minutes=15)
        )
        await session.commit()

    async with factory() as session:
        run = await session.get(GenerationRun, run_id)
        project = await session.get(Project, project_id)
        artifact = await session.get(Artifact, artifact_id)
        assert run.status == "FAILED" and run.error_code == "WORKER_INTERRUPTED"
        assert run.completed_at is not None
        assert artifact.gate_status == GateStatus.LOCKED
        assert project.workflow_status == "BLOCKED"


@pytest.mark.asyncio
async def test_stale_and_terminal_jobs_cannot_reset_new_generation(recovery_db):
    factory, project_id, artifact_id, profile_version_id, client_id = recovery_db
    async with factory() as session:
        project = await session.get(Project, project_id)
        stale, provenance = await add_run(
            session,
            project=project,
            artifact_id=artifact_id,
            profile_version_id=profile_version_id,
            client_id=client_id,
        )
        stale.provenance = {**provenance, "workflow_revision": project.workflow_revision - 1}
        queued, _ = await add_run(
            session,
            project=project,
            artifact_id=artifact_id,
            profile_version_id=profile_version_id,
            client_id=client_id,
            status="QUEUED",
        )
        completed, _ = await add_run(
            session,
            project=project,
            artifact_id=artifact_id,
            profile_version_id=profile_version_id,
            client_id=client_id,
            status="COMPLETED",
        )
        recent, _ = await add_run(
            session,
            project=project,
            artifact_id=artifact_id,
            profile_version_id=profile_version_id,
            client_id=client_id,
        )
        recent.started_at = datetime.now(UTC)
        ids = stale.id, queued.id, completed.id, recent.id
        await session.commit()

    cutoff = datetime.now(UTC) - timedelta(minutes=15)
    async with factory() as session:
        assert await expire_interrupted_run(session, ids[0], cutoff)
        assert not await expire_interrupted_run(session, ids[1], cutoff)
        assert not await expire_interrupted_run(session, ids[2], cutoff)
        assert not await expire_interrupted_run(session, ids[3], cutoff)
        await session.commit()

    async with factory() as session:
        stale, queued, completed, recent = [
            await session.get(GenerationRun, run_id) for run_id in ids
        ]
        project = await session.get(Project, project_id)
        artifact = await session.get(Artifact, artifact_id)
        assert stale.status == "FAILED"
        assert queued.status == "QUEUED" and completed.status == "COMPLETED"
        assert recent.status == "RUNNING"
        assert artifact.gate_status == GateStatus.GENERATING
        assert project.workflow_status == "GENERATING"


@pytest.mark.asyncio
async def test_changed_current_bindings_keep_new_generation_gate_locked(recovery_db):
    factory, project_id, artifact_id, profile_version_id, client_id = recovery_db
    async with factory() as session:
        project = await session.get(Project, project_id)
        old_run, old_bindings = await add_run(
            session,
            project=project,
            artifact_id=artifact_id,
            profile_version_id=profile_version_id,
            client_id=client_id,
        )
        old_run.provenance = {
            **old_run.provenance,
            "input_bindings": {**old_bindings, "requirement_version": 0},
        }
        project.requirement_version += 1
        new_run, new_bindings = await add_run(
            session,
            project=project,
            artifact_id=artifact_id,
            profile_version_id=profile_version_id,
            client_id=client_id,
            status="QUEUED",
        )
        assert new_bindings["requirement_version"] == project.requirement_version
        old_run_id = old_run.id
        new_run_id = new_run.id
        await session.commit()

    async with factory() as session:
        assert await expire_interrupted_run(
            session, old_run_id, datetime.now(UTC) - timedelta(minutes=15)
        )
        await session.commit()

    async with factory() as session:
        old_run = await session.get(GenerationRun, old_run_id)
        new_run = await session.get(GenerationRun, new_run_id)
        project = await session.get(Project, project_id)
        artifact = await session.get(Artifact, artifact_id)
        assert old_run.status == "FAILED"
        assert new_run.status == "QUEUED"
        assert artifact.gate_status == GateStatus.GENERATING
        assert project.workflow_status == "GENERATING"
