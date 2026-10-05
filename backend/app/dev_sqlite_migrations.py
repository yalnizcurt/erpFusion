"""Additive compatibility migration for legacy SQLite development databases.

Production schema changes are owned by Alembic. Older local prototype databases
were created with ``create_all`` and have no Alembic revision table. The explicit
``development-init --legacy-sqlite`` command adds compatible columns while
preserving lifecycle and exact bindings. Startup never invokes this helper.
"""

from uuid import uuid4

from sqlalchemy import inspect
from sqlalchemy.engine import Connection

_COLUMNS = {
    "erp_profiles": {
        "display_name": "VARCHAR(255) NOT NULL DEFAULT ''",
        "status": "VARCHAR(24) NOT NULL DEFAULT 'DRAFT'",
        "created_by": "VARCHAR(255) NOT NULL DEFAULT 'system'",
        "updated_by": "VARCHAR(255) NOT NULL DEFAULT 'system'",
    },
    "erp_stage_prompts": {
        "profile_version_id": "VARCHAR(36)",
        "name": "VARCHAR(255) NOT NULL DEFAULT 'Stage prompt'",
        "scope": "VARCHAR(16) NOT NULL DEFAULT 'ERP'",
        "status": "VARCHAR(24) NOT NULL DEFAULT 'PUBLISHED'",
        "variables": "JSON NOT NULL DEFAULT '[]'",
        "created_by": "VARCHAR(255) NOT NULL DEFAULT 'system'",
        "updated_by": "VARCHAR(255) NOT NULL DEFAULT 'system'",
    },
    "projects": {
        "erp_profile_id": "VARCHAR(36)",
        "erp_profile_version_id": "VARCHAR(36)",
        "requirement_version": "INTEGER NOT NULL DEFAULT 1",
        "schema_context_version": "INTEGER NOT NULL DEFAULT 1",
    },
    "artifact_versions": {"generation_run_id": "VARCHAR(36)"},
}


def migrate_legacy_sqlite(connection: Connection) -> None:
    """Bring an existing local SQLite prototype schema forward without dropping data."""
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    for table, columns in _COLUMNS.items():
        if table not in tables:
            continue
        current = {column["name"] for column in inspector.get_columns(table)}
        for name, definition in columns.items():
            if name not in current:
                connection.exec_driver_sql(
                    f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}'
                )

    if "erp_profiles" in tables:
        connection.exec_driver_sql(
            "UPDATE erp_profiles SET display_name = name WHERE display_name = ''"
        )
    if {"projects", "erp_profiles", "erp_profile_versions"}.issubset(tables):
        connection.exec_driver_sql("""
            UPDATE projects SET erp_profile_id = (
                SELECT erp_profile_versions.profile_id FROM erp_profile_versions
                WHERE erp_profile_versions.id = projects.erp_profile_version_id
            ) WHERE erp_profile_id IS NULL AND erp_profile_version_id IS NOT NULL
        """)
    if {"erp_stage_prompts", "erp_profile_versions", "prompt_versions"}.issubset(tables):
        rows = list(
            connection.exec_driver_sql("""
            SELECT p.id, p.profile_id, p.profile_version_id, p.stage, p.version, p.system_prompt,
                   p.status, p.created_at, p.updated_at
            FROM erp_stage_prompts p
            WHERE p.profile_version_id IS NOT NULL
        """).mappings()
        )
        for row in rows:
            exists = connection.exec_driver_sql(
                "SELECT 1 FROM prompt_versions WHERE scope = 'STAGE' "
                "AND profile_version_id = ? AND name = ? AND version = ? LIMIT 1",
                (row["profile_version_id"], f"{row['stage']} instructions", row["version"]),
            ).first()
            if exists:
                continue
            connection.exec_driver_sql(
                """
                INSERT INTO prompt_versions
                    (id, scope, profile_version_id, name, stage, content, version,
                     status, variables,
                     created_by, updated_by, created_at, updated_at)
                VALUES (?, 'STAGE', ?, ?, ?, ?, ?, ?, '[]', 'migration', 'migration', ?, ?)
            """,
                (
                    str(uuid4()),
                    row["profile_version_id"],
                    f"{row['stage']} instructions",
                    row["stage"],
                    row["system_prompt"],
                    row["version"],
                    row["status"],
                    row["created_at"],
                    row["updated_at"],
                ),
            )
