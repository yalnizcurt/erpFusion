"""Durable database worker; scoped to explicitly provisioned client IDs.

Run independently of the API so navigation/restarts cannot lose queued jobs.
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.generation import process_generation_run
from app.config import get_settings
from app.database import create_database_engine, create_session_factory
from app.models import Artifact, GateStatus, GenerationRun, Project
from app.security.tenant_context import apply_tenant_context
from app.services.project_revisions import lock_project
from app.services.workflow import WorkflowEngine


async def expire_interrupted_run(db: AsyncSession, run_id: str, cutoff: datetime) -> bool:
    """Fail one old RUNNING run without releasing a gate now owned by newer work."""
    run = await db.scalar(
        select(GenerationRun)
        .where(GenerationRun.id == run_id)
        .execution_options(populate_existing=True)
    )
    if run is None:
        return False
    project = await db.get(Project, run.project_id)
    if project is None:
        return False
    project = await lock_project(db, project)
    await db.refresh(run)
    started_at = run.started_at
    if started_at is None:
        return False
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    if run.status != "RUNNING" or started_at >= cutoff:
        return False

    owns_slot = False
    artifact = None
    provenance = run.provenance or {}
    artifact_id = provenance.get("artifact_id")
    if (
        artifact_id
        and project.workflow_revision == provenance.get("workflow_revision")
        and provenance.get("input_bindings") is not None
    ):
        artifact = await db.get(Artifact, artifact_id)
        if (
            artifact
            and artifact.project_id == project.id
            and artifact.client_id == project.client_id
            and artifact.artifact_type == run.artifact_type
            and artifact.gate_status == GateStatus.GENERATING
            and artifact.current_version == provenance.get("artifact_previous_version")
        ):
            current_bindings = await WorkflowEngine(db).current_bindings(
                project.id, run.artifact_type
            )
            owns_slot = provenance["input_bindings"] == current_bindings

    run.status = "FAILED"
    run.error_code = "WORKER_INTERRUPTED"
    run.completed_at = datetime.now(UTC)
    if owns_slot and artifact is not None:
        artifact.gate_status = GateStatus.LOCKED
        project.workflow_status = "BLOCKED"
    return True


async def work(*, clients: list[str], once: bool) -> None:
    settings = get_settings()
    if settings.is_production and not clients:
        raise ValueError("Provision the worker's permitted client scope")
    if settings.is_production and settings.configuration_issues():
        raise ValueError("Production worker configuration is not ready")
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    try:
        while True:
            async with factory() as db:
                await apply_tenant_context(
                    db,
                    client_ids=clients,
                    is_platform_admin=not settings.is_production and not clients,
                )
                # Crashed jobs are visible failures, not automatic duplicate LLM calls.
                cutoff = datetime.now(UTC) - timedelta(minutes=15)
                expired_ids = (
                    await db.scalars(
                        select(GenerationRun.id).where(
                            GenerationRun.status == "RUNNING",
                            GenerationRun.started_at < cutoff,
                        )
                    )
                ).all()
                for run_id in expired_ids:
                    await expire_interrupted_run(db, run_id, cutoff)
                await db.commit()
                job = await db.scalar(
                    select(GenerationRun.id)
                    .where(GenerationRun.status == "QUEUED")
                    .order_by(GenerationRun.created_at, GenerationRun.id)
                    .limit(1)
                )
                if job:
                    await process_generation_run(db, job, settings=settings)
            if once:
                return
            # ponytail: DB polling serves the initial worker; add SQS dispatch when
            # the cloud worker deployment replaces this bounded local runner.
            await asyncio.sleep(1)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Process committed HighStudio generation jobs")
    parser.add_argument("--client-id", action="append", default=[])
    parser.add_argument("--once", action="store_true")
    arguments = parser.parse_args()
    asyncio.run(work(clients=arguments.client_id, once=arguments.once))


if __name__ == "__main__":
    main()
