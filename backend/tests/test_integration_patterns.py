"""Pattern contracts, provenance and unsupported execution stay honest offline."""

import copy
import io
import json
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import (
    AdminAuditEvent,
    Artifact,
    ArtifactVersion,
    ERPAssetVersion,
    ERPConnection,
    ERPEnvironment,
    ERPInstallation,
    ERPProfile,
    ERPProfileVersion,
    GenerationRun,
    IntegrationPattern,
    IntegrationPatternVersion,
    PackageCandidate,
    PackageRelease,
    PatternBaseline,
    Project,
    ProjectInputRevision,
    SandboxEvidence,
)
from app.services.codegen.strategies import get_strategy
from app.services.integration_patterns import (
    apply_modifications,
    pattern_context,
    resolve_pattern,
)
from app.services.llm.mock import MockERPProvider
from app.services.packages import current_candidate, sha256
from app.services.prompt_compiler import CompiledGenerationContext

pytest_plugins = ("tests.test_execution_harness",)


async def version_input(system):
    async with system.factory() as db:
        project = await db.get(Project, "project")
        version = await db.get(IntegrationPatternVersion, project.integration_pattern_version_id)
        baselines = list(
            await db.scalars(
                select(PatternBaseline.asset_version_id).where(
                    PatternBaseline.pattern_version_id == version.id
                )
            )
        )
        return version.pattern_id, {
            "profile_version_id": version.profile_version_id,
            "runtime_type": version.runtime_type,
            "direction": version.direction,
            "deliverable_type": version.deliverable_type,
            "qualification_strategy": version.qualification_strategy,
            "delivery_method": version.delivery_method,
            "configuration": copy.deepcopy(version.configuration),
            "baseline_asset_version_ids": baselines,
        }


async def create_version(system, pattern_id, body, *, publish=True):
    response = await system.client.post(
        f"/api/integration-patterns/{pattern_id}/versions", json=body
    )
    assert response.status_code == 201, response.text
    version = response.json()
    if publish:
        response = await system.client.post(
            f"/api/integration-patterns/{pattern_id}/versions/{version['id']}/publish"
        )
        assert response.status_code == 200, response.text
        version = response.json()
    return version


async def assisted_candidate(system, required_assurance):
    pattern_id, body = await version_input(system)
    body.update(runtime_type="ASSISTED", qualification_strategy="ASSISTED")
    body["configuration"].update(
        adapter_bindings={},
        required_capabilities=[],
        optional_capabilities=[],
        qualification_policy={
            "allowed_modes": ["ASSISTED"],
            "required_assurance": required_assurance,
        },
    )
    version = await create_version(system, pattern_id, body)
    async with system.factory() as db:
        project = await db.get(Project, "project")
        previous_pattern = project.integration_pattern_version_id
        environment = await db.get(ERPEnvironment, "environment")
        environment.execution_mode = "ASSISTED"
        assert not await db.scalar(select(ERPConnection.id))
        await db.commit()
    response = await system.client.patch(
        "/api/projects/project",
        json={
            "integration_pattern_version_id": version["id"],
            "expected_integration_pattern_version_id": previous_pattern,
            "expected_requirement_version": 1,
        },
    )
    assert response.status_code == 200, response.text
    for stage in ("CONTEXT_ANALYSIS", "FDD", "TDD", "PUBLISHER"):
        await system.generate(stage)
    response = await system.client.post("/api/projects/project/package/candidates", json={})
    assert response.status_code == 201, response.text
    candidate = response.json()
    response = await system.client.get("/api/projects/project/sandbox/evidence")
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["candidate_id"] == candidate["id"]
    assert plan["manual_connection_required"] is False
    return version, candidate, {
        "candidate_id": candidate["id"],
        "candidate_checksum": candidate["checksum"],
        "reviewed_source_checksum": candidate["checksum"],
        "environment_id": "environment",
        "test_plan_sha256": plan["test_plan_sha256"],
        "acknowledge_assisted_evidence": True,
        "cases": [
            {
                "id": case["id"],
                "status": "PASSED",
                "expected": case["expected"],
                "actual": case["expected"],
                "evidence_note": "Synthetic authenticated tester observation",
                "evidence_sha256": sha256(b"Synthetic authenticated tester observation"),
            }
            for case in plan["test_plan"]["required_cases"]
        ],
    }


