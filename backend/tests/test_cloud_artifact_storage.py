"""Optional cloud storage checks use synthetic SDK responses, never live AWS."""

import hashlib
import ssl
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.core.readiness import check_configured_storage_readiness
from app.database import create_database_engine
from app.main import create_app
from app.models import Base, ERPAssetVersion
from app.services import artifact_storage

PRIVATE_FLAGS = dict.fromkeys(
    ["BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"], True
)


def test_cloud_database_ca_enforces_verified_tls(monkeypatch):
    engine_arguments = {}
    context = ssl.create_default_context()

    def verified_context(*, cafile):
        assert cafile == "/fixture/rds-ca-bundle.pem"
        return context

    def engine_factory(url, **kwargs):
        engine_arguments.update(url=url, **kwargs)
        return object()

    monkeypatch.setattr("app.database.ssl.create_default_context", verified_context)
    monkeypatch.setattr("app.database.create_async_engine", engine_factory)
    create_database_engine(
        Settings(
            _env_file=None,
            database_url="postgresql://fixture:synthetic@db.example.test/erp",
            database_ssl_ca_file="/fixture/rds-ca-bundle.pem",
        )
    )
    assert engine_arguments["url"].startswith("postgresql+asyncpg://")
    assert engine_arguments["connect_args"]["ssl"] is context
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


@pytest.mark.asyncio
async def test_local_database_ignores_cloud_ca_setting():
    engine = create_database_engine(
        Settings(
            _env_file=None,
            database_url="sqlite+aiosqlite:///:memory:",
            database_ssl_ca_file="/unavailable/cloud-ca.pem",
        )
    )
    try:
        async with engine.connect():
            pass
    finally:
        await engine.dispose()


def storage_settings(**overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        llm_provider="mock",
        **({"artifact_storage_backend": "s3", "artifact_s3_bucket": "fixture-private"} | overrides),
    )


class FixtureS3:
    def __init__(self, *, public: bool = False, fail_write: bool = False):
        self.public = public
        self.fail_write = fail_write
        self.operations: list[tuple[str, dict[str, Any]]] = []

    def close(self):
        pass

    def head_bucket(self, **kwargs):
        self.operations.append(("head_bucket", kwargs))
        return {}

    def get_public_access_block(self, **kwargs):
        self.operations.append(("get_public_access_block", kwargs))
        return {"PublicAccessBlockConfiguration": PRIVATE_FLAGS}

    def get_bucket_policy_status(self, **kwargs):
        self.operations.append(("get_bucket_policy_status", kwargs))
        return {"PolicyStatus": {"IsPublic": self.public}}

    def put_object(self, **kwargs):
        self.operations.append(("put_object", kwargs))
        if self.fail_write:
            raise RuntimeError("SECRET_PROVIDER_RESPONSE")
        return {"ETag": "fixture"}


@pytest.mark.asyncio
async def test_official_s3_sdk_contract_and_default_credentials(monkeypatch):
    # Installed cloud builds exercise the official SDK contract. Minimal local
    # installs continue to run the storage tests using the fixture client.
    pytest.importorskip("boto3", reason="Optional [aws] extra is not installed")
    from botocore.stub import Stubber

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "synthetic-fixture")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-fixture")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    client = artifact_storage._s3_client(storage_settings())
    assert client.meta.config.connect_timeout == 1
    assert client.meta.config.read_timeout == 2
    assert client.meta.config.retries["total_max_attempts"] == 1
    monkeypatch.setattr(artifact_storage, "_s3_client", lambda _settings: client)
    with Stubber(client) as stubber:
        expected = {"Bucket": "fixture-private"}
        stubber.add_response("head_bucket", {}, expected)
        stubber.add_response(
            "get_public_access_block", {"PublicAccessBlockConfiguration": PRIVATE_FLAGS}, expected
        )
        stubber.add_response(
            "get_bucket_policy_status", {"PolicyStatus": {"IsPublic": False}}, expected
        )
        stubber.add_response(
            "put_object",
            {"ETag": "fixture"},
            {
                "Bucket": "fixture-private",
                "Key": "erp-assets/profile/asset/1/source.sql",
                "Body": b"SOURCE",
                "ContentType": "text/plain",
                "ServerSideEncryption": "AES256",
                "IfNoneMatch": "*",
            },
        )
        artifact_storage.assert_private_s3_bucket(storage_settings())
        await artifact_storage.save_asset_file(
            storage_settings(),
            "s3://fixture-private/erp-assets/profile/asset/1",
            "source.sql",
            b"SOURCE",
            "text/plain",
        )
        stubber.assert_no_pending_responses()


@pytest.mark.asyncio
async def test_private_s3_readiness_only_reads_configuration(monkeypatch):
    client = FixtureS3()
    monkeypatch.setattr(artifact_storage, "_s3_client", lambda _settings: client)
    result = await check_configured_storage_readiness(storage_settings())
    assert result.status == "pass"
    assert [name for name, _ in client.operations] == [
        "head_bucket",
        "get_public_access_block",
        "get_bucket_policy_status",
    ]
    for _, parameters in client.operations:
        assert parameters == {"Bucket": "fixture-private"}


