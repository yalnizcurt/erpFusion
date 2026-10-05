"""Versioned integration patterns; nullable bindings preserve historical requests."""

import sqlalchemy as sa

from alembic import op

revision = "20261005_02"
down_revision = "20261005_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_patterns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "erp_profile_id", sa.String(36), sa.ForeignKey("erp_profiles.id"), nullable=False
        ),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(2000), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("erp_profile_id", "key", name="uq_product_pattern"),
    )
    op.create_index(
        "ix_integration_patterns_erp_profile_id", "integration_patterns", ["erp_profile_id"]
    )
    op.create_table(
        "integration_pattern_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "pattern_id", sa.String(36), sa.ForeignKey("integration_patterns.id"), nullable=False
        ),
        sa.Column(
            "profile_version_id",
            sa.String(36),
            sa.ForeignKey("erp_profile_versions.id"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("runtime_type", sa.String(32), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("deliverable_type", sa.String(80), nullable=False),
        sa.Column("qualification_strategy", sa.String(32), nullable=False),
        sa.Column("delivery_method", sa.String(80), nullable=False),
        sa.Column("configuration", sa.JSON, nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("pattern_id", "version", name="uq_pattern_version"),
    )
    op.create_index(
        "ix_integration_pattern_versions_pattern_id", "integration_pattern_versions", ["pattern_id"]
    )
    op.create_table(
        "pattern_baselines",
        sa.Column(
            "pattern_version_id",
            sa.String(36),
            sa.ForeignKey("integration_pattern_versions.id"),
            primary_key=True,
        ),
        sa.Column(
            "asset_version_id",
            sa.String(36),
            sa.ForeignKey("erp_asset_versions.id"),
            primary_key=True,
        ),
    )
    for table in ("projects", "package_candidates", "execution_attempts"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("integration_pattern_version_id", sa.String(36)))
            batch.create_foreign_key(
                f"fk_{table}_pattern_version",
                "integration_pattern_versions",
                ["integration_pattern_version_id"],
                ["id"],
            )
    op.create_index(
        "ix_projects_integration_pattern_version_id", "projects", ["integration_pattern_version_id"]
    )
    if op.get_bind().dialect.name == "postgresql":
        read = (
            "COALESCE(current_setting('app.platform_admin', true), '') = 'true' OR "
            "COALESCE(current_setting('app.erp_admin', true), '') = 'true'"
        )
        for table in ("integration_patterns", "integration_pattern_versions", "pattern_baselines"):
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            if table == "integration_patterns":
                visible = "true"
                editable = "true"
            elif table == "integration_pattern_versions":
                visible = (
                    f"status = 'PUBLISHED' OR ({read}) OR EXISTS (SELECT 1 FROM projects p "
                    "WHERE p.integration_pattern_version_id = integration_pattern_versions.id)"
                )
                editable = "status IN ('DRAFT', 'REVIEW')"
            else:
                visible = (
                    "EXISTS (SELECT 1 FROM integration_pattern_versions v "
                    "WHERE v.id = pattern_version_id)"
                )
                editable = (
                    "EXISTS (SELECT 1 FROM integration_pattern_versions v "
                    "WHERE v.id = pattern_version_id AND v.status IN ('DRAFT', 'REVIEW'))"
                )
            op.execute(f'CREATE POLICY pattern_read ON "{table}" FOR SELECT USING ({visible})')
            op.execute(
                f'CREATE POLICY pattern_insert ON "{table}" FOR INSERT '
                f"WITH CHECK (({read}) AND ({editable}))"
            )
            update_allowed = "true" if table == "integration_pattern_versions" else editable
            update_destination = "true" if table == "integration_pattern_versions" else editable
            op.execute(
                f'CREATE POLICY pattern_update ON "{table}" FOR UPDATE '
                f"USING (({read}) AND ({update_allowed})) "
                f"WITH CHECK (({read}) AND ({update_destination}))"
            )
            if table == "pattern_baselines":
                op.execute(
                    f'CREATE POLICY pattern_delete ON "{table}" FOR DELETE '
                    f"USING (({read}) AND ({editable}))"
                )
        registry_event = (
            f"client_id IS NULL AND ({read}) AND "
            "entity_type IN ('IntegrationPattern', 'IntegrationPatternVersion')"
        )
        op.execute(
            "CREATE POLICY pattern_audit_read ON admin_audit_events FOR SELECT "
            f"USING ({registry_event})"
        )
        op.execute(
            "CREATE POLICY pattern_audit_insert ON admin_audit_events FOR INSERT "
            f"WITH CHECK ({registry_event})"
        )
        op.execute("""
            CREATE FUNCTION preserve_pattern_version() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF OLD.status IN ('PUBLISHED', 'RETIRED') AND (
                (to_jsonb(NEW) - 'status' - 'updated_at') IS DISTINCT FROM
                (to_jsonb(OLD) - 'status' - 'updated_at') OR
                NEW.status NOT IN (OLD.status, 'RETIRED')) THEN
                RAISE EXCEPTION 'Published pattern contracts are immutable';
              END IF;
              RETURN NEW;
            END $$;
            CREATE TRIGGER immutable_pattern_version BEFORE UPDATE ON integration_pattern_versions
              FOR EACH ROW EXECUTE FUNCTION preserve_pattern_version();
        """)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY pattern_audit_read ON admin_audit_events")
        op.execute("DROP POLICY pattern_audit_insert ON admin_audit_events")
        op.execute("DROP TRIGGER immutable_pattern_version ON integration_pattern_versions")
        op.execute("DROP FUNCTION preserve_pattern_version()")
    op.drop_index("ix_projects_integration_pattern_version_id", "projects")
    for table in ("execution_attempts", "package_candidates", "projects"):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"fk_{table}_pattern_version", type_="foreignkey")
            batch.drop_column("integration_pattern_version_id")
    for table in ("pattern_baselines", "integration_pattern_versions", "integration_patterns"):
        op.drop_table(table)
