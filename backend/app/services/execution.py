"""Execution orchestration: authority, immutable bindings, private evidence and release."""

import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import (
    CapabilityQualification,
    ERPConnection,
    ERPEnvironment,
    ERPInstallation,
    ERPProfileVersion,
    ExecutionAttempt,
    IdentitySubject,
    PackageRelease,
    PlatformRoleAssignment,
    Project,
    SandboxEvidence,
)
from app.security.access import ensure_client_access
from app.security.identity import Identity
from app.services.artifact_storage import asset_directory, read_asset_file, save_asset_file
from app.services.execution_adapters import INSTALLED_EXECUTORS
from app.services.execution_contracts import (
    ADAPTER_CONTRACTS,
    ADAPTER_VERSION,
    CAPABILITIES,
    adapter_supports_pattern,
    assertions,
    failure,
    target_policy,
    transition,
    utc,
)
from app.services.integration_patterns import pattern_context, resolve_pattern
from app.services.ownership_audit import record_ownership_event
from app.services.packages import MAX_BUNDLE_BYTES, bundle, current_candidate, json_bytes, sha256
from app.services.project_revisions import lock_project


async def subject_identity(db, subject_id: str, settings) -> Identity:
    # Recheck a persisted approver/requester with its own role visibility only.
    # Client scope and privileges stay bounded to the current request/worker.
    from app.security.tenant_context import apply_tenant_context

    context = db.info.get("erpfusion_tenant_context")
    try:
        if context:
            await apply_tenant_context(db, **{**asdict(context), "subject_id": subject_id})
        subject = await db.get(IdentitySubject, subject_id, populate_existing=True)
        if not subject or subject.status != "ACTIVE":
            raise HTTPException(403, "execution_actor_inactive")
        roles = set(
            await db.scalars(
                select(PlatformRoleAssignment.role).where(
                    PlatformRoleAssignment.subject_id == subject.id,
                    PlatformRoleAssignment.status == "ACTIVE",
                )
            )
        )
    finally:
        if context:
            await apply_tenant_context(db, **asdict(context))
    # Only the explicitly configured local administrator retains fixture authority.
    if (
        not settings.is_production
        and settings.auth_mode == "development"
        and subject.issuer == "development"
        and subject.subject == settings.dev_identity_user_id
    ):
        roles.update(settings.dev_identity_roles)
    return Identity(
        user_id=subject.subject,
        issuer=subject.issuer,
        subject_id=subject.id,
        roles=frozenset(role.lower() for role in roles),
    )


async def qualification_target(db, project, environment_id: str) -> tuple:
    environment = await db.get(ERPEnvironment, environment_id, populate_existing=True)
    if not environment or environment.client_id != project.client_id:
        raise HTTPException(404, "ERP environment not found")
    installation = await db.get(
        ERPInstallation, environment.installation_id, populate_existing=True
    )
    if (
        not installation
        or installation.client_id != project.client_id
        or installation.erp_profile_id != project.erp_profile_id
        or installation.status != "ACTIVE"
        or installation.archived_at is not None
    ):
        raise HTTPException(409, "environment_installation_profile_mismatch")
    target_policy(environment)
    profile = await db.get(
        ERPProfileVersion, project.erp_profile_version_id, populate_existing=True
    )
    if not profile or profile.status != "PUBLISHED" or profile.profile_id != project.erp_profile_id:
        raise HTTPException(409, "published_profile_version_required")
    return environment, installation, profile


