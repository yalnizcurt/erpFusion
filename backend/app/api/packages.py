"""Immutable candidates, assisted test attestations, and authenticated release sign-off."""

import io
import uuid
import zipfile
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.connections import authorized_environment, get_connection
from app.config import Settings, get_settings
from app.database import get_db
from app.models import Project
from app.models.engineering import PackageCandidate, PackageRelease, SandboxEvidence
from app.security.access import ensure_client_access, get_authorized_project, resolved_identity
from app.security.identity import Identity, get_current_identity
from app.services.artifact_storage import (
    ArtifactStorageError,
    asset_directory,
    read_asset_file,
    save_asset_file,
)
from app.services.execution_contracts import target_policy
from app.services.ownership_audit import actor_subject, record_ownership_event
from app.services.packages import (
    MAX_BUNDLE_BYTES,
    bundle,
    create_candidate,
    current_candidate,
    current_release,
    json_bytes,
    latest_evidence,
    safe_name,
    sha256,
)
from app.services.project_revisions import lock_project

router = APIRouter(prefix="/api/projects/{project_id}", tags=["Packages and sandbox evidence"])


class CaseEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=128)
    status: Literal["PASSED", "FAILED", "BLOCKED", "NOT_RUN"]
    expected: Any
    actual: Any
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_note: str = Field(default="", max_length=4000)


class EvidenceSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(min_length=1, max_length=36)
    environment_id: str = Field(min_length=1, max_length=36)
    candidate_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewed_source_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    connection_version: int | None = Field(default=None, ge=1)
    test_plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    cases: list[CaseEvidence] = Field(min_length=1, max_length=100)
    acknowledge_assisted_evidence: Literal[True]

    @model_validator(mode="before")
    @classmethod
    def legacy_source_checksum(cls, value):
        if isinstance(value, dict) and "installed_candidate_checksum" in value:
            value = dict(value)
            old_checksum = value.pop("installed_candidate_checksum")
            value.setdefault("reviewed_source_checksum", old_checksum)
        return value


