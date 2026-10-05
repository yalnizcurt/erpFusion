"""Explicit cloud administration: schema upgrade, restricted runtime role, first admin.

Executed only by the private CodeBuild administration project. Database passwords
come from Secrets Manager and never enter a build argument, source archive or log.
"""

import asyncio
import json
import os
import ssl
import tempfile
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

import asyncpg
import boto3
from alembic import command
from alembic.config import Config
from app.cli.bootstrap_identity import bootstrap
from app.config import Settings
from app.database import create_database_engine, create_session_factory
from app.models import PlatformRoleAssignment
from app.security.tenant_context import apply_tenant_context, assert_runtime_role
from botocore.config import Config as AWSConfig
from sqlalchemy import func, select


def database_url(host: str, name: str, credentials: dict[str, str]) -> str:
    if not host or any(char in host for char in "/@?#:"):
        raise ValueError("A database hostname is required")
    if not name.isidentifier():
        raise ValueError("A database name is required")
    return (
        f"postgresql+asyncpg://{quote(credentials['username'], safe='')}:"
        f"{quote(credentials['password'], safe='')}@{host}:5432/{name}"
    )


async def provision_runtime(
    host: str,
    name: str,
    owner: dict[str, str],
    runtime: dict[str, str],
    certificate: str,
) -> None:
    if runtime["username"] != "erpfusion_runtime":
        raise ValueError("Unexpected runtime role")
    connection = await asyncpg.connect(
        host=host,
        database=name,
        user=owner["username"],
        password=owner["password"],
        ssl=ssl.create_default_context(cafile=certificate),
        timeout=15,
    )
    try:
        async with connection.transaction():
            await connection.execute("""
                DO $$ BEGIN
                  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erpfusion_runtime') THEN
                    CREATE ROLE erpfusion_runtime;
                  END IF;
                END $$
            """)
            # PostgreSQL performs literal quoting, including special password characters.
            role_command = await connection.fetchval(
                "SELECT format('ALTER ROLE erpfusion_runtime LOGIN NOSUPERUSER "
                "NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD %L', $1::text)",
                runtime["password"],
            )
            await connection.execute(role_command)
            await connection.execute(
                f'GRANT CONNECT ON DATABASE "{name}" TO erpfusion_runtime'
            )
            await connection.execute(
                "GRANT USAGE ON SCHEMA public TO erpfusion_runtime"
            )
            await connection.execute(
                "GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO erpfusion_runtime"
            )
            await connection.execute(
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO erpfusion_runtime"
            )
            await connection.execute(
                "REVOKE INSERT, UPDATE ON alembic_version FROM erpfusion_runtime"
            )
            await connection.execute(
                "REVOKE UPDATE ON audit_entries, admin_audit_events FROM erpfusion_runtime"
            )
    finally:
        await connection.close()


async def ensure_first_admin(settings: Settings, subject: str) -> None:
    engine = create_database_engine(settings)
    try:
        factory = create_session_factory(engine)
        async with factory() as db:
            await apply_tenant_context(db, client_ids=[], is_platform_admin=True)
            existing = await db.scalar(
                select(func.count())
                .select_from(PlatformRoleAssignment)
                .where(
                    PlatformRoleAssignment.role == "PLATFORM_ADMIN",
                    PlatformRoleAssignment.status == "ACTIVE",
                )
            )
    finally:
        await engine.dispose()
    if not existing:
        await bootstrap(settings, issuer=settings.oidc_issuer, subject=subject)


async def verify_runtime(settings: Settings) -> None:
    engine = create_database_engine(settings)
    try:
        async with create_session_factory(engine)() as db:
            await assert_runtime_role(db)
    finally:
        await engine.dispose()


def main() -> int:
    stage = "configuration"
    try:
        secrets = boto3.client(
            "secretsmanager",
            region_name=os.environ["AWS_DEFAULT_REGION"],
            config=AWSConfig(
                connect_timeout=5, read_timeout=10, retries={"max_attempts": 2}
            ),
        )
        master = json.loads(
            secrets.get_secret_value(SecretId=os.environ["MASTER_SECRET_ARN"])[
                "SecretString"
            ]
        )
        runtime = json.loads(
            secrets.get_secret_value(SecretId=os.environ["RUNTIME_SECRET_ARN"])[
                "SecretString"
            ]
        )
        host, name = os.environ["DB_HOST"], os.environ.get("DB_NAME", "erpfusion")
        owner_url = database_url(host, name, master)
        runtime_url = database_url(host, name, runtime)
        with tempfile.TemporaryDirectory() as directory:
            certificate = Path(directory) / "rds-ca-bundle.pem"
            with urlopen(
                "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem",
                timeout=15,
            ) as response:
                certificate.write_bytes(response.read(1024 * 1024))
            os.environ["DATABASE_URL"] = owner_url
            os.environ["MIGRATION_DATABASE_URL"] = owner_url
            os.environ["DATABASE_SSL_CA_FILE"] = str(certificate)
            stage = "schema migrations"
            config = Config("backend/alembic.ini")
            config.set_main_option("script_location", "backend/alembic")
            config.attributes["database_url"] = owner_url
            command.upgrade(config, "head")
            stage = "runtime role provisioning"
            asyncio.run(
                provision_runtime(host, name, master, runtime, str(certificate))
            )
            settings = Settings(
                _env_file=None,
                app_env="staging",
                auth_mode="oidc",
                database_url=owner_url,
                database_ssl_ca_file=str(certificate),
                oidc_issuer=os.environ["OIDC_ISSUER"],
                oidc_audience=os.environ["OIDC_AUDIENCE"],
                oidc_jwks_url=os.environ["OIDC_ISSUER"] + "/.well-known/jwks.json",
                oidc_audience_claim="client_id",
                oidc_token_use="access",
            )
            stage = "first administrator bootstrap"
            asyncio.run(ensure_first_admin(settings, os.environ["ADMIN_SUBJECT"]))
            stage = "restricted runtime verification"
            asyncio.run(
                verify_runtime(
                    settings.model_copy(update={"database_url": runtime_url})
                )
            )
            stage = "runtime secret publication"
            runtime["database_url"] = runtime_url
            secrets.put_secret_value(
                SecretId=os.environ["RUNTIME_SECRET_ARN"],
                SecretString=json.dumps(runtime),
            )
        print("Cloud schema, restricted runtime role, and administrator are ready.")
        return 0
    except Exception:
        # Driver/SDK exceptions can contain credentials or SQL-bound values.
        print(f"Cloud administration failed during {stage}; no success was recorded.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
