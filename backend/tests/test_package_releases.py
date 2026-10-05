"""Exact candidates, complete ZIPs, manual evidence, and stale release gates."""

import io
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import packages
from app.api.projects import _project_summaries
from app.config import Settings, get_settings
from app.database import get_db
from app.models import (
    Artifact,
    ArtifactVersion,
    Base,
    Client,
    ERPEnvironment,
    ERPInstallation,
    ERPProfile,
    ERPProfileVersion,
    GateStatus,
    IdentitySubject,
    Project,
    VersionState,
)
from app.models.connection import ERPConnection
from app.models.engineering import PackageCandidate, PackageRelease, SandboxEvidence
from app.security.identity import Identity, get_current_identity
from app.services.packages import bundle, source_files
from app.services.workflow import WorkflowEngine


@pytest.mark.parametrize("name", ["../secret", "/secret", "a/../../b", "C:\\file", "manifest.json"])
def test_archive_traversal_and_manifest_override_blocked(name):
    with pytest.raises(HTTPException):
        source_files("CODE", {"files_by_name": {name: "code"}}, {}, {})


def test_all_configured_generic_and_legacy_sources_in_bundle():
    files = source_files(
        "CODE",
        {
            "files": [{"name": "extension.al", "content": "AL source"}],
            "files_by_name": {"other.json": "{}"},
            "pks_content": "spec",
            "pkb_content": "body",
            "package_name": "PKG",
            "full_mode_sql": "SELECT 1",
            "custom": "configured",
        },
        {"output_names": {"custom": "custom.txt"}},
        {},
    )
    assert {
        "extension.al",
        "other.json",
        "PKG.pks",
        "PKG.pkb",
        "code-full_mode_sql.sql",
        "custom.txt",
        "artifacts/code.json",
    } <= set(files)
    assert bundle(files) == bundle(files)
    with zipfile.ZipFile(io.BytesIO(bundle(files))) as archive:
        assert all(archive.read(name) == value for name, value in files.items())


@pytest.mark.parametrize("value", [[], "unexpected", 42])
def test_malformed_named_file_output_is_blocked(value):
    with pytest.raises(HTTPException, match="package_file_contract_invalid"):
        source_files("CODE", {"files_by_name": value}, {}, {})