async def assisted_binding(db, project, environment_id, *, release=False):
    environment, installation, profile = await qualification_target(db, project, environment_id)
    if environment.execution_mode == "SIMULATED":
        raise HTTPException(409, "simulated_target_requires_machine_simulated_evidence")
    context = await pattern_context(db, project)
    if not context:
        return None
    target_code = (
        "ERPFUSION_SANDBOX"
        if environment.custody == "ERPFUSION_MANAGED"
        else "CUSTOMER_" + environment.environment_type
    )
    if target_code not in context["configuration"].get("supported_environments", []):
        raise HTTPException(409, "pattern_environment_not_supported")
    policy = context["configuration"].get("qualification_policy", {})
    if release and (
        "ASSISTED" not in policy.get("allowed_modes", [])
        or not set(policy.get("required_assurance", []))
        <= {"ASSISTED_MANUAL", "APPLICATION_STATIC_VALIDATION"}
    ):
        raise HTTPException(409, "pattern_release_requires_higher_assurance_than_manual_evidence")
    connection = await db.scalar(
        select(ERPConnection)
        .where(
            ERPConnection.client_id == project.client_id,
            ERPConnection.installation_id == installation.id,
            ERPConnection.environment_id == environment.id,
        )
        .execution_options(populate_existing=True)
    )
    return {
        "integration_pattern_version_id": context["version_id"],
        "pattern_contract_sha256": context["contract_sha256"],
        "baseline_versions": context["baseline_versions"],
        "environment_id": environment.id,
        "environment_type": environment.environment_type,
        "custody": environment.custody,
        "execution_mode": environment.execution_mode,
        "endpoint_url": environment.endpoint_url,
        "environment_configuration_sha256": sha256(json_bytes(environment.configuration)),
        "installation_id": installation.id,
        "edition": installation.edition,
        "product_version": installation.product_version,
        "connection_id": connection.id if connection else None,
        "connection_version": connection.configuration_version if connection else None,
        "secret_version": connection.secret_version if connection else None,
    }


async def target_binding(db, project, environment_id: str, settings) -> tuple:
    environment, installation, profile = await qualification_target(db, project, environment_id)
    if not project.integration_pattern_version_id:
        raise HTTPException(409, "integration_pattern_required_for_execution")
    pattern, pattern_version = await resolve_pattern(
        db,
        project.integration_pattern_version_id,
        profile_id=project.erp_profile_id,
        profile_version_id=profile.id,
        installation=installation,
        allow_retired=True,
    )
    context = await pattern_context(db, project)
    config = pattern_version.configuration
    target_code = (
        "ERPFUSION_SANDBOX"
        if environment.custody == "ERPFUSION_MANAGED"
        else "CUSTOMER_" + environment.environment_type
    )
    if target_code not in config.get("supported_environments", []):
        raise HTTPException(409, "pattern_environment_not_supported")
    adapter = config.get("adapter_bindings", {}).get(environment.execution_mode)
    if adapter not in CAPABILITIES:
        raise HTTPException(409, "pattern_execution_adapter_not_implemented")
    installed = ADAPTER_CONTRACTS[adapter]
    if environment.execution_mode not in installed["modes"]:
        raise HTTPException(409, "adapter_execution_mode_mismatch")
    if not adapter_supports_pattern(
        adapter,
        environment.execution_mode,
        pattern_version.runtime_type,
        pattern_version.deliverable_type,
    ):
        raise HTTPException(409, "pattern_deliverable_not_supported_by_adapter")
    if environment.execution_mode == "SIMULATED" and (
        settings.is_production or not settings.execution_simulator_enabled
    ):
        raise HTTPException(409, "execution_simulator_disabled")
    connection = await db.scalar(
        select(ERPConnection)
        .where(
            ERPConnection.environment_id == environment.id,
            ERPConnection.client_id == project.client_id,
            ERPConnection.installation_id == installation.id,
        )
        .execution_options(populate_existing=True)
    )
    if environment.execution_mode == "REMOTE" and (
        not connection
        or connection.adapter != adapter
        or not connection.secret_ref
        or not connection.secret_version
    ):
        raise HTTPException(409, "qualified_connection_required")
    binding = {
        "client_id": project.client_id,
        "profile_version_id": profile.id,
        "integration_pattern_version_id": pattern_version.id,
        "pattern_contract_sha256": context["contract_sha256"],
        "baseline_versions": context["baseline_versions"],
        "runtime_type": pattern_version.runtime_type,
        "qualification_strategy": pattern_version.qualification_strategy,
        "environment_id": environment.id,
        "installation_id": installation.id,
        "edition": installation.edition,
        "product_version": installation.product_version,
        "environment_type": environment.environment_type,
        "custody": environment.custody,
        "execution_mode": environment.execution_mode,
        "endpoint_url": environment.endpoint_url,
        "environment_configuration_sha256": sha256(json_bytes(environment.configuration)),
        "adapter": adapter,
        "adapter_version": ADAPTER_VERSION,
        "connection_id": connection.id if connection else None,
        "connection_version": connection.configuration_version if connection else None,
        "secret_version": connection.secret_version if connection else None,
        "connection_configuration_sha256": sha256(
            json_bytes(
                {
                    "source_url": connection.source_url,
                    "report_path": connection.report_path,
                    "expected_tenant": connection.expected_tenant,
                    "approved_hosts": connection.approved_hosts,
                    "permitted_operations": connection.permitted_operations,
                    "vendor_configuration": connection.vendor_configuration,
                }
            )
        )
        if connection
        else None,
    }
    return environment, pattern_version, connection, binding


