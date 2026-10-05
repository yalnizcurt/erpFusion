"""Persistent intake/history, durable generation and immutable sandbox packages."""

import sqlalchemy as sa

from alembic import op

revision = "20261002_03"
down_revision = "20261002_02"
branch_labels = None
depends_on = None

_TABLES = (
    "project_input_revisions",
    "requirement_documents",
    "package_candidates",
    "sandbox_evidence",
    "package_releases",
)


def _flag(name):
    return f"COALESCE(current_setting('app.{name}', true), '') = 'true'"


def _access(table):
    client = f"{table}.client_id"
    membership = (
        f"COALESCE(NULLIF(current_setting('app.client_ids', true), ''), '[]')::jsonb ? {client}"
    )
    return (
        f"(({client} IS NOT NULL AND ({_flag('platform_admin')} OR {membership})) OR "
        f"({client} IS NULL AND {_flag('allow_unowned_legacy')}))"
    )


def _project_scope(table):
    return (
        f"EXISTS (SELECT 1 FROM projects p WHERE p.id = {table}.project_id "
        f"AND p.client_id IS NOT DISTINCT FROM {table}.client_id)"
    )


def _candidate_scope(table):
    return (
        f"EXISTS (SELECT 1 FROM package_candidates c WHERE c.id = {table}.candidate_id "
        f"AND c.project_id = {table}.project_id "
        f"AND c.client_id IS NOT DISTINCT FROM {table}.client_id)"
    )


def _tester_or_client_admin(table, actor_column):
    subject = "NULLIF(current_setting('app.subject_id', true), '')"
    membership = (
        f"EXISTS (SELECT 1 FROM client_memberships m WHERE m.client_id = {table}.client_id "
        f"AND m.subject_id = {subject} AND m.status = 'ACTIVE' "
        "AND m.role IN ('TESTER', 'CLIENT_ADMIN'))"
    )
    return f"{table}.{actor_column} = {subject} AND ({_flag('platform_admin')} OR {membership})"


