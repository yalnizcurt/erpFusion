"""Requirement uploads stay client scoped, private, and version checked."""

import hashlib
import stat
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import requirements
from app.config import Settings, get_settings
from app.main import create_app
from app.models import (
    Base,
    Client,
    ClientMembership,
    ERPEnvironment,
    ERPInstallation,
    ERPProfile,
    ERPProfileVersion,
    IdentitySubject,
    Project,
    ProjectInputRevision,
    PromptVersion,
    RequirementDocument,
)
from app.security.identity import Identity, get_current_identity
from app.services.workflow import WorkflowEngine


@pytest_asyncio.fixture
async def requirements_app(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        profile = ERPProfile(
            key="requirements-erp",
            name="Requirements ERP",
            display_name="Requirements ERP",
            vendor="Fixture",
            active=True,
        )
        session.add(profile)
        await session.flush()
        profile_version = ERPProfileVersion(
            profile_id=profile.id,
            version=1,
            status="PUBLISHED",
            supported_artifact_types=["FDD"],
            configuration={
                "workflow": {
                    "stages": [
                        {
                            "type": "FDD",
                            "depends_on": [],
                            "adapter": "generic_json",
                            "task": "Build a functional design.",
                        }
                    ]
                },
                "validation": {"schema_conformity": False},
            },
        )
        session.add(profile_version)
        await session.flush()
        session.add(
            PromptVersion(
                scope="STAGE",
                profile_version_id=profile_version.id,
                name="Functional design",
                stage="FDD",
                content="Produce a functional design from the supplied requirement.",
                version=1,
                status="PUBLISHED",
                variables=[],
            )
        )
        client_a = Client(client_key="requirements-a", display_name="Requirements A")
        client_b = Client(client_key="requirements-b", display_name="Requirements B")
        subject_a = IdentitySubject(issuer="https://fixture.test", subject="admin-a")
        subject_b = IdentitySubject(issuer="https://fixture.test", subject="admin-b")
        session.add_all([client_a, client_b, subject_a, subject_b])
        await session.flush()
        for client, subject in ((client_a, subject_a), (client_b, subject_b)):
            session.add(
                ClientMembership(client_id=client.id, subject_id=subject.id, role="CLIENT_ADMIN")
            )
        installation = ERPInstallation(
            client_id=client_a.id,
            erp_profile_id=profile.id,
            installation_key="primary",
            display_name="Primary ERP",
        )
        session.add(installation)
        await session.flush()
        environment = ERPEnvironment(
            client_id=client_a.id,
            installation_id=installation.id,
            environment_key="sandbox",
            display_name="Sandbox",
        )
        session.add(environment)
        await session.flush()
        project = Project(
            name="Supplier integration",
            business_requirement="Map supplier records to the outbound feed.",
            erp_schema_context={"entities": []},
            erp_profile_id=profile.id,
            erp_profile_version_id=profile_version.id,
            client_id=client_a.id,
            erp_installation_id=installation.id,
            erp_environment_id=environment.id,
            created_by_subject_id=subject_a.id,
        )
        session.add(project)
        await session.flush()
        for artifact in await WorkflowEngine(session).initialize_project_artifacts(project):
            artifact.client_id = client_a.id
        session.add(
            ProjectInputRevision(
                project_id=project.id,
                client_id=client_a.id,
                revision=0,
                created_by_subject_id=subject_a.id,
                snapshot={
                    "requirement": project.business_requirement,
                    "requirement_version": project.requirement_version,
                    "schema_context": project.erp_schema_context,
                    "schema_context_version": project.schema_context_version,
                    "profile_version_id": profile_version.id,
                },
            )
        )
        await session.commit()

    actor_a = Identity(user_id="admin-a", issuer="https://fixture.test", subject_id=subject_a.id)
    actor_b = Identity(user_id="admin-b", issuer="https://fixture.test", subject_id=subject_b.id)

    async def session_dependency():
        async with factory() as session:
            yield session
            await session.commit()

    settings = Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        database_url="sqlite+aiosqlite:///:memory:",
        llm_provider="mock",
        artifact_storage_path=str(tmp_path),
    )
    application = create_app(
        settings=settings, engine=engine, session_dependency=session_dependency
    )
    application.dependency_overrides[get_current_identity] = lambda: actor_a
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as http:
        yield http, application, factory, project.id, client_a.id, actor_a, actor_b, tmp_path
    await engine.dispose()


