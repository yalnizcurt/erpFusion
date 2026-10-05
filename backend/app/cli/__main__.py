"""Development maintenance commands, invoked with ``python -m app.cli``.

Fixture loading never creates tables. Schema initialization is a separate,
explicit development command. Production schema changes use Alembic directly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text

from app.config import Settings, get_settings
from app.services.erp_registry import load_development_fixtures, read_fixture_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Explicit HighStudio development maintenance")
    commands = parser.add_subparsers(dest="command", required=True)
    seed = commands.add_parser(
        "seed", help="Load missing fixtures into an already migrated database"
    )
    seed.add_argument("--manifest", default="development-v1")
    seed.add_argument("--include-sample-projects", action="store_true")
    initialize = commands.add_parser(
        "development-init", help="Explicitly initialize a development schema"
    )
    initialize.add_argument(
        "--legacy-sqlite",
        action="store_true",
        help="Opt in to additive compatibility upgrades for an unversioned SQLite prototype",
    )
    return parser


def require_development(settings: Settings) -> None:
    if not settings.is_development:
        raise ValueError("This command requires APP_ENV=development")


async def seed_database(
    settings: Settings, *, manifest_name: str, include_sample_projects: bool
) -> dict[str, Any]:
    require_development(settings)
    manifest = read_fixture_manifest(manifest_name)
    from app.database import create_database_engine, create_session_factory

    engine = create_database_engine(settings)
    try:
        factory = create_session_factory(engine)
        async with factory() as session, session.begin():
            report = await load_development_fixtures(
                session,
                manifest=manifest,
                app_env=settings.app_env,
                include_sample_projects=include_sample_projects,
            )
            return report.model_dump()
    finally:
        await engine.dispose()


async def _upgrade_legacy_sqlite(settings: Settings) -> None:
    """Add missing local columns/tables without guessing ownership or changing lifecycle."""
    require_development(settings)
    if not settings.database_url.startswith("sqlite+aiosqlite:"):
        raise ValueError("--legacy-sqlite requires a SQLite development database")
    from app.database import create_database_engine
    from app.dev_sqlite_migrations import migrate_legacy_sqlite
    from app.models import Base

    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
            if "alembic_version" in tables:
                raise ValueError("This database is versioned; use Alembic upgrade head")
            if "projects" not in tables:
                raise ValueError(
                    "No prototype schema found; omit --legacy-sqlite for a fresh database"
                )
            await connection.run_sync(migrate_legacy_sqlite)
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(migrate_legacy_sqlite)
            # Verify the ORM can read the upgraded schema. This deliberately
            # does not claim or stamp an Alembic revision for a legacy database.
            await connection.execute(
                text("SELECT requirement_version, schema_context_version FROM projects LIMIT 1")
            )
    finally:
        await engine.dispose()


def initialize_development_database(settings: Settings, *, legacy_sqlite: bool) -> dict[str, str]:
    require_development(settings)
    if legacy_sqlite:
        asyncio.run(_upgrade_legacy_sqlite(settings))
        return {"schema": "legacy-development-compatibility", "fixtures": "not-loaded"}
    from alembic.config import Config

    from alembic import command

    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.attributes["database_url"] = settings.database_url
    config.set_main_option("path_separator", "os")
    command.upgrade(config, "head")
    return {"schema": "alembic-head", "fixtures": "not-loaded"}


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        settings = get_settings()
        require_development(settings)
        if arguments.command == "seed":
            result = asyncio.run(
                seed_database(
                    settings,
                    manifest_name=arguments.manifest,
                    include_sample_projects=arguments.include_sample_projects,
                )
            )
        else:
            result = initialize_development_database(
                settings, legacy_sqlite=arguments.legacy_sqlite
            )
        print(json.dumps(result, sort_keys=True))
        return 0
    except ValueError:
        print(
            "Development command rejected: check the environment, manifest, "
            "and schema prerequisites.",
            file=sys.stderr,
        )
        return 2
    except Exception:
        # Exception text can contain a database URL, bound document content,
        # or credentials. Operators diagnose connection/configuration locally.
        print(
            "Development command failed; no success was recorded. "
            "Check schema and connection configuration.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
