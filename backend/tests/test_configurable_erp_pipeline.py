"""Data-defined ERP onboarding and generation-context acceptance coverage."""

import json
import io
import zipfile

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import (
    Base, ERPAssetVersion, ERPProfile, ERPProfileVersion, FeedbackGuidance,
    Project, ProjectStatus, PromptVersion,
)
from app.api.admin_auth import require_erp_admin
from app.api.erp_profiles import _extract_text_parts
from app.database import get_db
from app.dev_sqlite_migrations import migrate_legacy_sqlite
from app.main import app
from app.services.codegen.strategies import GenericJSONStrategy
from app.services.llm.mock import MockERPProvider
from app.services.prompt_compiler import PromptCompiler


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


class CapturingLLM:
    model = "demo-test-model"

    def __init__(self):
        self.requests = []

    async def generate_json(self, request):
        self.requests.append(request)
        return {"stage": "DEMO_ANALYSIS", "system_prompt": request.system_prompt,
                "user_prompt": request.user_prompt}


@pytest.mark.asyncio
async def test_demo_erp_is_created_as_data_and_changes_generation_without_source_branch(db_session):
    """A never-before-seen ERP drives actual generation through its profile data."""
    profile = ERPProfile(
        key="demo-erp", name="Demo ERP", display_name="Demo ERP", vendor="Example Systems",
        product_version="2026", status="PUBLISHED", active=True, configuration={},
    )
    db_session.add(profile)
    await db_session.flush()
    profile_version = ERPProfileVersion(
        profile_id=profile.id, version=1, status="PUBLISHED", supported_artifact_types=["DEMO_ANALYSIS"],
        configuration={"workflow": {"stages": [{"type": "DEMO_ANALYSIS", "depends_on": [],
                                                   "adapter": "generic_json", "task": "Analyze the sample objects"}]},
                       "validation": {"schema_conformity": False}},
    )
    db_session.add(profile_version)
    await db_session.flush()
    project = Project(
        name="Demo request", business_requirement="Map the demo supplier records for the nightly feed.",
        erp_schema_context={"entities": [{"name": "SUPPLIER_RECORD", "fields": ["supplier_key", "legal_name"]}]},
        erp_profile_id=profile.id, erp_profile_version_id=profile_version.id, status=ProjectStatus.ACTIVE,
    )
    db_session.add(project)
    await db_session.flush()

    stage_prompt_v1 = PromptVersion(
        scope="STAGE", profile_version_id=profile_version.id, name="Demo analysis", stage="DEMO_ANALYSIS",
        content="DEMO_PROMPT_V1: normalize using supplier_key.", version=1, status="PUBLISHED", variables=[],
    )
    knowledge = ERPAssetVersion(
        asset_id="demo-k-guide", profile_version_id=profile_version.id, asset_kind="KNOWLEDGE",
        name="Demo Supplier Mapping Guide", description="supplier legal name mapping", package_type="guide",
        version=1, status="PUBLISHED", text_content="DEMO_KNOWLEDGE: legal_name comes from verified_supplier_name.",
        metadata_json={},
    )
    package = ERPAssetVersion(
        asset_id="demo-package", profile_version_id=profile_version.id, asset_kind="PACKAGE",
        name="Demo Nightly Feed Package", description="nightly supplier feed implementation template",
        package_type="template", version=1, status="PUBLISHED",
        text_content="DEMO_PACKAGE: write the normalized result to the configured outbound sink.", metadata_json={},
    )
    feedback = FeedbackGuidance(
        project_id=project.id, scope="PROJECT", stage="DEMO_ANALYSIS",
        content="DEMO_FEEDBACK: preserve supplier_key in every output row.", status="APPROVED", version=1,
    )
    db_session.add_all([stage_prompt_v1, knowledge, package, feedback])
    await db_session.flush()

    compiler = PromptCompiler(db_session)
    first_context = await compiler.compile(project, "DEMO_ANALYSIS", "Analyze the sample objects", {})
    llm = CapturingLLM()
    generated_v1 = await GenericJSONStrategy().generate(project, "DEMO_ANALYSIS", {}, first_context, llm)
    assert "DEMO_PROMPT_V1" in generated_v1["system_prompt"]
    assert "DEMO_KNOWLEDGE" in generated_v1["system_prompt"]
    assert "DEMO_PACKAGE" in generated_v1["system_prompt"]
    assert "DEMO_FEEDBACK" in generated_v1["system_prompt"]
    assert first_context.provenance["erp_profile"]["version"] == 1
    assert first_context.provenance["prompt_versions"][0]["version"] == 1
    assert first_context.provenance["knowledge_asset_versions"][0]["version"] == 1
    assert first_context.provenance["standard_package_versions"][0]["version"] == 1
    offline_result = await GenericJSONStrategy().generate(project, "DEMO_ANALYSIS", {}, first_context, MockERPProvider())
    assert offline_result["erp_name"] == "Demo ERP"
    assert offline_result["artifact_type"] == "DEMO_ANALYSIS"
    assert offline_result["knowledge_references"] == ["Demo Supplier Mapping Guide"]
    assert offline_result["standard_packages_considered"] == ["Demo Nightly Feed Package"]

    # Admin creates profile v2, changes the prompt, and publishes it. Existing requests stay pinned to v1.
    profile_version_2 = ERPProfileVersion(
        profile_id=profile.id, version=2, status="PUBLISHED", supported_artifact_types=["DEMO_ANALYSIS"],
        configuration=profile_version.configuration,
    )
    db_session.add(profile_version_2)
    await db_session.flush()
    project_version_1 = project.erp_profile_version_id
    prompt_copy = PromptVersion(
        scope="STAGE", profile_version_id=profile_version_2.id, name="Demo analysis", stage="DEMO_ANALYSIS",
        content=stage_prompt_v1.content, version=1, status="PUBLISHED", variables=[],
    )
    stage_prompt_v2 = PromptVersion(
        scope="STAGE", profile_version_id=profile_version_2.id, name="Demo analysis", stage="DEMO_ANALYSIS",
        content="DEMO_PROMPT_V2: normalize using canonical_supplier_id.", version=2, status="PUBLISHED", variables=[],
    )
    db_session.add_all([prompt_copy, stage_prompt_v2])
    for source in (knowledge, package):
        db_session.add(ERPAssetVersion(
            asset_id=source.asset_id, profile_version_id=profile_version_2.id, asset_kind=source.asset_kind,
            name=source.name, description=source.description, package_type=source.package_type,
            version=source.version, status="PUBLISHED", text_content=source.text_content,
            metadata_json=source.metadata_json,
        ))
    await db_session.flush()
    project.erp_profile_version_id = profile_version_2.id
    await db_session.flush()
    second_context = await compiler.compile(project, "DEMO_ANALYSIS", "Analyze the sample objects", {})
    generated_v2 = await GenericJSONStrategy().generate(project, "DEMO_ANALYSIS", {}, second_context, llm)

    assert "DEMO_PROMPT_V2" in generated_v2["system_prompt"]
    assert "DEMO_PROMPT_V1" not in generated_v2["system_prompt"]
    assert project_version_1 == first_context.profile_version.id
    assert second_context.profile_version.id == profile_version_2.id
    assert first_context.provenance["prompt_versions"][0]["version"] == 1
    assert json.dumps(first_context.provenance) != json.dumps(second_context.provenance)
    assert len(llm.requests) == 2