@pytest.mark.parametrize(
    "required_assurance,release_allowed",
    [
        (["ASSISTED_MANUAL", "APPLICATION_STATIC_VALIDATION"], True),
        (["REMOTE_ARTIFACT_IDENTITY_VERIFIED"], False),
    ],
)
async def test_pattern_assisted_evidence_and_signoff_without_connection_credentials(
    harness, required_assurance, release_allowed
):
    version, candidate, body = await assisted_candidate(harness, required_assurance)
    response = await harness.client.post("/api/projects/project/sandbox/evidence", json=body)
    assert response.status_code == 201, response.text
    evidence = response.json()
    assert evidence["status"] == "PASSED" and evidence["method"] == "ASSISTED_MANUAL"
    assert evidence["tester_subject_id"] and evidence["execution_attempt_id"] is None
    assert evidence["connection_version"] is None
    observations = evidence["observations"]
    assert observations["assurance"] == "authenticated_tester_attestation"
    assert observations["remote_exact_bytes_verified"] is False
    assert observations["secret_version"] is None
    binding = observations["pattern_binding"]
    assert binding["connection_id"] is None and binding["connection_version"] is None
    async with harness.factory() as db:
        project = await db.get(Project, "project")
        context = await pattern_context(db, project)
        manifest = (await db.get(PackageCandidate, candidate["id"])).manifest
        original = (await db.get(PackageCandidate, harness.candidate["id"])).manifest
        assert manifest["integration_pattern_version_id"] == binding[
            "integration_pattern_version_id"
        ] == version["id"]
        assert manifest["integration_pattern"]["contract_sha256"] == binding[
            "pattern_contract_sha256"
        ] == context["contract_sha256"]
        assert original["integration_pattern_version_id"] != version["id"]
        assert manifest["baseline_versions"] == binding["baseline_versions"] == original[
            "baseline_versions"
        ] == context["baseline_versions"]
        assert not await db.scalar(select(ERPConnection.id))
    response = await harness.client.get("/api/projects/project/sandbox/evidence")
    assert response.json()["assisted_release_allowed"] is release_allowed
    response = await harness.client.post(
        f"/api/projects/project/sandbox/evidence/{evidence['id']}/sign-off",
        json={"acknowledge_assisted_evidence": True},
    )
    if not release_allowed:
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == (
            "pattern_release_requires_higher_assurance_than_manual_evidence"
        )
        async with harness.factory() as db:
            assert not await db.scalar(select(PackageRelease.id))
        return
    assert response.status_code == 201, response.text
    release = response.json()
    assert (await harness.client.get("/api/projects/project/package")).json()["kind"] == "release"
    download = await harness.client.get(release["download_url"])
    assert download.status_code == 200, download.text
    assert sha256(download.content) == release["checksum"]
    assert download.headers["cache-control"] == "private, no-store"
    original_bytes = await harness.client.get(candidate["download_url"])
    assert original_bytes.status_code == 200, original_bytes.text
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert archive.read("candidate.zip") == original_bytes.content
        release_manifest = json.loads(archive.read("release-manifest.json"))
        report = json.loads(archive.read("test-report.json"))
    assert release_manifest["candidate_id"] == candidate["id"]
    assert release_manifest["candidate_checksum"] == candidate["checksum"]
    assert release_manifest["integration_pattern_version_id"] == version["id"]
    assert release_manifest["baseline_versions"] == context["baseline_versions"]
    assert release_manifest["pattern_binding"] == report["pattern_binding"] == binding
    assert release_manifest["method"] == "ASSISTED_MANUAL"
    assert release_manifest["assurance"] == "authenticated_tester_attestation"
    assert release_manifest["remote_exact_bytes_verified"] is False
    assert release_manifest["signer_subject_id"] == evidence["tester_subject_id"]
    assert report["test_plan_sha256"] == body["test_plan_sha256"]


