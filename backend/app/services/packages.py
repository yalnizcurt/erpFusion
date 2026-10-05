"""Deterministic private bundles and exact approval/evidence bindings."""

import hashlib
import io
import json
import re
import uuid
import zipfile
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import (
    ArtifactVersion,
    ERPInstallation,
    ERPProfileVersion,
    Project,
    ValidationCategory,
    ValidationResult,
    ValidationStatus,
    VersionState,
)
from app.models.engineering import PackageCandidate, PackageRelease
from app.services.artifact_storage import asset_directory, save_asset_file
from app.services.workflow import WorkflowEngine

MAX_BUNDLE_BYTES = 32 * 1024 * 1024


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(name: Any) -> str:
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 255
        or any(ord(char) < 32 for char in name)
        or "\\" in name
        or ":" in name
        or name.startswith("/")
        or any(part in ("", ".", "..") for part in name.split("/"))
    ):
        raise HTTPException(409, "unsafe_package_filename")
    if name in ("manifest.json", "test-report.json", "candidate.zip", "release-manifest.json"):
        raise HTTPException(409, "reserved_package_filename")
    return name


def source_files(
    stage: str, content: dict, stage_config: dict, generation: dict
) -> dict[str, bytes]:
    files: dict[str, bytes] = {}

    def add(name: Any, body: Any) -> None:
        name = safe_name(name)
        if not isinstance(body, str) or not body.strip():
            raise HTTPException(409, "package_file_content_missing")
        data = body.encode("utf-8")
        if name in files and files[name] != data:
            raise HTTPException(409, "package_filename_collision")
        files[name] = data

    for key in ("output_files", "generated_files", "files"):
        collection = content.get(key, [])
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict):
                raise HTTPException(409, "package_file_contract_invalid")
            add(
                item.get("file_name") or item.get("filename") or item.get("name"),
                item.get("content", item.get("text", item.get("body"))),
            )
    named_files = content.get("files_by_name", {})
    if not isinstance(named_files, dict):
        raise HTTPException(409, "package_file_contract_invalid")
    for name, body in named_files.items():
        add(name, body)
    package_name = re.sub(r"[^a-zA-Z0-9_-]", "_", str(content.get("package_name") or stage.lower()))
    for field, extension in (("pks_content", "pks"), ("pkb_content", "pkb")):
        if content.get(field):
            add(f"{package_name}.{extension}", content[field])
    for field in (
        "full_mode_sql",
        "delta_mode_sql",
        "selective_mode_sql",
        "sql_content",
        "grants_and_synonyms_sql",
        "verification_script_sql",
        "rollback_script_sql",
    ):
        if content.get(field):
            add(f"{stage.lower()}-{field}.sql", content[field])
    if content.get("run_instructions_markdown"):
        add("installation-instructions.md", content["run_instructions_markdown"])
    # Published file contracts use field -> filename mappings or explicit declarations.
    outputs = stage_config.get("output_names", {})
    if isinstance(outputs, dict):
        for field, name in outputs.items():
            add(name, content.get(field))
    contracts = generation.get("artifact_files", [])
    if isinstance(contracts, dict):
        contracts = contracts.get(stage, [])
    if not isinstance(contracts, list):
        raise HTTPException(409, "package_file_contract_invalid")
    for item in contracts:
        if not isinstance(item, dict) or item.get("stage", stage) != stage:
            continue
        add(item.get("name") or item.get("filename"), content.get(item.get("field")))
    if isinstance(outputs, list) and any(name not in files for name in outputs):
        raise HTTPException(409, "configured_package_file_missing")
    # Preserve every structured generated result, including unknown strategy output fields.
    structured_name = safe_name(f"artifacts/{stage.lower()}.json")
    structured = json_bytes(content)
    if structured_name in files and files[structured_name] != structured:
        raise HTTPException(409, "package_filename_collision")
    files[structured_name] = structured
    return files


def valid_test_case(case: object) -> bool:
    if (
        not isinstance(case, dict)
        or not isinstance(case.get("id"), str)
        or not 1 <= len(case["id"]) <= 128
        or "expected" not in case
    ):
        return False
    assertion = case.get("assertion")
    if assertion is None:
        return True  # Assisted observations need no machine assertion implementation.
    if not isinstance(assertion, dict) or not isinstance(assertion.get("type"), str):
        return False
    if assertion["type"] == "CSV_DECIMAL_SUM":
        return isinstance(assertion.get("field"), str) and bool(assertion["field"])
    if assertion["type"] == "CSV_REQUIRED_FIELDS":
        fields = assertion.get("fields")
        return (
            isinstance(fields, list)
            and 1 <= len(fields) <= 100
            and all(isinstance(field, str) and field for field in fields)
        )
    return True