@pytest.mark.asyncio
async def test_admin_api_onboards_demo_erp_and_generation_route_records_profile_context(monkeypatch):
    """Create and publish a new profile through admin APIs, then use it in live routes."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_db():
        async with factory() as session:
            yield session
            await session.commit()

    llm = CapturingLLM()
    monkeypatch.setattr("app.api.generation.get_llm_provider", lambda: llm)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_erp_admin] = lambda: "acceptance-admin"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            config = {
                "workflow": {"stages": [{"type": "DEMO_ANALYSIS", "label": "Demo Analysis",
                                           "depends_on": [], "adapter": "generic_json",
                                           "task": "Create a demo-specific analysis"}]},
                "validation": {"schema_conformity": True,
                               "rules": [{"name": "stage key", "type": "required_keys", "keys": ["stage"]}]},
            }
            created = await client.post("/api/erp-profiles", json={
                "name": "Demo ERP", "vendor": "Example Systems", "version": "2026",
                "supported_artifact_types": ["DEMO_ANALYSIS"], "configuration": config,
            })
            assert created.status_code == 201, created.text
            profile = created.json()
            profile_id = profile["id"]

            prompt = await client.post(f"/api/erp-profiles/{profile_id}/versions/1/prompts", json={
                "scope": "STAGE", "name": "Demo stage prompt", "stage": "DEMO_ANALYSIS",
                "content": "DEMO_UI_PROMPT: follow the approved demo supplier mapping guide.",
            })
            assert prompt.status_code == 201, prompt.text
            assert (await client.post(f"/api/erp-profiles/{profile_id}/prompts/{prompt.json()['id']}/publish")).status_code == 200

            asset_ids = {}
            for kind, name, body in [
                ("KNOWLEDGE", "Demo Guide", "DEMO_UI_KNOWLEDGE: supplier_code is the durable identifier."),
                ("PACKAGE", "Demo Package", "DEMO_UI_PACKAGE: use the outbound template for file layout."),
            ]:
                response = await client.post(f"/api/erp-profiles/{profile_id}/versions/1/assets", json={
                    "asset_kind": kind, "name": name, "description": "demo supplier outbound mapping",
                    "package_type": "template", "text_content": body,
                })
                assert response.status_code == 201, response.text
                asset = response.json()
                asset_ids[kind] = asset["asset_id"]
                assert (await client.post(f"/api/erp-profiles/{profile_id}/assets/{asset['asset_id']}/versions/1/publish")).status_code == 200

            published = await client.post(f"/api/erp-profiles/{profile_id}/versions/1/publish")
            assert published.status_code == 200, published.text
            audit = await client.get(f"/api/erp-profiles/{profile_id}/versions/1/audit")
            actions = {event["action"] for event in audit.json()}
            assert {"PROFILE_CREATED", "PROMPT_CREATED", "PROMPT_PUBLISHED",
                    "KNOWLEDGE_ASSET_CREATED", "PACKAGE_ASSET_CREATED", "PROFILE_VERSION_PUBLISHED"}.issubset(actions)
            public_profiles = await client.get("/api/erp-profiles")
            assert any(item["id"] == profile_id for item in public_profiles.json())

            created_request = await client.post("/api/projects", json={
                "name": "Demo supplier feed", "business_requirement": "Map supplier records for a nightly integration output.",
                "erp_schema_context": {"tables": [{"name": "DEMO_SUPPLIER", "columns": [{"name": "SUPPLIER_CODE"}]}]},
                "erp_profile_version_id": profile["profile_version_id"],
            })
            assert created_request.status_code == 201, created_request.text
            project = created_request.json()
            generated = await client.post(f"/api/projects/{project['id']}/generate", json={"stage": "DEMO_ANALYSIS"})
            assert generated.status_code == 200, generated.text
            assert "DEMO_UI_PROMPT" in generated.json()["content"]["system_prompt"]
            assert "DEMO_UI_KNOWLEDGE" in generated.json()["content"]["system_prompt"]
            assert "DEMO_UI_PACKAGE" in generated.json()["content"]["system_prompt"]
            assert generated.json()["input_context_snapshot"]["erp_profile"]["version"] == 1
            assert generated.json()["generation_run_id"]
            assert generated.json()["state"] == "PENDING_HUMAN_REVIEW"

            second_profile_version = await client.post(f"/api/erp-profiles/{profile_id}/versions")
            assert second_profile_version.status_code == 201, second_profile_version.text
            prompt_v2 = await client.post(f"/api/erp-profiles/{profile_id}/versions/2/prompts", json={
                "scope": "STAGE", "name": "Demo stage prompt", "stage": "DEMO_ANALYSIS",
                "content": "DEMO_UI_PROMPT_V2: use the new canonical supplier identifier.",
            })
            assert prompt_v2.status_code == 201, prompt_v2.text
            assert prompt_v2.json()["version"] == 2
            assert (await client.post(f"/api/erp-profiles/{profile_id}/prompts/{prompt_v2.json()['id']}/publish")).status_code == 200
            profile_v2_publish = await client.post(f"/api/erp-profiles/{profile_id}/versions/2/publish")
            assert profile_v2_publish.status_code == 200, profile_v2_publish.text

            pinned_update = await client.patch(f"/api/projects/{project['id']}", json={
                "erp_profile_version_id": second_profile_version.json()["id"],
            })
            assert pinned_update.status_code == 409

            request_v2 = await client.post("/api/projects", json={
                "name": "Demo supplier feed v2", "business_requirement": "Map supplier records for a nightly integration output.",
                "erp_schema_context": {"tables": [{"name": "DEMO_SUPPLIER", "columns": [{"name": "SUPPLIER_CODE"}]}]},
                "erp_profile_version_id": second_profile_version.json()["id"],
            })
            assert request_v2.status_code == 201, request_v2.text
            generated_v2 = await client.post(f"/api/projects/{request_v2.json()['id']}/generate", json={"stage": "DEMO_ANALYSIS"})
            assert generated_v2.status_code == 200, generated_v2.text
            assert "DEMO_UI_PROMPT_V2" in generated_v2.json()["content"]["system_prompt"]
            assert generated.json()["input_context_snapshot"]["prompt_versions"][0]["version"] == 1
            assert generated_v2.json()["input_context_snapshot"]["prompt_versions"][0]["version"] == 2
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_erp_admin, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_sqlite_schema_gets_additive_compatibility_upgrade():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("""
            CREATE TABLE erp_profiles (
              id VARCHAR(36) PRIMARY KEY, key VARCHAR(80), name VARCHAR(255), vendor VARCHAR(255),
              product_version VARCHAR(128), description TEXT, active BOOLEAN, configuration JSON,
              created_at DATETIME, updated_at DATETIME)
        """)
        await connection.exec_driver_sql("""
            CREATE TABLE erp_profile_versions (
              id VARCHAR(36) PRIMARY KEY, profile_id VARCHAR(36), version INTEGER, status VARCHAR(24),
              supported_artifact_types JSON, configuration JSON, created_by VARCHAR(255), updated_by VARCHAR(255),
              published_at DATETIME, created_at DATETIME, updated_at DATETIME)
        """)
        await connection.exec_driver_sql("""
            CREATE TABLE projects (
              id VARCHAR(36) PRIMARY KEY, erp_profile_id VARCHAR(36), name VARCHAR(255),
              business_requirement TEXT, erp_schema_context JSON)
        """)
        await connection.exec_driver_sql("CREATE TABLE artifact_versions (id VARCHAR(36) PRIMARY KEY)")
        await connection.exec_driver_sql("""
            INSERT INTO erp_profiles (id,key,name,vendor,active,configuration,created_at,updated_at)
            VALUES ('profile-1','demo','Demo ERP','Example Systems',1,'{}','2026-01-01','2026-01-01')
        """)
        await connection.exec_driver_sql("""
            INSERT INTO erp_profile_versions (id,profile_id,version,status,supported_artifact_types,configuration,
              created_by,updated_by,created_at,updated_at)
            VALUES ('profile-version-1','profile-1',1,'PUBLISHED','[]','{}','test','test','2026-01-01','2026-01-01')
        """)
        await connection.exec_driver_sql("INSERT INTO projects (id,erp_profile_id,name) VALUES ('project-1','profile-1','Demo')")
        await connection.exec_driver_sql("INSERT INTO projects (id,erp_profile_id,name) VALUES ('legacy-project',NULL,'Demo ERP Sample Request')")
        await connection.run_sync(migrate_legacy_sqlite)
        columns = await connection.run_sync(lambda conn: {
            table: {item["name"] for item in __import__("sqlalchemy").inspect(conn).get_columns(table)}
            for table in ("erp_profiles", "projects", "artifact_versions")
        })
        assert {"display_name", "status", "created_by", "updated_by"}.issubset(columns["erp_profiles"])
        assert {"erp_profile_version_id", "requirement_version", "schema_context_version"}.issubset(columns["projects"])
        assert "generation_run_id" in columns["artifact_versions"]
        pinned = await connection.exec_driver_sql("SELECT erp_profile_version_id FROM projects WHERE id='project-1'")
        assert pinned.scalar_one() == "profile-version-1"
        legacy_pin = await connection.exec_driver_sql("SELECT erp_profile_version_id FROM projects WHERE id='legacy-project'")
        assert legacy_pin.scalar_one() == "profile-version-1"
        profile_name = await connection.exec_driver_sql("SELECT display_name FROM erp_profiles WHERE id='profile-1'")
        assert profile_name.scalar_one() == "Demo ERP"
    await engine.dispose()


@pytest.mark.asyncio
async def test_erp_admin_routes_require_configured_admin_key(monkeypatch):
    from types import SimpleNamespace
    import app.api.admin_auth as admin_auth

    monkeypatch.setattr(admin_auth, "get_settings", lambda: SimpleNamespace(erp_admin_api_key="admin-secret"))
    with pytest.raises(HTTPException) as missing:
        await require_erp_admin(None)
    assert missing.value.status_code == 401
    assert await require_erp_admin("admin-secret") == "erp-admin"


def test_package_archive_text_is_indexed_without_extracting_paths():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("samples/demo.sql", "SELECT demo_supplier.supplier_code FROM demo_supplier;")
        archive.writestr("binary.bin", b"not text")
    parts = _extract_text_parts("demo-standard.zip", "application/zip", payload.getvalue())
    assert len(parts) == 1
    assert "demo-standard.zip!/demo.sql" in parts[0]
    assert "demo_supplier.supplier_code" in parts[0]