async def test_simulator_target_cannot_accept_manual_evidence_or_signoff(harness):
    _, _, body = await assisted_candidate(harness, ["ASSISTED_MANUAL"])
    response = await harness.client.post("/api/projects/project/sandbox/evidence", json=body)
    assert response.status_code == 201, response.text
    evidence_id = response.json()["id"]
    async with harness.factory() as db:
        environment = await db.get(ERPEnvironment, "environment")
        environment.execution_mode = "SIMULATED"
        await db.commit()
    for path, submission in (
        ("/api/projects/project/sandbox/evidence", body),
        (
            f"/api/projects/project/sandbox/evidence/{evidence_id}/sign-off",
            {"acknowledge_assisted_evidence": True},
        ),
    ):
        response = await harness.client.post(path, json=submission)
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == "simulated_target_requires_machine_simulated_evidence"
    async with harness.factory() as db:
        assert await db.scalar(select(func.count()).select_from(SandboxEvidence)) == 1
        assert not await db.scalar(select(PackageRelease.id))


async def test_pattern_publication_versions_are_immutable_and_audited(harness):
    pattern_id, body = await version_input(harness)
    version = await create_version(harness, pattern_id, body)
    assert version["version"] == 2 and version["status"] == "PUBLISHED"
    response = await harness.client.put(
        f"/api/integration-patterns/{pattern_id}/versions/{version['id']}", json=body
    )
    assert response.status_code == 409
    assert "immutable" in response.json()["detail"]
    async with harness.factory() as db:
        project = await db.get(Project, "project")
        assert project.integration_pattern_version_id != version["id"]
        actions = set(await db.scalars(select(AdminAuditEvent.action)))
        assert {"PATTERN_VERSION_CREATED", "PATTERN_VERSION_PUBLISHED"} <= actions
    response = await harness.client.post(
        f"/api/integration-patterns/{pattern_id}/versions/{version['id']}/retire"
    )
    assert response.status_code == 200 and response.json()["status"] == "RETIRED"
    response = await harness.client.put(
        f"/api/integration-patterns/{pattern_id}/versions/{version['id']}", json=body
    )
    assert response.status_code == 409