def use_actor(application, actor):
    application.dependency_overrides[get_current_identity] = lambda: actor


def upload(
    http, project_id, payload=b"supplier requirements", filename="requirements.txt", version=1
):
    return http.post(
        f"/api/projects/{project_id}/requirements",
        data={"expected_requirement_version": str(version)},
        files={"file": (filename, payload, "text/plain")},
    )


@pytest.mark.asyncio
async def test_upload_is_private_scoped_and_checksum_checked(requirements_app, monkeypatch):
    http, application, factory, project_id, client_id, actor_a, actor_b, storage = requirements_app

    async def clean_scan(*_args):
        return "CLEAN"

    async def extract(_data, _extension):
        return "Supplier key must remain stable.", None

    monkeypatch.setattr(requirements, "scan_document", clean_scan)
    monkeypatch.setattr(requirements, "parse_document", extract)
    payload = b"private source document"
    response = await upload(http, project_id, payload)
    assert response.status_code == 201, response.text
    document = response.json()
    assert document["extraction_status"] == "READY"
    assert document["checksum"] == hashlib.sha256(payload).hexdigest()

    async with factory() as session:
        stored = await session.get(RequirementDocument, document["id"])
        project = await session.get(Project, project_id)
        history = list(
            (
                await session.scalars(
                    select(ProjectInputRevision)
                    .where(ProjectInputRevision.project_id == project_id)
                    .order_by(ProjectInputRevision.revision)
                )
            ).all()
        )
        assert stored.client_id == client_id
        assert stored.created_by_subject_id == actor_a.subject_id
        assert stored.storage_path.startswith(str(storage))
        assert stat.S_IMODE(Path(stored.storage_path).stat().st_mode) == 0o600
        assert project.requirement_version == 2
        assert len(history) == 2
        assert history[0].snapshot["requirement"] == "Map supplier records to the outbound feed."
        assert "Supplier key must remain stable." in history[1].snapshot["requirement"]

    downloaded = await http.get(
        f"/api/projects/{project_id}/requirements/{document['id']}/download"
    )
    assert downloaded.status_code == 200
    assert downloaded.content == payload
    assert downloaded.headers["cache-control"] == "no-store"

    use_actor(application, actor_b)
    hidden = await http.get(f"/api/projects/{project_id}/requirements")
    assert hidden.status_code == 404
    use_actor(application, actor_a)

    async with factory() as session:
        stored = await session.get(RequirementDocument, document["id"])
        Path(stored.storage_path).write_bytes(b"tampered")
    corrupt = await http.get(f"/api/projects/{project_id}/requirements/{document['id']}/download")
    assert corrupt.status_code == 409
    assert corrupt.json()["detail"] == "DOCUMENT_CHECKSUM_MISMATCH"


@pytest.mark.asyncio
async def test_requirement_revision_cas_conflicts_preserve_project_history(
    requirements_app, monkeypatch
):
    http, _, factory, project_id, _, _, _, _ = requirements_app

    async def clean_scan(*_args):
        return "CLEAN"

    async def extract(_data, _extension):
        return "Updated approved requirement text.", None

    monkeypatch.setattr(requirements, "scan_document", clean_scan)
    monkeypatch.setattr(requirements, "parse_document", extract)
    accepted = await upload(http, project_id, b"new requirement")
    assert accepted.status_code == 201, accepted.text
    current_requirement = (
        "Map supplier records to the outbound feed.\n\nSource: requirements.txt\n"
        "Updated approved requirement text."
    )

    stale_edit = await http.patch(
        f"/api/projects/{project_id}",
        json={
            "business_requirement": "Overwrite from an old editor session.",
            "expected_requirement_version": 1,
        },
    )
    assert stale_edit.status_code == 409

    stale_upload = await upload(http, project_id, b"stale upload", version=1)
    assert stale_upload.status_code == 409

    async with factory() as session:
        project = await session.get(Project, project_id)
        documents = list((await session.scalars(select(RequirementDocument))).all())
        history = list(
            (
                await session.scalars(
                    select(ProjectInputRevision)
                    .where(ProjectInputRevision.project_id == project_id)
                    .order_by(ProjectInputRevision.revision)
                )
            ).all()
        )
        assert project.business_requirement == current_requirement
        assert project.requirement_version == 2
        assert len(documents) == 1
        assert len(history) == 2