async def active_qualification(db, project, environment_id, settings):
    environment, profile, connection, binding = await target_binding(
        db, project, environment_id, settings
    )
    qualifications = await db.scalars(
        select(CapabilityQualification)
        .where(
            CapabilityQualification.client_id == project.client_id,
            CapabilityQualification.environment_id == environment_id,
            CapabilityQualification.status == "ACTIVE",
        )
        .order_by(CapabilityQualification.created_at.desc())
    )
    for qualification in qualifications:
        if (
            qualification.binding == binding
            and qualification.adapter_version == ADAPTER_VERSION
            and utc(qualification.expires_at) > datetime.now(UTC)
        ):
            authority = await subject_identity(db, qualification.approved_by_subject_id, settings)
            await ensure_client_access(
                db, authority, project.client_id, allowed_roles=["CLIENT_ADMIN"]
            )
            return environment, profile, connection, binding, qualification
    raise HTTPException(409, "environment_capability_qualification_required")


async def validate_attempt(db, attempt, settings, *, require_unexpired_approval=True):
    project = await db.get(Project, attempt.project_id)
    if not project or project.client_id != attempt.client_id or project.archived_at is not None:
        raise HTTPException(409, "execution_project_unavailable")
    project = await lock_project(db, project)
    requester = await subject_identity(db, attempt.requested_by_subject_id, settings)
    await ensure_client_access(
        db, requester, attempt.client_id, allowed_roles=["CLIENT_ADMIN", "TESTER"]
    )
    if (
        not attempt.approved_by_subject_id
        or not attempt.approval_expires_at
        or (require_unexpired_approval and utc(attempt.approval_expires_at) <= datetime.now(UTC))
    ):
        raise HTTPException(409, "execution_approval_expired")
    approver = await subject_identity(db, attempt.approved_by_subject_id, settings)
    await ensure_client_access(
        db, approver, attempt.client_id, allowed_roles=["CLIENT_ADMIN", "TESTER"]
    )
    environment, profile, connection, binding, qualification = await active_qualification(
        db, project, attempt.environment_id, settings
    )
    if attempt.qualification_id != qualification.id or attempt.binding != binding:
        raise HTTPException(409, "execution_binding_changed")
    state, candidate = await current_candidate(db, project)
    if (
        not candidate
        or candidate.id != attempt.candidate_id
        or candidate.checksum != attempt.candidate_checksum
    ):
        raise HTTPException(409, "execution_candidate_superseded")
    if (
        sha256(json_bytes(state["manifest"].get("test_plan")))
        != attempt.request["test_plan_sha256"]
    ):
        raise HTTPException(409, "execution_test_plan_changed")
    if (
        attempt.integration_pattern_version_id != profile.id
        or candidate.integration_pattern_version_id != profile.id
    ):
        raise HTTPException(409, "execution_pattern_binding_changed")
    required = (
        set(profile.configuration.get("required_capabilities", []))
        if attempt.operation == "QUALIFY_CANDIDATE"
        else {attempt.operation}
    )
    profile_caps = set(profile.configuration.get("required_capabilities", [])) | set(
        profile.configuration.get("optional_capabilities", [])
    )
    if (
        not required
        <= set(qualification.capabilities) & set(CAPABILITIES[attempt.adapter]) & profile_caps
    ):
        raise HTTPException(409, "execution_capability_not_qualified")
    if (
        environment.execution_mode == "REMOTE"
        and connection
        and attempt.operation not in connection.permitted_operations
        and attempt.operation != "CHECK_REPORT_ACCESS"
    ):
        raise HTTPException(409, "execution_operation_not_permitted")
    if attempt.adapter != "oracle_simulator" and attempt.request.get("scenario") is not None:
        raise HTTPException(409, "simulator_scenario_forbidden")
    if candidate.manifest.get("format_version") == 1 and (
        candidate.manifest.get("environment_id") != environment.id
        or candidate.manifest.get("installation_id") != environment.installation_id
    ):
        raise HTTPException(409, "legacy_candidate_target_bound")
    return project, environment, profile, connection, candidate, requester