def approved_test_plan(configuration: dict) -> dict | None:
    testing = configuration.get("testing", {})
    if not isinstance(testing, dict):
        return None
    cases = testing.get("required_cases", [])
    if (
        not isinstance(testing.get("version"), str)
        or not testing["version"]
        or not isinstance(cases, list)
        or not cases
        or len(cases) > 100
        or any(not valid_test_case(case) for case in cases)
        or len({case["id"] for case in cases}) != len(cases)
    ):
        return None
    return {"version": str(testing["version"]), "required_cases": cases}


async def package_state(db: AsyncSession, project: Project) -> tuple[dict, dict[str, bytes]]:
    blockers: list[str] = []
    files: dict[str, bytes] = {}
    entries: list[dict[str, Any]] = []
    revisions: dict[str, Any] = {}
    profile = await db.get(ERPProfileVersion, project.erp_profile_version_id)
    if project.client_id is None:
        blockers.append("client_ownership_required")
    if project.archived_at is not None:
        blockers.append("project_archived")
    if (
        profile is None
        or profile.status != "PUBLISHED"
        or profile.profile_id != project.erp_profile_id
    ):
        blockers.append("published_profile_version_required")
    configuration = profile.configuration if profile else {}
    from app.services.integration_patterns import pattern_context

    pattern = await pattern_context(db, project)
    stage_map = WorkflowEngine.configured_stage_map(configuration)
    if not stage_map:
        blockers.append("configured_workflow_required")
    workflow = WorkflowEngine(db)
    effective = {
        stage["stage"]: stage for stage in (await workflow.get_workflow_status(project))["stages"]
    }
    for name, config in stage_map.items():
        stage = effective.get(name, {})
        if stage.get("gate_status") != "APPROVED":
            blockers.append(f"approval_required:{name}")
            continue
        version = (
            await db.execute(
                select(ArtifactVersion).where(
                    ArtifactVersion.artifact_id == stage["artifact_id"],
                    ArtifactVersion.client_id == project.client_id,
                    ArtifactVersion.version_number == stage["current_version"],
                )
            )
        ).scalar_one_or_none()
        if (
            version is None
            or version.state != VersionState.APPROVED
            or not version.reviewer_subject_id
        ):
            blockers.append(f"authenticated_revision_approval_required:{name}")
            continue
        bindings = (version.input_context_snapshot or {}).get("input_bindings")
        if bindings is None or bindings != await workflow.current_bindings(project.id, name):
            blockers.append(f"current_input_binding_required:{name}")
            continue
        validations = (
            (
                await db.execute(
                    select(ValidationResult).where(
                        ValidationResult.artifact_version_id == version.id,
                        ValidationResult.client_id == project.client_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        validation_config = configuration.get("validation", {})
        categories = set()
        if validation_config.get("schema_conformity", True):
            categories.add(ValidationCategory.SCHEMA)
        adapter = validation_config.get("adapters", {}).get(name)
        if adapter:
            from app.services.validation.strategies import get_validation_adapter

            _, category = get_validation_adapter(adapter)
            categories.add(category)
        traceability = validation_config.get("cross_artifact_traceability")
        if traceability and (
            validation_config.get("traceability_adapter") != "oracle_attribute_lineage"
            or ("FDD" in stage_map and list(stage_map).index(name) >= list(stage_map).index("FDD"))
        ):
            categories.add(ValidationCategory.CROSS_ARTIFACT)
        missing = categories - {item.category for item in validations}
        required_rules = {
            rule.get("name", "configured_rule")
            for rule in validation_config.get("rules", [])
            if isinstance(rule, dict) and rule.get("stage") in (None, name)
        }
        observed_rules = {check.get("name") for item in validations for check in item.checks}
        if missing or required_rules - observed_rules:
            blockers.append(f"validation_evidence_missing:{name}")
            continue
        if any(item.status != ValidationStatus.PASS for item in validations):
            blockers.append(f"validation_not_passed:{name}")
            continue
        stage_files = source_files(
            name, version.content, config, configuration.get("generation", {})
        )
        for filename, data in stage_files.items():
            if filename in files:
                if files[filename] != data:
                    blockers.append(f"package_filename_collision:{filename}")
                continue
            files[filename] = data
            entries.append(
                {
                    "name": filename,
                    "stage": name,
                    "revision": version.version_number,
                    "size_bytes": len(data),
                    "sha256": sha256(data),
                }
            )
        revisions[name] = {
            "artifact_id": version.artifact_id,
            "version_id": version.id,
            "revision": version.version_number,
            "reviewer_subject_id": version.reviewer_subject_id,
            "content_sha256": sha256(json_bytes(version.content)),
            "input_snapshot_sha256": sha256(json_bytes(version.input_context_snapshot)),
            "provenance": {
                key: (version.input_context_snapshot or {}).get(key)
                for key in (
                    "prompt_versions",
                    "knowledge_asset_versions",
                    "standard_package_versions",
                    "feedback_versions",
                    "generation_configuration",
                    "adapter",
                    "model",
                    "generation_run_id",
                )
            },
            "validation_results": [
                {"id": item.id, "category": item.category.value, "status": item.status.value}
                for item in validations
            ],
        }
    if not any(not name.startswith("artifacts/") for name in files):
        blockers.append("implementation_package_output_required")
    if sum(len(data) for data in files.values()) > MAX_BUNDLE_BYTES:
        blockers.append("package_size_limit_exceeded")
    manifest = {
        "format_version": 1,
        "kind": "candidate",
        "builder": "erpfusion-source-bundle-v1",
        "client_id": project.client_id,
        "project_id": project.id,
        "profile_version_id": project.erp_profile_version_id,
        "requirement_version": project.requirement_version,
        "schema_context_version": project.schema_context_version,
        "workflow_revision": project.workflow_revision,
        "environment_id": project.erp_environment_id,
        "installation_id": project.erp_installation_id,
        "execution_target": configuration.get("execution_target", {}),
        "artifacts": revisions,
        "files": sorted(entries, key=lambda entry: entry["name"]),
        "test_plan": approved_test_plan(configuration),
        "native_import_qualification": "NOT_VERIFIED",
        "automatic_import": "UNSUPPORTED",
        "compilation": "NOT_RUN",
        "sandbox_tests": "NOT_RUN",
        "automatic_execution_supported": False,
        "assurance_blockers": ["native_import_not_qualified", "compilation_not_run"],
    }
    # Version 1 remains byte-for-byte compatible. Only explicitly configured new
    # profiles opt into deliverable identity independent of an execution target.
    if pattern:
        manifest.pop("environment_id")
        manifest.pop("installation_id")
        manifest.update(
            format_version=2, builder="highstudio-source-bundle-v2", product="HighStudio"
        )
        manifest.update(
            integration_pattern_version_id=pattern["version_id"],
            integration_pattern={
                key: value for key, value in pattern.items() if key != "baselines"
            },
            baseline_versions=pattern["baseline_versions"],
            generation_strategy=pattern["configuration"].get("generation_rules", {}),
            deliverable_type=pattern["deliverable_type"],
            runtime_type=pattern["runtime_type"],
            qualification_strategy=pattern["qualification_strategy"],
            test_plan=approved_test_plan(pattern["configuration"]),
        )
    return {
        "available": not blockers,
        "kind": "candidate",
        "blockers": blockers,
        "files": manifest["files"],
        "manifest": manifest,
    }, files


def bundle(files: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100600 << 16
            archive.writestr(info, data)
    return stream.getvalue()


async def create_candidate(
    db: AsyncSession, project: Project, settings: Settings
) -> PackageCandidate:
    state, files = await package_state(db, project)
    if not state["available"]:
        raise HTTPException(409, {"blockers": state["blockers"]})
    data = bundle({**files, "manifest.json": json_bytes(state["manifest"])})
    checksum = sha256(data)
    existing = (
        await db.execute(
            select(PackageCandidate).where(
                PackageCandidate.project_id == project.id,
                PackageCandidate.client_id == project.client_id,
                PackageCandidate.checksum == checksum,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    identifier = str(uuid.uuid4())
    path = await save_asset_file(
        settings,
        asset_directory(settings, project.id, identifier, 1),
        "candidate.zip",
        data,
        "application/zip",
    )
    candidate = PackageCandidate(
        id=identifier,
        project_id=project.id,
        client_id=project.client_id,
        checksum=checksum,
        integration_pattern_version_id=project.integration_pattern_version_id,
        manifest=state["manifest"],
        storage_path=path,
    )
    db.add(candidate)
    await db.flush()
    return candidate


async def current_candidate(
    db: AsyncSession, project: Project
) -> tuple[dict, PackageCandidate | None]:
    state, files = await package_state(db, project)
    if not state["available"]:
        return state, None
    checksum = sha256(bundle({**files, "manifest.json": json_bytes(state["manifest"])}))
    matching = (
        await db.execute(
            select(PackageCandidate).where(
                PackageCandidate.project_id == project.id,
                PackageCandidate.client_id == project.client_id,
                PackageCandidate.checksum == checksum,
            )
        )
    ).scalar_one_or_none()
    return state, matching


async def latest_evidence(db: AsyncSession, project: Project, candidate: PackageCandidate):
    from app.models.engineering import SandboxEvidence

    return (
        await db.execute(
            select(SandboxEvidence)
            .where(
                SandboxEvidence.project_id == project.id,
                SandboxEvidence.client_id == project.client_id,
                SandboxEvidence.candidate_id == candidate.id,
                SandboxEvidence.environment_id == project.erp_environment_id,
            )
            .order_by(SandboxEvidence.created_at.desc(), SandboxEvidence.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def current_release(
    db: AsyncSession, project: Project, candidate: PackageCandidate
) -> PackageRelease | None:
    from app.models.connection import ERPConnection

    if candidate.manifest.get("format_version") == 2:
        from app.models import CapabilityQualification, ERPEnvironment, ExecutionAttempt
        from app.services.execution_contracts import target_policy

        releases = await db.scalars(
            select(PackageRelease)
            .where(
                PackageRelease.project_id == project.id,
                PackageRelease.client_id == project.client_id,
                PackageRelease.candidate_id == candidate.id,
            )
            .order_by(PackageRelease.created_at.desc())
        )
        for release in releases:
            if release.manifest.get("method") == "ASSISTED_MANUAL":
                from app.services.execution import assisted_binding

                evidence = await latest_evidence(db, project, candidate)
                if (
                    not evidence
                    or evidence.id != release.evidence_id
                    or evidence.status != "PASSED"
                ):
                    continue
                try:
                    binding = await assisted_binding(
                        db, project, evidence.environment_id, release=True
                    )
                except HTTPException:
                    continue
                if (
                    binding
                    == evidence.observations.get("pattern_binding")
                    == release.manifest.get("pattern_binding")
                ):
                    return release
                continue
            attempt = await db.get(
                ExecutionAttempt, release.manifest.get("execution_attempt_id", "")
            )
            if not attempt or attempt.status != "COMPLETED" or attempt.verdict != "PASSED":
                continue
            qualification = await db.get(CapabilityQualification, attempt.qualification_id)
            environment = await db.get(ERPEnvironment, attempt.environment_id)
            if not qualification or qualification.status != "ACTIVE" or not environment:
                continue
            try:
                target_policy(environment)
            except HTTPException:
                continue
            if (
                environment.client_id != project.client_id
                or environment.installation_id != attempt.binding.get("installation_id")
                or environment.endpoint_url != attempt.binding.get("endpoint_url")
                or environment.environment_type != attempt.binding.get("environment_type")
                or environment.execution_mode != attempt.binding.get("execution_mode")
                or environment.custody != attempt.binding.get("custody")
                or sha256(json_bytes(environment.configuration))
                != attempt.binding.get("environment_configuration_sha256")
            ):
                continue
            installation = await db.get(ERPInstallation, environment.installation_id)
            if (
                not installation
                or installation.status != "ACTIVE"
                or installation.archived_at is not None
                or installation.erp_profile_id != project.erp_profile_id
                or installation.edition != attempt.binding.get("edition")
                or installation.product_version != attempt.binding.get("product_version")
            ):
                continue
            if attempt.connection_id:
                connection = await db.get(ERPConnection, attempt.connection_id)
                if (
                    not connection
                    or connection.configuration_version != attempt.binding["connection_version"]
                    or connection.secret_version != attempt.binding["secret_version"]
                ):
                    continue
            newer = await db.scalar(
                select(ExecutionAttempt.id)
                .where(
                    ExecutionAttempt.candidate_id == candidate.id,
                    ExecutionAttempt.environment_id == environment.id,
                    ExecutionAttempt.created_at > attempt.created_at,
                    ExecutionAttempt.status.not_in(["CANCELLED", "SUPERSEDED"]),
                )
                .limit(1)
            )
            if not newer:
                return release
        return None

    evidence = await latest_evidence(db, project, candidate)
    if not evidence or evidence.status != "PASSED":
        return None
    connection = (
        await db.execute(
            select(ERPConnection).where(
                ERPConnection.environment_id == project.erp_environment_id,
                ERPConnection.client_id == project.client_id,
                ERPConnection.installation_id == project.erp_installation_id,
            )
        )
    ).scalar_one_or_none()
    if (
        not connection
        or evidence.connection_version != connection.configuration_version
        or evidence.observations.get("secret_version") != connection.secret_version
    ):
        return None
    return (
        await db.execute(
            select(PackageRelease).where(
                PackageRelease.project_id == project.id,
                PackageRelease.client_id == project.client_id,
                PackageRelease.candidate_id == candidate.id,
                PackageRelease.evidence_id == evidence.id,
            )
        )
    ).scalar_one_or_none()
