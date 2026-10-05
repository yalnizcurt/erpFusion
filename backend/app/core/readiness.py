"""Bounded readiness checks that never modify database or storage state."""

import asyncio
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from asyncpg import (  # type: ignore[import-untyped]
    InterfaceError,
    InternalClientError,
    PostgresError,
)
from pydantic import BaseModel, Field
from sqlalchemy import Connection, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.database import create_session_factory
from app.models import Base
from app.security.tenant_context import assert_runtime_role
from app.services.artifact_storage import ArtifactStorageError, assert_private_s3_bucket

BACKEND_DIRECTORY = Path(__file__).resolve().parents[2]
READINESS_TIMEOUT_SECONDS = 5.0


class ReadinessCheck(BaseModel):
    """Public operational result; no exception, secret, path, or client content."""

    status: Literal["pass", "fail", "not_checked"]
    codes: list[str] = Field(default_factory=list)


class ReadinessReport(BaseModel):
    status: Literal["ready", "not_ready"]
    service: str = "erpfusion-backend"
    checks: dict[str, ReadinessCheck]


def required_migration_heads() -> frozenset[str]:
    """Read checked-in migration metadata without executing its environment."""
    configuration = Config()
    configuration.set_main_option("script_location", str(BACKEND_DIRECTORY / "alembic"))
    return frozenset(ScriptDirectory.from_config(configuration).get_heads())


def _schema_checks(
    connection: Connection,
    required_heads: frozenset[str],
    required_columns: Mapping[str, frozenset[str]],
) -> dict[str, ReadinessCheck]:
    """Inspect migration heads and required tables/columns using read statements."""
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    if "alembic_version" not in table_names:
        return {
            "migrations": ReadinessCheck(status="fail", codes=["migration_version_missing"]),
            "schema": ReadinessCheck(status="not_checked"),
        }
    current_heads = frozenset(MigrationContext.configure(connection).get_current_heads())
    if current_heads != required_heads:
        return {
            "migrations": ReadinessCheck(status="fail", codes=["migration_version_mismatch"]),
            "schema": ReadinessCheck(status="not_checked"),
        }

    schema_codes = []
    if not set(required_columns).issubset(table_names):
        schema_codes.append("required_tables_missing")
    for table_name, column_names in required_columns.items():
        if table_name not in table_names:
            continue
        actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
        if not column_names.issubset(actual_columns):
            schema_codes.append("required_columns_missing")
            break
    return {
        "migrations": ReadinessCheck(status="pass"),
        "schema": ReadinessCheck(status="fail" if schema_codes else "pass", codes=schema_codes),
    }


async def check_database_readiness(
    engine: AsyncEngine,
    *,
    timeout_seconds: float = READINESS_TIMEOUT_SECONDS,
) -> dict[str, ReadinessCheck]:
    """Verify connectivity and checked-in schema compatibility without repairing it."""
    try:
        expected_heads = required_migration_heads()
    except Exception:
        # A missing migration bundle is an application packaging error. Never
        # expose its filesystem location or arbitrary exception text publicly.
        return {
            "database": ReadinessCheck(status="not_checked"),
            "migrations": ReadinessCheck(status="fail", codes=["migration_bundle_invalid"]),
            "schema": ReadinessCheck(status="not_checked"),
        }
    if not expected_heads:
        return {
            "database": ReadinessCheck(status="not_checked"),
            "migrations": ReadinessCheck(status="fail", codes=["migration_bundle_invalid"]),
            "schema": ReadinessCheck(status="not_checked"),
        }
    required_columns = {
        table.name: frozenset(column.name for column in table.columns)
        for table in Base.metadata.sorted_tables
    }
    database_connected = False
    try:
        async with asyncio.timeout(timeout_seconds):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
                database_connected = True
                schema_results = await connection.run_sync(
                    _schema_checks, expected_heads, required_columns
                )
        return {"database": ReadinessCheck(status="pass"), **schema_results}
    except TimeoutError:
        code = "database_readiness_timeout"
    except (SQLAlchemyError, OSError, PostgresError, InterfaceError, InternalClientError):
        # Drivers can raise native connection/DNS/TLS/authentication errors
        # before SQLAlchemy wraps them. Catch these operational failures only;
        # cancellation and unrelated programming errors must still propagate.
        code = "database_schema_probe_failed" if database_connected else "database_unavailable"
    return {
        "database": ReadinessCheck(
            status="pass" if database_connected else "fail",
            codes=[] if database_connected else [code],
        ),
        "migrations": ReadinessCheck(
            status="fail" if database_connected else "not_checked",
            codes=[code] if database_connected else [],
        ),
        "schema": ReadinessCheck(status="not_checked"),
    }


def check_storage_readiness(storage_path: str) -> ReadinessCheck:
    """Check already-provisioned local storage without creating paths or probe files."""
    try:
        directory = Path(storage_path)
        if not directory.is_dir():
            return ReadinessCheck(status="fail", codes=["artifact_storage_not_provisioned"])
        if not os.access(directory, os.R_OK | os.W_OK | os.X_OK):
            return ReadinessCheck(status="fail", codes=["artifact_storage_not_accessible"])
    except (OSError, ValueError):
        return ReadinessCheck(status="fail", codes=["artifact_storage_not_accessible"])
    return ReadinessCheck(status="pass")


async def check_readiness(
    settings: Settings,
    engine: AsyncEngine | None,
) -> ReadinessReport:
    issues = settings.configuration_issues()
    checks = {
        "configuration": ReadinessCheck(status="fail" if issues else "pass", codes=list(issues)),
        "storage": await check_configured_storage_readiness(settings),
    }
    if issues or engine is None:
        checks.update(
            {
                "database": ReadinessCheck(status="not_checked"),
                "migrations": ReadinessCheck(status="not_checked"),
                "schema": ReadinessCheck(status="not_checked"),
            }
        )
    else:
        checks.update(await check_database_readiness(engine))
        if settings.is_production and checks["database"].status == "pass":
            try:
                async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
                    async with create_session_factory(engine)() as session:
                        await assert_runtime_role(session)
            except (RuntimeError, SQLAlchemyError, OSError, PostgresError, TimeoutError):
                checks["database_role"] = ReadinessCheck(
                    status="fail", codes=["database_role_isolation_required"]
                )
            else:
                checks["database_role"] = ReadinessCheck(status="pass")
    status: Literal["ready", "not_ready"] = (
        "ready" if all(check.status == "pass" for check in checks.values()) else "not_ready"
    )
    return ReadinessReport(status=status, checks=checks)


async def check_configured_storage_readiness(settings: Settings) -> ReadinessCheck:
    """Inspect the selected storage without creating local paths or S3 objects."""
    if settings.artifact_storage_backend == "local":
        return check_storage_readiness(settings.artifact_storage_path)
    if not settings.artifact_s3_bucket.strip() or not settings.aws_region.strip():
        return ReadinessCheck(status="fail", codes=["artifact_storage_configuration_required"])
    try:
        async with asyncio.timeout(10):
            await asyncio.to_thread(assert_private_s3_bucket, settings)
    except ArtifactStorageError as exc:
        return ReadinessCheck(status="fail", codes=[str(exc)])
    except TimeoutError:
        return ReadinessCheck(status="fail", codes=["artifact_storage_readiness_timeout"])
    return ReadinessCheck(status="pass")