async def test_baseline_required_publication_rejects_non_baseline_strategy(harness):
    pattern_id, body = await version_input(harness)
    body["configuration"]["generation_rules"].update(
        baseline_required=True, strategy="generic_json"
    )
    version = await create_version(harness, pattern_id, body, publish=False)
    response = await harness.client.post(
        f"/api/integration-patterns/{pattern_id}/versions/{version['id']}/publish"
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "pattern_requires_a_baseline_modification_strategy"
    async with harness.factory() as db:
        assert (await db.get(IntegrationPatternVersion, version["id"])).status == "DRAFT"


async def test_pinned_retired_pattern_and_baseline_remain_reproducible(harness):
    pattern_id, body = await version_input(harness)
    async with harness.factory() as db:
        project = await db.get(Project, "project")
        original = await pattern_context(db, project)
        identifier = project.integration_pattern_version_id
        baseline = await db.get(ERPAssetVersion, body["baseline_asset_version_ids"][0])
        baseline.status = "RETIRED"
        await db.commit()
    response = await harness.client.post(
        f"/api/integration-patterns/{pattern_id}/versions/{identifier}/retire"
    )
    assert response.status_code == 200, response.text
    async with harness.factory() as db:
        project = await db.get(Project, "project")
        assert await pattern_context(db, project) == original
        _, candidate = await current_candidate(db, project)
        assert candidate.id == harness.candidate["id"]
        with pytest.raises(HTTPException, match="published_integration_pattern_version_required"):
            await resolve_pattern(db, identifier)


async def test_exact_baseline_and_pattern_versions_reach_generation_and_candidate(harness):
    async with harness.factory() as db:
        project = await db.get(Project, "project")
        context = await pattern_context(db, project)
        manifest = (await db.get(PackageCandidate, harness.candidate["id"])).manifest
        assert manifest["integration_pattern_version_id"] == context["version_id"]
        assert manifest["baseline_versions"] == context["baseline_versions"]
        assert manifest["runtime_type"] == "ERP_NATIVE"
        assert manifest["deliverable_type"] == "PUBLISHER_SOURCE"
        runs = list(await db.scalars(select(GenerationRun)))
        assert len(runs) == 4
        for run in runs:
            assert run.provenance["integration_pattern"]["version_id"] == context["version_id"]
            assert run.provenance["baseline_versions"] == context["baseline_versions"]
            assert run.resolved_context["integration_pattern"]["baselines"] == context["baselines"]
        publisher = next(run for run in runs if run.artifact_type == "PUBLISHER")
        assert publisher.provenance["generation_strategy_version"] == "1"
        output = (await db.get(ArtifactVersion, publisher.artifact_version_id)).content
        assert output["integration_pattern_version_id"] == context["version_id"]
        assert output["baseline_versions"] == context["baseline_versions"]
        assert "DEMO-001" in next(
            f["content"] for f in output["files"] if f["name"] == "extract.sql"
        )
        assert "password" not in json.dumps(run.resolved_context).lower()


@pytest.mark.parametrize(
    "runtime,strategy",
    [
        ("ERP_NATIVE", "NATIVE_ARTIFACT"),
        ("API_INTEGRATION", "REMOTE_API"),
        ("FILE_BASED", "FILE_EXCHANGE"),
        ("EXTERNAL_RUNTIME", "EXTERNAL_RUNTIME"),
        ("ASSISTED", "ASSISTED"),
    ],
)
async def test_execution_models_are_representable_without_fabricated_runtime(
    harness, runtime, strategy
):
    pattern_id, body = await version_input(harness)
    body.update(
        runtime_type=runtime,
        qualification_strategy=strategy,
        deliverable_type="MAPPING_CONFIGURATION",
    )
    body["configuration"].update(
        adapter_bindings={},
        required_capabilities=["CALL_API"] if runtime == "API_INTEGRATION" else [],
        optional_capabilities=[],
        qualification_policy={
            "allowed_modes": ["ASSISTED"],
            "required_assurance": ["ASSISTED_MANUAL"],
        },
    )
    body["configuration"]["generation_rules"]["strategy"] = "baseline_json"
    version = await create_version(harness, pattern_id, body)
    assert version["implementation_status"] == "GENERATION_SUPPORTED"
    assert version["adapter_support"] == {}
    assert version["qualification"] == "ENVIRONMENT_SPECIFIC_REQUIRED"
    assert version["runtime_type"] == runtime


async def test_unknown_draft_generation_strategy_is_not_reported_as_supported(harness):
    pattern_id, body = await version_input(harness)
    body["configuration"]["generation_rules"]["strategy"] = "not_installed"
    version = await create_version(harness, pattern_id, body, publish=False)
    assert version["implementation_status"] != "GENERATION_SUPPORTED"


@pytest.mark.parametrize(
    "runtime,strategy,deliverable,mode,adapter",
    [
        (
            "ERP_NATIVE", "NATIVE_ARTIFACT", "PUBLISHER_SOURCE", "SIMULATED",
            "oracle_fusion_publisher",
        ),
        ("FILE_BASED", "FILE_EXCHANGE", "MAPPING_CONFIGURATION", "SIMULATED", "oracle_simulator"),
    ],
)
async def test_adapter_status_requires_compatible_mode_runtime_and_deliverable(
    harness, runtime, strategy, deliverable, mode, adapter
):
    pattern_id, body = await version_input(harness)
    body.update(
        runtime_type=runtime,
        qualification_strategy=strategy,
        deliverable_type=deliverable,
    )
    body["configuration"]["adapter_bindings"] = {mode: adapter}
    version = await create_version(harness, pattern_id, body)
    assert version["adapter_support"][mode] == "NOT_IMPLEMENTED"
    assert version["implementation_status"] != "SIMULATOR_SUPPORTED"


async def test_same_erp_patterns_resolve_distinct_caps_and_unknown_adapters_stay_unavailable(
    harness,
):
    pattern_id, body = await version_input(harness)
    response = await harness.client.get("/api/projects/project/executions/capabilities/environment")
    assert response.status_code == 200
    publisher = response.json()
    assert "RUN_REPORT" in publisher["required_capabilities"]
    assert "INSTALL_ARTIFACT" in publisher["required_capabilities"]
    async with harness.factory() as db:
        product_id = (await db.get(IntegrationPattern, pattern_id)).erp_profile_id
    response = await harness.client.post(
        "/api/integration-patterns",
        json={"erp_profile_id": product_id, "key": "api-mapping", "name": "API mapping pattern"},
    )
    assert response.status_code == 201, response.text
    api_pattern = response.json()["id"]
    body.update(
        runtime_type="API_INTEGRATION",
        qualification_strategy="REMOTE_API",
        deliverable_type="API_CONFIGURATION",
    )
    body["configuration"].update(
        required_capabilities=["CALL_API"],
        optional_capabilities=[],
        adapter_bindings={"SIMULATED": "unimplemented_runtime"},
    )
    body["configuration"]["generation_rules"]["strategy"] = "baseline_json"
    version = await create_version(harness, api_pattern, body)
    assert version["adapter_support"]["SIMULATED"] == "NOT_IMPLEMENTED"
    async with harness.factory() as db:
        project = await db.get(Project, "project")
        project.integration_pattern_version_id = version["id"]
        await db.commit()
    response = await harness.client.get("/api/projects/project/executions/capabilities/environment")
    api = response.json()
    assert not api["available"]
    assert api["required_capabilities"] == ["CALL_API"]
    assert all(not c["qualified"] and not c["implemented"] for c in api["capabilities"])
    assert "INSTALL_ARTIFACT" not in {c["name"] for c in api["capabilities"]}


async def test_catalogue_and_wrong_pattern_do_not_grant_execution(harness):
    async with harness.factory() as db:
        project = await db.get(Project, "project")
        project.integration_pattern_version_id = None
        await db.commit()
    response = await harness.client.get("/api/projects/project/executions/capabilities/environment")
    assert response.json()["available"] is False
    assert response.json()["blockers"] == ["integration_pattern_required_for_execution"]
    assert response.json()["capabilities"] == []


async def test_unsupported_operation_is_rejected_even_with_qualified_simulator(harness):
    response = await harness.client.post(
        "/api/projects/project/executions/qualifications",
        json={"environment_id": "environment", "acknowledge_environment_scope": True},
    )
    assert response.status_code == 201, response.text
    response = await harness.client.post(
        "/api/projects/project/executions",
        json={
            "candidate_id": harness.candidate["id"],
            "environment_id": "environment",
            "operation": "CHECK_REPORT_ACCESS",
            "idempotency_key": "unsupported",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "operation_not_implemented_for_adapter"


@pytest.mark.parametrize(
    "configuration",
    [
        {"credentials": {"password": "never-store-this"}},
        {"required_capabilities": "CALL_API"},
        {"generation_rules": {"allowed_files": "mapping.json"}},
        {"adapter_bindings": []},
    ],
)
async def test_pattern_configuration_trust_boundary_rejects_secrets_and_malformed_contracts(
    harness, configuration
):
    pattern_id, body = await version_input(harness)
    body["configuration"] = configuration
    response = await harness.client.post(
        f"/api/integration-patterns/{pattern_id}/versions", json=body
    )
    assert response.status_code == 422
    assert "never-store-this" not in response.text


@pytest.mark.parametrize(
    "case",
    [
        {"id": [], "expected": 1, "assertion": {"type": "CSV_ROW_COUNT"}},
        {"id": "", "expected": 1, "assertion": {"type": "CSV_ROW_COUNT"}},
        {"id": "bad-assertion", "expected": 1, "assertion": []},
        {
            "id": "missing-decimal-field",
            "expected": "1",
            "assertion": {"type": "CSV_DECIMAL_SUM"},
        },
    ],
)
async def test_pattern_testing_configuration_rejects_malformed_cases(harness, case):
    pattern_id, body = await version_input(harness)
    body["configuration"]["testing"]["required_cases"] = [case]
    response = await harness.client.post(
        f"/api/integration-patterns/{pattern_id}/versions", json=body
    )
    assert response.status_code == 422, response.text


async def test_pattern_context_maps_invalid_persisted_configuration_to_conflict(harness):
    async with harness.factory() as db:
        project = await db.get(Project, "project")
        version = await db.get(IntegrationPatternVersion, project.integration_pattern_version_id)
        version.configuration = {"generation_rules": "malformed"}
        await db.commit()
        with pytest.raises(HTTPException) as exc_info:
            await pattern_context(db, project)
    assert exc_info.value.status_code == 409


async def test_pattern_admin_and_publication_require_server_roles(harness):
    pattern_id, body = await version_input(harness)
    headers = {"X-Dev-User-Id": "viewer", "X-Dev-Roles": ""}
    response = await harness.client.post(
        f"/api/integration-patterns/{pattern_id}/versions", json=body, headers=headers
    )
    assert response.status_code == 403
    response = await harness.client.get(
        "/api/integration-patterns?include_drafts=true", headers=headers
    )
    assert response.status_code == 403
    version = await create_version(harness, pattern_id, body, publish=False)
    response = await harness.client.post(
        f"/api/integration-patterns/{pattern_id}/versions/{version['id']}/publish", headers=headers
    )
    assert response.status_code == 403


async def test_baselines_cannot_cross_products_or_use_unapproved_versions(harness):
    pattern_id, body = await version_input(harness)
    async with harness.factory() as db:
        db.add(ERPProfile(id="foreign-product", key="foreign", name="Other ERP", vendor="Fixture"))
        await db.flush()
        db.add(
            ERPProfileVersion(
                id="foreign-profile-version",
                profile_id="foreign-product",
                version=1,
                status="PUBLISHED",
            )
        )
        await db.flush()
        db.add(
            ERPAssetVersion(
                id="foreign-baseline",
                asset_id="foreign-baseline",
                profile_version_id="foreign-profile-version",
                version=1,
                asset_kind="PACKAGE",
                status="PUBLISHED",
                name="Foreign baseline",
                text_content='{"files": []}',
            )
        )
        await db.commit()
    body["baseline_asset_version_ids"] = ["foreign-baseline"]
    response = await harness.client.post(
        f"/api/integration-patterns/{pattern_id}/versions", json=body
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "baseline_must_be_published_standard_package_for_product"
    body["profile_version_id"] = "foreign-profile-version"
    body["baseline_asset_version_ids"] = []
    response = await harness.client.post(
        f"/api/integration-patterns/{pattern_id}/versions", json=body
    )
    assert response.status_code == 409


async def test_pattern_upgrade_invalidates_work_retains_history_and_stales_jobs(harness):
    pattern_id, body = await version_input(harness)
    body["configuration"]["generation_rules"]["allowed_modifications"] = [
        "Version two change policy"
    ]
    version = await create_version(harness, pattern_id, body)
    async with harness.factory() as db:
        project = await db.get(Project, "project")
        old_pattern = project.integration_pattern_version_id
        previous_revision = project.workflow_revision
        versions_before = await db.scalar(select(func.count()).select_from(ArtifactVersion))
    queued = await harness.client.post(
        "/api/projects/project/generate", json={"stage": "CONTEXT_ANALYSIS"}
    )
    assert queued.status_code == 202, queued.text
    response = await harness.client.patch(
        "/api/projects/project",
        json={
            "integration_pattern_version_id": version["id"],
            "expected_integration_pattern_version_id": old_pattern,
            "expected_requirement_version": 1,
        },
    )
    assert response.status_code == 200, response.text
    async with harness.factory() as db:
        project = await db.get(Project, "project")
        assert project.integration_pattern_version_id == version["id"]
        assert project.workflow_revision > previous_revision
        assert await db.scalar(select(func.count()).select_from(ArtifactVersion)) == versions_before
        assert all(a.gate_status.value != "APPROVED" for a in await db.scalars(select(Artifact)))
        run = await db.get(GenerationRun, queued.json()["id"])
        assert run.status == "STALE"
        snapshots = list(await db.scalars(select(ProjectInputRevision)))
        assert {old_pattern, version["id"]} <= {
            s.snapshot["integration_pattern_version_id"] for s in snapshots
        }
        _, current = await current_candidate(db, project)
        assert current is None


async def test_exact_edition_and_product_version_contract_is_enforced(harness):
    pattern_id, body = await version_input(harness)
    body["configuration"]["compatibility"] = {
        "editions": ["ApprovedEdition"],
        "product_versions": ["approved-v1"],
    }
    version = await create_version(harness, pattern_id, body)
    async with harness.factory() as db:
        installation = await db.get(ERPInstallation, "installation")
        with pytest.raises(HTTPException, match="pattern_product_edition_version_not_supported"):
            await resolve_pattern(db, version["id"], installation=installation)
        installation.edition, installation.product_version = "ApprovedEdition", "approved-v1"
        assert (await resolve_pattern(db, version["id"], installation=installation))[
            1
        ].id == version["id"]
        project = await db.get(Project, "project")
        project.integration_pattern_version_id = version["id"]
        assert (await pattern_context(db, project))["version_id"] == version["id"]
        installation.edition = "UnapprovedEdition"
        with pytest.raises(HTTPException, match="pattern_product_edition_version_not_supported"):
            await pattern_context(db, project)


def test_baseline_modifications_are_bounded_and_unmodified_files_survive():
    context = {
        "baselines": [
            {
                "content": json.dumps(
                    {
                        "files": [
                            {"name": "mapping.json", "content": "old"},
                            {"name": "README.txt", "content": "retain"},
                        ]
                    }
                )
            }
        ],
        "configuration": {"generation_rules": {"allowed_files": ["mapping.json"]}},
    }
    assert apply_modifications(context, [{"name": "mapping.json", "content": "new"}]) == [
        {"name": "README.txt", "content": "retain"},
        {"name": "mapping.json", "content": "new"},
    ]
    with pytest.raises(ValueError, match="baseline_modification_not_permitted"):
        apply_modifications(context, [{"name": "README.txt", "content": "erase"}])
    with pytest.raises(ValueError, match="baseline_modification_not_permitted"):
        apply_modifications(context, [{"name": "../secret", "content": "erase"}])


async def test_baseline_json_generation_preserves_exact_revision_and_provenance():
    text = json.dumps({"files": [{"name": "mapping.json", "content": '{"id": "invoice_id"}'}]})
    refs = [{"id": "baseline-v3", "version": 3, "content_sha256": sha256(text.encode())}]
    pattern = {
        "version_id": "pattern-v7",
        "baseline_versions": refs,
        "baselines": [{"content": text}],
        "configuration": {"generation_rules": {"allowed_files": ["mapping.json"]}},
    }
    compiled = CompiledGenerationContext(
        "rules", "requirements", {}, SimpleNamespace(configuration={}), pattern
    )
    result = await get_strategy("baseline_json").generate(
        SimpleNamespace(), "CODE", {}, compiled, MockERPProvider()
    )
    assert result["files"] == [{"name": "mapping.json", "content": '{"id": "invoice_id"}'}]
    assert result["integration_pattern_version_id"] == "pattern-v7"
    assert result["baseline_versions"] == refs