class AssistedSignOff(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acknowledge_assisted_evidence: Literal[True]


async def scoped_project(
    project_id: str,
    db: AsyncSession,
    identity: Identity,
    *,
    manage: bool = False,
    roles: list[str] | None = None,
) -> Project:
    actor = resolved_identity(identity)
    project = await get_authorized_project(project_id, db, actor, allow_legacy_fixture=False)
    if not project.client_id:
        raise HTTPException(404, "Project not found")
    if roles:
        await ensure_client_access(db, actor, project.client_id, allowed_roles=roles)
    if manage:
        project = await lock_project(db, project)
        if project.archived_at is not None:
            raise HTTPException(409, "project_archived")
    return project


async def owned_record(db: AsyncSession, model: Any, identifier: str, project: Project):
    record = (
        await db.execute(
            select(model).where(
                model.id == identifier,
                model.project_id == project.id,
                model.client_id == project.client_id,
            )
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(404, "Package record not found")
    return record


async def verified_bytes(record: PackageCandidate | PackageRelease, settings: Settings) -> bytes:
    try:
        data = await read_asset_file(
            settings, record.storage_path, MAX_BUNDLE_BYTES + 2 * 1024 * 1024
        )
    except ArtifactStorageError:
        raise HTTPException(503, "package_storage_unavailable") from None
    if sha256(data) != record.checksum:
        raise HTTPException(503, "package_integrity_failed")
    return data


def file_response(data: bytes, filename: str) -> Response:
    return Response(
        data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def evidence_response(evidence: SandboxEvidence) -> dict:
    return {
        "id": evidence.id,
        "candidate_id": evidence.candidate_id,
        "environment_id": evidence.environment_id,
        "candidate_checksum": evidence.candidate_checksum,
        "connection_version": evidence.connection_version,
        "status": evidence.status,
        "method": evidence.method,
        "observations": {
            **evidence.observations,
            "files": [
                {key: value for key, value in item.items() if key != "storage_path"}
                for item in evidence.observations.get("files", [])
            ],
        },
        "execution_attempt_id": evidence.execution_attempt_id,
        "tester_subject_id": evidence.tester_subject_id,
        "created_at": evidence.created_at,
    }


@router.get("/package")
async def get_package(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> dict:
    project = await scoped_project(project_id, db, identity)
    state, candidate = await current_candidate(db, project)
    release = await current_release(db, project, candidate) if candidate else None
    state.update(
        {
            "candidate_id": candidate.id if candidate else None,
            "candidate_checksum": candidate.checksum if candidate else None,
            "release_id": release.id if release else None,
            "kind": "release" if release else "candidate",
        }
    )
    return state


@router.get("/package/releases")
async def list_releases(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> dict:
    project = await scoped_project(project_id, db, identity)
    releases = await db.scalars(
        select(PackageRelease)
        .where(
            PackageRelease.project_id == project.id, PackageRelease.client_id == project.client_id
        )
        .order_by(PackageRelease.created_at.desc())
        .limit(100)
    )
    return {
        "releases": [
            {
                "id": row.id,
                "candidate_id": row.candidate_id,
                "evidence_id": row.evidence_id,
                "checksum": row.checksum,
                "created_at": row.created_at,
                "manifest": row.manifest,
                "download_url": f"/api/projects/{project.id}/package/releases/{row.id}/download",
            }
            for row in releases
        ]
    }


@router.post("/package/candidates", status_code=201)
async def build_candidate(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
) -> dict:
    actor = resolved_identity(identity)
    project = await scoped_project(
        project_id,
        db,
        actor,
        manage=True,
        roles=["CLIENT_ADMIN", "CONSULTANT", "TECHNICAL_REVIEWER"],
    )
    try:
        candidate = await create_candidate(db, project, settings)
    except ArtifactStorageError:
        raise HTTPException(503, "package_storage_unavailable") from None
    await record_ownership_event(
        db,
        actor,
        "PACKAGE_CANDIDATE_CREATED",
        "PackageCandidate",
        candidate.id,
        client_id=project.client_id,
        details={"checksum": candidate.checksum},
    )
    return {
        "id": candidate.id,
        "checksum": candidate.checksum,
        "download_url": f"/api/projects/{project.id}/package/candidates/{candidate.id}/download",
    }


@router.get("/package/download")
async def download_current_package(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
) -> Response:
    project = await scoped_project(project_id, db, identity)
    state, candidate = await current_candidate(db, project)
    if not candidate:
        raise HTTPException(409, {"blockers": state["blockers"] or ["create_candidate_first"]})
    release = await current_release(db, project, candidate)
    record = release or candidate
    return file_response(
        await verified_bytes(record, settings),
        f"project-{project.id}-{'release' if release else 'candidate'}.zip",
    )


@router.get("/package/candidates/{candidate_id}/download")
async def download_historical_candidate(
    project_id: str,
    candidate_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
) -> Response:
    project = await scoped_project(project_id, db, identity)
    candidate = await owned_record(db, PackageCandidate, candidate_id, project)
    return file_response(await verified_bytes(candidate, settings), f"candidate-{candidate.id}.zip")


@router.get("/package/releases/{release_id}/download")
async def download_historical_release(
    project_id: str,
    release_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
) -> Response:
    project = await scoped_project(project_id, db, identity)
    release = await owned_record(db, PackageRelease, release_id, project)
    return file_response(await verified_bytes(release, settings), f"release-{release.id}.zip")


@router.get("/package/candidates/{candidate_id}/files")
async def download_candidate_file(
    project_id: str,
    candidate_id: str,
    name: str = Query(min_length=1, max_length=255),
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Download exact approved source bytes, including configured PL/SQL files."""
    project = await scoped_project(project_id, db, identity)
    candidate = await owned_record(db, PackageCandidate, candidate_id, project)
    safe_name(name)
    entry = next((item for item in candidate.manifest["files"] if item["name"] == name), None)
    if entry is None:
        raise HTTPException(404, "Package file not found")
    data = await verified_bytes(candidate, settings)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo(name)
            if info.file_size != entry["size_bytes"] or info.file_size > MAX_BUNDLE_BYTES:
                raise HTTPException(503, "package_integrity_failed")
            source = archive.read(info)
    except (zipfile.BadZipFile, KeyError, RuntimeError):
        raise HTTPException(503, "package_integrity_failed") from None
    if sha256(source) != entry["sha256"]:
        raise HTTPException(503, "package_integrity_failed")
    filename = quote(name.rsplit("/", 1)[-1], safe="")
    return Response(
        source,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/sandbox/evidence")
async def list_evidence(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> dict:
    project = await scoped_project(project_id, db, identity)
    state, candidate = await current_candidate(db, project)
    records = (
        await db.execute(
            select(SandboxEvidence)
            .where(
                SandboxEvidence.project_id == project.id,
                SandboxEvidence.client_id == project.client_id,
            )
            .order_by(SandboxEvidence.created_at.desc())
            .limit(100)
        )
    ).scalars()
    plan = state["manifest"]["test_plan"]
    pattern = state["manifest"].get("integration_pattern")
    policy = pattern["configuration"].get("qualification_policy", {}) if pattern else {}
    assisted_allowed = not pattern or (
        "ASSISTED" in policy.get("allowed_modes", [])
        and set(policy.get("required_assurance", []))
        <= {"ASSISTED_MANUAL", "APPLICATION_STATIC_VALIDATION"}
    )
    return {
        "evidence": [evidence_response(record) for record in records],
        "candidate_id": candidate.id if candidate else None,
        "test_plan": plan,
        "test_plan_sha256": sha256(json_bytes(plan)) if plan else None,
        "blockers": state["blockers"] + ([] if plan else ["test_plan_not_configured"]),
        "automatic_execution_supported": False,
        "automatic_execution_blocker": "native_candidate_import_not_qualified",
        "assisted_release_allowed": assisted_allowed,
        "manual_connection_required": not bool(pattern),
    }


@router.post("/sandbox/evidence", status_code=201)
async def submit_evidence(
    project_id: str,
    body: EvidenceSubmit,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> dict:
    actor = resolved_identity(identity)
    project = await scoped_project(
        project_id, db, actor, manage=True, roles=["CLIENT_ADMIN", "TESTER"]
    )
    state, candidate = await current_candidate(db, project)
    if not candidate or candidate.id != body.candidate_id:
        raise HTTPException(409, "current_approved_candidate_required")
    if (
        body.candidate_checksum != candidate.checksum
        or body.reviewed_source_checksum != candidate.checksum
    ):
        raise HTTPException(409, "candidate_checksum_mismatch")
    if body.environment_id != project.erp_environment_id or not project.erp_installation_id:
        raise HTTPException(409, "selected_project_environment_required")
    if not project.client_id or not project.erp_installation_id:
        raise HTTPException(409, "selected_project_environment_required")
    environment = await authorized_environment(
        project.client_id, project.erp_installation_id, body.environment_id, db, actor, lock=True
    )
    target_policy(environment)
    from app.services.execution import assisted_binding

    binding = await assisted_binding(db, project, environment.id)
    connection = None
    if binding is None:
        connection = await get_connection(
            db, project.client_id, project.erp_installation_id, environment.id
        )
        if (
            connection.configuration_version != body.connection_version
            or not connection.secret_version
        ):
            raise HTTPException(409, "current_connection_version_required")
    elif binding["connection_version"] != body.connection_version:
        raise HTTPException(409, "current_connection_version_required")
    plan = state["manifest"]["test_plan"]
    if not plan:
        raise HTTPException(409, "test_plan_not_configured")
    if sha256(json_bytes(plan)) != body.test_plan_sha256:
        raise HTTPException(409, "approved_test_plan_mismatch")
    cases = {case.id: case for case in body.cases}
    if len(cases) != len(body.cases):
        raise HTTPException(422, "duplicate_test_case")
    required = {case["id"]: case["expected"] for case in plan["required_cases"]}
    if set(cases) != set(required):
        raise HTTPException(409, "mandatory_test_cases_missing_or_unknown")
    if any(json_bytes(case.expected) != json_bytes(required[name]) for name, case in cases.items()):
        raise HTTPException(409, "independent_expected_fixture_mismatch")
    if any(
        case.evidence_note and sha256(case.evidence_note.encode()) != case.evidence_sha256
        for case in body.cases
    ):
        raise HTTPException(409, "test_observation_checksum_mismatch")
    outcomes = {case.status for case in body.cases}
    assertion_failure = any(
        case.status == "PASSED" and json_bytes(case.actual) != json_bytes(case.expected)
        for case in body.cases
    )
    status = (
        "PASSED"
        if outcomes == {"PASSED"} and not assertion_failure
        else (
            "FAILED"
            if "FAILED" in outcomes or assertion_failure
            else ("NOT_RUN" if outcomes == {"NOT_RUN"} else "BLOCKED")
        )
    )
    observations = {
        "test_plan": plan,
        "test_plan_sha256": body.test_plan_sha256,
        "cases": [case.model_dump() for case in body.cases],
        "reviewed_source_checksum": body.reviewed_source_checksum,
        "secret_version": connection.secret_version if connection else binding["secret_version"],
        "pattern_binding": binding,
        "assurance": "authenticated_tester_attestation",
        "remote_exact_bytes_verified": False,
        "acknowledge_assisted_evidence": True,
    }
    if len(json_bytes(observations)) > 256 * 1024:
        raise HTTPException(413, "test_evidence_size_limit_exceeded")
    tester = await actor_subject(db, actor)
    if not tester:
        raise HTTPException(403, "authenticated_tester_subject_required")
    evidence = SandboxEvidence(
        project_id=project.id,
        client_id=project.client_id,
        candidate_id=candidate.id,
        environment_id=environment.id,
        candidate_checksum=candidate.checksum,
        connection_version=connection.configuration_version
        if connection
        else binding["connection_version"],
        status=status,
        method="ASSISTED_MANUAL",
        observations=observations,
        tester_subject_id=tester,
    )
    db.add(evidence)
    await db.flush()
    await record_ownership_event(
        db,
        actor,
        "SANDBOX_EVIDENCE_RECORDED",
        "SandboxEvidence",
        evidence.id,
        client_id=project.client_id,
        details={"status": status, "candidate_id": candidate.id},
    )
    project.last_activity_at = datetime.now(UTC)
    project.workflow_status = "READY_FOR_RELEASE" if status == "PASSED" else "SANDBOX_BLOCKED"
    return evidence_response(evidence)


@router.post("/sandbox/evidence/{evidence_id}/sign-off", status_code=201)
async def sign_off(
    project_id: str,
    evidence_id: str,
    body: AssistedSignOff,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
) -> dict:
    actor = resolved_identity(identity)
    project = await scoped_project(
        project_id, db, actor, manage=True, roles=["CLIENT_ADMIN", "TESTER"]
    )
    evidence = await owned_record(db, SandboxEvidence, evidence_id, project)
    state, candidate = await current_candidate(db, project)
    if (
        not candidate
        or candidate.id != evidence.candidate_id
        or evidence.candidate_checksum != candidate.checksum
        or evidence.status != "PASSED"
        or not evidence.tester_subject_id
        or evidence.environment_id != project.erp_environment_id
    ):
        raise HTTPException(409, "current_successful_test_evidence_required")
    latest = await latest_evidence(db, project, candidate)
    if not latest or latest.id != evidence.id:
        raise HTTPException(409, "latest_test_evidence_required")
    if not project.client_id or not project.erp_installation_id:
        raise HTTPException(409, "selected_project_environment_required")
    environment = await authorized_environment(
        project.client_id,
        project.erp_installation_id,
        evidence.environment_id,
        db,
        actor,
        lock=True,
    )
    target_policy(environment)
    from app.services.execution import assisted_binding

    binding = await assisted_binding(db, project, environment.id, release=True)
    connection = (
        await get_connection(db, project.client_id, project.erp_installation_id, environment.id)
        if binding is None
        else None
    )
    observations = evidence.observations
    if evidence.method != "ASSISTED_MANUAL" or evidence.execution_attempt_id:
        raise HTTPException(409, "use_execution_sign_off_for_machine_evidence")
    plan = state["manifest"]["test_plan"]
    if (
        (
            binding is None
            and (
                not connection
                or evidence.connection_version != connection.configuration_version
                or observations.get("secret_version") != connection.secret_version
                or not connection.secret_version
            )
        )
        or (binding is not None and observations.get("pattern_binding") != binding)
        or not plan
        or observations.get("test_plan_sha256") != sha256(json_bytes(plan))
        or not observations.get("acknowledge_assisted_evidence")
    ):
        raise HTTPException(409, "test_evidence_binding_changed")
    # Re-derive assertions instead of accepting a mutable/stale PASSED label.
    cases = observations.get("cases", [])
    required = {case["id"]: case["expected"] for case in plan["required_cases"]}
    if (
        len(cases) != len(required)
        or {case.get("id") for case in cases} != set(required)
        or any(
            case.get("status") != "PASSED"
            or json_bytes(case.get("expected")) != json_bytes(required[case["id"]])
            or json_bytes(case.get("actual")) != json_bytes(required[case["id"]])
            or not case.get("evidence_sha256")
            for case in cases
        )
    ):
        raise HTTPException(409, "mandatory_test_assertions_not_passed")
    existing = (
        await db.execute(
            select(PackageRelease).where(
                PackageRelease.project_id == project.id,
                PackageRelease.client_id == project.client_id,
                PackageRelease.candidate_id == candidate.id,
                PackageRelease.evidence_id == evidence.id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return {
            "id": existing.id,
            "checksum": existing.checksum,
            "kind": "release",
            "download_url": f"/api/projects/{project.id}/package/releases/{existing.id}/download",
        }
    signer = await actor_subject(db, actor)
    if not signer:
        raise HTTPException(403, "authenticated_tester_subject_required")
    manifest = {
        "product": "HighStudio",
        "kind": "release",
        "client_id": project.client_id,
        "project_id": project.id,
        "candidate_id": candidate.id,
        "candidate_checksum": candidate.checksum,
        "evidence_id": evidence.id,
        "environment_id": evidence.environment_id,
        "connection_version": connection.configuration_version
        if connection
        else binding["connection_version"],
        "integration_pattern_version_id": project.integration_pattern_version_id,
        "baseline_versions": candidate.manifest.get("baseline_versions", []),
        "pattern_binding": binding,
        "test_plan_sha256": observations["test_plan_sha256"],
        "signer_subject_id": signer,
        "method": "ASSISTED_MANUAL",
        "assurance": "authenticated_tester_attestation",
        "remote_exact_bytes_verified": False,
        "automatic_import": "UNSUPPORTED",
    }
    candidate_data = await verified_bytes(candidate, settings)
    data = bundle(
        {
            "candidate.zip": candidate_data,
            "test-report.json": json_bytes(observations),
            "release-manifest.json": json_bytes(manifest),
        }
    )
    identifier = str(uuid.uuid4())
    try:
        path = await save_asset_file(
            settings,
            asset_directory(settings, project.id, identifier, 1),
            "release.zip",
            data,
            "application/zip",
        )
    except ArtifactStorageError:
        raise HTTPException(503, "package_storage_unavailable") from None
    release = PackageRelease(
        id=identifier,
        project_id=project.id,
        client_id=project.client_id,
        candidate_id=candidate.id,
        evidence_id=evidence.id,
        checksum=sha256(data),
        manifest=manifest,
        storage_path=path,
        approved_by_subject_id=signer,
    )
    db.add(release)
    await db.flush()
    await record_ownership_event(
        db,
        actor,
        "PACKAGE_RELEASE_SIGNED",
        "PackageRelease",
        release.id,
        client_id=project.client_id,
        details={"candidate_id": candidate.id, "evidence_id": evidence.id},
    )
    project.workflow_status = "RELEASED"
    project.last_activity_at = datetime.now(UTC)
    return {
        "id": release.id,
        "checksum": release.checksum,
        "kind": "release",
        "download_url": f"/api/projects/{project.id}/package/releases/{release.id}/download",
    }