def _columns():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("client_id", sa.String(36), sa.ForeignKey("clients.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade():
    for column in (
        sa.Column("project_type", sa.String(16), nullable=False, server_default="CUSTOM"),
        sa.Column("due_date", sa.Date()),
        sa.Column("workflow_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("workflow_status", sa.String(32), nullable=False, server_default="DRAFT"),
    ):
        op.add_column("projects", column)
    op.add_column(
        "projects", sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE projects SET last_activity_at = COALESCE(updated_at, CURRENT_TIMESTAMP) "
        "WHERE last_activity_at IS NULL"
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("projects") as batch:
            batch.alter_column(
                "last_activity_at",
                existing_type=sa.DateTime(timezone=True),
                nullable=False,
            )
    else:
        op.alter_column(
            "projects",
            "last_activity_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
    for column in (
        sa.Column("actor_subject_id", sa.String(36), sa.ForeignKey("identity_subjects.id")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("artifact_version_id", sa.String(36)),
        sa.Column("output_content", sa.JSON()),
    ):
        # SQLite cannot add a FK inline; identity binding is checked by commands.
        if op.get_bind().dialect.name == "sqlite" and column.name == "actor_subject_id":
            column = sa.Column("actor_subject_id", sa.String(36))
        op.add_column("generation_runs", column)
    op.create_index(
        "ix_generation_runs_status_created", "generation_runs", ["status", "created_at"]
    )
    op.create_table(
        "project_input_revisions",
        *_columns(),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_by_subject_id", sa.String(36), sa.ForeignKey("identity_subjects.id")),
        sa.UniqueConstraint("project_id", "revision", name="uq_project_input_revision"),
    )
    op.create_table(
        "requirement_documents",
        *_columns(),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.String(1024), nullable=False),
        sa.Column("extraction_status", sa.String(24), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("extraction_error", sa.String(80)),
        sa.Column("scan_status", sa.String(24), nullable=False, server_default="NOT_CONFIGURED"),
        sa.Column("requirement_version", sa.Integer(), nullable=False),
        sa.Column("created_by_subject_id", sa.String(36), sa.ForeignKey("identity_subjects.id")),
    )
    op.create_table(
        "package_candidates",
        *_columns(),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("storage_path", sa.String(1024), nullable=False),
        sa.UniqueConstraint("project_id", "checksum", name="uq_project_package_checksum"),
    )
    op.create_table(
        "sandbox_evidence",
        *_columns(),
        sa.Column(
            "candidate_id", sa.String(36), sa.ForeignKey("package_candidates.id"), nullable=False
        ),
        sa.Column(
            "environment_id", sa.String(36), sa.ForeignKey("erp_environments.id"), nullable=False
        ),
        sa.Column("candidate_checksum", sa.String(64), nullable=False),
        sa.Column("connection_version", sa.Integer()),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("method", sa.String(40), nullable=False),
        sa.Column("observations", sa.JSON(), nullable=False),
        sa.Column("tester_subject_id", sa.String(36), sa.ForeignKey("identity_subjects.id")),
    )
    op.create_table(
        "package_releases",
        *_columns(),
        sa.Column(
            "candidate_id", sa.String(36), sa.ForeignKey("package_candidates.id"), nullable=False
        ),
        sa.Column(
            "evidence_id", sa.String(36), sa.ForeignKey("sandbox_evidence.id"), nullable=False
        ),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("storage_path", sa.String(1024), nullable=False),
        sa.Column("approved_by_subject_id", sa.String(36), sa.ForeignKey("identity_subjects.id")),
        sa.UniqueConstraint("candidate_id", "evidence_id", name="uq_package_release_evidence"),
    )
    for table in _TABLES:
        op.create_index(f"ix_{table}_project_id", table, ["project_id"])
        op.create_index(f"ix_{table}_client_id", table, ["client_id"])
    if op.get_bind().dialect.name == "postgresql":
        for table in _TABLES:
            op.create_foreign_key(
                f"fk_{table}_project_client",
                table,
                "projects",
                ["project_id", "client_id"],
                ["id", "client_id"],
            )
        op.create_unique_constraint(
            "uq_candidate_tenant", "package_candidates", ["id", "project_id", "client_id"]
        )
        op.create_unique_constraint(
            "uq_evidence_tenant",
            "sandbox_evidence",
            ["id", "candidate_id", "project_id", "client_id"],
        )
        for table in ("sandbox_evidence", "package_releases"):
            op.create_foreign_key(
                f"fk_{table}_candidate_tenant",
                table,
                "package_candidates",
                ["candidate_id", "project_id", "client_id"],
                ["id", "project_id", "client_id"],
            )
        op.create_foreign_key(
            "fk_evidence_environment_tenant",
            "sandbox_evidence",
            "erp_environments",
            ["environment_id", "client_id"],
            ["id", "client_id"],
        )
        op.create_foreign_key(
            "fk_release_evidence_tenant",
            "package_releases",
            "sandbox_evidence",
            ["evidence_id", "candidate_id", "project_id", "client_id"],
            ["id", "candidate_id", "project_id", "client_id"],
        )
        read_scopes = {
            "project_input_revisions": _project_scope("project_input_revisions"),
            "requirement_documents": _project_scope("requirement_documents"),
            "package_candidates": _project_scope("package_candidates"),
            "sandbox_evidence": _candidate_scope("sandbox_evidence"),
            "package_releases": _candidate_scope("package_releases"),
        }
        insert_scopes = {
            table: f"{_access(table)} AND {scope}" for table, scope in read_scopes.items()
        }
        subject = "NULLIF(current_setting('app.subject_id', true), '')"
        for table in ("project_input_revisions", "requirement_documents"):
            insert_scopes[table] += f" AND {table}.created_by_subject_id = {subject}"
        insert_scopes["sandbox_evidence"] += (
            f" AND {_tester_or_client_admin('sandbox_evidence', 'tester_subject_id')}"
        )
        insert_scopes["package_releases"] += (
            f" AND {_tester_or_client_admin('package_releases', 'approved_by_subject_id')}"
        )
        for table, scope in read_scopes.items():
            select_scope = f"{_access(table)} AND {scope}"
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            op.execute(
                f'CREATE POLICY tenant_select ON "{table}" FOR SELECT USING ({select_scope})'
            )
            op.execute(
                f'CREATE POLICY tenant_insert ON "{table}" FOR INSERT '
                f"WITH CHECK ({insert_scopes[table]})"
            )


def downgrade():
    for table in reversed(_TABLES):
        op.drop_table(table)
    op.drop_index("ix_generation_runs_status_created", "generation_runs")
    for column in (
        "output_content",
        "artifact_version_id",
        "error_code",
        "completed_at",
        "started_at",
        "actor_subject_id",
    ):
        op.drop_column("generation_runs", column)
    for column in (
        "workflow_status",
        "workflow_revision",
        "last_activity_at",
        "due_date",
        "project_type",
    ):
        op.drop_column("projects", column)
