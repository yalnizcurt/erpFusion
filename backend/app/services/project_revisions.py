"""One revision/invalidation path for edits and document extraction."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ERPProfileVersion, GenerationRun, Project, ProjectInputRevision


async def lock_project(db: AsyncSession, project: Project) -> Project:
    return (
        await db.execute(
            select(Project)
            .where(Project.id == project.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def snapshot_inputs(db: AsyncSession, project: Project, actor: str | None) -> None:
    exists = await db.scalar(
        select(ProjectInputRevision.id).where(
            ProjectInputRevision.project_id == project.id,
            ProjectInputRevision.revision == project.workflow_revision,
        )
    )
    if exists:
        return
    db.add(
        ProjectInputRevision(
            project_id=project.id,
            client_id=project.client_id,
            revision=project.workflow_revision,
            created_by_subject_id=actor,
            snapshot={
                "requirement": project.business_requirement,
                "requirement_version": project.requirement_version,
                "schema_context": project.erp_schema_context,
                "schema_context_version": project.schema_context_version,
                "profile_version_id": project.erp_profile_version_id,
                "integration_pattern_version_id": project.integration_pattern_version_id,
            },
        )
    )
    await db.flush()


async def revise_inputs(
    db: AsyncSession,
    project: Project,
    actor: str | None,
    *,
    requirement: str | None = None,
    context: dict | None = None,
    expected_requirement_version: int | None = None,
    expected_schema_context_version: int | None = None,
    profile_version: ERPProfileVersion | None = None,
    pattern_version_id: str | None = None,
) -> None:
    from app.services.workflow import WorkflowEngine

    await lock_project(db, project)
    if (
        expected_requirement_version is not None
        and expected_requirement_version != project.requirement_version
    ):
        raise HTTPException(409, "The requirements changed. Reload before saving your revision.")
    if (
        expected_schema_context_version is not None
        and expected_schema_context_version != project.schema_context_version
    ):
        raise HTTPException(409, "The context changed. Reload before saving your revision.")
    await snapshot_inputs(db, project, actor)
    if requirement is not None and requirement != project.business_requirement:
        project.business_requirement = requirement
        project.requirement_version += 1
    if context is not None and context != project.erp_schema_context:
        project.erp_schema_context = context
        project.schema_context_version += 1
    if profile_version is not None:
        project.erp_profile_id = profile_version.profile_id
        project.erp_profile_version_id = profile_version.id
    if pattern_version_id is not None:
        project.integration_pattern_version_id = pattern_version_id
    project.workflow_revision += 1
    project.last_activity_at = datetime.now(UTC)
    project.workflow_status = "DRAFT"
    await WorkflowEngine(db, actor_subject_id=actor).invalidate_all(project.id)
    await snapshot_inputs(db, project, actor)


async def stale_jobs(db: AsyncSession, project_id: str, stages: set[str]) -> None:
    jobs = (
        await db.scalars(
            select(GenerationRun).where(
                GenerationRun.project_id == project_id,
                GenerationRun.artifact_type.in_(stages),
                GenerationRun.status.in_(["QUEUED", "RUNNING"]),
            )
        )
    ).all()
    for job in jobs:
        job.status = "STALE"
        job.error_code = "UPSTREAM_REVISION_CHANGED"
        job.completed_at = datetime.now(UTC)