async def persist_evidence(db, attempt, candidate, result, settings):
    output = result["output"]
    cases, verdict = (
        assertions(output, candidate.manifest.get("test_plan"))
        if not result["failure"]
        else ([], "FAILED")
    )
    if attempt.operation == "CHECK_REPORT_ACCESS":
        verdict = "INCONCLUSIVE"
    assurance = ["APPLICATION_STATIC_VALIDATION", *result["assurance"]]
    if verdict == "PASSED":
        assurance.append(
            "SIMULATED_FUNCTIONAL_ASSERTIONS_PASSED"
            if attempt.adapter == "oracle_simulator"
            else "FUNCTIONAL_ASSERTIONS_PASSED"
        )
    files = {
        "output.csv": output,
        "receipt.json": json_bytes(result["receipt"]),
        "logs.json": json_bytes(
            {
                "attempt_id": attempt.id,
                "failure": result["failure"],
                "execution_history": result["receipt"].get("execution_history", []),
            }
        ),
        "assertions.json": json_bytes({"verdict": verdict, "cases": cases}),
    }
    refs = []
    for name, data in files.items():
        path = await save_asset_file(
            settings,
            asset_directory(settings, attempt.project_id, attempt.id, 1),
            name,
            data,
            "text/csv" if name.endswith("csv") else "application/json",
        )
        refs.append(
            {"name": name, "storage_path": path, "sha256": sha256(data), "size_bytes": len(data)}
        )
    observations = {
        "attempt_id": attempt.id,
        "candidate_checksum": candidate.checksum,
        "environment_id": attempt.environment_id,
        "connection_version": attempt.binding["connection_version"],
        "secret_version": attempt.binding["secret_version"],
        "qualification_id": attempt.qualification_id,
        "test_plan_sha256": attempt.request["test_plan_sha256"],
        "parameters_sha256": sha256(json_bytes(attempt.request.get("parameters", {}))),
        "receipt": result["receipt"],
        "files": refs,
        "cases": cases,
        "assurance": assurance,
        "verdict": verdict,
        "simulated": attempt.adapter == "oracle_simulator",
    }
    evidence = SandboxEvidence(
        project_id=attempt.project_id,
        client_id=attempt.client_id,
        candidate_id=candidate.id,
        environment_id=attempt.environment_id,
        candidate_checksum=candidate.checksum,
        connection_version=attempt.binding["connection_version"],
        status=verdict,
        method="SIMULATED" if attempt.adapter == "oracle_simulator" else "REMOTE_API",
        execution_attempt_id=attempt.id,
        observations=observations,
        tester_subject_id=attempt.approved_by_subject_id,
    )
    db.add(evidence)
    await db.flush()
    attempt.result = {
        "evidence_id": evidence.id,
        "files": [{k: v for k, v in ref.items() if k != "storage_path"} for ref in refs],
    }
    attempt.assurance, attempt.verdict = assurance, verdict
    attempt.failure = (
        {**result["failure"], "evidence_reference": evidence.id} if result["failure"] else {}
    )
    return evidence


