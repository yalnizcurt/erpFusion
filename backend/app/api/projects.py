"""
erpFusion — Project API Routes

CRUD operations for projects. Creating a project automatically initializes
all artifact records in LOCKED state via the workflow engine.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Artifact, ERPProfileVersion, Project, ProjectStatus
from app.schemas import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from app.services.workflow import WorkflowEngine
from app.services.erp_registry import ensure_seed_profiles

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
) -> ProjectResponse:
    """
    Create a new project and initialize all workflow artifacts.

    Requires a business requirement and ERP schema context at minimum.
    """
    if not body.erp_profile_version_id:
        raise HTTPException(status_code=400, detail="Select a published ERP profile version")
    profile_version = await db.get(ERPProfileVersion, body.erp_profile_version_id)
    if not profile_version or profile_version.status != "PUBLISHED":
        raise HTTPException(status_code=400, detail="Selected ERP profile version is not published")
    project = Project(
        name=body.name,
        description=body.description,
        business_requirement=body.business_requirement,
        erp_schema_context=body.erp_schema_context,
        fdd_template_path=body.fdd_template_path,
        tdd_template_path=body.tdd_template_path,
        erp_profile_id=profile_version.profile_id,
        erp_profile_version_id=profile_version.id,
        status=ProjectStatus.ACTIVE,
    )
    db.add(project)
    await db.flush()

    # Initialize all artifact records for the workflow
    workflow = WorkflowEngine(db)
    await workflow.initialize_project_artifacts(project)

    await db.flush()
    return ProjectResponse.model_validate(project)


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List all projects",
)
async def list_projects(
    db: AsyncSession = Depends(get_db),
) -> ProjectListResponse:
    await ensure_seed_profiles(db)
    result = await db.execute(
        select(Project).order_by(Project.created_at.desc())
    )
    projects = list(result.scalars().all())

    count_result = await db.execute(select(func.count(Project.id)))
    total = count_result.scalar_one()

    return ProjectListResponse(
        projects=[ProjectResponse.model_validate(p) for p in projects],
        total=total,
    )


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get project details",
)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    """Get a single project by ID."""
    project = await _get_project_or_404(project_id, db)
    return ProjectResponse.model_validate(project)


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Update a project",
)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    """
    Update project fields.

    Note: Changing the business_requirement or erp_schema_context after
    artifacts have been generated may trigger dependency invalidation.
    """
    project = await _get_project_or_404(project_id, db)

    update_data = body.model_dump(exclude_unset=True)
    requirements_changed = "business_requirement" in update_data and update_data["business_requirement"] != project.business_requirement
    schema_changed = "erp_schema_context" in update_data and update_data["erp_schema_context"] != project.erp_schema_context
    profile_changed = "erp_profile_version_id" in update_data and update_data["erp_profile_version_id"] != project.erp_profile_version_id
    if "erp_profile_id" in update_data:
        raise HTTPException(status_code=400, detail="Select an ERP profile version using erp_profile_version_id")
    if "erp_profile_version_id" in update_data and not update_data["erp_profile_version_id"]:
        raise HTTPException(status_code=400, detail="A published ERP profile version is required")
    if update_data.get("erp_profile_version_id"):
        profile_version = await db.get(ERPProfileVersion, update_data["erp_profile_version_id"])
        if not profile_version or profile_version.status != "PUBLISHED":
            raise HTTPException(status_code=400, detail="Selected ERP profile version is not published")
        if project.erp_profile_version_id != profile_version.id and any(a.current_version for a in project.artifacts):
            raise HTTPException(status_code=409, detail="ERP profile version is pinned after generation begins")
        update_data["erp_profile_id"] = profile_version.profile_id
    if (requirements_changed or schema_changed) and any(a.current_version for a in project.artifacts):
        raise HTTPException(status_code=409, detail="Requirement and schema inputs are immutable after generation begins. Create a new request to preserve reproducibility.")
    for field, value in update_data.items():
        setattr(project, field, value)

    if requirements_changed:
        project.requirement_version += 1
    if schema_changed:
        project.schema_context_version += 1
    if profile_changed:
        # Replace the not-yet-used stage rows so the new profile's workflow is reflected exactly.
        for artifact in list(project.artifacts):
            await db.delete(artifact)
        await db.flush()
        await WorkflowEngine(db).initialize_project_artifacts(project)

    await db.flush()
    return ProjectResponse.model_validate(project)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project",
)
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a project and all its artifacts (cascade)."""
    project = await _get_project_or_404(project_id, db)
    await db.delete(project)


