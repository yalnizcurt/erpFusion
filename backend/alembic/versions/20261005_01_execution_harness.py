"""Add execution control plane; existing environments remain unverified."""

import sqlalchemy as sa

from alembic import op

revision = "20261005_01"
down_revision = "20261002_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "erp_environments",
        sa.Column("custody", sa.String(32), nullable=False, server_default="UNVERIFIED"),
    )
    op.add_column(
        "erp_environments",
        sa.Column("execution_mode", sa.String(24), nullable=False, server_default="ASSISTED"),
    )
    op.add_column(
        "erp_connections",
        sa.Column("vendor_configuration", sa.JSON, nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_table(
        "capability_qualifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_id", sa.String(36), nullable=False),
        sa.Column("environment_id", sa.String(36), nullable=False),
        sa.Column("adapter", sa.String(64), nullable=False),
        sa.Column("adapter_version", sa.String(32), nullable=False),
        sa.Column("binding", sa.JSON, nullable=False),
        sa.Column("capabilities", sa.JSON, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column(
            "approved_by_subject_id",
            sa.String(36),
            sa.ForeignKey("identity_subjects.id"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", "client_id", name="uq_qualification_client"),
        sa.ForeignKeyConstraint(
            ["environment_id", "client_id"], ["erp_environments.id", "erp_environments.client_id"]
        ),
    )
    columns = [sa.Column("id", sa.String(36), primary_key=True)]
    for name, length in {
        "client_id": 36,
        "project_id": 36,
        "candidate_id": 36,
        "candidate_checksum": 64,
        "environment_id": 36,
        "qualification_id": 36,
        "adapter": 64,
        "adapter_version": 32,
        "operation": 64,
        "status": 32,
        "idempotency_key": 128,
        "requested_by_subject_id": 36,
        "verdict": 24,
    }.items():
        columns.append(sa.Column(name, sa.String(length), nullable=False))
    for name, length in {
        "connection_id": 36,
        "approved_by_subject_id": 36,
        "external_execution_id": 255,
    }.items():
        columns.append(sa.Column(name, sa.String(length)))
    for name in ("binding", "request", "result", "failure", "assurance"):
        columns.append(sa.Column(name, sa.JSON, nullable=False))
    columns.append(sa.Column("retry_count", sa.Integer, nullable=False))
    for name in ("approval_expires_at", "deadline_at", "started_at", "completed_at", "created_at"):
        columns.append(sa.Column(name, sa.DateTime(timezone=True), nullable=name != "created_at"))
    op.create_table(
        "execution_attempts",
        *columns,
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_execution_idempotency"),
        sa.UniqueConstraint("id", "client_id", name="uq_execution_client"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["candidate_id"], ["package_candidates.id"]),
        sa.ForeignKeyConstraint(["connection_id"], ["erp_connections.id"]),
        sa.ForeignKeyConstraint(["requested_by_subject_id"], ["identity_subjects.id"]),
        sa.ForeignKeyConstraint(["approved_by_subject_id"], ["identity_subjects.id"]),
        sa.ForeignKeyConstraint(
            ["environment_id", "client_id"], ["erp_environments.id", "erp_environments.client_id"]
        ),
        sa.ForeignKeyConstraint(
            ["qualification_id", "client_id"],
            ["capability_qualifications.id", "capability_qualifications.client_id"],
        ),
    )
    op.create_table(
        "simulated_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_id", sa.String(36), nullable=False),
        sa.Column("attempt_id", sa.String(36), nullable=False),
        sa.Column("environment_id", sa.String(36), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("adapter_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("history", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("attempt_id", name="uq_simulated_attempt"),
        sa.ForeignKeyConstraint(
            ["attempt_id", "client_id"], ["execution_attempts.id", "execution_attempts.client_id"]
        ),
    )
    for table, names in {
        "capability_qualifications": ("client_id", "environment_id"),
        "execution_attempts": ("client_id", "project_id", "environment_id", "status"),
        "simulated_artifacts": ("client_id",),
    }.items():
        for name in names:
            op.create_index(f"ix_{table}_{name}", table, [name])
    with op.batch_alter_table("sandbox_evidence") as batch:
        batch.add_column(sa.Column("execution_attempt_id", sa.String(36)))
        batch.create_foreign_key(
            "fk_evidence_execution_attempt", "execution_attempts", ["execution_attempt_id"], ["id"]
        )
    if op.get_bind().dialect.name == "postgresql":
        for table, remote, local, foreign in (
            ("execution_attempts", "projects", ["project_id", "client_id"], ["id", "client_id"]),
            (
                "execution_attempts",
                "package_candidates",
                ["candidate_id", "project_id", "client_id"],
                ["id", "project_id", "client_id"],
            ),
            (
                "execution_attempts",
                "erp_connections",
                ["connection_id", "client_id"],
                ["id", "client_id"],
            ),
            (
                "sandbox_evidence",
                "execution_attempts",
                ["execution_attempt_id", "client_id"],
                ["id", "client_id"],
            ),
        ):
            op.create_foreign_key(f"fk_{table}_{remote}_ownership", table, remote, local, foreign)
        visible = (
            "COALESCE(current_setting('app.platform_admin', true), '') = 'true' OR "
            "COALESCE(NULLIF(current_setting('app.client_ids', true), ''), '[]')::jsonb ? client_id"
        )
        manage = (
            "COALESCE(current_setting('app.platform_admin', true), '') = 'true' OR "
            "COALESCE(NULLIF(current_setting('app.client_admin_ids', true), ''), '[]')::jsonb ? "
            "client_id"
        )
        worker = "COALESCE(current_setting('app.execution_worker', true), '') = 'true'"
        for table in ("capability_qualifications", "execution_attempts", "simulated_artifacts"):
            tester = (
                "EXISTS (SELECT 1 FROM client_memberships m "
                f"WHERE m.client_id = {table}.client_id "
                "AND m.subject_id = NULLIF(current_setting('app.subject_id', true), '') "
                "AND m.status = 'ACTIVE' AND m.role = 'TESTER')"
            )
            write = (
                manage
                if table == "capability_qualifications"
                else f"({visible}) AND (({manage}) OR ({tester}) OR ({worker}))"
            )
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            op.execute(f'CREATE POLICY tenant_select ON "{table}" FOR SELECT USING ({visible})')
            op.execute(f'CREATE POLICY tenant_insert ON "{table}" FOR INSERT WITH CHECK ({write})')
            op.execute(
                f'CREATE POLICY tenant_update ON "{table}" FOR UPDATE '
                f"USING ({write}) WITH CHECK ({write})"
            )
        # Workers persist machine evidence; HTTP callers cannot set this context.
        op.execute(
            "CREATE POLICY execution_evidence_insert ON sandbox_evidence FOR INSERT "
            f"WITH CHECK (({visible}) AND ({worker}) AND execution_attempt_id IS NOT NULL)"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY execution_evidence_insert ON sandbox_evidence")
        op.drop_constraint(
            "fk_sandbox_evidence_execution_attempts_ownership",
            "sandbox_evidence",
            type_="foreignkey",
        )
    with op.batch_alter_table("sandbox_evidence") as batch:
        batch.drop_constraint("fk_evidence_execution_attempt", type_="foreignkey")
        batch.drop_column("execution_attempt_id")
    for table in ("simulated_artifacts", "execution_attempts", "capability_qualifications"):
        op.drop_table(table)
    op.drop_column("erp_connections", "vendor_configuration")
    op.drop_column("erp_environments", "execution_mode")
    op.drop_column("erp_environments", "custody")
