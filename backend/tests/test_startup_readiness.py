"""Startup and health checks must observe deployed state without repairing it."""

import asyncio
import socket
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from asyncpg import InterfaceError, InternalClientError, InvalidPasswordError
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, inspect, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings
from app.core import readiness
from app.main import create_app
from app.models import Base


def build_settings(storage: Path, **overrides) -> Settings:
    """Use isolated explicit settings; real developer secrets are never fixture input."""
    values = {
        "_env_file": None,
        "app_env": "test",
        "demo_mode": True,
        "database_url": "sqlite+aiosqlite:///:memory:",
        "llm_provider": "mock",
        "groq_api_key": "",
        "erp_admin_api_key": "",
        "artifact_storage_path": str(storage),
    }
    values.update(overrides)
    return Settings(**values)


@pytest_asyncio.fixture
async def empty_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        yield engine
    finally:
        await engine.dispose()


async def provision_schema(engine: AsyncEngine, version: str | None = None) -> None:
    """Test-only setup represents externally migrated/provisioned deployment state."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        if version is not None:
            await connection.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
            )
            await connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:version)"),
                {"version": version},
            )


def record_read_statements(engine: AsyncEngine) -> list[str]:
    """Fail immediately if a startup/readiness/read operation attempts a write."""
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def before_cursor_execute(connection, cursor, statement, parameters, context, executemany):
        normalized = statement.lstrip().upper()
        assert normalized.startswith(("SELECT", "PRAGMA")), statement
        statements.append(statement)

    return statements


@pytest.mark.asyncio
async def test_startup_and_liveness_never_create_database_objects(empty_engine, tmp_path):
    statements = record_read_statements(empty_engine)
    application = create_app(settings=build_settings(tmp_path), engine=empty_engine)
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            for endpoint in ("/", "/health", "/health/live"):
                assert (await client.get(endpoint)).status_code == 200
            assert (await client.get("/")).json()["service"] == "HighStudio API"
    assert statements == []
    async with empty_engine.connect() as connection:
        tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
    assert tables == []


@pytest.mark.asyncio
async def test_default_runtime_is_lazy_and_not_created_by_liveness(monkeypatch, tmp_path):
    def forbidden_engine_creation(*args, **kwargs):
        raise AssertionError("Startup/liveness must not initialize a database engine")

    monkeypatch.setattr("app.main.create_database_engine", forbidden_engine_creation)
    application = create_app(settings=build_settings(tmp_path))
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            assert (await client.get("/health/live")).status_code == 200
        assert application.state.database_engine is None


@pytest.mark.asyncio
async def test_missing_migration_state_fails_readiness_without_repair(empty_engine, tmp_path):
    statements = record_read_statements(empty_engine)
    application = create_app(settings=build_settings(tmp_path), engine=empty_engine)
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            response = await client.get("/health/ready")
            assert response.status_code == 503
            assert response.headers["cache-control"] == "no-store"
            assert response.json()["checks"]["migrations"]["codes"] == ["migration_version_missing"]
            assert (await client.get("/health/live")).status_code == 200
    assert statements
    async with empty_engine.connect() as connection:
        tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
    assert tables == []


@pytest.mark.asyncio
async def test_wrong_migration_head_fails_readiness(empty_engine, tmp_path):
    await provision_schema(empty_engine, version="old-deployment-head")
    record_read_statements(empty_engine)
    result = await readiness.check_readiness(build_settings(tmp_path), empty_engine)
    assert result.status == "not_ready"
    assert result.checks["migrations"].codes == ["migration_version_mismatch"]
    async with empty_engine.connect() as connection:
        assert (
            await connection.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one() == "old-deployment-head"


@pytest.mark.asyncio
async def test_current_schema_and_provisioned_storage_are_ready_without_writes(
    empty_engine, tmp_path
):
    (current_head,) = readiness.required_migration_heads()
    await provision_schema(empty_engine, version=current_head)
    statements = record_read_statements(empty_engine)
    application = create_app(settings=build_settings(tmp_path), engine=empty_engine)
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            for _ in range(2):
                response = await client.get("/health/ready")
                assert response.status_code == 200
                assert response.json()["status"] == "ready"
                assert all(
                    check["status"] == "pass" for check in response.json()["checks"].values()
                )
    assert statements
    assert list(tmp_path.iterdir()) == []
    # The injected engine remains caller-owned after application shutdown.
    async with empty_engine.connect() as connection:
        assert (await connection.execute(text("SELECT 1"))).scalar_one() == 1


@pytest.mark.asyncio
async def test_stamped_but_missing_tables_fails_readiness(empty_engine, tmp_path):
    (current_head,) = readiness.required_migration_heads()
    async with empty_engine.begin() as connection:
        await connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        await connection.execute(
            text("INSERT INTO alembic_version VALUES (:version)"), {"version": current_head}
        )
    record_read_statements(empty_engine)
    result = await readiness.check_readiness(build_settings(tmp_path), empty_engine)
    assert result.status == "not_ready"
    assert result.checks["migrations"].status == "pass"
    assert result.checks["schema"].codes == ["required_tables_missing"]


@pytest.mark.asyncio
async def test_stamped_but_missing_columns_fails_readiness(empty_engine, tmp_path):
    (current_head,) = readiness.required_migration_heads()
    await provision_schema(empty_engine, version=current_head)
    async with empty_engine.begin() as connection:
        await connection.execute(text("ALTER TABLE projects DROP COLUMN description"))
    record_read_statements(empty_engine)
    result = await readiness.check_readiness(build_settings(tmp_path), empty_engine)
    assert result.status == "not_ready"
    assert result.checks["schema"].codes == ["required_columns_missing"]


@pytest.mark.asyncio
async def test_repeated_project_and_profile_reads_never_load_fixtures(empty_engine, tmp_path):
    await provision_schema(empty_engine)
    session_factory = async_sessionmaker(empty_engine, class_=AsyncSession, expire_on_commit=False)

    async def isolated_session():
        async with session_factory() as session:
            yield session

    record_read_statements(empty_engine)
    application = create_app(
        settings=build_settings(tmp_path), engine=empty_engine, session_dependency=isolated_session
    )
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            for _ in range(2):
                response = await client.get("/api/projects")
                assert response.status_code == 200
                assert response.json() == {
                    "projects": [],
                    "total": 0,
                    "next_offset": None,
                    "summary": {"awaiting_review": 0, "ready_for_sandbox": 0, "completed": 0},
                }
                response = await client.get("/api/erp-profiles")
                assert response.status_code == 200
                assert response.json() == []
    async with empty_engine.connect() as connection:
        for table in Base.metadata.sorted_tables:
            assert (
                await connection.execute(select(func.count()).select_from(table))
            ).scalar_one() == 0


@pytest.mark.asyncio
async def test_missing_production_configuration_fails_before_database_access(
    empty_engine, tmp_path
):
    statements = record_read_statements(empty_engine)
    settings = build_settings(tmp_path, app_env="production", llm_provider="groq")
    assert settings.configuration_issues()
    application = create_app(settings=settings, engine=empty_engine)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
    checks = response.json()["checks"]
    assert checks["configuration"]["status"] == "fail"
    assert checks["database"]["status"] == "not_checked"
    assert statements == []
    assert str(tmp_path) not in response.text
    assert settings.database_url not in response.text


def test_storage_probe_does_not_create_missing_directory(tmp_path):
    storage = tmp_path / "not-provisioned"
    result = readiness.check_storage_readiness(str(storage))
    assert result.status == "fail"
    assert result.codes == ["artifact_storage_not_provisioned"]
    assert not storage.exists()


def test_storage_permission_failure_is_safe(monkeypatch, tmp_path):
    monkeypatch.setattr(readiness.os, "access", lambda *args: False)
    result = readiness.check_storage_readiness(str(tmp_path))
    assert result.codes == ["artifact_storage_not_accessible"]
    assert str(tmp_path) not in result.model_dump_json()


@pytest.mark.asyncio
async def test_unreachable_database_returns_safe_error_without_credentials(tmp_path):
    nonexistent = tmp_path / "missing-parent" / "database.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{nonexistent}")
    try:
        result = await readiness.check_database_readiness(engine)
    finally:
        await engine.dispose()
    assert result["database"].codes == ["database_unavailable"]
    assert str(nonexistent) not in str(result)
    assert not nonexistent.parent.exists()


@pytest.mark.asyncio
async def test_slow_database_probe_is_bounded(monkeypatch, empty_engine):
    class SlowConnection:
        async def __aenter__(self):
            await asyncio.sleep(60)

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(AsyncEngine, "connect", lambda self: SlowConnection())
    result = await readiness.check_database_readiness(empty_engine, timeout_seconds=0.01)
    assert result["database"].codes == ["database_readiness_timeout"]


@pytest.mark.asyncio
async def test_missing_migration_bundle_fails_safely(monkeypatch, empty_engine, tmp_path):
    monkeypatch.setattr(readiness, "BACKEND_DIRECTORY", tmp_path / "missing-bundle")
    statements = record_read_statements(empty_engine)
    result = await readiness.check_database_readiness(empty_engine)
    assert result["migrations"].codes == ["migration_bundle_invalid"]
    assert statements == []


@pytest.mark.asyncio
async def test_invalid_database_runtime_returns_safe_readiness_error(monkeypatch, tmp_path):
    def broken_engine_factory(settings):
        raise SQLAlchemyError("driver unavailable: database password=private-value")

    monkeypatch.setattr("app.main.create_database_engine", broken_engine_factory)
    application = create_app(settings=build_settings(tmp_path))
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database"]["codes"] == ["database_runtime_invalid"]
    assert "private-value" not in response.text
    assert "SQLAlchemyError" not in response.text


@pytest.mark.asyncio
async def test_application_owned_lazy_engine_is_disposed_on_shutdown(monkeypatch, tmp_path):
    application_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    dispose_calls = []
    original_dispose = AsyncEngine.dispose

    async def record_dispose(engine, close=True):
        dispose_calls.append(engine)
        await original_dispose(engine, close=close)

    monkeypatch.setattr(AsyncEngine, "dispose", record_dispose)
    monkeypatch.setattr("app.main.create_database_engine", lambda settings: application_engine)
    application = create_app(settings=build_settings(tmp_path))
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            assert (await client.get("/health/ready")).status_code == 503
        assert dispose_calls == []
    assert dispose_calls == [application_engine]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception_type",
    [
        ConnectionRefusedError,
        socket.gaierror,
        InvalidPasswordError,
        InterfaceError,
        InternalClientError,
    ],
)
async def test_native_connection_failure_is_safe_and_read_only(
    exception_type, monkeypatch, empty_engine, tmp_path
):
    class FailedConnection:
        async def __aenter__(self):
            raise exception_type(
                "endpoint=private-host password=private-value document=client-data"
            )

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(AsyncEngine, "connect", lambda self: FailedConnection())
    statements = record_read_statements(empty_engine)
    application = create_app(settings=build_settings(tmp_path), engine=empty_engine)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
    checks = response.json()["checks"]
    assert checks["database"] == {"status": "fail", "codes": ["database_unavailable"]}
    assert checks["migrations"]["status"] == "not_checked"
    assert checks["schema"]["status"] == "not_checked"
    assert statements == []
    for sensitive_value in ("private-host", "private-value", "client-data"):
        assert sensitive_value not in response.text


@pytest.mark.asyncio
async def test_native_failure_after_connection_marks_schema_probe_failed(
    monkeypatch, empty_engine, tmp_path
):
    def failed_schema_probe(*args):
        raise OSError("connection lost: password=private-value")

    monkeypatch.setattr(readiness, "_schema_checks", failed_schema_probe)
    statements = record_read_statements(empty_engine)
    result = await readiness.check_readiness(build_settings(tmp_path), empty_engine)
    assert result.status == "not_ready"
    assert result.checks["database"].status == "pass"
    assert result.checks["migrations"].codes == ["database_schema_probe_failed"]
    assert "private-value" not in result.model_dump_json()
    assert statements == ["SELECT 1"]


@pytest.mark.asyncio
async def test_database_probe_does_not_swallow_cancellation(monkeypatch, empty_engine):
    class CancelledConnection:
        async def __aenter__(self):
            raise asyncio.CancelledError()

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(AsyncEngine, "connect", lambda self: CancelledConnection())
    statements = record_read_statements(empty_engine)
    with pytest.raises(asyncio.CancelledError):
        await readiness.check_database_readiness(empty_engine)
    assert statements == []