@router.post(
    "/seed-sample",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Seed sample Oracle Fusion AP Invoices integration project",
)
async def seed_sample_project(
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    """Create a fully-configured enterprise sample project with realistic requirement and Oracle schema."""
    sample_requirement = """Integrate Oracle Fusion Cloud Payables (AP) with enterprise Data Warehouse.

Objective:
Extract all approved and paid AP Invoices and their corresponding Line items on a scheduled basis.
The feed must support full initial baseline extraction as well as incremental (delta) runs based on LAST_UPDATE_DATE.

Attributes to extract:
- Invoice ID, Supplier Invoice Number, Invoice Date, Header Gross Amount
- Supplier Legal Party Name (from TCA HZ_PARTIES)
- Line Number, Itemized Line Amount, Line Description

Technical Requirements:
1. Output format: Pipe-delimited flat file (|) written to Oracle directory object XX_OUTBOUND_DIR.
2. Sanitization: All text fields (Invoice Number, Supplier Name, Line Description) must have pipe characters (|) and carriage returns/newlines stripped/replaced with spaces to prevent field shifting.
3. Exclude cancelled invoices (CANCELLED_DATE is not null).
4. Maintain high-water mark timestamp in XX_INTEGRATION_WATERMARKS table, updating only after successful file write."""

    sample_schema = {
        "tables": [
            {
                "name": "AP_INVOICES_ALL",
                "description": "Invoice header records in Oracle Fusion Payables",
                "columns": [
                    {"name": "INVOICE_ID", "data_type": "NUMBER", "nullable": False, "primary_key": True},
                    {"name": "INVOICE_NUM", "data_type": "VARCHAR2(50)", "nullable": False},
                    {"name": "INVOICE_DATE", "data_type": "DATE", "nullable": False},
                    {"name": "INVOICE_AMOUNT", "data_type": "NUMBER", "nullable": False},
                    {"name": "PAYMENT_STATUS_FLAG", "data_type": "VARCHAR2(1)", "nullable": True},
                    {"name": "VENDOR_ID", "data_type": "NUMBER", "nullable": True, "foreign_key": "HZ_PARTIES.PARTY_ID"},
                    {"name": "CANCELLED_DATE", "data_type": "DATE", "nullable": True},
                    {"name": "LAST_UPDATE_DATE", "data_type": "TIMESTAMP", "nullable": False},
                ],
            },
            {
                "name": "AP_INVOICE_LINES_ALL",
                "description": "Itemized lines for each invoice header",
                "columns": [
                    {"name": "INVOICE_ID", "data_type": "NUMBER", "nullable": False, "foreign_key": "AP_INVOICES_ALL.INVOICE_ID"},
                    {"name": "LINE_NUMBER", "data_type": "NUMBER", "nullable": False, "primary_key": True},
                    {"name": "LINE_TYPE_LOOKUP_CODE", "data_type": "VARCHAR2(25)", "nullable": False},
                    {"name": "AMOUNT", "data_type": "NUMBER", "nullable": False},
                    {"name": "DESCRIPTION", "data_type": "VARCHAR2(240)", "nullable": True},
                    {"name": "LAST_UPDATE_DATE", "data_type": "TIMESTAMP", "nullable": False},
                ],
            },
            {
                "name": "HZ_PARTIES",
                "description": "Trading Community Architecture (TCA) parties including vendors and suppliers",
                "columns": [
                    {"name": "PARTY_ID", "data_type": "NUMBER", "nullable": False, "primary_key": True},
                    {"name": "PARTY_NAME", "data_type": "VARCHAR2(360)", "nullable": False},
                    {"name": "PARTY_NUMBER", "data_type": "VARCHAR2(30)", "nullable": True},
                ],
            },
        ],
        "foreign_keys": [
            {"from": "AP_INVOICE_LINES_ALL.INVOICE_ID", "to": "AP_INVOICES_ALL.INVOICE_ID"},
            {"from": "AP_INVOICES_ALL.VENDOR_ID", "to": "HZ_PARTIES.PARTY_ID"},
        ],
    }

    profile = await ensure_seed_profiles(db)
    profile_version_result = await db.execute(select(ERPProfileVersion).where(
        ERPProfileVersion.profile_id == profile.id, ERPProfileVersion.status == "PUBLISHED"
    ).order_by(ERPProfileVersion.version.desc()).limit(1))
    profile_version = profile_version_result.scalar_one()
    project = Project(
        name="Oracle Fusion AP Invoices & Lines Outbound Feed",
        description="Production integration package for AP Invoices & Lines with HZ_PARTIES supplier resolution and delta watermarking.",
        business_requirement=sample_requirement,
        erp_schema_context=sample_schema,
        erp_profile_id=profile.id,
        erp_profile_version_id=profile_version.id,
        status=ProjectStatus.ACTIVE,
    )
    db.add(project)
    await db.flush()

    workflow = WorkflowEngine(db)
    await workflow.initialize_project_artifacts(project)
    await db.flush()

    return ProjectResponse.model_validate(project)


@router.get(
    "/{project_id}/traceability",
    summary="Get end-to-end traceability matrix for the project",
)
async def get_project_traceability(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Report configured dependency lineage, with optional installed traceability strategy."""
    project = await _get_project_or_404(project_id, db)
    profile = await db.get(ERPProfileVersion, project.erp_profile_version_id) if project.erp_profile_version_id else None
    validation_config = (profile.configuration.get("validation", {}) if profile else {})
    traceability_adapter = validation_config.get("traceability_adapter")
    if traceability_adapter == "oracle_attribute_lineage":
        workflow = WorkflowEngine(db)
        fdd_content = await workflow.get_approved_content(project_id, "FDD")
        tdd_content = await workflow.get_approved_content(project_id, "TDD")
        sql_content = await workflow.get_approved_content(project_id, "SQL")
        if not fdd_content:
            return {"project_id": project.id, "kind": "ATTRIBUTE_LINEAGE", "status": "NOT_AVAILABLE",
                    "message": "The configured attribute lineage strategy requires an approved functional design artifact.",
                    "matrix": []}
        from app.services.validation.engine import TraceabilityValidator
        _, _, summary = TraceabilityValidator.validate_traceability(fdd_content, tdd_content, sql_content)
        return {"project_id": project.id, "kind": "ATTRIBUTE_LINEAGE", "status": "AVAILABLE", **summary}

    stage_configs = list(WorkflowEngine.configured_stage_map(profile.configuration).values()) if profile else []
    artifacts_result = await db.execute(select(Artifact).where(Artifact.project_id == project.id))
    artifacts = {artifact.artifact_type: artifact for artifact in artifacts_result.scalars()}
    matrix = []
    for stage in stage_configs:
        if not isinstance(stage, dict) or not stage.get("type"):
            continue
        artifact = artifacts.get(stage["type"])
        dependencies = stage.get("depends_on", [])
        matrix.append({
            "stage": stage["type"], "label": stage.get("label", stage["type"]),
            "depends_on": dependencies,
            "status": artifact.gate_status.value if artifact else "LOCKED",
            "version": artifact.current_version if artifact else 0,
        })
    return {
        "project_id": project.id,
        "kind": "WORKFLOW",
        "status": "AVAILABLE",
        "matrix": matrix,
        "message": "Stage versions and approval gates follow the configured ERP workflow dependencies.",
    }



# ── Helpers ───────────────────────────────────────────────────


async def _get_project_or_404(project_id: str, db: AsyncSession) -> Project:
    """Fetch a project or raise 404."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )
    return project
