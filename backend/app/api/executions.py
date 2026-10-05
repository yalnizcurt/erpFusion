"""Scoped qualification, explicit execution approvals and authenticated evidence."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.api.connections import _RedactedValidationRoute
from app.api.packages import owned_record, scoped_project
from app.config import Settings, get_settings
from app.database import get_db
from app.models import (
    CapabilityQualification,
    ConnectionVerification,
    ERPEnvironment,
    ExecutionAttempt,
    SandboxEvidence,
)
from app.schemas.identity import validate_public_configuration
from app.security.access import ensure_client_access
from app.security.identity import Identity, get_current_identity
from app.services.artifact_storage import asset_directory, read_asset_file, save_asset_file
from app.services.execution import (
    active_qualification,
    release_attempt,
    target_binding,
    validate_attempt,
)
from app.services.execution_contracts import (
    ADAPTER_CONTRACTS,
    ADAPTER_VERSION,
    CAPABILITIES,
    FUTURE_ORACLE,
    SCENARIOS,
    TERMINAL,
    transition,
    utc,
)
from app.services.integration_patterns import pattern_context
from app.services.ownership_audit import actor_subject, record_ownership_event
from app.services.packages import current_candidate, json_bytes, sha256

router = APIRouter(
    prefix="/api/projects/{project_id}/executions",
    tags=["Execution harness"],
    route_class=_RedactedValidationRoute,
)


class QualificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    environment_id: str = Field(min_length=1, max_length=36)
    acknowledge_environment_scope: Literal[True]
    acknowledge_existing_report_only: bool = False


class ExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(min_length=1, max_length=36)
    environment_id: str = Field(min_length=1, max_length=36)
    operation: Literal["QUALIFY_CANDIDATE", "RUN_REPORT", "CHECK_REPORT_ACCESS"] = (
        "QUALIFY_CANDIDATE"
    )
    idempotency_key: str = Field(min_length=1, max_length=128)
    scenario: str | None = None
    parameters: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("scenario")
    @classmethod
    def known_scenario(cls, value):
        if value is not None and value not in SCENARIOS:
            raise ValueError("Unknown simulator scenario")
        return value

    @field_validator("parameters")
    @classmethod
    def bounded_parameters(cls, value):
        validate_public_configuration(value)
        if (
            len(value) > 30
            or len(json_bytes(value)) > 65536
            or any(
                not 1 <= len(key) <= 128
                or any(ord(c) < 32 for c in key)
                or len(values) > 100
                or any(len(v) > 2048 or any(ord(c) < 32 for c in v) for v in values)
                for key, values in value.items()
            )
        ):
            raise ValueError("Invalid parameters")
        return value


class Acknowledgement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acknowledge: Literal[True]


class TargetReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    environment_id: str = Field(min_length=1, max_length=36)
    custody: Literal["ERPFUSION_MANAGED", "CUSTOMER"]
    execution_mode: Literal["ASSISTED", "SIMULATED", "REMOTE"]
    acknowledge: Literal[True]


class Reconciliation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["CONFIRMED_NO_EXECUTION", "CONFIRMED_FAILED", "REQUIRES_EXTERNAL_REVIEW"]
    evidence_note: str = Field(min_length=1, max_length=4000)
    acknowledge: Literal[True]


def attempt_response(attempt):
    return {
        field: getattr(attempt, field)
        for field in (
            "id",
            "candidate_id",
            "candidate_checksum",
            "environment_id",
            "qualification_id",
            "integration_pattern_version_id",
            "adapter",
            "adapter_version",
            "operation",
            "status",
            "verdict",
            "assurance",
            "external_execution_id",
            "failure",
            "result",
            "created_at",
            "started_at",
            "completed_at",
            "requested_by_subject_id",
            "approved_by_subject_id",
            "approval_expires_at",
            "retry_count",
        )
    } | {
        "simulated": attempt.adapter == "oracle_simulator",
        "request": attempt.request,
        "result": {
            key: value for key, value in attempt.result.items() if not key.startswith("_private_")
        },
    }


@router.get("")
async def list_attempts(
    project_id: str, db=Depends(get_db), identity: Identity = Depends(get_current_identity)
):
    project = await scoped_project(project_id, db, identity)
    attempts = await db.scalars(
        select(ExecutionAttempt)
        .where(
            ExecutionAttempt.project_id == project.id,
            ExecutionAttempt.client_id == project.client_id,
        )
        .order_by(ExecutionAttempt.created_at.desc())
        .limit(100)
    )
    return {"attempts": [attempt_response(a) for a in attempts]}


@router.post("/target-review")
async def review_target(
    project_id: str,
    body: TargetReview,
    db=Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
):
    project = await scoped_project(project_id, db, identity, manage=True, roles=["CLIENT_ADMIN"])
    environment = await db.get(ERPEnvironment, body.environment_id)
    if (
        not environment
        or environment.client_id != project.client_id
        or environment.installation_id != project.erp_installation_id
    ):
        raise HTTPException(404, "ERP environment not found")
    if body.custody == "ERPFUSION_MANAGED" and not identity.is_platform_admin:
        raise HTTPException(403, "managed_environment_requires_platform_admin")
    if body.execution_mode == "SIMULATED" and (
        settings.is_production or not settings.execution_simulator_enabled
    ):
        raise HTTPException(409, "execution_simulator_disabled")
    environment.custody, environment.execution_mode = body.custody, body.execution_mode
    await record_ownership_event(
        db,
        identity,
        "EXECUTION_TARGET_REVIEWED",
        "ERPEnvironment",
        environment.id,
        client_id=project.client_id,
        details={"custody": body.custody, "execution_mode": body.execution_mode},
    )
    return {
        "id": environment.id,
        "custody": environment.custody,
        "execution_mode": environment.execution_mode,
    }


@router.get("/capabilities/{environment_id}")
async def capabilities(
    project_id: str,
    environment_id: str,
    db=Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
):
    project = await scoped_project(project_id, db, identity)
    context = await pattern_context(db, project)
    if not project.client_id:
        raise HTTPException(409, "owned_project_required_for_execution")
    declared = (
        set(
            context["configuration"].get("required_capabilities", [])
            + context["configuration"].get("optional_capabilities", [])
        )
        if context
        else set()
    )
    actor_can_execute = True
    try:
        await ensure_client_access(
            db, identity, project.client_id, allowed_roles=["CLIENT_ADMIN", "TESTER"]
        )
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        actor_can_execute = False
    try:
        environment, profile, connection, binding = await target_binding(
            db, project, environment_id, settings
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            raise
        return {
            "available": False,
            "blockers": [exc.detail],
            "capabilities": [
                {"name": name, "implemented": False, "qualified": False}
                for name in sorted(declared)
            ],
            "qualification_id": None,
            "integration_pattern_version_id": context["version_id"] if context else None,
            "runtime_type": context["runtime_type"] if context else None,
            "qualification_strategy": context["qualification_strategy"] if context else None,
            "actor_can_execute": actor_can_execute,
            "required_capabilities": context["configuration"].get("required_capabilities", [])
            if context
            else [],
        }
    qualification = None
    blockers = []
    try:
        *_, qualification = await active_qualification(db, project, environment_id, settings)
    except HTTPException as exc:
        blockers.append(exc.detail)
    implemented = set(CAPABILITIES[binding["adapter"]])
    available = declared & implemented & set(qualification.capabilities if qualification else [])
    if (
        environment.execution_mode == "REMOTE"
        and connection
        and "RUN_REPORT" not in connection.permitted_operations
    ):
        available.discard("RUN_REPORT")
    return {
        "available": bool(available),
        "adapter": binding["adapter"],
        "adapter_version": ADAPTER_VERSION,
        "mode": environment.execution_mode,
        "custody": environment.custody,
        "capabilities": [
            {"name": name, "implemented": name in implemented, "qualified": name in available}
            for name in sorted(declared | implemented)
        ],
        "unqualified_future_capabilities": FUTURE_ORACLE
        if binding["adapter"] == "oracle_fusion_publisher"
        else [],
        "qualification_id": qualification.id if qualification else None,
        "integration_pattern_version_id": profile.id,
        "runtime_type": profile.runtime_type,
        "qualification_strategy": profile.qualification_strategy,
        "required_capabilities": profile.configuration.get("required_capabilities", []),
        "blockers": blockers,
        "actor_can_execute": actor_can_execute,
        "qualification_ready": bool(
            set(profile.configuration.get("required_capabilities", [])) <= available
        ),
    }


@router.post("/qualifications", status_code=201)
async def qualify(
    project_id: str,
    body: QualificationRequest,
    db=Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
):
    project = await scoped_project(project_id, db, identity, manage=True, roles=["CLIENT_ADMIN"])
    environment, profile, connection, binding = await target_binding(
        db, project, body.environment_id, settings
    )
    subject = await actor_subject(db, identity)
    if not subject:
        raise HTTPException(403, "authenticated_subject_required")
    if environment.execution_mode == "REMOTE":
        probe = await db.scalar(
            select(ConnectionVerification)
            .where(
                ConnectionVerification.connection_id == connection.id,
                ConnectionVerification.configuration_version == connection.configuration_version,
                ConnectionVerification.secret_version == connection.secret_version,
            )
            .order_by(ConnectionVerification.checked_at.desc())
            .limit(1)
        )
        if (
            not body.acknowledge_existing_report_only
            or not probe
            or utc(probe.expires_at) <= datetime.now(UTC)
            or probe.checks.get("authentication") != "VERIFIED"
            or probe.checks.get("permissions") != "VERIFIED"
        ):
            raise HTTPException(
                409, "fresh_access_probe_and_existing_report_acknowledgement_required"
            )
    available = sorted(
        set(CAPABILITIES[binding["adapter"]])
        & set(
            profile.configuration.get("required_capabilities", [])
            + profile.configuration.get("optional_capabilities", [])
        )
    )
    if (
        environment.execution_mode == "REMOTE"
        and connection
        and "RUN_REPORT" not in connection.permitted_operations
    ):
        available = [c for c in available if c != "RUN_REPORT"]
    qualification = CapabilityQualification(
        client_id=project.client_id,
        environment_id=environment.id,
        adapter=binding["adapter"],
        adapter_version=ADAPTER_VERSION,
        binding=binding,
        capabilities=available,
        approved_by_subject_id=subject,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    db.add(qualification)
    await db.flush()
    await record_ownership_event(
        db,
        identity,
        "CAPABILITY_QUALIFICATION_APPROVED",
        "CapabilityQualification",
        qualification.id,
        client_id=project.client_id,
        details={
            "adapter": qualification.adapter,
            "capabilities": available,
            "environment_id": environment.id,
        },
    )
    return {
        "id": qualification.id,
        "capabilities": available,
        "expires_at": qualification.expires_at,
    }


@router.post("/qualifications/{qualification_id}/revoke")
async def revoke(
    project_id: str,
    qualification_id: str,
    body: Acknowledgement,
    db=Depends(get_db),
    identity: Identity = Depends(get_current_identity),
):
    project = await scoped_project(project_id, db, identity, manage=True, roles=["CLIENT_ADMIN"])
    qualification = await db.get(CapabilityQualification, qualification_id)
    if not qualification or qualification.client_id != project.client_id:
        raise HTTPException(404, "Qualification not found")
    qualification.status = "REVOKED"
    await record_ownership_event(
        db,
        identity,
        "CAPABILITY_QUALIFICATION_REVOKED",
        "CapabilityQualification",
        qualification.id,
        client_id=project.client_id,
    )
    return {"id": qualification.id, "status": qualification.status}


@router.post("", status_code=201)
async def request_execution(
    project_id: str,
    body: ExecutionRequest,
    db=Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
):
    project = await scoped_project(
        project_id, db, identity, manage=True, roles=["CLIENT_ADMIN", "TESTER"]
    )
    subject = await actor_subject(db, identity)
    if not subject:
        raise HTTPException(403, "authenticated_subject_required")
    previous = await db.scalar(
        select(ExecutionAttempt).where(
            ExecutionAttempt.project_id == project.id,
            ExecutionAttempt.idempotency_key == body.idempotency_key,
        )
    )
    if previous:
        original = {k: v for k, v in previous.request.items() if k != "test_plan_sha256"}
        if (
            previous.candidate_id != body.candidate_id
            or previous.environment_id != body.environment_id
            or original
            != body.model_dump(exclude={"candidate_id", "environment_id", "idempotency_key"})
        ):
            raise HTTPException(409, "idempotency_key_conflict")
        return attempt_response(previous)
    unresolved = await db.scalars(
        select(ExecutionAttempt).where(
            ExecutionAttempt.project_id == project.id,
            ExecutionAttempt.environment_id == body.environment_id,
            ExecutionAttempt.status == "UNKNOWN_OUTCOME",
        )
    )
    if any(
        not a.result.get("reconciliation", {}).get("safe_to_start_new_attempt") for a in unresolved
    ):
        raise HTTPException(409, "unknown_delivery_requires_human_reconciliation")
    environment, profile, connection, binding, qualification = await active_qualification(
        db, project, body.environment_id, settings
    )
    state, candidate = await current_candidate(db, project)
    if not candidate or candidate.id != body.candidate_id:
        raise HTTPException(409, "current_candidate_required")
    if body.operation not in ADAPTER_CONTRACTS[binding["adapter"]]["operations"]:
        raise HTTPException(409, "operation_not_implemented_for_adapter")
    if environment.execution_mode != "SIMULATED" and body.scenario is not None:
        raise HTTPException(409, "simulator_scenario_forbidden")
    attempt = ExecutionAttempt(
        client_id=project.client_id,
        project_id=project.id,
        candidate_id=candidate.id,
        candidate_checksum=candidate.checksum,
        integration_pattern_version_id=project.integration_pattern_version_id,
        environment_id=environment.id,
        qualification_id=qualification.id,
        connection_id=connection.id if connection else None,
        adapter=binding["adapter"],
        adapter_version=ADAPTER_VERSION,
        operation=body.operation,
        idempotency_key=body.idempotency_key,
        requested_by_subject_id=subject,
        binding=binding,
        request={
            **body.model_dump(exclude={"candidate_id", "environment_id", "idempotency_key"}),
            "test_plan_sha256": sha256(json_bytes(state["manifest"].get("test_plan"))),
        },
    )
    db.add(attempt)
    await db.flush()
    await record_ownership_event(
        db,
        identity,
        "EXECUTION_REQUESTED",
        "ExecutionAttempt",
        attempt.id,
        client_id=project.client_id,
        details={
            "candidate_id": candidate.id,
            "environment_id": environment.id,
            "operation": body.operation,
        },
    )
    return attempt_response(attempt)


@router.get("/{attempt_id}")
async def get_attempt(
    project_id: str,
    attempt_id: str,
    db=Depends(get_db),
    identity: Identity = Depends(get_current_identity),
):
    project = await scoped_project(project_id, db, identity)
    return attempt_response(await owned_record(db, ExecutionAttempt, attempt_id, project))


@router.post("/{attempt_id}/approve")
async def approve(
    project_id: str,
    attempt_id: str,
    body: Acknowledgement,
    db=Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
):
    project = await scoped_project(
        project_id, db, identity, manage=True, roles=["CLIENT_ADMIN", "TESTER"]
    )
    attempt = await owned_record(db, ExecutionAttempt, attempt_id, project)
    if attempt.status != "AWAITING_APPROVAL":
        raise HTTPException(409, "execution_not_awaiting_approval")
    attempt.approved_by_subject_id = await actor_subject(db, identity)
    attempt.approval_expires_at = datetime.now(UTC) + timedelta(hours=1)
    await validate_attempt(db, attempt, settings)
    transition(attempt, "QUEUED")
    await record_ownership_event(
        db,
        identity,
        "EXECUTION_APPROVED",
        "ExecutionAttempt",
        attempt.id,
        client_id=project.client_id,
        details={
            "candidate_checksum": attempt.candidate_checksum,
            "environment_id": attempt.environment_id,
        },
    )
    return attempt_response(attempt)


@router.post("/{attempt_id}/cancel")
async def cancel(
    project_id: str,
    attempt_id: str,
    body: Acknowledgement,
    db=Depends(get_db),
    identity: Identity = Depends(get_current_identity),
):
    project = await scoped_project(
        project_id, db, identity, manage=True, roles=["CLIENT_ADMIN", "TESTER"]
    )
    attempt = await owned_record(db, ExecutionAttempt, attempt_id, project)
    # Never pretend cancellation can undo an already dispatched remote operation.
    transition(attempt, "CANCELLED")
    await record_ownership_event(
        db,
        identity,
        "EXECUTION_CANCELLED",
        "ExecutionAttempt",
        attempt.id,
        client_id=project.client_id,
    )
    return attempt_response(attempt)


@router.get("/{attempt_id}/evidence/{filename}")
async def download_evidence(
    project_id: str,
    attempt_id: str,
    filename: str,
    db=Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
):
    project = await scoped_project(project_id, db, identity)
    attempt = await owned_record(db, ExecutionAttempt, attempt_id, project)
    if filename == "reconciliation.json":
        ref = attempt.result.get("_private_reconciliation")
    else:
        evidence = await owned_record(
            db, SandboxEvidence, attempt.result.get("evidence_id", ""), project
        )
        ref = next(
            (item for item in evidence.observations["files"] if item["name"] == filename), None
        )
    if ref is None:
        raise HTTPException(404, "Evidence file not found")
    data = await read_asset_file(settings, ref["storage_path"], settings.erp_max_response_bytes)
    if sha256(data) != ref["sha256"]:
        raise HTTPException(409, "evidence_integrity_failed")
    return Response(
        data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/{attempt_id}/sign-off")
async def sign_off(
    project_id: str,
    attempt_id: str,
    body: Acknowledgement,
    db=Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
):
    project = await scoped_project(
        project_id, db, identity, manage=True, roles=["CLIENT_ADMIN", "TESTER"]
    )
    attempt = await owned_record(db, ExecutionAttempt, attempt_id, project)
    subject = await actor_subject(db, identity)
    from dataclasses import replace

    release = await release_attempt(db, attempt, replace(identity, subject_id=subject), settings)
    return {
        "id": release.id,
        "checksum": release.checksum,
        "simulated": release.manifest["simulated"],
        "download_url": f"/api/projects/{project.id}/package/releases/{release.id}/download",
    }


@router.post("/{attempt_id}/reconcile")
async def reconcile(
    project_id: str,
    attempt_id: str,
    body: Reconciliation,
    db=Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
):
    project = await scoped_project(
        project_id, db, identity, manage=True, roles=["CLIENT_ADMIN", "TESTER"]
    )
    attempt = await owned_record(db, ExecutionAttempt, attempt_id, project)
    if attempt.status != "UNKNOWN_OUTCOME" or attempt.result.get("reconciliation"):
        raise HTTPException(409, "unreconciled_unknown_attempt_required")
    subject = await actor_subject(db, identity)
    data = json_bytes(
        {
            "attempt_id": attempt.id,
            "outcome": body.outcome,
            "evidence_note": body.evidence_note,
            "actor_subject_id": subject,
            "recorded_at": datetime.now(UTC).isoformat(),
            "method": "ASSISTED_MANUAL",
        }
    )
    path = await save_asset_file(
        settings,
        asset_directory(settings, project.id, attempt.id, 1),
        "reconciliation.json",
        data,
        "application/json",
    )
    ref = {
        "name": "reconciliation.json",
        "storage_path": path,
        "sha256": sha256(data),
        "size_bytes": len(data),
    }
    attempt.result = {
        **attempt.result,
        "_private_reconciliation": ref,
        "reconciliation": {
            "outcome": body.outcome,
            "actor_subject_id": subject,
            "evidence_sha256": ref["sha256"],
            "safe_to_start_new_attempt": body.outcome != "REQUIRES_EXTERNAL_REVIEW",
        },
    }
    await record_ownership_event(
        db,
        identity,
        "EXECUTION_RECONCILED",
        "ExecutionAttempt",
        attempt.id,
        client_id=project.client_id,
        details={"outcome": body.outcome, "evidence_sha256": ref["sha256"]},
    )
    return attempt_response(attempt)


@router.post("/{attempt_id}/remediate", status_code=202)
async def remediate(
    project_id: str,
    attempt_id: str,
    body: dict,
    db=Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
):
    from app.api.generation import trigger_generation
    from app.schemas import GenerateRequest

    if (
        body.keys() != {"stage", "acknowledge"}
        or body.get("acknowledge") is not True
        or not isinstance(body.get("stage"), str)
    ):
        raise HTTPException(422, "reviewed_remediation_stage_required")
    return await trigger_generation(
        project_id,
        GenerateRequest(stage=body["stage"], execution_attempt_id=attempt_id),
        db,
        identity,
        settings,
    )


@router.get("/{attempt_id}/remediation-context")
async def remediation_context(
    project_id: str,
    attempt_id: str,
    db=Depends(get_db),
    identity: Identity = Depends(get_current_identity),
):
    project = await scoped_project(
        project_id,
        db,
        identity,
        roles=["CLIENT_ADMIN", "CONSULTANT", "TECHNICAL_REVIEWER", "TESTER"],
    )
    attempt = await owned_record(db, ExecutionAttempt, attempt_id, project)
    if attempt.status not in TERMINAL or (attempt.verdict == "PASSED" and not attempt.failure):
        raise HTTPException(409, "failed_or_inconclusive_attempt_required")
    return {
        "attempt_id": attempt.id,
        "candidate_id": attempt.candidate_id,
        "candidate_checksum": attempt.candidate_checksum,
        "profile_version_id": attempt.binding["profile_version_id"],
        "failure": attempt.failure,
        "verdict": attempt.verdict,
        "instruction": (
            "Propose a new engineering revision. Never alter approvals, evidence, assurance, "
            "expectations or release state. Unknown delivery requires human reconciliation "
            "before another execution."
        ),
        "customer_output_included": False,
        "credentials_included": False,
    }