async def process_attempt(db: AsyncSession, attempt_id: str, settings: Settings) -> bool:
    claimed = await db.scalar(
        update(ExecutionAttempt)
        .where(
            ExecutionAttempt.id == attempt_id,
            ExecutionAttempt.status == "QUEUED",
        )
        .values(
            status="DISPATCHING",
            started_at=datetime.now(UTC),
            deadline_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        .returning(ExecutionAttempt.id)
    )
    if not claimed:
        return False
    attempt = await db.get(ExecutionAttempt, attempt_id, populate_existing=True)
    if attempt is None:
        raise RuntimeError("claimed_execution_attempt_missing")
    try:
        project, environment, profile, connection, candidate, requester = await validate_attempt(
            db, attempt, settings
        )
        candidate_bytes = await read_asset_file(settings, candidate.storage_path, MAX_BUNDLE_BYTES)
        if sha256(candidate_bytes) != candidate.checksum:
            raise HTTPException(409, "candidate_integrity_failed")
    except HTTPException as exc:
        attempt.status = (
            "SUPERSEDED" if exc.detail == "execution_candidate_superseded" else "BLOCKED"
        )
        attempt.completed_at = datetime.now(UTC)
        attempt.failure = {
            **failure("INFRASTRUCTURE_ERROR", attempt, phase="preflight"),
            "safe_message": str(exc.detail),
        }
        await db.commit()
        return True
    except Exception:
        attempt.status = "BLOCKED"
        attempt.failure = failure("INFRASTRUCTURE_ERROR", attempt, phase="integrity")
        attempt.completed_at = datetime.now(UTC)
        await db.commit()
        return True
    # Commit approval checks and claim before dispatch; never hold a project lock over I/O.
    await record_ownership_event(
        db,
        requester,
        "EXECUTION_DISPATCHED",
        "ExecutionAttempt",
        attempt.id,
        client_id=attempt.client_id,
    )
    await db.commit()
    try:
        result = await INSTALLED_EXECUTORS[attempt.adapter](
            db, attempt, candidate, settings, connection
        )
        transition(attempt, "REMOTE_RUNNING")
        attempt.external_execution_id = result["external_execution_id"]
        await db.commit()
        transition(attempt, "COLLECTING_EVIDENCE")
        await db.commit()
        await persist_evidence(db, attempt, candidate, result, settings)
        try:
            await validate_attempt(db, attempt, settings)
            applicable = True
        except HTTPException:
            applicable = False
        if result["failure"]:
            transition(
                attempt, "FAILED" if result["failure"]["outcome_known"] else "UNKNOWN_OUTCOME"
            )
        else:
            transition(attempt, "COMPLETED" if applicable else "SUPERSEDED")
        if not applicable:
            attempt.verdict = "INCONCLUSIVE"
        await record_ownership_event(
            db,
            requester,
            "EXECUTION_COMPLETED",
            "ExecutionAttempt",
            attempt.id,
            client_id=attempt.client_id,
            details={"status": attempt.status, "verdict": attempt.verdict},
        )
        await db.commit()
    except Exception:
        await db.rollback()
        attempt = await db.get(ExecutionAttempt, attempt_id, populate_existing=True)
        # A dispatched call or evidence write may have succeeded. Never resend it.
        if attempt is not None and attempt.status not in {"COMPLETED", "FAILED", "SUPERSEDED"}:
            attempt.status = "UNKNOWN_OUTCOME"
            attempt.failure = failure(
                "UNKNOWN_OUTCOME", attempt, phase="dispatch_or_collection", unknown=True
            )
            attempt.completed_at = datetime.now(UTC)
            await db.commit()
    return True


async def expire_attempts(db: AsyncSession) -> int:
    attempts = await db.scalars(
        select(ExecutionAttempt)
        .where(
            ExecutionAttempt.status.in_(["DISPATCHING", "REMOTE_RUNNING", "COLLECTING_EVIDENCE"]),
            ExecutionAttempt.deadline_at < datetime.now(UTC),
        )
        .with_for_update()
    )
    count = 0
    for attempt in attempts:
        attempt.status = "UNKNOWN_OUTCOME"
        attempt.failure = failure("UNKNOWN_OUTCOME", attempt, phase="worker_recovery", unknown=True)
        attempt.completed_at = datetime.now(UTC)
        count += 1
    await db.commit()
    return count


async def release_attempt(db, attempt, actor, settings):
    project, environment, profile, connection, candidate, requester = await validate_attempt(
        db, attempt, settings, require_unexpired_approval=False
    )
    if attempt.status != "COMPLETED" or attempt.verdict != "PASSED" or attempt.failure:
        raise HTTPException(409, "passing_applicable_execution_required")
    policy = profile.configuration.get("qualification_policy", {})
    mode = "SIMULATED" if attempt.adapter == "oracle_simulator" else "REMOTE"
    if (
        mode == "REMOTE"
        and profile.qualification_strategy == "NATIVE_ARTIFACT"
        and "REMOTE_ARTIFACT_IDENTITY_VERIFIED" not in attempt.assurance
    ):
        raise HTTPException(409, "remote_candidate_identity_not_verified")
    required = set(policy.get("required_assurance", []))
    if (
        mode not in policy.get("allowed_modes", [])
        or not required
        or not required <= set(attempt.assurance)
    ):
        raise HTTPException(409, "release_assurance_policy_not_satisfied")
    newer = await db.scalar(
        select(ExecutionAttempt.id)
        .where(
            ExecutionAttempt.project_id == project.id,
            ExecutionAttempt.candidate_id == candidate.id,
            ExecutionAttempt.environment_id == environment.id,
            ExecutionAttempt.created_at > attempt.created_at,
            ExecutionAttempt.status.not_in(["CANCELLED", "SUPERSEDED"]),
        )
        .limit(1)
    )
    if newer:
        raise HTTPException(409, "latest_environment_execution_required")
    evidence = await db.get(SandboxEvidence, attempt.result["evidence_id"])
    output_ref = next(ref for ref in evidence.observations["files"] if ref["name"] == "output.csv")
    output = await read_asset_file(
        settings, output_ref["storage_path"], settings.erp_max_response_bytes
    )
    if sha256(output) != output_ref["sha256"]:
        raise HTTPException(409, "evidence_integrity_failed")
    cases, verdict = assertions(output, candidate.manifest.get("test_plan"))
    if verdict != "PASSED" or cases != evidence.observations["cases"]:
        raise HTTPException(409, "functional_assertions_not_passed")
    existing = await db.scalar(
        select(PackageRelease).where(
            PackageRelease.candidate_id == candidate.id, PackageRelease.evidence_id == evidence.id
        )
    )
    if existing:
        return existing
    data = await read_asset_file(settings, candidate.storage_path, MAX_BUNDLE_BYTES)
    if sha256(data) != candidate.checksum:
        raise HTTPException(409, "candidate_integrity_failed")
    manifest = {
        "product": "HighStudio",
        "kind": "release",
        "candidate_id": candidate.id,
        "candidate_checksum": candidate.checksum,
        "evidence_id": evidence.id,
        "execution_attempt_id": attempt.id,
        "integration_pattern_version_id": attempt.integration_pattern_version_id,
        "baseline_versions": attempt.binding["baseline_versions"],
        "qualification_strategy": attempt.binding["qualification_strategy"],
        "environment_id": environment.id,
        "qualification_id": attempt.qualification_id,
        "method": mode,
        "assurance": attempt.assurance,
        "simulated": mode == "SIMULATED",
        "remote_exact_bytes_verified": "REMOTE_ARTIFACT_IDENTITY_VERIFIED" in attempt.assurance,
        "production_deployment": "CUSTOMER_RESPONSIBILITY",
        "signer_subject_id": actor.subject_id,
        "signed_at": datetime.now(UTC).isoformat(),
    }
    payload = {"candidate.zip": data, "release-manifest.json": json_bytes(manifest)}
    for ref in evidence.observations["files"]:
        raw = await read_asset_file(settings, ref["storage_path"], settings.erp_max_response_bytes)
        if sha256(raw) != ref["sha256"]:
            raise HTTPException(409, "evidence_integrity_failed")
        payload[f"evidence/{ref['name']}"] = raw
    zipped = bundle(payload)
    identifier = str(uuid.uuid4())
    path = await save_asset_file(
        settings,
        asset_directory(settings, project.id, identifier, 1),
        "release.zip",
        zipped,
        "application/zip",
    )
    release = PackageRelease(
        id=identifier,
        client_id=project.client_id,
        project_id=project.id,
        candidate_id=candidate.id,
        evidence_id=evidence.id,
        checksum=sha256(zipped),
        manifest=manifest,
        storage_path=path,
        approved_by_subject_id=actor.subject_id,
    )
    db.add(release)
    project.workflow_status = "RELEASED"
    await record_ownership_event(
        db,
        actor,
        "PACKAGE_RELEASE_SIGNED",
        "PackageRelease",
        identifier,
        client_id=project.client_id,
        details={
            "attempt_id": attempt.id,
            "assurance": attempt.assurance,
            "simulated": mode == "SIMULATED",
        },
    )
    await db.flush()
    return release
