"""
HighStudio — Project API Routes

CRUD operations for projects. Creating a project automatically initializes
all artifact records in LOCKED state via the workflow engine.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from app.database import get_db
from app.models import (
    Artifact,
    ArtifactVersion,
    Client,
    ERPEnvironment,
    ERPInstallation,
    ERPProfile,
    ERPProfileVersion,
    GateStatus,
    Project,
    ProjectStatus,
    ValidationResult,
    VersionState,
)
from app.models.connection import ERPConnection
from app.models.engineering import PackageCandidate, PackageRelease, SandboxEvidence
from app.schemas import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from app.security.access import (
    ensure_client_access,
    get_authorized_project,
    identity_client_ids,
    resolved_identity,
)
from app.security.identity import Identity, get_current_identity
from app.services.ownership_audit import actor_subject, record_ownership_event
from app.services.packages import json_bytes, sha256
from app.services.project_revisions import lock_project, revise_inputs, snapshot_inputs
from app.services.workflow import WorkflowEngine

router = APIRouter(prefix="/api/projects", tags=["Projects"])


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new integration project",
)
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> ProjectResponse:
    """
    Create a new project and initialize all workflow artifacts.

    Requires a business requirement and ERP schema context at minimum.
    """
    if not body.erp_profile_version_id:
        raise HTTPException(status_code=400, detail="Select a published ERP profile version")
    profile_version = await _selectable_profile_version(db, body.erp_profile_version_id)
    actor = resolved_identity(identity)
    if body.client_id:
        await ensure_client_access(
            db, actor, body.client_id, allowed_roles=["CLIENT_ADMIN", "CONSULTANT"]
        )
    elif actor.provider != "direct-test":
        raise HTTPException(
            status_code=400, detail="A client is required for a new integration request"
        )
    if actor.provider != "direct-test" and (
        not body.erp_installation_id or not body.erp_environment_id
    ):
        raise HTTPException(400, "Select a client ERP installation and environment")
    installation = None
    environment = None
    if body.erp_installation_id:
        installation = await db.get(ERPInstallation, body.erp_installation_id)
        if installation is None or (body.client_id and installation.client_id != body.client_id):
            raise HTTPException(
                status_code=409, detail="ERP installation is not in the selected client"
            )
        await ensure_client_access(db, actor, installation.client_id)
        if (
            installation.erp_profile_id != profile_version.profile_id
            or installation.status != "ACTIVE"
            or installation.archived_at is not None
        ):
            raise HTTPException(409, "Select an active installation for the selected ERP profile")
    if body.erp_environment_id:
        environment = await db.get(ERPEnvironment, body.erp_environment_id)
        if environment is None or (body.client_id and environment.client_id != body.client_id):
            raise HTTPException(
                status_code=409, detail="ERP environment is not in the selected client"
            )
        if installation and environment.installation_id != installation.id:
            raise HTTPException(
                status_code=409, detail="ERP environment is not in the selected installation"
            )
        await ensure_client_access(db, actor, environment.client_id)
        if environment.status != "ACTIVE" or environment.archived_at is not None:
            raise HTTPException(409, "Select an active ERP environment")
        if installation is None:
            raise HTTPException(409, "An environment requires its ERP installation")
    project = Project(
        name=body.name,
        description=body.description,
        business_requirement=body.business_requirement,
        erp_schema_context=body.erp_schema_context,
        fdd_template_path=body.fdd_template_path,
        tdd_template_path=body.tdd_template_path,
        erp_profile_id=profile_version.profile_id,
        erp_profile_version_id=profile_version.id,
        integration_pattern_version_id=body.integration_pattern_version_id,
        client_id=body.client_id,
        erp_installation_id=body.erp_installation_id,
        erp_environment_id=body.erp_environment_id,
        created_by_subject_id=await actor_subject(db, actor),
        status=ProjectStatus.ACTIVE,
        project_type=body.project_type,
        due_date=body.due_date,
    )
    if body.integration_pattern_version_id:
        from app.services.integration_patterns import resolve_pattern

        await resolve_pattern(
            db,
            body.integration_pattern_version_id,
            profile_id=profile_version.profile_id,
            profile_version_id=profile_version.id,
            installation=installation,
        )
    db.add(project)
    await db.flush()
    await snapshot_inputs(db, project, project.created_by_subject_id)

    # Initialize all artifact records for the workflow
    workflow = WorkflowEngine(db)
    artifacts = await workflow.initialize_project_artifacts(project)
    for artifact in artifacts:
        artifact.client_id = project.client_id

    await record_ownership_event(
        db,
        actor,
        "REQUEST_CREATED",
        "Project",
        project.id,
        client_id=project.client_id,
        details={
            "profile_version_id": profile_version.id,
            "installation_id": project.erp_installation_id,
            "environment_id": project.erp_environment_id,
        },
    )
    await db.flush()
    return (await _project_summaries(db, [project]))[0]


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List all projects",
)
async def list_projects(
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    search: Annotated[str | None, Query(max_length=255)] = None,
    client_id: str | None = None,
    erp_profile_id: str | None = None,
    owner_subject_id: str | None = None,
    request_status: str | None = None,
    project_type: Literal["STANDARD", "CUSTOM"] | None = None,
    sort: Literal["last_activity", "name", "due"] = "last_activity",
    direction: Literal["asc", "desc"] = "desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectListResponse:
    actor = resolved_identity(identity)
    query = select(Project).options(
        raiseload(Project.artifacts),
        raiseload(Project.client),
        raiseload(Project.installation),
        raiseload(Project.environment),
    )
    if request_status != "ARCHIVED":
        query = query.where(Project.archived_at.is_(None))
    if not actor.is_platform_admin and not actor.can_access_unowned_legacy_data:
        query = query.where(Project.client_id.in_(await identity_client_ids(db, actor)))
    elif not actor.can_access_unowned_legacy_data:
        query = query.where(Project.client_id.is_not(None))
    if client_id:
        query = query.where(Project.client_id == client_id)
    if erp_profile_id:
        query = query.where(Project.erp_profile_id == erp_profile_id)
    if owner_subject_id:
        query = query.where(Project.created_by_subject_id == owner_subject_id)
    if request_status:
        if request_status in {item.value for item in ProjectStatus}:
            query = query.where(Project.status == ProjectStatus(request_status))
        elif request_status in {
            "PENDING_REVIEW",
            "CHANGES_REQUESTED",
            "READY_FOR_SANDBOX",
            "DRAFT",
            "GENERATING",
            "IN_PROGRESS",
            "BLOCKED",
            "SANDBOX_BLOCKED",
            "READY_FOR_RELEASE",
            "RELEASED",
        }:
            query = query.where(Project.workflow_status == request_status)
        else:
            raise HTTPException(422, "Unsupported request status")
    if project_type:
        query = query.where(Project.project_type == project_type)
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(
            or_(
                Project.name.ilike(f"%{escaped}%", escape="\\"),
                Project.client_id.in_(
                    select(Client.id).where(Client.display_name.ilike(f"%{escaped}%", escape="\\"))
                ),
            )
        )
    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()
    order = {
        "last_activity": Project.last_activity_at,
        "name": Project.name,
        "due": Project.due_date,
    }[sort]
    result = await db.execute(
        query.order_by(
            order.asc().nulls_last() if direction == "asc" else order.desc().nulls_last(),
            Project.id,
        )
        .limit(limit)
        .offset(offset)
    )
    projects = list(result.scalars().all())

    return ProjectListResponse(
        projects=await _project_summaries(db, projects),
        total=total,
        next_offset=offset + limit if offset + limit < total else None,
        summary={
            "awaiting_review": await _count_status(db, query, "PENDING_REVIEW"),
            "ready_for_sandbox": await _count_status(db, query, "READY_FOR_SANDBOX"),
            "completed": await _count_status(db, query, "RELEASED"),
        },
    )


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get project details",
)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> ProjectResponse:
    """Get a single project by ID."""
    project = await _get_project_or_404(project_id, db, identity)
    return (await _project_summaries(db, [project]))[0]


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Update a project",
)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> ProjectResponse:
    """
    Update project fields.

    Note: Changing the business_requirement or erp_schema_context after
    artifacts have been generated may trigger dependency invalidation.
    """
    actor = resolved_identity(identity)
    project = await _get_project_or_404(project_id, db, actor)
    await ensure_project_mutation(db, actor, project)
    await lock_project(db, project)

    update_data = body.model_dump(exclude_unset=True)
    changed_fields = sorted(
        set(update_data)
        - {
            "expected_requirement_version",
            "expected_schema_context_version",
            "expected_erp_profile_version_id",
            "expected_integration_pattern_version_id",
        }
    )
    expected_requirement = update_data.pop("expected_requirement_version", None)
    expected_context = update_data.pop("expected_schema_context_version", None)
    expected_profile = update_data.pop("expected_erp_profile_version_id", None)
    expected_pattern = update_data.pop("expected_integration_pattern_version_id", None)
    pattern_changed = (
        "integration_pattern_version_id" in update_data
        and update_data["integration_pattern_version_id"] != project.integration_pattern_version_id
    )
    if pattern_changed and (
        not update_data["integration_pattern_version_id"]
        or expected_pattern != project.integration_pattern_version_id
    ):
        raise HTTPException(409, "confirm_current_pattern_before_selecting_a_new_version")
    requirements_changed = (
        "business_requirement" in update_data
        and update_data["business_requirement"] != project.business_requirement
    )
    schema_changed = (
        "erp_schema_context" in update_data
        and update_data["erp_schema_context"] != project.erp_schema_context
    )
    profile_changed = (
        "erp_profile_version_id" in update_data
        and update_data["erp_profile_version_id"] != project.erp_profile_version_id
    )
    if profile_changed and expected_profile != project.erp_profile_version_id:
        raise HTTPException(409, "The ERP profile changed. Reload before confirming an upgrade.")
    for ownership_field in ("client_id", "erp_installation_id", "erp_environment_id"):
        if ownership_field in update_data and update_data[ownership_field] != getattr(
            project, ownership_field
        ):
            raise HTTPException(
                status_code=409, detail="Request ownership is immutable after creation"
            )
    if "erp_profile_id" in update_data:
        raise HTTPException(
            status_code=400, detail="Select an ERP profile version using erp_profile_version_id"
        )
    if "erp_profile_version_id" in update_data and not update_data["erp_profile_version_id"]:
        raise HTTPException(status_code=400, detail="A published ERP profile version is required")
    if update_data.get("erp_profile_version_id"):
        profile_version = await _selectable_profile_version(
            db, update_data["erp_profile_version_id"]
        )
        if project.erp_installation_id:
            installation = await db.get(ERPInstallation, project.erp_installation_id)
            if installation is None or installation.erp_profile_id != profile_version.profile_id:
                raise HTTPException(409, "The profile must match the request's ERP installation")
        update_data["erp_profile_id"] = profile_version.profile_id
    if project.integration_pattern_version_id or update_data.get("integration_pattern_version_id"):
        from app.services.integration_patterns import resolve_pattern

        await resolve_pattern(
            db,
            update_data.get("integration_pattern_version_id")
            or project.integration_pattern_version_id,
            profile_id=project.erp_profile_id,
            profile_version_id=update_data.get("erp_profile_version_id")
            or project.erp_profile_version_id,
            installation=await db.get(ERPInstallation, project.erp_installation_id)
            if project.erp_installation_id
            else None,
            allow_retired=not pattern_changed,
        )
    if requirements_changed or schema_changed or profile_changed or pattern_changed:
        if any(a.current_version for a in project.artifacts) and (
            (requirements_changed or profile_changed or pattern_changed)
            and expected_requirement is None
            or schema_changed
            and expected_context is None
        ):
            raise HTTPException(
                409, "Supply the expected input version before revising generated work"
            )
        await revise_inputs(
            db,
            project,
            await actor_subject(db, actor),
            requirement=update_data.pop("business_requirement", None),
            context=update_data.pop("erp_schema_context", None),
            expected_requirement_version=expected_requirement,
            expected_schema_context_version=expected_context,
            profile_version=profile_version if profile_changed else None,
            pattern_version_id=update_data.pop("integration_pattern_version_id", None)
            if pattern_changed
            else None,
        )
    for field, value in update_data.items():
        setattr(project, field, value)

    if profile_changed:
        # Retain historical rows; add only newly configured stages.
        existing = {a.artifact_type for a in project.artifacts}
        stage_map = WorkflowEngine.configured_stage_map(profile_version.configuration)
        for stage in stage_map:
            if stage not in existing:
                db.add(
                    Artifact(
                        project_id=project.id,
                        client_id=project.client_id,
                        artifact_type=stage,
                        current_version=0,
                    )
                )
    project.last_activity_at = datetime.now(UTC)

    await record_ownership_event(
        db,
        actor,
        "REQUEST_UPDATED",
        "Project",
        project.id,
        client_id=project.client_id,
        details={"fields": changed_fields},
    )
    await db.flush()
    return (await _project_summaries(db, [project]))[0]


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive an integration request",
)
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> None:
    """Archive a project; historical artifacts remain available to its client."""
    project = await _get_project_or_404(project_id, db, identity)
    actor = resolved_identity(identity)
    await ensure_project_mutation(db, actor, project, allowed_roles=["CLIENT_ADMIN"])
    project.archived_at = datetime.now(UTC)
    project.status = ProjectStatus.ARCHIVED
    await record_ownership_event(
        db, actor, "REQUEST_ARCHIVED", "Project", project.id, client_id=project.client_id
    )


@router.get(
    "/{project_id}/traceability",
    summary="Get end-to-end traceability matrix for the project",
)
async def get_project_traceability(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> dict[str, Any]:
    """Report configured dependency lineage, with optional installed traceability strategy."""
    project = await _get_project_or_404(project_id, db, identity)
    profile = (
        await db.get(ERPProfileVersion, project.erp_profile_version_id)
        if project.erp_profile_version_id
        else None
    )
    workflow = WorkflowEngine(db)
    workflow_status = await workflow.get_workflow_status(project)
    effective_stages = {stage["stage"]: stage for stage in workflow_status["stages"]}
    validation_config = profile.configuration.get("validation", {}) if profile else {}
    traceability_adapter = validation_config.get("traceability_adapter")
    if traceability_adapter == "oracle_attribute_lineage":
        approved = {
            stage for stage, info in effective_stages.items() if info["gate_status"] == "APPROVED"
        }
        fdd_content = (
            await workflow.get_approved_content(project_id, "FDD") if "FDD" in approved else None
        )
        tdd_content = (
            await workflow.get_approved_content(project_id, "TDD") if "TDD" in approved else None
        )
        sql_content = (
            await workflow.get_approved_content(project_id, "SQL") if "SQL" in approved else None
        )
        if not fdd_content:
            return {
                "project_id": project.id,
                "kind": "ATTRIBUTE_LINEAGE",
                "status": "NOT_AVAILABLE",
                "message": (
                    "The configured attribute lineage strategy requires an "
                    "approved functional design artifact."
                ),
                "matrix": [],
            }
        from app.services.validation.engine import TraceabilityValidator

        _, _, summary = TraceabilityValidator.validate_traceability(
            fdd_content, tdd_content, sql_content
        )
        return {
            "project_id": project.id,
            "kind": "ATTRIBUTE_LINEAGE",
            "status": "AVAILABLE",
            **summary,
        }

    stage_configs = (
        list(WorkflowEngine.configured_stage_map(profile.configuration).values()) if profile else []
    )
    artifacts_result = await db.execute(
        select(Artifact).where(
            Artifact.project_id == project.id, Artifact.client_id == project.client_id
        )
    )
    artifacts = {artifact.artifact_type: artifact for artifact in artifacts_result.scalars()}
    matrix = []
    for stage in stage_configs:
        if not isinstance(stage, dict) or not stage.get("type"):
            continue
        artifact = artifacts.get(stage["type"])
        dependencies = stage.get("depends_on", [])
        matrix.append(
            {
                "stage": stage["type"],
                "label": stage.get("label", stage["type"]),
                "depends_on": dependencies,
                "status": effective_stages.get(stage["type"], {}).get("gate_status", "LOCKED"),
                "version": artifact.current_version if artifact else 0,
            }
        )
    return {
        "project_id": project.id,
        "kind": "WORKFLOW",
        "status": "AVAILABLE",
        "matrix": matrix,
        "message": (
            "Stage versions and approval gates follow the configured ERP workflow dependencies."
        ),
    }


# ── Helpers ───────────────────────────────────────────────────


async def _count_status(db, query, value):
    condition = (
        Project.status == ProjectStatus.COMPLETED
        if value == "COMPLETED"
        else Project.workflow_status == value
    )
    return int(
        await db.scalar(select(func.count()).select_from(query.where(condition).subquery())) or 0
    )


async def _project_summaries(db: AsyncSession, projects: list[Project]) -> list[ProjectResponse]:
    if not projects:
        return []
    ids = [p.id for p in projects]
    clients = dict(
        (
            await db.execute(
                select(Client.id, Client.display_name).where(
                    Client.id.in_([p.client_id for p in projects if p.client_id])
                )
            )
        ).all()
    )
    profiles = {
        row.id: row
        for row in (
            await db.execute(
                select(
                    ERPProfileVersion.id,
                    ERPProfileVersion.version,
                    ERPProfileVersion.configuration,
                    ERPProfileVersion.status,
                    ERPProfile.display_name,
                    ERPProfile.name,
                    ERPProfile.active,
                    ERPProfile.status.label("profile_status"),
                )
                .join(ERPProfile)
                .where(ERPProfileVersion.id.in_([p.erp_profile_version_id for p in projects]))
            )
        ).all()
    }
    rows = (
        await db.execute(
            select(
                Artifact.project_id,
                Artifact.id,
                Artifact.artifact_type,
                Artifact.current_version,
                Artifact.gate_status,
            ).where(Artifact.project_id.in_(ids))
        )
    ).all()
    artifacts: dict[str, dict[str, Any]] = {}
    artifact_ids = []
    for row in rows:
        artifact_ids.append(row.id)
        artifacts.setdefault(row.project_id, {})[row.artifact_type] = SimpleNamespace(
            id=row.id, gate_status=row.gate_status, current_version=row.current_version
        )
    version_rows = (
        (
            await db.execute(
                select(ArtifactVersion)
                .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
                .where(
                    Artifact.id.in_(artifact_ids),
                    ArtifactVersion.version_number == Artifact.current_version,
                )
            )
        )
        .scalars()
        .all()
        if artifact_ids
        else []
    )
    versions = {version.artifact_id: version for version in version_rows}
    validation_rows = (
        (
            await db.execute(
                select(ValidationResult).where(
                    ValidationResult.artifact_version_id.in_(
                        [version.id for version in version_rows]
                    )
                )
            )
        )
        .scalars()
        .all()
        if version_rows
        else []
    )
    validations: dict[str, list[ValidationResult]] = {}
    for validation in validation_rows:
        validations.setdefault(validation.artifact_version_id, []).append(validation)

    candidates = (
        (
            await db.execute(
                select(PackageCandidate)
                .where(PackageCandidate.project_id.in_(ids))
                .order_by(PackageCandidate.created_at.desc(), PackageCandidate.id.desc())
            )
        )
        .scalars()
        .all()
    )
    candidates_by_project: dict[str, list[PackageCandidate]] = {}
    for candidate in candidates:
        candidates_by_project.setdefault(candidate.project_id, []).append(candidate)

    connections = (
        (
            await db.execute(
                select(ERPConnection).where(
                    ERPConnection.environment_id.in_(
                        [
                            project.erp_environment_id
                            for project in projects
                            if project.erp_environment_id
                        ]
                    ),
                    ERPConnection.client_id.in_(
                        [project.client_id for project in projects if project.client_id]
                    ),
                )
            )
        )
        .scalars()
        .all()
        if any(p.erp_environment_id and p.client_id for p in projects)
        else []
    )
    connections_by_environment = {
        connection.environment_id: connection for connection in connections
    }

    current_candidates: dict[str, PackageCandidate | None] = {}
    for project in projects:
        profile = profiles.get(project.erp_profile_version_id or "")
        stages = WorkflowEngine.configured_stage_map(profile.configuration) if profile else {}
        current_candidates[project.id] = (
            _current_summary_candidate(
                project,
                stages,
                artifacts.get(project.id, {}),
                versions,
                validations,
                candidates_by_project.get(project.id, []),
            )
            if profile
            and profile.status == "PUBLISHED"
            and profile.active
            and profile.profile_status != "RETIRED"
            else None
        )
        if project.integration_pattern_version_id:
            from app.services.packages import current_candidate

            _, current_candidates[project.id] = await current_candidate(db, project)
    current_candidate_ids = [candidate.id for candidate in current_candidates.values() if candidate]
    evidence_rows = (
        (
            await db.execute(
                select(SandboxEvidence)
                .where(
                    SandboxEvidence.candidate_id.in_(current_candidate_ids),
                    SandboxEvidence.environment_id.in_(
                        [
                            project.erp_environment_id
                            for project in projects
                            if project.erp_environment_id
                        ]
                    ),
                )
                .order_by(SandboxEvidence.created_at.desc(), SandboxEvidence.id.desc())
            )
        )
        .scalars()
        .all()
        if current_candidate_ids
        else []
    )
    latest_evidence: dict[str, SandboxEvidence] = {}
    candidate_by_id = {
        candidate.id: candidate for candidate in current_candidates.values() if candidate
    }
    for evidence in evidence_rows:
        evidence_candidate = candidate_by_id.get(evidence.candidate_id)
        if (
            evidence_candidate is None
            or evidence.project_id != evidence_candidate.project_id
            or evidence.client_id != evidence_candidate.client_id
        ):
            continue
        latest_evidence.setdefault(evidence.candidate_id, evidence)
    releasable_evidence_ids = []
    for project in projects:
        project_candidate = current_candidates.get(project.id)
        environment_id = project.erp_environment_id
        if project_candidate is None or environment_id is None:
            continue
        current_evidence = latest_evidence.get(project_candidate.id)
        connection = connections_by_environment.get(environment_id)
        if (
            current_evidence
            and current_evidence.status == "PASSED"
            and connection
            and connection.client_id == project.client_id
            and connection.installation_id == project.erp_installation_id
            and current_evidence.connection_version == connection.configuration_version
            and (current_evidence.observations or {}).get("secret_version")
            == connection.secret_version
        ):
            releasable_evidence_ids.append(current_evidence.id)
    releases = (
        (
            await db.execute(
                select(PackageRelease).where(
                    PackageRelease.evidence_id.in_(releasable_evidence_ids),
                    PackageRelease.candidate_id.in_(current_candidate_ids),
                )
            )
        )
        .scalars()
        .all()
        if releasable_evidence_ids
        else []
    )
    releases_by_evidence = {
        release.evidence_id: release
        for release in releases
        if (release_candidate := candidate_by_id.get(release.candidate_id))
        and release.project_id == release_candidate.project_id
        and release.client_id == release_candidate.client_id
        and release.evidence_id in releasable_evidence_ids
    }

    summaries = []
    for project in projects:
        profile = profiles.get(project.erp_profile_version_id or "")
        stages = WorkflowEngine.configured_stage_map(profile.configuration) if profile else {}
        effective = WorkflowEngine._effective_gate_statuses(stages, artifacts.get(project.id, {}))
        current = next(
            (name for name in stages if effective.get(name, GateStatus.LOCKED).value != "APPROVED"),
            None,
        )
        response = ProjectResponse.model_validate(project)
        summary_candidate = current_candidates.get(project.id)
        summary_evidence = latest_evidence.get(summary_candidate.id) if summary_candidate else None
        release = releases_by_evidence.get(summary_evidence.id) if summary_evidence else None
        if summary_candidate and summary_candidate.manifest.get("format_version") == 2:
            from app.services.packages import current_release

            # ponytail: reuse authoritative release checks for new harness profiles;
            # batch this branch if measured directory latency requires it.
            release = await current_release(db, project, summary_candidate)
        package_kind = "release" if release else "candidate" if summary_candidate else None
        package_url = (
            f"/api/projects/{project.id}/package/releases/{release.id}/download"
            if release
            else f"/api/projects/{project.id}/package/candidates/{summary_candidate.id}/download"
            if summary_candidate
            else None
        )
        summaries.append(
            response.model_copy(
                update={
                    "client_name": clients.get(project.client_id or ""),
                    "erp_name": (profile.display_name or profile.name) if profile else None,
                    "erp_version": profile.version if profile else None,
                    "current_stage": current,
                    "package_available": bool(summary_candidate),
                    "package_kind": package_kind,
                    "package_download_url": package_url,
                }
            )
        )
        if project.integration_pattern_version_id:
            from app.models import IntegrationPattern, IntegrationPatternVersion

            pattern_version = await db.get(
                IntegrationPatternVersion, project.integration_pattern_version_id
            )
            pattern = (
                await db.get(IntegrationPattern, pattern_version.pattern_id)
                if pattern_version
                else None
            )
            summaries[-1] = summaries[-1].model_copy(
                update={
                    "integration_pattern_name": pattern.name if pattern else None,
                    "integration_pattern_version": pattern_version.version
                    if pattern_version
                    else None,
                }
            )
    return summaries


def _current_summary_candidate(project, stages, artifacts, versions, validations, candidates):
    """Return the newest candidate whose manifest still matches current approved inputs."""
    effective = WorkflowEngine._effective_gate_statuses(stages, artifacts)
    expected_artifacts = {}
    for name in stages:
        artifact = artifacts.get(name)
        version = versions.get(artifact.id) if artifact else None
        if (
            artifact is None
            or version is None
            or artifact.current_version != version.version_number
            or effective.get(name) != GateStatus.APPROVED
            or version.state != VersionState.APPROVED
            or not version.reviewer_subject_id
        ):
            return None
        dependency_names = set()
        pending = list(stages[name].get("depends_on", []))
        while pending:
            dependency = pending.pop()
            if dependency in dependency_names:
                continue
            dependency_names.add(dependency)
            pending.extend(stages.get(dependency, {}).get("depends_on", []))
        upstream = {
            dependency: (
                versions[artifacts[dependency].id].id
                if dependency in artifacts
                and artifacts[dependency].id in versions
                and effective.get(dependency) == GateStatus.APPROVED
                and versions[artifacts[dependency].id].state == VersionState.APPROVED
                else None
            )
            for dependency in sorted(dependency_names)
        }
        bindings = {
            "profile_version_id": project.erp_profile_version_id,
            "requirement_version": project.requirement_version,
            "schema_context_version": project.schema_context_version,
            "upstream_artifacts": upstream,
        }
        snapshot = version.input_context_snapshot or {}
        if snapshot.get("input_bindings") != bindings:
            return None
        result_rows = sorted(
            validations.get(version.id, []), key=lambda item: (item.category.value, item.id)
        )
        expected_artifacts[name] = {
            "artifact_id": version.artifact_id,
            "version_id": version.id,
            "revision": version.version_number,
            "reviewer_subject_id": version.reviewer_subject_id,
            "content_sha256": sha256(json_bytes(version.content)),
            "input_snapshot_sha256": sha256(json_bytes(version.input_context_snapshot)),
            "validation_results": [
                {"id": item.id, "category": item.category.value, "status": item.status.value}
                for item in result_rows
            ],
        }
        if any(item.status.value != "PASS" for item in result_rows):
            return None

    for candidate in candidates:
        if candidate.client_id != project.client_id:
            continue
        manifest = candidate.manifest or {}
        if any(
            manifest.get(key) != value
            for key, value in {
                "kind": "candidate",
                "client_id": project.client_id,
                "project_id": project.id,
                "profile_version_id": project.erp_profile_version_id,
                "requirement_version": project.requirement_version,
                "schema_context_version": project.schema_context_version,
                "workflow_revision": project.workflow_revision,
                **(
                    {
                        "environment_id": project.erp_environment_id,
                        "installation_id": project.erp_installation_id,
                    }
                    if manifest.get("format_version") == 1
                    else {}
                ),
            }.items()
        ):
            continue
        actual_artifacts = manifest.get("artifacts")
        if (
            isinstance(actual_artifacts, dict)
            and actual_artifacts.keys() == expected_artifacts.keys()
            and all(
                all(actual_artifacts[name].get(key) == value for key, value in expected.items())
                for name, expected in expected_artifacts.items()
            )
        ):
            return candidate
    return None


async def _get_project_or_404(
    project_id: str, db: AsyncSession, identity: object | None = None
) -> Project:
    """Fetch a project or raise 404."""
    return await get_authorized_project(project_id, db, identity)


async def ensure_project_mutation(
    db: AsyncSession,
    actor: Identity,
    project: Project,
    *,
    allowed_roles: list[str] | None = None,
) -> None:
    """Historical requests remain readable; commands require an active request and role."""
    if project.archived_at is not None or project.status == ProjectStatus.ARCHIVED:
        raise HTTPException(409, "Archived requests cannot be modified")
    if project.client_id:
        await ensure_client_access(
            db,
            actor,
            project.client_id,
            allowed_roles=allowed_roles or ["CLIENT_ADMIN", "CONSULTANT"],
        )
    elif actor.provider != "direct-test":
        raise HTTPException(409, "Reconcile legacy request ownership before modifying it")
    if project.erp_installation_id:
        installation = await db.get(ERPInstallation, project.erp_installation_id)
        if (
            installation is None
            or installation.client_id != project.client_id
            or installation.erp_profile_id != project.erp_profile_id
            or installation.status != "ACTIVE"
            or installation.archived_at is not None
        ):
            raise HTTPException(409, "The request's ERP installation is unavailable")
    if project.erp_environment_id:
        environment = await db.get(ERPEnvironment, project.erp_environment_id)
        if (
            environment is None
            or environment.client_id != project.client_id
            or environment.installation_id != project.erp_installation_id
            or environment.status != "ACTIVE"
            or environment.archived_at is not None
        ):
            raise HTTPException(409, "The request's ERP environment is unavailable")


async def _selectable_profile_version(db: AsyncSession, version_id: str) -> ERPProfileVersion:
    version = (
        await db.execute(
            select(ERPProfileVersion)
            .join(ERPProfile)
            .where(
                ERPProfileVersion.id == version_id,
                ERPProfileVersion.status == "PUBLISHED",
                ERPProfile.active.is_(True),
                ERPProfile.status != "RETIRED",
            )
        )
    ).scalar_one_or_none()
    if version is None:
        raise HTTPException(400, "Select a published version of an active ERP profile")
    return version