@pytest.mark.asyncio
async def test_candidate_manual_release_invalidation_history_and_client_boundaries(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as db:
        await db.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add_all(
            [
                Client(id="client", client_key="fixture", display_name="Fixture"),
                IdentitySubject(id="subject", issuer="development", subject="admin"),
                ERPProfile(id="profile", key="fixture", name="Fixture", vendor="Fixture"),
            ]
        )
        await db.flush()
        profile = ERPProfileVersion(
            id="profile-version",
            profile_id="profile",
            version=1,
            status="PUBLISHED",
            configuration={
                "validation": {"schema_conformity": False},
                "workflow": {"stages": [{"type": name} for name in ("ASSESS", "CODE")]},
                "testing": {
                    "version": "1",
                    "required_cases": [{"id": "extract", "expected": {"rows": 1}}],
                },
            },
        )
        installation = ERPInstallation(
            id="installation",
            client_id="client",
            erp_profile_id="profile",
            installation_key="fixture",
            display_name="Fixture",
        )
        db.add_all([profile, installation])
        await db.flush()
        db.add(
            ERPEnvironment(
                id="environment",
                client_id="client",
                installation_id="installation",
                environment_key="sandbox",
                display_name="Sandbox",
                environment_type="SANDBOX",
                custody="ERPFUSION_MANAGED",
                execution_mode="ASSISTED",
            )
        )
        await db.flush()
        project = Project(
            id="project",
            name="Fixture",
            client_id="client",
            erp_installation_id="installation",
            erp_environment_id="environment",
            erp_profile_id="profile",
            erp_profile_version_id="profile-version",
            business_requirement="A fixture extract",
            erp_schema_context={},
        )
        db.add(project)
        await db.flush()
        for stage, content in [
            ("ASSESS", {"summary": "Approved"}),
            (
                "CODE",
                {
                    "files": [
                        {"name": "extract.sql", "content": "SELECT 1 FROM dual;"},
                        {
                            "name": "definition.xdm",
                            "content": "qualified native format not claimed",
                        },
                    ]
                },
            ),
        ]:
            artifact = Artifact(
                project_id=project.id,
                client_id="client",
                artifact_type=stage,
                current_version=1,
                gate_status=GateStatus.APPROVED,
            )
            db.add(artifact)
            await db.flush()
            db.add(
                ArtifactVersion(
                    artifact_id=artifact.id,
                    client_id="client",
                    version_number=1,
                    state=VersionState.APPROVED,
                    content=content,
                    reviewer_subject_id="subject",
                    input_context_snapshot={
                        "input_bindings": await WorkflowEngine(db).current_bindings(
                            project.id, stage
                        )
                    },
                )
            )
            await db.flush()
        db.add(
            ERPConnection(
                id="connection",
                client_id="client",
                installation_id="installation",
                environment_id="environment",
                adapter="oracle_fusion_publisher",
                source_url="https://approved.oraclecloud.com",
                approved_hosts=["approved.oraclecloud.com"],
                expected_tenant="fixture",
                report_path="/Custom/Fixture.xdo",
                permitted_operations=["PING", "RUN_REPORT"],
                configuration_version=1,
                secret_ref="scoped AWS reference fixture",
                secret_version="fixture-version",
            )
        )
        await db.commit()

    async def sessions():
        async with factory() as db:
            try:
                yield db
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    actor = Identity(
        user_id="admin",
        issuer="development",
        provider="development",
        is_fixture=True,
        roles=frozenset({"platform_admin"}),
    )
    settings = Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        llm_provider="mock",
        artifact_storage_path=str(tmp_path),
        auth_mode="development",
    )
    app = FastAPI()
    app.include_router(packages.router)
    app.dependency_overrides[get_db] = sessions
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_current_identity] = lambda: actor
    base = "/api/projects/project"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:

            async def project_summary():
                async with factory() as db:
                    project = await db.get(Project, "project")
                    return (await _project_summaries(db, [project]))[0]

            before = (await http.get(base + "/package")).json()
            assert before["available"] and before["candidate_id"] is None
            summary = await project_summary()
            assert not summary.package_available
            assert summary.package_kind is None and summary.package_download_url is None
            async with factory() as db:
                profile = await db.get(ERPProfileVersion, "profile-version")
                saved_config = profile.configuration
                profile.configuration = {**saved_config, "validation": {"schema_conformity": True}}
                await db.commit()
            missing_checks = (await http.get(base + "/package")).json()
            assert not missing_checks["available"]
            assert "validation_evidence_missing:CODE" in missing_checks["blockers"]
            async with factory() as db:
                profile = await db.get(ERPProfileVersion, "profile-version")
                profile.configuration = saved_config
                code = await db.scalar(
                    select(ArtifactVersion).join(Artifact).where(Artifact.artifact_type == "CODE")
                )
                saved_content = code.content
                code.content = {"summary": "Only a summary"}
                await db.commit()
            no_implementation = (await http.get(base + "/package")).json()
            assert "implementation_package_output_required" in no_implementation["blockers"]
            async with factory() as db:
                code = await db.scalar(
                    select(ArtifactVersion).join(Artifact).where(Artifact.artifact_type == "CODE")
                )
                code.content = saved_content
                await db.commit()
            assert (await http.get(base + "/package/download")).status_code == 409
            async with factory() as db:
                assert await db.scalar(select(func.count()).select_from(PackageCandidate)) == 0
            response = await http.post(base + "/package/candidates", json={})
            assert response.status_code == 201, response.text
            candidate = response.json()
            summary = await project_summary()
            assert summary.package_available and summary.package_kind == "candidate"
            assert summary.package_download_url == candidate["download_url"]
            assert (await http.post(base + "/package/candidates", json={})).json()[
                "id"
            ] == candidate["id"]
            downloaded = await http.get(base + "/package/download")
            assert downloaded.status_code == 200
            with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
                assert {
                    "extract.sql",
                    "definition.xdm",
                    "artifacts/assess.json",
                    "artifacts/code.json",
                    "manifest.json",
                } <= set(archive.namelist())
            source_url = f"{base}/package/candidates/{candidate['id']}/files"
            exact_sql = await http.get(source_url, params={"name": "extract.sql"})
            assert exact_sql.status_code == 200
            assert exact_sql.content == b"SELECT 1 FROM dual;"
            assert exact_sql.headers["cache-control"] == "private, no-store"
            assert exact_sql.headers["x-content-type-options"] == "nosniff"
            exact_definition = await http.get(source_url, params={"name": "definition.xdm"})
            assert exact_definition.status_code == 200
            assert exact_definition.content == b"qualified native format not claimed"
            assert (await http.get(source_url, params={"name": "missing.sql"})).status_code == 404
            assert (
                await http.get(source_url, params={"name": "../extract.sql"})
            ).status_code == 409
            async with factory() as db:
                saved_candidate = await db.get(PackageCandidate, candidate["id"])
                candidate_path = Path(saved_candidate.storage_path)
            original_bundle = candidate_path.read_bytes()
            candidate_path.write_bytes(original_bundle + b"tamper")
            tampered = await http.get(source_url, params={"name": "extract.sql"})
            candidate_path.write_bytes(original_bundle)
            assert tampered.status_code == 503
            evidence_status = (await http.get(base + "/sandbox/evidence")).json()
            assert evidence_status["automatic_execution_supported"] is False
            body = {
                "candidate_id": candidate["id"],
                "candidate_checksum": candidate["checksum"],
                "installed_candidate_checksum": candidate["checksum"],
                "environment_id": "environment",
                "connection_version": 1,
                "test_plan_sha256": evidence_status["test_plan_sha256"],
                "acknowledge_assisted_evidence": True,
                "cases": [
                    {
                        "id": "extract",
                        "status": "PASSED",
                        "expected": {"rows": 1},
                        "actual": {"rows": 1},
                        "evidence_sha256": "a" * 64,
                    }
                ],
            }
            assert (
                await http.post(base + "/sandbox/evidence", json={**body, "cases": []})
            ).status_code == 422
            assert (
                await http.post(
                    base + "/sandbox/evidence", json={**body, "candidate_checksum": "b" * 64}
                )
            ).status_code == 409
            wrong = {**body, "cases": [{**body["cases"][0], "actual": {"rows": 2}}]}
            failed = await http.post(base + "/sandbox/evidence", json=wrong)
            assert failed.status_code == 201 and failed.json()["status"] == "FAILED"
            assert (
                await http.post(
                    base + f"/sandbox/evidence/{failed.json()['id']}/sign-off",
                    json={"acknowledge_assisted_evidence": True},
                )
            ).status_code == 409
            passed = await http.post(base + "/sandbox/evidence", json=body)
            assert passed.status_code == 201, passed.text
            assert passed.json()["observations"]["remote_exact_bytes_verified"] is False
            signoff_path = base + f"/sandbox/evidence/{passed.json()['id']}/sign-off"
            release = await http.post(signoff_path, json={"acknowledge_assisted_evidence": True})
            assert release.status_code == 201, release.text
            assert (await http.get(base + "/package")).json()["kind"] == "release"
            summary = await project_summary()
            assert summary.package_available and summary.package_kind == "release"
            assert summary.package_download_url == release.json()["download_url"]
            released = await http.get(base + "/package/download")
            with zipfile.ZipFile(io.BytesIO(released.content)) as archive:
                assert {"candidate.zip", "test-report.json", "release-manifest.json"} == set(
                    archive.namelist()
                )
                assert archive.read("candidate.zip") == downloaded.content
            newer_failure = await http.post(base + "/sandbox/evidence", json=wrong)
            assert newer_failure.status_code == 201
            assert (await http.get(base + "/package")).json()["kind"] == "candidate"
            summary = await project_summary()
            assert summary.package_available and summary.package_kind == "candidate"
            assert summary.package_download_url == candidate["download_url"]
            assert (
                await http.post(signoff_path, json={"acknowledge_assisted_evidence": True})
            ).status_code == 409
            async with factory() as db:
                changed = await db.get(ERPConnection, "connection")
                changed.configuration_version += 1
                await db.commit()
            assert (await http.get(base + "/package")).json()["kind"] == "candidate"
            summary = await project_summary()
            assert summary.package_available and summary.package_kind == "candidate"
            assert (
                await http.post(signoff_path, json={"acknowledge_assisted_evidence": True})
            ).status_code == 409
            async with factory() as db:
                changed = await db.get(Project, "project")
                changed.requirement_version += 1
                changed.workflow_revision += 1
                changed.workflow_status = "RELEASED"
                await db.commit()
            stale = await http.get(base + "/package")
            assert stale.status_code == 200 and not stale.json()["available"]
            summary = await project_summary()
            assert not summary.package_available
            assert summary.package_kind is None and summary.package_download_url is None
            assert (await http.get(base + "/package/download")).status_code == 409
            assert (await http.get(candidate["download_url"])).content == downloaded.content
            historical_release = await http.get(release.json()["download_url"])
            assert historical_release.content == released.content
            actor = Identity(user_id="outsider", issuer="development", provider="development")
            assert (await http.get(candidate["download_url"])).status_code == 404
            assert (await http.get(source_url, params={"name": "extract.sql"})).status_code == 404
            assert (await http.get(release.json()["download_url"])).status_code == 404
            assert (await http.get(base + "/sandbox/evidence")).status_code == 404
        async with factory() as db:
            assert await db.scalar(select(func.count()).select_from(PackageCandidate)) == 1
            assert await db.scalar(select(func.count()).select_from(PackageRelease)) == 1
            assert await db.scalar(select(func.count()).select_from(SandboxEvidence)) == 3
    finally:
        await engine.dispose()