@pytest.mark.asyncio
async def test_public_bucket_and_provider_failures_fail_closed(monkeypatch):
    monkeypatch.setattr(artifact_storage, "_s3_client", lambda _settings: FixtureS3(public=True))
    result = await check_configured_storage_readiness(storage_settings())
    assert result.codes == ["artifact_storage_bucket_not_private"]

    def unavailable(_settings):
        raise RuntimeError("SECRET_PROVIDER_RESPONSE")

    monkeypatch.setattr(artifact_storage, "_s3_client", unavailable)
    result = await check_configured_storage_readiness(storage_settings())
    assert result.codes == ["artifact_storage_unavailable"]
    assert "SECRET" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_incomplete_public_access_blocks_fail_closed(monkeypatch):
    client = FixtureS3()
    monkeypatch.setattr(
        client,
        "get_public_access_block",
        lambda **_kwargs: {
            "PublicAccessBlockConfiguration": PRIVATE_FLAGS | {"BlockPublicPolicy": False}
        },
    )
    monkeypatch.setattr(artifact_storage, "_s3_client", lambda _settings: client)
    result = await check_configured_storage_readiness(storage_settings())
    assert result.codes == ["artifact_storage_bucket_not_private"]


@pytest.mark.asyncio
async def test_optional_aws_sdk_missing_fails_readiness_with_safe_code(monkeypatch):
    def absent(_module):
        raise ImportError("fixture dependency absent")

    monkeypatch.setattr(artifact_storage, "import_module", absent)
    result = await check_configured_storage_readiness(storage_settings())
    assert result.codes == ["artifact_storage_dependency_missing"]


@pytest.mark.asyncio
async def test_local_files_remain_available_and_cannot_overwrite(tmp_path):
    settings = storage_settings(
        artifact_storage_backend="local", artifact_storage_path=str(tmp_path)
    )
    directory = artifact_storage.asset_directory(settings, "profile", "asset", 1)
    path = await artifact_storage.save_asset_file(
        settings, directory, "standard.pks", b"SOURCE", None
    )
    from pathlib import Path

    assert Path(path).read_bytes() == b"SOURCE"
    with pytest.raises(artifact_storage.ArtifactStorageError):
        await artifact_storage.save_asset_file(settings, directory, "standard.pks", b"OTHER", None)
    assert Path(path).read_bytes() == b"SOURCE"


@pytest.mark.asyncio
async def test_s3_asset_upload_persists_file_and_separate_metadata(monkeypatch, tmp_path):
    client = FixtureS3()
    monkeypatch.setattr(artifact_storage, "_s3_client", lambda _settings: client)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def sessions():
        async with factory() as db:
            try:
                yield db
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    settings = storage_settings(artifact_storage_path=str(tmp_path / "unused"))
    app = create_app(settings=settings, engine=engine, session_dependency=sessions)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            profile = await http.post(
                "/api/erp-profiles", json={"name": "Cloud ERP", "vendor": "Fixture", "version": "1"}
            )
            assert profile.status_code == 201, profile.text
            profile_id = profile.json()["id"]
            response = await http.post(
                f"/api/erp-profiles/{profile_id}/versions/1/assets/upload",
                params={"asset_kind": "PACKAGE", "name": "Standard source"},
                files=[("files", ("standard.pks", b"CREATE PACKAGE STANDARD", "text/plain"))],
            )
            assert response.status_code == 201, response.text
            metadata = response.json()[0]["metadata"]["files"][0]
            assert metadata["storage_path"].startswith("s3://fixture-private/erp-assets/")
            assert metadata["checksum"] == hashlib.sha256(b"CREATE PACKAGE STANDARD").hexdigest()
            writes = [parameters for name, parameters in client.operations if name == "put_object"]
            assert len(writes) == 1
            assert writes[0]["Body"] == b"CREATE PACKAGE STANDARD"
            assert writes[0]["ServerSideEncryption"] == "AES256"
            assert writes[0]["IfNoneMatch"] == "*"
            async with factory() as db:
                asset = (await db.execute(select(ERPAssetVersion))).scalar_one()
                assert "CREATE PACKAGE STANDARD" in asset.text_content
                assert asset.storage_path.startswith("s3://fixture-private/erp-assets/")
            assert not (tmp_path / "unused").exists()
            duplicate = await http.post(
                f"/api/erp-profiles/{profile_id}/versions/1/assets/upload",
                params={"asset_kind": "PACKAGE", "name": "Duplicate files"},
                files=[("files", ("same.sql", b"A")), ("files", ("same.sql", b"B"))],
            )
            assert duplicate.status_code == 400
            client.fail_write = True
            failed = await http.post(
                f"/api/erp-profiles/{profile_id}/versions/1/assets/upload",
                params={"asset_kind": "PACKAGE", "name": "Provider failure"},
                files=[("files", ("other.sql", b"OTHER"))],
            )
            assert failed.status_code == 503
            assert "SECRET_PROVIDER_RESPONSE" not in failed.text
    finally:
        await engine.dispose()