@pytest.mark.asyncio
async def test_infected_and_unparseable_uploads_are_blocked_without_revision(
    requirements_app, monkeypatch
):
    http, _, factory, project_id, _, _, _, storage = requirements_app

    async def infected_scan(*_args):
        return "INFECTED"

    monkeypatch.setattr(requirements, "scan_document", infected_scan)
    blocked = await upload(http, project_id, b"malware sample")
    assert blocked.status_code == 422
    assert blocked.json()["detail"] == "DOCUMENT_SCAN_REJECTED"
    assert (await http.get(f"/api/projects/{project_id}/requirements")).json() == []
    assert list(storage.rglob("*")) == []

    async def clean_scan(*_args):
        return "CLEAN"

    async def fail_extract(*_args):
        return "", "DOCUMENT_FORMAT_INVALID"

    monkeypatch.setattr(requirements, "scan_document", clean_scan)
    monkeypatch.setattr(requirements, "parse_document", fail_extract)
    recorded = await upload(http, project_id, b"unparseable document")
    assert recorded.status_code == 201, recorded.text
    assert recorded.json()["extraction_status"] == "BLOCKED"
    assert recorded.json()["extraction_error"] == "DOCUMENT_FORMAT_INVALID"

    async with factory() as session:
        project = await session.get(Project, project_id)
        documents = list((await session.scalars(select(RequirementDocument))).all())
        history = list(
            (
                await session.scalars(
                    select(ProjectInputRevision).where(
                        ProjectInputRevision.project_id == project_id
                    )
                )
            ).all()
        )
        assert project.requirement_version == 1
        assert project.business_requirement == "Map supplier records to the outbound feed."
        assert len(documents) == 1
    assert len(history) == 1
    assert list(storage.rglob("*"))


@pytest.mark.asyncio
async def test_download_requires_clean_scan_in_production_but_allows_dev_unscanned(
    requirements_app,
):
    http, application, factory, project_id, client_id, actor, _, storage = requirements_app
    scan_states = ("CLEAN", "NOT_CONFIGURED", "UNAVAILABLE", "INFECTED")
    ids = {}
    async with factory() as session:
        for scan_status in scan_states:
            payload = f"document {scan_status}".encode()
            path = storage / f"{scan_status}.txt"
            path.write_bytes(payload)
            document = RequirementDocument(
                project_id=project_id,
                client_id=client_id,
                filename=f"{scan_status}.txt",
                mime_type="text/plain",
                size_bytes=len(payload),
                checksum=hashlib.sha256(payload).hexdigest(),
                storage_path=str(path),
                extraction_status="READY" if scan_status == "CLEAN" else "BLOCKED",
                extracted_text="",
                extraction_error=None if scan_status == "CLEAN" else "DOCUMENT_SCAN_REQUIRED",
                scan_status=scan_status,
                requirement_version=1,
                created_by_subject_id=actor.subject_id,
            )
            session.add(document)
            await session.flush()
            ids[scan_status] = document.id
        await session.commit()

    production = Settings(
        _env_file=None,
        app_env="production",
        auth_mode="oidc",
        llm_provider="bedrock",
        artifact_storage_path=str(storage),
    )
    application.dependency_overrides[get_settings] = lambda: production
    for scan_status in scan_states:
        response = await http.get(
            f"/api/projects/{project_id}/requirements/{ids[scan_status]}/download"
        )
        assert response.status_code == (200 if scan_status == "CLEAN" else 409)
        if response.status_code == 409:
            assert response.json()["detail"] == "Document quarantined"

    development = Settings(
        _env_file=None,
        app_env="development",
        demo_mode=True,
        llm_provider="mock",
        artifact_storage_path=str(storage),
    )
    application.dependency_overrides[get_settings] = lambda: development
    response = await http.get(
        f"/api/projects/{project_id}/requirements/{ids['NOT_CONFIGURED']}/download"
    )
    assert response.status_code == 200
