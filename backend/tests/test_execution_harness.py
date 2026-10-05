"""Offline full lifecycle/API integration and adapter conformance; no live ERP claims."""

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.generation import process_generation_run
from app.config import Settings
from app.main import create_app
from app.models import (
    AdminAuditEvent,
    Artifact,
    Base,
    Client,
    ERPEnvironment,
    ERPInstallation,
    ERPProfile,
    ERPProfileVersion,
    ExecutionAttempt,
    IntegrationPatternVersion,
    PackageCandidate,
    Project,
    SandboxEvidence,
    SimulatedArtifact,
)
from app.services.erp_registry import load_development_fixtures, read_fixture_manifest
from app.services.execution import expire_attempts, process_attempt
from app.services.execution_contracts import SCENARIOS, assertions, target_policy, transition
from app.services.llm.mock import MockERPProvider
from app.services.packages import current_candidate
from app.services.workflow import WorkflowEngine


@pytest_asyncio.fixture
async def harness(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as db:
        await db.run_sync(Base.metadata.create_all)
    settings = Settings(
        _env_file=None,
        app_env="test",
        llm_provider="mock",
        demo_mode=True,
        execution_simulator_enabled=True,
        artifact_storage_path=str(tmp_path),
    )
    async with factory() as db:
        await load_development_fixtures(
            db, manifest=read_fixture_manifest("oracle-publisher-harness-v1"), app_env="development"
        )
        profile = await db.scalar(select(ERPProfile))
        version = await db.scalar(select(ERPProfileVersion))
        db.add_all(
            [
                Client(id="client", client_key="synthetic", display_name="Synthetic client"),
                Client(id="other", client_key="other", display_name="Other client"),
            ]
        )
        await db.flush()
        db.add(
            ERPInstallation(
                id="installation",
                client_id="client",
                erp_profile_id=profile.id,
                installation_key="publisher",
                display_name="Publisher fixture",
                product_version="fixture-v1",
            )
        )
        await db.flush()
        for identifier, kind in (
            ("environment", "TEST"),
            ("uat", "UAT"),
            ("dev", "DEVELOPMENT"),
            ("prod", "PRODUCTION"),
        ):
            db.add(
                ERPEnvironment(
                    id=identifier,
                    client_id="client",
                    installation_id="installation",
                    environment_key=identifier,
                    display_name=identifier,
                    environment_type=kind,
                    custody="CUSTOMER",
                    execution_mode="SIMULATED",
                )
            )
        await db.flush()
        pattern_version = await db.scalar(select(IntegrationPatternVersion))
        project = Project(
            id="project",
            name="Synthetic invoice extract",
            client_id="client",
            erp_profile_id=profile.id,
            erp_profile_version_id=version.id,
            integration_pattern_version_id=pattern_version.id,
            erp_installation_id="installation",
            erp_environment_id="environment",
            business_requirement=(
                "Extract invoice ID, amount and currency for one synthetic "
                "invoice into the agreed CSV contract."
            ),
            erp_schema_context={"tables": []},
        )
        db.add(project)
        await db.flush()
        await WorkflowEngine(db).initialize_project_artifacts(project)
        await db.commit()

    async def sessions():
        async with factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    app = create_app(settings, engine, sessions)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:

        async def generate(stage, attempt_id=None):
            route = (
                f"/api/projects/project/executions/{attempt_id}/remediate"
                if attempt_id
                else "/api/projects/project/generate"
            )
            response = await client.post(
                route, json={"stage": stage, **({"acknowledge": True} if attempt_id else {})}
            )
            assert response.status_code == 202, response.text
            async with factory() as db:
                result = await process_generation_run(
                    db, response.json()["id"], settings=settings, provider=MockERPProvider()
                )
                assert result["status"] == "COMPLETED", result
                artifact = await db.scalar(
                    select(Artifact).where(
                        Artifact.project_id == "project", Artifact.artifact_type == stage
                    )
                )
                artifact_id, revision = artifact.id, artifact.current_version
            response = await client.post(
                f"/api/reviews/artifacts/{artifact_id}/versions/{revision}/review",
                json={"decision": "APPROVED", "comments": "Synthetic fixture reviewed"},
            )
            assert response.status_code == 200, response.text

        for stage in ("CONTEXT_ANALYSIS", "FDD", "TDD", "PUBLISHER"):
            await generate(stage)
        response = await client.post("/api/projects/project/package/candidates", json={})
        assert response.status_code == 201, response.text
        candidate = response.json()
        yield SimpleNamespace(
            client=client,
            factory=factory,
            settings=settings,
            candidate=candidate,
            generate=generate,
        )
    await engine.dispose()


async def run_attempt(harness, scenario="SUCCESS", environment="environment", *, key=None):
    response = await harness.client.post(
        "/api/projects/project/executions/qualifications",
        json={"environment_id": environment, "acknowledge_environment_scope": True},
    )
    assert response.status_code == 201, response.text
    body = {
        "candidate_id": harness.candidate["id"],
        "environment_id": environment,
        "idempotency_key": key or scenario + environment,
        "scenario": scenario,
    }
    response = await harness.client.post("/api/projects/project/executions", json=body)
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    response = await harness.client.post(
        f"/api/projects/project/executions/{identifier}/approve", json={"acknowledge": True}
    )
    assert response.status_code == 200, response.text
    async with harness.factory() as db:
        assert await process_attempt(db, identifier, harness.settings)
        assert not await process_attempt(db, identifier, harness.settings)
    return (await harness.client.get(f"/api/projects/project/executions/{identifier}")).json()


async def test_full_lifecycle_simulated_release_private_evidence_and_multiple_targets(harness):
    first = await run_attempt(harness)
    assert first["status"] == "COMPLETED" and first["verdict"] == "PASSED"
    assert "SIMULATED_FUNCTIONAL_ASSERTIONS_PASSED" in first["assurance"]
    assert "REMOTE_ARTIFACT_IDENTITY_VERIFIED" not in first["assurance"]
    receipt = await harness.client.get(
        f"/api/projects/project/executions/{first['id']}/evidence/receipt.json"
    )
    assert receipt.json()["candidate_checksum"] == harness.candidate["checksum"]
    assert receipt.json()["read_back_checksum"] == harness.candidate["checksum"]
    assert receipt.json()["remote_exact_bytes_verified"] is False
    assert receipt.headers["cache-control"] == "private, no-store"
    response = await harness.client.post(
        f"/api/projects/project/executions/{first['id']}/sign-off", json={"acknowledge": True}
    )
    assert response.status_code == 200, response.text
    assert response.json()["simulated"] is True
    release = await harness.client.get(response.json()["download_url"])
    with zipfile.ZipFile(io.BytesIO(release.content)) as archive:
        manifest = json.loads(archive.read("release-manifest.json"))
        assert manifest["product"] == "HighStudio" and manifest["simulated"]
        assert not manifest["remote_exact_bytes_verified"]
    second = await run_attempt(harness, environment="uat")
    assert second["candidate_id"] == first["candidate_id"]
    async with harness.factory() as db:
        project = await db.get(Project, "project")
        original = await db.get(PackageCandidate, first["candidate_id"])
        project.erp_environment_id = "uat"
        _, current = await current_candidate(db, project)
        assert current.id == original.id
        assert "environment_id" not in original.manifest
        assert (
            await db.scalar(
                select(SimulatedArtifact).where(SimulatedArtifact.attempt_id == first["id"])
            )
        ).status == "INSTALLED"
        assert (
            len(
                (
                    await db.scalars(
                        select(AdminAuditEvent).where(AdminAuditEvent.action.like("EXECUTION_%"))
                    )
                ).all()
            )
            >= 6
        )


async def test_default_simulator_scenario_passes_without_fault_injection(harness):
    attempt = await run_attempt(harness, scenario=None, key="default-scenario")
    assert attempt["request"]["scenario"] is None
    assert attempt["status"] == "COMPLETED" and attempt["verdict"] == "PASSED"


@pytest.mark.parametrize("scenario", SCENARIOS[1:])
async def test_adapter_faults_do_not_pass_or_release(harness, scenario):
    attempt = await run_attempt(harness, scenario)
    assert attempt["status"] == (
        "UNKNOWN_OUTCOME" if scenario in {"TIMEOUT", "UNKNOWN_OUTCOME"} else "FAILED"
    )
    assert attempt["verdict"] != "PASSED"
    assert attempt["failure"]["attempt_id"] == attempt["id"]
    assert not attempt["failure"]["retryable"] if attempt["status"] == "UNKNOWN_OUTCOME" else True
    response = await harness.client.post(
        f"/api/projects/project/executions/{attempt['id']}/sign-off", json={"acknowledge": True}
    )
    assert response.status_code == 409


async def test_failed_history_remediation_new_candidate_then_success(harness):
    failed = await run_attempt(harness, "QUERY_ERROR")
    old = harness.candidate
    await harness.generate("PUBLISHER", failed["id"])
    response = await harness.client.post("/api/projects/project/package/candidates", json={})
    harness.candidate = response.json()
    assert harness.candidate["id"] != old["id"]
    passed = await run_attempt(harness, key="repaired")
    assert passed["verdict"] == "PASSED"
    history = (await harness.client.get("/api/projects/project/executions")).json()["attempts"]
    assert len(history) == 2
    assert (await harness.client.get(f"/api/projects/project/executions/{failed['id']}")).json()[
        "status"
    ] == "FAILED"


async def test_unknown_outcome_requires_reconciliation_and_no_resend(harness):
    attempt = await run_attempt(harness, "UNKNOWN_OUTCOME")
    body = {
        "candidate_id": harness.candidate["id"],
        "environment_id": "environment",
        "idempotency_key": "retry",
        "scenario": "SUCCESS",
    }
    response = await harness.client.post("/api/projects/project/executions", json=body)
    assert response.status_code == 409
    response = await harness.client.post(
        f"/api/projects/project/executions/{attempt['id']}/reconcile",
        json={
            "acknowledge": True,
            "outcome": "CONFIRMED_NO_EXECUTION",
            "evidence_note": "Operator inspected simulator receipt and confirmed no accepted job.",
        },
    )
    assert response.status_code == 200, response.text
    assert "storage_path" not in response.text
    response = await harness.client.post("/api/projects/project/executions", json=body)
    assert response.status_code == 201
    assert (
        response.json()["id"] != attempt["id"] and response.json()["status"] == "AWAITING_APPROVAL"
    )


@pytest.mark.parametrize("environment", ["dev", "prod"])
async def test_target_prohibitions_and_cross_client_access(harness, environment):
    response = await harness.client.post(
        "/api/projects/project/executions/qualifications",
        json={"environment_id": environment, "acknowledge_environment_scope": True},
    )
    assert response.status_code == 409
    response = await harness.client.get(
        "/api/projects/project/executions", headers={"X-Dev-User-Id": "outsider", "X-Dev-Roles": ""}
    )
    assert response.status_code == 404


async def test_revoked_configuration_stale_candidate_and_recovery(harness):
    await harness.client.post(
        "/api/projects/project/executions/qualifications",
        json={"environment_id": "environment", "acknowledge_environment_scope": True},
    )
    body = {
        "candidate_id": harness.candidate["id"],
        "environment_id": "environment",
        "idempotency_key": "stale",
    }
    response = await harness.client.post("/api/projects/project/executions", json=body)
    identifier = response.json()["id"]
    assert (await harness.client.post("/api/projects/project/executions", json=body)).json()[
        "id"
    ] == identifier
    await harness.client.post(
        f"/api/projects/project/executions/{identifier}/approve", json={"acknowledge": True}
    )
    async with harness.factory() as db:
        environment = await db.get(ERPEnvironment, "environment")
        environment.configuration = {"changed": True}
        await db.commit()
        await process_attempt(db, identifier, harness.settings)
        attempt = await db.get(ExecutionAttempt, identifier)
        assert attempt.status == "BLOCKED"
        assert not (await db.scalars(select(SandboxEvidence))).all()
        attempt.status = "DISPATCHING"
        attempt.deadline_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
        assert await expire_attempts(db) == 1
        assert attempt.status == "UNKNOWN_OUTCOME" and attempt.retry_count == 0


async def test_target_changed_during_dispatch_preserves_evidence_and_blocks_release(
    harness, monkeypatch
):
    from app.services.execution import INSTALLED_EXECUTORS

    original = INSTALLED_EXECUTORS["oracle_simulator"]

    async def changed_target(db, attempt, candidate, settings, connection=None):
        result = await original(db, attempt, candidate, settings, connection)
        async with harness.factory() as other_db:
            environment = await other_db.get(ERPEnvironment, "environment")
            environment.custody = "UNVERIFIED"
            await other_db.commit()
        return result

    monkeypatch.setitem(INSTALLED_EXECUTORS, "oracle_simulator", changed_target)
    attempt = await run_attempt(harness)
    assert attempt["status"] == "SUPERSEDED" and attempt["verdict"] == "INCONCLUSIVE"
    async with harness.factory() as db:
        evidence = await db.get(SandboxEvidence, attempt["result"]["evidence_id"])
        assert evidence.execution_attempt_id == attempt["id"]
        assert evidence.candidate_checksum == harness.candidate["checksum"]
        assert evidence.observations["cases"] and evidence.observations["files"]
    response = await harness.client.post(
        f"/api/projects/project/executions/{attempt['id']}/sign-off", json={"acknowledge": True}
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "execution_target_prohibited_or_unverified"


def test_assertions_use_observed_bytes_and_unknown_contract_is_inconclusive():
    plan = {
        "required_cases": [{"id": "rows", "expected": 999, "assertion": {"type": "CSV_ROW_COUNT"}}]
    }
    cases, verdict = assertions(b"id\n1\n", plan)
    assert verdict == "FAILED" and cases[0]["actual"] == 1
    assert (
        assertions(b"id\n1\n", {"required_cases": [{"id": "manual", "expected": 1}]})[1]
        == "INCONCLUSIVE"
    )
    malformed_sum = {
        "required_cases": [
            {"id": "total", "expected": "10.00", "assertion": {
                "type": "CSV_DECIMAL_SUM", "field": "amount"
            }}
        ]
    }
    assert assertions(b"id,amount\n1\n", malformed_sum)[1] == "INCONCLUSIVE"
    with pytest.raises(HTTPException):
        transition(SimpleNamespace(status="UNKNOWN_OUTCOME"), "QUEUED")
    with pytest.raises(HTTPException):
        target_policy(
            SimpleNamespace(
                custody="UNVERIFIED", environment_type="TEST", status="ACTIVE", archived_at=None
            )
        )
    assert (
        "EXECUTION_SIMULATOR_FORBIDDEN"
        in Settings(
            _env_file=None, app_env="production", execution_simulator_enabled=True
        ).configuration_issues()
    )
