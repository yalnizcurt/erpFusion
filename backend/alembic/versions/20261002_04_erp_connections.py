"""Secret reference metadata, version-bound probes, and client-scoped RLS."""

import sqlalchemy as sa

from alembic import op

revision = "20261002_04"
down_revision = "20261002_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "erp_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_id", sa.String(36), nullable=False),
        sa.Column("installation_id", sa.String(36), nullable=False),
        sa.Column("environment_id", sa.String(36), nullable=False),
        sa.Column("adapter", sa.String(64), nullable=False),
        sa.Column("source_url", sa.String(1024), nullable=False),
        sa.Column("expected_tenant", sa.String(255), nullable=False),
        sa.Column("approved_hosts", sa.JSON, nullable=False),
        sa.Column("report_path", sa.String(1024), nullable=False),
        sa.Column("permitted_operations", sa.JSON, nullable=False),
        sa.Column("configuration_version", sa.Integer, nullable=False),
        sa.Column("secret_ref", sa.String(2048)),
        sa.Column("secret_version", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("environment_id", name="uq_connection_environment"),
        sa.UniqueConstraint("id", "client_id", name="uq_connection_id_client"),
        sa.ForeignKeyConstraint(
            ["environment_id", "client_id"],
            ["erp_environments.id", "erp_environments.client_id"],
            name="fk_connection_environment_client",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_erp_connections_client_id", "erp_connections", ["client_id"])
    op.create_table(
        "connection_verifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_id", sa.String(36), nullable=False),
        sa.Column("connection_id", sa.String(36), nullable=False),
        sa.Column("actor_subject_id", sa.String(255), nullable=False),
        sa.Column("configuration_version", sa.Integer, nullable=False),
        sa.Column("secret_version", sa.String(128)),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("checks", sa.JSON, nullable=False),
        sa.Column("diagnostic_code", sa.String(80), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id", "client_id"],
            ["erp_connections.id", "erp_connections.client_id"],
            name="fk_verification_connection_client",
            ondelete="CASCADE",
        ),
    )
    for column in ("client_id", "connection_id"):
        op.create_index(
            f"ix_connection_verifications_{column}", "connection_verifications", [column]
        )
    if op.get_bind().dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_connection_environment_installation_client",
            "erp_connections",
            "erp_environments",
            ["environment_id", "installation_id", "client_id"],
            ["id", "installation_id", "client_id"],
            ondelete="CASCADE",
        )
        visible = (
            "COALESCE(current_setting('app.platform_admin', true), '') = 'true' OR "
            "COALESCE(NULLIF(current_setting('app.client_ids', true), ''), '[]')::jsonb ? client_id"
        )
        manage = (
            "COALESCE(current_setting('app.platform_admin', true), '') = 'true' OR "
            "COALESCE(NULLIF(current_setting('app.client_admin_ids', true), ''), '[]')::jsonb "
            "? client_id"
        )
        probe = (
            f"({manage}) OR EXISTS (SELECT 1 FROM client_memberships m "
            "WHERE m.client_id = connection_verifications.client_id "
            "AND m.subject_id = NULLIF(current_setting('app.subject_id', true), '') "
            "AND m.status = 'ACTIVE' AND m.role = 'TESTER')"
        )
        probe = (
            f"({probe}) AND ("
            "COALESCE(current_setting('app.platform_admin', true), '') = 'true' OR "
            "actor_subject_id = NULLIF(current_setting('app.subject_id', true), ''))"
        )
        for table, write in (("erp_connections", manage), ("connection_verifications", probe)):
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            op.execute(f'CREATE POLICY tenant_select ON "{table}" FOR SELECT USING ({visible})')
            op.execute(f'CREATE POLICY tenant_insert ON "{table}" FOR INSERT WITH CHECK ({write})')
            # Probe records are immutable for runtime roles, including client admins.
            if table == "erp_connections":
                op.execute(
                    f'CREATE POLICY tenant_update ON "{table}" FOR UPDATE '
                    f"USING ({write}) WITH CHECK ({write})"
                )


def downgrade() -> None:
    op.drop_table("connection_verifications")
    op.drop_table("erp_connections")
